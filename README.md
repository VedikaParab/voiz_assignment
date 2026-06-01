# VOIZ — AI Collections Call Platform

**Predixion AI · Intern Assignment · May 2026**

Built by **Vedika Parab** as part of the Predixion AI intern programme.

VOIZ is an AI-first debt collections voice agent platform for Indian NBFCs and banks. This repository contains four end-to-end assignments that together form the core platform stack: a stateful call agent, a compliance guardrail system, a grounded RAG knowledge layer, and a campaign orchestration engine.

---

## Repository Structure

```
voiz/
├── config.py                    # Shared Groq client + logger (used by all 4 modules)
├── requirements.txt
├── .env                         # GROQ_API_KEY (not committed)
│
├── a1_state_machine/            # Assignment 1 — Stateful Call Agent
│   ├── state_machine.py         # Phase enum, CallState dataclass, state_injector()
│   ├── conversation_loop.py     # Main loop: utterance → counters → LLM → transition
│   ├── phase_transitions.py     # Deterministic keyword-based phase transition engine
│   ├── goal_hierarchy.py        # 4-level goal hierarchy, evaluated per turn
│   ├── diversion_recovery.py    # Cycled diversion re-engagement utterances
│   ├── logger.py                # Structured JSONL logger (one entry per turn)
│   ├── test_harness.py          # 3 scripted call scenarios with assertions
│   ├── run.py                   # Entry point: --test or interactive
│   └── app.py                   # Streamlit UI (chat + live state panel)
│
├── a2_guardrails/               # Assignment 2 — Compliance Guardrail Classifier
│   ├── classifier.py            # Pipeline: PII pre-filter → Pass 1 → Pass 2
│   ├── pii_detector.py          # Regex detector for Aadhaar, PAN, mobile, IFSC, etc.
│   ├── pass1_regex.py           # Deterministic keyword/regex filter (7 categories)
│   ├── pass2_llm.py             # LLM classifier for ambiguous cases (Groq, temp=0)
│   ├── handlers.py              # Pre-approved static response per category
│   ├── audit_logger.py          # Append-only JSONL audit log (SHA-256 hash, no raw text)
│   ├── run_tests.py             # Test runner with precision/recall report
│   ├── test_suite.json          # 30-input adversarial test suite
│   └── api.py                   # FastAPI endpoint: POST /classify
│
├── a3_rag/                      # Assignment 3 — Agentic RAG Pipeline
│   ├── generator.py             # Generates 5 synthetic knowledge-base documents
│   ├── ingestor.py              # Chunk → embed → store in ChromaDB
│   ├── retriever.py             # Query embed → top-k retrieval → grounded generation
│   ├── vector_store.py          # Multi-tenant ChromaDB manager (one collection per client)
│   ├── hallucination_judge.py   # Second LLM call as faithfulness judge
│   ├── evaluate.py              # 20-question evaluation: precision, recall, hallucination rate
│   ├── multitenant_test.py      # Cross-collection isolation assertions
│   ├── evaluation_report.json   # Latest evaluation results
│   ├── app.py                   # Streamlit chat UI with citations panel
│   └── docs/                    # 5 synthetic knowledge-base documents
│       ├── 01_collections_policy.txt
│       ├── 02_product_faq.txt
│       ├── 03_complaince_sop.txt
│       ├── 04_pricing_sheet.txt
│       └── 05_communication_scripts.txt
│
└── a4_campaign/                 # Assignment 4 — Campaign Management Engine
    ├── campaign_runner.py       # Orchestration: load → score → queue → dispatch → log
    ├── scorer.py                # Composite priority score formula (pure function)
    ├── priority_queue.py        # Max-heap with lazy deletion, thread-safe, DNC at pop
    ├── dnc_manager.py           # In-memory set + SQLite persistence, pop-time enforcement
    ├── channel_sequencer.py     # Config-driven channel routing (voice → WhatsApp → SMS)
    ├── window_enforcer.py       # TRAI TCCCPR 2018 call window enforcement (IST)
    ├── nba_engine.py            # Batch LLM call: top-10 contacts → 3 ranked recommendations
    ├── app.py                   # Streamlit dashboard (queue, log, analytics)
    └── data/
        ├── contacts.json        # 50 synthetic contacts with risk/propensity/DPD fields
        └── channel_config.json  # Channel sequence rules (editable without code changes)
```

---

## Quick Start

### 1. Clone and install

```bash
git clone https://github.com/VedikaParab/voiz_assignment.git
cd voiz_assignment
pip install -r requirements.txt
```

### 2. Set your API key

```bash
# Create .env in the project root
echo "GROQ_API_KEY=your_key_here" > .env
```

Get a free Groq API key at [console.groq.com](https://console.groq.com). The free tier (30 req/min) is sufficient to run all four assignments.

### 3. Run each assignment

```bash
# A1 — State Machine: 3 scripted call scenarios
python a1_state_machine/run.py --test

# A1 — Interactive live call
python a1_state_machine/run.py

# A1 — Streamlit UI
streamlit run a1_state_machine/app.py

# A2 — Guardrail classifier test suite (precision/recall report)
python -m a2_guardrails.run_tests

# A2 — FastAPI endpoint
uvicorn a2_guardrails.api:app --reload
# POST http://localhost:8000/classify  {"utterance": "I'll take you to consumer court"}

# A3 — Generate knowledge-base docs, ingest, evaluate
cd a3_rag
python generator.py        # create 5 synthetic docs in docs/
python ingestor.py         # chunk + embed + store in ChromaDB
python evaluate.py         # run 20-question evaluation
python multitenant_test.py # multi-tenant isolation assertions
streamlit run app.py       # chat UI with citations

# A4 — Campaign engine simulation
cd a4_campaign
python campaign_runner.py  # 20-attempt simulated run, analytics output
streamlit run app.py       # full dashboard
```

---

## Assignment Summaries

### A1 — Call State Machine

A stateful 7-phase collections call agent. The LLM handles language; a deterministic Python layer owns all state. Phase transitions are keyword-triggered, never LLM-decided.

**7 phases:** `INTRO → VERIFICATION → PITCH → NEGOTIATION → CAPTURE → CLOSE → ESCALATE`

**Key design decisions:**

- `state_injector()` serialises the full `CallState` (phase, goal, objection count, diversion count, patience budget, confirmed data, escalation flag) into a `[CALL STATE]` block prepended to every system prompt. The LLM always sees current state explicitly — it never infers it from conversation history.
- Phase transitions fire on keyword matches in the LLM's own response text. `PHASE_INSTRUCTIONS` per phase tell the LLM what vocabulary to produce, making transitions reliable.
- The goal hierarchy (`secure_full_payment → secure_partial_payment → schedule_callback → log_hardship_and_escalate`) is re-evaluated every turn. Goal demotions are logged automatically.
- Diversion recovery utterances cycle through a fixed list per diversion level and never repeat until the set is exhausted.

**Test results:** All 3 scripted scenarios pass — cooperative (reaches `CLOSE`), resistant (objection count triggers goal demotion and `ESCALATE`), escalated (patience budget depletion triggers `ESCALATE`).

---

### A2 — Guardrail Classifier

A two-pass compliance classifier that runs **before** the main LLM on every caller utterance. On a `BLOCK`, the main LLM is bypassed entirely and a pre-approved deterministic response is returned.

**Pipeline:** PII pre-filter (Step 0) → Pass 1 regex (<5ms) → Pass 2 LLM (only if Pass 1 misses)

**7 guardrail categories:**

| Category | Severity | Example trigger |
|---|---|---|
| `ADVERSARIAL_JAILBREAK` | BLOCK | "ignore all previous instructions" |
| `SAFETY` | BLOCK | "want to kill myself" |
| `LEGAL_THREAT` | BLOCK | "my lawyer will be in touch" |
| `PRIVACY_PII` | BLOCK | Aadhaar / PAN / card number patterns |
| `AUTHORITY_BREACH` | FLAG | "I am from the RBI" |
| `FINANCIAL_HARDSHIP` | FLAG | "I lost my job last month" |
| `SCOPE_TOPIC` | LOG | "what's the cricket score?" |

**PII detection** covers Aadhaar (12-digit), PAN (AAAAA9999A), Indian mobile (+91 / 10-digit), email, bank account (9–18 digit), and IFSC. Raw utterances are never passed to the LLM or stored in logs — only SHA-256 hashes.

**Test results (30-input adversarial suite):** 0 BLOCK false negatives, 0 FLAG false negatives, 1 benign false positive (LOG severity). Pass 1 catches ~80% of triggers; Pass 2 handles the remaining ~20%.

---

### A3 — Agentic RAG Pipeline

A grounded retrieval-augmented generation pipeline. Every agent response must be traceable to a specific document and chunk. The hallucination rate target is <2%.

**Components:**

- **Ingestor:** paragraph-aware chunking (300 tokens / 50-token overlap), `all-MiniLM-L6-v2` embeddings (local, no API key), ChromaDB storage with `{source_doc, chunk_id, page_number}` metadata.
- **Retriever:** cosine similarity retrieval, top-3 chunks, similarity scores returned alongside chunks.
- **Generator:** context injected into system prompt; LLM instructed to answer only from retrieved context and cite every claim.
- **Hallucination judge:** second Groq call at temperature 0.0; evaluates each response against retrieved chunks; returns `{hallucinated, faithfulness_score, flagged_claims}`.
- **Multi-tenant isolation:** one ChromaDB collection per `client_id` (`voiz_{client_id}` namespace). Cross-collection access is architecturally impossible. Four isolation assertions verified by `multitenant_test.py`.

**Evaluation results (20 questions):**

| Metric | Result |
|---|---|
| Correctly grounded (17 domain Qs) | 17 / 17 — 100% |
| Correctly declined (3 out-of-domain Qs) | 3 / 3 — 100% |
| Hallucination rate | 0.0% |
| Avg faithfulness score | 1.00 / 1.00 |

**Knowledge base documents:** collections policy, product FAQ, compliance SOP, pricing sheet, borrower communication scripts — all generated via Groq and saved to `a3_rag/docs/`.

---

### A4 — Campaign Management Engine

The orchestration layer between a contact list and the voice agent: decides who to call, when, on which channel, in what order, and what to do after each outcome.

**Priority scoring formula** (pure function, no IO, no LLM):
```
priority_score = 0.4 × risk_score
               + 0.3 × propensity_score
               + 0.2 × dpd_urgency_score   # 0/30/60/90/120 DPD → 0.1/0.4/0.7/0.9/1.0
               + 0.1 × recency_score        # days since last contact / 14, capped at 1.0
```
Re-calculated after every contact outcome.

**Key components:**

- **Priority queue:** Python `heapq` max-heap with lazy deletion. Thread-safe via `threading.Lock`. DNC check fires at `pop()` — not at ingestion.
- **DNC manager:** in-memory set (O(1) lookup) backed by SQLite. `remove()` raises `NotImplementedError` — DNC is permanent per TRAI TCCCPR 2018. Every pop-time DNC catch is logged.
- **Channel sequencer:** fully config-driven via `data/channel_config.json`. Default sequence: Voice (0 min) → WhatsApp (120 min) → SMS (360 min) on NO\_ANSWER. No hardcoded channel logic in Python.
- **Window enforcer:** TRAI hard limits (9am–8pm IST, no Sundays) enforced before campaign-level windows. Contacts outside the window are deferred, never dropped.
- **NBA engine:** single batch Groq call for top-10 contacts → ranked 3 recommendations with reasoning, urgency, and recommended channel. Under 3s latency for the batch.

**Simulation results (20 attempts, 50 contacts):** contact rate, RPC rate, channel effectiveness, and queue depth tracked throughout. Full log saved to `a4_campaign/logs/`.

---

## Architecture Overview

```
Caller utterance
       │
       ▼
┌─────────────────────────────┐
│  A2 Guardrail Classifier    │  ← runs first, every turn
│  PII → Pass 1 → Pass 2      │
│  BLOCK: return handler      │
│  PASS: continue             │
└──────────────┬──────────────┘
               │ (cleared)
               ▼
┌─────────────────────────────┐
│  A3 RAG Retriever           │  ← grounds factual questions
│  embed query → top-3 chunks │
│  inject into system prompt  │
└──────────────┬──────────────┘
               │
               ▼
┌─────────────────────────────┐
│  A1 State Machine           │  ← owns call state
│  state_injector()           │
│  Groq LLM call              │
│  phase_transition_engine()  │
│  goal_hierarchy evaluation  │
└──────────────┬──────────────┘
               │
               ▼
           Agent response
               │
       ┌───────┴────────┐
       ▼                ▼
  A3 Hallucination   A4 Campaign
  Judge              Engine
  (audit response)   (re-score, re-queue)
```

---

## Configuration

All shared configuration lives in `config.py` at the project root:

```python
MODEL = "llama-3.3-70b-versatile"   # Groq model

chat(system, messages, max_tokens, temperature, model)
# Used by all 4 assignments — never call the Groq client directly

get_logger(name, log_file)
# Returns a logger writing to both console and logs/<log_file>
```

To switch from Groq to the Anthropic Claude API, replace the `Groq` client in `config.py` with `anthropic.Anthropic()` and update the `chat()` wrapper. All prompt structures are identical — no other changes needed.

---

## Tech Stack

| Component | Technology |
|---|---|
| LLM backend | Groq — `llama-3.3-70b-versatile` (free tier) |
| Embeddings | `sentence-transformers` — `all-MiniLM-L6-v2` (local, no API key) |
| Vector DB | ChromaDB (persistent local) |
| Guardrail classifier | Python `re` module (Pass 1) + Groq (Pass 2) |
| Campaign queue | Python `heapq` + `threading.Lock` |
| DNC persistence | SQLite via `sqlite3` |
| UI | Streamlit (all 4 assignments have a UI) |
| API | FastAPI (A2 guardrail endpoint) |
| Python | 3.11+ |

---

## Environment Variables

```bash
# .env (project root — do not commit)
GROQ_API_KEY=gsk_...
```

No other credentials required. ChromaDB runs locally. Embeddings are computed locally via sentence-transformers.

---

## Logs

All logs are written to `logs/` at the project root (gitignored).

| File | Contents |
|---|---|
| `voiz_a1.jsonl` | One JSON entry per conversation turn: phase, goal, state, utterance, response, transitions, latency |
| `voiz_a2_audit_YYYY-MM-DD.jsonl` | One entry per classified utterance: SHA-256 hash, category, severity, pass used, latency |
| `a4_campaign/logs/run_*.json` | Full campaign run log with attempt-by-attempt outcomes and analytics |

---

## Author

**Vedika Parab**
B.E. Artificial Intelligence & Data Science, VESIT Mumbai
Intern — Predixion AI, Powai, Mumbai
May 2026

---

*Predixion AI · VOIZ Platform · Intern Programme · May 2026*
