"""The run as it is written down: an append-only ledger, one resumable state blob, and the Context.

Every event the watch page draws goes through `Run.log`, and everything a
resumed run needs to be the same run goes through `Run.save`. The Context is
what a sitting and a night are handed: the state, the person, the ledger, the
charter as read, and the few things derived from the charter once at the start
of the run rather than at each use.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from regent import prompts
from regent.dice import DIALS, clip

if TYPE_CHECKING:
    from regent.agents import Adapter
    from regent.life import Life


def db(path: Path, schema: str) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(path, timeout=30, isolation_level=None, check_same_thread=False)
    c.execute("PRAGMA journal_mode=WAL")
    c.executescript(schema)
    return c


class Run:
    """The run: an append-only ledger and one resumable state blob."""

    SCHEMA = """
    CREATE TABLE IF NOT EXISTS event(id INTEGER PRIMARY KEY, t REAL, kind TEXT, data TEXT);
    CREATE TABLE IF NOT EXISTS state(k TEXT PRIMARY KEY, v TEXT);
    """

    def __init__(self, root: Path):
        self.root = root
        self.c = db(root / "run.db", self.SCHEMA)
        self.lock = threading.Lock()
        self.t0 = time.time()

    def log(self, kind: str, **kw):
        with self.lock:
            self.c.execute("INSERT INTO event(t, kind, data) VALUES(?,?,?)",
                           (round(time.time() - self.t0, 1), kind, json.dumps(kw, ensure_ascii=False)))

    def rows(self, kind: str) -> list[dict]:
        with self.lock:
            rows = self.c.execute("SELECT data FROM event WHERE kind=?", (kind,)).fetchall()
        return [json.loads(d) for (d,) in rows]

    def load(self) -> dict | None:
        r = self.c.execute("SELECT v FROM state WHERE k='run'").fetchone()
        return json.loads(r[0]) if r else None

    def save(self, s: dict):
        with self.lock:
            self.c.execute("INSERT OR REPLACE INTO state(k, v) VALUES('run', ?)", (json.dumps(s, ensure_ascii=False),))

    def say(self, text: str):
        print(f"[{(time.time() - self.t0) / 60:5.1f}m] {text}", flush=True)

    def close(self):
        with self.lock:
            self.c.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            self.c.close()


@dataclass
class Context:
    """Everything a sitting or a night works from, assembled once when the run starts.

    It was all closed over inside one `run_cmd` before, which is why it is a
    dataclass and not a pile of arguments: the same seven things are wanted by
    nearly every stage, and the derived ones are read off the charter once."""

    state: dict                  # S: the resumable state blob, mutated in place all run long
    life: Life                   # the person, and the sqlite file that is his life
    run: Run                     # the ledger
    args: argparse.Namespace     # what the command line asked for
    charter: dict[str, str]      # the charter by heading, lowercased
    project: Path                # where the builder works
    root: Path                   # the run folder, where the ledger and the digest live
    adapter: Adapter             # how a model is called
    check_cmd: str               # the charter's Check, run after every sitting
    show_cmd: str                # the charter's Show, which is how he sees the thing work
    tool_lines: list[str]        # the commands he may run when he tries it himself
    his_bash: str                # those commands as a Claude Code tool allowance
    deny: list[str]              # the tools no call of the builder's may use
    fence: list[str]             # the sandbox settings both of them work inside
    domains: list[str]           # the Network section, and the only domains a shell may reach
    his_words: set[str]          # everything he has ever written, plus plain English
    their_words: set[str]        # the builder's words, which grows with every reply
    happenings: list[str]        # what can happen in a week of this life, for the dice to draw from
    pursuits: list[str]          # what he does because he wants to

    @property
    def pname(self) -> str:
        """The project key. His memory, his picture and his reason are kept under it, per project."""
        return str(self.project)

    @property
    def days(self) -> int:
        return self.state["days"]

    @property
    def inbox(self) -> Path:
        return self.root / "inbox.md"

    @property
    def plant_file(self) -> Path:
        return self.root / "plant.md"

    @property
    def read_only(self) -> dict[str, str]:
        """Reading the project and changing nothing: the same leash for a question and for a read-back."""
        return {"tools": "Read,Glob,Grep,Bash",
                "allowed": "Read,Glob,Grep," + self.his_bash + ",Bash(git log:*),Bash(git status:*),Bash(git diff:*)"}

    def pending(self) -> list[dict]:
        return [i for i in self.state["ideas"] if i["status"] == "pending"]

    def stance(self) -> float:
        return clip(0.6 * self.state["mood"] + 0.4 * self.life.d("bold"))

    def system(self) -> str:
        """Built fresh for every call, because the why moves. A step back can rewrite it, and the man
        at the next sitting has to be the one who wants that, not the one who wanted the old thing."""
        life, last = self.life, self.state["stakes"][-1]
        return prompts.load("system").format(
            unseen=prompts.UNSEEN, who=life.who, why=life.get("stake", self.pname),
            could=("\n\nWhere you think it could go, and what you think comes of it:\n"
                   + last["could_become"] + "\n" + last["follows"]) if last.get("could_become") else "",
            dials=", ".join(f"{k} {life.d(k):+.1f}" for k in DIALS))

    def norms(self) -> str:
        """What the builder is told about the job, on every turn of its own, and never about him."""
        ch, amended = self.charter, self.state["amended"]
        return prompts.load("norms").format(
            intent=ch.get("intent", ""),
            check=f"\n\nAfter each turn the harness runs this check: {self.check_cmd}" if self.check_cmd else "",
            show=f"\nAnd it shows him the thing by running: {self.show_cmd}" if self.show_cmd else "",
            refusals=ch.get("refusals", ""), reserved=ch.get("reserved", "") or "- none",
            constraints=ch.get("constraints", ""),
            amended=("\n\nThe owner has since changed these limits, and his change stands:\n" + "\n".join(
                f"- was: {x['constraint']} / now: {x['now']}" for x in amended)) if amended else "")
