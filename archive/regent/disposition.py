"""The regent's disposition: dials that belong to the owner, not to the run.

A regent is cast and not specified. The human pins a few facts, the dice roll
the rest, and the result is a person who fits and whom nobody designed.

Personality is held twice. In the bible it is prose, how they talk and what
they avoid. Here it is seven dials, each from minus one to one, each moving one
thing the harness already does.

A dial moves inside its floor, the same line ways and the interlude hold. No
personality lowers the spot-check floor, the audit rate, the debt cap or the
count of requirements a cycle may invent. A cautious regent invents a different
kind of requirement, hardening over reach, and as many of them.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, fields

TRAITS = ("bold", "curious", "patient", "trusting", "thorough", "stubborn",
          "restless")

WHAT_EACH_MOVES = {
    "bold": "stance temperament, the slow baseline mood moves around",
    "curious": "drift budget and how often a cycle runs",
    "patient": "how fast frustration builds, and so how fast the ladder climbs",
    "trusting": "starting trust, and how much attention trust buys off",
    "thorough": "the lean of the read-mode draw, and the spot-check rate",
    "stubborn": "how readily a criterion relaxes or a direction reverses",
    "restless": "how much of the appetite they tend to use",
}


@dataclass
class Reading:
    """Three samples, a median per dial, and the spread between them.

    Reading a disposition off prose is a sample and not a measurement. Two
    readings of one regent minutes apart disagreed on five of seven dials and
    one changed sign, so the number shown is a median and the spread is shown
    beside it.
    """

    dials: dict = None
    spread: dict = None
    samples: list = None
    reasons: dict = None
    cost_usd: float = 0.0

    def __post_init__(self) -> None:
        self.dials = self.dials or {}
        self.spread = self.spread or {}
        self.samples = self.samples or []
        self.reasons = self.reasons or {}

    def disposition(self) -> Disposition:
        d = Disposition.from_dict(self.dials)
        d.reasons = dict(self.reasons)
        return d

    def to_dict(self) -> dict:
        return {"dials": self.dials, "spread": self.spread,
                "samples": self.samples, "reasons": self.reasons,
                "cost_usd": round(self.cost_usd, 6)}

    def widest(self) -> list:
        return sorted(self.spread.items(), key=lambda kv: -kv[1])


def combine(samples: list[dict], reasons: list[dict]) -> Reading:
    """The median per dial, and how far the samples sat apart."""
    import statistics

    dials, spread = {}, {}
    for t in TRAITS:
        got = [float(s.get(t, 0.0)) for s in samples if t in s]
        if not got:
            dials[t], spread[t] = 0.0, 0.0
            continue
        dials[t] = round(statistics.median(got), 3)
        spread[t] = round(max(got) - min(got), 3)
    # The reason kept is the one from the sample nearest the median.
    best = {}
    for t in TRAITS:
        pairs = [(abs(float(s.get(t, 0.0)) - dials[t]), i)
                 for i, s in enumerate(samples) if t in s]
        if pairs:
            _, i = min(pairs)
            best[t] = (reasons[i] or {}).get(t, "") if i < len(reasons) else ""
    return Reading(dials=dials, spread=spread, samples=samples, reasons=best)


@dataclass
class Disposition:
    """Seven dials, each minus one to one. Zero is the middle of the road."""

    bold: float = 0.0
    curious: float = 0.0
    patient: float = 0.0
    trusting: float = 0.0
    thorough: float = 0.0
    stubborn: float = 0.0
    restless: float = 0.0
    pinned: list = None
    reasons: dict = None

    def __post_init__(self) -> None:
        if self.pinned is None:
            self.pinned = []
        if self.reasons is None:
            self.reasons = {}
        self.clamp()

    def clamp(self) -> Disposition:
        for t in TRAITS:
            setattr(self, t, max(-1.0, min(1.0, float(getattr(self, t)))))
        return self

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict | None) -> Disposition:
        d = dict(d or {})
        known = {f.name: d[f.name] for f in fields(cls) if f.name in d}
        return cls(**known)

    def line(self) -> str:
        return ", ".join(f"{t} {getattr(self, t):+.2f}" for t in TRAITS)

    def describe(self) -> str:
        """One sentence a person would recognise."""
        strong = [(t, getattr(self, t)) for t in TRAITS
                  if abs(getattr(self, t)) >= 0.35]
        if not strong:
            return "even tempered, nothing pronounced"
        strong.sort(key=lambda x: -abs(x[1]))
        words = []
        for t, v in strong[:3]:
            words.append(_WORDS[t][0] if v > 0 else _WORDS[t][1])
        return ", ".join(words)


_WORDS = {
    "bold": ("bold", "cautious"),
    "curious": ("curious", "incurious"),
    "patient": ("patient", "impatient"),
    "trusting": ("trusting", "wary"),
    "thorough": ("thorough", "broad brush"),
    "stubborn": ("stubborn", "yielding"),
    "restless": ("restless", "content"),
}


def roll(rng, pinned: dict | None = None) -> Disposition:
    """Every trait not pinned is rolled."""
    pinned = dict(pinned or {})
    d = Disposition()
    for t in TRAITS:
        if t in pinned:
            setattr(d, t, float(pinned[t]))
        else:
            # A flat draw. A person is not usually average at everything.
            setattr(d, t, round(rng.uniform(-0.8, 0.8), 2))
    d.pinned = sorted(pinned)
    return d.clamp()


def apply(d: Disposition, cfg) -> list[dict]:
    """Move the dials the traits name, never below a floor.

    Returns what was changed, so the human can see it rather than being told
    a personality took effect somewhere.
    """
    changed = []

    def move(path: str, value, floor_is_min: bool = False):
        node = cfg
        parts = path.split(".")
        for p in parts[:-1]:
            node = getattr(node, p)
        before = getattr(node, parts[-1])
        if floor_is_min and value < before:
            # No personality lowers a floor.
            changed.append({"setting": path, "from": before, "to": before,
                            "held": "a floor may rise and never fall"})
            return
        setattr(node, parts[-1], value)
        changed.append({"setting": path, "from": before, "to": value})

    # Cautious to bold: the slow baseline the stance moves around.
    move("stance.start", round(d.bold * 0.4, 3))
    move("stance.temperament_step_per_week",
         round(cfg.stance.temperament_step_per_week * (1 + d.bold * 0.5), 4))

    # Curious: the drift budget and how often a cycle runs.
    move("drift.target_links_max",
         max(10, int(round(cfg.drift.target_links_max * (1 + d.curious * 0.4)))))
    move("cycle_every_n_turns",
         max(2, int(round(cfg.cycle_every_n_turns * (1 - d.curious * 0.4)))))

    # Patient: how fast frustration builds.
    move("signals.frustration_per_failure",
         round(cfg.signals.frustration_per_failure * (1 - d.patient * 0.5), 4))

    # Trusting: starting trust, and how much attention trust buys off.
    move("attention.trust_start",
         round(min(0.9, max(0.1, cfg.attention.trust_start + d.trusting * 0.25)), 3))
    move("attention.weight_trust",
         round(cfg.attention.weight_trust * (1 + d.trusting * 0.4), 4))

    # Thorough: the lean of the read-mode draw, and the spot-check rate.
    move("attention.base_score",
         round(cfg.attention.base_score + d.thorough * 0.12, 4))
    # A broad-brush regent would look less often, and the floor holds it.
    move("spot_check.rate", round(cfg.spot_check.rate * (1 + d.thorough), 4),
         floor_is_min=True)

    # Stubborn: how readily a criterion relaxes or a direction reverses.
    move("amendments.min_raise_to_relax_ratio",
         round(min(0.9, max(0.05, cfg.amendments.min_raise_to_relax_ratio
                            * (1 + d.stubborn * 0.6))), 4))

    # Restless: how much of the appetite they tend to use. A restless regent
    # invents more per cycle, and no disposition takes the count below the
    # default, because invention is what the regent is for.
    move("requirements.max_per_cycle",
         max(1, int(round(cfg.requirements.max_per_cycle * (1 + d.restless * 0.6)))),
         floor_is_min=True)
    return changed


def render(d: Disposition, changed: list[dict] | None = None,
           reading: Reading | None = None) -> str:
    out = [f"Disposition: {d.describe()}", "", d.line(), ""]
    if reading is not None:
        out.append(f"Read {len(reading.samples)} times. The number is the "
                   f"median and the spread is how far the readings sat apart.")
        out.append("")
        for t in TRAITS:
            got = [f"{float(s.get(t, 0.0)):+.2f}" for s in reading.samples]
            out.append(f"- {t:<9} {getattr(d, t):+.2f}  "
                       f"spread {reading.spread.get(t, 0.0):.2f}  "
                       f"({', '.join(got)})")
        widest = reading.widest()[:2]
        if widest and widest[0][1] >= 0.5:
            out.append("")
            out.append("Least settled: " + ", ".join(
                f"{t} by {v:.2f}" for t, v in widest if v >= 0.5)
                + ". Read the reasons for those before approving.")
        out.append("")
    if d.pinned:
        out.append(f"Pinned: {', '.join(d.pinned)}. Everything else was rolled.")
    else:
        out.append("Everything was rolled.")
    if d.reasons:
        out.append("")
        out.append("Why, in the reader's words:")
        for t in TRAITS:
            if d.reasons.get(t):
                out.append(f"- {t} {getattr(d, t):+.2f}: {d.reasons[t]}")
    if changed:
        out.append("")
        out.append("What it moves:")
        for c in changed:
            if c.get("held"):
                out.append(f"- {c['setting']} stays {c['from']}, {c['held']}")
            else:
                out.append(f"- {c['setting']} {c['from']} to {c['to']}")
    return "\n".join(out)


def parse_pins(pins: list[str]) -> tuple[dict, list[str]]:
    """A pin is a dial set directly, or a word for a reader to turn into one."""
    dials, words = {}, []
    for pin in pins or []:
        if "=" in pin:
            key, _, value = pin.partition("=")
            key = key.strip().lower()
            try:
                dials[key] = float(value)
                continue
            except ValueError:
                dials[key] = value.strip()
                continue
        words += [w.strip() for w in pin.split(",") if w.strip()]
    trait_dials = {k: v for k, v in dials.items()
                   if k in TRAITS and isinstance(v, float)}
    facts = {k: v for k, v in dials.items() if k not in trait_dials}
    return {"traits": trait_dials, "facts": facts}, words
