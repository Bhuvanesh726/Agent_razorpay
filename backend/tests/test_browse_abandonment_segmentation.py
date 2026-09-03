"""Segmentation for browse_abandonment, on a fixed, hand-built fixture —
no generator, no randomness. Complements test_campaign_segmentation-style
coverage of the other five segments (those live inline in
test_campaign_integration.py via the real generator; this one gets its own
file since the fixture needs product_views rows the other segments don't).
"""

from datetime import datetime, timedelta, timezone

from app.campaigns.models import Customer, HistoricalOrder, HistoricalOrderItem, ProductView
from app.campaigns.segmentation import compute_browse_abandonment_segment

_AS_OF = datetime(2026, 9, 3, tzinfo=timezone.utc)


def _customer(db, key: str) -> Customer:
    c = Customer(customer_key=key, name=key, email=f"{key.lower()}@example.test")
    db.add(c)
    db.flush()
    return c


def _view(db, customer: Customer, sku: str, days_ago: float) -> None:
    db.add(ProductView(user_id=customer.customer_key, sku=sku, session_id=None, viewed_at=_AS_OF - timedelta(days=days_ago), request_id=None))


def _order(db, customer: Customer, sku: str, days_ago: float, price_paise: int = 10_000) -> None:
    order = HistoricalOrder(customer_id=customer.id, placed_at=_AS_OF - timedelta(days=days_ago), total_paise=price_paise)
    db.add(order)
    db.flush()
    db.add(HistoricalOrderItem(order_id=order.id, sku=sku, category="groceries", quantity=1, unit_price_paise=price_paise))


def test_repeat_view_no_purchase_qualifies(db_session):
    c = _customer(db_session, "CUST-A")
    for d in (1, 2, 3):
        _view(db_session, c, "SKU-1", d)
    db_session.commit()

    seg = compute_browse_abandonment_segment(db_session, _AS_OF, min_views=3, window_days=7)

    assert seg.size == 1
    assert seg.members[0].customer_key == "CUST-A"
    assert seg.members[0].target_sku == "SKU-1"


def test_viewed_then_purchased_is_excluded(db_session):
    c = _customer(db_session, "CUST-B")
    for d in (1, 2, 3, 4):
        _view(db_session, c, "SKU-1", d)
    _order(db_session, c, "SKU-1", days_ago=0.5)
    db_session.commit()

    seg = compute_browse_abandonment_segment(db_session, _AS_OF, min_views=3, window_days=7)

    assert seg.size == 0


def test_below_view_threshold_is_excluded(db_session):
    c = _customer(db_session, "CUST-C")
    _view(db_session, c, "SKU-1", 1)
    _view(db_session, c, "SKU-1", 2)  # only 2 views, threshold is 3
    db_session.commit()

    seg = compute_browse_abandonment_segment(db_session, _AS_OF, min_views=3, window_days=7)

    assert seg.size == 0


def test_views_outside_window_are_excluded(db_session):
    c = _customer(db_session, "CUST-D")
    for d in (10, 12, 15):  # all older than the 7-day window
        _view(db_session, c, "SKU-1", d)
    db_session.commit()

    seg = compute_browse_abandonment_segment(db_session, _AS_OF, min_views=3, window_days=7)

    assert seg.size == 0


def test_multiple_qualifying_skus_picks_the_most_viewed_one(db_session):
    c = _customer(db_session, "CUST-E")
    for d in (1, 2, 3):
        _view(db_session, c, "SKU-1", d)
    for d in (1, 2, 3, 4, 5):
        _view(db_session, c, "SKU-2", d)
    db_session.commit()

    seg = compute_browse_abandonment_segment(db_session, _AS_OF, min_views=3, window_days=7)

    assert seg.size == 1  # one row per customer, not one per qualifying SKU
    assert seg.members[0].target_sku == "SKU-2"  # the more-viewed of the two


def test_unrelated_user_id_is_ignored(db_session):
    """Real-shop views (user_id="user_demo") never match a synthetic
    Customer.customer_key, so they're silently ignored here rather than
    crashing or being miscounted."""
    db_session.add(ProductView(user_id="user_demo", sku="SKU-1", session_id="s1", viewed_at=_AS_OF - timedelta(days=1), request_id=None))
    db_session.add(ProductView(user_id="user_demo", sku="SKU-1", session_id="s1", viewed_at=_AS_OF - timedelta(days=2), request_id=None))
    db_session.add(ProductView(user_id="user_demo", sku="SKU-1", session_id="s1", viewed_at=_AS_OF - timedelta(days=3), request_id=None))
    db_session.commit()

    seg = compute_browse_abandonment_segment(db_session, _AS_OF, min_views=3, window_days=7)

    assert seg.size == 0
