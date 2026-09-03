"""Agent-readable catalog: the discovery document and the paginated feed.

Both are read-only views over the existing product catalog — no new source
of truth, just a shape aligned to what an external agent would expect
(see docs/045-catalog.md for what that alignment actually means and where
it deviates from ACP/AP2/x402).
"""

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.product import Product
from app.repositories import product_repo
from app.schemas.catalog import CatalogFeedItemOut, CatalogFeedOut
from app.services.pricing import effective_price_paise


def _as_utc(dt: datetime) -> datetime:
    # SQLite round-trips DateTime(timezone=True) as naive — pin to UTC
    # explicitly rather than emit an ambiguous ISO string with no offset.
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def _to_feed_item(p: Product) -> CatalogFeedItemOut:
    return CatalogFeedItemOut(
        id=p.sku,
        sku=p.sku,
        title=p.name,
        description=p.description,
        brand=p.brand,
        category=p.category,
        price_paise=effective_price_paise(p),
        original_price_paise=p.price_paise if p.discount_pct else None,
        discount_pct=p.discount_pct,
        currency=settings.razorpay_currency,
        unit=p.unit,
        availability="in_stock" if p.stock > 0 else "out_of_stock",
        stock=p.stock,
        tags=p.tags,
        updated_at=_as_utc(p.updated_at).isoformat(),
    )


@dataclass
class FeedPage:
    body: CatalogFeedOut
    etag: str
    last_modified: datetime | None


def build_feed(db: Session, *, page: int, page_size: int) -> FeedPage:
    items, total = product_repo.list_products(db, page=page, page_size=page_size)
    feed_items = [_to_feed_item(p) for p in items]

    body = CatalogFeedOut(
        merchant=settings.merchant_display_name,
        currency=settings.razorpay_currency,
        page=page,
        page_size=page_size,
        total=total,
        items=feed_items,
    )

    # Content-derived: identical output always hashes the same, so a
    # consumer's If-None-Match round-trips correctly with zero extra state
    # on our side to track "did anything actually change".
    canonical = json.dumps(body.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    etag = hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    last_modified = max((p.updated_at for p in items), default=None)
    return FeedPage(body=body, etag=etag, last_modified=last_modified)


def build_discovery_doc(base_url: str) -> dict:
    return {
        "protocol_version": "0.1",
        "merchant": {
            "name": settings.merchant_display_name,
            "currency": settings.razorpay_currency,
            "environment": "test",  # Razorpay TEST MODE — never a live charge; see docs/045-catalog.md
        },
        "capabilities": ["catalog_feed", "conversational_checkout", "policy_gated_purchase", "test_mode_payments"],
        "endpoints": {
            "catalog_feed": f"{base_url}/api/catalog/feed",
            "chat": f"{base_url}/api/agent/chat",
            "confirm": f"{base_url}/api/agent/confirm",
            "payment_verify": f"{base_url}/api/payments/verify",
            "audit_trail": f"{base_url}/api/audit/{{session_id}}",
        },
        "how_to_transact": (
            "POST a natural-language purchase intent (with a session_id and, optionally, a "
            "budget_paise spending cap) to `chat`. Every proposed action — adding an item, an "
            "upsell offer, initiating payment — is evaluated by a deterministic policy engine "
            "before it executes; a response with status='awaiting_confirmation' must be "
            "explicitly approved via `confirm` before it proceeds. Payment is Razorpay test "
            "mode: complete Razorpay Checkout with the returned order details, then this "
            "merchant verifies the resulting signature server-side (never the client's say-so) "
            "before an order is marked paid. The full decision trail for any session, including "
            "every policy decision and its reason, is readable at `audit_trail`."
        ),
        "aligned_to": {
            "catalog_price_convention": "UCP (integer minor units, explicit currency field)",
            "catalog_field_names": "ACP product-feed spec, where a field applies (id/title/description/category/availability)",
            "discovery_uri_pattern": "the /.well-known/ convention used by UCP and A2A — not itself part of ACP/AP2/x402",
        },
    }
