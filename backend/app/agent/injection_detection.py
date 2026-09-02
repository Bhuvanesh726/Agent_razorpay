"""Heuristic detection of prompt-injection-shaped text in tool output.

This is defense-in-depth, NOT the actual security boundary. The real
guarantee is structural, in two independent places:

1. Tool results are passed to the model as clearly delimited, labelled
   `role: "tool"` messages (see app/agent/harness.py::_build_messages) —
   never spliced into the system prompt. The wire format itself marks this
   content as data, not instructions.
2. The policy engine evaluates the *proposed cart state*, deterministically,
   regardless of what the model does with any text it read. Even a model
   that fully "complies" with an injected instruction still has every
   proposed action re-checked in code — that's what
   tests/test_prompt_injection.py proves.

This scanner exists for the third leg: making an attempt visible in the
audit trail even when it fails, so "the system doesn't care" isn't just
asserted, it's logged.
"""

import re

_SUSPICIOUS_PATTERNS = [
    r"ignore (all )?(the )?(previous|prior|above)( \w+){0,3} instructions",
    r"disregard (all )?(the )?(previous|prior|above)",
    r"new instructions?:",
    r"you are now\b",
    r"system prompt",
    r"authoriz(ed|e)\s+unlimited",
    r"act as (an?|the)\s",
    r"\bdo anything now\b",
    r"without confirmation",
    r"proceed to payment immediately",
]

_COMPILED = [re.compile(p, re.IGNORECASE) for p in _SUSPICIOUS_PATTERNS]


def scan_for_injection(text: str | None) -> str | None:
    """Returns the matched snippet (for the audit reason), or None."""
    if not text:
        return None
    for pattern in _COMPILED:
        match = pattern.search(text)
        if match:
            return match.group(0)
    return None
