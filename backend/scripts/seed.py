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
from app.database import Base, SessionLocal, engine  # noqa: E402
from app.models.user import User  # noqa: E402
from app.repositories import product_repo  # noqa: E402

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
        print(f"Seeded {len(products)} products from {DATA_FILE.name} (upsert on sku), plus the demo user.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
