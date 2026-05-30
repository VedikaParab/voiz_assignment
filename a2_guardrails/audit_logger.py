"""
a2_guardrails/audit_logger.py
Append-only structured audit log for every classification decision.

Design:
  - Stores utterance SHA-256 hash, NEVER raw text (PII-safe)
  - Each line is a valid JSON object (JSONL format)
  - Rotation-ready: log file path includes date by default
  - Thread-safe append via file open/close per write (no shared handle)

Log entry schema:
  {
    "timestamp":      "2026-05-24T10:30:00.123456Z",
    "utterance_hash": "<sha256 hex>",
    "category":       "LEGAL_THREAT" | null,
    "severity":       "BLOCK" | "FLAG" | "LOG" | null,
    "triggered":      true | false,
    "handler_fired":  "handle_legal_threat" | null,
    "pass_used":      1 | 2 | null,
    "pii_found":      ["AADHAAR"] | [],
    "latency_ms":     42
  }
"""

from __future__ import annotations
import hashlib
import json
import logging
import pathlib
from datetime import datetime, timezone

logger = logging.getLogger("a2")

LOG_DIR = pathlib.Path(__file__).parent.parent / "logs"
LOG_DIR.mkdir(exist_ok=True)


def _utterance_hash(text: str) -> str:
    """SHA-256 hex digest of the raw utterance. Never store raw text."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _log_path(date_str: str | None = None) -> pathlib.Path:
    """
    Returns today's audit log path.
    Format: logs/voiz_a2_audit_YYYY-MM-DD.jsonl
    Pass date_str to override (useful in tests).
    """
    ds = date_str or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return LOG_DIR / f"voiz_a2_audit_{ds}.jsonl"


def log_classification(
    utterance: str,
    result,                  # ClassificationResult (avoid circular import with Any)
    date_str: str | None = None,
) -> None:
    """
    Append a classification decision to the audit log.

    Args:
        utterance: Raw caller utterance (hashed before logging — never stored raw).
        result:    ClassificationResult from classifier.classify().
        date_str:  Override date for log file name (default: today UTC).
    """
    # Derive handler function name from category label
    handler_fired: str | None = None
    if result.triggered and result.category:
        handler_fired = f"handle_{result.category.lower()}"

    entry = {
        "timestamp":      datetime.now(timezone.utc).isoformat(),
        "utterance_hash": _utterance_hash(utterance),
        "category":       result.category,
        "severity":       result.severity,
        "triggered":      result.triggered,
        "handler_fired":  handler_fired,
        "pass_used":      result.pass_used,
        "pii_found":      result.pii_found,
        "latency_ms":     result.latency_ms,
    }

    path = _log_path(date_str)
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    except OSError as exc:
        logger.error("Audit log write failed: %s", exc)


def read_recent_entries(n: int = 10, date_str: str | None = None) -> list[dict]:
    """
    Read the last n entries from today's audit log.
    Returns empty list if log doesn't exist yet.
    """
    path = _log_path(date_str)
    if not path.exists():
        return []

    try:
        lines = path.read_text(encoding="utf-8").strip().splitlines()
        recent = lines[-n:]
        return [json.loads(line) for line in recent]
    except (OSError, json.JSONDecodeError) as exc:
        logger.error("Audit log read failed: %s", exc)
        return []