"""Product view logging — must be cheap and, critically, must never break
browsing even when the write itself fails.
"""

from unittest.mock import patch

from app.campaigns.models import ProductView
from app.campaigns.service import log_product_view


def test_view_is_logged(db_session):
    log_product_view(db_session, user_id="user_demo", sku="PET-001", session_id="sess-1", request_id="req-1")

    rows = db_session.query(ProductView).all()
    assert len(rows) == 1
    assert rows[0].user_id == "user_demo"
    assert rows[0].sku == "PET-001"
    assert rows[0].session_id == "sess-1"


def test_a_failed_write_does_not_raise(db_session):
    """The whole point of this function: a DB failure while logging a view
    must never propagate — it would otherwise turn "someone looked at a
    product" into a broken page."""
    with patch.object(db_session, "commit", side_effect=RuntimeError("db is down")):
        log_product_view(db_session, user_id="user_demo", sku="PET-001", session_id=None, request_id=None)
    # No exception raised is the assertion — reaching this line is the pass.


def test_view_logging_survives_an_unknown_sku(db_session):
    """No catalog lookup happens here on purpose (see module docstring) —
    an invalid SKU is just data, not an error."""
    log_product_view(db_session, user_id="user_demo", sku="DOES-NOT-EXIST", session_id=None, request_id=None)
    rows = db_session.query(ProductView).all()
    assert len(rows) == 1
    assert rows[0].sku == "DOES-NOT-EXIST"
