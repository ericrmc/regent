"""Stance is one scalar with a slow baseline under it.

-1 is risk-weighted: prefers evidence, shrinks scope, raises the bar on failure
modes. +1 is opportunity-weighted: prefers reach, accepts partial, spends on the
adjacent possible.

It changes the weights on Sift's four axes and the size of the drift budget. It
never changes the gate or the risk tiers. It moves by a bounded step per turn,
which is what stops the disposition swinging end to end.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

DAY_S = 86400
WEEK_S = 7 * DAY_S


@dataclass
class StanceState:
    value: float = 0.0
    baseline: float = 0.0
    temperament: float = 0.0
    last_day_move: float = 0.0
    last_week_move: float = 0.0
    line: str = ""

    def to_dict(self) -> dict:
        d = asdict(self)
        for k in ("value", "baseline", "temperament"):
            d[k] = round(d[k], 4)
        return d

    @classmethod
    def from_dict(cls, d: dict | None) -> StanceState:
        d = d or {}
        return cls(
            value=float(d.get("value", 0.0)),
            baseline=float(d.get("baseline", 0.0)),
            temperament=float(d.get("temperament", 0.0)),
            last_day_move=float(d.get("last_day_move", 0.0)),
            last_week_move=float(d.get("last_week_move", 0.0)),
            line=str(d.get("line", "")),
        )

    def describe(self) -> str:
        v = self.value
        if v <= -0.5:
            word = "risk-weighted"
        elif v <= -0.15:
            word = "leaning to risk"
        elif v < 0.15:
            word = "even"
        elif v < 0.5:
            word = "leaning to opportunity"
        else:
            word = "opportunity-weighted"
        return f"{word} ({v:+.2f})"


def tilt(state: StanceState, cfg, *, friction: int = 0, unfinished: int = 0,
         foreign: int = 0, drift_accepted: bool = False,
         drift_died_grounded: bool = False, unease: float = 0.0,
         evidence_thin: bool = False, nudge: float = 0.0, day: int = 0,
         recent: int = 0) -> StanceState:
    """One bounded step per turn, around a slow baseline.

    `day` is the simulated day the life is on, not wall-clock time. Mood
    changing daily means changing on the agent's days, and a wall-clock move
    would also break replay.
    """
    s = cfg.stance

    # Mood changes daily. Temperament changes over weeks.
    if day > state.last_day_move:
        state.baseline = _clamp(state.baseline + _sign(state.value - state.baseline)
                                * s.baseline_step_per_day, s.bounds)
        state.last_day_move = day
        if day - state.last_week_move >= 7:
            state.temperament = _clamp(state.temperament + _sign(state.baseline)
                                       * s.temperament_step_per_week, s.bounds)
            state.last_week_move = day

    # Shares of the recent field, not raw counts. Thirty friction elements
    # would otherwise pin the stance to a bound rather than moving it in a band.
    scale = max(1, recent)
    friction = friction / scale
    unfinished = unfinished / scale
    foreign = foreign / scale

    want = state.baseline + state.temperament
    want += friction * s.tilt_friction
    want += (unfinished + foreign) * s.tilt_unfinished_foreign
    if drift_accepted:
        want += s.tilt_drift_accepted
    if drift_died_grounded:
        want += s.tilt_drift_died_grounded
    if unease >= 0.5 and evidence_thin:
        want += s.tilt_unease_thin_evidence
    want += nudge
    want = _clamp(want, s.bounds)

    step = _clamp(want - state.value, (-s.max_step_per_turn, s.max_step_per_turn))
    state.value = _clamp(state.value + step, s.bounds)
    return state


def perturb(state: StanceState, cfg, rng) -> float:
    """Interlude stance drift, either way, bounded.

    Randomness in disposition is productive. Randomness in authority is a
    runaway, so this touches one number and nothing else.
    """
    amp = cfg.stance.interlude_drift_amplitude
    delta = rng.uniform(-amp, amp)
    before = state.value
    state.value = _clamp(state.value + delta, cfg.stance.bounds)
    return state.value - before


def sift_weights(state: StanceState, cfg) -> dict[str, float]:
    """Opportunity raises novelty and leverage. Risk raises mechanism and cost."""
    base = dict(cfg.sift.weights)
    span = cfg.sift.stance_weight_span * state.value
    out = {
        "novelty": base["novelty"] + span,
        "leverage": base["leverage"] + span * 0.5,
        "mechanism": base["mechanism"] - span * 0.5,
        "cost": base["cost"] - span,
    }
    out = {k: max(0.01, v) for k, v in out.items()}
    total = sum(out.values())
    return {k: round(v / total, 3) for k, v in out.items()}


def drift_target(state: StanceState, cfg, curiosity: float) -> int:
    """Curiosity raises the drift budget. So does an opportunity-weighted stance."""
    low, high = cfg.drift.target_links_min, cfg.drift.target_links_max
    span = (high - low)
    lift = (state.value + 1.0) / 2.0 * cfg.drift.stance_budget_span
    lift += curiosity * cfg.drift.curiosity_budget_span
    target = low + span * min(1.0, lift / max(1e-9, cfg.drift.stance_budget_span
                                              + cfg.drift.curiosity_budget_span))
    return int(max(low, min(high, round(target))))


def _clamp(v: float, bounds) -> float:
    lo, hi = bounds
    return max(lo, min(hi, v))


def _sign(v: float) -> float:
    return 1.0 if v > 0 else (-1.0 if v < 0 else 0.0)
