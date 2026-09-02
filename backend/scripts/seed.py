"""Idempotent product seed script: loads backend/data/products.json and
upserts each row by sku, so re-running never duplicates products.

Run from the backend/ directory:
    python scripts/seed.py
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database import Base, SessionLocal, engine  # noqa: E402
from app.repositories import product_repo  # noqa: E402

DATA_FILE = Path(__file__).resolve().parents[1] / "data" / "products.json"


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
                    "unit": entry["unit"],
                    "stock": entry["stock"],
                    "description": entry["description"],
                    "tags": entry["tags"],
                },
            )
        db.commit()
        print(f"Seeded {len(products)} products from {DATA_FILE.name} (upsert on sku).")
    finally:
        db.close()


if __name__ == "__main__":
    main()
