"""The attention filter.

An instruction to skim does nothing, because a model reads every token it is
handed. The cut is therefore made here in code, between the return and the
agent, and the agent only ever receives the view its attention bought.

One thing is added to the mechanical cut: a small model passes through any line
that matches a warm motif or a live unease.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from .returns import Return, sentences

FULL = "full"
SKIM = "skim"
GLANCE = "glance"
WAVE = "wave-through"
MODES = (WAVE, GLANCE, SKIM, FULL)
_MODE_RANK = {WAVE: 0, GLANCE: 1, SKIM: 2, FULL: 3}

_NUMBER = re.compile(r"\d")


@dataclass
class Draw:
    mode: str
    score: float
    reasons: list[str] = field(default_factory=list)
    forced: str = ""
    audit_due: bool = False
    inputs: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"mode": self.mode, "score": round(self.score, 4),
                "reasons": self.reasons, "forced": self.forced,
                "audit_due": self.audit_due, "inputs": dict(self.inputs)}


def draw_mode(ret: Return, cfg, rng, *, trust: float, queue_depth: int,
              unease: float, stance: float, debt: int,
              sitting: str = "", sitting_share: float = 1.0,
              thorough: float = 0.0, trusting: float = 0.0) -> Draw:
    """Draw the mode for one return.

    A high-tier flag is full, always. A medium-tier flag is skim at least. Debt
    at the cap is full. Everything else is a score.
    """
    a = cfg.attention
    reasons = []
    noise = rng.uniform(-a.weight_noise, a.weight_noise)
    # Risk stance is the negative end of the scalar, so a risk-weighted stance
    # buys more attention.
    risk = max(0.0, -stance)
    score = (
        a.base_score
        + a.weight_queue_depth * max(0, queue_depth)
        + a.weight_trust * (trust - a.trust_start)
        + a.weight_unease * unease
        + a.weight_risk_stance * risk
        + a.weight_debt * debt
        # The day's time, and a disposition that reads more or takes more on
        # trust. A wave-through then has a cause a person would recognise.
        + a.weight_sitting * (sitting_share - 1.0)
        + a.weight_thorough * thorough
        - a.weight_trusting_disposition * trusting
        + noise
    )
    inputs = {"sitting": sitting, "sitting_share": round(sitting_share, 3),
              "thorough": round(thorough, 3), "trusting": round(trusting, 3),
              "queue_depth": queue_depth, "trust": round(trust, 4),
              "unease": round(unease, 4), "stance": round(stance, 4),
              "debt": debt, "noise": round(noise, 4),
              "top_tier": ret.top_tier(), "flags": len(ret.flags),
              "evidence": len(ret.evidence), "detail": len(ret.detail)}
    reasons.append(f"queue={queue_depth}")
    reasons.append(f"trust={trust:.2f}")
    reasons.append(f"unease={unease:.2f}")
    reasons.append(f"stance={stance:+.2f}")
    reasons.append(f"debt={debt}")

    if score >= a.band_full:
        mode = FULL
    elif score >= a.band_skim:
        mode = SKIM
    elif score >= a.band_glance:
        mode = GLANCE
    else:
        mode = WAVE

    forced = ""
    if ret.has_tier("high"):
        # A high-tier flag is full, always, whatever the day looked like.
        mode, forced = FULL, "high-tier flag"
    elif sitting == "none":
        # On a day with no time the builders carry on with their own
        # recommendation and the unread debt grows.
        mode, forced = WAVE, "the day left no time for the project"
    elif debt >= a.debt_cap:
        mode, forced = FULL, f"unread debt {debt}"
    elif trust < a.trust_floor_full_reads:
        mode, forced = FULL, f"trust {trust:.2f} below floor"
    elif ret.has_tier("medium") and _MODE_RANK[mode] < _MODE_RANK[SKIM]:
        mode, forced = SKIM, "medium-tier flag"

    audit_due = False
    if mode in (GLANCE, WAVE):
        # One in five glances and waves-through gets a full read later.
        audit_due = rng.chance(a.audit_rate)
    return Draw(mode=mode, score=score, reasons=reasons, forced=forced,
                audit_due=audit_due, inputs=inputs)


def cut(ret: Return, mode: str, cfg, *, salience=None, motifs=None, unease=0.0) -> str:
    """Render the view the agent receives. Nothing else reaches it."""
    if mode == WAVE:
        return _render(ret, ["headline_none", "recommendation"], mode)
    if mode == GLANCE:
        return _render(ret, ["headline", "recommendation", "flags"], mode)
    if mode == SKIM:
        return _skim(ret, cfg, salience=salience, motifs=motifs, unease=unease)
    return _full(ret)


def _header(ret: Return, mode: str) -> list[str]:
    return [f"RETURN {ret.id} from dispatch {ret.dispatch_id}",
            f"read mode: {mode}", ""]


def _render(ret: Return, parts: list[str], mode: str) -> str:
    out = _header(ret, mode)
    if "headline" in parts:
        out += ["HEADLINE", ret.headline, ""]
    if "recommendation" in parts:
        out += ["RECOMMENDATION", ret.recommendation, ""]
    if "flags" in parts:
        out += ["FLAGS"] + (_flag_lines(ret) or ["(none)"]) + [""]
    return "\n".join(out).strip() + "\n"


def _flag_lines(ret: Return) -> list[str]:
    return [f"- [{f.tier}] {f.text}" + (f" (criterion: {f.criterion})" if f.criterion else "")
            for f in ret.flags]


def _assumption_lines(ret: Return) -> list[str]:
    return [f"- {a.text}" + (f" (because {a.why})" if a.why else "")
            for a in ret.assumptions]


def _evidence_lines(ret: Return, with_note: bool) -> list[str]:
    out = []
    for e in ret.evidence:
        line = f"- {e.kind}: {e.ref}"
        if with_note and e.note:
            line += f" | {e.note}"
        out.append(line)
    return out


def _full(ret: Return) -> str:
    out = _header(ret, FULL)
    out += ["HEADLINE", ret.headline, ""]
    out += ["RECOMMENDATION", ret.recommendation, ""]
    out += ["FLAGS"] + (_flag_lines(ret) or ["(none)"]) + [""]
    out += ["EVIDENCE"] + (_evidence_lines(ret, True) or ["(none)"]) + [""]
    out += ["ASSUMPTIONS, WHICH NOBODY ASKED FOR"] + \
           (_assumption_lines(ret) or ["(none listed)"]) + [""]
    out += ["DETAIL"]
    for d in ret.detail:
        out += [f"## {d.heading}", d.body, ""]
    if not ret.detail:
        out += ["(none)", ""]
    return "\n".join(out).strip() + "\n"


def _skim(ret: Return, cfg, *, salience=None, motifs=None, unease=0.0) -> str:
    """Headline, recommendation, flags, the evidence list, the first sentence of
    each detail section, and every number.

    A model's summary is faithful. It finds the thing buried in paragraph six
    and carries it forward, which makes it a reader and not a skimmer. This cut
    misses what a person would miss.
    """
    a = cfg.attention
    out = _header(ret, SKIM)
    out += ["HEADLINE", ret.headline, ""]
    out += ["RECOMMENDATION", ret.recommendation, ""]
    out += ["FLAGS"] + (_flag_lines(ret) or ["(none)"]) + [""]
    out += ["EVIDENCE"] + (_evidence_lines(ret, False) or ["(none)"]) + [""]
    # Assumptions survive a skim. They are short and they are the thing an
    # owner picks at.
    out += ["ASSUMPTIONS, WHICH NOBODY ASKED FOR"] + \
           (_assumption_lines(ret) or ["(none listed)"]) + [""]
    out += ["DETAIL, SKIMMED"]

    carried: list[str] = []
    dropped: list[str] = []
    for d in ret.detail:
        parts = sentences(d.body)
        kept = parts[:a.skim_detail_sentences]
        rest = parts[a.skim_detail_sentences:]
        numbered = [s for s in rest if a.skim_keep_numbers and _NUMBER.search(s)]
        remainder = [s for s in rest if s not in numbered]
        out.append(f"## {d.heading}")
        for s in kept:
            out.append(s)
        for s in numbered:
            out.append(s)
        carried.extend(kept + numbered)
        dropped.extend(remainder)
        out.append("")

    passed = _salience_pass(dropped, salience=salience, motifs=motifs, unease=unease, cfg=cfg)
    if passed:
        out += ["CAUGHT BY A WORRIED EYE"] + [f"- {s}" for s in passed] + [""]
    out += [f"(the skim dropped {len(dropped) - len(passed)} sentences)"]
    return "\n".join(out).strip() + "\n"


def _salience_pass(dropped: list[str], *, salience, motifs, unease, cfg) -> list[str]:
    """A small model passes through any dropped line that matches a live motif
    or the current unease. With no model available, match on motif words.
    """
    if not dropped:
        return []
    motif_texts = [m for m in (motifs or []) if m]
    if not motif_texts and unease < 0.3:
        return []
    lines = dropped[: cfg.attention.salience_max_lines]
    if salience is None:
        return _keyword_match(lines, motif_texts)
    try:
        keep = salience(lines, motif_texts, unease)
    except Exception:
        return _keyword_match(lines, motif_texts)
    out = []
    for i in keep or []:
        if isinstance(i, int) and 0 <= i < len(lines):
            out.append(lines[i])
    return out


_WORD = re.compile(r"[a-z][a-z0-9_-]{3,}")
_STOP = {"that", "this", "with", "from", "have", "been", "were", "they", "their",
         "what", "when", "which", "there", "would", "could", "should", "about",
         "into", "than", "then", "some", "more", "most", "over", "only", "also"}


def _keyword_match(lines: list[str], motifs: list[str]) -> list[str]:
    words = set()
    for m in motifs:
        words |= {w for w in _WORD.findall(m.lower()) if w not in _STOP}
    if not words:
        return []
    out = []
    for line in lines:
        got = {w for w in _WORD.findall(line.lower()) if w not in _STOP}
        if got & words:
            out.append(line)
    return out


def ledger_phrase(mode: str) -> str:
    return {FULL: "judged", SKIM: "judged on a skim", GLANCE: "judged on a glance",
            WAVE: "accepted on recommendation, unread"}.get(mode, mode)


class Trust:
    """Trust is a scalar per orchestrator configuration, since the process is
    new each task. Audits earn it.
    """

    def __init__(self, cfg, table: dict | None = None) -> None:
        self.cfg = cfg
        self.table = dict(table or {})

    def get(self, key: str) -> float:
        return float(self.table.get(key, self.cfg.attention.trust_start))

    def agreed(self, key: str) -> float:
        v = min(1.0, self.get(key) + self.cfg.attention.trust_gain)
        self.table[key] = v
        return v

    def missed(self, key: str, severity: str) -> float:
        loss = (self.cfg.attention.trust_loss_buried if severity == "buried"
                else self.cfg.attention.trust_loss_minor)
        v = max(0.0, self.get(key) - loss)
        self.table[key] = v
        return v

    def to_dict(self) -> dict:
        return dict(self.table)


def salience_caller(runner, cfg, prompts, spend_hook=None, cwd=None):
    """Bind the small model into a callable the filter can use."""

    def call(lines: list[str], motifs: list[str], unease: float) -> list[int]:
        from .runner import ModelRequest
        numbered = "\n".join(f"{i}. {line}" for i, line in enumerate(lines))
        prompt = prompts.fill("salience", motifs=json.dumps(motifs, indent=2),
                              unease=f"{unease:.2f}", lines=numbered)
        schema = {"type": "object",
                  "properties": {"keep": {"type": "array", "items": {"type": "integer"}}},
                  "required": ["keep"], "additionalProperties": False}
        resp = runner.run(ModelRequest(
            role="salience", prompt=prompt, model=cfg.models.salience,
            schema=schema, toolless=True,
            max_budget_usd=cfg.spend.salience,
            system="You return one JSON object and nothing else.",
            cwd=cwd,
            timeout_s=cfg.dispatching.model_call_timeout_s))
        if spend_hook:
            spend_hook(resp)
        if resp.is_error or not resp.structured:
            return []
        return [int(i) for i in resp.structured.get("keep", []) if isinstance(i, (int, float))]

    return call
