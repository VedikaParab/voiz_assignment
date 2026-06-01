# A4 — Campaign Engine: Design Document

**Predixion AI · VOIZ Platform · Intern Assignment 04**
**Author:** Vedika Parab · Date: May 2026

---

## Current Architecture (50 Contacts)

The current engine is a synchronous Python process with five cooperating modules:

- **`scorer.py`** — Pure function computing composite priority score: `0.4 × risk + 0.3 × propensity + 0.2 × dpd_urgency + 0.1 × recency`. No IO, no LLM. Recalculated after every contact outcome.
- **`priority_queue.py`** — Max-heap wrapping Python `heapq`. Uses lazy deletion (a `_removed` set) to handle re-scoring without heap rebuilds. DNC check fires at `pop()` time, not at ingestion. Thread-safe via `threading.Lock`.
- **`dnc_manager.py`** — In-memory set for O(1) hot-path lookups, backed by SQLite for persistence across restarts. `remove()` raises `NotImplementedError` — DNC is permanent per TRAI TCCCPR 2018.
- **`channel_sequencer.py`** — JSON config-driven. Maps `last_contact_outcome` to an ordered sequence of `{channel, delay_minutes}` steps. No hardcoded rules — the entire sequencing logic lives in `channel_config.json`.
- **`window_enforcer.py`** — TRAI hard limits (9am–8pm IST, no Sundays) enforced before campaign-level `permitted_windows`. Returns `{dispatchable, reason, retry_after_ist}` — never blocks execution, always defers cleanly.
- **`nba_engine.py`** — Single batch Groq call for top-10 contacts. Returns ranked list of 3 with reasoning. Temperature 0.2 to allow flexible prioritisation reasoning without high variance.

For 50 contacts and a 20-attempt simulation, this architecture is sufficient and correct. The synchronous single-process design is easy to reason about, debug, and demo.

---

## How to Scale to 100,000 Contacts with Real-Time Telephony

At 100,000 contacts with real-time outcome updates from a live telephony system (Exotel/Twilio webhooks), four components of the current architecture must change fundamentally.

### 1. Queue Architecture

**Current:** Python `heapq` in-process. Capacity limit ~500k entries before memory pressure, but more critically, a single process cannot handle concurrent dispatch workers and score updates without lock contention.

**At scale:** Replace the in-process heap with **Redis Sorted Sets** (`ZADD`/`ZPOPMAX`). Redis Sorted Sets are O(log N) for push and pop, support atomic score updates (`ZADD XX GT` for update-only-if-higher), and are accessible from multiple worker processes over the network. A 100,000-contact queue fits in under 50MB of Redis memory.

DNC enforcement at pop time is preserved: each `ZPOPMAX` is followed by a DNC check against a Redis Set (`SISMEMBER dnc:phones`). If the phone is on DNC, the contact is discarded and the next entry is popped in the same atomic pipeline. This maintains the architectural guarantee — no contact is dispatched after DNC status is set — while handling concurrent workers safely.

Score updates from real-time outcomes (telephony webhook → outcome → re-score → `ZADD`) become non-blocking: the webhook handler writes the new score to Redis and returns immediately. Worker processes see the updated score on their next pop.

### 2. Scoring Model

**Current:** Fixed-weight formula with four inputs. Weights (0.4, 0.3, 0.2, 0.1) were set heuristically.

**At scale:** The scoring model should be learned from historical outcome data rather than set by hand. After 100,000 contacts are worked, there is a labelled dataset: each contact's features at dispatch time and whether they answered, paid, or churned. A logistic regression or gradient-boosted model trained on this data will outperform the hand-tuned formula, especially as the optimal weight between `risk_score` and `propensity_score` varies by DPD bucket (high-DPD contacts need risk weighted more heavily; low-DPD contacts respond better to propensity-based targeting).

The model is wrapped in the same `score(contact) → float` interface so the rest of the engine is unchanged. Model retraining runs nightly on the previous day's outcomes — no real-time training needed.

### 3. Channel Sequencer

**Current:** Config-driven JSON with fixed delay steps. Delays are calendar-time based (e.g. "WhatsApp after 120 minutes").

**At scale:** The delay between channel steps should be personalised. If a contact has answered on WhatsApp at 6pm three times in the past, the sequencer should route their next attempt to WhatsApp at 6pm rather than following the default sequence. This requires a per-contact `engagement_pattern` field — populated by a daily batch job aggregating historical call outcomes — and a sequencer that checks this field before falling back to the campaign default.

At 100,000 contacts, the number of simultaneous pending channel steps becomes large enough to require a proper task queue. APScheduler (used in development) is not horizontally scalable. The production solution is a Celery worker pool with Redis as the broker. Each `{dispatch contact C on channel X at time T}` event is a Celery task. The campaign runner enqueues tasks; Celery workers execute them at the right time, query the DNC set, check the window enforcer, and trigger the telephony API call.

### 4. NBA Engine

**Current:** One Groq call per campaign refresh for top-10 contacts. Works for a 50-contact simulation.

**At scale:** With 100,000 contacts and potentially thousands of concurrent campaigns (KOLLECT + LEADX + AGENTX for multiple enterprise clients), the NBA engine cannot be a per-refresh LLM call per campaign. Two changes are needed.

First, the NBA engine should be **event-driven rather than polling**. Instead of refreshing the top-10 on a timer, it fires when a significant queue event occurs: a contact is answered (score drops to bottom), a high-score contact's last outcome changes, or a callback time arrives. This reduces LLM calls from O(campaigns × time) to O(significant events).

Second, the NBA engine output should be **cached with a TTL**. The top-3 recommendation for a stable queue does not change every few seconds. Caching for 5 minutes and serving the cached result for non-significant events reduces LLM cost by 10–50x at scale.

The NBA prompt structure does not change. It remains a single batch call with top-10 contact summaries — the LLM reasoning quality does not degrade with scale, only the trigger and caching logic changes around it.

---

## Key Architectural Invariants That Must Be Preserved at Scale

Two design decisions in the current architecture must survive the scale-up without compromise:

**DNC check at pop time.** In a distributed system, the temptation is to check DNC at enqueue time (simpler) or periodically (cheaper). Both are wrong. A contact can be added to DNC mid-campaign — by a mid-call request, a TRAI complaint, or a bulk upload from the client. The only safe guarantee is: check the DNC set at the moment of dispatch, in the same atomic operation as the pop. In the Redis implementation, this is `ZPOPMAX` + `SISMEMBER` in a pipeline. If the check fails, `ZADD` the contact back with score -∞ (permanent removal), not just the current score.

**Deterministic channel rules.** The channel sequencer must remain config-driven JSON with no LLM involvement. At 100,000 contacts and real telephony, a non-deterministic channel decision is a compliance risk: if the system dispatches a WhatsApp message at 8:45pm because an LLM "decided" to, and a regulator audits that decision, "the model thought it was a good idea" is not an acceptable answer. Every dispatch decision must be traceable to a specific config rule, a specific contact state, and a specific timestamp — all of which are stored in the attempt log.