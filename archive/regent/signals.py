"""Four computed scalars that change what the loop does, and the ladder.

Nothing is performed in prose. Each signal is computed from counters the harness
already holds, and each has one effect.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

RUNGS = {
    1: "retry with the same approach",
    2: "change the approach",
    3: "change the builder",
    4: "amend the criterion",
    5: "escalate to the human",
    6: "kill the subgoal and take the budget elsewhere",
}


@dataclass
class SignalSet:
    frustration: float = 0.0
    curiosity: float = 0.0
    satisfaction: float = 0.0
    unease: float = 0.0

    def to_dict(self) -> dict:
        return {k: round(v, 3) for k, v in asdict(self).items()}

    @classmethod
    def from_dict(cls, d: dict | None) -> SignalSet:
        d = d or {}
        return cls(**{k: float(d.get(k, 0.0)) for k in
                      ("frustration", "curiosity", "satisfaction", "unease")})

    def clamp(self) -> SignalSet:
        for k in ("frustration", "curiosity", "satisfaction", "unease"):
            setattr(self, k, max(0.0, min(1.0, getattr(self, k))))
        return self

    def line(self) -> str:
        return (f"frustration {self.frustration:.2f}, curiosity {self.curiosity:.2f}, "
                f"satisfaction {self.satisfaction:.2f}, unease {self.unease:.2f}")


def update(signals: SignalSet, cfg, *, failures: int = 0, questions: int = 0,
           accepts: int = 0, thin_evidence: int = 0) -> SignalSet:
    s = cfg.signals
    signals.frustration += failures * s.frustration_per_failure
    signals.curiosity += questions * s.curiosity_per_question
    signals.satisfaction += accepts * s.satisfaction_per_accept
    signals.unease += thin_evidence * s.unease_per_thin_evidence
    # Satisfaction closes the subgoal and releases budget, which takes the edge
    # off frustration on the same branch.
    if accepts:
        signals.frustration = max(0.0, signals.frustration - accepts * 0.2)
        signals.unease = max(0.0, signals.unease - accepts * 0.1)
    return signals.clamp()


def decay(signals: SignalSet, cfg) -> SignalSet:
    """An interlude decays them, so a bad run colours the next judgement without
    owning it.
    """
    f = 1.0 - cfg.signals.interlude_decay
    signals.frustration *= f
    signals.curiosity *= f
    signals.satisfaction *= f
    signals.unease *= f
    return signals.clamp()


def thin_evidence(ret) -> bool:
    """Unease is evidence thinner than the claim.

    A return that claims something changed and offers nothing a reader can open
    is thin. A builder's account of its own work is narration, not evidence.
    """
    if not ret.evidence:
        return True
    openable = [e for e in ret.evidence if e.ref and e.kind in
                ("artifact", "screen", "test", "timing", "output", "log")]
    return len(openable) == 0


def rung_for(failures: int, cfg) -> int:
    """One rung per repeated failure, capped at the last rung."""
    return max(1, min(cfg.signals.ladder_rungs, failures))


class Ladder:
    """Frustration is only useful if it has somewhere to go.

    Rung 6 is the one agents never reach on their own, so the harness reaches it
    for them: a subgoal with no state change in N cycles loses its allocation
    whether or not frustration fired.
    """

    def __init__(self, cfg, table: dict | None = None) -> None:
        self.cfg = cfg
        self.table: dict[str, dict] = dict(table or {})

    def record_failure(self, subgoal_id: str) -> int:
        row = self.table.setdefault(subgoal_id, {"failures": 0, "idle_cycles": 0, "rung": 1})
        row["failures"] += 1
        row["idle_cycles"] = 0
        row["rung"] = rung_for(row["failures"], self.cfg)
        return row["rung"]

    def record_progress(self, subgoal_id: str) -> None:
        row = self.table.setdefault(subgoal_id, {"failures": 0, "idle_cycles": 0, "rung": 1})
        row["failures"] = 0
        row["idle_cycles"] = 0
        row["rung"] = 1

    def tick_idle(self, live_subgoals: list[str]) -> list[str]:
        """Returns the subgoals that lose their allocation this cycle."""
        killed = []
        for sid in live_subgoals:
            row = self.table.setdefault(sid, {"failures": 0, "idle_cycles": 0, "rung": 1})
            row["idle_cycles"] += 1
            if row["idle_cycles"] >= self.cfg.signals.kill_after_idle_cycles:
                row["rung"] = self.cfg.signals.ladder_rungs
                killed.append(sid)
        return killed

    def rung(self, subgoal_id: str) -> int:
        return int(self.table.get(subgoal_id, {}).get("rung", 1))

    def to_dict(self) -> dict:
        return dict(self.table)
