from dataclasses import dataclass
from enum import Enum


class Decision(str, Enum):
    ALLOW = "ALLOW"
    DENY = "DENY"
    REQUIRE_CONFIRMATION = "REQUIRE_CONFIRMATION"


@dataclass(frozen=True)
class CatalogProductSnapshot:
    """What the policy engine is allowed to know about a product.

    Deliberately not the SQLAlchemy model — rules must stay importable and
    testable with zero DB/ORM dependency.
    """

    sku: str
    price_paise: int
    stock: int


@dataclass(frozen=True)
class CartLineSnapshot:
    """One resolved cart line, for whole-cart actions like payment."""

    product: CatalogProductSnapshot
    quantity: int


@dataclass(frozen=True)
class ProposedCartState:
    """The state a proposed tool call would produce, if executed.

    This is what rules evaluate — never chat text, never the model's own
    claims about price or stock. `product` is resolved from the real catalog
    by the caller (the harness) before evaluation; if it's None, the sku the
    agent referenced does not exist.

    `cart_line_items` and `existing_order_status` are only populated for
    whole-cart actions (currently just `initiate_payment`) — add_to_cart and
    friends leave them None.
    """

    session_id: str
    user_id: str
    tool_name: str
    budget_paise: int | None
    current_cart_total_paise: int
    sku: str | None = None
    quantity: int | None = None
    product: CatalogProductSnapshot | None = None
    cart_line_items: tuple[CartLineSnapshot, ...] | None = None
    existing_order_status: str | None = None

    @property
    def line_total_paise(self) -> int | None:
        if self.product is None or self.quantity is None:
            return None
        return self.product.price_paise * self.quantity

    @property
    def proposed_cart_total_paise(self) -> int:
        return self.current_cart_total_paise + (self.line_total_paise or 0)


@dataclass(frozen=True)
class RuleResult:
    decision: Decision
    rule_name: str
    reason: str
