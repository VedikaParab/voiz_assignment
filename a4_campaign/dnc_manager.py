"""
dnc_manager.py — VOIZ A4 Campaign Engine
DNC enforcement: in-memory set + persistent SQLite table.
check(phone) → bool  (called at POP TIME, not ingestion)
add(phone, reason)   → permanently adds; cannot be undone
remove is NOT allowed — DNC is permanent.
"""

import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import Optional


DB_PATH = Path(__file__).parent / "data" / "dnc.db"


class DNCManager:
    """
    Two-layer DNC enforcement:
    1. In-memory set for O(1) hot-path check at pop time.
    2. SQLite persistence so DNC survives process restarts.

    Architecture note: DNC check must happen at queue POP TIME.
    A contact can be added to DNC during a live campaign run (e.g. mid-call).
    Checking only at ingestion would dispatch to contacts who joined DNC
    after the campaign started — a real TRAI/regulatory violation.
    """

    def __init__(self, db_path: Path = DB_PATH):
        self._lock = threading.Lock()
        self._dnc_set: set[str] = set()   # phone numbers (in-memory)
        self._pop_hits: list[dict] = []   # log of pop-time DNC catches
        self._db_path = db_path
        self._init_db()
        self._load_from_db()

    # ── DB setup ───────────────────────────────────────────────────────────────
    def _init_db(self) -> None:
        self._db_path.parent.mkdir(exist_ok=True)
        with sqlite3.connect(self._db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS dnc_list (
                    phone     TEXT PRIMARY KEY,
                    reason    TEXT,
                    added_at  TEXT,
                    source    TEXT DEFAULT 'manual'
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS dnc_pop_log (
                    contact_id  TEXT,
                    phone       TEXT,
                    caught_at   TEXT
                )
            """)
            conn.commit()

    def _load_from_db(self) -> None:
        """Load existing DNC entries into memory on startup."""
        with sqlite3.connect(self._db_path) as conn:
            rows = conn.execute("SELECT phone FROM dnc_list").fetchall()
        with self._lock:
            for (phone,) in rows:
                self._dnc_set.add(str(phone))

    # ── Check (O(1), called at pop time) ──────────────────────────────────────
    def check(self, phone: str) -> bool:
        """Return True if phone is on DNC. Called at queue pop time."""
        with self._lock:
            return str(phone) in self._dnc_set

    # ── Add (permanent) ───────────────────────────────────────────────────────
    def add(self, phone: str, reason: str = "user_request", source: str = "campaign") -> None:
        """
        Add a phone number to DNC permanently.
        Syncs to SQLite immediately. Cannot be undone.
        """
        phone = str(phone)
        with self._lock:
            self._dnc_set.add(phone)

        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                "INSERT OR IGNORE INTO dnc_list (phone, reason, added_at, source) VALUES (?, ?, ?, ?)",
                (phone, reason, datetime.now().isoformat(), source),
            )
            conn.commit()

        print(f"[DNC] ⛔ Added {phone} to DNC — reason: {reason}")

    # ── Remove is NOT allowed ─────────────────────────────────────────────────
    def remove(self, phone: str) -> None:
        raise NotImplementedError(
            "DNC removal is not permitted. DNC is permanent per TRAI TCCCPR 2018."
        )

    # ── Pop-time hit logging ───────────────────────────────────────────────────
    def log_pop_time_hit(self, contact_id: str, phone: str) -> None:
        """Log when a DNC contact is caught and discarded at pop time."""
        entry = {
            "contact_id": contact_id,
            "phone": phone,
            "caught_at": datetime.now().isoformat(),
        }
        self._pop_hits.append(entry)
        print(f"[DNC] 🔴 Pop-time catch: {contact_id} ({phone}) — discarded from queue")

        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                "INSERT INTO dnc_pop_log (contact_id, phone, caught_at) VALUES (?, ?, ?)",
                (contact_id, phone, entry["caught_at"]),
            )
            conn.commit()

    # ── Stats ──────────────────────────────────────────────────────────────────
    def stats(self) -> dict:
        with self._lock:
            return {
                "total_dnc_numbers": len(self._dnc_set),
                "pop_time_catches": len(self._pop_hits),
                "pop_log": self._pop_hits[-10:],  # last 10
            }

    def list_all(self) -> list[str]:
        with self._lock:
            return sorted(self._dnc_set)


# ── CLI smoke test ─────────────────────────────────────────────────────────────
if __name__ == "__main__":
    dnc = DNCManager()
    print(f"DNC list loaded: {len(dnc.list_all())} numbers")

    # Add a test number
    dnc.add("9999999999", reason="test_entry", source="cli")
    print(f"Check 9999999999: {dnc.check('9999999999')}")
    print(f"Check 1234567890: {dnc.check('1234567890')}")

    print(f"\nDNC Stats: {dnc.stats()}")