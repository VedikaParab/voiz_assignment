"""
priority_queue.py — VOIZ A4 Campaign Engine
Max-heap priority queue wrapping Python heapq.
Operations: push, pop, update(contact_id, new_score), remove(contact_id).
DNC check happens at POP TIME — not at ingestion time (critical!).
"""

import heapq
import threading
from typing import Dict, Any, Optional


class CampaignPriorityQueue:
    """
    Max-heap priority queue for campaign contacts.

    Key design decisions:
    - Uses a lazy-deletion pattern: removed/updated entries are marked
      invalid in a set and skipped at pop time.
    - DNC check fires at pop() — never at push(). This ensures contacts
      added to DNC mid-campaign are never dispatched even if already queued.
    - Thread-safe via threading.Lock.
    """

    def __init__(self, dnc_manager=None):
        self._heap: list = []          # (neg_score, contact_id, contact_dict)
        self._entry_map: Dict[str, tuple] = {}   # contact_id → heap entry
        self._removed: set = set()               # contact_ids marked for lazy deletion
        self._lock = threading.Lock()
        self._dnc_manager = dnc_manager          # injected at runtime

    # ── Push ──────────────────────────────────────────────────────────────────
    def push(self, contact: Dict[str, Any], priority_score: float) -> None:
        """Insert or re-insert a contact with a given score."""
        with self._lock:
            contact_id = contact["contact_id"]
            # If already in queue, mark old entry removed
            if contact_id in self._entry_map:
                self._removed.add(id(self._entry_map[contact_id]))

            # heapq is a min-heap; negate score for max-heap behaviour
            entry = [-priority_score, contact_id, contact]
            self._entry_map[contact_id] = entry
            heapq.heappush(self._heap, entry)

    # ── Pop ───────────────────────────────────────────────────────────────────
    def pop(self) -> Optional[Dict[str, Any]]:
        """
        Return highest-priority non-DNC contact.
        DNC check fires HERE — any contact on DNC at pop time is discarded.
        Returns None if queue is empty.
        """
        with self._lock:
            while self._heap:
                entry = heapq.heappop(self._heap)
                neg_score, contact_id, contact = entry

                # Skip lazily deleted entries
                if id(entry) in self._removed or contact_id in self._removed:
                    continue

                # ── DNC CHECK AT POP TIME (critical) ──────────────────────────
                if self._dnc_manager and self._dnc_manager.check(contact["phone"]):
                    self._removed.add(contact_id)
                    self._entry_map.pop(contact_id, None)
                    self._dnc_manager.log_pop_time_hit(contact_id, contact["phone"])
                    continue  # discard and try next

                # Valid contact — remove from entry_map and return
                self._entry_map.pop(contact_id, None)
                contact["priority_score"] = -neg_score
                return contact

            return None

    # ── Update score ──────────────────────────────────────────────────────────
    def update(self, contact_id: str, new_score: float) -> bool:
        """Re-score a contact already in the queue. Returns False if not found."""
        with self._lock:
            if contact_id not in self._entry_map:
                return False
            old_entry = self._entry_map[contact_id]
            contact = old_entry[2]
            # Mark old entry invalid
            self._removed.add(id(old_entry))
            # Push new entry
            new_entry = [-new_score, contact_id, contact]
            self._entry_map[contact_id] = new_entry
            heapq.heappush(self._heap, new_entry)
            return True

    # ── Remove ────────────────────────────────────────────────────────────────
    def remove(self, contact_id: str) -> bool:
        """Permanently remove a contact (used for DNC invocation mid-run)."""
        with self._lock:
            if contact_id not in self._entry_map:
                return False
            old_entry = self._entry_map.pop(contact_id)
            self._removed.add(id(old_entry))
            self._removed.add(contact_id)
            return True

    # ── Peek top-N ────────────────────────────────────────────────────────────
    def peek_top_n(self, n: int = 10) -> list[Dict[str, Any]]:
        """
        Return top-N contacts by score without removing them.
        Does NOT apply DNC filter (use for display only).
        """
        with self._lock:
            valid = [
                e for e in self._heap
                if id(e) not in self._removed and e[1] not in self._removed
            ]
            top = sorted(valid, key=lambda e: e[0])[:n]  # most negative = highest score
            return [
                {**e[2], "priority_score": -e[0]}
                for e in top
            ]

    # ── Size ──────────────────────────────────────────────────────────────────
    def size(self) -> int:
        with self._lock:
            return len(self._entry_map) - len(
                [cid for cid in self._entry_map if cid in self._removed]
            )

    def __len__(self) -> int:
        return self.size()


# ── CLI smoke test ─────────────────────────────────────────────────────────────
if __name__ == "__main__":
    from scorer import score_all
    import json
    from pathlib import Path

    contacts = json.loads((Path(__file__).parent / "data" / "contacts.json").read_text())
    ranked = score_all(contacts)

    pq = CampaignPriorityQueue()
    for c in ranked:
        pq.push(c, c["priority_score"])

    print(f"Queue size after loading 50 contacts: {len(pq)}")
    print("\nTop 5 by priority:")
    for c in pq.peek_top_n(5):
        print(f"  {c['contact_id']} {c['name']:<22} score={c['priority_score']:.4f}  DPD={c['dpd_bucket']}")

    # Test pop
    top = pq.pop()
    print(f"\nPopped: {top['contact_id']} {top['name']} (score={top['priority_score']:.4f})")
    print(f"Queue size after pop: {len(pq)}")

    # Test update
    second = pq.peek_top_n(1)[0]
    pq.update(second["contact_id"], 0.99)
    print(f"\nUpdated {second['contact_id']} to score=0.99")
    print(f"New top: {pq.peek_top_n(1)[0]['contact_id']}")

    # Test remove
    pq.remove(second["contact_id"])
    print(f"Removed {second['contact_id']}. Queue size: {len(pq)}")