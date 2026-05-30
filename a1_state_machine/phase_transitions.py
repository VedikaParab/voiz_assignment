"""
a1_state_machine/phase_transitions.py
Phase transition engine — pure deterministic function.

FIX: The original signal keywords were too narrow — they looked for exact
phrases like "verified", "confirmed identity" that the LLM never actually
produces. Expanded to match the real vocabulary the LLM uses when
acknowledging identity info, pitch responses, payment agreements, etc.

Also added: confirmed_data extraction — parse DOB / account number from
LLM responses and write them into state.confirmed_data.
"""

from __future__ import annotations
import re
import logging
from a1_state_machine.state_machine import CallState, Phase, ALLOWED_TRANSITIONS

logger = logging.getLogger("a1")

# ── Transition signal table ────────────────────────────────────────────
# Each entry: (list_of_trigger_substrings, next_phase)
# All matches are case-insensitive substring checks on the LLM response.
# Keywords expanded to match actual LLM output vocabulary.
#
# WHY: Original keywords ("verified", "confirmed identity") were never
# produced by the LLM. The LLM says things like "I've noted your date of
# birth" or "I've confirmed your account details" — those are matched now.

TRANSITION_SIGNALS: dict[Phase, list[tuple[list[str], Phase]]] = {
    Phase.INTRO: [
        (
            # Agent acknowledges the caller's identity info → go to VERIFICATION
            [
                "noted your date of birth",
                "noted your dob",
                "noted your account",
                "account number",
                "date of birth",
                "i've noted",
                "i have noted",
                "thank you for confirming",
                "confirmed your",
                "identity confirmed",
                "verified",
                "confirmed identity",
            ],
            Phase.VERIFICATION,
        ),
        (
            ["escalate", "supervisor", "legal action", "complaint", "lawyer", "rbi"],
            Phase.ESCALATE,
        ),
    ],
    Phase.VERIFICATION: [
        (
            # Agent moves past identity check and into the payment discussion
            [
                "outstanding balance",
                "overdue amount",
                "overdue payment",
                "outstanding amount",
                "amount due",
                "payment due",
                "verification complete",
                "details confirmed",
                "dob match",
                "account confirmed",
                "how much is outstanding",
                "outstanding on your account",
                "status of the overdue",
            ],
            Phase.PITCH,
        ),
        (
            ["cannot verify", "wrong person", "not the account holder", "escalate"],
            Phase.ESCALATE,
        ),
    ],
    Phase.PITCH: [
        (
            # Caller shows interest / asks payment options → NEGOTIATION
            [
                "what options",
                "payment options",
                "payment method",
                "how can i pay",
                "credit",
                "debit",
                "bank transfer",
                "which payment",
                "interested",
                "tell me more",
                "how much",
            ],
            Phase.NEGOTIATION,
        ),
        (
            # Caller agrees to pay outright → skip NEGOTIATION, go to CAPTURE
            [
                "agree to full payment",
                "process it",
                "full payment today",
                "pay the full amount",
                "yes i will pay",
                "pay now",
                "process the payment",
                "please process",
            ],
            Phase.CAPTURE,
        ),
        (
            ["refuse", "not paying", "wrong person", "escalate"],
            Phase.ESCALATE,
        ),
    ],
    Phase.NEGOTIATION: [
        (
            # Payment confirmed — move to capture
            [
                "card details",
                "card number",
                "provide me with your",
                "please provide",
                "process the full payment",
                "i'll process",
                "will process",
                "agreed",
                "accepted",
                "deal",
                "partial payment",
                "i will pay",
            ],
            Phase.CAPTURE,
        ),
        (
            ["final payment", "close account", "settlement done"],
            Phase.CLOSE,
        ),
        (
            ["lawyer", "consumer court", "rbi", "escalate"],
            Phase.ESCALATE,
        ),
    ],
    Phase.CAPTURE: [
        (
            # Payment reference issued — call is closed
            [
                "reference number",
                "payment confirmed",
                "receipt",
                "transaction id",
                "successfully processed",
                "confirmation email",
                "payment of",
                "has been processed",
            ],
            Phase.CLOSE,
        ),
        (
            ["escalate", "cancel"],
            Phase.ESCALATE,
        ),
    ],
    Phase.CLOSE: [
        (
            ["escalate", "not happy", "complaint", "wrong amount"],
            Phase.ESCALATE,
        ),
    ],
    Phase.ESCALATE: [],  # terminal — no further transitions
}


# ── Confirmed-data extractor ───────────────────────────────────────────
# Regex patterns to pull structured data out of LLM echoes.
# The LLM repeats what the caller said ("I've noted your DOB as..."),
# so we extract from the agent response to update confirmed_data.

_DOB_RE = re.compile(
    r"(?:date of birth|dob)[^\d]*"           # label
    r"(\d{1,2}(?:st|nd|rd|th)?\s+\w+\s+\d{4}"  # "14th March 1990"
    r"|\d{1,2}[/-]\d{1,2}[/-]\d{2,4})",     # or "14/03/1990"
    re.IGNORECASE,
)
_ACCOUNT_RE = re.compile(
    r"account number[^\d]*(\d{6,12})",
    re.IGNORECASE,
)
_AMOUNT_RE = re.compile(
    # Must be preceded by amount/balance/payment keywords but NOT 'account number'
    r"(?<!account\s)(?<!account number\s)"
    r"(?:outstanding amount|outstanding balance|overdue amount|amount due"
    r"|total amount|payment of|balance of)[^\d₹$]*[₹$]?\s*([\d,]+(?:\.\d{2})?)",
    re.IGNORECASE,
)


def extract_confirmed_data(llm_response: str, state: CallState) -> None:
    """
    Parses DOB, account number, and payment amount out of the LLM response
    and writes them into state.confirmed_data in-place.

    FIX: confirmed_data was always {} because nothing ever populated it.
    """
    text = llm_response

    dob_match = _DOB_RE.search(text)
    if dob_match and "dob" not in state.confirmed_data:
        state.confirmed_data["dob"] = dob_match.group(1).strip()
        logger.info("[DATA] Extracted DOB: %s", state.confirmed_data["dob"])

    acc_match = _ACCOUNT_RE.search(text)
    if acc_match and "account_number" not in state.confirmed_data:
        state.confirmed_data["account_number"] = acc_match.group(1).strip()
        logger.info("[DATA] Extracted account: %s", state.confirmed_data["account_number"])

    amt_match = _AMOUNT_RE.search(text)
    if amt_match and "amount" not in state.confirmed_data:
        state.confirmed_data["amount"] = amt_match.group(1).strip()
        logger.info("[DATA] Extracted amount: %s", state.confirmed_data["amount"])


# ── Phase transition engine ────────────────────────────────────────────

def phase_transition_engine(
    current_phase: Phase,
    llm_response: str,
    state: CallState,
) -> Phase:
    """
    Pure deterministic function: evaluates LLM response text for
    transition signals. Hard counter-based rules checked first.

    FIX: Signals now match actual LLM output vocabulary, not idealised
    phrases that the model never produces.

    Args:
        current_phase: The phase the call is currently in.
        llm_response:  The agent's latest response text.
        state:         Full call state (for counter-based hard rules).

    Returns:
        next_phase — may equal current_phase if no signal fires.
    """
    text = llm_response.lower()

    # ── Hard counter rules — override everything ───────────────────────
    if state.objection_count >= 5:
        logger.info("[TRANSITION] objection_count=%d >= 5 -> ESCALATE", state.objection_count)
        return Phase.ESCALATE

    if state.patience_budget <= 0:
        logger.info("[TRANSITION] patience_budget exhausted -> ESCALATE")
        return Phase.ESCALATE

    # ── Extract any structured data from this response ─────────────────
    extract_confirmed_data(llm_response, state)

    # ── Signal-based transitions ───────────────────────────────────────
    for keywords, next_phase in TRANSITION_SIGNALS.get(current_phase, []):
        if any(kw in text for kw in keywords):
            allowed = ALLOWED_TRANSITIONS.get(current_phase, set())
            if next_phase in allowed:
                matched_kw = next((kw for kw in keywords if kw in text), "?")
                logger.info(
                    "[TRANSITION] %s -> %s  (signal: '%s')",
                    current_phase.value, next_phase.value, matched_kw,
                )
                return next_phase

    return current_phase  # no signal matched — stay in phase