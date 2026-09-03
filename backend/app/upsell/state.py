"""Session upsell state, derived entirely from the audit log — no new table.

Same philosophy as app/audit/replay.py: the audit trail is the one source
of truth, so anything derivable from it stays derived rather than cached
somewhere that could drift. There is at most one *unresolved* offer per
session at a time (the harness never proposes a second one while one is
outstanding), so "the pending offer" is unambiguous: the most recent
upsell_proposed event not yet superseded by an accept/decline for that SKU.
"""

from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.audit.service import AuditService

_audit = AuditService()


@dataclass(frozen=True)
class UpsellOffer:
    sku: str
    price_paise: int
    reason: str


@dataclass(frozen=True)
class UpsellState:
    proposed_count: int = 0
    declined_skus: frozenset[str] = field(default_factory=frozenset)
    pending: UpsellOffer | None = None
    accepted_count: int = 0
    declined_count: int = 0
    blocked_count: int = 0
    incremental_revenue_paise: int = 0
    # The cart total at the moment the *first* offer was proposed this
    # session — stays fixed across later offers so "% of original cart"
    # means the same thing throughout, even after an accepted upsell has
    # grown the cart.
    original_cart_total_paise: int | None = None


def get_state(db: Session, session_id: str) -> UpsellState:
    events = _audit.get_trail(db, session_id)

    proposed_count = 0
    declined_skus: set[str] = set()
    pending: UpsellOffer | None = None
    accepted_count = 0
    declined_count = 0
    blocked_count = 0
    incremental_revenue_paise = 0
    original_cart_total_paise: int | None = None

    for e in events:
        args = e.tool_args or {}
        if e.event_type == "upsell_proposed":
            proposed_count += 1
            pending = UpsellOffer(sku=args["sku"], price_paise=args["price_paise"], reason=args.get("reason", ""))
            if original_cart_total_paise is None:
                original_cart_total_paise = args.get("cart_total_at_proposal_paise")
        elif e.event_type == "upsell_blocked":
            blocked_count += 1
        elif e.event_type == "upsell_accepted":
            accepted_count += 1
            incremental_revenue_paise += args.get("price_paise", 0) * args.get("quantity", 1)
            pending = None
        elif e.event_type == "upsell_declined":
            declined_count += 1
            if "sku" in args:
                declined_skus.add(args["sku"])
            pending = None

    return UpsellState(
        proposed_count=proposed_count,
        declined_skus=frozenset(declined_skus),
        pending=pending,
        accepted_count=accepted_count,
        declined_count=declined_count,
        blocked_count=blocked_count,
        incremental_revenue_paise=incremental_revenue_paise,
        original_cart_total_paise=original_cart_total_paise,
    )
