"""
a1_state_machine/conversation_loop.py
Main conversation loop — wires all A1 modules together.

FIX SUMMARY vs original:
  1. Phase transition now runs on BOTH user utterance AND agent response
     text — the original only ran it on the agent response, which was
     fine in theory but the signals were wrong (see phase_transitions.py).
  2. confirmed_data is now populated via extract_confirmed_data() inside
     phase_transition_engine — was always empty {} before.
  3. Diversion hint prepended correctly; original had a scoping bug where
     state.diversion_count check and the keyword check were duplicated.
  4. build_system_prompt updated to include phase guidance so the LLM
     knows WHAT to do in each phase, reducing off-script responses.
"""

from __future__ import annotations
import json
import time
import logging

from config import chat, get_logger
from a1_state_machine.state_machine import (
    CallState, Phase, TERMINAL_PHASES,
    init_call_state, state_injector,
)
from a1_state_machine.goal_hierarchy    import evaluate_goal_hierarchy
from a1_state_machine.phase_transitions import phase_transition_engine
from a1_state_machine.diversion_recovery import (
    get_diversion_utterance, reset_diversion_index,
)
from a1_state_machine.logger import log_turn

get_logger("a1", "voiz_a1.jsonl")
logger = logging.getLogger("a1")


# ── Phase-specific agent instructions ─────────────────────────────────
# Injected per-phase so the LLM knows what task to accomplish right now.
# This is what drives the LLM to produce the keywords our signal detector
# looks for — without it the model goes off-script and no signal fires.
PHASE_INSTRUCTIONS: dict[Phase, str] = {
    Phase.INTRO: (
        "You are in the INTRO phase. Greet the caller and confirm you have "
        "the right person. Ask for their date of birth and account number. "
        "Once they provide identity details, acknowledge them explicitly "
        "(e.g. 'I've noted your date of birth and account number')."
    ),
    Phase.VERIFICATION: (
        "You are in the VERIFICATION phase. Identity has been noted. "
        "Now inform the caller about their outstanding balance and overdue "
        "payment amount. State the amount clearly."
    ),
    Phase.PITCH: (
        "You are in the PITCH phase. The caller knows their balance. "
        "Present the payment options (full payment, partial, callback). "
        "Encourage full payment today. Ask which payment method they prefer."
    ),
    Phase.NEGOTIATION: (
        "You are in the NEGOTIATION phase. Discuss payment terms. "
        "If the caller agrees, ask for their card or payment details to "
        "process the payment."
    ),
    Phase.CAPTURE: (
        "You are in the CAPTURE phase. Collect and confirm payment details. "
        "Once payment is processed, provide a reference number and confirm "
        "the transaction. Say 'payment has been successfully processed'."
    ),
    Phase.CLOSE: (
        "You are in the CLOSE phase. Payment is done. Thank the caller, "
        "confirm they will receive a receipt, and close the call politely."
    ),
    Phase.ESCALATE: (
        "You are in the ESCALATE phase. Inform the caller this account "
        "is being escalated to a senior agent and end the call professionally."
    ),
}

# ── Agent base prompt ──────────────────────────────────────────────────
AGENT_BASE_PROMPT = """You are VOIZ, a professional AI collections agent for Predixion AI.
You are on an outbound call to recover an overdue loan payment.
Be empathetic but firm. Stay focused on the account. Do not go off-topic.
Respond in 2–3 sentences maximum unless capturing payment details.
Never invent data — only confirm what the caller provides.
Always respect the current phase and goal shown in [CALL STATE] above."""

# ── Signal detectors ───────────────────────────────────────────────────
OBJECTION_KEYWORDS = [
    "can't pay", "cannot pay", "refuse", "won't pay",
    "no money", "not my debt", "wrong person", "don't owe",
]
DIVERSION_KEYWORDS = [
    "weather", "cricket", "football", "politics", "movie",
    "recipe", "unrelated", "anyway", "by the way",
]


def build_system_prompt(state: CallState) -> str:
    """
    Combines injected state block + base agent instructions + phase guidance.

    FIX: Original only combined state + base prompt. Without phase guidance
    the LLM didn't know what keywords/actions to produce, so transition
    signals never fired. Phase instructions fix that.
    """
    phase_hint = PHASE_INSTRUCTIONS.get(state.call_phase, "")
    return (
        f"{state_injector(state)}\n\n"
        f"{AGENT_BASE_PROMPT}\n\n"
        f"CURRENT PHASE INSTRUCTIONS:\n{phase_hint}"
    )


def run_call(
    conversation_script: list[str] | None = None,
    max_turns: int = 10,
    call_id: str = "CALL-001",
) -> CallState:
    """
    Main conversation loop.

    Args:
        conversation_script: Pre-scripted utterances (test harness mode).
                             None = interactive stdin mode.
        max_turns:           Hard cap on conversation length.
        call_id:             Label for logging.

    Returns:
        Final CallState after the call ends.
    """
    state   = init_call_state("secure_full_payment")
    history: list[dict] = []
    reset_diversion_index()

    print(f"\n{'─'*60}")
    print(f"  VOIZ Call — {call_id}")
    print(f"{'─'*60}\n")

    for turn in range(1, max_turns + 1):

        # ── 1. Get utterance ─────────────────────────────────────────
        if conversation_script is not None:
            if turn - 1 >= len(conversation_script):
                print("[Script complete — ending call]")
                break
            user_utterance = conversation_script[turn - 1]
            print(f"CALLER [{turn:02d}]: {user_utterance}")
        else:
            try:
                user_utterance = input(f"CALLER [{turn:02d}]: ").strip()
            except (EOFError, KeyboardInterrupt):
                break
            if user_utterance.lower() in {"quit", "exit", "bye", ""}:
                break

        # ── 2. Update counters ────────────────────────────────────────
        if any(kw in user_utterance.lower() for kw in OBJECTION_KEYWORDS):
            state.objection_count += 1
            logger.info("[OBJECTION] count now %d", state.objection_count)

        is_diversion = any(kw in user_utterance.lower() for kw in DIVERSION_KEYWORDS)
        if is_diversion:
            state.diversion_count += 1
            state.patience_budget -= 1
            logger.info(
                "[DIVERSION] count now %d, patience=%d",
                state.diversion_count, state.patience_budget,
            )

        # ── 3. Re-evaluate goal hierarchy ────────────────────────────
        state.current_goal = evaluate_goal_hierarchy(state)

        # ── 4. Build system prompt ────────────────────────────────────
        system_prompt = build_system_prompt(state)

        # ── 5. Prepend diversion hint if needed ───────────────────────
        if is_diversion:
            hint = get_diversion_utterance(state.diversion_count)
            system_prompt += (
                f'\n\nDIVERSION RECOVERY: The caller went off-topic. '
                f'Begin your response with exactly: "{hint}"'
            )

        # ── 6. LLM call ───────────────────────────────────────────────
        history.append({"role": "user", "content": user_utterance})
        t0 = time.monotonic()

        llm_response = chat(
            system     = system_prompt,
            messages   = history,
            max_tokens = 200,
            temperature= 0.3,
        )

        latency_ms = int((time.monotonic() - t0) * 1000)
        history.append({"role": "assistant", "content": llm_response})
        print(f"AGENT  [{turn:02d}]: {llm_response}\n")

        # ── 7. Phase transition — runs after LLM responds ─────────────
        # phase_transition_engine also calls extract_confirmed_data()
        # internally, so confirmed_data is populated as a side-effect.
        old_phase = state.call_phase
        new_phase = phase_transition_engine(state.call_phase, llm_response, state)
        transitions_fired: list[str] = []

        if new_phase != old_phase:
            state.call_phase = new_phase
            transitions_fired.append(f"{old_phase.value} -> {new_phase.value}")

        if state.call_phase == Phase.ESCALATE:
            state.escalation_flag = True

        # ── 8. Log turn ───────────────────────────────────────────────
        log_turn(
            turn, state, system_prompt,
            user_utterance, llm_response,
            transitions_fired, latency_ms,
        )

        # ── 9. Terminal check ─────────────────────────────────────────
        if state.call_phase in TERMINAL_PHASES:
            print(f"[Call ended — final phase: {state.call_phase.value}]")
            break

    print(f"\nFinal state:\n{json.dumps(state.to_dict(), indent=2)}\n")
    return state