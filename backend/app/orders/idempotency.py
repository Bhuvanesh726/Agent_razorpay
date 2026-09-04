"""Deterministic idempotency key derivation.

Same (user_id, cart contents, amount_paise) always produces the same key —
by design, not by luck. This is what makes "insert, and on conflict return
the existing row" a correct de-duplication strategy: a retry of the exact
same intent can only ever collide with itself.

Deliberately NOT random (no UUID, no timestamp) — a random key would defeat
the entire point: two requests for the same purchase would get different
keys and both would be allowed through.

`cart_id` is part of the key, and is what separates "a retry" from "another
purchase". Paying marks the cart checked_out and opens a fresh one
(order service, `_reset_cart_after_payment`), so re-ordering the identical
basket later happens on a *different* cart row and correctly gets its own
order. Retrying payment on the *same* unpaid cart keeps the same id and
still collapses into one order, which is the case this exists for.

This was originally keyed on content + amount alone, on the reasoning that a
successful payment empties the cart so a new purchase would have different
contents. That reasoning was wrong: a fresh cart refilled with the same items
has identical contents, so buying the same weekly basket twice produced the
same key and the second attempt was rejected with "this exact cart has
already been paid for" — permanently. See Failures.md.
"""

import hashlib
import json


def compute_idempotency_key(
    user_id: str, line_items: list[tuple[str, int, int]], amount_paise: int, cart_id: int | None = None
) -> str:
    """line_items: list of (sku, quantity, unit_price_paise).

    cart_id is optional only so the pure-function tests can omit it; every
    real caller passes one.
    """
    canonical = {
        "user_id": user_id,
        "cart_id": cart_id,
        "items": sorted(
            [{"sku": sku, "quantity": qty, "unit_price_paise": price} for sku, qty, price in line_items],
            key=lambda x: x["sku"],
        ),
        "amount_paise": amount_paise,
    }
    encoded = json.dumps(canonical, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()
