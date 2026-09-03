"""Agent-readable catalog: discovery doc + paginated feed. Router functions
are called directly (same pattern as the rest of this suite) rather than
through a TestClient, since none of this depends on HTTP framing.
"""

from app.repositories import product_repo
from app.services import catalog_service


def seed_two_products(db):
    product_repo.upsert(
        db,
        {
            "sku": "PET-001",
            "name": "Pedigree Adult Dry Dog Food",
            "brand": "Pedigree",
            "category": "pet_supplies",
            "price_paise": 74000,
            "unit": "3kg pack",
            "stock": 25,
            "description": "dog food",
            "tags": ["dog"],
        },
    )
    product_repo.upsert(
        db,
        {
            "sku": "GRO-004",
            "name": "Tata Salt",
            "brand": "Tata",
            "category": "groceries",
            "price_paise": 2800,
            "unit": "1kg",
            "stock": 0,  # deliberately out of stock, to prove availability tracks it
            "description": "salt",
            "tags": [],
        },
    )
    db.commit()


def test_discovery_doc_has_currency_and_transact_endpoints():
    doc = catalog_service.build_discovery_doc("http://testserver")
    assert doc["merchant"]["currency"] == "INR"
    assert doc["merchant"]["environment"] == "test"
    assert doc["endpoints"]["chat"] == "http://testserver/api/agent/chat"
    assert doc["endpoints"]["catalog_feed"] == "http://testserver/api/catalog/feed"
    # the dev-only test-complete endpoint is deliberately NOT advertised here
    # (see docs/045-catalog.md) — it's this project's own headless-testing
    # shortcut, not a capability a real external integrator should rely on.
    assert "test-complete" not in str(doc)


def test_feed_prices_are_integer_paise_with_explicit_currency(db_session):
    seed_two_products(db_session)
    page = catalog_service.build_feed(db_session, page=1, page_size=50)
    item = next(i for i in page.body.items if i.sku == "PET-001")
    assert item.price_paise == 74000
    assert isinstance(item.price_paise, int)
    assert item.currency == "INR"


def test_feed_availability_reflects_stock(db_session):
    seed_two_products(db_session)
    page = catalog_service.build_feed(db_session, page=1, page_size=50)
    by_sku = {i.sku: i for i in page.body.items}
    assert by_sku["PET-001"].availability == "in_stock"
    assert by_sku["GRO-004"].availability == "out_of_stock"


def test_feed_pagination(db_session):
    seed_two_products(db_session)
    page = catalog_service.build_feed(db_session, page=1, page_size=1)
    assert len(page.body.items) == 1
    assert page.body.total == 2
    assert page.body.page == 1
    assert page.body.page_size == 1


def test_feed_etag_is_stable_for_identical_content(db_session):
    seed_two_products(db_session)
    first = catalog_service.build_feed(db_session, page=1, page_size=50)
    second = catalog_service.build_feed(db_session, page=1, page_size=50)
    assert first.etag == second.etag

    # changing the catalog changes the etag
    product = product_repo.get_by_sku(db_session, "PET-001")
    product.price_paise = 70000
    db_session.commit()
    third = catalog_service.build_feed(db_session, page=1, page_size=50)
    assert third.etag != first.etag
