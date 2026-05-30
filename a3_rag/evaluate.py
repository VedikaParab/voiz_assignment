"""
evaluate.py — VOIZ A3 RAG Pipeline
Runs 20 test questions matched to the ACTUAL 5 docs in a3_rag/docs/.
Measures precision, recall, hallucination rate.
Uses config.chat() (Groq) — no API key argument needed anywhere.
"""

import json
import time
import sys
import os
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from vector_store import get_collection
from retriever import retrieve, generate_grounded_response
from hallucination_judge import judge

# ── 20 questions matched to actual doc content ─────────────────────────────────
# Doc 01: collections_policy   → DPD buckets, settlement %, calling rules, prohibited conduct
# Doc 02: product_faq          → borrower Q&A: EMI, prepayment, CIBIL, settlement, NACH
# Doc 03: compliance_sop       → pre-call checklist, during-call, post-call, escalation
# Doc 04: pricing_sheet        → interest rates, fees, penalty, prepayment charges, B2B tiers
# Doc 05: communication_scripts → 10 call scripts: opening, payment, hardship, legal, settlement

TEST_QUESTIONS = [
    # ── Doc 01: Collections Policy ────────────────────────────────────────────
    {"q": "What is the maximum settlement discount allowed for a Bucket 2 account?",      "grounded": True},
    {"q": "What are the DPD bucket definitions and their treatment strategies?",           "grounded": True},
    {"q": "How many calls per day are permitted for a Bucket 3 account?",                 "grounded": True},
    {"q": "What happens to an account at 91+ DPD?",                                       "grounded": True},
    {"q": "What conduct is strictly prohibited for VOIZ collection agents?",              "grounded": True},

    # ── Doc 02: Borrower Product FAQ ──────────────────────────────────────────
    {"q": "What is the late payment fee if I miss an EMI?",                               "grounded": True},
    {"q": "What payment methods are accepted for loan repayment?",                        "grounded": True},
    {"q": "Can I prepay my loan early and what charges apply?",                           "grounded": True},
    {"q": "What happens to my CIBIL score if I settle a loan?",                          "grounded": True},
    {"q": "How long does it take to get a settlement confirmation?",                      "grounded": True},

    # ── Doc 03: Compliance SOP ────────────────────────────────────────────────
    {"q": "What are the allowed calling hours for outbound collection calls?",            "grounded": True},
    {"q": "How must an agent verify borrower identity before discussing the account?",    "grounded": True},
    {"q": "What must an agent do immediately if a borrower mentions legal action?",       "grounded": True},
    {"q": "What information must be logged in the audit trail after every call?",         "grounded": True},

    # ── Doc 04: Pricing Sheet ─────────────────────────────────────────────────
    {"q": "What are all the personal loan interest rate tiers based on CIBIL score?",     "grounded": True},
    {"q": "What is the penalty for a bounced NACH payment?",                             "grounded": True},
    {"q": "What is the monthly cost of the VOIZ Growth Plan?",                           "grounded": True},

    # ── Out-of-domain (should be declined) ────────────────────────────────────
    {"q": "What is the recipe for biryani?",                                              "grounded": False},
    {"q": "Who won the 2024 Indian Premier League?",                                      "grounded": False},
    {"q": "Write a Python function to sort a list in descending order.",                  "grounded": False},
]

DECLINE_KEYWORDS = [
    "not available in my knowledge base",
    "not in my knowledge base",
    "cannot find",
    "don't have information",
    "no information",
    "outside my knowledge",
    "i don't have",
    "not covered",
]

def is_declined(response: str) -> bool:
    return any(kw in response.lower() for kw in DECLINE_KEYWORDS)


def run_evaluation(client_id: str = "client_A") -> dict:
    collection = get_collection(client_id)
    if collection.count() == 0:
        print(f"❌ Collection '{client_id}' is empty — run: python ingestor.py")
        return {}

    results = []
    total = len(TEST_QUESTIONS)
    correctly_grounded = correctly_declined = hallucinated_count = 0
    total_faithfulness = 0.0

    print(f"=== VOIZ RAG Evaluation — {total} questions | {client_id} ===\n")

    for i, item in enumerate(TEST_QUESTIONS, 1):
        q, expected_grounded = item["q"], item["grounded"]
        print(f"[{i:02d}/{total}] {q[:72]}...")
        t0 = time.time()

        chunks = retrieve(q, collection, top_k=3)
        response = generate_grounded_response(q, chunks)

        if chunks:
            judge_result = judge(response, chunks)
        else:
            judge_result = {
                "hallucinated": False, "faithfulness_score": 1.0,
                "flagged_claims": [], "reasoning": "No chunks retrieved — correct decline",
            }

        latency = round(time.time() - t0, 2)
        declined = is_declined(response)

        if expected_grounded and not declined and not judge_result["hallucinated"]:
            outcome = "CORRECT_GROUNDED";  correctly_grounded += 1
        elif not expected_grounded and declined:
            outcome = "CORRECT_DECLINED";  correctly_declined += 1
        elif judge_result["hallucinated"]:
            outcome = "HALLUCINATED";      hallucinated_count += 1
        elif expected_grounded and declined:
            outcome = "FALSE_DECLINE"
        else:
            outcome = "UNKNOWN"

        faith = judge_result.get("faithfulness_score", 1.0)
        total_faithfulness += faith
        flag = "✅" if "CORRECT" in outcome else ("🔴" if outcome == "HALLUCINATED" else "⚠️")
        print(f"  {flag} {outcome} | Faithfulness: {faith:.2f} | {latency}s")
        for claim in judge_result.get("flagged_claims", [])[:1]:
            print(f"     ⚠ {claim[:80]}")

        results.append({
            "question": q, "expected_grounded": expected_grounded,
            "response_snippet": response[:200], "outcome": outcome,
            "chunks_retrieved": len(chunks), "faithfulness_score": faith,
            "flagged_claims": judge_result.get("flagged_claims", []),
            "latency_s": latency,
        })

    grounded_q  = sum(1 for t in TEST_QUESTIONS if t["grounded"])
    ood_q       = total - grounded_q
    precision   = correctly_grounded / grounded_q if grounded_q else 0
    recall      = correctly_grounded / grounded_q if grounded_q else 0
    decline_acc = correctly_declined / ood_q      if ood_q       else 0
    hall_rate   = hallucinated_count / total
    avg_faith   = total_faithfulness / total

    report = {
        "total_questions":       total,
        "correctly_grounded":    correctly_grounded,
        "correctly_declined":    correctly_declined,
        "hallucinated":          hallucinated_count,
        "precision":             round(precision,   3),
        "recall":                round(recall,      3),
        "decline_accuracy":      round(decline_acc, 3),
        "hallucination_rate":    round(hall_rate,   3),
        "avg_faithfulness_score":round(avg_faith,   3),
        "results":               results,
    }

    out_path = Path(__file__).parent / "evaluation_report.json"
    out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print(f"\n{'='*55}")
    print(f"  Precision (grounded Qs answered):  {precision:.1%}")
    print(f"  Recall (grounded Qs answered):     {recall:.1%}")
    print(f"  Out-of-domain decline rate:        {decline_acc:.1%}")
    print(f"  Hallucination rate:                {hall_rate:.1%}  (target <2%)")
    print(f"  Avg faithfulness score:            {avg_faith:.2f} / 1.00")
    print(f"\n  Full report → {out_path}")
    return report


if __name__ == "__main__":
    run_evaluation("client_A")