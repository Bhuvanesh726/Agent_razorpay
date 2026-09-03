"""Dev-only bootstrap for an EXTERNAL-mode agent credential.

In the real product, a buyer creates a Mode B (external) credential by
logging in with Google, opening the agent-management UI, and copying the
raw key shown exactly once at creation (see docs/047-principals.md). This
script exists only because that flow needs a browser and a Google account,
neither of which this headless demo repo can drive on its own — it performs
the identical database write the /api/agents endpoint would (same table,
same delivery_mode="EXTERNAL", same one-time key), just from a script
instead of a click, so buyer_agent/ has something real to authenticate with
during local development.

Run from the backend/ directory, with the server not necessarily running
(this talks to the DB directly, not over HTTP):

    python scripts/create_agent_credential.py
    python scripts/create_agent_credential.py --spend-limit-paise 500000

The printed key is shown ONCE, exactly like the real endpoint — save it
(e.g. into an AGENT_API_KEY environment variable) before closing the
terminal; it is hashed at rest and cannot be recovered afterward.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.auth.security import generate_agent_key, hash_agent_key  # noqa: E402
from app.core.config import settings  # noqa: E402
from app.database import Base, SessionLocal, engine  # noqa: E402
from app.models.agent_credential import AgentCredential  # noqa: E402
from app.models.user import User  # noqa: E402

# Everything buyer_agent/buyer.py's shopping + checkout flow calls through
# /api/agent/chat. Deliberately excludes report_content_gap (buyer_agent
# never triggers it).
DEFAULT_SCOPES = [
    "search_products",
    "get_product",
    "add_to_cart",
    "view_cart",
    "remove_from_cart",
    "initiate_payment",
    "decline_upsell",
]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--owner-user-id", default=settings.default_user_id)
    parser.add_argument("--name", default="buyer_agent (external)")
    parser.add_argument("--scopes", default=",".join(DEFAULT_SCOPES), help="Comma-separated tool scopes.")
    parser.add_argument(
        "--spend-limit-paise",
        type=int,
        default=1_000_000,
        help="₹10,000 default — comfortably above buyer_agent's two demo scenarios combined, "
        "since AgentSpendLimitRule tracks cumulative spend across every run of this credential.",
    )
    args = parser.parse_args()

    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        owner = db.get(User, args.owner_user_id)
        if owner is None:
            print(f"No user '{args.owner_user_id}' — run scripts/seed.py first.", file=sys.stderr)
            return 1

        raw_key = generate_agent_key()
        cred = AgentCredential(
            owner_user_id=owner.id,
            name=args.name,
            key_hash=hash_agent_key(raw_key),
            delivery_mode="EXTERNAL",
            scopes=[s.strip() for s in args.scopes.split(",") if s.strip()],
            spend_limit_paise=args.spend_limit_paise,
        )
        owner_id = owner.id
        db.add(cred)
        db.commit()
        db.refresh(cred)
    finally:
        db.close()

    print(f"Created EXTERNAL agent credential '{cred.id}' for owner '{owner_id}'.")
    print(f"Scopes: {', '.join(cred.scopes)}")
    print(f"Spend limit: {'{:,}'.format(cred.spend_limit_paise)} paise")
    print()
    print("Raw key (shown exactly once — save it now):")
    print(f"  {raw_key}")
    print()
    print("Usage:")
    print(f"  export AGENT_API_KEY={raw_key}")
    print("  python buyer_agent/buyer.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
