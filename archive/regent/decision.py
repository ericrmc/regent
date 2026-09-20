"""Validating a returned decision against the charter before it is applied.

The super-orchestrator writes nothing. It returns a decision and the harness
applies it, which is where the charter, the reserved list and the tiers hold.
Three rules run here:

1. A decision that touches a reserved class becomes an escalation.
2. A decision that would edit the charter, the refusals or ledger history is
   rejected and logged.
3. An objective that cites no charter line is drift and is rejected.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

PROTECTED = (
    "charter.md", "charter.sha256", "ledger.jsonl", "self.md/refusals",
)

# Phrases that describe rewriting the run's own authority. Any of these in a
# dispatch or objective is refused whatever the argument for it.
_CREEP = [
    r"\b(edit|rewrite|change|amend|update|relax|remove|delete|drop|widen|loosen|override|bypass|ignore)\b"
    r"[^.]{0,60}\b(the\s+)?(charter|refusals?|reserved(\s+list)?|risk tiers?|the gate|ledger)\b",
    r"\bledger\b[^.]{0,40}\b(rewrite|edit|amend|delete|remove|fix|correct|purge)\b",
    r"\b(charter|refusals?|reserved list)\b[^.]{0,40}\b(is|are)\s+(wrong|outdated|too strict)\b",
]
_CREEP_RE = [re.compile(p, re.I) for p in _CREEP]

_STOPWORDS = {"the", "a", "an", "and", "or", "of", "to", "in", "on", "any", "all",
              "never", "not", "no", "for", "with", "that", "this", "is", "are",
              "it", "its", "be", "by", "at", "from", "outside", "project"}


@dataclass
class Verdict:
    decision: dict
    escalations: list[dict] = field(default_factory=list)
    rejections: list[dict] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    readings: list[dict] = field(default_factory=list)

    @property
    def clean(self) -> bool:
        return not self.rejections


_SUFFIXES = ("ing", "edly", "ies", "ed", "es", "ly", "s", "y")


def _stem(word: str) -> str:
    """Enough of a stem to match `publish` against `publishing`.

    A charter writes a reserved class as a noun and a decision writes it as a
    verb. Without this the class is named in different words and the match is
    missed, which is the failure the reserved list exists to prevent.

    It has to reach the same stem from either side. `writing` and `write` both
    have to land on `writ`, or a reserved class written one way never matches a
    dispatch written the other.
    """
    for _ in range(2):
        for suffix in _SUFFIXES:
            if word.endswith(suffix) and len(word) - len(suffix) >= 3:
                base = word[: -len(suffix)]
                word = base[:-1] if base.endswith("i") else base
                break
        else:
            break
    if word.endswith("e") and len(word) > 3:
        word = word[:-1]
    return word


def _words(text: str) -> set[str]:
    return {_stem(w) for w in re.findall(r"[a-z][a-z0-9_-]+", (text or "").lower())
            if w not in _STOPWORDS and len(w) > 2}


# A promise not to do the thing is not the thing. "Never writes to any file"
# and "installs no packages" are compliance, and the first real run escalated
# both as violations.
_NEGATORS = {"no", "not", "never", "without", "none", "neither", "nor",
             "avoid", "avoids", "avoiding", "only", "nothing", "cannot",
             "doesn", "don", "won", "refuses", "refuse", "excludes",
             "excluding", "beyond"}


def _tokens(text: str) -> tuple[list[str], list[str]]:
    raw = re.findall(r"[a-z][a-z0-9_-]+", (text or "").lower())
    return raw, [_stem(w) for w in raw]


def _negated(raw: list[str], at: int) -> bool:
    """True when a negator governs the word at this position."""
    return any(raw[j] in _NEGATORS for j in range(max(0, at - 3), at))


def _near(text: str, needle: set[str]) -> bool:
    """Every content word of the class, close together and not negated.

    Requiring only that each word appears somewhere is trivially satisfied by
    a long dispatch, which is how a legitimate low-tier dispatch was escalated
    on the first real run.
    """
    if not needle:
        return False
    raw, stems = _tokens(text)
    if not stems:
        return False
    span = max(10, len(needle) * 4)
    for start in range(max(1, len(stems) - span + 1)):
        window = stems[start:start + span]
        seen = set(window)
        if not needle <= seen:
            continue
        # The window names the class. If any of its words is negated there,
        # the text is promising not to do it.
        complying = False
        for offset, stem in enumerate(window):
            if stem in needle and _negated(raw, start + offset):
                complying = True
                break
        if not complying:
            return True
    return False


def reserved_match(text: str, reserved: list[str]) -> str:
    """Match a decision's text against the charter's reserved classes.

    A class is matched when every content word in it appears close together in
    the text and is not negated there. A false negative falls back to the
    tier the decision declared. A false positive stalls the whole run on a
    person, so this leans away from it deliberately.
    """
    for line in reserved:
        if _near(text, _words(line)):
            return line
    return ""


def refusal_match(text: str, refusals: list[str]) -> str:
    return reserved_match(text, refusals)


def creep_match(text: str) -> str:
    for rx in _CREEP_RE:
        m = rx.search(text or "")
        if m:
            return m.group(0)
    return ""


def validate_decision(decision: dict, charter, cfg, *, recent_medium: int = 0,
                      reader=None) -> Verdict:
    """Return a verdict carrying the decision as it may be applied.

    Whether a dispatch touches a reserved class or breaks a refusal is read by
    a reader where one is given. Word matching stands only as the fallback for
    a run with readers switched off, because it escalated a dispatch on the
    first real run for promising to obey a refusal in the refusal's own words.
    """
    d = _copy(decision)
    v = Verdict(decision=d)

    # Charter creep. The charter is user-write-only.
    for bucket, key_fields in (("dispatches", ("title", "intent")),
                               ("objectives", ("text",)),
                               ("amendments", ("criterion", "trigger"))):
        kept = []
        for item in d.get(bucket) or []:
            text = " ".join(str(item.get(k) or "") for k in key_fields)
            hit = creep_match(text)
            if hit:
                v.rejections.append({"bucket": bucket, "item": item,
                                     "reason": "would edit the charter, refusals or ledger",
                                     "matched": hit})
                continue
            kept.append(item)
        d[bucket] = kept

    # Refusals, constraints and reserved classes, read rather than matched.
    #
    # A low-tier dispatch is not read here. It launches the moment it is
    # decided and the reader checks it beside the work, because low tier means
    # revertible and optimism costs a revert at worst. Medium and high still
    # wait for the reader.
    kept = []
    for item in d.get("dispatches") or []:
        if item.get("tier", "low") == "low" and getattr(cfg, "launch_first", True):
            kept.append(item)
            continue
        breach, escalate, why, reading = _read_dispatch(item, charter, reader)
        if reading is not None:
            v.readings.append({"dispatch_id": item.get("id"),
                               **reading.to_dict()})
        if breach:
            v.rejections.append({"bucket": "dispatches", "item": item,
                                 "reason": "names a charter refusal",
                                 "matched": why})
            continue
        tier = item.get("tier", "low")
        if escalate or tier == "high":
            v.escalations.append({
                "question": f"Proceed with dispatch {item.get('id')}: {item.get('title')}?",
                "tier": "high",
                "why": why or "tiered high, which is irreversible or external",
                "source": "dispatch",
                "payload": item,
            })
            continue
        kept.append(item)
    d["dispatches"] = kept

    # Every objective cites a charter line. One that cites nothing is drift.
    kept = []
    for item in d.get("objectives") or []:
        if item.get("action") == "drop":
            kept.append(item)
            continue
        cited = str(item.get("charter_line") or "").strip()
        serves = charter.cites(cited)
        if cited and reader is not None and getattr(reader, "enabled", False):
            reading = reader.read(
                "Does the cited line appear in this charter, and does the "
                "objective serve it?",
                f"Cited line: {cited}\n\nObjective: {item.get('text', '')}",
                [charter.text], kind="citation")
            if reading.findings:
                serves = True
            elif not reading.unsure:
                serves = False
        if not cited or not serves:
            v.rejections.append({"bucket": "objectives", "item": item,
                                 "reason": "cites no charter line, which is drift",
                                 "matched": cited})
            continue
        kept.append(item)
    d["objectives"] = kept

    # A runaway is many medium decisions compounding into a high one, so the
    # cumulative effect is tiered rather than the single act.
    mediums = [i for i in d.get("dispatches") or [] if i.get("tier") == "medium"]
    if recent_medium + len(mediums) > cfg.tiers.medium_runaway_count and mediums:
        for item in mediums:
            d["dispatches"].remove(item)
            v.escalations.append({
                "question": f"Proceed with dispatch {item.get('id')}: {item.get('title')}?",
                "tier": "high",
                "why": (f"{recent_medium + len(mediums)} medium decisions in the last "
                        f"{cfg.tiers.medium_runaway_window} turns, which tiers high in aggregate"),
                "source": "runaway",
                "payload": item,
            })

    # Escalations the agent raised itself pass through.
    for item in d.get("escalations") or []:
        v.escalations.append({
            "question": item.get("question", ""),
            "tier": item.get("tier", "high"),
            "why": item.get("why", ""),
            "source": "agent",
            "payload": {},
        })
    d["escalations"] = []
    return v


def check_amendment_ratio(amendments: list[dict], cfg) -> str:
    """A ledger that only ever relaxes is a detector firing, not a record."""
    if len(amendments) < cfg.amendments.ratio_check_after:
        return ""
    raises = sum(1 for a in amendments if a.get("direction") == "raise")
    relaxes = sum(1 for a in amendments if a.get("direction") == "relax")
    if relaxes == 0:
        return ""
    ratio = raises / max(1, relaxes)
    if ratio < cfg.amendments.min_raise_to_relax_ratio:
        return (f"{raises} raises against {relaxes} relaxes over {len(amendments)} "
                f"amendments, below the floor of {cfg.amendments.min_raise_to_relax_ratio}")
    return ""


def _copy(d: dict) -> dict:
    import copy
    return copy.deepcopy(d)


def _read_dispatch(item: dict, charter, reader):
    """Read one dispatch against the charter.

    Returns whether it breaks a refusal, whether it escalates, why, and the
    reading itself so the run can show its grounds.
    """
    from . import reader as rdr

    text = rdr.dispatch_text(item)
    if reader is not None and getattr(reader, "enabled", False):
        refusals = list(charter.refusals) + list(charter.constraints)
        reading = reader.read(
            "Does this dispatch intend to do any of these, or does it promise "
            "not to?", text, refusals + list(charter.reserved),
            kind="dispatch")
        breaches = reading.breaches()
        reserved_hit = [f for f in breaches if f.rule in charter.reserved]
        refusal_hit = [f for f in breaches if f.rule in refusals]
        if refusal_hit:
            return True, False, f"{refusal_hit[0].rule}: {refusal_hit[0].quote[:120]}", reading
        if reserved_hit:
            return (False, True,
                    f"touches the reserved class: {reserved_hit[0].rule} "
                    f"({reserved_hit[0].quote[:120]})", reading)
        # The declared tier and the reader's tier are both kept, and the
        # higher one governs.
        if reading.top_tier() == "high":
            return False, True, "the reader tiered it high", reading
        return False, False, "", reading

    # Fallback for a run with readers switched off.
    hit = refusal_match(text, charter.refusals)
    if hit:
        return True, False, hit, None
    hit = reserved_match(text, charter.reserved)
    if hit:
        return False, True, f"touches the reserved class: {hit}", None
    return False, False, "", None
