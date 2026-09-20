"""Decisions, amendments, escalations and read modes, append-only.

Nothing rewrites a line. The ledger is the record the digest is drawn from and
the thing a later audit reads back.
"""

from __future__ import annotations

import time
from collections.abc import Iterable

from .store import Store

KINDS = (
    "run_started", "run_stopped", "turn", "decision", "dispatch", "return",
    "read_mode", "judgement", "amendment", "objective", "escalation",
    "escalation_answered", "audit", "trust", "cycle", "candidate", "gate",
    "interlude", "signal", "stance", "kill", "budget", "rejected", "error",
    "digest", "charter",
)


class Ledger:
    def __init__(self, store: Store) -> None:
        self.store = store
        self._seq: int | None = None
        # The turn a row belongs to, set by the loop. The digest scopes on it.
        self.turn = 0

    def write(self, kind: str, **fields) -> dict:
        # The sequence and the append are one act. A cycle running beside the
        # work writes here too, and out-of-order sequences break `watch --from`
        # and the guardrail's prefix hash.
        with self.store.lock:
            return self._write(kind, **fields)

    def _write(self, kind: str, **fields) -> dict:
        record = {
            "seq": self.next_seq(),
            "ts": time.time(),
            "iso": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "kind": kind,
            "turn": self.turn,
        }
        record.update(fields)
        return self.store.append_jsonl(self.store.ledger, record)

    def next_seq(self) -> int:
        """Counted once, then held.

        Re-reading and parsing the whole ledger on every write is quadratic in
        run length, and the design asks for runs of weeks.
        """
        if self._seq is None:
            self._seq = self._count()
        self._seq += 1
        return self._seq

    def _count(self) -> int:
        if not self.store.ledger.exists():
            return 0
        with open(self.store.ledger) as fh:
            return sum(1 for line in fh if line.strip())

    def all(self) -> list[dict]:
        return self.store.read_jsonl(self.store.ledger)

    def tail(self, n: int) -> list[dict]:
        return self.store.tail_jsonl(self.store.ledger, n)

    def of_kind(self, *kinds: str) -> list[dict]:
        wanted = set(kinds)
        return [r for r in self.all() if r.get("kind") in wanted]

    def since(self, seq: int) -> list[dict]:
        return [r for r in self.all() if r.get("seq", 0) > seq]

    def count(self, kind: str) -> int:
        return sum(1 for r in self.all() if r.get("kind") == kind)


def summarise(records: Iterable[dict], limit: int = 30) -> str:
    """One line per record, newest last. This is what Wake and `watch` read."""
    lines = []
    for r in list(records)[-limit:]:
        kind = r.get("kind", "?")
        bits = [f"[{r.get('seq', 0):04d}]", r.get("iso", ""), kind]
        for key in ("tier", "read_mode", "outcome", "direction", "rung", "event", "state"):
            if r.get(key):
                bits.append(f"{key}={r[key]}")
        for key in ("id", "dispatch_id", "return_id", "objective_id"):
            if r.get(key):
                bits.append(str(r[key]))
        summary = r.get("summary") or r.get("text") or r.get("reason") or r.get("question") or ""
        if summary:
            bits.append(str(summary)[:160])
        lines.append(" ".join(b for b in bits if b))
    return "\n".join(lines)
