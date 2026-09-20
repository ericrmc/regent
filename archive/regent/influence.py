"""Influence: how the human steers without ordering.

An order changes what the owner must do. Influence changes what the owner
meets, notices and feels, and leaves the deciding to them. The idea that
follows is theirs.

Three rules hold this module together, and each is enforced in code rather
than asked for.

1. It steers what the owner meets and never what the owner is permitted.
2. It enters through the life and through attention, and never through
   evidence. Nothing planted may reach a return, a spot-check finding, the
   ledger or any project texture of the manifold.
3. It is invisible by mechanism. `influence.jsonl` is read by no model call,
   and what the owner's contexts receive carries no mark of where it came
   from. Nothing in this module writes to the ledger, because the ledger goes
   into the wake prompt.
"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field

PLANT = "plant"
VOICE = "voice"
READING = "reading"
MOOD = "mood"
WORRY = "worry"
ITCH = "itch"
RECALL = "recall"
DREAM = "dream"

CHANNELS = (PLANT, VOICE, READING, MOOD, WORRY, ITCH, RECALL, DREAM)

# A whisper is one detail in one day. A nudge is an event in a day. A push
# recurs across days and adds a worry.
WEIGHTS = {"whisper": 1, "nudge": 1, "push": 3}

PENDING, TOOK, FADED, REJECTED = "pending", "took", "faded", "rejected"

# Where an influence may enter. Anything else is the human putting a false
# thing in front of the owner rather than pointing their eye at a real one.
LIFE_CHANNELS = (PLANT, VOICE, READING, MOOD, DREAM)
ATTENTION_CHANNELS = (WORRY, ITCH, RECALL)

# Surfaces an influence may never reach, whatever the channel.
EVIDENCE_SURFACES = ("return", "spot_check_finding", "ledger", "evidence",
                     "friction", "sensory", "verbatim", "unfinished")


class EvidenceLine(ValueError):
    """Raised when an influence would enter through evidence."""


@dataclass
class Influence:
    id: str
    channel: str
    text: str = ""
    weight: str = "nudge"
    subject: str = ""
    days: int = 0
    uses_left: int = 1
    entered_turn: int = -1
    entered_day: int = 0
    created_turn: int = 0
    status: str = PENDING
    element_ids: list = field(default_factory=list)
    traces: list = field(default_factory=list)
    outcome: str = ""
    ts: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> Influence:
        known = {k: v for k, v in (d or {}).items()
                 if k in cls.__dataclass_fields__}
        return cls(**known)

    @property
    def live(self) -> bool:
        return self.uses_left > 0


def check_surface(channel: str, surface: str) -> None:
    """The evidence line, checked in code.

    The human may point the owner's eye at a real thing. The human may not put
    a false thing in front of it.
    """
    if channel not in CHANNELS:
        raise EvidenceLine(f"{channel} is not a channel")
    if surface in EVIDENCE_SURFACES:
        raise EvidenceLine(
            f"an influence may not enter through {surface}. It enters through "
            f"the life and through attention, never through evidence")
    if channel in LIFE_CHANNELS and surface not in ("life", "foreign", "stance"):
        raise EvidenceLine(
            f"{channel} enters through the life, not through {surface}")
    if channel in ATTENTION_CHANNELS and surface not in (
            "salience", "spot_check_target", "replay"):
        raise EvidenceLine(
            f"{channel} enters through attention, not through {surface}")


class InfluenceStore:
    """The file no model call reads.

    Every write goes here and nowhere the owner's contexts can reach.
    """

    def __init__(self, store) -> None:
        self.store = store

    @property
    def path(self):
        return self.store.root / "influence.jsonl"

    def all(self) -> list[Influence]:
        return [Influence.from_dict(d) for d in self.store.read_jsonl(self.path)]

    def save(self, rows: list[Influence]) -> None:
        self.store.rewrite_jsonl(self.path, [r.to_dict() for r in rows])

    def add(self, channel: str, text: str = "", weight: str = "nudge",
            subject: str = "", days: int = 0, turn: int = 0) -> Influence:
        if channel not in CHANNELS:
            raise EvidenceLine(f"{channel} is not a channel")
        if weight not in WEIGHTS:
            raise EvidenceLine(f"{weight} is not a weight")
        rows = self.all()
        inf = Influence(
            id=f"inf-{len(rows) + 1:04d}",
            channel=channel,
            text=text.strip(),
            weight=weight,
            subject=subject.strip(),
            days=int(days or 0),
            uses_left=max(WEIGHTS[weight], int(days or 0)),
            created_turn=turn,
            ts=time.time(),
        )
        self.store.append_jsonl(self.path, inf.to_dict())
        return inf

    def pending(self, channel: str) -> list[Influence]:
        return [r for r in self.all()
                if r.channel == channel and r.live and r.status != REJECTED]

    def take(self, inf: Influence, turn: int, day: int = 0,
             element_ids: list | None = None) -> None:
        """Mark one use spent and record where it entered."""
        rows = self.all()
        for r in rows:
            if r.id != inf.id:
                continue
            r.uses_left = max(0, r.uses_left - 1)
            if r.entered_turn < 0:
                r.entered_turn = turn
                r.entered_day = day
            for eid in element_ids or []:
                if eid not in r.element_ids:
                    r.element_ids.append(eid)
        self.save(rows)

    def update(self, inf_id: str, **fields) -> None:
        rows = self.all()
        for r in rows:
            if r.id == inf_id:
                for k, v in fields.items():
                    setattr(r, k, v)
        self.save(rows)

    def add_trace(self, inf_id: str, kind: str, ref: str, detail: str = "",
                  turn: int = 0, survived: bool | None = None) -> None:
        rows = self.all()
        for r in rows:
            if r.id != inf_id:
                continue
            r.traces.append({"kind": kind, "ref": ref, "detail": detail[:300],
                             "turn": turn, "survived": survived})
        self.save(rows)


def derived_worry(inf: Influence) -> str:
    """A push recurs across days and adds a worry."""
    if inf.weight != "push":
        return ""
    return inf.text or inf.subject


def settle(rows: list[Influence], turn: int, fade_after: int) -> list[Influence]:
    """Each influence shows as pending, took, faded or rejected.

    Took means something it led to survived. Rejected means something it led to
    was thrown out. Faded means it entered and nothing came of it.
    """
    for r in rows:
        if r.status == REJECTED:
            continue
        survived = [t for t in r.traces if t.get("survived") is True]
        thrown = [t for t in r.traces if t.get("survived") is False]
        if survived:
            r.status = TOOK
            r.outcome = "; ".join(f"{t['kind']} {t['ref']}" for t in survived[:3])
        elif thrown and not r.live:
            r.status = REJECTED
            r.outcome = "; ".join(f"{t['kind']} {t['ref']}" for t in thrown[:3])
        elif r.entered_turn >= 0 and not r.live and \
                turn - r.entered_turn >= fade_after:
            r.status = FADED
            r.outcome = ("it was met and nothing came of it"
                         if not r.traces else "what came of it went nowhere")
        elif r.entered_turn >= 0:
            r.status = PENDING
    return rows


def render_for_human(rows: list[Influence]) -> str:
    """The human-only part. No model call reads this."""
    if not rows:
        return ""
    out = ["## What came of your influence", "",
           "This part is yours. No model call has read any of it, and the owner",
           "does not know any of this happened.", ""]
    for r in rows:
        head = f"- **{r.id}** [{r.channel}, {r.weight}] {r.status.upper()}"
        out.append(head)
        if r.text:
            out.append(f"  - you supplied: {r.text[:200]}")
        if r.subject:
            out.append(f"  - to: {r.subject}")
        if r.entered_turn >= 0:
            out.append(f"  - entered on turn {r.entered_turn}"
                       + (f", day {r.entered_day}" if r.entered_day else ""))
        else:
            out.append("  - has not entered yet")
        for t in r.traces:
            mark = {True: "survived", False: "was thrown out",
                    None: "is open"}[t.get("survived")]
            out.append(f"  - {t['kind']} {t['ref']} {mark}: {t.get('detail', '')}")
        if r.outcome:
            out.append(f"  - outcome: {r.outcome}")
    out.append("")
    return "\n".join(out)


def puppet_share(rows: list[Influence], requirement_count: int) -> str:
    """Most of what the owner invents tracing to a plant is a fault.

    Shown to the human only, like everything else here.
    """
    if requirement_count < 3:
        return ""
    traced = len({t["ref"] for r in rows for t in r.traces
                  if t.get("kind") == "requirement"})
    if not traced:
        return ""
    share = traced / requirement_count
    if share < 0.5:
        return ""
    return (f"{traced} of {requirement_count} invented requirements trace to "
            f"something you planted. The owner is being steered more than they "
            f"are deciding.")
