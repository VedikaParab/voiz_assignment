"""
a2_guardrails/pass1_regex.py
Pass 1 — fast deterministic regex filter.

Architecture:
  - 7 categories ordered BLOCK → FLAG → LOG (severity-first evaluation)
  - Returns immediately on first match (no stacking)
  - Zero LLM calls — target latency < 5ms
  - Each entry: (category, severity, compiled_pattern)

Categories:
  1. ADVERSARIAL_JAILBREAK  — BLOCK  (prompt injection, roleplay bypass)
  2. SAFETY                 — BLOCK  (self-harm, distress signals)
  3. LEGAL_THREAT           — BLOCK  (legal action language)
  4. PRIVACY_PII            — BLOCK  (PII disclosure — handled via pii_detector too)
  5. AUTHORITY_BREACH       — FLAG   (claims to be regulator / auditor)
  6. FINANCIAL_HARDSHIP     — FLAG   (hardship signals)
  7. SCOPE_TOPIC            — LOG    (off-topic requests)
"""

from __future__ import annotations
import re
import time
from dataclasses import dataclass


@dataclass(frozen=True)
class RegexMatch:
    category: str
    severity: str          # 'BLOCK' | 'FLAG' | 'LOG'
    pattern_matched: str   # the raw pattern string that fired (for audit)


# ── Pattern registry — BLOCK categories first ─────────────────────────
# Each tuple: (category_label, severity, pattern_string)
# Patterns are case-insensitive (re.IGNORECASE applied at compile time)

_RAW_PATTERNS: list[tuple[str, str, str]] = [

    # ── 1. ADVERSARIAL / JAILBREAK (BLOCK) ───────────────────────────
    # Prompt injection, roleplay bypass, instruction override attempts
    (
        "ADVERSARIAL_JAILBREAK", "BLOCK",
        r"ignore (your |all )?(previous |prior )?(instructions?|rules?|guidelines?|prompt)"
    ),
    (
        "ADVERSARIAL_JAILBREAK", "BLOCK",
        r"(pretend|act|roleplay|imagine|simulate).{0,40}(you are|you're|youre).{0,40}"
        r"(different|human|person|not an? (ai|bot|agent|assistant)|free|unrestricted)"
    ),
    (
        "ADVERSARIAL_JAILBREAK", "BLOCK",
        r"(jailbreak|dan mode|developer mode|god mode|unrestricted mode)"
    ),
    (
        "ADVERSARIAL_JAILBREAK", "BLOCK",
        r"(disregard|forget|override|bypass).{0,30}(rules?|instructions?|guidelines?|restrictions?|compliance)"
    ),
    (
        "ADVERSARIAL_JAILBREAK", "BLOCK",
        r"(system prompt|your prompt|your instructions?).{0,20}(show|reveal|repeat|print|output|tell me)"
    ),
    (
        "ADVERSARIAL_JAILBREAK", "BLOCK",
        r"(from now on|starting now|henceforth).{0,40}(respond as|act as|behave as|you (are|will be))"
    ),
    (
        "ADVERSARIAL_JAILBREAK", "BLOCK",
        r"do anything now|no restrictions|without (any )?restrictions|anything goes"
    ),
    (
        "ADVERSARIAL_JAILBREAK", "BLOCK",
        r"\[system\]|\{\{.*?\}\}|<\|.*?\|>"   # template injection markers
    ),

    # ── 2. SAFETY — self-harm / distress (BLOCK) ─────────────────────
    (
        "SAFETY", "BLOCK",
        r"\b(want to|going to|thinking (about|of)|plan(ning)? to).{0,30}"
        r"(kill (myself|my self)|end (my life|it all)|hurt (myself|my self)|suicide|self.harm)\b"
    ),
    (
        "SAFETY", "BLOCK",
        r"\b(suicid(al|e)|self.harm|self.injur|cut(ting)? myself|overdose on)\b"
    ),
    (
        "SAFETY", "BLOCK",
        r"\b(i (can't|cannot|don't want to) (live|go on|do this anymore))\b"
    ),
    (
        "SAFETY", "BLOCK",
        r"\b(nobody (cares?|would miss me)|better off (dead|without me))\b"
    ),

    # ── 3. LEGAL THREAT (BLOCK) ───────────────────────────────────────
    (
        "LEGAL_THREAT", "BLOCK",
        r"\b(sue|suing|lawsuit|file a (suit|case|complaint)|take (you|this) to court)\b"
    ),
    (
        "LEGAL_THREAT", "BLOCK",
        r"\b(my (lawyer|attorney|solicitor)|legal action|cease.and.desist|defamation)\b"
    ),
    (
        "LEGAL_THREAT", "BLOCK",
        r"\b(consumer court|consumer forum|rbi ombudsman|banking ombudsman|nclt|nclat)\b"
    ),
    (
        "LEGAL_THREAT", "BLOCK",
        r"\b(fdcpa|fair debt|illegal (collection|harassment)|report you to (rbi|sebi|nclt))\b"
    ),

    # ── 4. PRIVACY / PII DISCLOSURE (BLOCK) ──────────────────────────
    # Catching explicit mentions of sharing sensitive data verbally
    (
        "PRIVACY_PII", "BLOCK",
        r"\b(my (aadhaar|aadhar|pan (card|number)|pan is)|aadhaar (number|is|no\.?)\s*[:–]?\s*\d)"
    ),
    (
        "PRIVACY_PII", "BLOCK",
        r"\b(account (number|no\.?) (is|:)\s*\d{6,})"
    ),
    (
        "PRIVACY_PII", "BLOCK",
        r"\b(cvv|card (number|no\.?)|expiry date).{0,20}(is|:|\d)"
    ),

    # ── 5. AUTHORITY BREACH (FLAG) ────────────────────────────────────
    (
        "AUTHORITY_BREACH", "FLAG",
        r"\b(i (am|work for|represent|am from).{0,30}"
        r"(rbi|sebi|income tax|enforcement directorate|cbi|police|government|ministry|regulator|auditor))\b"
    ),
    (
        "AUTHORITY_BREACH", "FLAG",
        r"\b(official (notice|order|directive)|court order|warrant|subpoena)\b"
    ),
    (
        "AUTHORITY_BREACH", "FLAG",
        r"\b(you (are|will be) (fined|penalised|arrested|shut down))\b"
    ),
    (
        "AUTHORITY_BREACH", "FLAG",
        r"\b(i (have|hold) (authority|jurisdiction|power) over)\b"
    ),

    # ── 6. FINANCIAL HARDSHIP (FLAG) ─────────────────────────────────
    (
        "FINANCIAL_HARDSHIP", "FLAG",
        r"\b(lost (my job|my work|employment)|laid off|been (fired|retrenched)|no (income|salary))\b"
    ),
    (
        "FINANCIAL_HARDSHIP", "FLAG",
        r"\b(can('t| not) (afford|eat|feed|pay (rent|bills?))|not enough (money|food))\b"
    ),
    (
        "FINANCIAL_HARDSHIP", "FLAG",
        r"\b(in (hospital|icu|surgery)|medical (emergency|bills?)|hospitalised|cancer|dialysis)\b"
    ),
    (
        "FINANCIAL_HARDSHIP", "FLAG",
        r"\b(bankrupt(cy)?|insolvency|debt trap|drowning in debt|creditors? calling)\b"
    ),
    (
        "FINANCIAL_HARDSHIP", "FLAG",
        r"\b(death in (the )?family|spouse (died|passed|left)|single (parent|mother|father))\b"
    ),

    # ── 7. SCOPE / OFF-TOPIC (LOG) ────────────────────────────────────
    (
        "SCOPE_TOPIC", "LOG",
        r"\b(what('s| is) (the )?weather|weather (today|tomorrow|forecast))\b"
    ),
    (
        "SCOPE_TOPIC", "LOG",
        r"\b(cricket (score|match|ipl)|football (match|score|result)|sports (score|update))\b"
    ),
    (
        "SCOPE_TOPIC", "LOG",
        r"\b(tell me (a )?joke|funny (story|video)|entertain me)\b"
    ),
    (
        "SCOPE_TOPIC", "LOG",
        r"\b(recipe (for|of)|how (to cook|do i cook|do i make))\b"
    ),
    (
        "SCOPE_TOPIC", "LOG",
        r"\b(stock (price|market|tips?)|bitcoin|crypto(currency)?|nifty|sensex)\b"
    ),
    (
        "SCOPE_TOPIC", "LOG",
        r"\b(who (won|is winning)|election (results?|news)|political (party|news))\b"
    ),
]

# ── Compile all patterns once at import time ───────────────────────────
_COMPILED: list[tuple[str, str, re.Pattern, str]] = [
    (cat, sev, re.compile(pat, re.IGNORECASE), pat)
    for cat, sev, pat in _RAW_PATTERNS
]


def pass1_check(text: str) -> tuple[RegexMatch | None, int]:
    """
    Run all regex patterns against text in severity order.
    Stops and returns on first match.

    Args:
        text: Caller utterance (raw string).

    Returns:
        (RegexMatch | None, latency_ms)
        RegexMatch contains category, severity, and which pattern fired.
    """
    t0 = time.monotonic()
    for category, severity, pattern, raw_pat in _COMPILED:
        if pattern.search(text):
            latency_ms = int((time.monotonic() - t0) * 1000)
            return RegexMatch(
                category=category,
                severity=severity,
                pattern_matched=raw_pat,
            ), latency_ms

    latency_ms = int((time.monotonic() - t0) * 1000)
    return None, latency_ms