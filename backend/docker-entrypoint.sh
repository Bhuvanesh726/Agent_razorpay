#!/bin/sh
# Creates the schema and seeds the catalog before the API starts.
#
# scripts/seed.py is idempotent by design: it calls Base.metadata.create_all
# (a no-op once the tables exist) and upserts each product by SKU, so running
# it on every container start is safe and keeps a fresh clone working with a
# single `docker compose up` — no manual migration step for a reviewer.
set -e

echo "[entrypoint] preparing database: ${DATABASE_URL}"
python scripts/seed.py

echo "[entrypoint] starting: $*"
exec "$@"
