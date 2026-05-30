"""
a1_state_machine/diversion_recovery.py
Diversion recovery utterances.

Cycles through list per diversion level — never repeats until all
utterances at that level are exhausted (cycle, not random).
"""

from __future__ import annotations

DIVERSION_UTTERANCES: dict[int, list[str]] = {
    1: [
        "I understand — let me bring us back to the main reason for my call today.",
        "That's noted. To make the most of your time, let me refocus on your account.",
        "I hear you. Coming back to why I'm calling — your account balance.",
    ],
    2: [
        "I appreciate your patience. It's important we address this before we run out of time.",
        "Let me be direct — I need to confirm a resolution on this call if possible.",
        "I understand there's a lot on your mind. This will only take a moment more.",
    ],
    3: [
        "I want to help resolve this today. Let's focus on finding a path forward.",
        "I can see this is frustrating — the quickest way through is to resolve this now.",
        "I'll be honest: this is the last attempt before I have to escalate this account.",
    ],
}

# Per-call rotation index — reset via reset_diversion_index() at call start
_diversion_index: dict[int, int] = {1: 0, 2: 0, 3: 0}


def get_diversion_utterance(diversion_count: int) -> str:
    """
    Returns next re-engagement utterance for the given diversion level.
    Cycles through the list — never repeats until all are used once.
    """
    level = min(max(diversion_count, 1), 3)
    utterances = DIVERSION_UTTERANCES[level]
    idx = _diversion_index[level] % len(utterances)
    utterance = utterances[idx]
    _diversion_index[level] = idx + 1
    return utterance


def reset_diversion_index() -> None:
    """Call at the start of each new call to reset the rotation."""
    for k in _diversion_index:
        _diversion_index[k] = 0