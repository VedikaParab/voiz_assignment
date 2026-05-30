"""
a1_state_machine/state_machine.py
Core data structures: Phase enum, ALLOWED_TRANSITIONS, CallState dataclass,
init_call_state(), and state_injector().

This file is the foundation — every other A1 module imports from here.
"""

from __future__ import annotations
import json
from dataclasses import dataclass, field
from enum import Enum


# ── 7-Phase Enum ───────────────────────────────────────────────────────

class Phase(str, Enum):
    INTRO        = "INTRO"
    VERIFICATION = "VERIFICATION"
    PITCH        = "PITCH"
    NEGOTIATION  = "NEGOTIATION"
    CAPTURE      = "CAPTURE"
    CLOSE        = "CLOSE"
    ESCALATE     = "ESCALATE"


# Legal transitions — deterministic, never LLM-driven
ALLOWED_TRANSITIONS: dict[Phase, set[Phase]] = {
    Phase.INTRO:        {Phase.VERIFICATION, Phase.ESCALATE},
    Phase.VERIFICATION: {Phase.PITCH, Phase.ESCALATE},
    Phase.PITCH:        {Phase.NEGOTIATION, Phase.CAPTURE, Phase.ESCALATE},
    Phase.NEGOTIATION:  {Phase.CAPTURE, Phase.CLOSE, Phase.ESCALATE},
    Phase.CAPTURE:      {Phase.CLOSE, Phase.ESCALATE},
    Phase.CLOSE:        {Phase.ESCALATE},
    Phase.ESCALATE:     set(),  # terminal
}

TERMINAL_PHASES = {Phase.CLOSE, Phase.ESCALATE}


# ── CallState dataclass — all 7 required variables ─────────────────────

@dataclass
class CallState:
    call_phase:      Phase = Phase.INTRO
    current_goal:    str   = "confirm_identity"
    confirmed_data:  dict  = field(default_factory=dict)
    objection_count: int   = 0
    diversion_count: int   = 0
    escalation_flag: bool  = False
    patience_budget: int   = 3

    def to_dict(self) -> dict:
        return {
            "call_phase":      self.call_phase.value,
            "current_goal":    self.current_goal,
            "confirmed_data":  self.confirmed_data,
            "objection_count": self.objection_count,
            "diversion_count": self.diversion_count,
            "escalation_flag": self.escalation_flag,
            "patience_budget": self.patience_budget,
        }


def init_call_state(primary_goal: str = "secure_full_payment") -> CallState:
    """Returns a fresh CallState at call start."""
    return CallState(
        call_phase      = Phase.INTRO,
        current_goal    = primary_goal,
        confirmed_data  = {},
        objection_count = 0,
        diversion_count = 0,
        escalation_flag = False,
        patience_budget = 3,
    )


# ── State Injector ─────────────────────────────────────────────────────

def state_injector(state: CallState) -> str:
    """
    Serialises full call state into a structured string block.
    Prepended to EVERY LLM system prompt — the model always sees current state.

    Why not rely on conversation history alone?
    → History can drift over many turns; counts are authoritative here.
    → Explicit injection prevents the model from 'forgetting' objection
      counts or agreed amounts from earlier in the call.

    Format matches assignment spec:
      [CALL STATE] Phase | Goal | Objections | Confirmed | Escalation
    """
    confirmed_str = json.dumps(state.confirmed_data) if state.confirmed_data else "none"
    escalation_note = "YES — hand off to human agent immediately" if state.escalation_flag else "no"
    return (
        f"[CALL STATE]\n"
        f"Phase:          {state.call_phase.value}\n"
        f"Goal:           {state.current_goal}\n"
        f"Objections:     {state.objection_count}\n"
        f"Diversions:     {state.diversion_count}\n"
        f"Patience left:  {state.patience_budget}\n"
        f"Confirmed data: {confirmed_str}\n"
        f"Escalation:     {escalation_note}\n"
        f"[/CALL STATE]"
    )