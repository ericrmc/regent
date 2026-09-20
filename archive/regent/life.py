"""The agent's invented life.

Saturation needs volume. A bible, thirty days of backstory before the first
turn, then one day per simulated day, append-only.

The harness rolls what happens and the model writes the prose. The journal is
append-only, so everything before today is a stable prefix and the prompt cache
carries it.

Nothing in the life is evidence. It is fuel for Drift, a second anchor at most.
A life element's id begins with L, which is how the groundedness floor tells it
from a project element.
"""

from __future__ import annotations

import datetime
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from . import influence as infl
from . import lifetables, schemas


@dataclass
class Day:
    n: int
    date: str
    file: str
    words: int = 0
    valence: float = 0.0
    keywords: list[str] = field(default_factory=list)
    element_id: str = ""
    sitting: str = ""
    sitting_share: float = 1.0

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class LifeIndex:
    date: str = ""
    day_count: int = 0
    threads: list[str] = field(default_factory=list)
    days: list[dict] = field(default_factory=list)
    bible_words: int = 0
    seed_facts: dict = field(default_factory=dict)
    bootstrapped: bool = False
    has_stake: bool = False

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> LifeIndex:
        d = dict(d or {})
        known = {k: v for k, v in d.items() if k in cls.__dataclass_fields__}
        return cls(**known)


class LifeStore:
    """The life on disk.

    An owner is written once and reused across projects. Where `life.owner`
    names one, the bible and the journal live under `owners/<name>/` and a run
    starts at turn 1 instead of after seventy minutes of backstory.
    """

    def __init__(self, store, cfg) -> None:
        self.store = store
        self.cfg = cfg

    @property
    def root(self) -> Path:
        name = (self.cfg.life.owner or "").strip()
        if name:
            return Path(self.cfg.life.owners_dir).resolve() / name
        return self.store.root / "life"

    @property
    def bible_path(self) -> Path:
        return self.root / "bible.md"

    @property
    def journal(self) -> Path:
        return self.root / "journal"

    @property
    def index_path(self) -> Path:
        return self.root / "index.json"

    def ensure(self) -> None:
        self.journal.mkdir(parents=True, exist_ok=True)

    def index(self) -> LifeIndex:
        return LifeIndex.from_dict(self.store.read_json(self.index_path))

    def save_index(self, idx: LifeIndex) -> None:
        self.store.write_json(self.index_path, idx.to_dict())

    def bible(self) -> str:
        return self.bible_path.read_text() if self.bible_path.exists() else ""

    def day_text(self, day: dict) -> str:
        p = self.root / day["file"]
        return p.read_text() if p.exists() else ""

    def append_stake(self, text: str, threads: list[str]) -> None:
        """The bible is amended, never rewritten.

        The backstory is this person's life before the project began, so it
        stays valid. What is added is why they want the thing built.
        """
        self.ensure()
        with open(self.bible_path, "a") as fh:
            fh.write("\n\n" + text.strip() + "\n")
        idx = self.index()
        idx.bible_words = _words(self.bible())
        idx.has_stake = True
        for t in threads or []:
            t = str(t).strip()
            if t and t not in idx.threads:
                idx.threads.append(t)
        self.save_index(idx)

    def write_bible(self, text: str, threads: list[str], seed_facts: dict) -> None:
        self.ensure()
        self.bible_path.write_text(text)
        idx = self.index()
        idx.threads = list(threads)
        idx.bible_words = _words(text)
        idx.seed_facts = seed_facts
        if not idx.date:
            idx.date = self.cfg.life.start_date
        self.save_index(idx)

    def append_day(self, entry: str, valence: float, keywords: list[str],
                   thread_notes: list[str], sitting: str = "",
                   sitting_share: float = 1.0) -> Day:
        """Append-only. The date advances by one day per entry."""
        self.ensure()
        idx = self.index()
        n = idx.day_count + 1
        date = _advance(idx.date or self.cfg.life.start_date,
                        0 if n == 1 and not idx.day_count else 1) if idx.date else \
            self.cfg.life.start_date
        if idx.day_count:
            date = _advance(idx.date, 1)
        else:
            date = idx.date or self.cfg.life.start_date
        name = f"day-{n:04d}.md"
        (self.journal / name).write_text(f"# {date}\n\n{entry.strip()}\n")
        day = Day(n=n, date=date, file=f"journal/{name}", words=_words(entry),
                  valence=float(valence), keywords=list(keywords),
                  sitting=sitting, sitting_share=float(sitting_share))
        idx.days.append(day.to_dict())
        idx.day_count = n
        idx.date = date
        for note in thread_notes or []:
            note = str(note).strip()
            if note and note not in idx.threads:
                idx.threads.append(note)
        self.save_index(idx)
        return day

    def recent_days(self, n: int) -> list[dict]:
        return self.index().days[-n:] if n > 0 else []

    def total_words(self) -> int:
        return sum(int(d.get("words", 0)) for d in self.index().days)

    # Context assembly, by reader.
    def for_drift(self, model: str = "") -> str:
        """The bible and the most recent N words, whole, oldest first.

        Oldest first is deliberate. The journal is append-only, so assembling it
        in order makes everything before today a stable prefix the prompt cache
        can carry.
        """
        idx = self.index()
        window = int(self.cfg.life.window_by_model.get(model,
                                                       self.cfg.life.drift_window_words))
        chosen: list[dict] = []
        running = 0
        for day in reversed(idx.days):
            w = int(day.get("words", 0))
            if running + w > window and chosen:
                break
            chosen.append(day)
            running += w
        chosen.reverse()
        parts = []
        if self.bible_path.exists():
            parts.append("# The bible\n\n" + self.bible())
        for day in chosen:
            parts.append(f"## {day.get('element_id') or ''} {day['date']}\n\n"
                         + self.day_text(day))
        return "\n\n".join(parts).strip() or "(no life yet)"

    def for_judgement(self, days: int = 0) -> str:
        """The last two days. Judgement carries the residue of a life, not the
        archive.
        """
        days = self.recent_days(days or self.cfg.life.judgement_days)
        if not days:
            return "(no life yet)"
        return "\n\n".join(f"## {d['date']}\n\n{self.day_text(d)}" for d in days)

    def mood_line(self) -> str:
        days = self.recent_days(1)
        if not days:
            return "no mood recorded yet"
        v = float(days[0].get("valence", 0.0))
        if v <= -0.5:
            word = "a bad day behind it"
        elif v <= -0.15:
            word = "a flat day behind it"
        elif v < 0.15:
            word = "an ordinary day behind it"
        elif v < 0.5:
            word = "a decent day behind it"
        else:
            word = "a good day behind it"
        return f"{days[0]['date']}, {word} (valence {v:+.2f})"

    def last_valence(self) -> float:
        days = self.recent_days(1)
        return float(days[0].get("valence", 0.0)) if days else 0.0


def _words(text: str) -> int:
    return len((text or "").split())


def _advance(date: str, days: int) -> str:
    d = datetime.date.fromisoformat(date)
    return (d + datetime.timedelta(days=days)).isoformat()


class LifeWriter:
    """The calls that produce the life. One per bible, one per day."""

    def __init__(self, ctx) -> None:
        self.ctx = ctx

    @property
    def store(self) -> LifeStore:
        return self.ctx.life

    def bootstrap(self) -> int:
        """The bible, then the backstory, before the first turn."""
        cfg = self.ctx.cfg
        if not cfg.life.enabled:
            return 0
        idx = self.store.index()
        if idx.bootstrapped:
            return 0
        self.store.ensure()
        if not self.store.bible_path.exists():
            self.write_bible()
        # The bible says why this person wants the charter's thing built. An
        # existing bible is amended rather than rewritten, so a life already
        # under way keeps every day it has.
        if not self.store.index().has_stake:
            self.write_stake()
        written = 0
        target = cfg.life.backstory_days
        per_call = max(1, cfg.life.days_per_call)
        while self.store.index().day_count < target:
            left = target - self.store.index().day_count
            n = self.write_week(min(per_call, left))
            if not n:
                break
            written += n
        # self.md is his, written from the charter and the bible together.
        self.write_self()
        idx = self.store.index()
        idx.bootstrapped = True
        self.store.save_index(idx)
        self.ctx.ledger.write("life", state="bootstrapped", days=idx.day_count,
                              words=self.store.total_words(),
                              summary=f"bible plus {idx.day_count} days, "
                                      f"{self.store.total_words()} words")
        return written

    def write_bible(self) -> bool:
        ctx = self.ctx
        seed = lifetables.roll_bible_seed(ctx.rng)
        prompt = ctx.prompts.fill(
            "life_bible",
            seed_facts=json.dumps(seed, indent=2),
            word_target=str(ctx.cfg.life.bible_words),
        )
        resp = ctx.call("life_bible", prompt, schemas.LIFE_BIBLE,
                        model=ctx.cfg.models.life_writer,
                        budget=ctx.cfg.spend.life_bible,
                        runner_role="life_writer")
        data = ctx.structured("life_bible", resp, schemas.LIFE_BIBLE)
        if not data or not (data.get("bible") or "").strip():
            # Without a bible the days have nothing to be continuous with, so
            # the seed itself becomes one rather than leaving the life empty.
            text = _fallback_bible(seed)
            self.store.write_bible(text, seed["open_threads"], seed)
            ctx.ledger.write("life", state="bible", summary="the writer failed, "
                                                            "the rolled facts became the bible")
            return False
        threads = data.get("threads") or seed["open_threads"]
        self.store.write_bible(data["bible"], threads, seed)
        ctx.ledger.write("life", state="bible", words=_words(data["bible"]),
                         summary=f"{seed['name']}, {seed['occupation']}, {seed['city']}")
        return True

    def write_stake(self) -> bool:
        """Why this person wants the thing built. Appended to the bible."""
        ctx = self.ctx
        if not self.store.bible_path.exists():
            return False
        prompt = ctx.prompts.fill(
            "life_stake",
            bible=self.store.bible(),
            intent=ctx.charter.intent,
            constraints="\n".join(f"- {c}" for c in ctx.charter.constraints) or "(none)",
            word_target=str(ctx.cfg.life.stake_words),
        )
        resp = ctx.call("life_stake", prompt, schemas.LIFE_STAKE,
                        model=ctx.cfg.models.life_writer,
                        budget=ctx.cfg.spend.life_bible,
                        runner_role="life_writer")
        data = ctx.structured("life_stake", resp, schemas.LIFE_STAKE)
        if not data or not (data.get("stake") or "").strip():
            ctx.ledger.write("life", state="stake_failed",
                             summary="the writer returned no stake")
            return False
        self.store.append_stake(data["stake"], data.get("threads") or [])
        ctx.manifold.write("verbatim", data["stake"].strip()[:1200], cycle=0,
                           source="the bible", synthetic=True)
        ctx.ledger.write("life", state="stake", words=_words(data["stake"]),
                         summary=data["stake"].strip().splitlines()[-1][:200])
        return True

    def write_self(self) -> bool:
        """self.md in his voice, from the charter and the bible."""
        ctx = self.ctx
        ch = ctx.charter
        prompt = ctx.prompts.fill(
            "self_md",
            bible=self.store.bible() or "(none)",
            intent=ch.intent,
            constraints="\n".join(f"- {c}" for c in ch.constraints) or "(none)",
            refusals="\n".join(f"- {r}" for r in ch.refusals) or "(none)",
            reserved="\n".join(f"- {r}" for r in ch.reserved) or "(none)",
            stop="\n".join(f"- {r}" for r in ch.stop) or "(none)",
        )
        resp = ctx.call("self_md", prompt, schemas.SELF_MD,
                        model=ctx.cfg.models.life_writer,
                        budget=ctx.cfg.spend.life_bible,
                        runner_role="life_writer")
        data = ctx.structured("self_md", resp, schemas.SELF_MD)
        if not data or not (data.get("self_md") or "").strip():
            return False
        ctx.store.self_md.write_text(data["self_md"].strip() + "\n")
        for row in data.get("objectives") or []:
            oid = row.get("id") or f"obj-{len(ctx.state.objectives) + 1}"
            if ctx.state.objective(oid):
                continue
            ctx.state.objectives.append({
                "id": oid, "text": row.get("text", ""),
                "weight": float(row.get("weight", 0.5)),
                "charter_line": row.get("charter_line", ""),
                "trigger": "the charter, read in his own words",
                "created_turn": 0, "status": "live",
                "criteria_met": 0, "criteria_total": 0,
            })
        ctx.ledger.write("life", state="self",
                         summary=f"self.md written in his voice, "
                                 f"{len(data.get('objectives') or [])} objectives")
        return True

    def write_week(self, days: int) -> int:
        """A week to a call. Thirty days is five calls, not thirty.

        Seventy minutes of backstory in series is the single largest cost the
        first run paid, and none of it was the work.
        """
        ctx = self.ctx
        cfg = ctx.cfg
        if days <= 1:
            return 1 if self.write_day(backstory=True) else 0
        idx = self.store.index()
        plans = []
        for _ in range(days):
            plans.append(lifetables.roll_day(ctx.rng, idx.threads))
        target = ctx.rng.randint(cfg.life.day_words_min, cfg.life.day_words_max)
        recent = self.store.recent_days(1)
        recent_text = "\n\n".join(f"## {d['date']}\n\n{self.store.day_text(d)}"
                                  for d in recent) or "(this is the first day)"
        start = _advance(idx.date or cfg.life.start_date, 1) if idx.day_count \
            else (idx.date or cfg.life.start_date)
        prompt = ctx.prompts.fill(
            "life_week",
            bible=self.store.bible() or "(none yet)",
            recent_days=recent_text,
            start_date=start,
            days=str(days),
            day_plans=json.dumps(plans, indent=2),
            foreign_text=self._foreign_text() or "none",
            signals=ctx.state.signals.line(),
            word_target=str(target),
        )
        resp = ctx.call("life_week", prompt, schemas.LIFE_WEEK,
                        model=ctx.cfg.models.life_writer,
                        budget=ctx.cfg.spend.life_day,
                        runner_role="life_writer")
        data = ctx.structured("life_week", resp, schemas.LIFE_WEEK)
        entries = (data or {}).get("entries") or []
        if not entries:
            ctx.ledger.write("life", state="week_failed",
                             summary="the writer returned no entries")
            return 0
        written = 0
        for i, row in enumerate(entries[:days]):
            text = (row.get("entry") or "").strip()
            if not text:
                continue
            day = self.store.append_day(
                text, row.get("valence", plans[i]["mood_valence"]),
                row.get("keywords") or [], row.get("thread_notes") or [])
            el = ctx.manifold.write("life", text, cycle=ctx.state.cycle,
                                    source=f"life day {day.n}", synthetic=True,
                                    meta={"day": day.n, "date": day.date,
                                          "valence": day.valence,
                                          "keywords": day.keywords,
                                          "plan": plans[i]})
            idx2 = self.store.index()
            for r in idx2.days:
                if r["n"] == day.n:
                    r["element_id"] = el.id
            self.store.save_index(idx2)
            written += 1
        ctx.ledger.write("life", state="week", days=written,
                         words=sum(len((e.get("entry") or "").split())
                                   for e in entries[:days]),
                         summary=f"{written} days in one call")
        return written

    def write_day(self, backstory: bool = False) -> bool:
        ctx = self.ctx
        cfg = ctx.cfg
        idx = self.store.index()
        # The backstory is the life before the project began, so no backstory
        # day carries it.
        weight = 0.0
        if not backstory:
            weight = (cfg.life.project_day_weight_after_bad_return
                      if ctx.state.last_return_was_bad
                      else cfg.life.project_day_weight)
        plan = lifetables.roll_day(ctx.rng, idx.threads, project_weight=weight)
        # Folded in with no mark. What the writer receives is indistinguishable
        # from what the dice gave it.
        taken = self._fold_influence(plan)
        target = ctx.rng.randint(cfg.life.day_words_min, cfg.life.day_words_max)
        # One day in ten runs long, the way a person sometimes writes a page.
        if cfg.life.long_day_in and ctx.rng.chance(1.0 / cfg.life.long_day_in):
            target = cfg.life.long_day_words
        foreign, foreign_inf = self._foreign_text_with_influence()
        recent = self.store.recent_days(2)
        recent_text = "\n\n".join(f"## {d['date']}\n\n{self.store.day_text(d)}"
                                  for d in recent) or "(this is the first day)"
        next_date = _advance(idx.date or cfg.life.start_date, 1) if idx.day_count \
            else (idx.date or cfg.life.start_date)
        material = self._project_material() if plan.get("project_today") else ""
        prompt = ctx.prompts.fill(
            "life_day",
            project_material=material or "none",
            project_share="a quarter of the words"
            if material else "none of the words",
            bible=self.store.bible() or "(none yet)",
            recent_days=recent_text,
            date=next_date,
            day_plan=json.dumps(plan, indent=2),
            threads_today=json.dumps(plan["threads_today"], indent=2)
            if plan["threads_today"] else "(none today)",
            foreign_text=foreign or "none",
            signals=ctx.state.signals.line(),
            word_target=str(target),
        )
        resp = ctx.call("life_day", prompt, schemas.LIFE_DAY,
                        model=ctx.cfg.models.life_writer,
                        budget=ctx.cfg.spend.life_day,
                        runner_role="life_writer")
        data = ctx.structured("life_day", resp, schemas.LIFE_DAY)
        if not data or not (data.get("entry") or "").strip():
            ctx.ledger.write("life", state="day_failed",
                             summary="the writer returned nothing")
            return False
        day = self.store.append_day(
            data["entry"], data.get("valence", plan["mood_valence"]),
            data.get("keywords") or [], data.get("thread_notes") or [],
            sitting=plan.get("sitting", ""),
            sitting_share=plan.get("sitting_share", 1.0))
        offered = [m["id"] for m in self._offered] if material else []
        if material:
            # The harness records what was offered, so the passage is
            # traceable to what he actually saw.
            ctx.ledger.write("life", state="project_day", day=day.n,
                             offered=offered,
                             drew_on=[i for i in (data.get("project_ids") or [])
                                      if i in offered],
                             turn=ctx.state.turn,
                             summary=f"day {day.n} has the project in it")

        # The day enters the manifold with a life id, so Replay can bring it
        # back and Drift can cite it as a second anchor.
        el = ctx.manifold.write("life", data["entry"], cycle=ctx.state.cycle,
                                source=f"life day {day.n}", synthetic=True,
                                meta={"day": day.n, "date": day.date,
                                      "valence": day.valence,
                                      "keywords": day.keywords,
                                      "plan": plan})
        taken += foreign_inf
        for inf in taken:
            # The element id is how a later drift link is traced back, and it
            # is recorded only in the influence file.
            ctx.influence.take(inf, ctx.state.turn, day=day.n,
                               element_ids=[el.id])
        idx = self.store.index()
        for row in idx.days:
            if row["n"] == day.n:
                row["element_id"] = el.id
        self.store.save_index(idx)

        if not backstory:
            # The day's valence moves the stance baseline by a bounded amount.
            self._bleed_out(day.valence)
            ctx.ledger.write("life", state="day", day=day.n, date=day.date,
                             valence=round(day.valence, 3), words=day.words,
                             element_id=el.id,
                             summary=", ".join(plan["events"])[:200])
        return True

    def _bleed_out(self, valence: float) -> None:
        """A bad night makes a risk-weighted morning."""
        cfg = self.ctx.cfg
        step = cfg.life.valence_baseline_step * max(-1.0, min(1.0, valence))
        lo, hi = cfg.stance.bounds
        st = self.ctx.state.stance
        st.baseline = max(lo, min(hi, st.baseline + step))

    def _fold_influence(self, plan: dict) -> list:
        """Plants and voices join the rolled plan as ordinary material.

        Nothing here marks them. A key named for the channel would be read by
        the writer, and the owner would know.
        """
        ctx = self.ctx
        if not ctx.cfg.influence.enabled:
            return []
        taken = []
        for inf in ctx.influence.pending(infl.PLANT):
            infl.check_surface(infl.PLANT, "life")
            plan.setdefault("events", []).append(inf.text)
            taken.append(inf)
        for inf in ctx.influence.pending(infl.VOICE):
            infl.check_surface(infl.VOICE, "life")
            plan.setdefault("said_today", []).append(
                {"who": inf.subject, "says": inf.text})
            taken.append(inf)
        return taken

    def _project_material(self) -> str:
        """Only what he actually saw.

        The cut views the attention filter gave him and his own spot-check
        findings. Never source, never the stored whole return.
        """
        ctx = self.ctx
        self._offered: list[dict] = []
        parts: list[str] = []
        views = sorted(ctx.store.returns.glob("*.view.json"))[-3:]
        for path in views:
            row = ctx.store.read_json(path)
            text = (row.get("view") or "").strip()
            if not text:
                continue
            rid = row.get("return_id", path.stem)
            self._offered.append({"id": rid, "kind": "report"})
            parts.append(f"### {rid}, a report he read on a "
                         f"{row.get('mode', 'glance')}\n\n{text}")
        for f in ctx.state.spot_check_findings[-2:]:
            self._offered.append({"id": f.get("id", ""), "kind": "spot check"})
            parts.append(f"### {f.get('id')}, what he found looking himself\n\n"
                         f"Question: {f.get('question', '')}\n"
                         f"{f.get('findings', '')}")
        return "\n\n".join(parts)

    def _foreign_text_with_influence(self) -> tuple[str, list]:
        """Real external text to fold in, the same material Foreign reading
        pulls. Not every day gets one.

        A `reading` influence is the human handing over a text. It arrives as
        any other foreign material does.
        """
        ctx = self.ctx
        if ctx.cfg.influence.enabled:
            for inf in ctx.influence.pending(infl.READING):
                infl.check_surface(infl.READING, "foreign")
                return inf.text, [inf]
        return self._foreign_text(), []

    def _foreign_text(self) -> str:
        if not self.ctx.rng.chance(0.35):
            return ""
        foreign = [e for e in self.ctx.manifold.warm() if e.texture == "foreign"]
        if foreign:
            return self.ctx.rng.choice(foreign).text
        from . import corpus
        return corpus.draw_foreign(self.ctx.rng)["text"]


def _fallback_bible(seed: dict) -> str:
    lines = [f"# {seed['name']}", "",
             f"{seed['name']} is {seed['age']}, {seed['occupation']}, in {seed['city']}.",
             f"{seed['name'].split()[0]} {seed['household']}.", "",
             "## What happened", "", seed["upheaval"], "",
             "## People", ""]
    lines += [f"- {r}" for r in seed["relationships"]]
    lines += ["", "## Places", ""]
    lines += [f"- {p}" for p in seed["places"]]
    lines += ["", "## Open threads", ""]
    lines += [f"- {t}" for t in seed["open_threads"]]
    return "\n".join(lines)
