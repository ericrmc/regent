"""The process view: how the work is going, as opposed to how the project is.

Built in code from the ledger and the metrics, so the numbers are counted and
not recalled. Nothing here reads the project and nothing here is a model's
recollection of its own run.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ProcessView:
    since_turn: int = 0
    turn: int = 0
    flow: dict = field(default_factory=dict)
    reading: dict = field(default_factory=dict)
    trust: dict = field(default_factory=dict)
    asking: dict = field(default_factory=dict)
    mood: dict = field(default_factory=dict)
    invention: dict = field(default_factory=dict)
    pace: dict = field(default_factory=dict)
    faults: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "since_turn": self.since_turn, "turn": self.turn,
            "flow": self.flow, "reading": self.reading, "trust": self.trust,
            "asking": self.asking, "mood": self.mood,
            "invention": self.invention, "pace": self.pace,
            "faults": self.faults,
        }

    def metric(self, name: str) -> float | None:
        """One named number, for a way to be reviewed against."""
        for block in (self.flow, self.reading, self.asking, self.mood,
                      self.invention):
            if name in block:
                value = block[name]
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    return float(value)
        return None

    def metric_names(self) -> list[str]:
        out = []
        for block in (self.flow, self.reading, self.asking, self.mood,
                      self.invention):
            out += [k for k, v in block.items()
                    if isinstance(v, (int, float)) and not isinstance(v, bool)]
        return sorted(out)


def build(ctx, since_turn: int = 0) -> ProcessView:
    rows = [r for r in ctx.ledger.all() if int(r.get("turn", 0)) > since_turn]
    series = [m for m in ctx.store.read_jsonl(ctx.store.metrics)
              if int(m.get("turn", 0)) > since_turn]
    v = ProcessView(since_turn=since_turn, turn=ctx.state.turn)

    def of(kind: str) -> list[dict]:
        return [r for r in rows if r.get("kind") == kind]

    # Flow.
    judgements = of("judgement")
    accepts = [r for r in judgements if r.get("outcome") == "accept"]
    rejects = [r for r in judgements if r.get("outcome") == "reject"]
    redirects = [r for r in of("amendment") if r.get("direction") == "redirect"]
    turns = max(1, v.turn - since_turn)
    dispatches = of("dispatch")
    resumed = [r for r in dispatches if r.get("resumed")]
    per_branch: dict[str, int] = {}
    for r in dispatches:
        key = r.get("objective_id") or r.get("dispatch_id") or "?"
        per_branch[key] = per_branch.get(key, 0) + 1
    v.flow = {
        "turns": turns,
        "dispatches": len(dispatches),
        "accepts": len(accepts),
        "rejects": len(rejects),
        "turns_per_accept": round(turns / len(accepts), 2) if accepts else None,
        "rework_dispatches": len(resumed),
        "reversals": len(redirects),
        "kills": len(of("kill")),
        "dispatches_per_branch": per_branch,
        "most_redone": max(per_branch, key=per_branch.get) if per_branch else "",
    }

    # Reading.
    modes = of("read_mode")
    mix: dict[str, int] = {}
    for r in modes:
        mix[r.get("read_mode", "?")] = mix.get(r.get("read_mode", "?"), 0) + 1
    unread = mix.get("glance", 0) + mix.get("wave-through", 0)
    audits = of("audit")
    spots = of("spot_check")
    gaps = [r for r in spots if r.get("outcome") == "gap"]
    buried = [r for r in audits if r.get("outcome") == "buried"]
    v.reading = {
        "returns_read": len(modes),
        "mode_mix": mix,
        "unread_share": round(unread / len(modes), 2) if modes else None,
        "forced_full": len([r for r in modes if r.get("forced")]),
        "max_debt": max((max((m.get("debt") or {}).values(), default=0)
                         for m in series), default=0),
        "audits": len(audits),
        "audits_finding_something": len([r for r in audits
                                         if r.get("outcome") != "agreed"]),
        "buried_defects": len(buried),
        "spot_checks": len(spots),
        "spot_check_gaps": len(gaps),
    }

    # Trust.
    paths: dict[str, list] = {}
    for r in of("trust"):
        paths.setdefault(r.get("key", "?"), []).append(
            {"turn": r.get("turn"), "trust": r.get("trust"),
             "outcome": r.get("outcome"), "source": r.get("source")})
    v.trust = {"paths": paths,
               "now": dict(ctx.trust.table),
               "lowest": min(ctx.trust.table.values(), default=None)}

    # Asking.
    challenges = of("challenge")
    queries = of("query")
    listed = sum(len(r.get("assumptions") or []) for r in of("return_assumptions"))
    amendments = of("amendment")
    v.asking = {
        "queries": len(queries),
        "challenges": len(challenges),
        "assumptions_listed": listed,
        "challenge_share": round(len(challenges) / listed, 2) if listed else None,
        "answered": len([r for r in challenges + queries
                         if r.get("outcome") == "answered"]),
        "amendments_after_asking": len([
            a for a in amendments
            if any(int(c.get("turn", 0)) == int(a.get("turn", 0))
                   for c in challenges)]),
        "inspections": len([r for r in spots if r.get("trigger") == "the agent asked"]),
    }

    # Mood.
    stance_path = [{"turn": m.get("turn"), "stance": m.get("stance"),
                    "baseline": m.get("stance_baseline")} for m in series]
    frustration = [(m.get("turn"), (m.get("signals") or {}).get("frustration", 0))
                   for m in series]
    rungs = [int(r.get("rung", 0)) for r in of("signal") if r.get("rung")]
    v.mood = {
        "stance_path": stance_path,
        "stance_now": ctx.state.stance.value,
        "stance_range": [min((p["stance"] for p in stance_path), default=None),
                         max((p["stance"] for p in stance_path), default=None)],
        "frustration_peak": max((f for _, f in frustration), default=0),
        "frustration_peak_turn": max(frustration, key=lambda x: x[1])[0]
        if frustration else None,
        "highest_rung": max(rungs, default=0),
        "rungs_reached": sorted(set(rungs)),
    }

    # Invention.
    reqs = ctx.requirements.since_turn(since_turn)
    origins: dict[str, int] = {}
    for r in reqs:
        src = (r.get("origin") or {}).get("source", "unknown")
        origins[src] = origins.get(src, 0) + 1
    v.invention = {
        "requirements": len(reqs),
        "appetite_used": round(ctx.requirements.appetite_used(), 3),
        "appetite_left": round(ctx.appetite_left(), 3),
        "origins": origins,
        "candidates_gated_out": len(of("gate")),
        "cycles": len(set(r.get("cycle") for r in of("cycle") if r.get("cycle"))),
    }

    v.pace = pace(rows)
    v.faults = detectors(ctx)
    return v


def pace(rows: list[dict]) -> dict:
    """Where the wall time went, from the per-call rows.

    A turn where the regent's blocking time exceeds the builders' is a fault.
    """
    calls = [r for r in rows if r.get("kind") == "call"
             and r.get("started") is not None and r.get("ended") is not None]
    if not calls:
        return {}
    builders = [c for c in calls if c.get("role") == "orchestrator"]
    regent = [c for c in calls if c.get("role") != "orchestrator"]
    blocking = [c for c in regent if c.get("blocking")]

    def secs(rows_):
        return round(sum(float(r.get("seconds", 0)) for r in rows_), 1)

    def spend(rows_):
        return round(sum(float(r.get("cost_usd", 0)) for r in rows_), 4)

    # Wall time is the span the calls covered, not their sum, since the
    # builders and the regent overlap.
    start = min(float(c["started"]) for c in calls)
    end = max(float(c["ended"]) for c in calls)
    wall = round(end - start, 1)
    builder_wall = _covered(builders)
    slowest = max(blocking, key=lambda c: float(c.get("seconds", 0)),
                  default=None)
    by_role: dict[str, dict] = {}
    for c in calls:
        row = by_role.setdefault(c.get("role", "?"),
                                 {"calls": 0, "seconds": 0.0, "cost": 0.0,
                                  "blocking_seconds": 0.0})
        row["calls"] += 1
        row["seconds"] = round(row["seconds"] + float(c.get("seconds", 0)), 1)
        row["cost"] = round(row["cost"] + float(c.get("cost_usd", 0)), 4)
        if c.get("blocking") and c.get("role") != "orchestrator":
            row["blocking_seconds"] = round(
                row["blocking_seconds"] + float(c.get("seconds", 0)), 1)
    return {
        "wall_seconds": wall,
        "builder_wall_seconds": builder_wall,
        "builder_wall_share": round(builder_wall / wall, 3) if wall else None,
        "regent_blocking_seconds": secs(blocking),
        "regent_blocking_share": round(secs(blocking) / wall, 3) if wall else None,
        "builder_spend": spend(builders),
        "regent_spend": spend(regent),
        "builder_spend_share": round(
            spend(builders) / (spend(builders) + spend(regent)), 3)
        if (spend(builders) + spend(regent)) else None,
        "slowest_blocker": {
            "role": slowest.get("role"), "model": slowest.get("model"),
            "seconds": slowest.get("seconds"), "turn": slowest.get("turn"),
        } if slowest else None,
        "by_role": by_role,
        "fault": secs(blocking) > builder_wall,
    }


def _covered(calls: list[dict]) -> float:
    """Seconds covered by these calls, counting overlap once."""
    spans = sorted((float(c["started"]), float(c["ended"])) for c in calls
                   if c.get("started") and c.get("ended"))
    total, cur_s, cur_e = 0.0, None, None
    for s, e in spans:
        if cur_e is None or s > cur_e:
            if cur_e is not None:
                total += cur_e - cur_s
            cur_s, cur_e = s, e
        else:
            cur_e = max(cur_e, e)
    if cur_e is not None:
        total += cur_e - cur_s
    return round(total, 1)


def detectors(ctx) -> list[str]:
    from . import requirements as reqmod
    out = []
    for check in (reqmod.timid_owner(ctx.requirements, ctx.state.turn, ctx.cfg),
                  reqmod.trusting_owner(ctx.state, ctx.cfg),
                  reqmod.unchallenged_assumptions(ctx.ledger, ctx.state, ctx.cfg),
                  reqmod.churn(ctx.ledger, ctx.cfg,
                               reader=getattr(ctx, 'reader', None))):
        if check:
            out.append(check)
    return out


def render(v: ProcessView) -> str:
    """The view as the call reads it. Numbers, not prose about numbers."""
    import json

    parts = [f"Turns {v.since_turn + 1} to {v.turn}.", ""]
    for name, block in (("Pace", v.pace), ("Flow", v.flow),
                        ("Reading", v.reading), ("Trust", v.trust),
                        ("Asking", v.asking), ("Mood", v.mood),
                        ("Invention", v.invention)):
        parts.append(f"## {name}")
        parts.append(json.dumps(block, indent=2, default=str))
        parts.append("")
    parts.append("## Faults that fired")
    parts += [f"- {f}" for f in v.faults] or ["- (none)"]
    return "\n".join(parts)
