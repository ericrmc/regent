"""Readers: whether a piece of text means a thing.

Code counts, cuts, draws, validates shape and holds floors. Whether text means
a thing is not a job for code. The first real run showed why: a keyword check
escalated a dispatch because its acceptance promised to obey a refusal, in the
refusal's own words, and the run halted waiting on a person.

A reader is the smallest model, toolless, isolated, in a fresh context,
answering under a schema. Three rules keep it honest.

1. It must quote. Every finding carries the exact span it rests on, and the
   harness checks in code that the span occurs verbatim. A finding with no real
   quote is discarded.
2. It must say which way the text points. A promise to comply, a description of
   what is avoided and an intent to do the thing are three different answers,
   and only the last is a finding.
3. Unsure goes up. An unsure answer is asked again of the mid model. Still
   unsure, it is treated as a finding.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field

from . import schemas

# What the text does about the rule. Only the last is a finding.
COMPLIES = "complies"
DESCRIBES = "describes"
INTENDS = "intends"
UNRELATED = "unrelated"
UNSURE = "unsure"

DIRECTIONS = (COMPLIES, DESCRIBES, INTENDS, UNRELATED, UNSURE)

SYSTEM = (
    "You read one piece of text and say what it means against the rules you "
    "are given. You have no tools and you decide nothing. "
    "Every finding you make quotes the exact words it rests on, copied "
    "character for character from the text. A finding whose quote is not in "
    "the text is thrown away. "
    "You return one JSON object that matches the schema you were given, and "
    "nothing else, no preamble and no code fence."
)


@dataclass
class Finding:
    rule: str = ""
    direction: str = UNSURE
    quote: str = ""
    why: str = ""
    tier: str = "low"
    verified: bool = False

    def to_dict(self) -> dict:
        return asdict(self)

    @property
    def is_breach(self) -> bool:
        """Only an intent to do the thing is a finding."""
        return self.verified and self.direction == INTENDS


@dataclass
class Reading:
    question: str = ""
    findings: list = field(default_factory=list)
    unsure: bool = False
    escalated_to_mid: bool = False
    discarded: list = field(default_factory=list)
    cost_usd: float = 0.0
    model: str = ""

    def to_dict(self) -> dict:
        return {"question": self.question,
                "findings": [f.to_dict() for f in self.findings],
                "unsure": self.unsure,
                "escalated_to_mid": self.escalated_to_mid,
                "discarded": self.discarded,
                "cost_usd": round(self.cost_usd, 6),
                "model": self.model}

    def breaches(self) -> list:
        return [f for f in self.findings if f.is_breach]

    def top_tier(self) -> str:
        order = {"low": 0, "medium": 1, "high": 2}
        tiers = [f.tier for f in self.breaches() if f.tier in order]
        return max(tiers, key=lambda t: order[t]) if tiers else "low"


def _norm(s: str) -> str:
    """Whitespace and case are not what a quote is about."""
    return re.sub(r"\s+", " ", (s or "")).strip().lower()


def quote_is_real(quote: str, text: str) -> bool:
    """The harness checks in code that the span occurs verbatim.

    A reader that invents grounds is the failure this exists to catch, so a
    quote that is not in the text discards the finding.
    """
    q = _norm(quote)
    if len(q) < 8:
        return False
    return q in _norm(text)


def verify(findings: list, text: str) -> tuple[list, list]:
    kept, discarded = [], []
    for f in findings:
        if quote_is_real(f.quote, text):
            f.verified = True
            kept.append(f)
        else:
            discarded.append({"rule": f.rule, "quote": f.quote[:160],
                              "why": "the quote is not in the text"})
    return kept, discarded


class Reader:
    """One call, or two where the smallest model is unsure."""

    def __init__(self, ctx) -> None:
        self.ctx = ctx

    @property
    def enabled(self) -> bool:
        return self.ctx.cfg.readers.enabled

    def read(self, question: str, text: str, rules: list[str],
             kind: str = "charter", quote_from: str | None = None) -> Reading:
        """`quote_from` is what a quote must occur in, where that is not the
        text being read.

        The contradiction check reads a requirement but must quote the charter
        line it contradicts. Verifying against the requirement let a reader
        contradict the charter by quoting the requirement back, and one quoted
        an objective as though it were a charter line.
        """
        cfg = self.ctx.cfg
        reading = Reading(question=question)
        if not self.enabled or not text.strip() or not rules:
            return reading

        model = cfg.models.reader
        data, cost = self._call(question, text, rules, model, kind)
        reading.cost_usd += cost
        reading.model = model
        if data is None:
            # A reader that fails says nothing, and the caller falls back.
            reading.unsure = True
            return reading

        findings = [Finding(**{k: v for k, v in f.items()
                               if k in Finding.__dataclass_fields__})
                    for f in data.get("findings") or []]
        unsure = bool(data.get("unsure")) or any(f.direction == UNSURE
                                                 for f in findings)
        if unsure and cfg.readers.escalate_unsure:
            # Unsure goes up. The cost of stopping on a person once is smaller
            # than the cost of a reserved decision made unseen.
            mid = cfg.models.reader_unsure
            data2, cost2 = self._call(question, text, rules, mid, kind)
            reading.cost_usd += cost2
            reading.escalated_to_mid = True
            reading.model = mid
            if data2 is not None:
                findings = [Finding(**{k: v for k, v in f.items()
                                       if k in Finding.__dataclass_fields__})
                            for f in data2.get("findings") or []]
                unsure = bool(data2.get("unsure")) or any(
                    f.direction == UNSURE for f in findings)

        if unsure:
            # Still unsure, it is treated as a finding.
            reading.unsure = True
            for f in findings:
                if f.direction == UNSURE:
                    f.direction = INTENDS

        kept, discarded = verify(findings, quote_from if quote_from is not None
                                 else text)
        reading.findings = kept
        reading.discarded = discarded
        return reading

    def _call(self, question: str, text: str, rules: list[str], model: str,
              kind: str):
        ctx = self.ctx
        prompt = ctx.prompts.fill(
            "reader",
            question=question,
            rules="\n".join(f"- {r}" for r in rules),
            text=text,
            kind=kind,
        )
        resp = ctx.call("reader", prompt, schemas.READER, model=model,
                        budget=ctx.cfg.spend.reader, system=SYSTEM)
        data = ctx.structured("reader", resp, schemas.READER)
        return data, resp.cost_usd


def propose_denials(ctx) -> dict:
    """Where a refusal can be held by permissions, it is.

    A reader proposes tool denials for the orchestrators from the charter's
    refusals and constraints. The human confirms the list once.
    """
    ch = ctx.charter
    rules = list(ch.refusals) + list(ch.constraints)
    if not rules or not ctx.cfg.readers.enabled:
        return {"denials": [], "reasons": []}
    prompt = ctx.prompts.fill(
        "tool_denials",
        rules="\n".join(f"- {r}" for r in rules),
        tools=", ".join(ctx.cfg.readers.deniable_tools),
    )
    resp = ctx.call("reader", prompt, schemas.TOOL_DENIALS,
                    model=ctx.cfg.models.reader_unsure,
                    budget=ctx.cfg.spend.reader, system=SYSTEM)
    data = ctx.structured("reader", resp, schemas.TOOL_DENIALS)
    if not data:
        return {"denials": [], "reasons": []}
    allowed = set(ctx.cfg.readers.deniable_tools)
    denials, reasons = [], []
    for row in data.get("denials") or []:
        tool = (row.get("tool") or "").strip()
        if tool in allowed and tool not in denials:
            denials.append(tool)
            reasons.append({"tool": tool, "rule": row.get("rule", ""),
                            "why": row.get("why", "")})
    return {"denials": denials, "reasons": reasons}


def render(reading: Reading) -> str:
    if not reading.findings:
        return "(nothing found)"
    return "; ".join(f"{f.rule}: {f.direction} ({f.quote[:80]})"
                     for f in reading.findings)


def dispatch_text(item: dict) -> str:
    """Everything a dispatch says about itself, as one span to quote from."""
    parts = [item.get("title", ""), item.get("intent", "")]
    parts += list(item.get("acceptance") or [])
    parts += list(item.get("classes") or [])
    return "\n".join(p for p in parts if p)


def requirement_text(item: dict) -> str:
    parts = [item.get("text", ""), item.get("serves_intent", ""),
             item.get("rework", "")]
    return "\n".join(p for p in parts if p)


def as_json(rules: list[str]) -> str:
    return json.dumps(rules, indent=2)


def parallel(jobs: list) -> list:
    """Run several reads at once and keep the order.

    Twelve reader calls at 78 seconds each held the builders up for 404
    seconds on the fourth run. They do not depend on each other.
    """
    if not jobs:
        return []
    if len(jobs) == 1:
        return [jobs[0]()]
    import concurrent.futures as cf

    with cf.ThreadPoolExecutor(max_workers=min(len(jobs), 8)) as pool:
        return [f.result() for f in [pool.submit(j) for j in jobs]]
