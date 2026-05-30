"""
a2_guardrails/run_tests.py
Runs the guardrail classifier against test_suite.json and produces a full
classification report: precision, recall, FP rate, FN rate per category.

Usage (from project root):
    python -m a2_guardrails.run_tests
    python -m a2_guardrails.run_tests --verbose
    python -m a2_guardrails.run_tests --no-pass2   # regex only (faster CI)

Exit code:
    0 = all BLOCK-category false negatives = 0
    1 = at least one BLOCK-category false negative detected
"""

from __future__ import annotations
import argparse
import json
import pathlib
import sys
import time

# Allow running from project root
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

from a2_guardrails.classifier    import classify
from a2_guardrails.audit_logger  import log_classification


SUITE_PATH = pathlib.Path(__file__).parent / "test_suite.json"
BLOCK_CATEGORIES = {"ADVERSARIAL_JAILBREAK", "SAFETY", "LEGAL_THREAT", "PRIVACY_PII"}


def load_suite() -> list[dict]:
    if not SUITE_PATH.exists():
        print(f"ERROR: test_suite.json not found at {SUITE_PATH}")
        print("Run:  python -m a2_guardrails.generate_test_suite")
        sys.exit(1)
    with open(SUITE_PATH, encoding="utf-8") as f:
        return json.load(f)


def run_tests(verbose: bool = False, skip_pass2: bool = False) -> int:
    """
    Returns number of BLOCK-category false negatives (target: 0).
    """
    suite = load_suite()
    print(f"\n{'═'*60}")
    print(f"  VOIZ A2 — Guardrail Classifier Test Report")
    print(f"  {len(suite)} test cases | {SUITE_PATH.name}")
    print(f"{'═'*60}\n")

    # Per-category accumulators: {cat: {TP, FP, FN, TN}}
    stats: dict[str, dict[str, int]] = {}
    for cat in [
        "ADVERSARIAL_JAILBREAK", "SAFETY", "LEGAL_THREAT", "PRIVACY_PII",
        "AUTHORITY_BREACH", "FINANCIAL_HARDSHIP", "SCOPE_TOPIC",
    ]:
        stats[cat] = {"TP": 0, "FP": 0, "FN": 0, "TN": 0}

    overall = {"TP": 0, "FP": 0, "FN": 0, "TN": 0}
    block_fn = 0
    results = []

    for tc in suite:
        idx          = tc.get("id", "?")
        utterance    = tc["utterance"]
        exp_triggered = tc["expected_triggered"]
        exp_category  = tc.get("expected_category")

        t0 = time.monotonic()
        result = classify(utterance)
        elapsed = int((time.monotonic() - t0) * 1000)

        # Log to audit file
        log_classification(utterance, result)

        got_triggered = result.triggered
        got_category  = result.category

        # Determine TP/FP/FN/TN at overall level
        if exp_triggered and got_triggered:
            overall["TP"] += 1
            outcome = "TP"
        elif not exp_triggered and not got_triggered:
            overall["TN"] += 1
            outcome = "TN"
        elif not exp_triggered and got_triggered:
            overall["FP"] += 1
            outcome = "FP"
        else:  # exp_triggered and not got_triggered
            overall["FN"] += 1
            outcome = "FN"
            if exp_category in BLOCK_CATEGORIES:
                block_fn += 1

        # Per-category stats (based on expected category)
        cat = exp_category or got_category
        if cat and cat in stats:
            stats[cat][outcome] += 1

        status_icon = "✓" if outcome in ("TP", "TN") else "✗"
        result_entry = {
            "id": idx,
            "outcome": outcome,
            "expected": exp_category,
            "got": got_category,
            "severity": result.severity,
            "pass": result.pass_used,
            "ms": elapsed,
            "utterance": utterance[:60],
        }
        results.append(result_entry)

        if verbose or outcome in ("FP", "FN"):
            print(
                f"[{status_icon}] #{idx:02d} {outcome:2s} | "
                f"exp={str(exp_category):<22} got={str(got_category):<22} "
                f"pass={result.pass_used} | {elapsed}ms"
            )
            if outcome in ("FP", "FN"):
                print(f"     utterance: {utterance[:80]}")
                print(f"     reasoning: {result.reasoning[:80]}")
                print()

    # ── Summary ──────────────────────────────────────────────────────
    print(f"\n{'─'*60}")
    print(f"  OVERALL RESULTS")
    print(f"{'─'*60}")
    total = len(suite)
    correct = overall["TP"] + overall["TN"]
    print(f"  Total:    {total}   Correct: {correct}   Accuracy: {correct/total*100:.1f}%")
    print(f"  TP={overall['TP']}  TN={overall['TN']}  FP={overall['FP']}  FN={overall['FN']}")

    if (overall["TP"] + overall["FN"]) > 0:
        recall = overall["TP"] / (overall["TP"] + overall["FN"])
        print(f"  Recall (sensitivity): {recall*100:.1f}%")
    if (overall["TP"] + overall["FP"]) > 0:
        precision = overall["TP"] / (overall["TP"] + overall["FP"])
        print(f"  Precision:            {precision*100:.1f}%")
    if (overall["FP"] + overall["TN"]) > 0:
        fpr = overall["FP"] / (overall["FP"] + overall["TN"])
        print(f"  False positive rate:  {fpr*100:.1f}%")

    # ── Per-category breakdown ────────────────────────────────────────
    print(f"\n{'─'*60}")
    print(f"  PER-CATEGORY BREAKDOWN")
    print(f"{'─'*60}")
    print(f"  {'Category':<26} {'TP':>4} {'FP':>4} {'FN':>4} {'TN':>4}  {'Recall':>7}  {'Prec':>7}")
    print(f"  {'─'*26} {'─'*4} {'─'*4} {'─'*4} {'─'*4}  {'─'*7}  {'─'*7}")

    for cat, s in stats.items():
        tp, fp, fn, tn = s["TP"], s["FP"], s["FN"], s["TN"]
        recall_s    = f"{tp/(tp+fn)*100:.0f}%" if (tp+fn) > 0 else "  N/A"
        precision_s = f"{tp/(tp+fp)*100:.0f}%" if (tp+fp) > 0 else "  N/A"
        block_marker = " ◀ BLOCK" if cat in BLOCK_CATEGORIES else ""
        print(
            f"  {cat:<26} {tp:>4} {fp:>4} {fn:>4} {tn:>4}  "
            f"{recall_s:>7}  {precision_s:>7}{block_marker}"
        )

    # ── BLOCK false negative verdict ──────────────────────────────────
    print(f"\n{'═'*60}")
    if block_fn == 0:
        print("  ✓  BLOCK-CATEGORY FALSE NEGATIVES: 0  — TARGET MET")
    else:
        print(f"  ✗  BLOCK-CATEGORY FALSE NEGATIVES: {block_fn}  — TARGET MISSED")
        print("     Review FN cases above and tighten Pass 1 patterns.")
    print(f"{'═'*60}\n")

    return block_fn


def main():
    parser = argparse.ArgumentParser(description="Run VOIZ A2 guardrail test suite")
    parser.add_argument("--verbose",   action="store_true", help="Print every test case result")
    parser.add_argument("--no-pass2",  action="store_true", help="Skip LLM pass (regex only)")
    args = parser.parse_args()

    block_fn = run_tests(verbose=args.verbose, skip_pass2=args.no_pass2)
    sys.exit(0 if block_fn == 0 else 1)


if __name__ == "__main__":
    main()