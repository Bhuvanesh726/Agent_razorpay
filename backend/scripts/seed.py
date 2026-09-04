"""Idempotent product seed script: loads backend/data/products.json and
upserts each row by sku, so re-running never duplicates products.

Run from the backend/ directory:
    python scripts/seed.py
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import settings  # noqa: E402
from app.database import Base, SessionLocal, engine, ensure_schema  # noqa: E402
from app.models.user import User  # noqa: E402
from app.repositories import product_repo  # noqa: E402
from app.testing.demo_login import demo_login_available, ensure_demo_environment  # noqa: E402

DATA_FILE = Path(__file__).resolve().parents[1] / "data" / "products.json"


def _seed_demo_user(db) -> None:
    """id="user_demo" — the exact literal every Cart/Order/AgentSession row
    from Layers 0-4.6 already uses as its user_id, so this one row is what
    keeps all of that pre-Layer-4.7 data owned by a real User instead of
    orphaned (see docs/047-principals.md)."""
    existing = db.get(User, settings.default_user_id)
    if existing is not None:
        return
    db.add(
        User(
            id=settings.default_user_id,
            email="demo-buyer@example.test",
            name="Demo Buyer",
            google_sub=None,
            role="BUYER",
        )
    )


def main() -> None:
    Base.metadata.create_all(bind=engine)
    ensure_schema()

    catalog = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    products = catalog["products"]

    db = SessionLocal()
    try:
        for entry in products:
            product_repo.upsert(
                db,
                {
                    "sku": entry["sku"],
                    "name": entry["name"],
                    "brand": entry["brand"],
                    "category": entry["category"],
                    "price_paise": entry["price_paise"],
                    "cost_paise": entry["cost_paise"],
                    "unit": entry["unit"],
                    "stock": entry["stock"],
                    "description": entry["description"],
                    "tags": entry["tags"],
                },
            )
        _seed_demo_user(db)
        db.commit()

        # Demo buyer + merchant, with enough history to be worth looking at.
        # Gated exactly like chaos injection: development only, in code. In
        # any other environment this is skipped and the only way in is Google
        # (app/auth/oauth_router.py). See app/testing/demo_login.py.
        demo_seeded = demo_login_available()
        if demo_seeded:
            ensure_demo_environment(db)

        suffix = ", plus the demo user and the development-only demo principals." if demo_seeded else ", plus the demo user."
        print(f"Seeded {len(products)} products from {DATA_FILE.name} (upsert on sku){suffix}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
