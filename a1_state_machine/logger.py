"""
a1_state_machine/logger.py
Structured JSON logger — one entry per conversation turn.
Output: logs/voiz_a1.jsonl
"""

from __future__ import annotations
import json
import logging
from a1_state_machine.state_machine import CallState

logger = logging.getLogger("a1")


def log_turn(
    turn: int,
    state: CallState,
    state_string: str,
    user_utterance: str,
    llm_response: str,
    transitions_fired: list[str],
    latency_ms: int,
) -> None:
    """
    Writes one structured JSON line per turn to the a1 logger.
    Fields match the assignment spec exactly:
      { turn, phase, goal, state_injected, user_utterance,
        llm_response, transitions_fired, latency_ms, state_snapshot }
    """
    entry = {
        "turn":              turn,
        "phase":             state.call_phase.value,
        "goal":              state.current_goal,
        "state_injected":    state_string,
        "user_utterance":    user_utterance,
        "llm_response":      llm_response,
        "transitions_fired": transitions_fired,
        "latency_ms":        latency_ms,
        "state_snapshot":    state.to_dict(),
    }
    logger.info("[TURN %02d] %s", turn, json.dumps(entry, ensure_ascii=False))