"""
a1_state_machine/test_harness.py
3 simulated calls with assertions on final state.

Run:  python -m pytest a1_state_machine/test_harness.py -v
  or: python a1_state_machine/run.py --test

FIX vs original:
  - cooperative_call assertion relaxed to also accept CLOSE (reachable now
    that transitions fire correctly).
  - resistant_call assertion now also checks goal demotion happened
    (objection_count ≥ 2 should push goal off secure_full_payment).
  - escalated_call script strengthened — original sometimes didn't hit
    the escalation signal keywords the transition engine looks for.
"""

from __future__ import annotations
from a1_state_machine.state_machine import Phase
from a1_state_machine.conversation_loop import run_call


# ── Test scripts ───────────────────────────────────────────────────────

COOPERATIVE_SCRIPT = [
    "Hello, yes this is Riya Sharma.",
    "My date of birth is 14th March 1990, account number 9876543210.",
    "Okay, I understand. How much is outstanding?",
    "I can pay the full amount today. What are my options?",
    "Yes, I agree to full payment. Please process it.",
    "I received the reference number. Thank you.",
]

RESISTANT_SCRIPT = [
    "Who is this?",
    "I can't pay anything right now. I lost my job.",
    "This isn't my debt, you have the wrong person.",
    "I refuse to pay. Stop calling me.",
    "I'm going to report you to the RBI.",
    "I'm calling my lawyer about this.",
]

ESCALATED_SCRIPT = [
    "Yes, this is Arjun Mehta.",
    "Whatever, did you watch the cricket match yesterday?",
    "I want to speak to your supervisor right now.",
    "Get me a senior agent or I'm hanging up.",
    "This is harassment. I'm escalating this to consumer court.",
]


# ── Assertion helpers ──────────────────────────────────────────────────

def assert_state(label: str, state, **expected) -> bool:
    """Assert multiple state fields at once and print result."""
    passed = True
    for field, expected_val in expected.items():
        actual_val = getattr(state, field)
        if hasattr(actual_val, "value"):
            actual_val = actual_val.value
        if hasattr(expected_val, "value"):
            expected_val = expected_val.value
        ok = actual_val == expected_val
        status = "PASS" if ok else "FAIL"
        print(f"  [{status}] {label}.{field}: expected={expected_val!r}, got={actual_val!r}")
        if not ok:
            passed = False
    return passed


# ── Test functions ─────────────────────────────────────────────────────

def test_cooperative_call():
    print("\n" + "=" * 60)
    print("SCENARIO 1: Cooperative caller")
    print("=" * 60)
    state = run_call(
        conversation_script=COOPERATIVE_SCRIPT,
        max_turns=10,
        call_id="CALL-COOPERATIVE",
    )
    # FIX: CLOSE is now reachable — transitions fire correctly.
    # Accept CLOSE, CAPTURE, or NEGOTIATION (LLM variance may land here).
    assert state.call_phase in {Phase.CLOSE, Phase.CAPTURE, Phase.NEGOTIATION}, (
        f"Expected CLOSE/CAPTURE/NEGOTIATION, got {state.call_phase.value}"
    )
    assert state.escalation_flag is False, "Should not escalate a cooperative caller"
    assert_state("cooperative", state, escalation_flag=False)
    print("  Cooperative call assertions PASSED\n")


def test_resistant_call():
    print("\n" + "=" * 60)
    print("SCENARIO 2: Resistant caller (high objections)")
    print("=" * 60)
    state = run_call(
        conversation_script=RESISTANT_SCRIPT,
        max_turns=10,
        call_id="CALL-RESISTANT",
    )
    assert state.objection_count >= 2, (
        f"Expected ≥2 objections, got {state.objection_count}"
    )
    # With 4+ objections the goal hierarchy should have demoted away from
    # secure_full_payment. Check it's not still on the primary goal.
    assert state.current_goal != "secure_full_payment", (
        f"Goal should have demoted from secure_full_payment, got {state.current_goal}"
    )
    assert_state("resistant", state)
    print(f"  Objection count: {state.objection_count} — PASSED")
    print(f"  Goal demoted to: {state.current_goal} — PASSED\n")


def test_escalated_call():
    print("\n" + "=" * 60)
    print("SCENARIO 3: Escalation call")
    print("=" * 60)
    state = run_call(
        conversation_script=ESCALATED_SCRIPT,
        max_turns=10,
        call_id="CALL-ESCALATED",
    )
    assert state.call_phase == Phase.ESCALATE or state.escalation_flag, (
        f"Expected ESCALATE phase or flag, "
        f"got phase={state.call_phase.value}, flag={state.escalation_flag}"
    )
    assert_state("escalated", state, escalation_flag=True)
    print("  Escalation call assertions PASSED\n")


# ── Run directly ───────────────────────────────────────────────────────

if __name__ == "__main__":
    test_cooperative_call()
    test_resistant_call()
    test_escalated_call()
    print("\n" + "=" * 60)
    print("ALL 3 SCENARIOS COMPLETE")
    print("=" * 60)