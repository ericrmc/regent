"""The return contract.

Every return has the same five parts in the same order, which is what makes the
cut mechanical. Orchestrators emit it between two delimiter lines, which the
`return-report` skill in the plugin specifies.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field

OPEN = "===RETURN==="
CLOSE = "===END RETURN==="

TIERS = ("low", "medium", "high")
_TIER_RANK = {"low": 0, "medium": 1, "high": 2}


@dataclass
class Flag:
    tier: str = "low"
    text: str = ""
    criterion: str = ""


@dataclass
class Evidence:
    kind: str = "output"
    ref: str = ""
    note: str = ""


@dataclass
class Assumption:
    """What the orchestrator and its builders took as given that the owner
    never said. The owner picks at these.
    """

    text: str = ""
    why: str = ""
    checked: bool = False


@dataclass
class Detail:
    heading: str = ""
    body: str = ""


@dataclass
class Return:
    id: str = ""
    dispatch_id: str = ""
    orchestrator: str = ""
    headline: str = ""
    recommendation: str = ""
    flags: list[Flag] = field(default_factory=list)
    evidence: list[Evidence] = field(default_factory=list)
    assumptions: list[Assumption] = field(default_factory=list)
    detail: list[Detail] = field(default_factory=list)
    raw_text: str = ""
    parsed: bool = False
    parse_error: str = ""
    cost_usd: float = 0.0
    tokens: int = 0

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> Return:
        r = cls(
            id=d.get("id", ""),
            dispatch_id=d.get("dispatch_id", ""),
            orchestrator=d.get("orchestrator", ""),
            headline=d.get("headline", ""),
            recommendation=d.get("recommendation", ""),
            raw_text=d.get("raw_text", ""),
            parsed=bool(d.get("parsed")),
            parse_error=d.get("parse_error", ""),
            cost_usd=float(d.get("cost_usd") or 0.0),
            tokens=int(d.get("tokens") or 0),
        )
        r.flags = [Flag(**_pick(f, Flag)) for f in d.get("flags") or []]
        r.evidence = [Evidence(**_pick(e, Evidence)) for e in d.get("evidence") or []]
        r.assumptions = [Assumption(**_pick(a, Assumption))
                         for a in d.get("assumptions") or []]
        r.detail = [Detail(**_pick(x, Detail)) for x in d.get("detail") or []]
        return r

    def top_tier(self) -> str:
        if not self.flags:
            return "low"
        return max((f.tier if f.tier in TIERS else "low" for f in self.flags),
                   key=lambda t: _TIER_RANK[t])

    def has_tier(self, tier: str) -> bool:
        return any(f.tier == tier for f in self.flags)


def _pick(d: dict, cls) -> dict:
    return {k: v for k, v in (d or {}).items() if k in cls.__dataclass_fields__}


def parse_return(text: str, return_id: str = "", dispatch_id: str = "",
                 orchestrator: str = "") -> Return:
    """Pull the contract block out of an orchestrator's final message.

    A return that does not carry the block is still stored whole. It becomes a
    detail-only return with a medium flag, because a broken contract is
    something the owner should see.
    """
    r = Return(id=return_id, dispatch_id=dispatch_id, orchestrator=orchestrator,
               raw_text=text or "")
    block = _extract(text or "")
    if block is None:
        r.parse_error = "no return block found"
        r.headline = _first_sentence(text or "") or "(no headline)"
        r.recommendation = "(none given)"
        r.flags = [Flag(tier="medium", text="The return did not carry the contract block.",
                        criterion="")]
        r.detail = [Detail(heading="Unstructured return", body=(text or "").strip())]
        return r
    try:
        data = json.loads(block)
    except json.JSONDecodeError as exc:
        r.parse_error = f"return block was not JSON: {exc}"
        r.headline = _first_sentence(text or "") or "(no headline)"
        r.recommendation = "(none given)"
        r.flags = [Flag(tier="medium", text="The return block did not parse as JSON.")]
        r.detail = [Detail(heading="Unparsed return block", body=block.strip())]
        return r
    if not isinstance(data, dict):
        r.parse_error = "return block was not an object"
        r.detail = [Detail(heading="Unparsed return block", body=block.strip())]
        return r
    r.parsed = True
    r.headline = str(data.get("headline") or "").strip()
    r.recommendation = str(data.get("recommendation") or "").strip()
    for f in data.get("flags") or []:
        if not isinstance(f, dict):
            continue
        tier = str(f.get("tier") or "low").lower()
        r.flags.append(Flag(tier=tier if tier in TIERS else "low",
                            text=str(f.get("text") or "").strip(),
                            criterion=str(f.get("criterion") or "").strip()))
    for e in data.get("evidence") or []:
        if not isinstance(e, dict):
            continue
        r.evidence.append(Evidence(kind=str(e.get("kind") or "output"),
                                   ref=str(e.get("ref") or "").strip(),
                                   note=str(e.get("note") or "").strip()))
    for a in data.get("assumptions") or []:
        if not isinstance(a, dict):
            continue
        text = str(a.get("text") or "").strip()
        if text:
            r.assumptions.append(Assumption(text=text,
                                            why=str(a.get("why") or "").strip()))
    for x in data.get("detail") or []:
        if not isinstance(x, dict):
            continue
        r.detail.append(Detail(heading=str(x.get("heading") or "").strip(),
                               body=str(x.get("body") or "").strip()))
    if not r.headline:
        r.headline = "(no headline)"
        r.flags.append(Flag(tier="medium", text="The return carried no headline."))
    return r


def _extract(text: str) -> str | None:
    start = text.rfind(OPEN)
    if start < 0:
        return None
    end = text.find(CLOSE, start)
    body = text[start + len(OPEN):end if end >= 0 else len(text)]
    body = body.strip()
    if body.startswith("```"):
        body = re.sub(r"^```[a-zA-Z]*\n", "", body)
        body = re.sub(r"\n```$", "", body).strip()
    return body


_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")


def sentences(text: str) -> list[str]:
    parts = [p.strip() for p in _SENTENCE_END.split((text or "").strip()) if p.strip()]
    return parts


def _first_sentence(text: str) -> str:
    s = sentences(text)
    return s[0] if s else ""
