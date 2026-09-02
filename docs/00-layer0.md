# Layer 0 — Shopping app foundation

No AI, agent, or LLM code anywhere in this layer. That's Layer 1+.

## What exists

```
/backend
  app/
    core/        config.py (pydantic-settings), logging.py (structured JSON + request_id), money.py
    models/      Product, Cart, CartItem (SQLAlchemy 2.0)
    schemas/     Pydantic response models
    repositories/  DB access only (no business logic)
    services/    business logic only (no DB queries, no HTTP)
    routers/     HTTP only (no DB queries, no business logic)
    database.py  engine/session
    main.py      FastAPI app, middleware, router wiring
  alembic/       migrations
  data/products.json   seed catalog (moved from repo root)
  scripts/seed.py      idempotent seed script
  requirements.txt
/frontend        Next.js App Router + TypeScript + Tailwind
  src/app/page.tsx          the whole UI (client component)
  src/components/           ProductGrid, CategoryTabs, SearchBox, CartSidebar
  src/lib/api.ts, types.ts  typed fetch client
/docs
docker-compose.yml   Postgres for when you're ready to swap off SQLite
.gitignore
```

Routers never touch the DB directly — they call services, which call repositories.
This is what makes it possible to add caching, alternate data sources, or new
business rules later without touching HTTP concerns.

## Database: SQLite now, Postgres-ready

Docker was installed but the daemon wasn't running when this was built, so local
dev uses **SQLite** (`backend/razorpay_agent.db`). The SQLAlchemy models use only
types that exist on both engines (`Integer`, `String`, `Text`, `JSON` — no
Postgres-only `ARRAY`), so switching is a config change, not a rewrite:

1. `docker compose up -d` (starts Postgres from `docker-compose.yml`)
2. In `.env`, uncomment/set:
   `DATABASE_URL=postgresql+psycopg://razorpay:razorpay@localhost:5432/razorpay_agent`
3. `alembic upgrade head`
4. `python scripts/seed.py`

Nothing else changes — no model code, no router code.

## Why money is always paise

`price_paise`, `unit_price_paise` are integers everywhere: models, DB columns,
API payloads. Floats lose precision on money (`0.1 + 0.2 != 0.3` in every
language), and rupee decimals compound that over many line items. Paise avoids
the whole class of bug. The API also returns a formatted `*_display` string
(e.g. `"₹275.00"`) computed at the edge — the frontend never does its own
rupee math, it just renders the string.

## `user_id` on every table

There's no auth yet, so every row gets `user_id="user_demo"` (from
`DEFAULT_USER_ID` in `.env`). This looks unnecessary for a global product
catalog today, but it means Google OAuth (a later layer) is a matter of
reading a real user id out of a session instead of a constant — zero schema
changes, no migration to backfill a column that didn't exist.

## Schema

- **products**: `id, sku (unique), name, brand, category, price_paise, unit, stock, description, tags (JSON array), user_id`
- **carts**: `id, user_id, status, created_at`
- **cart_items**: `id, cart_id, product_id, quantity, unit_price_paise, user_id`

`cart_items.unit_price_paise` is a **snapshot** taken when the item is added —
it does not join to `products.price_paise`. If the catalog price changes
later, carts that already have the item keep the price the shopper saw.

## Port note (Windows-specific)

Port `8000` was already bound by Docker Desktop's background services
(`com.docker.backend.exe` / `wslrelay.exe` were listening on it, likely for
WSL port-forwarding) even though no container was using it. The backend runs
on **`8842`** instead. If you free up 8000 later you can switch back — just
update `NEXT_PUBLIC_API_URL` in `frontend/.env.local` and the `--port` flag
below.

## How to run it (PowerShell)

**Backend:**
```powershell
cd backend
..\venv\Scripts\Activate.ps1
python -m uvicorn app.main:app --host 127.0.0.1 --port 8842 --reload
```

**Seed the database** (safe to re-run — upserts by `sku`, never duplicates):
```powershell
cd backend
..\venv\Scripts\Activate.ps1
python scripts\seed.py
```

**Apply migrations** (only needed after pulling new model changes):
```powershell
cd backend
..\venv\Scripts\Activate.ps1
python -m alembic upgrade head
```

**Frontend:**
```powershell
cd frontend
npm run dev
```

Then open http://localhost:3000. The API runs at http://127.0.0.1:8842 and
its interactive docs are at http://127.0.0.1:8842/docs.

## Endpoints

| Method | Path | Notes |
|---|---|---|
| GET | `/health` | liveness check |
| GET | `/api/products` | `category`, `search`, `min_price_paise`, `max_price_paise`, `page`, `page_size` |
| GET | `/api/products/{sku}` | 404 if unknown sku |
| GET | `/api/categories` | category + product_count |
| POST | `/api/cart/items` | `{sku, quantity}` — merges into existing line if the sku is already in the cart |
| GET | `/api/cart` | items + computed `total_paise` / `total_display` |
| DELETE | `/api/cart/items/{id}` | removes one line |

## Verified working

Backend endpoints smoke-tested via curl (search, category filter, pagination,
cart add/merge/delete, 404s). Frontend driven end-to-end with a headless
browser: all 50 products render, category tabs filter correctly, search
narrows results, add-to-cart updates the sidebar total, zero console errors.
