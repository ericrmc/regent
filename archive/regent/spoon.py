"""The spoon cycle: saturate, drift, catch, sift, the gate, consolidate.

Catch is the falling spoon and it runs in code, because the stop rules have to
be reliable. Sift runs in a fresh context that never saw the drift happen, and
on a different runner where one is configured, because the cycle is worth
nothing if the filter is captured.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field

from . import manifold as mf
from . import requirements as reqs
from . import schemas

STOP_BUDGET = "budget"
STOP_MOTIF_LOCK = "motif lock"
STOP_GROUNDEDNESS = "groundedness floor"
STOP_EXHAUSTED = "pass ended"


@dataclass
class CaughtLink:
    kind: str
    text: str
    anchors: list[str]
    ingredients: list[dict]
    mechanism: str
    pass_index: int = 0
    model: str = ""
    # Anchors dropped because they are the life. Kept so an influence can be
    # traced to the link that drew on it. Sift never sees this.
    life_anchors: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class CycleRecord:
    cycle: int
    started: float = 0.0
    trigger: str = ""
    problem: str = ""
    motifs: list[dict] = field(default_factory=list)
    tensions: list[dict] = field(default_factory=list)
    questions: list[str] = field(default_factory=list)
    links: list[dict] = field(default_factory=list)
    stops: list[dict] = field(default_factory=list)
    scored: list[dict] = field(default_factory=list)
    candidates: list[dict] = field(default_factory=list)
    gated_out: list[dict] = field(default_factory=list)
    kept: list[dict] = field(default_factory=list)
    requirements: list[dict] = field(default_factory=list)
    origin: dict = field(default_factory=dict)
    cost_usd: float = 0.0
    died_at_groundedness: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


def estimate_tokens(text: str) -> int:
    """A word-count proxy. The stop rule needs a number the harness owns, and a
    real count is not available until the call returns.
    """
    return max(1, int(len(text) / 4))


def catch(links: list[dict], cfg, pass_index: int = 0, model: str = "",
          manifold_ids: set[str] | None = None) -> tuple[list[CaughtLink], dict]:
    """Three stop rules, whichever fires first.

    The groundedness floor is the one that matters. A link with no anchor is the
    model fluent about nothing, and past that point the pass costs more to
    evaluate than it returns.
    """
    d = cfg.drift
    kept: list[CaughtLink] = []
    seen_pairs: set[tuple] = set()
    repeat_run = 0
    unanchored_run = 0
    tokens = 0
    stop = {"rule": STOP_EXHAUSTED, "at": len(links), "pass": pass_index}

    for i, raw in enumerate(links):
        given = [a for a in (raw.get("anchors") or []) if a]
        anchors = given
        life_anchors: list = []
        if manifold_ids is not None:
            anchors = [a for a in given if a in manifold_ids]
            life_anchors = [a for a in given if a not in manifold_ids]
        text = str(raw.get("text") or "")
        tokens += estimate_tokens(text)

        if not anchors:
            unanchored_run += 1
            repeat_run = 0
            if unanchored_run >= d.groundedness_floor:
                stop = {"rule": STOP_GROUNDEDNESS, "at": i, "pass": pass_index}
                break
            continue
        unanchored_run = 0

        pair = tuple(sorted(anchors)[:2])
        if pair in seen_pairs:
            repeat_run += 1
            if repeat_run >= d.motif_lock_repeats:
                stop = {"rule": STOP_MOTIF_LOCK, "at": i, "pass": pass_index}
                break
            continue
        repeat_run = 0
        seen_pairs.add(pair)

        kept.append(CaughtLink(
            kind=str(raw.get("kind") or "seed"),
            text=text,
            anchors=anchors,
            ingredients=list(raw.get("ingredients") or []),
            mechanism=str(raw.get("mechanism") or ""),
            pass_index=pass_index,
            model=model,
            life_anchors=life_anchors,
        ))

        if len(kept) >= d.max_links or tokens >= d.max_tokens:
            stop = {"rule": STOP_BUDGET, "at": i + 1, "pass": pass_index,
                    "links": len(kept), "tokens": tokens}
            break
    return kept, stop


def gate(candidates: list[dict]) -> tuple[list[dict], list[dict]]:
    """No candidate becomes work until a disconfirming observation is named.

    A candidate with no such observation is poetry and gets filed, not built.
    This is the only defence against apophenia, and the cycle is not safe to run
    without it.
    """
    passed, filed = [], []
    for c in candidates:
        obs = str(c.get("disconfirming") or "").strip()
        if obs and len(obs) > 8:
            passed.append(c)
        else:
            filed.append({**c, "filed_reason": "no disconfirming observation named"})
    return passed, filed


class SpoonCycle:
    def __init__(self, ctx) -> None:
        self.ctx = ctx

    def run(self, trigger: str, problem: str = "none", dream: bool = False,
            origin: dict | None = None) -> CycleRecord:
        ctx = self.ctx
        ctx.state.cycle += 1
        rec = CycleRecord(cycle=ctx.state.cycle, started=time.time(),
                          trigger=trigger, problem=problem)
        rec.origin = dict(origin or {})
        ctx.ledger.write("cycle", state="start", cycle=rec.cycle, summary=trigger,
                         dream=dream)

        self._saturate(rec)
        self._drift_and_catch(rec, dream=dream)
        self._sift(rec)
        self._consolidate(rec)

        ctx.store.write_json(ctx.store.cycles / f"cycle-{rec.cycle:04d}.json", rec.to_dict())
        ctx.ledger.write("cycle", state="end", cycle=rec.cycle,
                         summary=f"{len(rec.links)} links caught, {len(rec.kept)} candidates through the gate",
                         cost_usd=round(rec.cost_usd, 4))
        return rec

    # Saturate extracts motifs, tensions and unresolved questions. It answers nothing.
    def _saturate(self, rec: CycleRecord) -> None:
        ctx = self.ctx
        warm = ctx.manifold.project()
        if not warm:
            return
        life = ctx.life.for_drift(ctx.cfg.models.saturate) if ctx.cfg.life.enabled else ""
        prompt = ctx.prompts.fill(
            "saturate",
            manifold_warm=mf.render(warm) + (f"\n\n# The life\n\n{life}" if life else ""),
            objectives=ctx.read_self(),
        )
        resp = ctx.call("saturate", prompt, schemas.SATURATE, model=ctx.cfg.models.saturate,
                        budget=ctx.cfg.spend.saturate)
        rec.cost_usd += resp.cost_usd
        data = ctx.structured("saturate", resp, schemas.SATURATE)
        if not data:
            return
        rec.motifs = data.get("motifs") or []
        rec.tensions = data.get("tensions") or []
        rec.questions = data.get("questions") or []
        cited = [i for m in rec.motifs + rec.tensions for i in (m.get("element_ids") or [])]
        ctx.manifold.cite(cited, ctx.state.cycle)
        ctx.state.motifs = [m.get("text", "") for m in rec.motifs][:12]

    def _drift_and_catch(self, rec: CycleRecord, dream: bool = False) -> None:
        ctx = self.ctx
        cfg = ctx.cfg
        ids = ctx.manifold.project_ids()
        target = ctx.drift_target()
        if dream:
            target = cfg.drift.target_links_max
        life = [e for e in ctx.manifold.warm() if e.texture in ("life", "foreign")]
        motifs = json.dumps(rec.motifs + rec.tensions, indent=2) if rec.motifs else "(none yet)"
        caught: list[CaughtLink] = []

        # Each pass gets a different random subset of the warm manifold, and the
        # passes run on mixed model sizes, because a smaller model makes jumps a
        # larger one would not.
        for i in range(cfg.drift.passes):
            model = cfg.models.drift[i % len(cfg.models.drift)]
            subset = ctx.manifold.subset(ctx.rng)
            if not subset:
                break
            prompt = ctx.prompts.fill(
                "drift",
                motifs=motifs,
                manifold_subset=mf.render(subset),
                life_fragments=mf.render(life) if life else "(none)",
                life=ctx.life.for_drift(model) if cfg.life.enabled else "(no life running)",
                problem=rec.problem or "none",
                target_links=str(target),
                stance=ctx.state.stance.describe(),
                stance_word=ctx.state.stance.describe(),
            )
            resp = ctx.call("drift", prompt, schemas.DRIFT, model=model,
                            budget=cfg.spend.drift)
            rec.cost_usd += resp.cost_usd
            data = ctx.structured("drift", resp, schemas.DRIFT)
            links = (data or {}).get("links") or []
            kept, stop = catch(links, cfg, pass_index=i, model=model, manifold_ids=ids)
            rec.stops.append(stop)
            caught.extend(kept)
            if stop["rule"] == STOP_GROUNDEDNESS:
                # The stance tilts on this whether or not the pass kept
                # anything before it ran out of anchors.
                rec.died_at_groundedness = True

        rec.links = [link.to_dict() for link in caught]
        # Catch writes the links to a holding file. Sift reads that file and
        # nothing else.
        path = ctx.store.holding / f"cycle-{rec.cycle:04d}.jsonl"
        ctx.store.rewrite_jsonl(path, rec.links)
        ctx.manifold.cite([a for link in caught for a in link.anchors], ctx.state.cycle)
        ctx.ledger.write("cycle", state="catch", cycle=rec.cycle,
                         summary=f"{len(caught)} links held, stops: "
                                 + ", ".join(s["rule"] for s in rec.stops))

    def _sift(self, rec: CycleRecord) -> None:
        """A fresh context that never saw the list being produced.

        The anonymous list carries no ids, no model names and no pass numbers,
        because an evaluator that watched itself generate a thing rates its own
        thing highly.
        """
        ctx = self.ctx
        if not rec.links:
            return
        listing = "\n".join(f"{i}. {link['text']}"
                            + (f"\n   mechanism: {link['mechanism']}"
                               if link.get("mechanism") else "")
                            for i, link in enumerate(rec.links))
        prompt = ctx.prompts.fill(
            "sift",
            holding_list=listing,
            weights=json.dumps(ctx.sift_weights(), indent=2),
            keep=str(ctx.cfg.sift.keep),
            places_for_requirements=str(ctx.cfg.sift.places_for_requirements),
            stance_word=ctx.state.stance.describe(),
            appetite=f"{ctx.appetite_left():.0%} of the budget remains",
            intent=ctx.charter.intent,
            constraints="\n".join(f"- {c}" for c in ctx.charter.constraints) or "(none)",
        )
        resp = ctx.call("sift", prompt, schemas.SIFT, model=ctx.cfg.models.sift,
                        budget=ctx.cfg.spend.sift)
        rec.cost_usd += resp.cost_usd
        data = ctx.structured("sift", resp, schemas.SIFT)
        if not data:
            return
        rec.scored = data.get("scored") or []
        rec.candidates = data.get("candidates") or []

        # Each survivor is a solution or a requirement, and the two pass
        # different gates.
        solutions = [c for c in rec.candidates if c.get("kind") != reqs.REQUIREMENT]
        passed, filed = gate(solutions)
        result = reqs.requirement_gate(rec.candidates, ctx.charter, ctx.cfg,
                                       ctx.appetite_left(), reader=ctx.reader)
        # Places held for requirements are not filled by solutions.
        held = min(ctx.cfg.sift.places_for_requirements, ctx.cfg.sift.keep - 1)
        room = ctx.cfg.sift.keep - max(0, held - len(result.passed))
        rec.kept = passed[:room]
        if len(passed) > room:
            ctx.ledger.write("gate", cycle=rec.cycle,
                             reason="a place held for a requirement nobody invented",
                             summary=f"{len(passed) - room} solutions dropped, "
                                     f"{len(result.passed)} requirements offered")
        rec.gated_out = filed + result.filed
        rec.requirements = result.passed[: ctx.cfg.requirements.max_per_cycle]

        origin = {**rec.origin, "cycle": rec.cycle, "trigger": rec.trigger,
                  "links": [link["text"][:120] for link in rec.links[:3]],
                  "life_day": ctx.life.index().day_count if ctx.cfg.life.enabled else 0}
        for c in rec.kept:
            ctx.ledger.write("candidate", cycle=rec.cycle, candidate_kind="solution",
                             summary=c.get("text", "")[:200],
                             disconfirming=c.get("disconfirming", ""))
        for c in filed + result.filed:
            ctx.ledger.write("gate", cycle=rec.cycle, summary=c.get("text", "")[:200],
                             reason=c.get("filed_reason",
                                          "filed, no disconfirming observation"))
        for item in result.escalated:
            # A reserved class is the one wait.
            ctx.harness_escalate(item)
        for note in result.notes:
            ctx.harness_note(note)
        if rec.requirements:
            ctx.apply_invented(rec.requirements, origin=origin, cycle=rec.cycle)

    def _consolidate(self, rec: CycleRecord) -> None:
        """Survivors to memory, rejections and their reasons to the taste record,
        then the manifold is pruned.
        """
        ctx = self.ctx
        record = {
            "cycle": rec.cycle,
            "trigger": rec.trigger,
            "problem": rec.problem,
            "questions": rec.questions,
            "stops": rec.stops,
            "candidates_kept": rec.kept,
            "candidates_filed": rec.gated_out,
            "scored": rec.scored[:20],
        }
        prompt = ctx.prompts.fill(
            "consolidate",
            cycle_record=json.dumps(record, indent=2),
            self=ctx.read_self(),
            taste=ctx.read_taste(),
            objectives=json.dumps(ctx.state.objectives, indent=2),
        )
        resp = ctx.call("consolidate", prompt, schemas.CONSOLIDATE,
                        model=ctx.cfg.models.consolidate, budget=ctx.cfg.spend.consolidate)
        rec.cost_usd += resp.cost_usd
        data = ctx.structured("consolidate", resp, schemas.CONSOLIDATE)
        if data:
            ctx.append_memory(data.get("memory") or [])
            ctx.append_taste(data.get("taste") or [])
            ctx.apply_objectives(data.get("objectives") or [], source="consolidate")
        cooled = ctx.manifold.decay(ctx.state.cycle)
        if cooled:
            ctx.ledger.write("cycle", state="prune", cycle=rec.cycle,
                             summary=f"{len(cooled)} elements went cold")
        # Kept, not replaced. A candidate that survived the gate is available
        # as work until he uses it or drops it.
        fresh = [{"text": c.get("text", ""), "kind": c.get("kind", "solution"),
                  "disconfirming": c.get("disconfirming", ""),
                  "cycle": rec.cycle}
                 for c in rec.kept if c.get("text")]
        have = {c.get("text") for c in ctx.state.candidates
                if isinstance(c, dict)}
        ctx.state.candidates = ([c for c in ctx.state.candidates
                                 if isinstance(c, dict)]
                                + [c for c in fresh if c["text"] not in have])[-12:]
        ctx.state.last_cycle = rec.cycle
        ctx.state.last_drift_accepted = bool(rec.kept)
        ctx.state.last_drift_died_grounded = rec.died_at_groundedness
