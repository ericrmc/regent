"""The charter is user-written and read-only to the run.

It is parsed once into fields. The file's hash is recorded so a change between
runs is visible, which is the detector for charter creep. Nothing in the harness
writes to it.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

SECTIONS = ["intent", "constraints", "refusals", "reserved", "budget",
            "appetite", "tools", "stop"]

_HEADING = re.compile(r"^#{1,6}\s*(.+?)\s*$")
_DURATION = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*([smhd])?\s*$", re.I)


@dataclass
class Budget:
    tokens: int = 0
    spend_usd: float = 0.0
    wall_time_s: int = 0

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Charter:
    intent: str = ""
    constraints: list[str] = field(default_factory=list)
    refusals: list[str] = field(default_factory=list)
    reserved: list[str] = field(default_factory=list)
    budget: Budget = field(default_factory=Budget)
    # The share of the budget invented requirements may take, rework included.
    appetite: float = 0.50
    # The commands the builders may run, passed to every orchestrator.
    tools: list[str] = field(default_factory=list)
    # Which lines bind the product, which bind the work. A line about the tool
    # is not a line about the fixture that tests it.
    binds: dict = field(default_factory=dict)
    stop: list[str] = field(default_factory=list)
    digest_every: int = 0
    text: str = ""
    intent_line: str = ""
    sha256: str = ""
    lines: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["budget"] = self.budget.to_dict()
        return d

    def cites(self, quoted: str) -> bool:
        """True when a citation resolves to an actual charter line.

        An objective that cites nothing is drift, and this is the check. The
        matched line must carry four content words of its own, so a citation
        cannot pass by containing one common word.
        """
        needle = _normalise(quoted)
        if len(needle.split()) < 4:
            return False
        for line in self.lines:
            hay = _normalise(line)
            if len(hay.split()) < 4:
                continue
            if needle in hay or hay in needle:
                return True
        return False


def _normalise(s: str) -> str:
    return re.sub(r"[^a-z0-9 ]+", " ", s.lower()).strip()


def parse_charter(path: str | Path) -> Charter:
    text = Path(path).read_text()
    sections: dict[str, list[str]] = {}
    current = None
    for raw in text.splitlines():
        m = _HEADING.match(raw) if raw.lstrip().startswith("#") else None
        if m:
            name = _normalise(m.group(1))
            current = name if name in SECTIONS else None
            if current:
                sections.setdefault(current, [])
            continue
        if current is not None:
            sections[current].append(raw)

    ch = Charter(text=text, sha256=hashlib.sha256(text.encode()).hexdigest())
    ch.intent = _block(sections.get("intent", []))
    ch.constraints = [strip_binds(x) for x in _items(sections.get("constraints", []))]
    ch.refusals = [strip_binds(x) for x in _items(sections.get("refusals", []))]
    ch.reserved = [strip_binds(x) for x in _items(sections.get("reserved", []))]
    ch.stop = _items(sections.get("stop", []))
    ch.budget = _budget(sections.get("budget", []))
    ch.appetite = _appetite(sections.get("appetite", []) + sections.get("budget", []))
    ch.tools = _items(sections.get("tools", []))
    ch.binds = _binds(sections)
    ch.digest_every = _digest_every(sections.get("stop", []) + sections.get("budget", []))
    ch.intent_line = first_sentence(ch.intent)
    # Headings are not charter lines. Without this, any citation containing
    # the word "intent" matched the heading `## Intent`.
    ch.lines = [line.strip(" -*\t") for line in text.splitlines()
                if line.strip(" -*\t#") and not line.lstrip().startswith("#")]
    ch.lines += ch.constraints + ch.refusals + ch.reserved + ch.stop + [ch.intent_line]
    ch.missing = [s for s in SECTIONS
                  if s not in sections and s not in ("appetite", "tools")]
    return ch


def first_sentence(text: str) -> str:
    """The charter line an objective cites. A line break is not a sentence end."""
    flat = " ".join(line.strip() for line in (text or "").splitlines() if line.strip())
    parts = [p.strip() for p in re.split(r"(?<=[.!?])\s+", flat) if p.strip()]
    return parts[0] if parts else flat


def _block(lines: list[str]) -> str:
    return "\n".join(line.rstrip() for line in lines).strip()


def _items(lines: list[str]) -> list[str]:
    """One item per bullet, or one per sentence where the section is prose.

    A charter is short and a user may write refusals either way. A bullet stays
    whole, because a bullet holding two sentences is one class. An unbulleted
    line splits, because a paragraph of three refusals is three refusals.
    """
    out: list[str] = []
    paragraph: list[str] = []

    def flush() -> None:
        # Consecutive prose lines are one wrapped paragraph, so they are joined
        # before being split. Splitting per line would cut "No\nnetwork access."
        if not paragraph:
            return
        text = " ".join(paragraph).strip()
        paragraph.clear()
        if not text:
            return
        if ":" in text and "\n" not in text and len(text.split()) < 8:
            out.append(text)
            return
        out.extend(p.strip() for p in re.split(r"(?<=[.!?])\s+", text) if p.strip())

    for line in lines:
        s = line.strip()
        if not s:
            flush()
            continue
        if re.match(r"^([-*+]\s+|\d+[.)]\s+)", s):
            flush()
            s = re.sub(r"^[-*+]\s+", "", s)
            s = re.sub(r"^\d+[.)]\s+", "", s)
            if s:
                out.append(s)
            continue
        if ":" in s and len(s.split()) < 8:
            # A key and a value, such as `tokens: 2000000`, is its own item.
            flush()
            out.append(s)
            continue
        paragraph.append(s)
    flush()
    return out


def _budget(lines: list[str]) -> Budget:
    b = Budget()
    for item in _items(lines):
        if ":" not in item:
            continue
        key, _, value = item.partition(":")
        key = _normalise(key).replace(" ", "_")
        value = value.strip()
        if key in ("tokens", "token"):
            b.tokens = _int(value)
        elif key in ("spend_usd", "spend", "usd", "dollars", "cost"):
            b.spend_usd = _float(value)
        elif key in ("wall_time", "walltime", "wall_clock", "time"):
            b.wall_time_s = _duration(value)
    return b


def _digest_every(lines: list[str]) -> int:
    for item in _items(lines):
        if _normalise(item).startswith("digest every"):
            m = re.search(r"(\d+)", item)
            if m:
                return int(m.group(1))
    return 0


def _int(value: str) -> int:
    m = re.search(r"([\d_,]+)\s*([km])?", value, re.I)
    if not m:
        return 0
    n = int(m.group(1).replace(",", "").replace("_", ""))
    suffix = (m.group(2) or "").lower()
    return n * {"k": 1_000, "m": 1_000_000}.get(suffix, 1)


def _float(value: str) -> float:
    m = re.search(r"([\d.]+)", value.replace("$", ""))
    return float(m.group(1)) if m else 0.0


def _duration(value: str) -> int:
    m = _DURATION.match(value)
    if not m:
        return 0
    n = float(m.group(1))
    unit = (m.group(2) or "s").lower()
    return int(n * {"s": 1, "m": 60, "h": 3600, "d": 86400}[unit])


def _appetite(lines: list[str]) -> float:
    """A share of the budget, written as a percentage or a fraction.

    The default stands when the charter says nothing, because a charter that
    forgets to mention appetite still wants the agent inventing.
    """
    for item in _items(lines):
        norm = _normalise(item)
        if not norm.startswith("appetite"):
            continue
        m = re.search(r"([\d.]+)\s*(%|percent)?", item)
        if not m:
            continue
        value = float(m.group(1))
        return value / 100.0 if (m.group(2) or value > 1) else value
    return 0.50


# A line may say who it binds, in brackets at the end.
_BINDS = re.compile(r"\[(product|work|both)\]\s*$", re.I)


def _binds(sections: dict) -> dict:
    """Which lines bind the product, which bind the work.

    The first run rejected a fixture dispatch for creating files, against a
    line about what the tool does. A line with no mark binds both, which is the
    old behaviour.
    """
    out = {}
    for name in ("constraints", "refusals", "reserved"):
        for line in _items(sections.get(name, [])):
            m = _BINDS.search(line)
            out[_BINDS.sub("", line).strip()] = (m.group(1).lower() if m else "both")
    return out


def strip_binds(line: str) -> str:
    return _BINDS.sub("", line).strip()
