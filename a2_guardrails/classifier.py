"""
a2_guardrails/classifier.py
Main classifier pipeline — the single entry point for all guardrail checks.

Pipeline order:
  0. PII pre-filter  (pii_detector)   — always runs, adds metadata
  1. Pass 1 regex    (pass1_regex)     — deterministic, returns on first hit
  2. Pass 2 LLM      (pass2_llm)       — only if Pass 1 found nothing

Result object (ClassificationResult):
  triggered       bool
  category        str | None
  severity        'BLOCK' | 'FLAG' | 'LOG' | None
  handler_response str | None   (pre-approved safe response)
  reasoning       str
  latency_ms      int           (total pipeline latency)
  pass_used       int | None    (1 or 2; None if not triggered)
  pii_found       list[str]     (PII types detected, may be non-empty even if not triggered)
"""

from __future__ import annotations
import time
import logging
from dataclasses import dataclass, field, asdict

from a2_guardrails.pii_detector import detect_pii
from a2_guardrails.pass1_regex  import pass1_check
from a2_guardrails.pass2_llm    import pass2_classify
from a2_guardrails.handlers     import get_handler_response

logger = logging.getLogger("a2")


@dataclass
class ClassificationResult:
    triggered:        bool
    category:         str | None
    severity:         str | None          # 'BLOCK' | 'FLAG' | 'LOG' | None
    handler_response: str | None
    reasoning:        str
    latency_ms:       int
    pass_used:        int | None          # 1 or 2; None = not triggered
    pii_found:        list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def classify(utterance: str) -> ClassificationResult:
    """
    Run the full guardrail pipeline on a caller utterance.

    Args:
        utterance: Raw string from caller.

    Returns:
        ClassificationResult — always returns, never raises.
    """
    pipeline_start = time.monotonic()

    # ── Step 0: PII pre-filter ────────────────────────────────────────
    pii_found = detect_pii(utterance)
    if pii_found:
        logger.info("[PII] detected: %s", pii_found)

    # If PII detected, treat as PRIVACY_PII BLOCK immediately
    if pii_found:
        total_ms = int((time.monotonic() - pipeline_start) * 1000)
        return ClassificationResult(
            triggered        = True,
            category         = "PRIVACY_PII",
            severity         = "BLOCK",
            handler_response = get_handler_response("PRIVACY_PII"),
            reasoning        = f"PII detected in utterance: {', '.join(pii_found)}",
            latency_ms       = total_ms,
            pass_used        = 1,
            pii_found        = pii_found,
        )

    # ── Step 1: Pass 1 regex ──────────────────────────────────────────
    regex_match, p1_ms = pass1_check(utterance)

    if regex_match:
        total_ms = int((time.monotonic() - pipeline_start) * 1000)
        logger.info(
            "[PASS1] category=%s severity=%s pattern=%r",
            regex_match.category, regex_match.severity, regex_match.pattern_matched,
        )
        return ClassificationResult(
            triggered        = True,
            category         = regex_match.category,
            severity         = regex_match.severity,
            handler_response = get_handler_response(regex_match.category),
            reasoning        = f"Pass 1 regex match on pattern: {regex_match.pattern_matched[:60]}",
            latency_ms       = total_ms,
            pass_used        = 1,
            pii_found        = pii_found,
        )

    # ── Step 2: Pass 2 LLM ───────────────────────────────────────────
    llm_result, p2_ms = pass2_classify(utterance)
    total_ms = int((time.monotonic() - pipeline_start) * 1000)

    if llm_result.get("triggered"):
        category = llm_result.get("category")
        severity = llm_result.get("severity")
        logger.info(
            "[PASS2] category=%s severity=%s reasoning=%s",
            category, severity, llm_result.get("reasoning"),
        )
        return ClassificationResult(
            triggered        = True,
            category         = category,
            severity         = severity,
            handler_response = get_handler_response(category) if category else None,
            reasoning        = llm_result.get("reasoning", "LLM classifier triggered"),
            latency_ms       = total_ms,
            pass_used        = 2,
            pii_found        = pii_found,
        )

    # ── Clean pass ────────────────────────────────────────────────────
    logger.debug("[CLEAN] utterance passed all checks in %dms", total_ms)
    return ClassificationResult(
        triggered        = False,
        category         = None,
        severity         = None,
        handler_response = None,
        reasoning        = llm_result.get("reasoning", "No guardrail triggered"),
        latency_ms       = total_ms,
        pass_used        = None,
        pii_found        = pii_found,
    )