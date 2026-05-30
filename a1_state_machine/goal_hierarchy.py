"""
a1_state_machine/goal_hierarchy.py
Goal hierarchy engine: ordered list of (goal_name, reachability_fn).

At each turn, the first reachable goal wins.
Every demotion (goal changes downward) is logged.

Goal ladder (primary → fallbacks):
  1. secure_full_payment      — primary; viable when objections ≤ 2
  2. secure_partial_payment   — first fallback; viable when objections ≤ 4
  3. schedule_callback        — second fallback; viable unless ESCALATE
  4. log_hardship_and_escalate — ultimate fallback; always reachable
"""

from __future__ import annotations
import logging
from typing import Callable
from a1_state_machine.state_machine import CallState, Phase

logger = logging.getLogger("a1")

GOAL_HIERARCHY: list[tuple[str, Callable[[CallState], bool]]] = [
    (
        "secure_full_payment",
        lambda s: s.objection_count <= 2 and s.call_phase not in {Phase.ESCALATE},
    ),
    (
        "secure_partial_payment",
        lambda s: s.objection_count <= 4 and s.call_phase not in {Phase.ESCALATE},
    ),
    (
        "schedule_callback",
        lambda s: s.call_phase not in {Phase.ESCALATE},
    ),
    (
        "log_hardship_and_escalate",
        lambda s: True,  # always reachable — final fallback
    ),
]


def evaluate_goal_hierarchy(state: CallState) -> str:
    """
    Returns the name of the first reachable goal.
    Logs every demotion when current_goal changes downward.
    """
    for goal_name, is_reachable in GOAL_HIERARCHY:
        if is_reachable(state):
            if goal_name != state.current_goal:
                logger.info(
                    "[GOAL DEMOTION] %s -> %s  (objections=%d, phase=%s)",
                    state.current_goal,
                    goal_name,
                    state.objection_count,
                    state.call_phase.value,
                )
            return goal_name

    return "log_hardship_and_escalate"