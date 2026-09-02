"""Deterministic idempotency key derivation.

Same (user_id, cart contents, amount_paise) always produces the same key —
by design, not by luck. This is what makes "insert, and on conflict return
the existing row" a correct de-duplication strategy: a retry of the exact
same intent can only ever collide with itself.

Deliberately NOT random (no UUID, no timestamp) — a random key would defeat
the entire point: two requests for the same purchase would get different
keys and both would be allowed through.

Known tradeoff: because the key is pure content + amount, buying the exact
same cart twice in two unrelated sessions produces the same key. This is
fine here because a successful payment resets the cart (see order service),
so a *new* purchase always starts from a fresh, empty cart and therefore
different contents. Two genuinely concurrent attempts at the *same* unpaid
cart are exactly the case this is supposed to collapse into one order.
"""

import hashlib
import json


def compute_idempotency_key(
    user_id: str, line_items: list[tuple[str, int, int]], amount_paise: int
) -> str:
    """line_items: list of (sku, quantity, unit_price_paise)."""
    canonical = {
        "user_id": user_id,
        "items": sorted(
            [{"sku": sku, "quantity": qty, "unit_price_paise": price} for sku, qty, price in line_items],
            key=lambda x: x["sku"],
        ),
        "amount_paise": amount_paise,
    }
    encoded = json.dumps(canonical, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()
