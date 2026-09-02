from app.orders.idempotency import compute_idempotency_key


def test_same_cart_hashed_twice_produces_the_same_key():
    items = [("PET-001", 1, 74000), ("GRO-001", 2, 27500)]
    key1 = compute_idempotency_key("user_demo", items, amount_paise=74000 + 2 * 27500)
    key2 = compute_idempotency_key("user_demo", items, amount_paise=74000 + 2 * 27500)
    assert key1 == key2


def test_key_is_order_independent():
    """Same items in a different order must still hash the same — it's the
    same cart, just iterated differently."""
    a = [("PET-001", 1, 74000), ("GRO-001", 2, 27500)]
    b = [("GRO-001", 2, 27500), ("PET-001", 1, 74000)]
    assert compute_idempotency_key("user_demo", a, 129000) == compute_idempotency_key("user_demo", b, 129000)


def test_different_user_produces_different_key():
    items = [("PET-001", 1, 74000)]
    key_a = compute_idempotency_key("user_a", items, 74000)
    key_b = compute_idempotency_key("user_b", items, 74000)
    assert key_a != key_b


def test_different_quantity_produces_different_key():
    key_1 = compute_idempotency_key("user_demo", [("PET-001", 1, 74000)], 74000)
    key_2 = compute_idempotency_key("user_demo", [("PET-001", 2, 74000)], 148000)
    assert key_1 != key_2


def test_different_amount_produces_different_key():
    """Same items, different stated amount (e.g. a price mismatch bug) must
    not silently collapse into the same key — that would hide the bug."""
    items = [("PET-001", 1, 74000)]
    key_1 = compute_idempotency_key("user_demo", items, 74000)
    key_2 = compute_idempotency_key("user_demo", items, 99999)
    assert key_1 != key_2


def test_key_is_a_sha256_hex_digest():
    key = compute_idempotency_key("user_demo", [("PET-001", 1, 74000)], 74000)
    assert len(key) == 64
    assert all(c in "0123456789abcdef" for c in key)
