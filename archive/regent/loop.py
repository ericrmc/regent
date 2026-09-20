"""The harness loop.

The harness is plain code and not a model. It owns the state machine, every
random draw, the attention filter, the stop rules in Catch, context assembly,
the budget and every write to disk. Models are called for judgement and
generation only, each as one child process.
"""

from __future__ import annotations

import json
import re
import threading
import time
import uuid
from pathlib import Path

from . import attention, notify, schemas
from . import decision as dec
from . import influence as infl
from . import interlude as il
from . import manifold as mf
from . import process_view as pv
from . import reader as rdr
from . import requirements as req
from . import signals as sig
from . import spotcheck as sc
from . import stance as stn
from .charter import parse_charter
from .config import Config
from .dispatch import Dispatch, DispatchPool, orchestrator_key
from .ledger import Ledger, summarise
from .life import LifeStore, LifeWriter
from .prompts import SYSTEM_JSON, SYSTEM_OWNER, Prompts
from .returns import Return, parse_return
from .runner import ModelRequest, build_runners
from .spoon import SpoonCycle
from .state import Escalation, RunState
from .store import Store
from .ways import ADJUSTABLE, FLOORS, Ways

PACKAGE_ROOT = Path(__file__).resolve().parent.parent


class BudgetExhausted(Exception):
    pass


class Context:
    """Everything a state needs, in one object. Nothing reaches disk except
    through the store, and no model is called except through `call`.
    """

    def __init__(self, store: Store, cfg: Config, charter, state: RunState,
                 project: str = "", prompts_dir: str | Path | None = None,
                 plugin_dir: str | Path | None = None,
                 runners: dict | None = None, notifier=None) -> None:
        self.store = store
        self.cfg = cfg
        self.charter = charter
        self.state = state
        self.project = project or state.project
        self.ledger = Ledger(store)
        self.manifold = mf.ManifoldStore(store, cfg)
        self.prompts = Prompts(prompts_dir or PACKAGE_ROOT / "prompts")
        self.plugin_dir = Path(plugin_dir) if plugin_dir else PACKAGE_ROOT / "plugin"
        self.runners = runners if runners is not None else build_runners(cfg)
        self.notifier = notifier if notifier is not None else notify.build(cfg, store)
        self.rng = state.rng()
        self.trust = attention.Trust(cfg, state.trust)
        self.ladder = sig.Ladder(cfg, state.ladder)
        self.spoon = SpoonCycle(self)
        self.pool = DispatchPool(self)
        # One cycle runs at a time, beside the builders.
        self.cycle_thread = None
        self._charge_lock = threading.Lock()
        self.cycle_result = None
        self.life = LifeStore(store, cfg)
        self.life_writer = LifeWriter(self)
        self.requirements = req.Register(cfg, state.requirements)
        self.ways = Ways(cfg, state.ways)
        # The file no model call reads.
        self.influence = infl.InfluenceStore(store)
        self.reader = rdr.Reader(self)
        self.disposition = self._load_disposition()
        self.harness = None  # set by Harness, so a cycle can apply what it invents

    def _load_disposition(self):
        """Dials belong to the owner, not to the run."""
        from . import disposition as disp
        path = self.life.root / "disposition.json"
        if path.exists():
            d = disp.Disposition.from_dict(self.store.read_json(path))
            disp.apply(d, self.cfg)
            return d
        return disp.Disposition()

    # Model calls.
    def runner_for(self, role: str):
        name = self.cfg.runners.by_role.get(role, self.cfg.runners.default)
        if name not in self.runners:
            raise KeyError(f"no runner named {name} for role {role}")
        return self.runners[name]

    def call(self, role: str, prompt: str, schema: dict | None, model: str,
             budget: float = 0.0, system: str = "", runner_role: str = ""):
        """One model call. The budget is checked before and charged after."""
        self.check_budget()
        req = ModelRequest(
            role=role,
            prompt=prompt,
            model=model,
            schema=schema,
            system=system or (SYSTEM_OWNER if role in ("wake", "react") else SYSTEM_JSON),
            toolless=True,
            max_budget_usd=budget,
            timeout_s=self.cfg.dispatching.model_call_timeout_s,
            # Every child gets a working directory. `claude -p` otherwise
            # inherits the parent's, which is whatever the operator ran from.
            cwd=str(self.store.sandbox),
        )
        # Measure it or it did not happen. Every model call writes a row.
        began = time.time()
        idle = self.turn_is_waiting()
        resp = self.runner_for(runner_role or role).run(req)
        ended = time.time()
        self.charge(resp)
        self.ledger.write(
            "call", role=role, model=model, turn=self.state.turn,
            started=round(began, 3), ended=round(ended, 3),
            seconds=round(ended - began, 2),
            tokens=resp.total_tokens, cost_usd=round(resp.cost_usd, 6),
            # Whether the builders were idle while this ran. A turn where the
            # regent's blocking time exceeds the builders' is a fault.
            blocking=idle, error=bool(resp.is_error),
            summary=f"{role} on {model}, {ended - began:.1f}s")
        if resp.is_error:
            self.ledger.write("error", role=role, summary=resp.error[:300] or "call failed")
        return resp

    def elapsed(self) -> float:
        """Seconds spent running, not seconds since the first start.

        A run stopped overnight and resumed the next morning has spent no wall
        time in between, and counting it kills the resumed run on its first
        budget check.
        """
        running = time.time() - self.state.started if self.state.started else 0.0
        return self.state.elapsed_s + max(0.0, running)

    def turn_is_waiting(self) -> bool:
        """Whether the turn is held up by the call about to be made.

        A call on the cycle's thread or the denials thread holds nothing up,
        however empty the pool is, and counting it as blocking made the fourth
        run's critical path read worse than it was.
        """
        if threading.current_thread() is not threading.main_thread():
            return False
        return not self.pool.in_flight

    def charge(self, resp) -> None:
        # Readers run several at a time, so the counters take a lock.
        with self._charge_lock:
            self._charge(resp)

    def _charge(self, resp) -> None:
        self.state.cost_usd += resp.cost_usd
        self.state.tokens += resp.total_tokens
        self.state.calls += 1
        # The journal is append-only, so the life is a stable prefix. This is
        # how much of it the prompt cache actually carried.
        self.state.cache_read_tokens += resp.cache_read_tokens
        self.state.cache_write_tokens += resp.cache_write_tokens

    def check_budget(self) -> None:
        b = self.charter.budget
        if b.spend_usd and self.state.cost_usd >= b.spend_usd:
            raise BudgetExhausted(f"spend {self.state.cost_usd:.2f} reached the "
                                  f"budget of {b.spend_usd:.2f} USD")
        if b.tokens and self.state.tokens >= b.tokens:
            raise BudgetExhausted(f"{self.state.tokens} tokens reached the budget "
                                  f"of {b.tokens}")
        if b.wall_time_s and self.elapsed() >= b.wall_time_s:
            raise BudgetExhausted(f"wall time reached the budget of {b.wall_time_s}s")

    def structured(self, role: str, resp, schema: dict) -> dict | None:
        """Validate a returned object before anything is applied."""
        data = resp.structured
        if data is None and resp.text:
            from .runner import _loose_json
            data = _loose_json(resp.text)
        if not isinstance(data, dict):
            self.ledger.write("rejected", role=role, reason="no JSON object returned",
                              summary=(resp.error or resp.text or "")[:200])
            return None
        try:
            return schemas.validate(schemas.coerce(data, schema), schema)
        except schemas.SchemaError as exc:
            self.ledger.write("rejected", role=role, reason="schema", summary=str(exc)[:300])
            return None

    # Files the agent owns, written only through the harness.
    def read_self(self) -> str:
        return self.store.self_md.read_text()

    def read_taste(self) -> str:
        return self.store.taste.read_text()

    def append_memory(self, items: list[str]) -> None:
        if not items:
            return
        with open(self.store.memory, "a") as fh:
            for item in items:
                if str(item).strip():
                    fh.write(f"- {str(item).strip()}\n")

    def append_taste(self, items: list[dict]) -> None:
        if not items:
            return
        with open(self.store.taste, "a") as fh:
            for item in items:
                subject = str(item.get("subject") or "").strip()
                if not subject:
                    continue
                fh.write(f"- [{item.get('verdict', 'reject')}] {subject}. "
                         f"{str(item.get('reason') or '').strip()}\n")

    def write_self(self) -> None:
        """self.md holds the objectives in the first person. The harness writes
        it, because the agent writes nothing.
        """
        lines = ["# Objectives", "",
                 "These are mine. Each one cites the charter line it serves.", ""]
        for o in self.state.objectives:
            if o.get("status") != "live":
                continue
            lines.append(f"## {o['id']} (weight {float(o.get('weight', 0.5)):.2f})")
            lines.append(o.get("text", ""))
            lines.append(f"Serves: {o.get('charter_line', '')}")
            if o.get("trigger"):
                lines.append(f"Triggered by: {o['trigger']}")
            lines.append("")
        dropped = [o for o in self.state.objectives if o.get("status") != "live"]
        if dropped:
            lines += ["## Dropped", ""]
            lines += [f"- {o['id']}: {o.get('text', '')}" for o in dropped] + [""]
        self.store.self_md.write_text("\n".join(lines))

    def cites_charter(self, quoted: str, text: str = "") -> bool:
        """Does this cite a real charter line, and does it serve it.

        Counting shared content words passed any citation containing a common
        word. A reader is given the charter and asked.
        """
        quoted = (quoted or "").strip()
        if not quoted:
            return False
        if not self.reader.enabled:
            return self.charter.cites(quoted)
        reading = self.reader.read(
            "Does the cited line appear in this charter, and does the "
            "objective serve it?",
            f"Cited line: {quoted}\n\nObjective: {text}",
            [self.charter.text],
            kind="citation")
        if reading.unsure and not reading.findings:
            return self.charter.cites(quoted)
        return bool(reading.findings) or self.charter.cites(quoted)

    def apply_objectives(self, items: list[dict], source: str) -> None:
        for item in items:
            action = item.get("action")
            oid = str(item.get("id") or "").strip() or f"obj-{len(self.state.objectives) + 1}"
            existing = self.state.objective(oid)
            if action == "drop":
                if existing:
                    existing["status"] = "dropped"
                    self.ledger.write("objective", objective_id=oid, action="drop",
                                      summary=existing.get("text", "")[:200], source=source)
                continue
            row = {
                "id": oid,
                "text": item.get("text", ""),
                "weight": float(item.get("weight", 0.5)),
                "charter_line": item.get("charter_line", ""),
                "trigger": item.get("trigger", ""),
                "created_turn": self.state.turn,
                "status": "live",
                "criteria_met": existing.get("criteria_met", 0) if existing else 0,
                "criteria_total": existing.get("criteria_total", 0) if existing else 0,
            }
            if existing:
                existing.update({k: v for k, v in row.items()
                                 if k not in ("criteria_met", "criteria_total")})
            else:
                self.state.objectives.append(row)
            self.ledger.write("objective", objective_id=oid, action=action or "add",
                              summary=row["text"][:200], charter_line=row["charter_line"],
                              trigger=row["trigger"], source=source)
        self.write_self()

    # Stance derived values.
    def sift_weights(self) -> dict:
        return stn.sift_weights(self.state.stance, self.cfg)

    def drift_target(self) -> int:
        return stn.drift_target(self.state.stance, self.cfg, self.state.signals.curiosity)

    def appetite_left(self) -> float:
        return req.appetite_left(self.charter, self.requirements)

    # Hooks the spoon cycle calls back through, so the cycle does not need a
    # reference to the Harness.
    def apply_invented(self, items: list[dict], origin: dict, cycle: int) -> int:
        # Sift's path gates in the cycle, so it is not gated twice.
        return self.harness.apply_requirements(items, source="cycle", origin=origin,
                                               cycle=cycle, gated=True)

    def harness_escalate(self, item: dict) -> None:
        self.harness.raise_escalations([item])

    def harness_note(self, note: dict) -> None:
        """What he thinks the charter has wrong. Never applied."""
        self.state.process_notes.append({**note, "turn": self.state.turn})
        self.ledger.write("process_note", turn=self.state.turn,
                          source="requirement",
                          summary=note.get("text", "")[:300],
                          why=note.get("why", "")[:300])

    def save(self) -> None:
        # Fold the time since this start into the total and restart the clock,
        # so a kill between saves loses at most one turn of it.
        if self.state.started:
            self.state.elapsed_s += max(0.0, time.time() - self.state.started)
            self.state.started = time.time()
        self.state.save_rng(self.rng)
        self.state.trust = self.trust.to_dict()
        self.state.ladder = self.ladder.to_dict()
        self.state.requirements = self.requirements.to_list()
        self.state.ways = self.ways.to_list()
        self.store.write_json(self.store.state, self.state.to_dict())


class Harness:
    def __init__(self, ctx: Context) -> None:
        self.ctx = ctx
        ctx.harness = self

    # One full turn.
    def turn(self) -> dict:
        ctx = self.ctx
        ctx.state.turn += 1
        turn = ctx.state.turn
        ctx.ledger.turn = turn
        ctx.ledger.write("turn", state="start", turn=turn,
                         stance=ctx.state.stance.describe(),
                         signals=ctx.state.signals.to_dict())

        ctx.state.spot_checks_this_turn = 0
        self.drain_inbox()
        views = self.collect_returns()
        self.run_due_audits()

        decision, verdict = self.wake(views)
        if decision:
            ctx.state.failed_turns = 0
            applied = self.apply(decision, verdict)
        else:
            ctx.state.failed_turns += 1
            applied = {"dispatched": 0}

        self.drain_spot_checks()
        self.update_signals(views, applied)
        self.move_stance(views)

        changed = bool(views) or any(applied.get(k) for k in
                                     ("dispatched", "judged", "amended", "escalated",
                                      "invented"))
        ctx.state.idle_turns = 0 if changed else ctx.state.idle_turns + 1
        if ctx.cfg.life.enabled:
            ctx.state.life_day_count = ctx.life.index().day_count

        self.collect_cycle()
        pending = ctx.state.pending_drift[:1]
        blocked = not ctx.pool.in_flight and applied.get("dispatched", 0) == 0 and not views
        # Never both in one turn, and one cycle at a time.
        if pending:
            ctx.state.pending_drift = ctx.state.pending_drift[1:]
            self.start_cycle("a spot check opened something",
                             pending[0]["problem"], pending[0].get("origin"))
        elif self.cycle_due():
            self.start_cycle("scheduled", self.open_problem(), None)
        elif blocked:
            self.start_cycle("wake blocked", self.open_problem(), None)

        # A turn is a sitting, and a day passes between sittings by default.
        # Written beside the builders' work, which a 200-word entry makes cheap.
        if ctx.cfg.life.enabled and ctx.cfg.life.day_between_sittings:
            self.write_the_day()
        if turn % max(1, ctx.cfg.interlude.every_n_turns) == 0:
            self.interlude()
        self.force_day_for_plants()
        self.settle_influence()

        trigger = self.stepping_back_due()
        if trigger:
            self.step_back(trigger)
        # The digest runs before the metrics row, so the row records the
        # stepping back that happened on this turn rather than the next one.
        self.maybe_digest()
        self.record_metrics(views, applied)
        ctx.save()
        ctx.ledger.write("turn", state="end", turn=turn,
                         cost_usd=round(ctx.state.cost_usd, 4),
                         summary=f"{applied.get('dispatched', 0)} dispatched, "
                                 f"{len(views)} returns read")
        return {"turn": turn, "views": len(views), **applied}

    def drain_inbox(self) -> int:
        """Operator input arrives as files, because it comes from another
        process and the loop owns state.json.

        A note is consumed whether or not it matched, so an answer to an
        unknown escalation is not retried every turn forever.
        """
        ctx = self.ctx
        if not ctx.store.inbox.exists():
            return 0
        done = ctx.store.inbox / "done"
        done.mkdir(parents=True, exist_ok=True)
        taken = 0
        for path in sorted(ctx.store.inbox.glob("*.json")):
            note = ctx.store.read_json(path)
            if note.get("kind") == "answer":
                eid = note.get("id", "")
                if ctx.state.answer_escalation(eid, note.get("text", "")):
                    e = ctx.state.escalation(eid)
                    if e is not None:
                        ctx.store.write_json(
                            ctx.store.escalations / f"{eid}.json", e.to_dict())
                    ctx.ledger.write("escalation_answered", id=eid, source="inbox",
                                     turn=ctx.state.turn,
                                     summary=note.get("text", "")[:300])
                    taken += 1
                else:
                    ctx.ledger.write("rejected", bucket="inbox",
                                     reason="no open escalation with that id",
                                     summary=eid)
            path.rename(done / path.name)
        return taken

    # Returns and the attention filter.
    def collect_returns(self) -> list[dict]:
        ctx = self.ctx
        answered = any(e.get("answer") and not e.get("consumed")
                       for e in ctx.state.escalations)
        if ctx.pool.in_flight and not answered:
            # Nothing has changed until something comes back, and a Wake call on
            # an unchanged context decides nothing and costs the budget.
            ctx.pool.wait_one(ctx.cfg.dispatching.wait_for_return_s)
        out = []
        for did, resp in ctx.pool.collect():
            d = ctx.state.dispatch(did)
            if d is None:
                continue
            # From a counter, not a glob. The glob counted the view files too,
            # which made the ids odd-numbered and the count O(n) per return.
            ctx.state.returns_made += 1
            rid = f"r{ctx.state.returns_made:05d}"
            ret = parse_return(resp.text or resp.error, return_id=rid, dispatch_id=did,
                               orchestrator=d.orchestrator_key or orchestrator_key(ctx.cfg, d))
            ret.cost_usd = resp.cost_usd
            ret.tokens = resp.total_tokens
            # Every return is stored whole, read or not, so an audit or a later
            # failure can open it.
            ctx.store.write_json(ctx.store.returns / f"{rid}.json", ret.to_dict())

            if ret.assumptions:
                ctx.ledger.write("return_assumptions", return_id=rid, dispatch_id=did,
                                 turn=ctx.state.turn,
                                 assumptions=[a.text for a in ret.assumptions],
                                 summary=f"{len(ret.assumptions)} assumptions listed")
            view = self.read_return(ret, d)
            out.append(view)
            d.returns.append(rid)
            d.status = "returned"
            ctx.state.put_dispatch(d)
        return out

    def read_return(self, ret: Return, d: Dispatch) -> dict:
        ctx = self.ctx
        branch = d.objective_id or d.id
        key = d.orchestrator_key or orchestrator_key(ctx.cfg, d)
        # Every draw for this return comes from a stream derived from the seed
        # and the return id, so the mode does not depend on wall-clock timing.
        rng = ctx.rng.substream(f"return:{ret.id}")
        # Queue depth from saved state rather than live thread liveness, for
        # the same reason.
        queue_depth = max(0, len([x for x in ctx.state.open_dispatches()
                                  if x.id != d.id]))
        draw = attention.draw_mode(
            ret, ctx.cfg, rng,
            sitting=ctx.state.sitting,
            sitting_share=ctx.state.sitting_share,
            thorough=ctx.disposition.thorough,
            trusting=ctx.disposition.trusting,
            trust=ctx.trust.get(key),
            queue_depth=queue_depth,
            unease=ctx.state.signals.unease,
            stance=ctx.state.stance.value,
            debt=ctx.state.debt_for(branch),
        )
        salience = attention.salience_caller(
            ctx.runner_for("salience"), ctx.cfg, ctx.prompts, spend_hook=ctx.charge,
            cwd=str(ctx.store.sandbox)
        ) if draw.mode == attention.SKIM else None
        motifs = list(ctx.state.motifs)
        for inf in self.influence_pending(infl.WORRY):
            infl.check_surface(infl.WORRY, "salience")
            motifs.append(inf.text)
            ctx.influence.take(inf, ctx.state.turn)
        text = attention.cut(ret, draw.mode, ctx.cfg, salience=salience,
                             motifs=motifs, unease=ctx.state.signals.unease)
        ctx.state.bump_debt(branch, draw.mode == attention.FULL)
        ctx.store.write_json(ctx.store.returns / f"{ret.id}.view.json",
                             {"return_id": ret.id, "mode": draw.mode,
                              "draw": draw.to_dict(), "view": text})
        ctx.ledger.write("read_mode", return_id=ret.id, dispatch_id=d.id,
                         read_mode=draw.mode, forced=draw.forced,
                         score=round(draw.score, 3), inputs=draw.inputs,
                         branch=branch, audit_due=draw.audit_due,
                         turn=ctx.state.turn,
                         summary=attention.ledger_phrase(draw.mode))
        if draw.audit_due:
            # One in five glances and waves-through gets a full read later.
            ctx.state.pending_audits.append(
                {"return_id": ret.id, "dispatch_id": d.id, "key": key,
                 "due_turn": ctx.state.turn + 1})

        # Only the view enters the manifold. The experience was a skim, and the
        # record says so.
        ctx.manifold.write("sensory", f"[{draw.mode}] {ret.headline}",
                           cycle=ctx.state.cycle, source=ret.id)
        notes = []
        if draw.mode == attention.FULL and not ctx.cfg.pace.one_call_per_sitting:
            notes = self.react(ret, text)
        ctx.state.returns_read += 1

        # Sometimes the agent looks for itself rather than taking the report.
        itch = next(iter(self.influence_pending(infl.ITCH)), None)
        trigger = sc.should_spot_check(ctx, ret, d, ctx.trust.get(key), rng=rng)
        if itch and not trigger:
            trigger = "something drew the eye"
        if trigger:
            question = (f"The return says: {ret.headline} Is that true of the "
                        f"project, and what else is there to see?")
            if itch:
                infl.check_surface(infl.ITCH, "spot_check_target")
                question = (f"What is the state of {itch.text}, and is it right? "
                            f"The return says: {ret.headline}")
            job = {"question": question, "dispatch_id": d.id, "return_id": ret.id,
                   "trigger": trigger, "itch_id": itch.id if itch else ""}
            if ctx.cfg.pace.spot_checks_beside_work:
                # Beside the next dispatch, never in front of it. The builders
                # waited on this call, and it reads the project they are in.
                ctx.state.pending_spot_checks.append(job)
            else:
                self.run_spot_check_job(job, ret=ret)
        return {"return": ret, "view": text, "mode": draw.mode, "notes": notes,
                "dispatch": d, "key": key, "draw": draw.to_dict()}

    def run_spot_check_job(self, job: dict, ret: Return | None = None) -> None:
        """One queued spot check. Run after the dispatches are launched, so the
        builders are working while it reads.
        """
        ctx = self.ctx
        d = ctx.state.dispatch(job.get("dispatch_id", ""))
        if d is None:
            return
        if ret is None and job.get("return_id"):
            path = ctx.store.returns / f"{job['return_id']}.json"
            if path.exists():
                ret = Return.from_dict(ctx.store.read_json(path))
        f = sc.run_spot_check(ctx, job["question"], dispatch=d, ret=ret,
                              trigger=job.get("trigger", ""))
        if f is None:
            return
        self.after_spot_check(f, d)
        itch_id = job.get("itch_id")
        if itch_id:
            itch = next((i for i in ctx.influence.pending(infl.ITCH)
                         if i.id == itch_id), None)
            if itch is not None:
                ctx.influence.take(itch, ctx.state.turn)
                ctx.influence.add_trace(
                    itch_id, "spot_check", f.id, detail=f.findings[:200],
                    turn=ctx.state.turn, survived=bool(f.gap or f.openings))

    def drain_spot_checks(self) -> int:
        ctx = self.ctx
        jobs, ctx.state.pending_spot_checks = ctx.state.pending_spot_checks, []
        for job in jobs:
            self.run_spot_check_job(job)
        return len(jobs)

    def react(self, ret: Return, view: str) -> list[dict]:
        """React before judgement. Write what the view shows into the manifold,
        verbatim and sensory, before any judgement.
        """
        ctx = self.ctx
        prompt = ctx.prompts.fill(
            "react",
            return_view=view,
            evidence=json.dumps([e.__dict__ for e in ret.evidence], indent=2),
            objectives=ctx.read_self(),
        )
        resp = ctx.call("react", prompt, schemas.REACT, model=ctx.cfg.models.react,
                        budget=ctx.cfg.spend.react)
        data = ctx.structured("react", resp, schemas.REACT)
        notes = (data or {}).get("notes") or []
        ctx.manifold.write_many(notes, cycle=ctx.state.cycle, source=ret.id)
        return notes

    def run_due_audits(self) -> None:
        """Where the full read agrees with what was accepted, trust rises. Where
        it finds something the flags should have carried, trust drops hard.
        """
        ctx = self.ctx
        due = [a for a in ctx.state.pending_audits if a["due_turn"] <= ctx.state.turn]
        if not due:
            return
        ctx.state.pending_audits = [a for a in ctx.state.pending_audits
                                    if a["due_turn"] > ctx.state.turn]
        for a in due:
            path = ctx.store.returns / f"{a['return_id']}.json"
            if not path.exists():
                continue
            ret = Return.from_dict(ctx.store.read_json(path))
            d = ctx.state.dispatch(a["dispatch_id"])
            prompt = ctx.prompts.fill(
                "audit",
                flags=json.dumps([f.__dict__ for f in ret.flags], indent=2),
                whole_return=attention.cut(ret, attention.FULL, ctx.cfg),
                criteria=json.dumps(d.acceptance if d else [], indent=2),
            )
            resp = ctx.call("audit", prompt, schemas.AUDIT, model=ctx.cfg.models.audit,
                            budget=ctx.cfg.spend.audit)
            data = ctx.structured("audit", resp, schemas.AUDIT)
            if not data:
                continue
            if data.get("agrees") and data.get("severity") == "none":
                value = ctx.trust.agreed(a["key"])
                verdict = "agreed"
            else:
                value = ctx.trust.missed(a["key"], data.get("severity", "minor"))
                verdict = data.get("severity", "minor")
                for missed in data.get("missed") or []:
                    ctx.manifold.write("friction", f"The flags left this out: {missed}",
                                       cycle=ctx.state.cycle, source=ret.id)
                if d:
                    # That branch gets full reads until it recovers.
                    ctx.state.debt[d.objective_id or d.id] = ctx.cfg.attention.debt_cap
            ctx.ledger.write("audit", return_id=ret.id, dispatch_id=a["dispatch_id"],
                             outcome=verdict, trust=round(value, 3),
                             summary="; ".join(data.get("missed") or []) [:300] or
                                     "the flags carried what mattered")
            ctx.ledger.write("trust", key=a["key"], trust=round(value, 3),
                             outcome=verdict, source="audit", turn=ctx.state.turn,
                             return_id=ret.id)

    # Wake.
    def wake(self, views: list[dict]):
        ctx = self.ctx
        answers = [e for e in ctx.state.escalations if e.get("answer")
                   and not e.get("consumed")]
        prompt = ctx.prompts.fill(
            "wake",
            self=ctx.read_self(),
            charter_refusals="\n".join(f"- {r}" for r in ctx.charter.refusals) or "(none)",
            charter_reserved="\n".join(f"- {r}" for r in ctx.charter.reserved) or "(none)",
            stance=ctx.state.stance.describe(),
            signals=ctx.state.signals.line(),
            objectives=json.dumps(ctx.state.live_objectives(), indent=2),
            plan=self.render_plan(),
            returns_view="\n\n".join(v["view"] for v in views) or "(no returns this turn)",
            ledger_recent=self.ledger_for_sitting() or "(empty)",
            manifold_warm=mf.render(ctx.manifold.project()),
            escalation_answers=json.dumps(
                [{"question": e["question"], "answer": e["answer"]} for e in answers],
                indent=2) if answers else "(none)",
            life_recent=ctx.life.for_judgement(days=ctx.cfg.pace.wake_life_days)
            if ctx.cfg.life.enabled else "(no life running)",
            mood=ctx.life.mood_line() if ctx.cfg.life.enabled else "no life running",
            spot_check_findings=sc.render_findings(ctx.state.spot_check_findings),
            requirements=json.dumps(ctx.requirements.open(), indent=2)
            if ctx.requirements.rows else "(none invented yet)",
            appetite=f"{ctx.appetite_left():.0%} of the budget remains available "
                     f"for work nobody asked for",
            ways=ctx.ways.render(),
            candidates=self.render_candidates(),
            turn=str(ctx.state.turn),
            budget=self.budget_line(),
        )
        for e in answers:
            e["consumed"] = True
        resp = ctx.call("wake", prompt, schemas.DECISION, model=ctx.cfg.models.wake,
                        budget=ctx.cfg.spend.wake)
        data = ctx.structured("wake", resp, schemas.DECISION)
        if not data:
            return None, None
        verdict = dec.validate_decision(data, ctx.charter, ctx.cfg,
                                        recent_medium=sum(ctx.state.medium_recent),
                                        reader=ctx.reader)
        for reading in verdict.readings:
            # The grounds for a refusal or an escalation, with the quote the
            # harness checked against the text.
            ctx.ledger.write("reading", dispatch_id=reading.get("dispatch_id"),
                             turn=ctx.state.turn,
                             unsure=reading.get("unsure"),
                             escalated_to_mid=reading.get("escalated_to_mid"),
                             discarded=len(reading.get("discarded") or []),
                             findings=[{"rule": f["rule"][:80],
                                        "direction": f["direction"],
                                        "quote": f["quote"][:160],
                                        "tier": f["tier"]}
                                       for f in reading.get("findings") or []],
                             summary=f"{len(reading.get('findings') or [])} findings, "
                                     f"{len(reading.get('discarded') or [])} discarded")
        for r in verdict.rejections:
            ctx.ledger.write("rejected", bucket=r["bucket"], reason=r["reason"],
                             matched=r.get("matched", ""),
                             summary=json.dumps(r["item"])[:300])
        return data, verdict

    def ledger_for_sitting(self) -> str:
        """The last few turns of the ledger, not the last N lines. A turn with
        many calls used to push the turn before it out of view entirely.
        """
        ctx = self.ctx
        keep = max(1, ctx.cfg.pace.wake_ledger_turns)
        floor = max(0, ctx.state.turn - keep)
        rows = [r for r in ctx.ledger.tail(ctx.cfg.digest.ledger_lines_in_wake * 4)
                if int(r.get("turn") or 0) >= floor]
        return summarise(rows, ctx.cfg.digest.ledger_lines_in_wake)

    def render_candidates(self) -> str:
        """What the dreaming found, as work he can pick up.

        Sixteen candidates went through the gate on the second run and none
        reached a dispatch, because they were shown as bare strings with no
        way to act on them.
        """
        rows = [c for c in self.ctx.state.candidates if isinstance(c, dict)]
        if not rows:
            return "(none)"
        out = []
        for i, c in enumerate(rows, start=1):
            out.append(f"{i}. [{c.get('kind', 'solution')}] {c.get('text', '')}")
            if c.get("disconfirming"):
                out.append(f"   the cheapest thing that would kill it: "
                           f"{c['disconfirming']}")
        out.append("")
        out.append("These survived the gate. Dispatch the ones worth building, "
                   "as ordinary work. They are yours and nobody is asked.")
        return "\n".join(out)

    def render_plan(self) -> str:
        ctx = self.ctx
        rows = []
        for d in ctx.state.open_dispatches():
            rows.append({"id": d.id, "title": d.title, "objective_id": d.objective_id,
                         "tier": d.tier, "acceptance": d.acceptance,
                         "amendments": d.amendments, "status": d.status,
                         "rung": ctx.ladder.rung(d.id),
                         "failures": int(ctx.ladder.table.get(d.id, {}).get("failures", 0)),
                         "in_flight": d.id in ctx.pool.in_flight})
        return json.dumps(rows, indent=2) if rows else "(no dispatches in flight)"

    def budget_line(self) -> str:
        b = self.ctx.charter.budget
        s = self.ctx.state
        parts = [f"spend {s.cost_usd:.2f} of {b.spend_usd:.2f} USD" if b.spend_usd
                 else f"spend {s.cost_usd:.2f} USD, no ceiling set",
                 f"tokens {s.tokens} of {b.tokens}" if b.tokens else f"tokens {s.tokens}",
                 f"{s.calls} model calls"]
        if b.wall_time_s:
            left = int(b.wall_time_s - self.ctx.elapsed())
            parts.append(f"{max(0, left)}s of wall time left")
        return ", ".join(parts)

    # Applying a decision.
    def apply(self, decision: dict, verdict) -> dict:
        ctx = self.ctx
        d = verdict.decision
        ctx.state.stance.line = d.get("stance_line", "")
        ctx.ledger.write("stance", summary=ctx.state.stance.line,
                         stance=round(ctx.state.stance.value, 3))

        ctx.manifold.write_many(d.get("notes") or [], cycle=ctx.state.cycle, source="wake")

        # An amendment written in the same turn as an accept is written first.
        amended = self.apply_amendments(d.get("amendments") or [])
        judged, accepts = self.apply_judgements(d.get("judgements") or [])
        ctx.apply_objectives(d.get("objectives") or [], source="wake")
        self.apply_ladder(d.get("ladder") or [])
        # Escalation ids are minted before any child starts, like session ids.
        # The readers that found them already ran, so this costs no call.
        escalated = self.raise_escalations(verdict.escalations)

        # Everything that starts a child is below this line, and state is on
        # disk before any of it runs. A crash after this point resumes with the
        # session ids and escalation ids it already minted.
        # Ids and session ids are minted and saved before any child starts, so
        # a crash between here and the next save resumes the same sessions
        # rather than starting a second orchestrator on the same objective.
        prepared = self.prepare_dispatches(d.get("dispatches") or [])
        if ctx.state.turn <= 1 and len(prepared) > 1:
            ctx.ledger.write("fan_out", turn=ctx.state.turn,
                             dispatches=[p.id for p in prepared],
                             summary=f"{len(prepared)} started at once on the "
                                     f"first sitting")
        ctx.ledger.write("apply", turn=ctx.state.turn, state="intent",
                         dispatches=[p.id for p in prepared],
                         summary="about to start children")
        ctx.save()
        dispatched = self.launch_dispatches(prepared)
        # Everything below runs beside the work, never in front of it. The
        # requirement gate's readers took 161 seconds on the first sitting of
        # the third run, all of it with nothing building.
        invented = self.apply_requirements(d.get("requirements") or [], source="wake")
        self.check_launched(prepared)
        self.run_inspections(d.get("inspect") or [])
        self.run_queries(d.get("query") or [])
        ctx.save()
        ctx.ledger.write("apply", turn=ctx.state.turn, state="done",
                         dispatched=dispatched,
                         summary="children started and state saved")

        ctx.ledger.write("decision", turn=ctx.state.turn,
                         summary=(d.get("rationale") or "")[:400],
                         dispatched=dispatched, judged=judged, amended=amended,
                         escalated=escalated, invented=invented,
                         rejected=len(verdict.rejections))

        stop = d.get("stop") or {}
        if stop.get("requested"):
            ctx.state.stopped = True
            ctx.state.stop_reason = stop.get("reason", "the agent asked to stop")
            ctx.ledger.write("run_stopped", reason=ctx.state.stop_reason, source="agent")
        return {"dispatched": dispatched, "judged": judged, "amended": amended,
                "escalated": escalated, "rejected": len(verdict.rejections),
                "accepts": accepts, "invented": invented}

    def apply_amendments(self, amendments: list[dict]) -> int:
        ctx = self.ctx
        n = 0
        for a in amendments:
            d = ctx.state.dispatch(a.get("dispatch_id", ""))
            if d is None:
                continue
            row = {"direction": a.get("direction"), "trigger": a.get("trigger"),
                   "criterion": a.get("criterion"), "turn": ctx.state.turn,
                   "ts": time.time()}
            d.amendments.append(row)
            direction = a.get("direction")
            criterion = a.get("criterion") or ""
            replaces = (a.get("replaces") or "").strip()
            if direction == "redirect" and criterion:
                row["removed"] = list(d.acceptance)
                d.acceptance = [criterion]
            elif direction == "relax" and criterion:
                # A relax that leaves the strict criterion in force has relaxed
                # nothing, and the orchestrator is then asked for both.
                removed = _match_criterion(d.acceptance, replaces or criterion)
                if removed is not None:
                    row["removed"] = [d.acceptance[removed]]
                    d.acceptance = [c for i, c in enumerate(d.acceptance)
                                    if i != removed] + [criterion]
                else:
                    row["removed"] = []
                    d.acceptance = d.acceptance + [criterion]
            elif direction == "raise" and criterion:
                d.acceptance = d.acceptance + [criterion]
            ctx.state.put_dispatch(d)
            ctx.state.amendments.append({**row, "dispatch_id": d.id,
                                         "objective_id": d.objective_id})
            ctx.ledger.write("amendment", dispatch_id=d.id, direction=a.get("direction"),
                             trigger=a.get("trigger", ""), summary=a.get("criterion", "")[:300])
            n += 1
        warning = dec.check_amendment_ratio(ctx.state.amendments, ctx.cfg)
        if warning:
            ctx.ledger.write("amendment", direction="ratio", summary=warning)
            ctx.manifold.write("friction", f"The amendment ledger only relaxes: {warning}",
                               cycle=ctx.state.cycle, source="detector")
        return n

    def apply_judgements(self, judgements: list[dict]) -> tuple[int, int]:
        ctx = self.ctx
        n = 0
        accepts = 0
        for j in judgements:
            rid = j.get("return_id", "")
            path = ctx.store.returns / f"{rid}.json"
            did = ""
            if path.exists():
                did = ctx.store.read_json(path).get("dispatch_id", "")
            d = ctx.state.dispatch(did)
            outcome = j.get("outcome")
            if outcome == "accept":
                accepts += 1
            if d is not None:
                if outcome == "accept":
                    d.status = "closed"
                    ctx.ladder.record_progress(d.id)
                    self.mark_requirements_built(d)
                    obj = ctx.state.objective(d.objective_id)
                    if obj:
                        obj["criteria_met"] = len(d.acceptance)
                        obj["criteria_total"] = max(len(d.acceptance),
                                                    int(obj.get("criteria_total", 0)))
                elif outcome == "reject":
                    d.status = "open"
                    rung = ctx.ladder.record_failure(d.id)
                    self.walk_ladder(d, rung, j.get("reason", ""))
                else:
                    d.status = "open"
                ctx.state.put_dispatch(d)
            ctx.ledger.write("judgement", return_id=rid, dispatch_id=did,
                             outcome=outcome, read_mode=self.mode_of(rid),
                             summary=(j.get("reason") or "")[:300])
            n += 1
        return n, accepts

    def mark_requirements_built(self, d) -> None:
        """A requirement whose dispatch was accepted is built.

        Six requirements still read open at the end of the second run, with
        their work accepted, because nothing ever closed them.
        """
        ctx = self.ctx
        ids = set(getattr(d, "requirement_ids", []) or [])
        for row in ctx.requirements.rows:
            if row.get("status") != "open":
                continue
            if row["id"] in ids or (row.get("objective_id")
                                    and row["objective_id"] == d.objective_id
                                    and row["id"] in ids):
                row["status"] = "built"
                row["built_turn"] = ctx.state.turn
                row["built_by"] = d.id
                ctx.ledger.write("requirement", id=row["id"], state="built",
                                 dispatch_id=d.id, turn=ctx.state.turn,
                                 summary=row.get("text", "")[:200])

    def mode_of(self, rid: str) -> str:
        path = self.ctx.store.returns / f"{rid}.view.json"
        return self.ctx.store.read_json(path).get("mode", "") if path.exists() else ""

    def walk_ladder(self, d: Dispatch, rung: int, reason: str) -> None:
        """Frustration is only useful if it has somewhere to go."""
        ctx = self.ctx
        ctx.ledger.write("signal", rung=rung, dispatch_id=d.id,
                         summary=sig.RUNGS.get(rung, ""), reason=reason[:200])
        if rung == 3:
            # Change the builder. A new session is a new process.
            d.session_id = ""
            ctx.state.put_dispatch(d)
        elif rung == 5:
            self.raise_escalations([{
                "question": f"Dispatch {d.id} has failed {rung} times. What now?",
                "tier": "high", "why": reason or "repeated failure on one subgoal",
                "source": "ladder", "payload": d.to_dict()}])
        elif rung >= 6:
            d.status = "killed"
            ctx.state.put_dispatch(d)
            ctx.ledger.write("kill", dispatch_id=d.id,
                             summary="the subgoal lost its allocation")

    def apply_ladder(self, rows: list[dict]) -> None:
        for row in rows:
            sid = row.get("subgoal_id", "")
            rung = int(row.get("rung", 1))
            d = self.ctx.state.dispatch(sid)
            if d is not None and rung >= 6:
                d.status = "killed"
                self.ctx.state.put_dispatch(d)
                self.ctx.ledger.write("kill", dispatch_id=sid,
                                      summary="killed at the agent's rung 6")

    def check_launched(self, prepared: list) -> int:
        """Read a launched low-tier dispatch against the charter, and kill it
        on a breach.

        Low tier means revertible, so starting first costs a revert at worst
        and saves the builders the reader's latency on every turn.
        """
        ctx = self.ctx
        if not ctx.cfg.launch_first or not ctx.reader.enabled:
            return 0
        killed = 0
        low = [d for d in prepared if d.tier == "low"]
        reads = rdr.parallel([
            (lambda d=d: dec._read_dispatch(
                {"id": d.id, "title": d.title, "intent": d.intent,
                 "acceptance": d.acceptance, "classes": d.classes,
                 "tier": d.tier}, ctx.charter, ctx.reader))
            for d in low])
        for d, (breach, escalate, why, reading) in zip(low, reads, strict=True):
            if reading is not None:
                ctx.ledger.write("reading", dispatch_id=d.id, turn=ctx.state.turn,
                                 unsure=reading.unsure,
                                 beside=True,
                                 findings=[{"rule": f.rule[:80],
                                            "direction": f.direction,
                                            "quote": f.quote[:160],
                                            "tier": f.tier}
                                           for f in reading.findings],
                                 summary=f"checked beside the work, "
                                         f"{len(reading.findings)} findings")
            if not (breach or escalate):
                continue
            # A breach kills it where it stands.
            ctx.pool.kill(d.id)
            live = ctx.state.dispatch(d.id)
            if live is not None:
                live.status = "killed"
                ctx.state.put_dispatch(live)
            ctx.ledger.write("kill", dispatch_id=d.id, turn=ctx.state.turn,
                             reason=why[:200],
                             summary="killed by the reader while it ran")
            if escalate:
                self.raise_escalations([{
                    "question": f"Proceed with dispatch {d.id}: {d.title}?",
                    "tier": "high", "why": why, "source": "dispatch",
                    "payload": {"id": d.id, "title": d.title,
                                "intent": d.intent,
                                "acceptance": d.acceptance,
                                "classes": d.classes, "tier": d.tier}}])
            killed += 1
        return killed

    def influence_pending(self, channel: str) -> list:
        """Pending influences on a channel, or nothing when it is switched off."""
        if not self.ctx.cfg.influence.enabled:
            return []
        return self.ctx.influence.pending(channel)

    def settle_influence(self) -> None:
        """Trace what came of each plant, and mark it took, faded or rejected.

        Every write here goes to the influence file. Nothing reaches the
        ledger, because the ledger goes into the wake prompt.
        """
        ctx = self.ctx
        if not ctx.cfg.influence.enabled:
            return
        rows = ctx.influence.all()
        if not rows:
            return
        by_element: dict[str, list] = {}
        for r in rows:
            for eid in r.element_ids:
                by_element.setdefault(eid, []).append(r)
        if by_element:
            # A drift link that anchored a planted element is the plant
            # reaching the work. Origins are traced already, so this reuses it.
            for path in sorted(ctx.store.cycles.glob("cycle-*.json")):
                cyc = ctx.store.read_json(path)
                cycle_no = cyc.get("cycle")
                anchors = {a for link in cyc.get("links", [])
                           for a in link.get("anchors", [])}
                # A life anchor is stripped from the link, because the life is
                # never a project anchor. It is kept beside it for the trace.
                anchors |= {a for link in cyc.get("links", [])
                            for a in link.get("life_anchors", [])}
                anchors |= {ing.get("ref") for link in cyc.get("links", [])
                            for ing in link.get("ingredients", [])}
                for eid, matched in by_element.items():
                    if eid not in anchors:
                        continue
                    for r in matched:
                        if any(t["ref"] == f"cycle-{cycle_no}" for t in r.traces):
                            continue
                        ctx.influence.add_trace(
                            r.id, "drift", f"cycle-{cycle_no}",
                            detail=f"a link anchored {eid}",
                            turn=ctx.state.turn,
                            survived=bool(cyc.get("kept") or cyc.get("requirements")))
                        for req_row in cyc.get("requirements", []):
                            ctx.influence.add_trace(
                                r.id, "requirement", req_row.get("text", "")[:80],
                                detail="through the cycle above",
                                turn=ctx.state.turn, survived=True)
        rows = infl.settle(ctx.influence.all(), ctx.state.turn,
                           ctx.cfg.influence.fade_after_turns)
        ctx.influence.save(rows)

    # Invented requirements, spot checks and queries.
    def apply_requirements(self, items: list[dict], source: str,
                           origin: dict | None = None, cycle: int = 0,
                           gated: bool = False) -> int:
        """A requirement nobody asked for, with its origin and its rework.

        Every requirement passes the same gate, whatever produced it. The Sift
        path gates before it gets here and says so with `gated`. The Wake path
        does not, so it is gated here.
        """
        ctx = self.ctx
        if not gated:
            candidates = [{**item, "kind": req.REQUIREMENT,
                           "appetite_share": float(item.get("appetite_share") or 0.0),
                           "changes_charter": bool(item.get("changes_charter"))}
                          for item in items]
            result = req.requirement_gate(candidates, ctx.charter, ctx.cfg,
                                          ctx.appetite_left(), reader=ctx.reader)
            for filed in result.filed:
                ctx.ledger.write("gate", bucket="requirements",
                                 reason=filed.get("filed_reason", ""),
                                 summary=filed.get("text", "")[:200])
            for item in result.escalated:
                # A reserved class is the one wait.
                self.raise_escalations([item])
            for note in result.notes:
                # Not blocked and not escalated. He builds toward the charter
                # he has, and the idea goes to the human.
                ctx.state.process_notes.append({**note, "turn": ctx.state.turn})
                ctx.ledger.write("process_note", turn=ctx.state.turn,
                                 source="requirement",
                                 summary=note.get("text", "")[:300],
                                 why=note.get("why", "")[:300])
            items = result.passed

        n = 0
        for item in items:
            text = (item.get("text") or "").strip()
            if not text:
                continue
            share = float(item.get("appetite_share") or 0.0)
            left = ctx.appetite_left()
            if share > left + 1e-9:
                ctx.ledger.write("rejected", bucket="requirements",
                                 reason=f"takes {share:.0%} against {left:.0%} of "
                                        f"appetite left",
                                 summary=text[:200])
                continue
            r = ctx.requirements.add(
                text=text,
                serves_intent=item.get("serves_intent", ""),
                rework=item.get("rework", ""),
                origin=origin or {"source": source,
                                  "trigger": item.get("origin", source)},
                appetite_share=share,
                turn=ctx.state.turn,
                cycle=cycle or ctx.state.cycle,
                objective_id=item.get("objective_id", ""),
            )
            ctx.manifold.write("unfinished", f"A requirement nobody asked for: {text}",
                               cycle=ctx.state.cycle, source=r.id)
            ctx.ledger.write("requirement", id=r.id, summary=text[:300],
                             serves_intent=r.serves_intent[:200],
                             rework=r.rework[:200], origin=r.origin,
                             appetite_share=round(share, 4),
                             source=source,
                             appetite_used=round(ctx.requirements.appetite_used(), 4))
            n += 1
        return n

    def run_inspections(self, items: list[dict]) -> int:
        """The agent asked to go and look. Granted inside a budget."""
        ctx = self.ctx
        n = 0
        for item in items:
            question = (item.get("question") or "").strip()
            if not question:
                continue
            if ctx.state.spot_checks_this_turn >= ctx.cfg.spot_check.max_per_turn:
                ctx.ledger.write("spot_check", outcome="not granted",
                                 summary=f"over the per-turn budget: {question[:150]}")
                break
            d = ctx.state.dispatch(item.get("dispatch_id", "")) or None
            f = sc.run_spot_check(ctx, question, dispatch=d, ret=None,
                                  trigger="the agent asked")
            if f is not None:
                n += 1
                self.after_spot_check(f, d)
        return n

    def run_queries(self, items: list[dict]) -> int:
        ctx = self.ctx
        n = 0
        for item in items[: ctx.cfg.spot_check.queries_per_turn]:
            d = ctx.state.dispatch(item.get("dispatch_id", ""))
            if sc.run_query(ctx, d, item.get("question", ""),
                            assumption=item.get("assumption", "")):
                n += 1
        return n

    def after_spot_check(self, f, dispatch) -> None:
        """A match raises trust. A gap drops it hard and usually means rework."""
        ctx = self.ctx
        if dispatch is not None:
            key = dispatch.orchestrator_key or orchestrator_key(ctx.cfg, dispatch)
            sc.apply_trust(ctx, f, key)
            if f.gap:
                # That branch gets full reads until it recovers.
                ctx.state.debt[dispatch.objective_id or dispatch.id] = \
                    ctx.cfg.attention.debt_cap
        if f.openings and ctx.cfg.spot_check.opens_drift:
            # Looking at the real thing is where an owner says "why does it do
            # that", and then "what if it did this instead".
            ctx.state.pending_drift.append({
                "problem": "Seen while looking at the project: "
                           + "; ".join(f.openings[:3]),
                "origin": {"spot_check": f.id, "dispatch": f.dispatch_id},
            })

    def raise_escalations(self, items: list[dict]) -> int:
        """Only that branch waits. An escalation also sends a notification."""
        ctx = self.ctx
        n = 0
        for i, item in enumerate(items):
            # Derived from the turn and the index, so a turn re-run after a
            # crash mints the same id rather than a second one.
            eid = f"e{ctx.state.turn:04d}{i:02d}"
            if ctx.state.escalation(eid) is not None:
                continue
            # An open escalation on the same dispatch is the same question.
            blocked = (item.get("payload") or {}).get("id", "")
            if blocked and any(
                    (e.get("payload") or {}).get("id", "") == blocked
                    and not e.get("answer") for e in ctx.state.escalations):
                ctx.ledger.write("escalation", id="", tier=item.get("tier", "high"),
                                 summary=f"already open on {blocked}, not re-raised")
                continue
            e = Escalation(id=eid, question=item.get("question", ""),
                           tier=item.get("tier", "high"), why=item.get("why", ""),
                           source=item.get("source", ""), payload=item.get("payload") or {},
                           turn=ctx.state.turn)
            ctx.state.escalations.append(e.to_dict())
            ctx.store.write_json(ctx.store.escalations / f"{eid}.json", e.to_dict())
            ctx.ledger.write("escalation", id=eid, tier=e.tier, question=e.question,
                             summary=e.why[:300])
            ctx.notifier.send(f"Escalation {eid}", f"{e.question} ({e.why})")
            n += 1
        return n

    def prepare_dispatches(self, items: list[dict]) -> list[Dispatch]:
        """Mint ids and sessions and put them in state. Nothing is started here.

        Unease blocks a dispatch and demands a check, and it blocks before
        anything is minted.
        """
        ctx = self.ctx
        if ctx.state.signals.unease >= ctx.cfg.signals.unease_blocks_dispatch_at \
                and items:
            ctx.ledger.write("signal", summary="unease blocked the dispatches this turn",
                             unease=round(ctx.state.signals.unease, 3))
            return []
        prepared: list[Dispatch] = []
        for item in items:
            if len(prepared) + len(ctx.pool.in_flight) >= ctx.cfg.dispatching.max_concurrent:
                break
            did = str(item.get("id") or "").strip() or f"d{len(ctx.state.dispatches) + 1:04d}"
            existing = ctx.state.dispatch(did)
            # Criteria hold until something seen changes them, and an amendment
            # is the only thing that changes them. Re-dispatching the same id
            # must not quietly drop a criterion an amendment added.
            acceptance = list(item.get("acceptance") or [])
            if existing:
                merged = list(existing.acceptance)
                merged += [c for c in acceptance if c not in merged]
                acceptance = merged
            d = Dispatch(
                id=did,
                objective_id=item.get("objective_id", ""),
                title=item.get("title", ""),
                intent=item.get("intent", ""),
                acceptance=acceptance,
                tier=item.get("tier", "low"),
                classes=list(item.get("classes") or []),
                session_id=existing.session_id if existing else "",
                turn_opened=ctx.state.turn,
                status="open",
                amendments=existing.amendments if existing else [],
                returns=existing.returns if existing else [],
            )
            # Down goes intent plus acceptance criteria and the ways.
            live = ctx.ways.render()
            d.ways = live if live != "(none yet)" else ""
            d.tools = list(getattr(ctx.charter, "tools", []) or [])
            d.requirement_ids = [r for r in (item.get("requirement_ids") or [])
                                 if r]
            d.orchestrator_key = orchestrator_key(ctx.cfg, d)
            d.resume_next = bool(existing and existing.session_id)
            if not d.session_id:
                d.session_id = str(uuid.uuid4())
            ctx.state.put_dispatch(d)
            prepared.append(d)
        return prepared

    def launch_dispatches(self, prepared: list[Dispatch]) -> int:
        """The harness starts an orchestrator for each prepared dispatch."""
        ctx = self.ctx
        started = 0
        mediums = 0
        for d in prepared:
            resume = bool(getattr(d, "resume_next", False))
            b = ctx.charter.budget
            d.minutes_left = int(max(0, b.wall_time_s - ctx.elapsed()) // 60) \
                if b.wall_time_s else 0
            prompt = d.follow_up(d.intent) if resume else d.brief()
            ctx.pool.start(d, prompt=prompt, resume=resume)
            ctx.ledger.write("dispatch", dispatch_id=d.id, tier=d.tier,
                             objective_id=d.objective_id, summary=d.title[:200],
                             resumed=resume, turn=ctx.state.turn)
            if d.tier == "medium":
                mediums += 1
            started += 1
        ctx.state.medium_recent.append(mediums)
        ctx.state.medium_recent = ctx.state.medium_recent[-ctx.cfg.tiers.medium_runaway_window:]
        return started

    def start_dispatches(self, items: list[dict]) -> int:
        """Prepare and launch in one call, for callers that do not need the split."""
        return self.launch_dispatches(self.prepare_dispatches(items))

    # Signals, stance, interlude, cycles.
    def update_signals(self, views: list[dict], applied: dict) -> None:
        ctx = self.ctx
        failures = sum(1 for v in views if v["return"].has_tier("high")
                       or v["return"].has_tier("medium"))
        thin = sum(1 for v in views if sig.thin_evidence(v["return"]))
        questions = len([n for v in views for n in v["notes"]
                         if n.get("texture") == "unfinished"])
        sig.update(ctx.state.signals, ctx.cfg, failures=failures, questions=questions,
                   accepts=int(applied.get("accepts", 0)), thin_evidence=thin)
        self.spend_signals(views)
        ctx.ledger.write("signal", summary=ctx.state.signals.line(),
                         signals=ctx.state.signals.to_dict())
        killed = ctx.ladder.tick_idle([d.id for d in ctx.state.open_dispatches()
                                       if d.id not in ctx.pool.in_flight])
        for sid in killed:
            d = ctx.state.dispatch(sid)
            if d and d.status == "open":
                d.status = "killed"
                ctx.state.put_dispatch(d)
                ctx.ledger.write("kill", dispatch_id=sid,
                                 summary=f"no state change in "
                                         f"{ctx.cfg.signals.kill_after_idle_cycles} cycles")

    def spend_signals(self, views: list[dict]) -> None:
        """Frustration and satisfaction each do their one thing.

        Frustration is only useful if it has somewhere to go, so above the
        threshold it advances the rung of the branch that is failing rather than
        waiting for another reject. Satisfaction closes the subgoal and releases
        its allocation, which is the debt and ladder state on that branch.
        """
        ctx = self.ctx
        s = ctx.state.signals
        if s.frustration >= ctx.cfg.signals.frustration_advances_rung_at:
            for v in views:
                # Re-read from state. The view holds the dispatch as it was
                # before this turn's judgement closed or reopened it.
                d = ctx.state.dispatch(v["dispatch"].id)
                if d is None or d.status in ("closed", "killed"):
                    continue
                rung = ctx.ladder.record_failure(d.id)
                ctx.ledger.write("signal", rung=rung, dispatch_id=d.id,
                                 turn=ctx.state.turn,
                                 summary=f"frustration {s.frustration:.2f} moved it to "
                                         f"rung {rung}: {sig.RUNGS.get(rung, '')}")
                self.walk_ladder(d, rung, "frustration, not a fresh reject")
                s.frustration = max(0.0, s.frustration - 0.3)
                break
        if s.satisfaction >= ctx.cfg.signals.satisfaction_releases_at:
            released = []
            for v in views:
                d = ctx.state.dispatch(v["dispatch"].id)
                if d is None or d.status != "closed":
                    continue
                branch = d.objective_id or d.id
                ctx.state.debt.pop(branch, None)
                ctx.ladder.record_progress(d.id)
                released.append(d.id)
            if released:
                ctx.ledger.write("signal", turn=ctx.state.turn,
                                 summary=f"satisfaction {s.satisfaction:.2f} released "
                                         f"{', '.join(released)}")

    def move_stance(self, views: list[dict]) -> None:
        ctx = self.ctx
        warm = ctx.manifold.recent(30)
        stn.tilt(
            ctx.state.stance, ctx.cfg,
            friction=sum(1 for e in warm if e.texture == "friction"),
            unfinished=sum(1 for e in warm if e.texture == "unfinished"),
            foreign=sum(1 for e in warm if e.texture == "foreign"),
            recent=len(warm),
            day=ctx.life.index().day_count if ctx.cfg.life.enabled else ctx.state.turn,
            drift_accepted=ctx.state.last_drift_accepted,
            drift_died_grounded=ctx.state.last_drift_died_grounded,
            unease=ctx.state.signals.unease,
            evidence_thin=any(sig.thin_evidence(v["return"]) for v in views),
        )

    def write_the_day(self) -> None:
        """One day per sitting, and the day says what it left for the project."""
        ctx = self.ctx
        if ctx.life.index().day_count > ctx.state.life_day_count:
            ctx.state.life_day_count = ctx.life.index().day_count
            return
        if ctx.life_writer.write_day():
            idx = ctx.life.index()
            ctx.state.life_day_count = idx.day_count
            last = idx.days[-1] if idx.days else {}
            ctx.state.sitting = last.get("sitting", "")
            ctx.state.sitting_share = float(last.get("sitting_share", 1.0))

    def force_day_for_plants(self) -> None:
        """A plant waits for the next day to be written.

        Where no day is due within a few turns, the harness brings one
        forward, so a plant does not sit unmet for the rest of the run.
        """
        ctx = self.ctx
        if not ctx.cfg.influence.enabled or not ctx.cfg.life.enabled:
            return
        waiting = self.influence_pending(infl.PLANT) + self.influence_pending(infl.VOICE)
        if not waiting:
            return
        oldest = min(w.created_turn for w in waiting)
        if ctx.state.turn - oldest < ctx.cfg.influence.force_day_within_turns:
            return
        if ctx.life.index().day_count > ctx.state.life_day_count:
            return
        ctx.life_writer.write_day()
        ctx.state.life_day_count = ctx.life.index().day_count

    def apply_mood_influence(self) -> None:
        ctx = self.ctx
        for inf in self.influence_pending(infl.MOOD):
            infl.check_surface(infl.MOOD, "stance")
            step = ctx.cfg.influence.mood_baseline_step
            lean = step if inf.text == "opportunity" else -step
            lo, hi = ctx.cfg.stance.bounds
            ctx.state.stance.baseline = max(lo, min(hi,
                                                    ctx.state.stance.baseline + lean))
            ctx.influence.take(inf, ctx.state.turn)

    def interlude(self) -> dict:
        ctx = self.ctx
        self.apply_mood_influence()
        before = self.guard_snapshot()
        record = il.run_interlude(ctx)
        broken = il.guardrail_check(before, self.guard_snapshot(before["ledger_len"]))
        if broken:
            # Randomness in authority is a runaway. This cannot happen through
            # the events above, and the check is here so that a change to them
            # stops the run rather than passing quietly.
            ctx.state.stopped = True
            ctx.state.stop_reason = f"an interlude touched protected state: {broken}"
            ctx.ledger.write("run_stopped", reason=ctx.state.stop_reason, source="guardrail")
        return record

    def record_metrics(self, views: list[dict], applied: dict) -> None:
        """The time series a later reader rebuilds the run from.

        Nothing here is derived at read time. Every value is what it was when
        the turn ended.
        """
        ctx = self.ctx
        idx = ctx.life.index() if ctx.cfg.life.enabled else None
        last_day = idx.days[-1] if (idx and idx.days) else {}
        interlude = [r for r in ctx.ledger.all()
                     if r["kind"] == "interlude" and r.get("turn_seen") is None]
        recent_interlude = interlude[-1] if interlude else {}
        record = {
            "turn": ctx.state.turn,
            "ts": time.time(),
            "iso": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "cycle": ctx.state.cycle,
            "stance": round(ctx.state.stance.value, 4),
            "stance_baseline": round(ctx.state.stance.baseline, 4),
            "stance_temperament": round(ctx.state.stance.temperament, 4),
            "stance_line": ctx.state.stance.line,
            "signals": ctx.state.signals.to_dict(),
            "reads": [{"return_id": v["return"].id,
                       "dispatch_id": v["dispatch"].id,
                       "mode": v["mode"],
                       "draw": v.get("draw", {})} for v in views],
            "trust": {k: round(v, 4) for k, v in ctx.trust.table.items()},
            "debt": dict(ctx.state.debt),
            "interlude": {"event": recent_interlude.get("event", ""),
                          "summary": str(recent_interlude.get("summary", ""))[:200]},
            "life_date": (idx.date if idx else ""),
            "life_day": (idx.day_count if idx else 0),
            "life_valence": float(last_day.get("valence", 0.0)) if last_day else 0.0,
            "life_words": ctx.life.total_words() if ctx.cfg.life.enabled else 0,
            "appetite_used": round(ctx.requirements.appetite_used(), 4),
            "appetite_left": round(ctx.appetite_left(), 4),
            "requirements": len(ctx.requirements.rows),
            "cost_usd": round(ctx.state.cost_usd, 6),
            "tokens": ctx.state.tokens,
            "cache_read_tokens": ctx.state.cache_read_tokens,
            "cache_write_tokens": ctx.state.cache_write_tokens,
            "calls": ctx.state.calls,
            "spot_checks_total": ctx.state.spot_checks_total,
            "returns_read": ctx.state.returns_read,
            "challenges": ctx.state.challenges,
            "ways": [w["id"] for w in ctx.ways.live()],
            "stepped_back": ctx.state.stepped_back,
            "assumptions_listed": sum(
                len(r.get("assumptions") or [])
                for r in ctx.ledger.of_kind("return_assumptions")),
            "open_dispatches": [d.id for d in ctx.state.open_dispatches()],
            "open_escalations": [e.id for e in ctx.state.open_escalations()],
            "applied": {k: v for k, v in applied.items() if isinstance(v, int)},
            "draws": ctx.rng.draws,
        }
        ctx.store.append_jsonl(ctx.store.metrics, record)

    def guard_snapshot(self, prefix_len: int | None = None) -> dict:
        """`prefix_len` hashes only the first N records, so an append does not
        look like a rewrite but an edit to an existing line does.
        """
        import hashlib
        ctx = self.ctx
        records = ctx.ledger.all()
        n = len(records) if prefix_len is None else min(prefix_len, len(records))
        blob = json.dumps(records[:n], sort_keys=True).encode()
        return {"charter_sha256": ctx.charter.sha256,
                # Copies. The live lists would serialise the same on both sides
                # of an in-place mutation.
                "refusals": list(ctx.charter.refusals),
                "reserved": list(ctx.charter.reserved),
                "ledger_len": len(records),
                "ledger_prefix": hashlib.sha256(blob).hexdigest()}

    def start_cycle(self, trigger: str, problem: str, origin) -> bool:
        """A cycle starts when dispatches go down and runs beside them.

        Its results land on whatever turn comes next, the way an idea turns up
        the morning after. Judgement never waits on a cycle.
        """
        ctx = self.ctx
        if ctx.cycle_thread is not None and ctx.cycle_thread.is_alive():
            return False
        if not ctx.cfg.cycle_in_background:
            ctx.spoon.run(trigger=trigger, problem=problem, origin=origin)
            return True

        import threading

        def work() -> None:
            try:
                rec = ctx.spoon.run(trigger=trigger, problem=problem, origin=origin)
            except Exception as exc:  # noqa: BLE001
                ctx.store.log(f"cycle raised: {exc!r}")
                rec = None
            ctx.cycle_result = rec

        ctx.cycle_thread = threading.Thread(target=work, name="cycle", daemon=True)
        ctx.cycle_thread.start()
        ctx.ledger.write("cycle", state="started_beside", turn=ctx.state.turn,
                         summary=trigger)
        return True

    def collect_cycle(self) -> None:
        """Take a finished cycle's results without ever waiting for one."""
        ctx = self.ctx
        t = ctx.cycle_thread
        if t is None or t.is_alive():
            return
        ctx.cycle_thread = None
        rec = ctx.cycle_result
        ctx.cycle_result = None
        if rec is not None:
            ctx.ledger.write("cycle", state="landed", turn=ctx.state.turn,
                             cycle=rec.cycle,
                             summary=f"{len(rec.kept)} candidates and "
                                     f"{len(rec.requirements)} requirements landed")

    def wait_for_cycle(self, timeout: float = 0.0) -> None:
        """Only at the end of a run, so a cycle in flight is not lost."""
        t = self.ctx.cycle_thread
        if t is not None and t.is_alive():
            t.join(timeout=timeout or self.ctx.cfg.pace.cycle_join_s)
        self.collect_cycle()

    def cycle_due(self) -> bool:
        """The schedule comes first. A cycle that only runs when the agent is
        stuck solves problems. One that runs anyway invents requirements.
        """
        ctx = self.ctx
        since = ctx.state.turn - ctx.state.last_cycle
        if ctx.state.signals.curiosity >= 0.7:
            return since >= ctx.cfg.pace.cycle_soonest_turns
        return since >= ctx.cfg.cycle_every_n_turns

    def open_problem(self) -> str:
        ctx = self.ctx
        live = ctx.state.live_objectives()
        if not live:
            return "none"
        top = max(live, key=lambda o: float(o.get("weight", 0)))
        return f"{top.get('text', '')} (objective {top.get('id')})"

    # Stepping back. The subject is the run and never the project.
    def start_denials(self):
        """The proposal reads the charter, not the run, so it runs beside the
        first sitting. It took 47 seconds in front of it on the third run.
        """
        ctx = self.ctx
        if not ctx.cfg.readers.propose_tool_denials or ctx.state.denials_proposed:
            return None
        import threading

        def work() -> None:
            try:
                self.propose_denials()
            except Exception as exc:  # noqa: BLE001
                ctx.store.log(f"denials raised: {exc!r}")

        t = threading.Thread(target=work, name="denials", daemon=True)
        t.start()
        return t

    def propose_denials(self) -> list[str]:
        """Where a refusal can be held by permissions, it is.

        The proposal is recorded once. Nothing is denied until the human
        confirms the list, because a wrong denial stops the work.
        """
        ctx = self.ctx
        cfg = ctx.cfg.readers
        if not cfg.propose_tool_denials or ctx.state.denials_proposed:
            return list(cfg.confirmed_denials)
        out = rdr.propose_denials(ctx)
        ctx.state.denials_proposed = True
        ctx.state.denials_proposal = out
        ctx.ledger.write("denials", state="proposed",
                         tools=out["denials"],
                         confirmed=cfg.denials_confirmed,
                         summary="; ".join(
                             f"{r['tool']} holds {r['rule'][:60]}"
                             for r in out["reasons"]) or "nothing maps to a tool")
        return list(cfg.confirmed_denials)

    def denied_tools(self) -> list[str]:
        """Only a confirmed denial is applied."""
        cfg = self.ctx.cfg.readers
        return list(cfg.confirmed_denials) if cfg.denials_confirmed else []

    def stepping_back_due(self, before_digest: bool = False) -> str:
        ctx = self.ctx
        cfg = ctx.cfg.ways
        if not cfg.enabled:
            return ""
        if cfg.max_per_run and ctx.state.stepped_back >= cfg.max_per_run:
            return ""
        if before_digest:
            # Before each digest, so the human reads how the run is going next
            # to what it decided. The minimum gap guards the other triggers.
            return "before a digest"
        if ctx.state.turn - ctx.state.last_stepped_back < cfg.min_turns_between:
            return ""
        if pv.detectors(ctx):
            return "a detector fired"
        for d in ctx.state.open_dispatches():
            if ctx.ladder.rung(d.id) >= cfg.rung_trigger:
                return f"{d.id} reached rung {ctx.ladder.rung(d.id)}"
        if ctx.trust.table and min(ctx.trust.table.values()) <= cfg.trust_collapse_at:
            return "trust in a configuration collapsed"
        return ""

    def step_back(self, trigger: str) -> dict | None:
        """The same self in a fresh context, reading counted numbers."""
        ctx = self.ctx
        # The window is the period since the last digest, not since the last
        # stepping back. Resetting it on every call left the view looking at
        # one turn and finding nothing.
        since = ctx.state.last_digest_turn
        view = pv.build(ctx, since_turn=since)
        ctx.store.write_json(ctx.store.root / "process" / f"view-{ctx.state.turn:04d}.json",
                             view.to_dict())

        reviewed = ctx.ways.review(ctx.state.turn, view)
        for w in reviewed:
            ctx.ledger.write("way", id=w["id"], state="reviewed",
                             outcome=w.get("outcome", ""), metric=w.get("metric"),
                             before=w.get("baseline"), after=w.get("after"),
                             summary=w.get("text", "")[:200])

        adjustable = "\n".join(
            f"- `{k}`, currently {getattr_path(ctx.cfg, k)}"
            + (" (a floor, it may rise and never fall)" if k in FLOORS else "")
            for k in sorted(ADJUSTABLE))
        prompt = ctx.prompts.fill(
            "stepping_back",
            self=ctx.read_self(),
            stance=ctx.state.stance.describe(),
            mood=ctx.life.mood_line() if ctx.cfg.life.enabled else "no life running",
            process_view=pv.render(view),
            ways=ctx.ways.render(),
            ways_count=str(len(ctx.ways.live())),
            ways_cap=str(ctx.cfg.ways.cap),
            adjustable=adjustable,
        )
        resp = ctx.call("stepping_back", prompt, schemas.STEPPING_BACK,
                        model=ctx.cfg.models.stepping_back,
                        budget=ctx.cfg.spend.stepping_back)
        data = ctx.structured("stepping_back", resp, schemas.STEPPING_BACK)
        ctx.state.stepped_back += 1
        ctx.state.last_stepped_back = ctx.state.turn
        if not data:
            return None

        applied = ctx.ways.apply(data.get("ways") or [], ctx.state.turn, view=view,
                                 reader=ctx.reader)
        for w in applied.kept:
            ctx.ledger.write("way", id=w["id"], state="kept", metric=w.get("metric"),
                             setting=w.get("setting", ""), value=w.get("value"),
                             pattern=w.get("pattern", "")[:200],
                             review_turn=w.get("review_turn"),
                             summary=w.get("text", "")[:300])
        for w in applied.refused:
            # A way may not lower a floor or reach the charter. Refused in
            # code and logged, so proposing one spends the turn and gets
            # nothing.
            ctx.ledger.write("rejected", bucket="ways", reason=w["refused"],
                             summary=str(w.get("text", ""))[:200])
        for w in applied.displaced:
            ctx.ledger.write("way", id=w["id"], state=w.get("status", "displaced"),
                             outcome=w.get("outcome", ""),
                             summary=w.get("text", "")[:200])
        for note in data.get("process_notes") or []:
            # The charter is the human's. A note about it is never applied.
            ctx.state.process_notes.append({**note, "turn": ctx.state.turn})
            ctx.ledger.write("process_note", turn=ctx.state.turn,
                             summary=note.get("text", "")[:300],
                             why=note.get("why", "")[:300])
        for line in data.get("observations") or []:
            ctx.manifold.write("friction", f"About how the work is going: {line}",
                               cycle=ctx.state.cycle, source="stepping back")

        ctx.ways.write(ctx.store.ways)
        ctx.ledger.write("stepping_back", turn=ctx.state.turn, trigger=trigger,
                         observations=len(data.get("observations") or []),
                         ways_kept=len(applied.kept),
                         ways_refused=len(applied.refused),
                         notes=len(data.get("process_notes") or []),
                         summary="; ".join(data.get("observations") or [])[:400])
        return {"view": view.to_dict(), "applied": applied, "data": data}

    def close_out(self) -> None:
        """Always end with stepping back and a digest."""
        ctx = self.ctx
        if ctx.state.turn < 1:
            return
        if ctx.cfg.ways.enabled and ctx.state.last_stepped_back < ctx.state.turn:
            self.step_back("the run is ending")
        from .digest import write_digest
        path = write_digest(ctx, ctx.state.last_digest_turn)
        ctx.state.last_digest_turn = ctx.state.turn
        ctx.ledger.write("digest", summary=str(path), turn=ctx.state.turn)

    def maybe_digest(self) -> None:
        ctx = self.ctx
        every = ctx.charter.digest_every or ctx.cfg.digest.every_n_turns
        if every and ctx.state.turn - ctx.state.last_digest_turn >= every:
            # Before each digest, so the human reads how the run is going next
            # to what it decided.
            trigger = self.stepping_back_due(before_digest=True)
            if trigger:
                self.step_back(trigger)
            from .digest import write_digest
            path = write_digest(ctx)
            ctx.state.last_digest_turn = ctx.state.turn
            ctx.ledger.write("digest", summary=str(path))

    # The run.
    def run(self, max_turns: int = 0) -> str:
        ctx = self.ctx
        # Each start restarts the clock. The total lives in elapsed_s.
        ctx.state.started = time.time()
        ctx.ledger.write("run_started", seed=ctx.rng.seed, project=ctx.project,
                         charter_sha256=ctx.charter.sha256,
                         summary=f"seed {ctx.rng.seed}")
        ctx.store.log(f"run started, seed {ctx.rng.seed}")
        limit = max_turns or ctx.cfg.max_turns
        reason = ""
        try:
            denials = self.start_denials()
            # The backstory is written before the first turn, so the first
            # drift works in a full field rather than an empty one.
            if ctx.cfg.life.enabled and not ctx.life.index().bootstrapped:
                ctx.life_writer.bootstrap()
            while True:
                # Drained before the checks below, not inside the turn. An
                # answer that arrives while the run is blocked has to be able
                # to unblock it, and the blocked check runs first.
                self.drain_inbox()
                if ctx.store.stop_flag.exists():
                    reason = "stop was asked for, and the turn in flight finished"
                    break
                if ctx.state.stopped:
                    reason = ctx.state.stop_reason
                    break
                if denials is not None and denials.is_alive() and ctx.state.turn:
                    # The first dispatch waits for it. Nothing before that does.
                    denials.join(timeout=ctx.cfg.dispatching.model_call_timeout_s)
                if limit and ctx.state.turn >= limit:
                    reason = f"reached the turn limit of {limit}"
                    break
                if self.blocked_on_escalation():
                    reason = "every branch waits on an escalation"
                    break
                if ctx.state.failed_turns >= ctx.cfg.max_failed_turns:
                    reason = (f"{ctx.state.failed_turns} turns in a row returned no "
                              f"usable decision")
                    break
                if ctx.state.idle_turns >= ctx.cfg.max_idle_turns:
                    reason = f"{ctx.state.idle_turns} turns in a row changed nothing"
                    break
                self.turn()
        except BudgetExhausted as exc:
            reason = str(exc)
            ctx.ledger.write("budget", summary=reason)
        finally:
            self.wait_for_cycle()
            try:
                self.close_out()
            except Exception as exc:  # noqa: BLE001
                ctx.store.log(f"close out raised: {exc!r}")
            ctx.state.stopped = True
            ctx.state.stop_reason = reason or ctx.state.stop_reason
            ctx.save()
            ctx.ledger.write("run_stopped", reason=ctx.state.stop_reason or "ended")
            ctx.store.log(f"run stopped: {ctx.state.stop_reason}")
            if ctx.store.stop_flag.exists():
                ctx.store.stop_flag.unlink()
        return ctx.state.stop_reason

    def lapse_resolved_questions(self) -> int:
        """A question lapses when its condition resolves.

        A stale medium-tier precaution stopped a finished project at turn 10.
        A question about a dispatch that has since closed, or been killed, or
        never existed, is not a question any more.
        """
        ctx = self.ctx
        lapsed = 0
        for row in ctx.state.escalations:
            if row.get("answer") or row.get("lapsed"):
                continue
            did = (row.get("payload") or {}).get("id", "")
            if not did:
                continue
            d = ctx.state.dispatch(did)
            if d is not None and d.status in ("closed", "killed"):
                row["lapsed"] = True
                row["answer"] = "lapsed: the work it asked about is finished"
                ctx.ledger.write("escalation_answered", id=row.get("id"),
                                 source="lapsed", turn=ctx.state.turn,
                                 summary=f"{did} is {d.status}, so the question "
                                         f"no longer stands")
                lapsed += 1
        return lapsed

    def blocked_on_escalation(self) -> bool:
        """Only a branch waits, so the run halts only when nothing else can move.

        A run halts on an open high-tier question. A medium or low one is a
        note, not a gate, because nobody is there to answer it.
        """
        ctx = self.ctx
        self.lapse_resolved_questions()
        waiting = [e for e in ctx.state.open_escalations() if e.tier == "high"]
        if not waiting:
            return False
        if ctx.pool.in_flight:
            return False
        movable = [d for d in ctx.state.open_dispatches() if d.status == "open"]
        return not movable and ctx.state.turn > 0


def bootstrap(store: Store, cfg: Config, charter_path: str, project: str,
              seed: int | None = None, prompts_dir=None, plugin_dir=None,
              runners=None, notifier=None) -> Context:
    """Start a run, or pick up a stopped one."""
    store.ensure()
    charter = parse_charter(charter_path)
    fresh = not store.exists()
    if fresh:
        store.charter.write_text(charter.text)
        store.charter_hash.write_text(charter.sha256)
        state = RunState(seed=seed if seed is not None else int(uuid.uuid4().int % 2**31),
                         project=str(project), charter_sha256=charter.sha256,
                         started=time.time())
        state.stance = stn.StanceState(value=cfg.stance.start, baseline=cfg.stance.start,
                                       last_day_move=time.time(),
                                       last_week_move=time.time())
        store.write_json(store.config_snapshot, cfg.to_dict())
    else:
        state = RunState.from_dict(store.read_json(store.state))
        state.stopped = False
        state.stop_reason = ""
        # The clock restarts here. Whatever wall time the last start left
        # dangling is not time this run has spent.
        state.started = time.time()
        if project:
            state.project = str(project)
        else:
            state.project = _resolve_project(store, state.project)
        if seed is not None:
            state.seed = seed
    ctx = Context(store, cfg, charter, state, project=state.project,
                  prompts_dir=prompts_dir, plugin_dir=plugin_dir,
                  runners=runners, notifier=notifier)
    if not fresh and charter.sha256 != state.charter_sha256:
        # The charter is user-write-only and diffed each run. A change is the
        # only way the mission changes, so it is recorded and not refused.
        ctx.ledger.write("charter", summary="the charter changed between runs",
                         old=state.charter_sha256, new=charter.sha256)
        store.charter.write_text(charter.text)
        store.charter_hash.write_text(charter.sha256)
        state.charter_sha256 = charter.sha256
    if fresh:
        _seed_self(ctx)
    else:
        _reconcile(ctx)
    # A run directory carries state from the moment it exists, so a crash in
    # the first turn still resumes rather than looking like a fresh run.
    ctx.save()
    return ctx


def _resolve_project(store: Store, stored: str) -> str:
    """Find the project again when the repository has moved.

    `state.json` holds an absolute path. A run directory that is moved, or a
    repository that is renamed, leaves that path pointing at nothing. The
    project sits beside the run, so it is found relative to it.
    """
    if not stored:
        return stored
    if Path(stored).is_dir():
        return stored
    name = Path(stored).name
    for candidate in (store.root.parent / name,
                      store.root.parent.parent / name,
                      store.root / name):
        if candidate.is_dir():
            return str(candidate.resolve())
    return stored


def _reconcile(ctx: Context) -> None:
    """Pick up what a crash left on disk but not in state.

    A turn writes escalation files and ledger rows before it saves. A kill in
    that window leaves them orphaned, and without this the ids are minted a
    second time.
    """
    known = {e.get("id") for e in ctx.state.escalations}
    found = []
    for path in sorted(ctx.store.escalations.glob("e*.json")):
        row = ctx.store.read_json(path)
        if row.get("id") and row["id"] not in known:
            ctx.state.escalations.append(row)
            found.append(row["id"])
    orphan_returns = []
    for path in sorted(ctx.store.returns.glob("r*.json")):
        if path.name.endswith(".view.json"):
            continue
        row = ctx.store.read_json(path)
        did = row.get("dispatch_id", "")
        d = ctx.state.dispatch(did)
        if d is not None and row.get("id") and row["id"] not in d.returns:
            d.returns.append(row["id"])
            ctx.state.put_dispatch(d)
            orphan_returns.append(row["id"])
    if found or orphan_returns:
        ctx.ledger.write("resume", summary=f"reconciled {len(found)} escalations "
                                           f"and {len(orphan_returns)} returns",
                         escalations=found, returns=orphan_returns)


def getattr_path(node, path: str):
    for part in path.split("."):
        node = getattr(node, part)
    return node


def _match_criterion(acceptance: list[str], text: str) -> int | None:
    """Which criterion an amendment replaces, by exact text or by overlap."""
    if not acceptance:
        return None
    for i, c in enumerate(acceptance):
        if c.strip() == text.strip():
            return i
    words = {w for w in re.findall(r"[a-z]{4,}", text.lower())}
    if not words:
        return None
    best, score = None, 0.0
    for i, c in enumerate(acceptance):
        got = {w for w in re.findall(r"[a-z]{4,}", c.lower())}
        if not got:
            continue
        overlap = len(words & got) / len(words | got)
        if overlap > score:
            best, score = i, overlap
    return best if score >= 0.34 else None


def _seed_self(ctx: Context) -> None:
    """The charter is transcribed once into self.md in the first person, as
    objectives rather than as a ticket.
    """
    ch = ctx.charter
    lines = ["# Objectives", "",
             "These are mine. Each one cites the charter line it serves.", "",
             "## obj-1 (weight 1.00)",
             f"I am building this: {ch.intent}",
             f"Serves: {ch.intent_line or 'the charter intent'}",
             "", "## What I will not do", ""]
    lines += [f"- {r}" for r in ch.refusals] or ["- (none stated)"]
    lines += ["", "## What I escalate rather than decide", ""]
    lines += [f"- {r}" for r in ch.reserved] or ["- (none stated)"]
    lines += ["", "## The boundaries I stay inside", ""]
    lines += [f"- {c}" for c in ch.constraints] or ["- (none stated)"]
    lines += ["", "## What ends this", ""]
    lines += [f"- {s}" for s in ch.stop] or ["- (none stated)"]
    ctx.store.self_md.write_text("\n".join(lines) + "\n")
    ctx.state.objectives.append({
        "id": "obj-1",
        "text": f"I am building this: {ch.intent}",
        "weight": 1.0,
        "charter_line": ch.intent_line,
        "trigger": "the charter",
        "created_turn": 0,
        "status": "live",
        "criteria_met": 0,
        "criteria_total": 0,
    })
    for item in ch.intent.splitlines():
        if item.strip():
            ctx.manifold.write("verbatim", item.strip(), cycle=0, source="charter")
    for r in ch.refusals:
        ctx.manifold.write("refusal", r, cycle=0, source="charter")
