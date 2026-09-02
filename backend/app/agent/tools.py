"""Tools the agent may call.

Each function is a thin wrapper over the existing Layer 0 service layer —
none of them run a raw query. All prices in and out are integer paise. Every
function returns plain, JSON-serializable data, never prose: the model reads
these as tool results, not as something to paraphrase blindly.

These functions are also the *execution* step the harness calls once the
policy engine has said ALLOW — the LLM only ever proposes a call by name; it
never runs one directly.
"""

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.repositories import cart_repo
from app.schemas.cart import CartItemCreate
from app.services import cart_service, product_service


def search_products(
    db: Session, query: str = "", max_price_paise: int | None = None, category: str | None = None
) -> dict:
    result = product_service.list_products(
        db,
        category=category,
        search=query or None,
        min_price_paise=None,
        max_price_paise=max_price_paise,
        page=1,
        page_size=20,
    )
    return {
        "total": result.total,
        "items": [
            {
                "sku": p.sku,
                "name": p.name,
                "brand": p.brand,
                "category": p.category,
                "price_paise": p.price_paise,
                "price_display": p.price_display,
                "stock": p.stock,
            }
            for p in result.items
        ],
    }


def get_product(db: Session, sku: str) -> dict:
    try:
        product = product_service.get_product_by_sku(db, sku)
    except HTTPException:
        return {"error": f"SKU '{sku}' was not found in the catalog."}
    return {
        "sku": product.sku,
        "name": product.name,
        "brand": product.brand,
        "category": product.category,
        "price_paise": product.price_paise,
        "price_display": product.price_display,
        "stock": product.stock,
        "description": product.description,
    }


def add_to_cart(db: Session, user_id: str, sku: str, quantity: int = 1) -> dict:
    cart = cart_service.add_item(db, user_id, CartItemCreate(sku=sku, quantity=quantity))
    return cart.model_dump(mode="json")


def view_cart(db: Session, user_id: str) -> dict:
    cart = cart_service.get_cart(db, user_id)
    return cart.model_dump(mode="json")


def remove_from_cart(db: Session, user_id: str, sku: str) -> dict:
    cart = cart_repo.get_or_create_active_cart(db, user_id)
    match = next((item for item in cart.items if item.product.sku == sku), None)
    if match is None:
        return {"error": f"'{sku}' is not in the cart."}
    updated = cart_service.delete_item(db, user_id, match.id)
    return updated.model_dump(mode="json")


# Uniform dispatch signature: fn(db, user_id, **arguments) -> dict.
# search_products/get_product ignore user_id but accept it for a uniform call site.
TOOL_FUNCTIONS = {
    "search_products": lambda db, user_id, **kw: search_products(db, **kw),
    "get_product": lambda db, user_id, **kw: get_product(db, **kw),
    "add_to_cart": lambda db, user_id, **kw: add_to_cart(db, user_id, **kw),
    "view_cart": lambda db, user_id, **kw: view_cart(db, user_id),
    "remove_from_cart": lambda db, user_id, **kw: remove_from_cart(db, user_id, **kw),
}

TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "search_products",
            "description": "Search the product catalog by name/tag text, optionally filtered by "
            "category and a maximum price. Returns matching products with prices in paise "
            "(integer, 100 paise = 1 rupee).",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search text, matched against product name and tags."},
                    "max_price_paise": {
                        "type": "integer",
                        "description": "Optional maximum price in paise (e.g. ₹800 = 80000).",
                    },
                    "category": {
                        "type": "string",
                        "description": "Optional exact category, e.g. 'pet_supplies', 'groceries'.",
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_product",
            "description": "Look up a single product by its exact SKU.",
            "parameters": {
                "type": "object",
                "properties": {"sku": {"type": "string", "description": "The product SKU, e.g. 'PET-001'."}},
                "required": ["sku"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "add_to_cart",
            "description": "Propose adding a product to the cart. This does not execute immediately — "
            "it is checked against budget, stock, and catalog rules before anything happens.",
            "parameters": {
                "type": "object",
                "properties": {
                    "sku": {"type": "string", "description": "The exact SKU of the product to add."},
                    "quantity": {"type": "integer", "description": "How many units to add. Defaults to 1."},
                },
                "required": ["sku"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "view_cart",
            "description": "View the current cart contents and total (in paise).",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "remove_from_cart",
            "description": "Remove a product from the cart by SKU.",
            "parameters": {
                "type": "object",
                "properties": {"sku": {"type": "string", "description": "The SKU to remove from the cart."}},
                "required": ["sku"],
            },
        },
    },
]
