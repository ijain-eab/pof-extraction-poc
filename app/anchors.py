"""Deterministic regex cross-check against the 90% template.

This is cheap insurance against LLM hallucination on the highest-value fields. It runs on
the plain text layer (extracted with pypdf) and flags when the LLM output disagrees with a
hard anchor it could find. It is intentionally conservative: when an anchor is not found,
it simply reports None and does not contradict the LLM.
"""
import re
from typing import Optional

_PROPOSAL_FOOTER = re.compile(r"PROPOSAL\s*\|\s*(Q-\d{4,})", re.IGNORECASE)
_PROPOSAL_LOOSE = re.compile(r"\b(Q-\d{4,})\b")
_ORGANIZATION = re.compile(r"(?im)^\W*Organization:\s*\|?\s*([^\n|]+?)\s*(?:\||Date:|$)")


def find_proposal_number(text: str) -> Optional[str]:
    if not text:
        return None
    match = _PROPOSAL_FOOTER.search(text)
    if match:
        return match.group(1).upper()
    match = _PROPOSAL_LOOSE.search(text)
    return match.group(1).upper() if match else None


def find_organization(text: str) -> Optional[str]:
    if not text:
        return None
    match = _ORGANIZATION.search(text)
    return match.group(1).strip() if match else None


def _norm(value: Optional[str]) -> str:
    return re.sub(r"\s+", " ", (value or "")).strip().lower()


def build_anchor_checks(text: str, fields) -> dict:
    """Compare a couple of high-value LLM fields against deterministic anchors.

    Returns a dict of {field: {anchor, llm, agrees}}. `agrees` is None when the anchor
    could not be located in the text (so we can't confirm or deny).
    """
    checks: dict = {}

    anchor_proposal = find_proposal_number(text)
    llm_proposal = getattr(fields, "proposal_number", None)
    checks["proposal_number"] = {
        "anchor": anchor_proposal,
        "llm": llm_proposal,
        "agrees": None if anchor_proposal is None else _norm(anchor_proposal) == _norm(llm_proposal),
    }

    anchor_org = find_organization(text)
    llm_org = getattr(fields, "customer_organization", None)
    org_agrees = None
    if anchor_org is not None and llm_org:
        org_agrees = _norm(anchor_org) in _norm(llm_org) or _norm(llm_org) in _norm(anchor_org)
    checks["customer_organization"] = {
        "anchor": anchor_org,
        "llm": llm_org,
        "agrees": org_agrees,
    }

    return checks
