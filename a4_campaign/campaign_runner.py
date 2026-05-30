"""
campaign_runner.py — VOIZ A4 Campaign Engine
Orchestration layer: loads contacts → scores → queues → enforces window →
sequences channels → dispatches (simulated) → logs outcomes → re-scores.

Run standalone for a 20-attempt simulation:
    python campaign_runner.py

Or import CampaignRunner and drive it from app.py (Streamlit).
"""

import json
import random
import logging
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, Any, Optional

from scorer import score_all, score
from priority_queue import CampaignPriorityQueue
from dnc_manager import DNCManager
from channel_sequencer import ChannelSequencer
from window_enforcer import WindowEnforcer, IST
from nba_engine import next_best_actions

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# Paths
DATA_DIR     = Path(__file__).parent / "data"
CONTACTS_PATH = DATA_DIR / "contacts.json"
CONFIG_PATH   = DATA_DIR / "channel_config.json"
LOG_DIR       = Path(__file__).parent / "logs"
LOG_DIR.mkdir(exist_ok=True)

# Simulated outcome distribution (realistic collections rates)
_OUTCOME_WEIGHTS = {
    "ANSWERED":           0.35,
    "NO_ANSWER":          0.45,
    "CALLBACK_REQUESTED": 0.15,
    "DNC":                0.05,
}

# 60% of ANSWERED contacts make actual payment commitment (RPC)
RPC_RATE = 0.60


class CampaignRunner:
    """
    Full campaign orchestration engine.

    Usage:
        runner = CampaignRunner()
        runner.load_contacts()
        runner.start()
        # Then call runner.dispatch_next() in a loop or from scheduler
    """

    def __init__(
        self,
        contacts_path: Path = CONTACTS_PATH,
        config_path: Path   = CONFIG_PATH,
        bypass_window: bool = False,   # True = ignore time window (for demo/testing)
    ):
        self.contacts_path  = contacts_path
        self.config_path    = config_path
        self.bypass_window  = bypass_window

        # Sub-modules
        self.dnc        = DNCManager()
        self.pq         = CampaignPriorityQueue(dnc_manager=self.dnc)
        self.sequencer  = ChannelSequencer(config_path)
        self.enforcer   = WindowEnforcer()

        # Campaign config
        self.config: Dict[str, Any] = {}
        self._load_config()

        # State
        self.contacts:      list[Dict[str, Any]] = []
        self.attempt_log:   list[Dict[str, Any]] = []
        self.queue_snapshots: list[Dict[str, Any]] = []
        self.started_at:    Optional[datetime]   = None
        self.attempt_count: int = 0
        self._contact_attempts: Dict[str, int] = {}  # contact_id → attempt count

    # ── Loaders ────────────────────────────────────────────────────────────────
    def _load_config(self) -> None:
        with open(self.config_path) as f:
            self.config = json.load(f)

    def load_contacts(self, contacts: Optional[list] = None) -> int:
        """Score and load contacts into the priority queue."""
        raw = contacts or json.loads(self.contacts_path.read_text())
        self.contacts = score_all(raw)

        for c in self.contacts:
            self.pq.push(c, c["priority_score"])
            self._contact_attempts[c["contact_id"]] = 0

        logger.info(f"Loaded {len(self.contacts)} contacts into queue (size={len(self.pq)})")
        return len(self.contacts)

    def start(self) -> None:
        self.started_at = datetime.now(IST)
        logger.info(f"Campaign '{self.config.get('campaign_name','?')}' started at {self.started_at.strftime('%Y-%m-%d %H:%M IST')}")

    # ── Core dispatch ──────────────────────────────────────────────────────────
    def dispatch_next(self, force_window: bool = False) -> Optional[Dict[str, Any]]:
        """
        Pop the highest-priority contact and simulate a call attempt.
        Returns the attempt log entry, or None if queue empty / window blocked.

        force_window: bypass window check (for simulation/testing).
        """
        # Window check
        if not self.bypass_window and not force_window:
            window_result = self.enforcer.is_dispatchable({}, self.config)
            if not window_result["dispatchable"]:
                logger.warning(f"Window blocked: {window_result['reason']} | retry after {window_result.get('retry_after_ist','?')}")
                return None

        contact = self.pq.pop()
        if contact is None:
            logger.info("Queue empty — no contacts to dispatch.")
            return None

        cid = contact["contact_id"]
        self._contact_attempts[cid] = self._contact_attempts.get(cid, 0) + 1
        attempt_num = self._contact_attempts[cid]

        # Determine channel for this attempt
        channel_step = self.sequencer.next_step(contact, attempt_number=attempt_num - 1)
        channel = channel_step["channel"] if channel_step else contact.get("preferred_channel", "voice")

        # Simulate outcome
        outcome = self._simulate_outcome(contact)
        is_rpc  = (outcome == "ANSWERED") and (random.random() < RPC_RATE)

        # Handle DNC mid-run
        if outcome == "DNC":
            self.dnc.add(contact["phone"], reason="mid_call_dnc", source="campaign_runner")
            logger.info(f"⛔ DNC triggered mid-run for {cid} ({contact['name']})")
        else:
            # Update contact outcome and re-score
            contact["last_contact_outcome"] = outcome
            contact["last_contact_date"]    = datetime.now(IST).strftime("%Y-%m-%d")
            contact["total_attempts"]       = attempt_num
            new_score = score(contact)

            max_attempts = self.sequencer.max_attempts()
            if attempt_num < max_attempts and outcome != "ANSWERED":
                self.pq.push(contact, new_score)
                logger.debug(f"Re-queued {cid} with new score={new_score:.4f}")

        # Log attempt
        log_entry = {
            "attempt_id":   f"ATT-{self.attempt_count + 1:04d}",
            "timestamp":    datetime.now(IST).isoformat(),
            "contact_id":   cid,
            "name":         contact["name"],
            "phone":        contact["phone"],
            "channel":      channel,
            "outcome":      outcome,
            "is_rpc":       is_rpc,
            "priority_score": contact.get("priority_score", 0),
            "dpd_bucket":   contact.get("dpd_bucket", 0),
            "attempt_num":  attempt_num,
            "queue_depth":  len(self.pq),
        }
        self.attempt_log.append(log_entry)
        self.attempt_count += 1

        # Queue depth snapshot
        self.queue_snapshots.append({
            "attempt": self.attempt_count,
            "depth": len(self.pq),
            "timestamp": log_entry["timestamp"],
        })

        logger.info(
            f"[{log_entry['attempt_id']}] {cid} {contact['name']:<20} "
            f"| {channel:<10} | {outcome:<20} | rpc={is_rpc} | score={contact.get('priority_score',0):.4f}"
        )
        return log_entry

    def run_simulation(self, n_attempts: int = 20) -> list[Dict[str, Any]]:
        """Run n_attempts dispatch cycles (with window bypass for simulation)."""
        logger.info(f"\n{'='*60}")
        logger.info(f"Starting simulation: {n_attempts} attempts")
        logger.info(f"{'='*60}\n")

        for _ in range(n_attempts):
            if len(self.pq) == 0:
                logger.info("Queue exhausted — stopping simulation.")
                break
            self.dispatch_next(force_window=True)
            time.sleep(0.05)  # small delay so logs are readable

        logger.info(f"\nSimulation complete. {self.attempt_count} attempts logged.")
        return self.attempt_log

    # ── Analytics ──────────────────────────────────────────────────────────────
    def analytics(self) -> Dict[str, Any]:
        """Compute 4 campaign metrics from attempt log."""
        log = self.attempt_log
        if not log:
            return {}

        total      = len(log)
        answered   = [e for e in log if e["outcome"] == "ANSWERED"]
        rpc_count  = sum(1 for e in log if e["is_rpc"])

        contact_rate = len(answered) / total if total else 0
        rpc_rate     = rpc_count / total if total else 0

        # Channel effectiveness
        channel_stats: Dict[str, Dict[str, int]] = {}
        for e in log:
            ch = e["channel"]
            if ch not in channel_stats:
                channel_stats[ch] = {"attempts": 0, "answered": 0}
            channel_stats[ch]["attempts"] += 1
            if e["outcome"] == "ANSWERED":
                channel_stats[ch]["answered"] += 1

        channel_effectiveness = {
            ch: {
                "attempts": v["attempts"],
                "answer_rate": round(v["answered"] / v["attempts"], 3) if v["attempts"] else 0,
            }
            for ch, v in channel_stats.items()
        }

        return {
            "total_attempts":        total,
            "contact_rate":          round(contact_rate, 3),
            "rpc_rate":              round(rpc_rate, 3),
            "answered_count":        len(answered),
            "rpc_count":             rpc_count,
            "dnc_triggered":         sum(1 for e in log if e["outcome"] == "DNC"),
            "callback_requested":    sum(1 for e in log if e["outcome"] == "CALLBACK_REQUESTED"),
            "channel_effectiveness": channel_effectiveness,
            "queue_depth_over_time": self.queue_snapshots,
        }

    def get_nba(self) -> Dict[str, Any]:
        """Run NBA engine on current top-10 queue."""
        top10 = self.pq.peek_top_n(10)
        return next_best_actions(top10)

    # ── Helpers ────────────────────────────────────────────────────────────────
    @staticmethod
    def _simulate_outcome(contact: Dict[str, Any]) -> str:
        """
        Weighted random outcome. Adjusts weights based on contact profile:
        - Higher propensity → more likely ANSWERED
        - NO_ANSWER history → more likely NO_ANSWER again
        - DPD 120 → slightly higher DNC risk
        """
        weights = dict(_OUTCOME_WEIGHTS)
        prop = contact.get("propensity_score", 0.5)
        weights["ANSWERED"]  = max(0.05, weights["ANSWERED"] + (prop - 0.5) * 0.3)
        weights["NO_ANSWER"] = max(0.05, 1.0 - sum(v for k, v in weights.items() if k != "NO_ANSWER"))

        if contact.get("dpd_bucket", 0) >= 120:
            weights["DNC"] = min(0.15, weights["DNC"] * 2)

        choices  = list(weights.keys())
        w_values = [weights[k] for k in choices]
        total    = sum(w_values)
        w_norm   = [w / total for w in w_values]

        return random.choices(choices, weights=w_norm, k=1)[0]

    def save_log(self, path: Optional[Path] = None) -> Path:
        """Save attempt log to JSON file."""
        out = path or LOG_DIR / f"run_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        payload = {
            "campaign": self.config.get("campaign_name"),
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "total_attempts": self.attempt_count,
            "analytics": self.analytics(),
            "log": self.attempt_log,
        }
        out.write_text(json.dumps(payload, indent=2))
        logger.info(f"Log saved to {out}")
        return out


# ── CLI simulation ─────────────────────────────────────────────────────────────
if __name__ == "__main__":
    runner = CampaignRunner(bypass_window=True)
    runner.load_contacts()
    runner.start()

    # Run 20-attempt simulation
    runner.run_simulation(n_attempts=20)

    # Print analytics
    stats = runner.analytics()
    print("\n" + "="*60)
    print("CAMPAIGN ANALYTICS")
    print("="*60)
    print(f"  Total attempts    : {stats['total_attempts']}")
    print(f"  Contact rate      : {stats['contact_rate']*100:.1f}%")
    print(f"  RPC rate          : {stats['rpc_rate']*100:.1f}%")
    print(f"  Answered          : {stats['answered_count']}")
    print(f"  RPC (committed)   : {stats['rpc_count']}")
    print(f"  DNC triggered     : {stats['dnc_triggered']}")
    print(f"  Callbacks         : {stats['callback_requested']}")
    print("\n  Channel effectiveness:")
    for ch, v in stats["channel_effectiveness"].items():
        print(f"    {ch:<12}: {v['attempts']} attempts | {v['answer_rate']*100:.1f}% answer rate")

    # Save log
    log_path = runner.save_log()
    print(f"\n  Full log: {log_path}")