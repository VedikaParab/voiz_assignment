"""
a2_guardrails/api.py
Optional FastAPI wrapper — POST /classify → ClassificationResult JSON.

Install deps:  pip install fastapi uvicorn
Run:           uvicorn a2_guardrails.api:app --reload --port 8000
Test:          curl -X POST http://localhost:8000/classify \
                    -H "Content-Type: application/json" \
                    -d '{"utterance": "I am going to sue you"}'
"""

from __future__ import annotations

try:
    from fastapi import FastAPI, HTTPException
    from pydantic import BaseModel
except ImportError:
    raise ImportError(
        "FastAPI not installed. Run: pip install fastapi uvicorn"
    )

import logging
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

from a2_guardrails.classifier   import classify
from a2_guardrails.audit_logger import log_classification

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("a2.api")

app = FastAPI(
    title       = "VOIZ Guardrail Classifier",
    description = "Parallel guardrail classifier for the VOIZ collections platform",
    version     = "1.0.0",
)


class ClassifyRequest(BaseModel):
    utterance: str


class ClassifyResponse(BaseModel):
    triggered:         bool
    category:          str | None
    severity:          str | None
    handler_response:  str | None
    reasoning:         str
    latency_ms:        int
    pass_used:         int | None
    pii_found:         list[str]


@app.post("/classify", response_model=ClassifyResponse)
def classify_utterance(request: ClassifyRequest) -> ClassifyResponse:
    """
    Classify a single caller utterance through the full guardrail pipeline.

    Returns a ClassificationResult including:
    - triggered: whether a guardrail fired
    - category: which guardrail category
    - severity: BLOCK / FLAG / LOG
    - handler_response: pre-approved safe response (if triggered)
    - reasoning: one-line explanation
    - latency_ms: total pipeline latency
    - pass_used: 1 (regex) or 2 (LLM)
    - pii_found: list of PII types detected
    """
    if not request.utterance or not request.utterance.strip():
        raise HTTPException(status_code=422, detail="utterance must be a non-empty string")

    result = classify(request.utterance)
    log_classification(request.utterance, result)

    logger.info(
        "classified | triggered=%s category=%s severity=%s pass=%s latency=%dms",
        result.triggered, result.category, result.severity,
        result.pass_used, result.latency_ms,
    )

    return ClassifyResponse(
        triggered        = result.triggered,
        category         = result.category,
        severity         = result.severity,
        handler_response = result.handler_response,
        reasoning        = result.reasoning,
        latency_ms       = result.latency_ms,
        pass_used        = result.pass_used,
        pii_found        = result.pii_found,
    )


@app.get("/health")
def health():
    return {"status": "ok", "service": "voiz-guardrails"}


@app.get("/categories")
def list_categories():
    """List all available guardrail categories."""
    from a2_guardrails.handlers import list_categories
    return {"categories": list_categories()}