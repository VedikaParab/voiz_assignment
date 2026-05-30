"""
scorer.py — VOIZ A4 Campaign Engine
Composite priority score formula (pure function, no IO, no LLM).
score = 0.4×risk + 0.3×propensity + 0.2×dpd_urgency + 0.1×recency
Recalculated after every contact outcome.
"""

from datetime import date, datetime
from typing import Dict, Any


# ── DPD urgency: maps dpd_bucket → 0–1 urgency score ─────────────────────────
_DPD_URGENCY = {
    0:   0.10,   # current — lowest urgency
    30:  0.40,   # early delinquency
    60:  0.70,   # mid delinquency
    90:  0.90,   # late delinquency
    120: 1.00,   # NPA — highest urgency
}


def dpd_urgency_score(dpd_bucket: int) -> float:
    """Return urgency score for a given DPD bucket."""
    return _DPD_URGENCY.get(dpd_bucket, min(dpd_bucket / 120, 1.0))


def recency_score(last_contact_date: str) -> float:
    """
    Return recency score based on days since last contact.
    More days since last contact → higher score (needs re-engagement).
    0 days → 0.0, 14+ days → 1.0 (capped).
    """
    try:
        last = datetime.strptime(last_contact_date, "%Y-%m-%d").date()
        days_ago = (date.today() - last).days
    except (ValueError, TypeError):
        days_ago = 7  # default to 1 week if unknown

    # Linear scale: 0 days = 0.0, 14+ days = 1.0
    return min(days_ago / 14.0, 1.0)


def score(contact: Dict[str, Any]) -> float:
    """
    Compute composite priority score for a contact.

    Formula:
        score = (0.4 × risk_score)
              + (0.3 × propensity_score)
              + (0.2 × dpd_urgency_score)
              + (0.1 × recency_score)

    Returns float in [0, 1]. Higher = higher priority.
    """
    risk       = float(contact.get("risk_score", 0))
    propensity = float(contact.get("propensity_score", 0))
    dpd_u      = dpd_urgency_score(contact.get("dpd_bucket", 0))
    recency    = recency_score(contact.get("last_contact_date", ""))

    composite = (
        0.4 * risk
        + 0.3 * propensity
        + 0.2 * dpd_u
        + 0.1 * recency
    )
    return round(min(max(composite, 0.0), 1.0), 6)


def score_all(contacts: list[Dict[str, Any]]) -> list[Dict[str, Any]]:
    """Score all contacts and return sorted list (highest first)."""
    scored = []
    for c in contacts:
        s = score(c)
        scored.append({**c, "priority_score": s})
    return sorted(scored, key=lambda x: x["priority_score"], reverse=True)


# ── CLI test ───────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import json
    from pathlib import Path

    contacts = json.loads((Path(__file__).parent / "data" / "contacts.json").read_text())
    ranked = score_all(contacts)

    print("=== VOIZ Campaign — Top 10 Priority Contacts ===\n")
    print(f"{'Rank':<5} {'ID':<6} {'Name':<22} {'Score':<8} {'DPD':<6} {'Risk':<6} {'Prop':<6}")
    print("-" * 65)
    for i, c in enumerate(ranked[:10], 1):
        print(
            f"{i:<5} {c['contact_id']:<6} {c['name']:<22} "
            f"{c['priority_score']:<8.4f} {c['dpd_bucket']:<6} "
            f"{c['risk_score']:<6} {c['propensity_score']:<6}"
        )