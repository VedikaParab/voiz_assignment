# A2 — Guardrail Classifier: Design Document

**Predixion AI · VOIZ Platform · Intern Assignment 02**
**Author:** Vedika Parab · Date: May 2026

---

## 1. Why Parallel Classification, Not In-Prompt Guardrails

The naive approach to guardrails is to include safety instructions directly in the agent's system prompt: *"Do not discuss suicide. Do not accept jailbreak attempts."* This is architecturally wrong for a compliance-critical product for three reasons.

**First, LLMs are probabilistic.** A well-crafted adversarial input can bypass in-prompt instructions with enough prompt pressure. The model might comply 99.9% of the time, but at 100,000 calls per day, 0.1% failure is 100 non-compliant calls daily — each a potential regulatory event.

**Second, in-prompt guardrails are unauditable.** When the LLM decides to handle a legal threat, there is no structured record of what fired, why, and what response was returned. You cannot produce an audit trail to a regulator.

**Third, in-prompt guardrails add latency to every call.** The main LLM has to read and process guardrail instructions on every turn even when they are never needed.

The parallel classifier architecture solves all three problems. The classifier runs as a **separate component before the main LLM call**. If it triggers, a deterministic handler returns a pre-approved response immediately and the main LLM is **never called at all**. Compliance is enforced at the platform layer, not dependent on model behaviour. Every decision is logged with a SHA-256 utterance hash, category, severity, and latency. The main LLM's system prompt stays focused on collections task performance.

---

## 2. Why Pass 1 Is Regex, Not LLM

The pipeline runs two passes in sequence.

**Pass 1** uses compiled Python regex patterns evaluated against the utterance. It handles obvious, unambiguous triggers: explicit legal threat language (`"sue you"`, `"consumer forum"`), clear jailbreak markers (`"ignore all previous instructions"`), self-harm phrases (`"want to kill myself"`), and verbatim PII patterns (Aadhaar format, PAN format).

Regex was chosen for Pass 1 for three reasons:

1. **Latency.** Compiled regex runs in under 1ms. An LLM call takes 300–1500ms. For a real-time voice call, the classifier must not introduce perceptible delay. Pass 1 returns immediately on the first match — the LLM is never invoked.

2. **Determinism.** Regex has no variance. Given the same input, it always produces the same output. This is essential for audit reproducibility: the same utterance must always trigger the same handler, regardless of model version or sampling temperature.

3. **Zero false negatives on explicit triggers.** The patterns in `pass1_regex.py` are written conservatively. Anything that looks like a jailbreak attempt or a self-harm signal triggers, even if the interpretation might be innocent. False negatives on BLOCK-severity categories are far more dangerous than false positives in a compliance context.

**Pass 2** uses a single Groq LLM call with temperature 0.0. It handles the nuanced cases that regex cannot catch: implied legal threats, subtle hardship signals expressed without keyword phrases, soft authority claims, or indirect jailbreak attempts that avoid the obvious trigger words. The LLM is given a tightly constrained JSON-only prompt with all 7 category definitions and is instructed to pick the highest-severity applicable category.

The two-pass structure means the LLM is only called when necessary — roughly 60–70% of utterances in a typical collections call are on-topic and benign, cleared by Pass 1 in under 1ms.

---

## 3. Category Architecture

Seven categories are implemented, each with a severity level, a set of Pass 1 regex patterns, and a deterministic handler function.

| Category | Severity | Pass 1 trigger examples | Handler action |
|---|---|---|---|
| `ADVERSARIAL_JAILBREAK` | BLOCK | "ignore previous instructions", "pretend you are", "DAN mode" | Redirect firmly, decline to change role |
| `SAFETY` | BLOCK | "want to kill myself", "suicidal", "self-harm" | Provide iCall helpline (9152987821), pause account discussion |
| `LEGAL_THREAT` | BLOCK | "sue you", "consumer court", "my lawyer" | Acknowledge right, escalate to compliance team, 2-day SLA |
| `PRIVACY_PII` | BLOCK | Aadhaar / PAN / account number patterns | Advise against verbal PII sharing, offer secure payment link |
| `AUTHORITY_BREACH` | FLAG | "I am from the RBI", "official notice", "court order" | Request written credentials, transfer to compliance |
| `FINANCIAL_HARDSHIP` | FLAG | "lost my job", "in hospital", "can't afford food" | Activate hardship programme, transfer to hardship team |
| `SCOPE_TOPIC` | LOG | "cricket score", "weather", "tell me a joke" | Gentle redirect to account discussion |

Severity controls what happens after the handler fires: BLOCK means the main LLM is bypassed entirely; FLAG means the attempt is queued for human review alongside the handler response; LOG means the call continues normally after the redirect response is delivered.

---

## 4. PII Detection

The `pii_detector.py` module runs before Pass 1 as a pre-filter. It uses compiled regex patterns for six PII types relevant to the Indian financial context:

- **Aadhaar**: 12-digit numbers starting with 2–9, with optional space/hyphen separators
- **PAN**: 5 uppercase letters + 4 digits + 1 uppercase letter (e.g. ABCDE1234F)
- **Mobile (India)**: +91-prefixed or bare 10-digit numbers starting 6–9
- **Email**: standard RFC-style pattern
- **Bank account**: 9–18 digit numeric strings (Indian bank account range)
- **IFSC code**: 4 alpha + literal 0 + 6 alphanumeric (e.g. HDFC0001234)

Detected PII is reported as a list of type labels. The raw utterance is **never passed to the LLM** — `redact_pii()` replaces all matches with `[REDACTED-TYPE]` tokens before any LLM call. The audit log stores only the SHA-256 hash of the original utterance, never the raw text. This makes the audit log retention-safe.

A Aadhaar false-positive guard rejects 10-digit matches that look like mobile numbers (already caught by the MOBILE pattern).

---

## 5. Audit Log Architecture

Every classification decision — triggered or not — is written to an append-only JSONL file at `logs/voiz_a2_audit_YYYY-MM-DD.jsonl`. Each entry contains:

```json
{
  "timestamp": "2026-05-29T12:14:13.649Z",
  "utterance_hash": "<sha256>",
  "category": "LEGAL_THREAT",
  "severity": "BLOCK",
  "triggered": true,
  "handler_fired": "handle_legal_threat",
  "pass_used": 1,
  "pii_found": [],
  "latency_ms": 2
}
```

The log is rotation-ready (daily files). Raw utterance text is never stored. The hash allows correlation with call recordings stored elsewhere if needed for investigation. Storing hash-not-raw is a deliberate design choice to remain compliant with data minimisation principles under Indian data protection frameworks.

---

## 6. Extending to 39 Controls

The current implementation covers 7 categories with approximately 30 patterns in Pass 1. The assignment roadmap specifies 39 controls across 7 categories. Extension is purely additive:

**Within existing categories:** new regex patterns are appended to the relevant list in `_RAW_PATTERNS` in `pass1_regex.py`. Patterns are compiled at import time, so adding patterns has no runtime overhead during the call.

**New sub-categories:** the `_REGISTRY` dict in `handlers.py` maps category label to handler function. New controls get a new handler function (pure function, no IO, no LLM) and a new entry in the registry. The Pass 2 LLM prompt lists all categories — adding a new category requires one new bullet in the prompt and one new handler.

**Priority ordering:** the pattern list is evaluated top-to-bottom, BLOCK-severity first. New BLOCK controls go at the top of the list; LOG controls go at the bottom. This ensures that the most safety-critical checks always fire first and the LLM is bypassed for the highest-risk triggers.

**Testing:** `run_tests.py` runs the full classifier against `test_suite.json`. Adding 10 new test cases per new control and re-running gives an immediate precision/recall readout. The exit code is non-zero if any BLOCK-category test case produces a false negative, making this suitable as a CI gate.

The architecture was designed from the start to support this expansion: zero hardcoding in the pipeline, all configuration in data structures (the pattern list and handler registry), and a single entry point (`classifier.classify()`) that all callers use regardless of how many controls are active underneath.