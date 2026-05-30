"""
hallucination_judge.py — VOIZ A3 RAG Pipeline
Second Groq call as faithfulness evaluator.
Uses shared config.chat() — no API key argument needed.
"""

import json
import re
import sys
import os
from typing import List, Dict, Any

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from config import chat

JUDGE_SYSTEM_PROMPT = """You are a strict hallucination detection judge for an enterprise RAG system.

Given an AI-generated response and the context chunks it was based on,
identify every factual claim in the response NOT supported by the context.

RULES:
1. A claim is SUPPORTED if the context explicitly states it OR if it can be directly derived
   from stated numbers/ranges without adding new information.
   Example: context says "Tier 2: CIBIL 700-749 → 21%". A response saying "CIBIL 720 falls
   in Tier 2 and attracts 21%" is SUPPORTED — it is arithmetic/range classification, not invention.
2. A claim is HALLUCINATED only if it introduces facts, names, numbers, or details that are
   ABSENT from the context and cannot be logically derived from it.
3. Decline phrases like "not available in my knowledge base" are NEVER hallucinations.
4. Arithmetic, range classification, unit conversions, and logical deductions made directly
   from numbers or ranges stated in the context are NOT hallucinations.
5. Be conservative — only flag something as hallucinated if you are certain it cannot be
   derived from the provided context chunks.

Respond with ONLY valid JSON — no markdown, no preamble:
{
  "hallucinated": true | false,
  "faithfulness_score": 0.0 to 1.0,
  "flagged_claims": ["claim not in context and not derivable", ...],
  "reasoning": "brief explanation"
}"""


def judge(
    response: str,
    chunks: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Run hallucination judge on a response against the retrieved chunks.
    Uses config.chat() — Groq under the hood.
    Returns: {hallucinated, faithfulness_score, flagged_claims, reasoning}
    """
    context_summary = "\n\n".join(
        f"[Chunk {i+1} — {c['metadata']['source_doc']}]:\n{c['text']}"
        for i, c in enumerate(chunks)
    )

    user_message = f"""CONTEXT CHUNKS:
{context_summary}

AI RESPONSE TO EVALUATE:
{response}

Return JSON only."""

    raw = chat(
        system=JUDGE_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_message}],
        max_tokens=512,
        temperature=0.0,
    )

    raw = re.sub(r"```(?:json)?|```", "", raw).strip()

    try:
        result = json.loads(raw)
    except json.JSONDecodeError:
        result = {
            "hallucinated": True,
            "faithfulness_score": 0.5,
            "flagged_claims": ["[Judge parse error — manual review needed]"],
            "reasoning": raw[:300],
        }

    result.setdefault("hallucinated", bool(result.get("flagged_claims")))
    result.setdefault("faithfulness_score", 1.0 if not result["hallucinated"] else 0.5)
    result.setdefault("flagged_claims", [])
    result.setdefault("reasoning", "")
    return result


def log_judgment(result: Dict[str, Any]) -> None:
    status = "🔴 HALLUCINATION DETECTED" if result["hallucinated"] else "✅ GROUNDED"
    print(f"\n[JUDGE] {status}")
    print(f"  Faithfulness: {result['faithfulness_score']:.2f}")
    for claim in result.get("flagged_claims", []):
        print(f"  ⚠  {claim}")
    print(f"  Reasoning: {result['reasoning'][:150]}")