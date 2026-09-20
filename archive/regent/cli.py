"""The command line.

    regent run charter.md --project <dir>    start, or pick up a stopped run
    regent status                            where the run stands
    regent watch                             one line per decision as it lands
    regent digest                            the page for the current period
    regent answer <id> "<text>"              reply to an escalation
    regent stop                              finish the turn in flight, then halt
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from .config import Config
from .ledger import Ledger, summarise
from .store import Store

DEFAULT_STATE = "run"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="regent", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--state", default=DEFAULT_STATE,
                        help="the run directory holding all state (default: run)")
    sub = parser.add_subparsers(dest="command", required=True)

    p_run = sub.add_parser("run", help="start a run, or pick up a stopped one")
    p_run.add_argument("charter", help="path to the charter")
    p_run.add_argument("--project", required=True, help="the directory orchestrators work in")
    p_run.add_argument("--config", default="", help="a JSON file overriding any config field")
    p_run.add_argument("--profile", default="", help="a named set of overrides, such as cheap")
    p_run.add_argument("--owner", default="",
                       help="an owner written once and reused, under owners/")
    p_run.add_argument("--seed", type=int, default=None, help="the seed for every draw")
    p_run.add_argument("--max-turns", type=int, default=0, help="stop after N turns")
    p_run.add_argument("--dry-run", action="store_true",
                       help="print the assembled first prompt and the argv, call nothing")

    sub.add_parser("status", help="where the run stands")

    p_watch = sub.add_parser("watch", help="one line per decision as it lands")
    p_watch.add_argument("--from", dest="from_seq", type=int, default=0)
    p_watch.add_argument("--once", action="store_true", help="print and exit")

    p_digest = sub.add_parser("digest", help="the page for the current period")
    p_digest.add_argument("--since", type=int, default=None, help="start from this turn")
    p_digest.add_argument("--write", action="store_true", help="save it under digests/")

    p_answer = sub.add_parser("answer", help="reply to an escalation")
    p_answer.add_argument("id")
    p_answer.add_argument("text")

    p_export = sub.add_parser("export",
                              help="write one json holding how the run went")
    p_export.add_argument("run_dir", nargs="?", default="",
                          help="the run directory, defaulting to --state")
    p_export.add_argument("--out", default="", help="where to write it")

    p_inf = sub.add_parser("influence",
                           help="steer what the owner meets, without ordering")
    inf_sub = p_inf.add_subparsers(dest="channel", required=True)
    p_plant = inf_sub.add_parser("plant", help="something met: a remark, a sight, a small event")
    p_plant.add_argument("text")
    p_plant.add_argument("--weight", default="nudge",
                         choices=["whisper", "nudge", "push"])
    p_voice = inf_sub.add_parser("voice", help="a line for someone in the cast")
    p_voice.add_argument("name")
    p_voice.add_argument("text")
    p_voice.add_argument("--weight", default="nudge",
                         choices=["whisper", "nudge", "push"])
    p_read = inf_sub.add_parser("read", help="a text the owner reads")
    p_read.add_argument("source")
    p_mood = inf_sub.add_parser("mood", help="a lean toward risk or opportunity")
    p_mood.add_argument("lean", choices=["risk", "opportunity"])
    p_mood.add_argument("--days", type=int, default=3)
    p_worry = inf_sub.add_parser("worry", help="a motif the owner's eye catches")
    p_worry.add_argument("text")
    p_worry.add_argument("--days", type=int, default=3)
    p_itch = inf_sub.add_parser("itch", help="an area the next spot check is drawn to")
    p_itch.add_argument("text")
    p_recall = inf_sub.add_parser("recall", help="an element gone cold, brought back")
    p_recall.add_argument("element_id")
    p_dream = inf_sub.add_parser("dream", help="a theme the next dream starts from")
    p_dream.add_argument("text")
    inf_sub.add_parser("list", help="what you have supplied and what came of it")

    p_owner = sub.add_parser("owner", help="an owner written once and reused")
    owner_sub = p_owner.add_subparsers(dest="owner_cmd", required=True)
    p_adopt = owner_sub.add_parser(
        "adopt", help="take a run's life into owners/, condensed to journal form")
    p_adopt.add_argument("name")
    p_adopt.add_argument("--owners-dir", default="owners")
    p_adopt.add_argument("--words", type=int, default=200)
    p_new = owner_sub.add_parser("new", help="cast a regent: pin a few facts, roll the rest")
    p_new.add_argument("--pin", action="append", default=[],
                       help="a word, or a dial set directly, such as patient=-0.4")
    p_new.add_argument("--candidates", type=int, default=1)
    p_new.add_argument("--owners-dir", default="owners")
    p_new.add_argument("--name", default="")
    p_new.add_argument("--seed", type=int, default=None)
    p_dials = owner_sub.add_parser(
        "disposition", help="read an existing owner's dials from their own life")
    p_dials.add_argument("name")
    p_dials.add_argument("--owners-dir", default="owners")
    p_dials.add_argument("--apply", action="store_true",
                         help="store exactly the reading that was last shown")
    p_dials.add_argument("--reread", action="store_true",
                         help="take a fresh reading over a stored one")

    sub.add_parser("stop", help="finish the turn in flight, then halt")

    args = parser.parse_args(argv)
    store = Store(args.state)
    return COMMANDS[args.command](args, store)


def cmd_run(args, store: Store) -> int:
    from .loop import Harness, bootstrap

    cfg = Config.load(args.config or None, profile=args.profile or "")
    if args.owner:
        cfg.life.owner = args.owner
    project = Path(args.project).resolve()
    project.mkdir(parents=True, exist_ok=True)
    if store.stop_flag.exists():
        store.stop_flag.unlink()
    ctx = bootstrap(store, cfg, args.charter, str(project), seed=args.seed)

    if ctx.charter.missing:
        print(f"the charter has no {', '.join(ctx.charter.missing)} section",
              file=sys.stderr)
    if args.dry_run:
        return _dry_run(ctx)

    print(f"run: state in {store.root}, project {project}, seed {ctx.rng.seed}")
    print(f"charter: {ctx.charter.sha256[:12]}, "
          f"{len(ctx.charter.refusals)} refusals, {len(ctx.charter.reserved)} reserved")
    reason = Harness(ctx).run(max_turns=args.max_turns)
    print(f"stopped: {reason}")
    print(f"turns {ctx.state.turn}, spend {ctx.state.cost_usd:.2f} USD, "
          f"{ctx.state.calls} model calls")
    return 0


def _dry_run(ctx) -> int:
    """Print what the first super-orchestrator call would be, and call nothing."""
    from . import manifold as mf
    from . import schemas
    from .loop import Harness
    from .prompts import SYSTEM_OWNER
    from .runner import ClaudeCliRunner, ModelRequest

    h = Harness(ctx)
    prompt = ctx.prompts.fill(
        "wake",
        self=ctx.read_self(), charter_refusals="\n".join(ctx.charter.refusals),
        charter_reserved="\n".join(ctx.charter.reserved),
        stance=ctx.state.stance.describe(), signals=ctx.state.signals.line(),
        objectives=json.dumps(ctx.state.live_objectives(), indent=2),
        plan=h.render_plan(), returns_view="(no returns this turn)",
        ledger_recent="(empty)",
        manifold_warm=mf.render(ctx.manifold.warm()),
        escalation_answers="(none)", candidates="(none)",
        life_recent=ctx.life.for_judgement() if ctx.cfg.life.enabled
        else "(no life running)",
        mood=ctx.life.mood_line() if ctx.cfg.life.enabled else "no life running",
        spot_check_findings="(none)",
        requirements="(none invented yet)",
        ways=ctx.ways.render(),
        appetite=f"{ctx.appetite_left():.0%} of the budget remains available "
                 f"for work nobody asked for",
        turn="1", budget=h.budget_line())
    runner = ClaudeCliRunner()
    argv = runner.argv(ModelRequest(role="wake", prompt=prompt, model=ctx.cfg.models.wake,
                                    schema=schemas.DECISION, system=SYSTEM_OWNER,
                                    max_budget_usd=ctx.cfg.spend.wake))
    print("argv:")
    shown = []
    for a in argv:
        short = a if len(a) <= 70 else a[:70] + "..."
        shown.append(repr(short) if short == "" or " " in short else short)
    print(" ".join(shown))
    print()
    print("prompt:")
    print(prompt)
    return 0


def cmd_status(args, store: Store) -> int:
    if not store.exists():
        print(f"no run in {store.root}")
        return 1
    from rich.console import Console
    from rich.table import Table

    from .charter import parse_charter
    from .config import Config
    from .life import LifeStore
    from .requirements import Register
    from .state import RunState

    st = RunState.from_dict(store.read_json(store.state))
    ch = parse_charter(store.charter) if store.charter.exists() else None
    cfg = Config.load(None)
    ledger = Ledger(store)
    register = Register(cfg, st.requirements)
    life = LifeStore(store, cfg)
    con = Console()

    con.print(f"[bold]turn {st.turn}[/bold], cycle {st.cycle}, seed {st.seed}, "
              f"{st.draws} draws")
    if ch:
        con.print(f"stop condition: {'; '.join(ch.stop) or 'none stated'}")
    con.print()

    t = Table(title="objectives", title_justify="left", header_style="")
    t.add_column("id")
    t.add_column("weight", justify="right")
    t.add_column("criteria", justify="right")
    t.add_column("text", overflow="fold")
    for o in st.objectives:
        mark = "" if o.get("status") == "live" else " (dropped)"
        t.add_row(o["id"] + mark, f"{float(o.get('weight', 0)):.2f}",
                  f"{o.get('criteria_met', 0)}/{o.get('criteria_total', 0)}",
                  (o.get("text", "") or "")[:90])
    if not st.objectives:
        t.add_row("(none)", "", "", "")
    con.print(t)

    live = list(st.open_dispatches())
    d = Table(title="dispatches in flight", title_justify="left", header_style="")
    d.add_column("id")
    d.add_column("tier")
    d.add_column("title", overflow="fold")
    for row in live:
        d.add_row(row.id, row.tier, row.title[:80])
    if not live:
        d.add_row("(none)", "", "")
    con.print(d)

    if register.rows:
        r = Table(title="requirements invented", title_justify="left", header_style="")
        r.add_column("id")
        r.add_column("appetite", justify="right")
        r.add_column("text", overflow="fold")
        for row in register.rows:
            r.add_row(row["id"], f"{float(row.get('appetite_share', 0)):.0%}",
                      row.get("text", "")[:90])
        con.print(r)

    appetite = getattr(ch, "appetite", 0.0) if ch else 0.0
    con.print(f"requirements invented: {len(register.rows)}, appetite used "
              f"{register.appetite_used():.0%} of {appetite:.0%}")
    con.print(f"spot checks: {st.spot_checks_total} against {st.returns_read} "
              f"returns read")
    if cfg.life.enabled and life.index_path.exists():
        idx = life.index()
        con.print(f"life: day {idx.day_count}, {life.total_words()} words, "
                  f"{life.mood_line()}")

    b = ch.budget if ch else None
    if b:
        con.print(f"budget: {st.cost_usd:.2f} of {b.spend_usd:.2f} USD, "
                  f"{st.tokens} of {b.tokens or 'no'} tokens, {st.calls} calls")
    else:
        con.print(f"budget: {st.cost_usd:.2f} USD, {st.tokens} tokens")

    waiting = st.open_escalations()
    con.print(f"escalations waiting: {len(waiting)}")
    for e in waiting:
        con.print(f"  {e.id} [{e.tier}] {e.question[:80]}")
    con.print()
    con.print(f"stance: {st.stance.describe()}")
    if st.stance.line:
        con.print(f"  {st.stance.line}")
    con.print(f"signals: {st.signals.line()}")
    reads = {}
    for rec in ledger.of_kind("read_mode"):
        reads[rec.get("read_mode", "?")] = reads.get(rec.get("read_mode", "?"), 0) + 1
    if reads:
        con.print("reads: " + ", ".join(f"{k} {v}" for k, v in sorted(reads.items())))
    if st.stopped:
        con.print(f"stopped: {st.stop_reason}")
    return 0


def cmd_watch(args, store: Store) -> int:
    if not store.ledger.exists():
        print(f"no ledger in {store.root}")
        return 1
    ledger = Ledger(store)
    if args.once:
        print(summarise(ledger.since(args.from_seq), limit=10_000))
        return 0
    seen = args.from_seq
    print(f"watching {store.ledger}. ctrl-c to stop.")
    try:
        while True:
            new = ledger.since(seen)
            if new:
                print(summarise(new, limit=10_000), flush=True)
                seen = new[-1].get("seq", seen)
            time.sleep(1.0)
    except KeyboardInterrupt:
        return 0


def cmd_digest(args, store: Store) -> int:
    if not store.exists():
        print(f"no run in {store.root}")
        return 1
    from .charter import parse_charter
    from .digest import build_digest, write_digest
    from .loop import Context
    from .state import RunState

    cfg = Config.load(None)
    st = RunState.from_dict(store.read_json(store.state))
    ch = parse_charter(store.charter)
    ctx = Context(store, cfg, ch, st, project=st.project, runners={}, notifier=None)
    since = args.since if args.since is not None else st.last_digest_turn
    if args.write:
        print(write_digest(ctx, since))
    else:
        print(build_digest(ctx, since))
    return 0


def cmd_answer(args, store: Store) -> int:
    """Answering is an inbox note, never a state write.

    A live run holds its state in memory and rewrites state.json at the end of
    every turn, so a second process writing that file loses the answer.
    """
    import time as _t

    if not store.exists():
        print(f"no run in {store.root}")
        return 1
    from .state import RunState

    st = RunState.from_dict(store.read_json(store.state))
    known = {e.get("id") for e in st.escalations}
    pending = _pending_answers(store)
    if args.id not in known:
        print(f"no escalation with id {args.id}")
        open_ids = [e.id for e in st.open_escalations() if e.id not in pending]
        if open_ids:
            print("open: " + ", ".join(open_ids))
        return 1
    if args.id in pending:
        print(f"{args.id} already has an answer waiting to be picked up")
        return 1
    already = st.escalation(args.id)
    if already is not None and already.answer:
        print(f"{args.id} was already answered")
        return 1

    store.inbox.mkdir(parents=True, exist_ok=True)
    note = {"kind": "answer", "id": args.id, "text": args.text, "ts": _t.time(),
            "iso": _t.strftime("%Y-%m-%dT%H:%M:%S")}
    path = store.inbox / f"{int(note['ts'] * 1000)}-{args.id}.json"
    store.write_json(path, note)
    Ledger(store).write("escalation_answered", id=args.id, source="operator",
                        summary=args.text[:300])
    print(f"answered {args.id}. the run picks it up on its next turn.")
    return 0


def _pending_answers(store: Store) -> set:
    if not store.inbox.exists():
        return set()
    out = set()
    for p in store.inbox.glob("*.json"):
        try:
            out.add(json.loads(p.read_text()).get("id"))
        except (json.JSONDecodeError, OSError):
            continue
    return out


def cmd_stop(args, store: Store) -> int:
    store.root.mkdir(parents=True, exist_ok=True)
    store.stop_flag.write_text(f"asked at {time.strftime('%Y-%m-%dT%H:%M:%S')}\n")
    print("stop asked. the turn in flight finishes, then the run halts.")
    return 0


def cmd_export(args, store: Store) -> int:
    from .export import write_export

    root = args.run_dir or str(store.root)
    try:
        path = write_export(root, args.out or None)
    except FileNotFoundError as exc:
        print(str(exc))
        return 1
    print(path)
    return 0


def cmd_influence(args, store: Store) -> int:
    """Influence is an input to the run, written to a file no model reads."""
    from . import influence as infl

    if not store.exists():
        print(f"no run in {store.root}")
        return 1
    from .state import RunState

    st = RunState.from_dict(store.read_json(store.state))
    inf_store = infl.InfluenceStore(store)

    if args.channel == "list":
        rows = infl.settle(inf_store.all(), st.turn, 8)
        if not rows:
            print("nothing supplied yet")
            return 0
        print(infl.render_for_human(rows))
        return 0

    try:
        if args.channel == "plant":
            inf = inf_store.add(infl.PLANT, text=args.text, weight=args.weight,
                                turn=st.turn)
        elif args.channel == "voice":
            inf = inf_store.add(infl.VOICE, text=args.text, subject=args.name,
                                weight=args.weight, turn=st.turn)
        elif args.channel == "read":
            text = args.source
            path = Path(args.source)
            if path.is_file():
                text = path.read_text()[:4000]
            inf = inf_store.add(infl.READING, text=text, subject=args.source,
                                turn=st.turn)
        elif args.channel == "mood":
            inf = inf_store.add(infl.MOOD, text=args.lean, days=args.days,
                                turn=st.turn)
        elif args.channel == "worry":
            inf = inf_store.add(infl.WORRY, text=args.text, days=args.days,
                                turn=st.turn)
        elif args.channel == "itch":
            inf = inf_store.add(infl.ITCH, text=args.text, turn=st.turn)
        elif args.channel == "recall":
            inf = inf_store.add(infl.RECALL, text=args.element_id, turn=st.turn)
        else:
            inf = inf_store.add(infl.DREAM, text=args.text, turn=st.turn)
    except infl.EvidenceLine as exc:
        print(str(exc))
        return 1

    print(f"{inf.id} supplied. The owner will meet it and will not know where "
          f"it came from.")
    print("`regent influence list` shows what came of it.")
    return 0


def cmd_owner(args, store: Store) -> int:
    from .charter import parse_charter
    from .loop import Context
    from .owner import adopt, render
    from .state import RunState

    if not store.exists():
        print(f"no run in {store.root}")
        return 1
    cfg = Config.load(None)
    if store.config_snapshot.exists():
        from .export import _merge_snapshot
        _merge_snapshot(cfg, store.read_json(store.config_snapshot))
    st = RunState.from_dict(store.read_json(store.state))
    # A command is not a run, so it does not inherit the run's spent budget.
    st.started = time.time()
    st.elapsed_s = 0.0
    ctx = Context(store, cfg, parse_charter(store.charter), st,
                  project=st.project)
    if args.owner_cmd == "disposition":
        return _cmd_owner_disposition(args, ctx)
    if args.owner_cmd == "new":
        return _cmd_owner_new(args, ctx)
    try:
        out = adopt(ctx, args.name, args.owners_dir, word_target=args.words)
    except FileNotFoundError as exc:
        print(str(exc))
        return 1
    print(render(out))
    return 0


def _cmd_owner_disposition(args, ctx) -> int:
    from .owner import disposition_command

    code, text = disposition_command(ctx, args.name, args.owners_dir,
                                     apply=args.apply, reread=args.reread)
    print(text)
    return code


def _cmd_owner_new(args, ctx) -> int:
    from .owner import cast

    if args.seed is not None:
        from .rng import Rng
        ctx.rng = Rng(seed=args.seed)
    for i, row in enumerate(cast(ctx, args.pin, args.candidates), start=1):
        head = f"{i}. " if args.candidates > 1 else ""
        print(f"{head}{row['paragraph']}")
        print(f"   {row['disposition'].line()}")
        print()
    print("Nothing written. Run the charter with --owner <name> to keep one.")
    return 0


COMMANDS = {
    "run": cmd_run,
    "owner": cmd_owner,
    "influence": cmd_influence,
    "export": cmd_export,
    "status": cmd_status,
    "watch": cmd_watch,
    "digest": cmd_digest,
    "answer": cmd_answer,
    "stop": cmd_stop,
}


def run() -> None:
    """Console script entry point. `uv run harness <command>`."""
    import sys
    sys.exit(main())
