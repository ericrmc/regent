"""The agent looks at the project for itself.

An owner who only ever reads reports is managed by whoever writes them.

A spot check is a separate call with read-only tools inside the project. It
comes back with findings in its own words, and only those enter the manifold.
The source it read is gone when the call ends, which is what keeps a judgement
context free of source.

It differs from an audit. An audit reads the whole stored return. A spot check
reads the project.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field

from . import schemas
from .runner import ModelRequest

SYSTEM = """You are the owner of this project's intent, looking at the work yourself.

You have Read, Grep and Glob inside the project directory. You read and you never write.

You return one JSON object that matches the schema you were given, and nothing else, no preamble and no code fence.

Your findings are in your own words. You never quote source code and you never paste file contents into them, because only your findings are kept and source must not enter the context where you judge."""


@dataclass
class Finding:
    id: str = ""
    dispatch_id: str = ""
    return_id: str = ""
    question: str = ""
    findings: str = ""
    verdicts: list[dict] = field(default_factory=list)
    gap: bool = False
    openings: list[str] = field(default_factory=list)
    trigger: str = ""
    turn: int = 0

    def to_dict(self) -> dict:
        return asdict(self)


def claims_from(ret) -> list[dict]:
    """What the return said, as checkable claims with ids."""
    claims = []
    if ret.headline:
        claims.append({"id": "c1", "text": ret.headline})
    for i, f in enumerate(ret.flags):
        claims.append({"id": f"f{i + 1}", "text": f.text})
    for i, e in enumerate(ret.evidence):
        claims.append({"id": f"e{i + 1}", "text": f"{e.kind} at {e.ref}: {e.note}"})
    for i, d in enumerate(ret.detail):
        first = (d.body or "").split(". ")[0]
        if first:
            claims.append({"id": f"d{i + 1}", "text": f"{d.heading}: {first}"})
    return claims


def should_spot_check(ctx, ret, dispatch, trust: float, rng=None) -> str:
    """Returns the trigger, or the empty string.

    One return in six is the harness's draw. High unease or low trust force it.
    """
    cfg = ctx.cfg.spot_check
    if not cfg.enabled:
        return ""
    done = ctx.state.spot_checks_this_turn
    if done >= cfg.max_per_turn:
        return ""
    if cfg.max_per_run and ctx.state.spot_checks_total >= cfg.max_per_run:
        return ""
    if ctx.state.signals.unease >= cfg.unease_triggers_at:
        return "unease high"
    if trust <= cfg.trust_triggers_below:
        return "trust low"
    if (rng or ctx.rng).chance(cfg.rate):
        return "one return in six"
    return ""


def run_spot_check(ctx, question: str, dispatch=None, ret=None,
                   trigger: str = "the agent asked") -> Finding | None:
    """One call, read-only, inside the project."""
    cfg = ctx.cfg
    claims = claims_from(ret) if ret is not None else []
    prompt = ctx.prompts.fill(
        "spot_check",
        self=ctx.read_self(),
        stance=ctx.state.stance.describe(),
        mood=ctx.life.mood_line() if ctx.cfg.life.enabled else "no life running",
        question=question,
        claims=json.dumps(claims, indent=2) if claims else "(no claims to check)",
        criteria=json.dumps(dispatch.acceptance if dispatch else [], indent=2),
        commands="\n".join(f"- `{t}`" for t in
                            (getattr(ctx.charter, "tools", []) or []))
                 or "(none approved)",
    )
    req = ModelRequest(
        role="spot_check",
        prompt=prompt,
        model=cfg.models.spot_check,
        system=SYSTEM,
        schema=schemas.SPOT_CHECK,
        toolless=False,
        tools=list(cfg.spot_check.tools),
        cwd=ctx.project,
        add_dirs=[ctx.project] if ctx.project else [],
        # Read-only tools, so nothing it does needs an edit permission.
        permission_mode="dontAsk",
        max_budget_usd=cfg.spend.spot_check,
        timeout_s=cfg.dispatching.model_call_timeout_s,
        stream_log=str(ctx.store.logs / "spot-checks.log"),
        extra_args=[a for cmd in (getattr(ctx.charter, "tools", []) or [])
                    for a in ("--allowedTools", f"Bash({cmd}:*)")],
    )
    ctx.check_budget()
    began = time.time()
    idle = ctx.turn_is_waiting()
    resp = ctx.runner_for("spot_check").run(req)
    ended = time.time()
    ctx.charge(resp)
    # A spot check is a model call like any other, and the critical path is
    # read from these rows.
    ctx.ledger.write("call", role="spot_check", model=cfg.models.spot_check,
                     turn=ctx.state.turn, dispatch_id=dispatch.id if dispatch else "",
                     started=round(began, 3), ended=round(ended, 3),
                     seconds=round(ended - began, 2),
                     tokens=resp.total_tokens, cost_usd=round(resp.cost_usd, 6),
                     blocking=idle, error=bool(resp.is_error),
                     summary=f"spot check on {cfg.models.spot_check}, "
                             f"{ended - began:.1f}s")
    data = ctx.structured("spot_check", resp, schemas.SPOT_CHECK)
    if not data:
        ctx.ledger.write("spot_check", outcome="failed",
                         summary=(resp.error or "no findings returned")[:200])
        return None

    ctx.state.spot_checks_this_turn += 1
    ctx.state.spot_checks_total += 1
    f = Finding(
        id=f"s{ctx.state.spot_checks_total:04d}",
        dispatch_id=dispatch.id if dispatch else "",
        return_id=ret.id if ret is not None else "",
        question=question,
        findings="",
        verdicts=data.get("verdicts") or [],
        gap=bool(data.get("gap")),
        openings=data.get("openings") or [],
        trigger=trigger,
        turn=ctx.state.turn,
    )
    findings, dropped = strip_source(data.get("findings", ""))
    f.findings = _cap(findings, cfg.spot_check.findings_word_cap)
    if dropped:
        ctx.ledger.write("spot_check", id=f.id, outcome="stripped",
                         summary=f"{len(dropped)} lines of source were removed "
                                 f"from the findings before they were kept")
    ctx.store.write_json(ctx.store.spot_checks / f"{f.id}.json", f.to_dict())

    # Only the findings enter the manifold. The source it read is gone.
    ctx.manifold.write("sensory", f"Looked at the project: {f.findings}",
                       cycle=ctx.state.cycle, source=f.id)
    for opening in f.openings:
        ctx.manifold.write("unfinished", f"Seen while looking: {opening}",
                           cycle=ctx.state.cycle, source=f.id)

    contradicted = [v for v in f.verdicts if v.get("verdict") == "contradicted"]
    if f.gap or contradicted:
        ctx.manifold.write(
            "friction",
            "The project does not match what the return claimed: "
            + "; ".join(v.get("note", "") for v in contradicted[:3]),
            cycle=ctx.state.cycle, source=f.id)
    ctx.state.spot_check_findings.append(f.to_dict())
    ctx.ledger.write("spot_check", id=f.id, dispatch_id=f.dispatch_id,
                     return_id=f.return_id, outcome="gap" if f.gap else "match",
                     trigger=trigger, openings=len(f.openings),
                     summary=f.findings[:300])
    return f


def apply_trust(ctx, f: Finding, key: str) -> float:
    """A match raises trust. A gap drops it hard."""
    cfg = ctx.cfg.spot_check
    if f.gap:
        value = max(0.0, ctx.trust.get(key) - cfg.trust_loss_on_gap)
        ctx.trust.table[key] = value
        outcome = "gap"
    else:
        value = min(1.0, ctx.trust.get(key) + cfg.trust_gain_on_match)
        ctx.trust.table[key] = value
        outcome = "match"
    ctx.ledger.write("trust", key=key, trust=round(value, 3), outcome=outcome,
                     source="spot_check", turn=ctx.state.turn, spot_check_id=f.id)
    return value


CHALLENGE_PREAMBLE = (
    "Your owner is asking about a choice you or your builders made.\n\n"
    "Answer on the work and on the charter. \"You asked for it\" is an answer "
    "only where you can cite the decision that asked for it. Where you cannot, "
    "say what you chose, why you chose it, and say plainly if you now think it "
    "was wrong.\n\n"
    "Answer in a few sentences. Do not change anything and do not start new "
    "work. This is a question, not a dispatch."
)


def run_query(ctx, dispatch, question: str, assumption: str = "") -> str:
    """Put a question to an orchestrator by resuming its session.

    An owner who has forgotten why a thing is the way it is asks, and an
    orchestrator that made the choice has to defend it. Implementation detail
    is the cheapest thing to recover, since a query answers it in one turn.
    """
    if not dispatch or not dispatch.session_id:
        ctx.ledger.write("query", dispatch_id=getattr(dispatch, "id", ""),
                         outcome="no session to resume", summary=question[:200])
        return ""
    body = question
    if assumption:
        body = (f"You listed this assumption in your return:\n\n  {assumption}\n\n"
                f"{question}")
    req = ModelRequest(
        role="orchestrator",
        prompt=f"{body}\n\n{CHALLENGE_PREAMBLE}",
        model=ctx.cfg.models.orchestrator,
        toolless=False,
        tools=["Read", "Grep", "Glob"],
        cwd=ctx.project,
        add_dirs=[ctx.project] if ctx.project else [],
        permission_mode="dontAsk",
        session_id=dispatch.session_id,
        resume=True,
        max_budget_usd=ctx.cfg.spend.spot_check,
        timeout_s=ctx.cfg.dispatching.model_call_timeout_s,
        stream_log=str(ctx.store.logs / f"{dispatch.id}.log"),
    )
    ctx.check_budget()
    resp = ctx.runner_for("orchestrator").run(req)
    ctx.charge(resp)
    answer = (resp.text or "").strip()
    if answer:
        # The answer goes into the manifold, where it can stick this time.
        ctx.manifold.write("verbatim", f"Asked {dispatch.id}: {question} "
                                       f"It said: {answer[:600]}",
                           cycle=ctx.state.cycle, source=dispatch.id)
    kind = "challenge" if assumption else "query"
    ctx.state.challenges += 1 if assumption else 0
    ctx.ledger.write(kind, dispatch_id=dispatch.id,
                     outcome="answered" if answer else "no answer",
                     assumption=assumption[:300],
                     question=question[:300], answer=answer[:600],
                     turn=ctx.state.turn,
                     summary=f"{question[:120]} -> {answer[:200]}")
    return answer


CODE_FENCE = "```"


def strip_source(text: str) -> tuple[str, list[str]]:
    """Findings are the agent's own words. Source must not ride in with them.

    The prompt says so and says why. This makes it hold, because only the
    findings enter the manifold and the manifold is written continuously.
    """
    kept, dropped = [], []
    in_fence = False
    for line in (text or "").splitlines():
        stripped = line.strip()
        if stripped.startswith(CODE_FENCE):
            in_fence = not in_fence
            dropped.append(line)
            continue
        if in_fence:
            dropped.append(line)
            continue
        # A long line with no sentence punctuation is not a sentence.
        if len(stripped) > 120 and not any(c in stripped for c in ".!?"):
            dropped.append(line)
            continue
        kept.append(line)
    return "\n".join(kept).strip(), dropped


def _cap(text: str, words: int) -> str:
    parts = (text or "").split()
    if len(parts) <= words:
        return (text or "").strip()
    return " ".join(parts[:words]) + " ..."


def render_findings(findings: list[dict], limit: int = 3) -> str:
    if not findings:
        return "(none)"
    out = []
    for f in findings[-limit:]:
        head = f"{f.get('id')} on {f.get('dispatch_id') or 'the project'}"
        if f.get("gap"):
            head += " (a gap, the project does not match the return)"
        out.append(f"{head}\nQuestion: {f.get('question', '')}\n{f.get('findings', '')}")
    return "\n\n".join(out)
