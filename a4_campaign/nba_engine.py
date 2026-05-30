"""
nba_engine.py — VOIZ A4 Campaign Engine
Next-Best-Action engine: single batch Groq call for top-10 contacts.
Uses shared config.py chat() wrapper — same pattern as all other assignments.
"""

import json
import sys
import time
import logging
from pathlib import Path
from typing import Dict, Any

sys.path.insert(0, str(Path(__file__).parent.parent))  # reach voiz/config.py
from config import chat

logger = logging.getLogger(__name__)


def _build_prompt(contacts: list[Dict[str, Any]]) -> str:
    lines = []
    for i, c in enumerate(contacts, 1):
        lines.append(
            f"{i}. ID={c['contact_id']} | {c['name']} | "
            f"DPD={c['dpd_bucket']} | risk={c['risk_score']:.2f} | "
            f"propensity={c['propensity_score']:.2f} | "
            f"priority={c.get('priority_score', 0):.4f} | "
            f"last_outcome={c.get('last_contact_outcome','?')} | "
            f"channel={c.get('preferred_channel','?')} | "
            f"lang={c.get('language','?')} | "
            f"last_contact={c.get('last_contact_date','?')}"
        )

    return "\n".join(lines)


SYSTEM_PROMPT = """You are the VOIZ Campaign Next-Best-Action engine for a collections campaign (VOIZ KOLLECT).

You will receive the top 10 contacts in the priority queue. Recommend the TOP 3 to contact IMMEDIATELY.

Consider:
- DPD bucket (higher = more urgent): 0=current, 30=early, 60=mid, 90=late, 120=NPA
- Risk score (0-1): likelihood of default
- Propensity score (0-1): likelihood of payment if contacted
- Last outcome: NO_ANSWER needs retry; CALLBACK_REQUESTED should be honoured; recent ANSWERED may not need follow-up
- Preferred channel and language

Respond ONLY with a JSON array of exactly 3 objects. No preamble, no markdown fences.
Schema:
[
  {
    "rank": 1,
    "contact_id": "C...",
    "name": "...",
    "reasoning": "2-3 sentence justification citing DPD, outcome, and propensity",
    "recommended_channel": "voice|whatsapp|sms",
    "urgency": "critical|high|medium"
  }
]"""


def next_best_actions(
    top_contacts: list[Dict[str, Any]],
    max_contacts: int = 10,
) -> Dict[str, Any]:
    contacts = top_contacts[:max_contacts]
    if not contacts:
        return {"ranked": [], "latency_ms": 0, "model": "", "error": "No contacts provided"}

    user_message = f"TOP {len(contacts)} CONTACTS:\n{_build_prompt(contacts)}"
    t0 = time.time()

    try:
        raw = chat(
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_message}],
            max_tokens=1000,
            temperature=0.2,
        )
        latency_ms = (time.time() - t0) * 1000

        # Strip markdown fences if model adds them anyway
        clean = raw.strip()
        if clean.startswith("```"):
            clean = clean.split("```")[1]
            if clean.startswith("json"):
                clean = clean[4:]

        ranked = json.loads(clean.strip())
        return {
            "ranked": ranked,
            "latency_ms": round(latency_ms, 1),
            "model": "llama-3.3-70b-versatile",
            "error": None,
        }

    except json.JSONDecodeError as e:
        logger.error(f"NBA JSON parse error: {e}\nRaw response: {raw}")
        return {"ranked": [], "latency_ms": round((time.time() - t0) * 1000, 1), "model": "", "error": f"JSON parse error: {e}"}
    except Exception as e:
        logger.error(f"NBA engine error: {e}")
        return {"ranked": [], "latency_ms": round((time.time() - t0) * 1000, 1), "model": "", "error": str(e)}


# ── CLI smoke test ─────────────────────────────────────────────────────────────
if __name__ == "__main__":
    from pathlib import Path
    from scorer import score_all

    contacts = json.loads((Path(__file__).parent / "data" / "contacts.json").read_text())
    top10 = score_all(contacts)[:10]

    print("=== NBA Engine (Groq) Smoke Test ===\n")
    result = next_best_actions(top10)

    if result["error"]:
        print(f"ERROR: {result['error']}")
    else:
        print(f"Latency: {result['latency_ms']}ms\n")
        for item in result["ranked"]:
            print(f"Rank {item['rank']}: {item['contact_id']} — {item['name']}")
            print(f"  Channel: {item['recommended_channel']} | Urgency: {item['urgency']}")
            print(f"  {item['reasoning']}\n")