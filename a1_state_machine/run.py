"""
voiz/a1_state_machine/run.py
Single entry point.

Run:
  python a1_state_machine/run.py           # live interactive call
  python a1_state_machine/run.py --test    # 3 simulated test calls
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from config import get_logger
get_logger("a1", "voiz_a1.jsonl")

if __name__ == "__main__":
    if "--test" in sys.argv:
        from a1_state_machine.test_harness import (
            test_cooperative_call,
            test_resistant_call,
            test_escalated_call,
        )
        test_cooperative_call()
        test_resistant_call()
        test_escalated_call()
        print("\n" + "=" * 60)
        print("ALL 3 SCENARIOS COMPLETE")
        print("=" * 60)
    else:
        from a1_state_machine.conversation_loop import run_call
        run_call(max_turns=12, call_id="CALL-LIVE")