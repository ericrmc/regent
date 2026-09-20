"""The run's mutable state, saved after every turn.

All state is on disk, so the harness can stop and start without losing the run.
The random draw counter is part of it, which is what makes a resumed run stay on
the same stream.
"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field

from .dispatch import Dispatch
from .rng import Rng
from .signals import SignalSet
from .stance import StanceState


@dataclass
class Objective:
    id: str
    text: str
    weight: float = 0.5
    charter_line: str = ""
    trigger: str = ""
    created_turn: int = 0
    status: str = "live"
    criteria_met: int = 0
    criteria_total: int = 0

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Escalation:
    id: str
    question: str
    tier: str = "high"
    why: str = ""
    source: str = ""
    payload: dict = field(default_factory=dict)
    turn: int = 0
    answer: str = ""
    answered_at: float = 0.0
    consumed: bool = False

    @property
    def open(self) -> bool:
        return not self.answer

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class RunState:
    seed: int = 0
    draws: int = 0
    turn: int = 0
    cycle: int = 0
    started: float = 0.0
    # Seconds actually spent running, across every start and stop. Elapsed
    # time since the first start counts the hours the run was not running.
    elapsed_s: float = 0.0
    project: str = ""
    charter_sha256: str = ""
    stopped: bool = False
    stop_reason: str = ""
    cost_usd: float = 0.0
    tokens: int = 0
    calls: int = 0
    stance: StanceState = field(default_factory=StanceState)
    signals: SignalSet = field(default_factory=SignalSet)
    objectives: list[dict] = field(default_factory=list)
    dispatches: dict = field(default_factory=dict)
    escalations: list[dict] = field(default_factory=list)
    trust: dict = field(default_factory=dict)
    debt: dict = field(default_factory=dict)
    ladder: dict = field(default_factory=dict)
    motifs: list[str] = field(default_factory=list)
    candidates: list[str] = field(default_factory=list)
    pending_audits: list[dict] = field(default_factory=list)
    amendments: list[dict] = field(default_factory=list)
    medium_recent: list[int] = field(default_factory=list)
    last_cycle: int = 0
    last_digest_turn: int = 0
    last_drift_accepted: bool = False
    last_drift_died_grounded: bool = False
    last_return_seq: int = 0
    failed_turns: int = 0
    idle_turns: int = 0
    # Spot checks, requirements and appetite.
    spot_checks_total: int = 0
    spot_checks_this_turn: int = 0
    spot_check_findings: list = field(default_factory=list)
    requirements: list = field(default_factory=list)
    returns_read: int = 0
    returns_made: int = 0
    life_day_count: int = 0
    # What the day left for the project.
    sitting: str = ""
    sitting_share: float = 1.0
    challenges: int = 0
    ways: list = field(default_factory=list)
    process_notes: list = field(default_factory=list)
    stepped_back: int = 0
    denials_proposed: bool = False
    denials_proposal: dict = field(default_factory=dict)
    last_stepped_back: int = 0
    last_return_was_bad: bool = False
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    pending_drift: list = field(default_factory=list)
    pending_spot_checks: list = field(default_factory=list)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["stance"] = self.stance.to_dict()
        d["signals"] = self.signals.to_dict()
        return d

    @classmethod
    def from_dict(cls, d: dict) -> RunState:
        d = dict(d or {})
        stance = StanceState.from_dict(d.pop("stance", None))
        sig = SignalSet.from_dict(d.pop("signals", None))
        known = {k: v for k, v in d.items() if k in cls.__dataclass_fields__}
        s = cls(**known)
        s.stance = stance
        s.signals = sig
        return s

    # Dispatches.
    def open_dispatches(self) -> list[Dispatch]:
        return [Dispatch.from_dict(d) for d in self.dispatches.values()
                if d.get("status") == "open"]

    def dispatch(self, did: str) -> Dispatch | None:
        raw = self.dispatches.get(did)
        return Dispatch.from_dict(raw) if raw else None

    def put_dispatch(self, d: Dispatch) -> None:
        self.dispatches[d.id] = d.to_dict()

    # Escalations.
    def open_escalations(self) -> list[Escalation]:
        return [Escalation(**{k: v for k, v in e.items()
                              if k in Escalation.__dataclass_fields__})
                for e in self.escalations if not e.get("answer")]

    def escalation(self, eid: str) -> Escalation | None:
        for e in self.escalations:
            if e.get("id") == eid:
                return Escalation(**{k: v for k, v in e.items()
                                     if k in Escalation.__dataclass_fields__})
        return None

    def answer_escalation(self, eid: str, text: str) -> bool:
        for e in self.escalations:
            if e.get("id") == eid and not e.get("answer"):
                e["answer"] = text
                e["answered_at"] = time.time()
                return True
        return False

    # Objectives.
    def objective(self, oid: str) -> dict | None:
        for o in self.objectives:
            if o.get("id") == oid:
                return o
        return None

    def live_objectives(self) -> list[dict]:
        return [o for o in self.objectives if o.get("status") == "live"]

    # Debt is the count of consecutive returns on a branch with no full read.
    def debt_for(self, branch: str) -> int:
        return int(self.debt.get(branch, 0))

    def bump_debt(self, branch: str, full_read: bool) -> int:
        self.debt[branch] = 0 if full_read else self.debt_for(branch) + 1
        return self.debt[branch]

    def rng(self) -> Rng:
        return Rng(seed=self.seed, draws=self.draws)

    def save_rng(self, rng: Rng) -> None:
        self.seed = rng.seed
        self.draws = rng.draws
