"""
channel_sequencer.py — VOIZ A4 Campaign Engine
Config-driven channel sequencer. Reads channel_config.json.
sequence(contact, last_outcome) → {channel, delay_minutes, reason}
No hardcoded rules — all logic driven by JSON config.
"""

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Any, Optional


CONFIG_PATH = Path(__file__).parent / "data" / "channel_config.json"


class ChannelSequencer:
    """
    Determines the next channel and delay for a contact based on:
    - Their last contact outcome
    - Their preferred channel (for tie-breaking / personalisation)
    - Campaign-level channel_sequences config

    Config is loaded once at init; call reload_config() to hot-reload.
    """

    def __init__(self, config_path: Path = CONFIG_PATH):
        self._config_path = config_path
        self.config: Dict[str, Any] = {}
        self.reload_config()

    def reload_config(self) -> None:
        """Load / reload channel config from JSON. Safe to call mid-run."""
        with open(self._config_path) as f:
            self.config = json.load(f)

    # ── Main API ───────────────────────────────────────────────────────────────
    def next_step(
        self,
        contact: Dict[str, Any],
        attempt_number: int = 0,
    ) -> Optional[Dict[str, Any]]:
        """
        Return the next channel action for a contact.

        Parameters
        ----------
        contact       : contact dict (must have last_contact_outcome)
        attempt_number: 0-based index into the outcome's channel sequence

        Returns
        -------
        {channel, delay_minutes, reason} or None if sequence exhausted / DNC
        """
        outcome = contact.get("last_contact_outcome", "NO_ANSWER")
        sequences: Dict[str, list] = self.config.get("channel_sequences", {})

        # DNC → never dispatch
        if outcome == "DNC":
            return None

        seq = sequences.get(outcome, sequences.get("NO_ANSWER", []))

        if attempt_number >= len(seq):
            # Sequence exhausted — wrap back to first step after max_attempts check
            max_attempts = self.config.get("max_attempts_per_contact", 5)
            total_attempts = contact.get("total_attempts", 0)
            if total_attempts >= max_attempts:
                return None
            # Restart sequence from step 0
            attempt_number = 0

        if not seq:
            return None

        step = seq[attempt_number]
        channel = step["channel"]
        delay   = step["delay_minutes"]

        # Personalise: prefer contact's preferred_channel on step 0 if it matches any step
        if attempt_number == 0:
            preferred = contact.get("preferred_channel", "voice")
            preferred_step = next(
                (s for s in seq if s["channel"] == preferred), None
            )
            if preferred_step and preferred_step != step:
                # Swap to preferred channel at step 0 but keep configured delay
                channel = preferred_step["channel"]
                delay   = preferred_step.get("delay_minutes", 0)

        return {
            "channel": channel,
            "delay_minutes": delay,
            "dispatch_after": (
                datetime.now() + timedelta(minutes=delay)
            ).isoformat(),
            "reason": f"outcome={outcome}, step={attempt_number}",
        }

    def callback_hold(self) -> int:
        """Return configured callback hold time in minutes."""
        return self.config.get("callback_hold_minutes", 240)

    def max_attempts(self) -> int:
        return self.config.get("max_attempts_per_contact", 5)

    def all_channels_for_outcome(self, outcome: str) -> list[str]:
        """Return ordered list of channels for a given outcome."""
        sequences = self.config.get("channel_sequences", {})
        seq = sequences.get(outcome, [])
        return [s["channel"] for s in seq]


# ── CLI smoke test ─────────────────────────────────────────────────────────────
if __name__ == "__main__":
    cs = ChannelSequencer()

    test_contacts = [
        {"contact_id": "C001", "name": "Arjun",  "last_contact_outcome": "NO_ANSWER",         "preferred_channel": "voice"},
        {"contact_id": "C002", "name": "Priya",  "last_contact_outcome": "CALLBACK_REQUESTED","preferred_channel": "whatsapp"},
        {"contact_id": "C004", "name": "Sunita", "last_contact_outcome": "ANSWERED",           "preferred_channel": "sms"},
        {"contact_id": "C999", "name": "DNC Guy","last_contact_outcome": "DNC",                "preferred_channel": "voice"},
    ]

    print("=== Channel Sequencer Smoke Test ===\n")
    for c in test_contacts:
        for step in range(4):
            result = cs.next_step(c, attempt_number=step)
            if result:
                print(f"  {c['contact_id']} | outcome={c['last_contact_outcome']:<20} | "
                      f"step={step} → channel={result['channel']:<10} delay={result['delay_minutes']}min")
            else:
                print(f"  {c['contact_id']} | outcome={c['last_contact_outcome']:<20} | step={step} → None (exhausted/DNC)")
                break
    print()
    print(f"Callback hold: {cs.callback_hold()} min")
    print(f"Max attempts:  {cs.max_attempts()}")