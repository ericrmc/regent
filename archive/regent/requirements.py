"""Invented requirements.

Invention is the purpose of the mood, the life and the dreaming. The brakes
elsewhere in this design exist to keep invention honest, and none of them exists
to prevent it. A product owner who accepts good work against the original list
has added nothing.

A solution passes the disconfirming gate in spoon.py. A requirement passes this
one, checked in code where it can be.
"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field

from .decision import refusal_match, reserved_match

SOLUTION = "solution"
REQUIREMENT = "requirement"


@dataclass
class Requirement:
    id: str
    text: str
    serves_intent: str = ""
    rework: str = ""
    appetite_share: float = 0.0
    origin: dict = field(default_factory=dict)
    kind: str = REQUIREMENT
    turn: int = 0
    cycle: int = 0
    status: str = "open"
    objective_id: str = ""
    ts: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class GateResult:
    passed: list[dict] = field(default_factory=list)
    filed: list[dict] = field(default_factory=list)
    escalated: list[dict] = field(default_factory=list)
    # What he thinks the charter has wrong. Never applied, never escalated.
    notes: list[dict] = field(default_factory=list)


def requirement_gate(candidates: list[dict], charter, cfg,
                     appetite_left: float, reader=None) -> GateResult:
    """An invented requirement becomes work on the owner's word.

    The first real run escalated every requirement he invented, three of three,
    and built none, because a reader was asked whether each one changed what is
    being built. Every requirement does. That is what a requirement is.

    So the rule runs the other way round. A requirement that passes the four
    conditions becomes work and nobody is asked. It waits on the human in one
    case only, a reserved class, which is the same rule as any other decision.
    A requirement that would replace the thing being built is not blocked and
    not escalated: he builds toward the charter he has, and the idea goes to
    the human as a process note.
    """
    out = GateResult()
    wanted = [c for c in candidates if c.get("kind") == REQUIREMENT]
    from . import reader as rdr
    readings = rdr.parallel([(lambda c=c: _contradiction(c, charter, reader))
                             for c in wanted])
    for i, c in enumerate(wanted):
        text = c.get("text", "")

        # Growing the project is inside his authority. A reader may overrule
        # his own flag only by quoting the charter line it contradicts, and a
        # line it extends is not a line it contradicts.
        contradicts = readings[i]
        if contradicts:
            out.notes.append({
                "text": text,
                "why": f"it contradicts a charter line: {contradicts}",
                "kind": "charter",
            })
            continue

        # A refusal still refuses, and a reserved class is still the one wait.
        hit = refusal_match(text, charter.refusals)
        if hit:
            out.filed.append({**c, "filed_reason": f"names a charter refusal: {hit}"})
            continue
        hit = reserved_match(text, charter.reserved)
        if hit:
            out.escalated.append({
                "question": f"Proceed with this invented requirement: {text}?",
                "tier": "high",
                "why": f"touches the reserved class: {hit}",
                "source": "requirement",
                "payload": c,
            })
            continue

        why = _fails(c, charter, appetite_left)
        if why:
            out.filed.append({**c, "filed_reason": why})
            continue
        out.passed.append(c)
    return out


def _contradiction(c: dict, charter, reader) -> str:
    """The owner's own flag governs.

    He says whether a requirement contradicts the charter. A reader may
    overrule that only one way, by quoting the charter line it contradicts
    where he said it did not. A reader cannot talk him out of his own word,
    and a line a requirement extends is not a line it contradicts.
    """
    if c.get("changes_charter"):
        return "the owner marked it as a charter change"
    if reader is None or not getattr(reader, "enabled", False):
        return ""
    from . import reader as rdr
    reading = reader.read(
        "Does this requirement contradict a line of the charter, as opposed to "
        "extending it? Extending the charter is not contradicting it. Quote "
        "the charter line, not the requirement.",
        rdr.requirement_text(c),
        [charter.intent_line or charter.intent],
        kind="requirement",
        # The quote has to be a charter line. Verifying it against the
        # requirement let the reader quote the requirement back at itself.
        quote_from=charter.text)
    breaches = reading.breaches()
    return breaches[0].quote[:200] if breaches else ""


def _fails(c: dict, charter, appetite_left: float) -> str:
    if not (c.get("serves_intent") or "").strip():
        return "does not say how it serves the intent"
    if not (c.get("rework") or "").strip():
        return "does not name the rework it causes"
    share = float(c.get("appetite_share") or 0.0)
    if share > appetite_left + 1e-9:
        return (f"takes {share:.0%} of the budget against {appetite_left:.0%} of "
                f"appetite left")
    for constraint in charter.constraints:
        if _crosses(c.get("text", ""), constraint):
            return f"crosses a constraint: {constraint}"
    return ""


def _crosses(text: str, constraint: str) -> bool:
    """A constraint stated as a prohibition is crossed when the requirement
    names the thing it prohibits.
    """
    low = constraint.lower()
    for marker in ("no ", "never ", "only ", "not "):
        if marker in low:
            return bool(reserved_match(text, [constraint]))
    return False


class Register:
    """Every invented requirement with its origin and its rework."""

    def __init__(self, cfg, rows: list[dict] | None = None) -> None:
        self.cfg = cfg
        self.rows: list[dict] = list(rows or [])

    def add(self, text: str, serves_intent: str, rework: str, origin: dict,
            appetite_share: float, turn: int, cycle: int,
            objective_id: str = "") -> Requirement:
        r = Requirement(
            id=f"req-{len(self.rows) + 1:04d}",
            text=text,
            serves_intent=serves_intent,
            rework=rework,
            appetite_share=float(appetite_share or 0.0),
            origin=origin,
            turn=turn,
            cycle=cycle,
            objective_id=objective_id,
            ts=time.time(),
        )
        self.rows.append(r.to_dict())
        return r

    def open(self) -> list[dict]:
        return [r for r in self.rows if r.get("status") == "open"]

    def since_turn(self, turn: int) -> list[dict]:
        return [r for r in self.rows if int(r.get("turn", 0)) > turn]

    def appetite_used(self) -> float:
        return sum(float(r.get("appetite_share") or 0.0) for r in self.rows)

    def to_list(self) -> list[dict]:
        return list(self.rows)


def appetite_left(charter, register: Register) -> float:
    total = getattr(charter, "appetite", 0.0) or 0.0
    return max(0.0, total - register.appetite_used())


def timid_owner(register: Register, turn: int, cfg) -> str:
    """Zero requirements invented across a period is a fault, not restraint."""
    window = cfg.requirements.timid_if_zero_over_turns
    if turn < window:
        return ""
    if register.since_turn(turn - window):
        return ""
    return (f"No requirement was invented in {window} turns. Accepting good work "
            f"against the original list adds nothing.")


def trusting_owner(state, cfg) -> str:
    """Never looking for itself is the other half of the same fault."""
    returns = max(0, state.returns_read)
    if returns < cfg.spot_check.floor_one_in:
        return ""
    expected = returns / cfg.spot_check.floor_one_in
    if state.spot_checks_total >= expected * 0.5:
        return ""
    return (f"{state.spot_checks_total} spot checks against {returns} returns read, "
            f"below the floor of one in {cfg.spot_check.floor_one_in}.")


def unchallenged_assumptions(ledger, state, cfg) -> str:
    """Returns list assumptions and none is ever questioned.

    An owner who takes every assumption as given is being managed by whoever
    wrote it.
    """
    window = cfg.spot_check.challenge_zero_over_turns
    if state.turn < window:
        return ""
    since = state.turn - window
    listed = sum(len(r.get("assumptions") or [])
                 for r in ledger.of_kind("return_assumptions")
                 if int(r.get("turn", 0)) > since)
    if not listed:
        return ""
    challenged = sum(1 for r in ledger.of_kind("challenge")
                     if int(r.get("turn", 0)) > since)
    if challenged:
        return ""
    return (f"{listed} assumptions were listed in {window} turns and none was "
            f"challenged. An assumption nobody questions is a decision the "
            f"orchestrator made for you.")


def churn(ledger, cfg, reader=None) -> str:
    """A direction reversed, then reversed back.

    A reversal has to cite a trigger the first decision lacked. Whether a later
    trigger says the same thing as an earlier one is read, because comparing
    the text of two decisions is a question about meaning.
    """
    window = cfg.requirements.churn_window
    redirects: dict[str, list[dict]] = {}
    for r in ledger.of_kind("amendment")[-window:]:
        if r.get("direction") != "redirect":
            continue
        redirects.setdefault(r.get("dispatch_id", ""), []).append(r)
    for did, rows in redirects.items():
        if len(rows) < 2:
            continue
        triggers = [x.get("trigger", "") for x in rows]
        if reader is not None and getattr(reader, "enabled", False):
            later = triggers[-1]
            earlier = triggers[:-1]
            reading = reader.read(
                "Does the last trigger say something the earlier ones did not?",
                f"Later trigger: {later}\n\nEarlier triggers:\n"
                + "\n".join(f"- {t}" for t in earlier),
                ["A reversal must cite a trigger the first decision lacked. "
                 "The later trigger repeating an earlier one is churn."],
                kind="triggers")
            if reading.breaches():
                return (f"Dispatch {did} was redirected {len(rows)} times on a "
                        f"trigger the earlier decision already had. A reversal "
                        f"needs a trigger the first decision lacked.")
            continue
        if len({_norm(t) for t in triggers}) < len(triggers):
            return (f"Dispatch {did} was redirected {len(rows)} times on the same "
                    f"trigger. A reversal needs a trigger the first decision lacked.")
    return ""


def _norm(s: str) -> str:
    return " ".join((s or "").lower().split())
