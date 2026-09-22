"""The command line, and the run loop the whole harness hangs off.

`run_cmd` reads the charter, assembles the Context once, and then does the only
loop there is: the dice roll the day, each sitting is the owner and then the
builder, and the night runs after them. Everything it calls lives in another
module; what is here is the order things happen in.
"""
from __future__ import annotations

import argparse
import json
import math
import random
import subprocess
import sys
import time
import uuid
from pathlib import Path

from regent import HOME, agents, digest, night, owner, prompts
from regent.charter import budget, charter_faults, sections
from regent.crossing import plain_english, words
from regent.dice import DIALS, REGISTERS, clip, due, poisson, roll_register
from regent.ledger import Context, Run
from regent.life import Life, cast_cmd, owner_dir
from regent.schemas import EVENTS, PURSUITS
from regent.watch import watch_cmd


def run_cmd(a):
    project = Path(a.project).expanduser().resolve()
    project.mkdir(parents=True, exist_ok=True)
    top = subprocess.run(["git", "-C", str(project), "rev-parse", "--show-toplevel"], capture_output=True, text=True)
    if not top.stdout.strip() or Path(top.stdout.strip()).resolve() != project:
        subprocess.run(["git", "-C", str(project), "init", "-q"], check=True)   # its own, or its commits land above it
        print(f"charter: {project.name} had no repository of its own; one is made, so the builder's commits stay in it")
    runs = Path(a.runs).expanduser() if a.runs else HOME / "runs"
    prior = sorted(runs.glob(f"{project.name}-*"))
    root = None
    if prior and not a.new:
        s = Run(prior[-1]).load()
        if s and not s.get("finished") and "day_i" in s:
            root = prior[-1]
    fresh = root is None
    if fresh:
        root = runs / f"{project.name}-{time.strftime('%m%d-%H%M')}"
    run = Run(root)
    S = None if fresh else run.load()
    pname = str(project)

    if S:
        life = Life(owner_dir(S["owner"]))
        run.say(f"resuming {root.name} at day {S['day_i'] + 1}. Use --new to start over.")
    else:
        cf = Path(a.charter).expanduser() if a.charter else project / ".regent" / "charter.md"
        if not cf.exists():
            raise SystemExit(f"no charter at {cf}" if a.charter else f"no charter. Pass one, or put it in {cf}")
        # The charter and the project's own git live in here too, so neither counts as something already built.
        had_code = any(x for x in project.iterdir() if x.name not in (".regent", ".git"))
        life = Life(owner_dir(a.owner))
        S = {"charter": cf.read_text(), "owner": a.owner, "day_i": 0, "turn": 0, "finished": False,
             "reqs": [], "ideas": [], "ways": [], "amended": [], "escalations": [], "notes": [], "human_notes": [],
             "records": [], "compressed_upto": 0, "trust": 0.5 + 0.1 * life.d("trusting"), "mood": 0.0, "dry": 0,
             "since_dream": 0, "since_step": 0, "since_look": 2, "session_turns": 0, "wants_look": had_code,
             "existing": had_code, "last_reply": "", "last_check": "", "last_show": "", "check_ok": False,
             "built_once": had_code, "session": str(uuid.uuid4()), "started": False, "handover": "",
             "agent": a.agent or "claude",
             "claude_secs": 0.0, "blocking": 0.0,
             "counts": {"direct": 0, "challenge": 0, "constrain": 0, "cycles": 0, "step_backs": 0, "looks": 0,
                        "empty_days": 0, "fresh": 0}}

    # The agent is the run's, not the command line's: a run resumed with the flag left off is the
    # same agent it started as, and one started before there was a flag was Claude.
    S.setdefault("agent", "claude")
    if a.agent and a.agent != S["agent"]:   # its sessions, and the builder's memory of the work, are in that CLI
        raise SystemExit(f"this run belongs to {S['agent']}, not {a.agent}. Resume it with no --agent, "
                         f"or start a new run with --new.")
    adapter = agents.builder(S["agent"])
    S.setdefault("since_ask", 2)
    S.setdefault("idle", 0)
    S.setdefault("assumptions", [])
    S.setdefault("words", [])          # words of the builder's trade he has picked up and now owns
    S.setdefault("not_followed", [])   # what a reading left him unsure of, which he may ask about
    S.setdefault("ways_sent", [])
    S.setdefault("directions", [])     # wishes he has taken: where he is steering, not work for now
    S.setdefault("whys", [])           # doubts and worries he has answered for himself
    S.setdefault("tensions", [])       # what the last night saw pulling against itself, which may open a thread
    S.setdefault("field", [])          # notions stirring under his notice, fed by every stream, most never arriving
    S.setdefault("field_n", 0)         # notions ever made, so an id is never handed out twice
    S.setdefault("refractory", 0.0)    # what the last arrivals put on the threshold, decaying every night
    S.setdefault("gaps", [])           # what he knows he does not understand about what this is for
    S.setdefault("gaps_fed", [])
    S.setdefault("done_at", 0)
    S.setdefault("same", 0.0)          # a running average of how little each sitting changed anything
    S["counts"].setdefault("asks", 0)
    S["counts"].setdefault("readbacks", 0)
    S["counts"].setdefault("pushes", 0)
    ch = sections(S["charter"])

    tpd = a.turns_per_day or S.get("tpd") or budget(ch, "turns_per_day") or 1.0
    days = a.days or S.get("days") or math.ceil(budget(ch, "days") or budget(ch, "turns") / tpd) or 10
    S["tpd"], S["days"] = tpd, days
    check_cmd, show_cmd = ch.get("check", "").strip().strip("`"), ch.get("show", "").strip().strip("`")
    tool_lines = [t for ln in ch.get("tools", "").splitlines() if ln.strip().startswith("-") and (t := ln.strip("- ").strip())]
    his_bash = ",".join(sorted({f"Bash({t.split()[0]}:*)" for t in tool_lines})) or "Bash(ls:*)"
    # The web is the Network section's to open, not a word's to close: no domains listed, no web tools.
    domains = [ln.strip("- ").strip() for ln in ch.get("network", "").splitlines() if ln.strip().startswith("-")]
    deny = [] if domains else ["WebFetch", "WebSearch"]
    for fault in charter_faults(S["charter"], ch):
        print(f"charter: {fault}")
    # Only Claude Code can be handed the list of domains. Under another CLI the Network section is a
    # thing the charter asks for and nothing enforces, and a run days long has to say so at the start.
    web = (f"web {'open to ' + ', '.join(domains) if domains else 'off'}" if adapter.holds_network else
           f"web is {adapter.name}'s own sandbox to decide, so the charter's Network section is not applied")
    print(f"charter: {days} days at {tpd:g} sittings a day, run by {adapter.name}; the owner may run "
          f"{', '.join(sorted({t.split()[0] for t in tool_lines})) or 'ls'}; "
          f"{web}; check {'set' if check_cmd else 'none'}, show {'set' if show_cmd else 'none'}")
    # Claude Code's own sandbox holds them both: a shell can write only inside the project and reach only the domains the
    # charter's Network section lists. A builder's subagent once left its scratch files in /tmp, and nothing stopped it.
    fence = ["--settings", json.dumps({"sandbox": {"enabled": True, "autoAllowBashIfSandboxed": True,
                                                   "allowUnsandboxedCommands": False, "network": {"allowedDomains": domains}}})]
    plant_file = root / "plant.md"
    for line in a.plant:
        with plant_file.open("a") as f:
            f.write(line + "\n")

    # Three things a life needs that a bible does not carry: what could happen in a week of it, for the dice to draw
    # from, what this person does because they want to, and why they want this project. Each is written once, by a
    # model, the first time it is missed, and the first two are asked for in the casting's own words.
    for what, schema in (("events", EVENTS), ("pursuits", PURSUITS)):
        if not (f := life.root / f"{what}.md").exists():
            asked = f"{what} is " + prompts.load("cast").split(f"\n{what} is ")[1].split("\n\n")[0]
            f.write_text("\n".join(agents.ask(run, adapter, what, "haiku", asked + "\n\nWHO THEY ARE\n" + life.bible,
                                              schema, thinking=False)[what]) + "\n")
    # How he keeps a journal is the same kind of thing: a life cast before it was rolled gets it rolled now,
    # once, from his name, so the same person writes the same way on every run.
    if "register" not in life.disp:
        life.disp["register"] = roll_register(random.Random(life.root.name))
        (life.root / "disposition.json").write_text(json.dumps(life.disp, indent=2))
    happenings, pursuits = ([x for x in (life.root / f"{w}.md").read_text().splitlines() if x.strip()]
                            for w in ("events", "pursuits"))
    if not life.get("stake", pname):
        life.put("stake", pname, agents.ask(run, adapter, "stake", "sonnet", prompts.load("stake").format(
            intent=ch.get("intent", ""), bible=life.bible)))
    # The why is not a fact about him, it is the thing that moves. Every version is kept, because a project
    # whose reason has not changed in twenty days is one nobody has actually used.
    if "stakes" not in S:
        S["stakes"] = [{"day": 0, "turn": 0, "text": life.get("stake", pname), "could_become": "", "follows": ""}]
        run.log("stake", **S["stakes"][0])
    S.setdefault("why_sent", S["stakes"][-1]["text"])

    # The two word sets the gauge measures against. His is everything he has ever written plus plain English;
    # the builder's grows with every reply, and on a resumed run it is read back out of the ledger.
    his_words = set(words("\n".join([life.bible, *happenings, life.get("stake", pname), S["charter"]]
                                     + [r[0] for r in life.q("SELECT text FROM day")]))) | plain_english(life.root)
    their_words = set(words(" ".join(
        [e.get("text", "") for e in run.rows("reply")]
        + [r["a"] for e in run.rows("asked") for r in e.get("rounds", [])]
        + [x["spec"] + " " + x["test"] for e in run.rows("readback") for x in e.get("readings", [])]
        + [q for e in run.rows("readback") for q in e.get("questions", [])])))

    cx = Context(state=S, life=life, run=run, args=a, charter=ch, project=project, root=root, adapter=adapter,
                 check_cmd=check_cmd, show_cmd=show_cmd, tool_lines=tool_lines, his_bash=his_bash, deny=deny,
                 fence=fence, domains=domains, his_words=his_words, their_words=their_words,
                 happenings=happenings, pursuits=pursuits)

    if a.watch:
        watch_cmd(a, root, background=True)
    run.log("start", project=pname, owner=S["owner"], days=days, turns_per_day=tpd, seed=a.seed, resumed=not fresh,
            agent=S["agent"])
    run.say(f"regent: {life.root.name} on {project}, {days} days at about {tpd:g} sittings a day, run {root}")
    while S["day_i"] < days:
        rng = random.Random(f"{a.seed}-{S['day_i']}")
        day = life.days() + 1
        S["mood"] = clip(0.6 * S["mood"] + rng.gauss(0, 0.35))
        failing = bool(S["last_check"]) and not S["check_ok"]
        # A failed check pulls him back. A thing he is content with, that has gone quiet, lets him drift away.
        n = poisson(rng, tpd * (1.6 if failing else 1.0) * 0.6 ** S["dry"])
        n = max(n, 1) if S["turn"] == 0 else n
        run.log("dawn", day=day, mood=round(S["mood"], 2), sittings=n)
        met = ""
        if plant_file.exists() and (lines := [x for x in plant_file.read_text().splitlines() if x.strip()]):
            met = lines[0]
            plant_file.write_text("\n".join(lines[1:]) + "\n")
            run.log("plant", human_only=True)
        if not n:
            S["counts"]["empty_days"] += 1
            S["idle"] += 1
            run.say(f"day {day}: no time for the project.")
        seen = [owner.sitting(cx, day, rng, met if k == 0 else "") for k in range(n)]

        # Night. The day gets written, the project is half forgotten, and sometimes the spoon falls.
        t = time.time()
        S["since_dream"] += 1
        S["since_step"] += 1
        last = S["day_i"] + 1 >= days
        caught: dict = {}
        jobs = [night.tonight(cx, "day", night.write_day, day, rng, seen, met)]
        if night.to_remember(cx):
            jobs.append(night.tonight(cx, "memory", night.consolidate, day))
        if S["built_once"] and not cx.pending() and not last and due(rng, S["since_dream"], a.dream_gap * (1 - 0.5 * life.d("curious"))):
            S["since_dream"] = 0
            jobs.append(night.tonight(cx, "spoon", night.spoon, random.Random(rng.random()), caught))
        for j in jobs:
            j.start()
        for j in jobs:
            j.join()
        # The field settles after them and not beside them: the day that was just written and the links the
        # spoon just caught both feed it, and it is one thing, so nothing may be adding to it twice at once.
        night.tonight(cx, "field", night.night_field, day, rng, caught, bool(seen), last).run()
        if S["turn"] and (last or due(rng, S["since_step"], 7 * (1 + 0.4 * life.d("patient")))):
            night.tonight(cx, "step_back", night.step_back, day, rng).run()
        # A builder's session grows stale with every turn in it, so the odds of a fresh pair of hands grow too.
        if not last and S["started"] and life.get("memory", pname) and due(rng, S["session_turns"], 9):
            S["session"], S["started"], S["session_turns"] = str(uuid.uuid4()), False, 0
            S["counts"]["fresh"] += 1
            S["handover"] = owner.handover(life.get("memory", pname))
            run.say("   (a fresh builder picks it up in the morning, from his memory of it)")
        S["blocking"] += time.time() - t
        S["day_i"] += 1
        run.save(S)
        if S.get("done_at") and S["check_ok"]:   # he called it finished and the check agrees: the charter's Stop is his to read
            run.say(f"day {day}: he called it done.")
            break

    S["finished"] = True
    run.save(S)
    digest.write(cx)
    life.close()
    run.close()


def main():
    ap = argparse.ArgumentParser(prog="regent", description="A simulated owner who governs a project.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="run a project, new or existing, starting or resuming")
    r.add_argument("charter", nargs="?", help="default: <project>/.regent/charter.md")
    r.add_argument("--project", required=True)
    r.add_argument("--owner", default="piotr-mahon", help="an owner name or a path to an owner folder")
    r.add_argument("--days", type=int, default=None, help="how many days of his life the run lasts. Charter: 'days:'")
    r.add_argument("--turns-per-day", type=float, default=None,
                   help="mean sittings a day, the mean of a Poisson draw, so 0.5 is every other day. Charter: 'turns_per_day:'")
    r.add_argument("--dream-gap", type=float, default=3.0, help="mean nights between spoon cycles. His curiosity shortens it")
    r.add_argument("--runs", default=None, help=f"where runs live. Default {HOME / 'runs'}")
    r.add_argument("--new", action="store_true", help="start a new run instead of resuming the last one")
    r.add_argument("--seed", type=int, default=1)
    r.add_argument("--agent", default=None, choices=("claude", "codex", "cursor"),
                   help="which CLI makes every call, the owner's and the builder's. Default claude. Kept in the "
                        "run, so a resume is the agent the run started as, and passing another one is refused")
    r.add_argument("--model", default="sonnet", help="the builder")
    r.add_argument("--regent-model", default="sonnet")
    r.add_argument("--effort", default="low")
    r.add_argument("--exchanges", type=int, default=4, help="how many times a sitting the builder may stop and ask him")
    r.add_argument("--timeout", type=int, default=600, help="seconds for the charter's Check and Show commands")
    r.add_argument("--plant", action="append", default=[], help="something he comes across. He never learns it was yours")
    r.add_argument("--watch", action="store_true", help="open the live page in a browser while it runs")
    r.add_argument("--port", type=int, default=0, help="port for --watch. Default: any free one")
    w = sub.add_parser("watch", help="a live page of a run: his days, his sittings, the nights, the project growing")
    w.add_argument("run", nargs="?", help="a run folder or a project name. Default: the newest run")
    w.add_argument("--port", type=int, default=8642)
    w.add_argument("--export", help="write the page to this file with the run inside it, and do not serve")
    c = sub.add_parser("cast", help="roll a new owner")
    c.add_argument("--pin", action="append", default=[], help="a fact in words: 'a lock keeper', 'impatient, generous'")
    c.add_argument("--dial", action="append", default=[], help=f"set a dial instead of rolling it, e.g. bold=0.6. {', '.join(DIALS)}")
    c.add_argument("--register", default=None, choices=tuple(REGISTERS), help="how they keep a journal. Default: rolled")
    c.add_argument("--name", default=None, help="folder name. Default: their own")
    c.add_argument("--seed", type=int, default=int(time.time()))
    c.add_argument("--model", default="sonnet")
    c.add_argument("--agent", default="claude", choices=("claude", "codex", "cursor"))
    for name, helptext in (("say", "leave him a note, shown at his next sitting"),
                           ("plant", "something he comes across, never traced to you")):
        s = sub.add_parser(name, help=helptext)
        s.add_argument("run")
        s.add_argument("text")
    j = sub.add_parser("journal", help="read an owner's life")
    j.add_argument("owner")
    j.add_argument("--last", type=int, default=5)
    a = ap.parse_args()
    if a.cmd == "run":
        return run_cmd(a)
    if a.cmd == "cast":
        return cast_cmd(a)
    if a.cmd == "watch":
        return watch_cmd(a)
    if a.cmd == "journal":
        life = Life(owner_dir(a.owner))
        print(f"# {life.root.name}, day {life.days()}\n\n{life.recent(a.last, 4000)}"
              f"\n\n## What is hanging over him\n\n{life.thread_lines()}")
        return 0
    target = Path(a.run).expanduser() / ("inbox.md" if a.cmd == "say" else "plant.md")
    if not target.parent.is_dir():
        raise SystemExit(f"no run at {target.parent}")
    with target.open("a") as f:
        f.write(a.text.strip() + "\n")
    print(f"written to {target}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
