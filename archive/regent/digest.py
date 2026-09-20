"""The digest, one page at the cadence the charter sets.

Decisions made, amendments with triggers, new objectives, what was killed, what
is next. Anything in it can be reversed, which costs a revert and never a wait.
It is assembled from the ledger in code. No model writes it, because a written
summary of a record is a second record that can disagree with the first.
"""

from __future__ import annotations

import time
from pathlib import Path


def build_digest(ctx, since_turn: int = 0) -> str:
    st = ctx.state
    # One page at a cadence. A digest that carries the whole run every period
    # grows without bound and stops being a page.
    records = [r for r in ctx.ledger.all() if int(r.get("turn", 0)) > since_turn]
    period = f"turns {since_turn + 1} to {st.turn}"
    out = [f"# Digest, {period}", ""]

    out += ["## Where the run stands", ""]
    out.append(f"- Turn {st.turn}, cycle {st.cycle}, {st.calls} model calls.")
    out.append(f"- Spend {st.cost_usd:.2f} USD of "
               f"{ctx.charter.budget.spend_usd:.2f}, {st.tokens} tokens.")
    out.append(f"- Stance {st.stance.describe()}. Signals: {st.signals.line()}.")
    if hasattr(ctx, "requirements"):
        out.append(f"- {len(ctx.requirements.rows)} requirements invented, "
                   f"{ctx.requirements.appetite_used():.0%} of the budget's appetite "
                   f"used against {getattr(ctx.charter, 'appetite', 0):.0%} available.")
    out.append(f"- {st.spot_checks_total} spot checks against {st.returns_read} "
               f"returns read, and {st.challenges} assumptions challenged.")
    if hasattr(ctx, "ways"):
        out.append(f"- {len(ctx.ways.live())} ways of working in force, "
                   f"{st.stepped_back} times stepped back.")
    if ctx.cfg.life.enabled:
        out.append(f"- The life runs to day {ctx.life.index().day_count}, "
                   f"{ctx.life.total_words()} words. Mood: {ctx.life.mood_line()}.")
    if st.stance.line:
        out.append(f"- The disposition this turn: {st.stance.line}")
    out.append(f"- Stop condition: {'; '.join(ctx.charter.stop) or 'none stated'}")
    out.append("")

    # The critical path. A turn where the regent's blocking time exceeds the
    # builders' is a fault.
    from . import process_view as pvmod
    pace = pvmod.pace(ctx.ledger.all())
    if pace:
        out += ["## Where the time went", ""]
        out.append(f"- Wall time {pace['wall_seconds'] / 60:.1f} min. The "
                   f"builders held {pace['builder_wall_seconds'] / 60:.1f} min "
                   f"of it, {(pace['builder_wall_share'] or 0):.0%}.")
        out.append(f"- The regent blocked them for "
                   f"{pace['regent_blocking_seconds'] / 60:.1f} min, "
                   f"{(pace['regent_blocking_share'] or 0):.0%}.")
        out.append(f"- Spend: builders {pace['builder_spend']:.2f} USD, regent "
                   f"{pace['regent_spend']:.2f}, builders "
                   f"{(pace['builder_spend_share'] or 0):.0%} of it.")
        if pace.get("slowest_blocker"):
            sb = pace["slowest_blocker"]
            out.append(f"- The slowest thing that held a builder up: "
                       f"{sb['role']} on {sb['model']}, {sb['seconds']}s, "
                       f"turn {sb['turn']}.")
        if pace.get("fault"):
            out.append("- **Fault: the regent blocked the builders for longer "
                       "than they worked.**")
        out.append("")
        out.append("| Role | Calls | Seconds | Blocking | Spend |")
        out.append("| --- | --- | --- | --- | --- |")
        for role, row in sorted(pace["by_role"].items(),
                                key=lambda kv: -kv[1]["seconds"]):
            out.append(f"| {role} | {row['calls']} | {row['seconds']:.0f} | "
                       f"{row['blocking_seconds']:.0f} | "
                       f"{row['cost']:.2f} |")
        out.append("")

    out += ["## Objectives", ""]
    for o in st.objectives:
        mark = "" if o.get("status") == "live" else " (dropped)"
        out.append(f"- **{o['id']}**{mark} weight {float(o.get('weight', 0)):.2f}, "
                   f"{o.get('criteria_met', 0)} of {o.get('criteria_total', 0)} criteria met. "
                   f"{o.get('text', '')}")
        if o.get("charter_line"):
            out.append(f"  - serves: {o['charter_line']}")
    out.append("")

    out += _section(records, "decision", "Decisions made",
                    lambda r: f"turn {r.get('turn')}: {r.get('summary', '')} "
                              f"({r.get('dispatched', 0)} dispatched, "
                              f"{r.get('judged', 0)} judged, "
                              f"{r.get('rejected', 0)} rejected by the harness)")
    out += _section(records, "amendment", "Amendments, with triggers",
                    lambda r: f"{r.get('dispatch_id', '')} [{r.get('direction', '')}] "
                              f"{r.get('summary', '')} (triggered by: {r.get('trigger', '')})")
    out += _section(records, "objective", "New and changed objectives",
                    lambda r: f"{r.get('objective_id', '')} [{r.get('action', '')}] "
                              f"{r.get('summary', '')}")
    # Requirements invented, each with its origin and its rework, so the human
    # can see where the project turned and why.
    invented = ctx.requirements.since_turn(since_turn) if hasattr(ctx, "requirements") else []
    if invented:
        out += ["## Requirements invented", ""]
        for r in invented:
            out.append(f"- **{r['id']}** {r['text']}")
            out.append(f"  - serves the intent: {r.get('serves_intent', '')}")
            out.append(f"  - rework: {r.get('rework', '')}")
            origin = r.get("origin") or {}
            bits = [f"{k} {v}" for k, v in origin.items() if v and k != "links"]
            out.append(f"  - origin: {', '.join(bits) or 'not recorded'}")
            for link in (origin.get("links") or [])[:2]:
                out.append(f"    - from the link: {link}")
            out.append(f"  - appetite: {float(r.get('appetite_share', 0)):.0%}")
        out.append("")

    out += _section(records, "challenge", "Assumptions challenged",
                    lambda r: f"{r.get('dispatch_id', '')} on \"{r.get('assumption', '')[:110]}\" "
                              f"-> {r.get('answer', '')[:200]}")
    out += _section(records, "spot_check", "What it found when it looked itself",
                    lambda r: f"{r.get('id', '')} on {r.get('dispatch_id') or 'the project'} "
                              f"[{r.get('outcome', '')}, {r.get('trigger', '')}]: "
                              f"{r.get('summary', '')}")
    out += _section(records, "kill", "What was killed",
                    lambda r: f"{r.get('dispatch_id', '')}: {r.get('summary', '')}")
    out += _section(records, "escalation", "Escalations",
                    lambda r: f"{r.get('id', '')} [{r.get('tier', '')}] "
                              f"{r.get('question', '')} ({r.get('summary', '')})")
    out += _section(records, "audit", "Audits",
                    lambda r: f"{r.get('return_id', '')} {r.get('outcome', '')}, "
                              f"trust now {r.get('trust', '')}: {r.get('summary', '')}")
    out += _section(records, "rejected", "What the harness refused to apply",
                    lambda r: f"{r.get('bucket') or r.get('role', '')}: "
                              f"{r.get('reason', '')} {r.get('summary', '')[:160]}")
    out += _section(records, "candidate", "Candidates through the gate",
                    lambda r: f"{r.get('summary', '')} (killed by: "
                              f"{r.get('disconfirming', '')})")

    modes = {}
    for r in records:
        if r.get("kind") != "read_mode":
            continue
        modes[r.get("read_mode", "?")] = modes.get(r.get("read_mode", "?"), 0) + 1
    if modes:
        out += ["## How returns were read", ""]
        out += [f"- {k}: {v}" for k, v in sorted(modes.items())] + [""]

    # Detectors that only a period can show.
    faults = []
    if hasattr(ctx, "requirements"):
        from . import requirements as reqmod
        for check in (reqmod.timid_owner(ctx.requirements, st.turn, ctx.cfg),
                      reqmod.trusting_owner(st, ctx.cfg),
                      reqmod.unchallenged_assumptions(ctx.ledger, st, ctx.cfg),
                      reqmod.churn(ctx.ledger, ctx.cfg,
                                   reader=getattr(ctx, 'reader', None))):
            if check:
                faults.append(check)
    if faults:
        out += ["## Detectors firing", ""] + [f"- {f}" for f in faults] + [""]

    # The process notes from stepping back, so the human reads how the run is
    # going next to what it decided.
    stepped = [r for r in records if r.get("kind") == "stepping_back"]
    if stepped:
        out += ["## How the run is going", ""]
        for r in stepped:
            out.append(f"- turn {r.get('turn')} [{r.get('trigger', '')}]: "
                       f"{r.get('summary', '')}")
        out.append("")
    ways = [r for r in records if r.get("kind") == "way"]
    if ways:
        out += ["## Ways that changed, and why", ""]
        for r in ways:
            out.append(f"- **{r.get('id')}** {r.get('state')}: "
                       f"{r.get('summary', '')}")
            if r.get("pattern"):
                out.append(f"  - prompted by: {r['pattern']}")
            if r.get("outcome"):
                out.append(f"  - {r['outcome']}")
        out.append("")
    notes = [n for n in st.process_notes if int(n.get("turn", 0)) > since_turn]
    if notes:
        out += ["## What it thinks the charter has wrong", "",
                "These are not applied. They are yours.", ""]
        for n in notes:
            out.append(f"- {n.get('text', '')}")
            out.append(f"  - why: {n.get('why', '')}")
        out.append("")
    refused = [r for r in records
               if r.get("kind") == "rejected" and r.get("bucket") == "ways"]
    if refused:
        out += ["## Ways the harness refused", ""]
        out += [f"- {r.get('reason', '')}: {r.get('summary', '')}" for r in refused]
        out.append("")

    out += ["## What is next", ""]
    live = [d for d in st.open_dispatches()]
    if live:
        for d in live:
            out.append(f"- {d.id} [{d.tier}] {d.title}")
    else:
        out.append("- No dispatches in flight.")
    waiting = st.open_escalations()
    if waiting:
        out += ["", "## Waiting on you", ""]
        for e in waiting:
            out.append(f"- `regent answer {e.id} \"...\"` : {e.question}")
            out.append(f"  - why: {e.why}")
    out.append("")
    out.append(f"Seed {st.seed}, {st.draws} draws. The run replays from these.")
    return "\n".join(out) + "\n"


def _section(records: list[dict], kind: str, title: str, render) -> list[str]:
    rows = [r for r in records if r.get("kind") == kind]
    if not rows:
        return []
    return [f"## {title}", ""] + [f"- {render(r)}" for r in rows] + [""]


def human_only(ctx) -> str:
    """Appended by the harness after every model call has finished.

    Nothing in it has been in a model's context and nothing in it ever will be.
    """
    from . import influence as infl

    if not ctx.cfg.influence.enabled:
        return ""
    rows = infl.settle(ctx.influence.all(), ctx.state.turn,
                       ctx.cfg.influence.fade_after_turns)
    if not rows:
        return ""
    out = [infl.render_for_human(rows)]
    puppet = infl.puppet_share(rows, len(ctx.requirements.rows))
    if puppet:
        out += ["### A caution, for you only", "", puppet, ""]
    return "\n".join(out)


def write_digest(ctx, since_turn: int | None = None) -> Path:
    since = ctx.state.last_digest_turn if since_turn is None else since_turn
    text = build_digest(ctx, since) + "\n" + human_only(ctx)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    path = ctx.store.digests / f"digest-{ctx.state.turn:04d}-{stamp}.md"
    path.write_text(text)
    return path
