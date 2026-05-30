"""
a2_guardrails/pii_detector.py
Standalone PII detector — runs BEFORE Pass 1 as a pre-filter.

Detects:
  - Aadhaar  : 12-digit number (with optional spaces every 4 digits)
  - PAN      : AAAAA9999A format (5 letters, 4 digits, 1 letter)
  - Mobile   : +91 prefix or standalone 10-digit starting with 6-9
  - Email    : standard email pattern
  - Bank Acc : 9–18 digit numeric strings (Indian bank account range)
  - IFSC     : 4 alpha + 0 + 6 alphanumeric (e.g. HDFC0001234)

Returns a list of PII type strings found — caller decides what to do.
Never raises; always returns a list (empty = clean).
"""

from __future__ import annotations
import re

# ── Compiled patterns (compiled once at import time for speed) ──────────

_PATTERNS: dict[str, re.Pattern] = {
    "AADHAAR": re.compile(
        r"\b[2-9]\d{3}\s?\d{4}\s?\d{4}\b"
    ),
    "PAN": re.compile(
        r"\b[A-Z]{5}[0-9]{4}[A-Z]\b"
    ),
    "MOBILE": re.compile(
        r"(?:\+91[\s\-]?)?[6-9]\d{9}\b"
    ),
    "EMAIL": re.compile(
        r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b"
    ),
    "BANK_ACCOUNT": re.compile(
        r"\b\d{9,18}\b"
    ),
    "IFSC": re.compile(
        r"\b[A-Z]{4}0[A-Z0-9]{6}\b"
    ),
}

# Aadhaar false-positive guard: reject if it looks like a plain phone number
# (10 digits starting with 6-9 with no spaces — already caught by MOBILE)
_AADHAAR_PHONE_GUARD = re.compile(r"^[6-9]\d{9}$")


def detect_pii(text: str) -> list[str]:
    """
    Scan text for PII patterns.

    Args:
        text: Raw utterance string.

    Returns:
        List of PII type labels found (e.g. ['AADHAAR', 'MOBILE']).
        Empty list = no PII detected.
    """
    found: list[str] = []
    clean = text.strip()

    for pii_type, pattern in _PATTERNS.items():
        matches = pattern.findall(clean)
        if not matches:
            continue

        # Extra guard for AADHAAR — reject 10-digit mobile-like hits
        if pii_type == "AADHAAR":
            real_matches = [
                m for m in matches
                if not _AADHAAR_PHONE_GUARD.match(m.replace(" ", ""))
            ]
            if real_matches:
                found.append(pii_type)
        else:
            found.append(pii_type)

    return found


def redact_pii(text: str) -> str:
    """
    Returns a copy of text with all detected PII replaced by [REDACTED-TYPE].
    Used in audit logging so raw PII never hits the log file.
    """
    redacted = text
    for pii_type, pattern in _PATTERNS.items():
        redacted = pattern.sub(f"[REDACTED-{pii_type}]", redacted)
    return redacted