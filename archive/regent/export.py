"""One file holding how a run went, for a reader who was not there.

Everything here is read back off disk. Nothing is derived, inferred or filled
in. A value the run did not record is absent from the export rather than
guessed at, because a review page built on a guessed number is worse than one
with a gap in it.
"""

from __future__ import annotations

import json
from pathlib import Path

from .charter import parse_charter
from .config import Config
from .ledger import Ledger
from .life import LifeStore
from .requirements import Register
from .state import RunState
from .store import Store

VERSION = 1


def build_export(root: str | Path, cfg: Config | None = None) -> dict:
    store = Store(root)
    if not store.state.exists():
        raise FileNotFoundError(f"no run state in {store.root}")
    cfg = cfg or Config.load(None)
    if store.config_snapshot.exists():
        # The run's own config, so the export reflects what actually ran.
        cfg = Config.load(None)
        _merge_snapshot(cfg, store.read_json(store.config_snapshot))

    state = RunState.from_dict(store.read_json(store.state))
    ledger = Ledger(store)
    rows = ledger.all()
    register = Register(cfg, state.requirements)
    life = LifeStore(store, cfg)

    out: dict = {
        "export_version": VERSION,
        "run": {
            "root": str(store.root),
            "project": state.project,
            "seed": state.seed,
            "draws": state.draws,
            "turns": state.turn,
            "cycles": state.cycle,
            "calls": state.calls,
            "cost_usd": round(state.cost_usd, 6),
            "tokens": state.tokens,
            "cache_read_tokens": state.cache_read_tokens,
            "cache_write_tokens": state.cache_write_tokens,
            "stopped": state.stopped,
            "stop_reason": state.stop_reason,
            "started": state.started,
            "returns_read": state.returns_read,
            "spot_checks_total": state.spot_checks_total,
            "challenges": state.challenges,
            "stepped_back": state.stepped_back,
            "models": _models(cfg),
        },
        "charter": _charter(store),
        "objectives": list(state.objectives),
        "series": store.read_jsonl(store.metrics),
        "decisions": _decisions(rows),
        "amendments": _amendments(rows),
        "requirements": register.to_list(),
        "spot_checks": _spot_checks(store, rows),
        "cycles": _cycles(store),
        "dispatches": _dispatches(state, store),
        "escalations": list(state.escalations),
        "trust_events": [_pick(r, ("seq", "iso", "turn", "key", "trust", "outcome",
                                   "source", "return_id", "spot_check_id"))
                         for r in rows if r.get("kind") == "trust"],
        "read_modes": [_pick(r, ("seq", "iso", "turn", "return_id", "dispatch_id",
                                 "read_mode", "forced", "score", "inputs", "branch",
                                 "audit_due"))
                       for r in rows if r.get("kind") == "read_mode"],
        "challenges": [_pick(r, ("seq", "iso", "turn", "dispatch_id", "assumption",
                                 "question", "answer", "outcome"))
                       for r in rows if r.get("kind") == "challenge"],
        "queries": [_pick(r, ("seq", "iso", "turn", "dispatch_id", "question",
                              "outcome", "summary"))
                    for r in rows if r.get("kind") == "query"],
        "assumptions": [_pick(r, ("seq", "iso", "turn", "return_id", "dispatch_id",
                                  "assumptions"))
                        for r in rows if r.get("kind") == "return_assumptions"],
        "audits": [_pick(r, ("seq", "iso", "return_id", "dispatch_id", "outcome",
                             "trust", "summary"))
                   for r in rows if r.get("kind") == "audit"],
        "interludes": [_pick(r, ("seq", "iso", "event", "summary", "day", "date",
                                 "valence", "delta", "stance", "element_id"))
                       for r in rows if r.get("kind") == "interlude"],
        "rejections": [_pick(r, ("seq", "iso", "bucket", "role", "reason", "matched",
                                 "summary"))
                       for r in rows if r.get("kind") == "rejected"],
        "ways": list(state.ways),
        "process_notes": list(state.process_notes),
        "stepping_back": [_pick(r, ("seq", "iso", "turn", "trigger", "observations",
                                    "ways_kept", "ways_refused", "notes", "summary"))
                          for r in rows if r.get("kind") == "stepping_back"],
        "way_events": [_pick(r, ("seq", "iso", "turn", "id", "state", "outcome",
                                 "metric", "before", "after", "setting", "value",
                                 "pattern", "review_turn", "summary"))
                       for r in rows if r.get("kind") == "way"],
        "process_views": _process_views(store),
        "calls": [_pick(r, ("seq", "turn", "role", "model", "started", "ended",
                            "seconds", "tokens", "cost_usd", "blocking",
                            "dispatch_id", "error"))
                  for r in rows if r.get("kind") == "call"],
        "readings": [_pick(r, ("seq", "iso", "turn", "dispatch_id", "findings",
                               "unsure", "escalated_to_mid", "discarded",
                               "summary"))
                     for r in rows if r.get("kind") == "reading"],
        "tool_denials": {"proposed": state.denials_proposal,
                         "confirmed": list(cfg.readers.confirmed_denials),
                         "applied": cfg.readers.denials_confirmed},
        # Human only. No model call has read any of this.
        "influence": _influence(store, state, cfg),
        "life": _life(life, cfg),
        "digest": _digest(store),
        "ledger_kinds": _counts(rows),
    }
    return out


def _merge_snapshot(cfg: Config, data: dict) -> None:
    from .config import _merge
    try:
        _merge(cfg, data)
    except ValueError:
        # A snapshot from an older build may name a key this one dropped. The
        # export is still worth producing.
        pass


def _models(cfg: Config) -> dict:
    return {k: v for k, v in vars(cfg.models).items()}


def _charter(store: Store) -> dict:
    if not store.charter.exists():
        return {}
    ch = parse_charter(store.charter)
    return {
        "text": ch.text,
        "sha256": ch.sha256,
        "intent": ch.intent,
        "intent_line": ch.intent_line,
        "constraints": ch.constraints,
        "refusals": ch.refusals,
        "reserved": ch.reserved,
        "stop": ch.stop,
        "appetite": ch.appetite,
        "budget": ch.budget.to_dict(),
        "digest_every": ch.digest_every,
    }


def _decisions(rows: list[dict]) -> list[dict]:
    out = []
    for r in rows:
        if r.get("kind") == "decision":
            out.append(_pick(r, ("seq", "iso", "turn", "summary", "dispatched",
                                 "judged", "amended", "escalated", "invented",
                                 "rejected")))
        elif r.get("kind") == "judgement":
            out.append(_pick(r, ("seq", "iso", "return_id", "dispatch_id", "outcome",
                                 "read_mode", "summary")) | {"kind": "judgement"})
        elif r.get("kind") == "dispatch":
            out.append(_pick(r, ("seq", "iso", "dispatch_id", "tier", "objective_id",
                                 "summary", "resumed")) | {"kind": "dispatch"})
    return out


def _amendments(rows: list[dict]) -> list[dict]:
    return [_pick(r, ("seq", "iso", "dispatch_id", "direction", "trigger", "summary"))
            for r in rows if r.get("kind") == "amendment"]


def _spot_checks(store: Store, rows: list[dict]) -> list[dict]:
    out = []
    for path in sorted(store.spot_checks.glob("s*.json")):
        f = store.read_json(path)
        out.append({
            "id": f.get("id"),
            "turn": f.get("turn"),
            "trigger": f.get("trigger"),
            "dispatch_id": f.get("dispatch_id"),
            "return_id": f.get("return_id"),
            "question": f.get("question"),
            "findings": f.get("findings"),
            "verdicts": f.get("verdicts"),
            "gap": f.get("gap"),
            "openings": f.get("openings"),
            "claims": _claims_for(store, f.get("return_id", "")),
        })
    return out


def _claims_for(store: Store, return_id: str) -> dict:
    """What the return said, so a reader can set the findings against it."""
    if not return_id:
        return {}
    path = store.returns / f"{return_id}.json"
    if not path.exists():
        return {}
    r = store.read_json(path)
    return {"headline": r.get("headline", ""),
            "recommendation": r.get("recommendation", ""),
            "flags": r.get("flags", []),
            "evidence": r.get("evidence", [])}


def _cycles(store: Store) -> list[dict]:
    out = []
    for path in sorted(store.cycles.glob("cycle-*.json")):
        c = store.read_json(path)
        out.append({
            "cycle": c.get("cycle"),
            "trigger": c.get("trigger"),
            "problem": c.get("problem"),
            "origin": c.get("origin", {}),
            "motifs": c.get("motifs", []),
            "tensions": c.get("tensions", []),
            "questions": c.get("questions", []),
            "link_count": len(c.get("links", [])),
            "links": [{"kind": link.get("kind"), "text": link.get("text"),
                       "anchors": link.get("anchors"),
                       "mechanism": link.get("mechanism"),
                       "life_anchors": link.get("life_anchors", []),
                       "ingredients": link.get("ingredients"),
                       "model": link.get("model"), "pass": link.get("pass_index")}
                      for link in c.get("links", [])],
            "stops": c.get("stops", []),
            "scored": c.get("scored", []),
            "candidates": c.get("candidates", []),
            "kept": c.get("kept", []),
            "requirements": c.get("requirements", []),
            "gated_out": c.get("gated_out", []),
            "cost_usd": c.get("cost_usd"),
            "died_at_groundedness": c.get("died_at_groundedness"),
        })
    return out


def _dispatches(state: RunState, store: Store) -> list[dict]:
    out = []
    for raw in state.dispatches.values():
        row = dict(raw)
        row["returns"] = []
        for rid in raw.get("returns", []):
            path = store.returns / f"{rid}.json"
            if not path.exists():
                continue
            r = store.read_json(path)
            view = store.read_json(store.returns / f"{rid}.view.json")
            row["returns"].append({
                "id": rid,
                "headline": r.get("headline", ""),
                "recommendation": r.get("recommendation", ""),
                "flags": r.get("flags", []),
                "evidence": r.get("evidence", []),
                "assumptions": r.get("assumptions", []),
                "detail_headings": [d.get("heading") for d in r.get("detail", [])],
                "parsed": r.get("parsed"),
                "parse_error": r.get("parse_error", ""),
                "read_mode": view.get("mode", ""),
                "draw": view.get("draw", {}),
            })
        out.append(row)
    return out


def _influence(store: Store, state: RunState, cfg: Config) -> dict:
    from . import influence as infl

    inf_store = infl.InfluenceStore(store)
    rows = infl.settle(inf_store.all(), state.turn, cfg.influence.fade_after_turns)
    return {
        "human_only": True,
        "note": "the owner does not know any of this happened, and no model "
                "call has read it",
        "supplied": [r.to_dict() for r in rows],
        "by_status": {s: len([r for r in rows if r.status == s])
                      for s in (infl.PENDING, infl.TOOK, infl.FADED, infl.REJECTED)},
        "puppet_share": infl.puppet_share(rows, len(state.requirements)),
    }


def _process_views(store: Store) -> list[dict]:
    root = store.root / "process"
    if not root.is_dir():
        return []
    return [store.read_json(p) for p in sorted(root.glob("view-*.json"))]


def _life(life: LifeStore, cfg: Config) -> dict:
    if not cfg.life.enabled or not life.index_path.exists():
        return {"enabled": False}
    idx = life.index()
    bible = life.bible()
    days = list(idx.days)
    excerpts = []
    for day in _sample(days, 3):
        text = life.day_text(day)
        excerpts.append({"n": day.get("n"), "date": day.get("date"),
                         "valence": day.get("valence"), "words": day.get("words"),
                         "keywords": day.get("keywords", []),
                         "excerpt": text[:1500]})
    return {
        "enabled": True,
        "day_count": idx.day_count,
        "date": idx.date,
        "total_words": life.total_words(),
        "bible_words": idx.bible_words,
        "threads": idx.threads,
        "seed_facts": idx.seed_facts,
        "bible_opening": bible[:1500],
        "days": [{"n": d.get("n"), "date": d.get("date"), "words": d.get("words"),
                  "valence": d.get("valence"), "keywords": d.get("keywords", []),
                  "element_id": d.get("element_id", "")} for d in days],
        "excerpts": excerpts,
    }


def _sample(days: list[dict], n: int) -> list[dict]:
    """First, middle and last, so a reader sees whether it stayed varied."""
    if len(days) <= n:
        return list(days)
    return [days[0], days[len(days) // 2], days[-1]]


def _digest(store: Store) -> dict:
    paths = sorted(store.digests.glob("digest-*.md"))
    if not paths:
        return {"path": "", "text": ""}
    return {"path": str(paths[-1]), "text": paths[-1].read_text(),
            "all": [str(p) for p in paths]}


def _counts(rows: list[dict]) -> dict:
    counts: dict[str, int] = {}
    for r in rows:
        counts[r.get("kind", "?")] = counts.get(r.get("kind", "?"), 0) + 1
    return counts


def _pick(row: dict, keys: tuple) -> dict:
    return {k: row[k] for k in keys if k in row}


def write_export(root: str | Path, out_path: str | Path | None = None) -> Path:
    data = build_export(root)
    path = Path(out_path) if out_path else Path(root) / "export.json"
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False))
    return path
