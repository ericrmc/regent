"""The run directory. All state is on disk, so the harness stops and starts
without losing the run.

Logs are append-only. `state.json` is the only file rewritten in place, and it
is written through a temporary file so a kill mid-write cannot corrupt it.
"""

from __future__ import annotations

import json
import os
import threading
import time
from collections.abc import Iterator
from pathlib import Path


class Store:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve()
        # A cycle runs beside the work, so two threads write these files. The
        # lock covers the read-modify-write in rewrite_jsonl and the sequence
        # the ledger keeps.
        self.lock = threading.RLock()

    # Paths the design names.
    @property
    def charter(self) -> Path:
        return self.root / "charter.md"

    @property
    def charter_hash(self) -> Path:
        return self.root / "charter.sha256"

    @property
    def self_md(self) -> Path:
        return self.root / "self.md"

    @property
    def taste(self) -> Path:
        return self.root / "taste.md"

    @property
    def ledger(self) -> Path:
        return self.root / "ledger.jsonl"

    @property
    def state(self) -> Path:
        return self.root / "state.json"

    @property
    def warm(self) -> Path:
        return self.root / "manifold" / "warm.jsonl"

    @property
    def cold(self) -> Path:
        return self.root / "manifold" / "cold.jsonl"

    @property
    def returns(self) -> Path:
        return self.root / "returns"

    @property
    def logs(self) -> Path:
        return self.root / "returns" / "logs"

    @property
    def holding(self) -> Path:
        return self.root / "holding"

    @property
    def cycles(self) -> Path:
        return self.root / "cycles"

    @property
    def escalations(self) -> Path:
        return self.root / "escalations"

    @property
    def digests(self) -> Path:
        return self.root / "digests"

    @property
    def inbox(self) -> Path:
        """Operator input, append-only, read by the loop each turn."""
        return self.root / "inbox"

    @property
    def sandbox(self) -> Path:
        """An empty directory for children that should reach nothing."""
        return self.root / "sandbox"

    @property
    def ways(self) -> Path:
        return self.root / "ways.md"

    @property
    def metrics(self) -> Path:
        return self.root / "metrics.jsonl"

    @property
    def spot_checks(self) -> Path:
        return self.root / "spot_checks"

    @property
    def life(self) -> Path:
        return self.root / "life"

    @property
    def memory(self) -> Path:
        return self.root / "memory.md"

    @property
    def stop_flag(self) -> Path:
        return self.root / "STOP"

    @property
    def harness_log(self) -> Path:
        return self.root / "regent.log"

    @property
    def config_snapshot(self) -> Path:
        return self.root / "config.json"

    def ensure(self) -> None:
        for d in (self.root, self.root / "manifold", self.returns, self.logs,
                  self.holding, self.cycles, self.escalations, self.digests,
                  self.spot_checks, self.life, self.life / "journal",
                  self.sandbox, self.inbox):
            d.mkdir(parents=True, exist_ok=True)
        for f, seed in ((self.self_md, "# Objectives\n"),
                        (self.taste, "# Taste\n"),
                        (self.memory, "# Memory\n")):
            if not f.exists():
                f.write_text(seed)
        for f in (self.ledger, self.warm, self.cold, self.metrics):
            f.touch()

    def exists(self) -> bool:
        return self.state.exists()

    # Append-only logs.
    def append_jsonl(self, path: Path, record: dict) -> dict:
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.lock, open(path, "a") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
            fh.flush()
            os.fsync(fh.fileno())
        return record

    def read_jsonl(self, path: Path) -> list[dict]:
        if not path.exists():
            return []
        out = []
        for line in path.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return out

    def rewrite_jsonl(self, path: Path, records: list[dict]) -> None:
        """Only the manifold files are rewritten. The ledger never is."""
        with self.lock:
            tmp = path.with_suffix(path.suffix + f".{os.getpid()}.tmp")
            tmp.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n"
                                   for r in records))
            tmp.replace(path)

    def tail_jsonl(self, path: Path, n: int) -> list[dict]:
        records = self.read_jsonl(path)
        return records[-n:] if n > 0 else records

    def write_json(self, path: Path, data: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False, sort_keys=False))
        tmp.replace(path)

    def read_json(self, path: Path, default: dict | None = None) -> dict:
        if not path.exists():
            return dict(default or {})
        try:
            return json.loads(path.read_text())
        except json.JSONDecodeError:
            return dict(default or {})

    def log(self, message: str) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y-%m-%dT%H:%M:%S")
        with open(self.harness_log, "a") as fh:
            fh.write(f"{stamp} {message}\n")

    def follow_jsonl(self, path: Path, from_index: int = 0) -> Iterator[dict]:
        """Yield records from an index onward, then block for new ones."""
        seen = from_index
        while True:
            records = self.read_jsonl(path)
            while seen < len(records):
                yield records[seen]
                seen += 1
            if self.stop_flag.exists() and seen >= len(self.read_jsonl(path)):
                return
            time.sleep(0.5)
