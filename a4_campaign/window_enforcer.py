"""
window_enforcer.py — VOIZ A4 Campaign Engine
Call window enforcement: is_dispatchable(contact, config) → bool.
Checks current IST time against permitted_windows in campaign config.
Never blocks execution — returns False to defer, True to dispatch.
Compliant with TRAI TCCCPR 2018 (9am–8pm, no Sundays for commercial calls).
"""

from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Optional
import logging

logger = logging.getLogger(__name__)

# IST = UTC+5:30
IST = timezone(timedelta(hours=5, minutes=30))

# TRAI hard limits — these override any campaign config
TRAI_START_HOUR = 9   # 9:00 AM IST
TRAI_END_HOUR   = 20  # 8:00 PM IST (exclusive)
TRAI_BLOCKED_DAYS = {"Sunday"}  # 0=Monday in isoweekday (7=Sunday)


class WindowEnforcer:
    """
    Determines whether a contact can be dispatched RIGHT NOW.

    Rules (in priority order):
    1. TRAI hard limits always apply (9am–8pm IST, no Sundays).
    2. Campaign-level permitted_windows from config.
    3. Contact-level opt-out window (optional field: contact_opt_out_start / contact_opt_out_end).

    Returns False (defer) if ANY rule blocks. Never raises — safe to call in hot path.
    """

    def __init__(self, strict_trai: bool = True):
        """
        strict_trai: if True, TRAI limits override campaign config.
                     Set False only in test environments.
        """
        self.strict_trai = strict_trai

    # ── Main API ───────────────────────────────────────────────────────────────
    def is_dispatchable(
        self,
        contact: Dict[str, Any],
        campaign_config: Dict[str, Any],
        now_ist: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        """
        Check if a contact can be dispatched now.

        Returns
        -------
        {
            "dispatchable": bool,
            "reason": str,          # why blocked (or "OK")
            "retry_after_ist": str  # ISO timestamp of next window open (if blocked)
        }
        """
        now = now_ist or datetime.now(IST)

        # ── 1. TRAI hard limits ────────────────────────────────────────────────
        if self.strict_trai:
            trai_check = self._check_trai(now)
            if not trai_check["ok"]:
                return {
                    "dispatchable": False,
                    "reason": trai_check["reason"],
                    "retry_after_ist": trai_check["retry_after"],
                }

        # ── 2. Campaign permitted_windows ─────────────────────────────────────
        permitted = campaign_config.get("permitted_windows", {})
        campaign_check = self._check_campaign_window(now, permitted)
        if not campaign_check["ok"]:
            return {
                "dispatchable": False,
                "reason": campaign_check["reason"],
                "retry_after_ist": campaign_check["retry_after"],
            }

        # ── 3. Contact opt-out window ─────────────────────────────────────────
        opt_check = self._check_contact_optout(now, contact)
        if not opt_check["ok"]:
            return {
                "dispatchable": False,
                "reason": opt_check["reason"],
                "retry_after_ist": opt_check["retry_after"],
            }

        return {
            "dispatchable": True,
            "reason": "OK",
            "retry_after_ist": None,
        }

    # ── TRAI check ─────────────────────────────────────────────────────────────
    def _check_trai(self, now: datetime) -> Dict[str, Any]:
        day_name = now.strftime("%A")  # e.g. "Sunday"
        hour     = now.hour

        if day_name in TRAI_BLOCKED_DAYS:
            # Next Monday 9am
            days_until_monday = (7 - now.weekday()) % 7 or 7
            retry = now.replace(hour=TRAI_START_HOUR, minute=0, second=0, microsecond=0) + timedelta(days=days_until_monday)
            return {"ok": False, "reason": f"TRAI: no calls on {day_name}", "retry_after": retry.isoformat()}

        if hour < TRAI_START_HOUR:
            retry = now.replace(hour=TRAI_START_HOUR, minute=0, second=0, microsecond=0)
            return {"ok": False, "reason": f"TRAI: before 9am IST (current={now.strftime('%H:%M')})", "retry_after": retry.isoformat()}

        if hour >= TRAI_END_HOUR:
            # Next day 9am (skip Sunday)
            retry = now.replace(hour=TRAI_START_HOUR, minute=0, second=0, microsecond=0) + timedelta(days=1)
            if retry.strftime("%A") == "Sunday":
                retry += timedelta(days=1)
            return {"ok": False, "reason": f"TRAI: after 8pm IST (current={now.strftime('%H:%M')})", "retry_after": retry.isoformat()}

        return {"ok": True, "reason": "TRAI OK", "retry_after": None}

    # ── Campaign window check ──────────────────────────────────────────────────
    def _check_campaign_window(self, now: datetime, permitted: Dict[str, Any]) -> Dict[str, Any]:
        if not permitted:
            return {"ok": True, "reason": "no campaign window config", "retry_after": None}

        day_name   = now.strftime("%A")
        hour       = now.hour
        start_hour = permitted.get("start_hour_ist", TRAI_START_HOUR)
        end_hour   = permitted.get("end_hour_ist",   TRAI_END_HOUR)
        allowed_days: list = permitted.get("days", [
            "Monday","Tuesday","Wednesday","Thursday","Friday","Saturday"
        ])

        if day_name not in allowed_days:
            # Find next allowed day
            retry = self._next_allowed_day(now, allowed_days, start_hour)
            return {"ok": False, "reason": f"Campaign: {day_name} not in permitted days", "retry_after": retry}

        if hour < start_hour:
            retry = now.replace(hour=start_hour, minute=0, second=0, microsecond=0).isoformat()
            return {"ok": False, "reason": f"Campaign: before {start_hour}:00 IST", "retry_after": retry}

        if hour >= end_hour:
            base = now.replace(hour=start_hour, minute=0, second=0, microsecond=0) + timedelta(days=1)
            retry = self._next_allowed_day_from(base, allowed_days)
            return {"ok": False, "reason": f"Campaign: after {end_hour}:00 IST", "retry_after": retry}

        return {"ok": True, "reason": "campaign window OK", "retry_after": None}

    # ── Contact opt-out window ─────────────────────────────────────────────────
    def _check_contact_optout(self, now: datetime, contact: Dict[str, Any]) -> Dict[str, Any]:
        opt_start = contact.get("opt_out_start_hour_ist")
        opt_end   = contact.get("opt_out_end_hour_ist")

        if opt_start is None or opt_end is None:
            return {"ok": True, "reason": "no contact opt-out window", "retry_after": None}

        hour = now.hour
        if opt_start <= hour < opt_end:
            retry = now.replace(hour=opt_end, minute=0, second=0, microsecond=0).isoformat()
            return {
                "ok": False,
                "reason": f"Contact opt-out: {opt_start}:00–{opt_end}:00 IST",
                "retry_after": retry,
            }

        return {"ok": True, "reason": "contact opt-out OK", "retry_after": None}

    # ── Helpers ────────────────────────────────────────────────────────────────
    @staticmethod
    def _next_allowed_day(now: datetime, allowed_days: list, start_hour: int) -> str:
        candidate = now + timedelta(days=1)
        for _ in range(8):
            if candidate.strftime("%A") in allowed_days:
                return candidate.replace(hour=start_hour, minute=0, second=0, microsecond=0).isoformat()
            candidate += timedelta(days=1)
        return (now + timedelta(days=1)).isoformat()

    @staticmethod
    def _next_allowed_day_from(base: datetime, allowed_days: list) -> str:
        for _ in range(8):
            if base.strftime("%A") in allowed_days:
                return base.isoformat()
            base += timedelta(days=1)
        return base.isoformat()

    def seconds_until_window(self, campaign_config: Dict[str, Any]) -> int:
        """Return seconds until next dispatch window opens (0 if open now)."""
        result = self.is_dispatchable({}, campaign_config)
        if result["dispatchable"]:
            return 0
        retry = result.get("retry_after_ist")
        if not retry:
            return 3600  # default 1hr
        try:
            retry_dt = datetime.fromisoformat(retry)
            diff = (retry_dt - datetime.now(IST)).total_seconds()
            return max(int(diff), 0)
        except Exception:
            return 3600


# ── CLI smoke test ─────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import json
    from pathlib import Path

    config = json.loads((Path(__file__).parent / "data" / "channel_config.json").read_text())
    we = WindowEnforcer()

    test_cases = [
        ("Weekday 10am",  datetime(2026, 5, 25, 10, 0, tzinfo=IST)),   # Monday
        ("Weekday 8pm",   datetime(2026, 5, 25, 20, 0, tzinfo=IST)),   # Monday after close
        ("Sunday noon",   datetime(2026, 5, 24, 12, 0, tzinfo=IST)),   # Sunday
        ("Weekday 8am",   datetime(2026, 5, 25,  8, 0, tzinfo=IST)),   # Before open
    ]

    print("=== Window Enforcer Smoke Test ===\n")
    contact = {"contact_id": "C001"}
    for label, t in test_cases:
        result = we.is_dispatchable(contact, config, now_ist=t)
        status = "✅ DISPATCH" if result["dispatchable"] else f"⏸  DEFERRED"
        print(f"  {label:<20} → {status}  | {result['reason']}")
        if not result["dispatchable"] and result.get("retry_after_ist"):
            print(f"                         retry after: {result['retry_after_ist']}")