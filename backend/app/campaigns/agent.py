"""The one place an LLM touches the campaign feature: given a segment's
name, description, and summary statistics, plus the current catalog,
propose which products to feature, a discount percentage, and a
customer-facing message.

This mirrors Layer 1's whole architecture: the model *proposes* via the
low-level tool-calling gateway (never Agno's Agent.run(), for the same
reason the shopping agent avoids it — an auto-executing loop would bypass
the policy engine entirely). It never decides whether the offer actually
goes out (app/campaigns/rules.py + engine.py do that, per customer) and
never sends anything (service.py drives that loop). Which customers get
considered is decided beforehand and entirely without the model, in
segmentation.py — the model only ever sees a segment's aggregate shape,
never a customer list.
"""

import json
from dataclasses import dataclass

from app.llm.gateway import GatewayError, gateway

SYSTEM_PROMPT = (
    "You are a marketing campaign planner for an online store. You are given one customer "
    "segment - a name, a description, and summary statistics about its members - and a list of "
    "catalog products. Propose ONE campaign by calling propose_campaign: 1-3 SKUs to feature "
    "(ONLY SKUs that literally appear in the catalog list you were given - never invent one), a "
    "discount percentage as a decimal (e.g. 0.15 for 15%, never a value above 1.0), and a short "
    "customer-facing message (under 240 characters). "
    "You are proposing, not deciding - a separate policy system checks your discount against "
    "margin-floor and budget limits before anything is sent, and can reject part or all of it. "
    "Keep the discount modest and proportionate to the segment's value - a deeper discount is not "
    "automatically a better campaign, and an oversized one is simply more likely to be rejected. "
    "Call propose_campaign exactly once."
)

PROPOSE_CAMPAIGN_SCHEMA = [
    {
        "type": "function",
        "function": {
            "name": "propose_campaign",
            "description": "Propose a targeted marketing campaign for the given customer segment.",
            "parameters": {
                "type": "object",
                "properties": {
                    "skus": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "1-3 catalog SKUs to feature, most relevant to this segment first.",
                    },
                    "discount_pct": {
                        "type": "number",
                        "description": "Proposed discount as a decimal, e.g. 0.15 for 15%.",
                    },
                    "message": {
                        "type": "string",
                        "description": "A short (<= 240 character) customer-facing campaign message.",
                    },
                    "rationale": {
                        "type": "string",
                        "description": "One sentence on why this segment and this offer make sense together.",
                    },
                },
                "required": ["skus", "discount_pct", "message", "rationale"],
            },
        },
    }
]


class CampaignProposalError(Exception):
    pass


@dataclass
class CampaignProposal:
    skus: list[str]
    discount_pct: float
    message: str
    rationale: str
    model_used: str
    fallback_used: bool
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    cost_paise: int
    latency_ms: int


def propose_campaign(
    *, segment_name: str, segment_description: str, segment_stats: dict, catalog_summary: list[dict]
) -> CampaignProposal:
    """catalog_summary: [{"sku", "name", "category", "price_paise"}, ...] —
    deliberately never includes cost_paise (see app/models/product.py)."""
    known_skus = {p["sku"] for p in catalog_summary}

    user_content = json.dumps(
        {
            "segment": segment_name,
            "description": segment_description,
            "stats": segment_stats,
            "catalog": catalog_summary,
        }
    )
    messages = [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": user_content}]

    try:
        result = gateway.call(messages, PROPOSE_CAMPAIGN_SCHEMA)
    except GatewayError as e:
        raise CampaignProposalError(f"Both primary and fallback model calls failed: {e}") from e

    if not result.tool_calls:
        raise CampaignProposalError(f"Model returned no campaign proposal (text only: {result.content!r}).")

    call = result.tool_calls[0]
    try:
        args = json.loads(call.arguments_raw)
    except (json.JSONDecodeError, TypeError) as e:
        raise CampaignProposalError(f"Malformed campaign proposal JSON: {e}") from e

    skus = [s for s in (args.get("skus") or []) if isinstance(s, str)]
    # Same discipline as the shopping agent's UnknownSkuRule: never trust a
    # model-claimed SKU. Filter to what's real rather than blocking the
    # whole proposal over one hallucinated entry, since a partially-valid
    # campaign is still a valid one — but require at least one real SKU.
    valid_skus = [s for s in skus if s in known_skus]
    if not valid_skus:
        raise CampaignProposalError(f"No valid SKUs in proposal (got {skus!r}, none exist in the catalog).")

    try:
        discount_pct = float(args["discount_pct"])
    except (KeyError, TypeError, ValueError) as e:
        raise CampaignProposalError(f"Malformed discount_pct: {e}") from e
    if not (0 < discount_pct <= 1.0):
        raise CampaignProposalError(f"discount_pct {discount_pct} is out of range (0, 1.0].")

    message = str(args.get("message") or "").strip()
    if not message:
        raise CampaignProposalError("Proposal is missing a customer-facing message.")

    return CampaignProposal(
        skus=valid_skus,
        discount_pct=discount_pct,
        message=message[:240],
        rationale=str(args.get("rationale") or ""),
        model_used=result.model_used,
        fallback_used=result.fallback_used,
        prompt_tokens=result.prompt_tokens,
        completion_tokens=result.completion_tokens,
        total_tokens=result.total_tokens,
        cost_paise=result.cost_paise,
        latency_ms=result.latency_ms,
    )
