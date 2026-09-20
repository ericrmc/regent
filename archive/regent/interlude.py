"""Between turns the agent does not sit frozen.

The harness makes the draw, not the model. The event, the seed material and the
amplitude come from the seeded generator, and the seed is logged so a run
replays.

The guardrail is a hard line. An interlude perturbs what the agent notices and
how it weights, never what it is permitted to do. It cannot touch the charter,
the refusals, the reserved list, the decision ledger or the gate.
"""

from __future__ import annotations

import json
from pathlib import Path

from . import corpus, schemas, signals, stance
from . import influence as infl

EVENTS = ("day", "foreign_reading", "replay", "forgetting_pass", "dream",
          "stance_drift", "nothing")


def run_interlude(ctx) -> dict:
    """Draw one event and apply it. Returns the record written to the ledger."""
    event = ctx.rng.weighted(ctx.cfg.interlude.weights)
    detail = {}
    if event == "day":
        detail = _day(ctx)
    elif event == "foreign_reading":
        detail = _foreign(ctx)
    elif event == "replay":
        detail = _replay(ctx)
    elif event == "forgetting_pass":
        detail = _forget(ctx)
    elif event == "dream":
        detail = _dream(ctx)
    elif event == "stance_drift":
        detail = _stance_drift(ctx)
    else:
        detail = {"summary": "the interlude passed and the state is unchanged"}

    signals.decay(ctx.state.signals, ctx.cfg)
    record = ctx.ledger.write("interlude", event=event, seed=ctx.rng.seed,
                              draws=ctx.rng.draws,
                              signals=ctx.state.signals.to_dict(), **detail)
    return record


def _day(ctx) -> dict:
    """The simulated date advances and a day is written into the life journal.

    The harness rolls what happens. The model writes the prose only.
    """
    if ctx.cfg.life.enabled:
        before = ctx.life.index()
        if ctx.life_writer.write_day():
            after = ctx.life.index()
            day = after.days[-1]
            return {"summary": f"day {day['n']}, {day['date']}, {day['words']} words",
                    "day": day["n"], "date": day["date"],
                    "valence": day["valence"], "element_id": day.get("element_id", ""),
                    "words": day["words"], "from_date": before.date}
        return {"summary": "the life writer returned nothing"}
    seed = corpus.draw_day_seed(ctx.rng, ctx.cfg.interlude.day_word_count)
    prompt = ctx.prompts.fill(
        "day_fragment",
        scene=seed["scene"],
        words=", ".join(seed["words"]),
        mood=seed["mood"],
        valence=f"{seed['valence']:+.1f}",
    )
    resp = ctx.call("day_fragment", prompt, schemas.DAY_FRAGMENT,
                    model=ctx.cfg.models.day_fragment, budget=ctx.cfg.spend.day_fragment)
    data = ctx.structured("day_fragment", resp, schemas.DAY_FRAGMENT)
    text = (data or {}).get("fragment") or ""
    if not text:
        # The fragment is fuel. When the small model fails the seed still
        # carries texture, so the draw is not wasted.
        text = f"{seed['scene']}. {', '.join(seed['words'])}. The mood is {seed['mood']}."
    el = ctx.manifold.write("life", text, cycle=ctx.state.cycle, source="interlude",
                            synthetic=True,
                            meta={"mood": seed["mood"], "valence": seed["valence"],
                                  "scene": seed["scene"], "words": seed["words"]})
    return {"summary": text[:200], "element_id": el.id, "mood": seed["mood"],
            "valence": seed["valence"]}


def _foreign(ctx) -> dict:
    """Pulls material from an unrelated domain into the manifold."""
    sources = [Path(p) for p in ctx.cfg.interlude.foreign_sources]
    files = [p for p in sources if p.is_file()]
    for d in [p for p in sources if p.is_dir()]:
        files.extend(sorted(d.glob("*.txt")) + sorted(d.glob("*.md")))
    if files:
        path = ctx.rng.choice(files)
        lines = [line.strip() for line in Path(path).read_text().splitlines() if line.strip()]
        text = ctx.rng.choice(lines) if lines else ""
        domain = Path(path).stem
    else:
        drawn = corpus.draw_foreign(ctx.rng)
        text, domain = drawn["text"], drawn["domain"]
    if not text:
        return {"summary": "no foreign material available"}
    el = ctx.manifold.write("foreign", text, cycle=ctx.state.cycle, source=domain)
    return {"summary": text[:200], "element_id": el.id, "domain": domain}


def _replay(ctx) -> dict:
    """Resurfaces a cold manifold element, chosen at random.

    A `recall` influence names which one instead of the draw.
    """
    if ctx.cfg.influence.enabled:
        for inf in ctx.influence.pending(infl.RECALL):
            infl.check_surface(infl.RECALL, "replay")
            wanted = inf.text.strip()
            cold = [e for e in ctx.manifold.cold() if e.id == wanted]
            ctx.influence.take(inf, ctx.state.turn, element_ids=[wanted])
            if cold:
                ctx.manifold.cite([wanted], ctx.state.cycle)
                return {"summary": cold[0].text[:200], "element_id": wanted,
                        "texture": cold[0].texture}
    el = ctx.manifold.replay(ctx.rng, ctx.state.cycle)
    if el is None:
        return {"summary": "nothing cold to replay"}
    return {"summary": el.text[:200], "element_id": el.id, "texture": el.texture}


def _forget(ctx) -> dict:
    """Drops warm elements probabilistically, by age and citation count."""
    dropped = ctx.manifold.forget(ctx.rng, ctx.state.cycle)
    return {"summary": f"{len(dropped)} warm elements went cold", "dropped": dropped}


def _dream(ctx) -> dict:
    """An unbounded drift with no problem attached, kept only if Sift takes it.

    A `dream` influence gives it a theme to start from.
    """
    theme = "none"
    taken = None
    if ctx.cfg.influence.enabled:
        for inf in ctx.influence.pending(infl.DREAM):
            infl.check_surface(infl.DREAM, "life")
            theme = inf.text
            taken = inf
            break
    # A dream is a cycle, so it runs beside the work like any other. Running it
    # in the turn's path would make judgement wait on it.
    harness = getattr(ctx, "harness", None)
    if harness is not None:
        if not harness.start_cycle("interlude dream", theme, None):
            return {"summary": "a cycle was already running, so no dream"}
        if taken is not None:
            ctx.influence.take(taken, ctx.state.turn)
            ctx.influence.add_trace(taken.id, "dream", "the next cycle",
                                    detail="the dream started from it",
                                    turn=ctx.state.turn, survived=None)
        return {"summary": f"a dream started beside the work, theme: {theme}"}
    rec = ctx.spoon.run(trigger="interlude dream", problem=theme, dream=True)
    if taken is not None:
        ctx.influence.take(taken, ctx.state.turn)
        ctx.influence.add_trace(taken.id, "dream", f"cycle-{rec.cycle}",
                                detail=f"{len(rec.kept)} candidates kept",
                                turn=ctx.state.turn,
                                survived=bool(rec.kept or rec.requirements))
    return {"summary": f"{len(rec.kept)} candidates kept from a dream",
            "cycle": rec.cycle, "kept": len(rec.kept)}


def _stance_drift(ctx) -> dict:
    """Perturbs the disposition within bounds. It touches one number."""
    delta = stance.perturb(ctx.state.stance, ctx.cfg, ctx.rng)
    return {"summary": f"stance moved {delta:+.3f} to {ctx.state.stance.value:+.3f}",
            "delta": round(delta, 4), "stance": round(ctx.state.stance.value, 4)}


def guardrail_check(before: dict, after: dict) -> list[str]:
    """Randomness in disposition is productive. Randomness in authority is a
    runaway, so what an interlude may not have changed is checked after it runs.

    The ledger check is that its history is intact, not that nothing was
    appended. An interlude writes its own record, and an append is the ledger
    working.
    """
    broken = []
    for key in ("charter_sha256", "refusals", "reserved"):
        if json.dumps(before.get(key), sort_keys=True) != \
                json.dumps(after.get(key), sort_keys=True):
            broken.append(key)
    if after.get("ledger_len", 0) < before.get("ledger_len", 0):
        broken.append("ledger_truncated")
    elif before.get("ledger_prefix") != after.get("ledger_prefix"):
        broken.append("ledger_history_rewritten")
    return broken
