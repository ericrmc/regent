"""Adopting a life out of a run, so an owner is written once and reused.

The first run spent about seventy minutes writing thirty days of finished
prose before turn 1, and none of it was the work. An owner lives under
`owners/<name>/` after this, and a later run starts at turn 1.

The long originals are kept beside the journal. What loads a drift pass is
events, objects, people and unfinished business per word, and the journal form
carries more of those per word, but the prose is what the journal was made from
and it is not thrown away.
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from . import disposition as disp
from . import lifetables, schemas


@dataclass
class Adoption:
    name: str = ""
    root: str = ""
    days: int = 0
    condensed: int = 0
    words_before: int = 0
    words_after: int = 0
    kept: list = field(default_factory=list)
    cost_usd: float = 0.0

    def to_dict(self) -> dict:
        return {"name": self.name, "root": self.root, "days": self.days,
                "condensed": self.condensed, "words_before": self.words_before,
                "words_after": self.words_after,
                "kept": self.kept[:40], "cost_usd": round(self.cost_usd, 6)}


def adopt(ctx, name: str, owners_dir: str | Path, per_call: int = 7,
          word_target: int = 200) -> Adoption:
    """Copy a run's life into `owners/<name>/` and condense it once."""
    src = ctx.life.root
    dest = Path(owners_dir).resolve() / name
    if not src.exists():
        raise FileNotFoundError(f"no life at {src}")
    dest.mkdir(parents=True, exist_ok=True)
    if src.resolve() != dest.resolve():
        shutil.copytree(src, dest, dirs_exist_ok=True)

    out = Adoption(name=name, root=str(dest))
    index = json.loads((dest / "index.json").read_text())
    days = index.get("days") or []
    out.days = len(days)
    if not days:
        return out

    long_dir = dest / "journal" / "long"
    long_dir.mkdir(parents=True, exist_ok=True)

    todo = []
    for day in days:
        path = dest / day["file"]
        if not path.exists():
            continue
        text = path.read_text()
        body = text.split("\n\n", 1)[-1].strip()
        # The original is kept beside the journal, not thrown away.
        keep = long_dir / Path(day["file"]).name
        if not keep.exists():
            keep.write_text(text)
        todo.append({"day": day, "path": path, "date": day["date"], "text": body})
        out.words_before += len(body.split())

    for start in range(0, len(todo), per_call):
        batch = todo[start:start + per_call]
        prompt = ctx.prompts.fill(
            "life_condense",
            entries=json.dumps([{"date": b["date"], "text": b["text"]}
                                for b in batch], indent=2),
            word_target=str(word_target),
        )
        resp = ctx.call("life_condense", prompt, schemas.LIFE_CONDENSE,
                        model=ctx.cfg.models.life_condense,
                        budget=ctx.cfg.spend.life_day,
                        runner_role="life_condense")
        out.cost_usd += resp.cost_usd
        data = ctx.structured("life_condense", resp, schemas.LIFE_CONDENSE)
        entries = (data or {}).get("entries") or []
        for item, row in zip(batch, entries, strict=False):
            entry = (row.get("entry") or "").strip()
            if not entry:
                continue
            item["path"].write_text(f"# {item['date']}\n\n{entry}\n")
            item["day"]["words"] = len(entry.split())
            out.words_after += item["day"]["words"]
            out.condensed += 1
            out.kept += list(row.get("kept") or [])

    index["days"] = [b["day"] for b in todo]
    (dest / "index.json").write_text(json.dumps(index, indent=2,
                                                ensure_ascii=False))
    return out


def render(a: Adoption) -> str:
    if not a.days:
        return f"{a.name}: no life to adopt"
    shrink = (1 - a.words_after / a.words_before) if a.words_before else 0
    return (f"{a.name}: {a.condensed} of {a.days} days condensed, "
            f"{a.words_before} words to {a.words_after}, "
            f"{shrink:.0%} smaller. The originals are under "
            f"journal/long/. {a.root}")


def read_disposition(ctx, description: str, times: int = 0) -> disp.Reading:
    """Read the same prose several times and take the median per dial.

    A reading is a sample and not a measurement. Two readings of one regent
    minutes apart disagreed on five of seven dials and one changed sign.
    """
    times = times or ctx.cfg.readers.disposition_samples
    prompt = ctx.prompts.fill("disposition", description=description)
    samples, reasons = [], []
    cost = 0.0
    for _ in range(max(1, times)):
        resp = ctx.call("disposition", prompt, schemas.DISPOSITION,
                        model=ctx.cfg.models.disposition,
                        budget=ctx.cfg.spend.reader, runner_role="disposition")
        cost += resp.cost_usd
        data = ctx.structured("disposition", resp, schemas.DISPOSITION)
        if not data:
            continue
        samples.append(dict(data.get("dials") or {}))
        reasons.append(dict(data.get("reasons") or {}))
    if not samples:
        return disp.Reading()
    reading = disp.combine(samples, reasons)
    reading.cost_usd = cost
    return reading


def describe_from_life(ctx, limit_days: int = 8) -> str:
    """What an existing owner's own bible and journal say about them."""
    parts = []
    bible = ctx.life.bible()
    if bible:
        parts.append(bible[:6000])
    for day in ctx.life.recent_days(limit_days):
        parts.append(f"## {day['date']}\n\n{ctx.life.day_text(day)}")
    return "\n\n".join(parts).strip()


def cast(ctx, pins: list[str] | None = None, candidates: int = 1) -> list[dict]:
    """Roll one or more regents. The human pins a few facts, the dice do the rest.

    Nothing is written here. A candidate is a proposal with its paragraph and
    its dials, and the caller picks one.
    """
    pinned, words = disp.parse_pins(pins or [])
    out = []
    for _ in range(max(1, candidates)):
        seed = lifetables.roll_bible_seed(ctx.rng)
        for key, value in (pinned.get("facts") or {}).items():
            if key in seed:
                seed[key] = value
        d = disp.roll(ctx.rng, pinned.get("traits") or {})
        reading = None
        if words:
            # A pin can be a word, and a reader turns it into dial settings
            # once, read the same three times as any other.
            reading = read_disposition(ctx, ", ".join(words))
            read = reading.disposition()
            for t in disp.TRAITS:
                if t not in (pinned.get("traits") or {}):
                    setattr(d, t, getattr(read, t))
            d.reasons = read.reasons
            d.pinned = sorted(set(d.pinned) | set(words))
        out.append({"seed": seed, "disposition": d, "reading": reading,
                    "paragraph": paragraph(seed, d)})
    return out


def paragraph(seed: dict, d: disp.Disposition) -> str:
    """One paragraph a person can choose from."""
    name = seed.get("name", "someone")
    return (f"{name}, {seed.get('age')}, {seed.get('occupation')} in "
            f"{seed.get('city')}. {name.split()[0]} {seed.get('household')}. "
            f"{seed.get('upheaval').capitalize()}. "
            f"Open: {'; '.join(seed.get('open_threads', [])[:2])}. "
            f"To work for: {d.describe()}.")


def disposition_command(ctx, name: str, owners_dir: str, apply: bool = False,
                        reread: bool = False) -> tuple[int, str]:
    """Read and show, or store exactly what a reading showed.

    `apply` never reads again. Approval has to mean the numbers that were on
    the screen, and a reading taken twice does not give them twice.
    """
    import json as _json

    from . import disposition as disp

    ctx.cfg.life.owner = name
    ctx.cfg.life.owners_dir = owners_dir
    root = ctx.life.root
    shown_path = root / "disposition.reading.json"
    stored = root / "disposition.json"

    if apply:
        if not shown_path.exists():
            return 1, ("nothing has been read yet. Run it without --apply "
                       "first, look at the numbers, then apply them.")
        reading = disp.Reading(**ctx.store.read_json(shown_path))
        d = reading.disposition()
        stored.parent.mkdir(parents=True, exist_ok=True)
        stored.write_text(_json.dumps(d.to_dict(), indent=2))
        return 0, (disp.render(d, disp.apply(d, ctx.cfg), reading)
                   + f"\n\nstored exactly as shown, to {stored}"
                   + "\nIt is fixed until someone asks for a new reading.")

    if stored.exists() and not reread:
        d = disp.Disposition.from_dict(ctx.store.read_json(stored))
        return 0, (disp.render(d, disp.apply(d, ctx.cfg))
                   + f"\n\nalready stored at {stored}. "
                   + "Pass --reread to take a new reading.")

    description = describe_from_life(ctx)
    if not description:
        return 1, f"no life for {name} under {owners_dir}"
    reading = read_disposition(ctx, description)
    if not reading.samples:
        return 1, "the reader returned nothing"
    d = reading.disposition()
    ctx.store.write_json(shown_path, reading.to_dict())
    return 0, (disp.render(d, disp.apply(d, ctx.cfg), reading)
               + "\n\nNothing stored. `--apply` keeps exactly these numbers "
               + f"({reading.cost_usd:.4f} USD to read).")
