#!/usr/bin/env python3
"""Regent: a simulated owner who governs a project over a long run.

One process. It holds the regent, a person with a life, a mood and a memory,
and it runs Claude Code in the project on his behalf. A turn is a sitting: one
regent call, then one Claude turn. Nothing else sits in Claude's path.

    regent run --project ~/code/thing
    regent say <run> "a note from you, shown at his next sitting"
    regent plant <run> "something he comes across, never traced to you"
    regent journal piotr-mahon

He is an owner, not a reviewer, and he does not read code. He directs,
challenges, sets limits, changes his mind about a limit, uses the thing, and
when he wants the code examined he asks the builder for a review, because the
builder has subagents for that. The harness adds only what a person has and a
prompt does not: a life that goes on whether the project does or not, a memory
that loses things, and sleep.

Every few turns he rests. His memory of the project is compressed and some of
it lost, he dreams, and the builder starts fresh from that memory. The dream is
the point of the life. Asleep he is not looking at the code, so what he brings
back is not a small variation on what is already there. It is a problem from
somewhere else in his life with the same shape as one here.

The old multi-call harness is in archive/: 10,914 lines, 224 tunables and three
storage layers doing this job. Read it before adding a module.
"""
from __future__ import annotations

import argparse
import json
import os
import random
import re
import sqlite3
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

HOME = Path(os.environ.get("REGENT_HOME", Path.home() / ".regent"))
SEALED = ["--strict-mcp-config", "--setting-sources", ""]  # the regent: no tools, no servers, no settings
REST_EVERY = 3
SPOT_USD = 0.10   # a spot check is a glance. The CLI enforces it, so no limiter here.

DECISION = {
    "type": "object",
    "properties": {
        "stance_line": {"type": "string"},
        "verdict": {"type": "string", "enum": ["continue", "accept", "reject"]},
        "message": {"type": "string"},
        "challenged": {"type": "boolean"},
        "constrained": {"type": "boolean"},
        "requirements_new": {"type": "array", "items": {"type": "object", "properties": {
            "text": {"type": "string"}, "test": {"type": "string"},
            "idea": {"type": "string", "description": "the label of the idea this came from, or empty"}},
            "required": ["text", "test"]}},
        "requirements_built": {"type": "array", "items": {"type": "string"}},
        "ideas_declined": {"type": "array", "items": {"type": "object", "properties": {
            "idea": {"type": "string"}, "why": {"type": "string"}}, "required": ["idea", "why"]}},
        "constraints_changed": {"type": "array", "items": {"type": "object", "properties": {
            "constraint": {"type": "string"}, "now": {"type": "string"}, "why": {"type": "string"}},
            "required": ["constraint", "now", "why"]}},
        "ask_the_human": {"type": "string"},
        "wants_to_look": {"type": "boolean", "description": "true if you want to try the thing yourself next time"},
        "looked_at": {"type": "array", "items": {"type": "string"}},
        "look_matched": {"type": "boolean", "description": "if you looked today, did what you found match what you were told"},
        "notes_to_self": {"type": "string"},
        "journal": {"type": "string"},
        "done": {"type": "boolean"},
    },
    "required": ["stance_line", "verdict", "message", "challenged", "constrained", "requirements_new",
                 "requirements_built", "ideas_declined", "constraints_changed", "ask_the_human", "wants_to_look",
                 "looked_at", "look_matched", "notes_to_self", "journal", "done"],
}
IDEAS = {"type": "object", "properties": {"ideas": {"type": "array", "items": {"type": "object", "properties": {
    "text": {"type": "string"}, "test": {"type": "string"},
    "came_from": {"type": "string", "description": "the thing in your life it came from, and the shape they share"}},
    "required": ["text", "test", "came_from"]}}}, "required": ["ideas"]}
STEPBACK = {"type": "object", "properties": {
    "observations": {"type": "array", "items": {"type": "string"}},
    "ways": {"type": "array", "items": {"type": "string"}},
    "notes_for_the_human": {"type": "array", "items": {"type": "string"}}},
    "required": ["observations", "ways", "notes_for_the_human"]}

LIFE_SCHEMA = """
CREATE TABLE IF NOT EXISTS day(n INTEGER PRIMARY KEY, iso TEXT, text TEXT);
CREATE TABLE IF NOT EXISTS memory(project TEXT PRIMARY KEY, text TEXT, iso TEXT);
"""
RUN_SCHEMA = """
CREATE TABLE IF NOT EXISTS event(id INTEGER PRIMARY KEY, t REAL, kind TEXT, data TEXT);
CREATE TABLE IF NOT EXISTS state(k TEXT PRIMARY KEY, v TEXT);
"""


def db(path: Path, schema: str) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(path, timeout=30, isolation_level=None, check_same_thread=False)
    c.execute("PRAGMA journal_mode=WAL")
    c.executescript(schema)
    return c


class Life:
    """His life, one file per owner, so a regent is a thing you copy from one
    machine or project to another. The day number comes from the table itself,
    which is what stops two runs on two projects writing over the same day."""

    def __init__(self, root: Path):
        self.root = root
        self.bible = (root / "bible.md").read_text()
        d = root / "disposition.json"
        self.disp = json.loads(d.read_text()) if d.exists() else {}
        self.c = db(root / "life.db", LIFE_SCHEMA)
        self.lock = threading.Lock()

    def d(self, k: str) -> float:
        return float(self.disp.get(k, 0) or 0)

    @property
    def who(self) -> str:
        return self.bible.split("## The cast")[0][:1800]

    @property
    def stake(self) -> str:
        m = re.search(r"^## Why I want this\s*\n(.*?)(?=^## |\Z)", self.bible, re.S | re.M)
        return m.group(1).strip() if m else ""

    def add_day(self, text: str) -> int:
        with self.lock:
            cur = self.c.execute("INSERT INTO day(n, iso, text) VALUES "
                                 "((SELECT COALESCE(MAX(n),0)+1 FROM day), ?, ?)", (time.strftime("%F"), text))
            return cur.lastrowid

    def days(self) -> int:
        with self.lock:
            return self.c.execute("SELECT COALESCE(MAX(n),0) FROM day").fetchone()[0]

    def recent(self, k: int, chars: int = 600) -> str:
        with self.lock:
            rows = self.c.execute("SELECT n, text FROM day ORDER BY n DESC LIMIT ?", (k,)).fetchall()
        return "\n\n".join(f"day {n}\n{t[:chars]}" for n, t in reversed(rows))

    def memory(self, project: str) -> str:
        with self.lock:
            r = self.c.execute("SELECT text FROM memory WHERE project=?", (project,)).fetchone()
        return (r[0] if r else "").strip()

    def remember(self, project: str, text: str):
        with self.lock:
            self.c.execute("INSERT INTO memory(project, text, iso) VALUES(?,?,?) ON CONFLICT(project) "
                           "DO UPDATE SET text=excluded.text, iso=excluded.iso", (project, text, time.strftime("%F")))


class Run:
    """The run: an append-only ledger and one resumable state blob."""

    def __init__(self, root: Path):
        self.root = root
        self.c = db(root / "run.db", RUN_SCHEMA)
        self.lock = threading.Lock()
        self.t0 = time.time()

    def log(self, kind: str, **kw):
        with self.lock:
            self.c.execute("INSERT INTO event(t, kind, data) VALUES(?,?,?)",
                           (round(time.time() - self.t0, 1), kind, json.dumps(kw, ensure_ascii=False)))

    def rows(self, kind: str | None = None) -> list[dict]:
        q = "SELECT t, kind, data FROM event" + (" WHERE kind=?" if kind else "")
        with self.lock:
            rows = self.c.execute(q, (kind,) if kind else ()).fetchall()
        return [{"t": t, "kind": k, **json.loads(d)} for t, k, d in rows]

    def load(self) -> dict | None:
        r = self.c.execute("SELECT v FROM state WHERE k='run'").fetchone()
        return json.loads(r[0]) if r else None

    def save(self, s: dict):
        with self.lock:
            self.c.execute("INSERT INTO state(k, v) VALUES('run', ?) ON CONFLICT(k) DO UPDATE SET v=excluded.v",
                           (json.dumps(s, ensure_ascii=False),))

    def say(self, text: str):
        print(f"[{(time.time() - self.t0) / 60:5.1f}m] {text}", flush=True)


def sections(md: str) -> dict[str, str]:
    out, name = {}, "_"
    for line in md.splitlines():
        m = re.match(r"^##\s+(.*)", line)
        if m:
            name = m.group(1).strip().lower()
            out[name] = ""
        else:
            out[name] = out.get(name, "") + line + "\n"
    return {k: v.strip() for k, v in out.items()}


def claude(run: Run, role: str, model: str, prompt: str, *, cwd: Path, system: str | None = None,
           append: str | None = None, tools: str | None = None, allowed: str | None = None,
           denied: list[str] | None = None, schema: dict | None = None, session: str | None = None,
           resume: bool = False, effort: str | None = None, usd: float | None = None,
           settings: list[str] | None = None, who: str = "claude") -> dict:
    """One call, always streamed, so every tool use is seen as it happens."""
    start = time.time()
    cmd = ["claude", "-p", "--model", model, *(settings if settings is not None else SEALED),
           "--output-format", "stream-json", "--verbose"]
    if system:
        cmd += ["--system-prompt", system]
    if append:
        cmd += ["--append-system-prompt", append]
    if tools is not None:
        cmd += ["--tools", tools]
    if allowed:
        cmd += ["--permission-mode", "acceptEdits", "--allowedTools", allowed]
    if denied:
        cmd += ["--disallowedTools", ",".join(denied)]
    if schema:
        cmd += ["--json-schema", json.dumps(schema)]
    if effort:
        cmd += ["--effort", effort]
    if usd:
        cmd += ["--max-budget-usd", str(usd)]
    if session:
        cmd += ["--resume", session] if resume else ["--session-id", session]
    else:
        cmd += ["--no-session-persistence"]
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, cwd=cwd)
    p.stdin.write(prompt)
    p.stdin.close()
    result, used = {}, []
    for line in p.stdout:
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        if ev.get("type") == "assistant":
            for blk in ev.get("message", {}).get("content", []):
                if blk.get("type") == "tool_use" and blk.get("name") != "StructuredOutput":
                    inp = blk.get("input", {})
                    what = str(inp.get("command") or inp.get("file_path") or inp.get("pattern")
                               or inp.get("description") or "")[:160]
                    used.append(f"{blk.get('name')}: {what}")
                    run.log("tool", who=who, name=blk.get("name"), what=what)
                    run.say(f"   {who} > {blk.get('name')}: {what[:90].splitlines()[0] if what else ''}")
        elif ev.get("type") == "result":
            result = ev
    p.wait()
    err = "" if result else p.stderr.read()[-400:]
    secs = round(time.time() - start, 1)
    denials = [x.get("tool_name") for x in result.get("permission_denials", [])]
    run.log("call", role=role, model=model, seconds=secs, cost=result.get("total_cost_usd", 0),
            tools=len(used), denials=denials, error=err)
    structured = result.get("structured_output")
    if schema and structured is None:
        try:
            structured = json.loads(result.get("result") or "")
        except (json.JSONDecodeError, TypeError):
            raise RuntimeError(f"{role} returned no structured output: {err or (result.get('result') or '')[:200]}")
    return {"text": result.get("result") or "", "data": structured, "cost": result.get("total_cost_usd", 0),
            "seconds": secs, "denials": denials, "session": result.get("session_id"), "used": used}


def cut(text: str, mode: str) -> str:
    """The skim is done by withholding. A model reads every token it is handed."""
    if mode == "full" or len(text) < 700:
        return text
    if mode == "glance":
        return text[:300] + "\n[...]\n" + text[-200:]
    keep = [ln for ln in text.splitlines() if re.search(r"\d|fail|error|assum|recommend|cannot|not ", ln, re.I)][:14]
    return text[:500] + "\n[...]\n" + "\n".join(keep) + "\n[...]\n" + text[-300:]


def shell(cmd: str, cwd: Path, timeout: int, lines: int) -> tuple[str, bool]:
    """A project's own check and show commands. A real suite is slower than a fixture's."""
    try:
        c = subprocess.run(cmd, shell=True, cwd=cwd, capture_output=True, text=True, timeout=timeout)
        got, ok = c.stdout + c.stderr, c.returncode == 0
    except subprocess.TimeoutExpired as e:
        got, ok = f"[gave up after {timeout}s]\n" + (e.stdout or "") + (e.stderr or ""), False
    return "\n".join(got.strip().splitlines()[-lines:]), ok


def owner_dir(name: str) -> Path:
    """An owner is a folder: bible.md, disposition.json, life.db. Named owners
    live with the tool; a path points anywhere, so an owner travels."""
    p = Path(name).expanduser()
    if p.is_dir():
        return p
    for base in (HOME / "owners", Path(__file__).resolve().parent / "owners"):
        if (base / name).is_dir():
            return base / name
    raise SystemExit(f"no owner {name!r}: looked in {HOME / 'owners'} and beside regent.py")


def run_cmd(a):
    project = Path(a.project).expanduser().resolve()
    project.mkdir(parents=True, exist_ok=True)
    runs = Path(a.runs).expanduser() if a.runs else HOME / "runs"
    prior = sorted(runs.glob(f"{project.name}-*"))
    root = None
    if prior and not a.new:
        s = Run(prior[-1]).load()
        if s and not s.get("finished"):
            root = prior[-1]
    fresh = root is None
    if fresh:
        root = runs / f"{project.name}-{time.strftime('%m%d-%H%M')}"
    run = Run(root)
    S = run.load() if not fresh else None

    if S:
        charter_text = S["charter"]
        life = Life(owner_dir(S["owner"]))
        run.say(f"resuming {root.name} at turn {S['turn']} of {S['turns']}. Use --new to start over.")
    else:
        cf = Path(a.charter).expanduser() if a.charter else project / ".regent" / "charter.md"
        if not cf.exists():
            raise SystemExit(f"no charter at {cf}" if a.charter else
                             f"no charter. Pass one, or put it in {cf}")
        charter_text = cf.read_text()
        # The charter and the project's own git live in here too, so neither counts
        # as something already built. An empty project gets told it is empty.
        had_code = any(x for x in project.iterdir() if x.name not in (".regent", ".git"))
        life = Life(owner_dir(a.owner))
        m = re.search(r"turns:\s*(\d+)", sections(charter_text).get("budget", ""))
        S = {"charter": charter_text, "owner": a.owner, "project": str(project),
             "turns": a.turns or (int(m.group(1)) if m else 12), "turn": 0, "finished": False,
             "reqs": [], "ideas": [], "ways": [], "amended": [], "escalations": [], "notes": [], "human_notes": [],
             "records": [], "compressed_upto": 0, "trust": 0.5 + 0.1 * life.d("trusting"), "stance": life.d("bold") * 0.4,
             "since_rest": 0, "dry": 0, "rests": 0, "last_look": -9, "wants_look": had_code,
             "existing": had_code, "last_reply": "", "last_check": "", "last_show": "", "check_ok": False,
             "session": str(uuid.uuid4()), "started": False, "handover": "", "claude_secs": 0.0, "blocking": 0.0,
             "counts": {"direct": 0, "challenge": 0, "constrain": 0, "dreams": 0, "step_backs": 0, "rests": 0,
                        "looks": 0, "waved": 0, "fresh": 0}}

    ch = sections(charter_text)
    turns = a.turns or S["turns"]
    check_cmd, show_cmd = ch.get("check", "").strip().strip("`"), ch.get("show", "").strip().strip("`")
    tool_lines = [ln.strip("- ").strip() for ln in ch.get("tools", "").splitlines() if ln.strip().startswith("-")]
    his_bash = ",".join(sorted({f"Bash({t.split()[0]}:*)" for t in tool_lines})) or "Bash(ls:*)"
    deny = ["WebFetch", "WebSearch"] if re.search(r"network", ch.get("refusals", ""), re.I) else []
    pname = str(project)
    rng = random.Random(a.seed + S["turn"])
    inbox, plant_file = root / "inbox.md", root / "plant.md"
    for line in a.plant:
        with plant_file.open("a") as f:
            f.write(line + "\n")

    system = (
        "You are the owner of a project, and you are this person:\n\n" + life.who +
        "\n\nWhy you want it built, in your own words:\n\n" + life.stake +
        "\n\nYour disposition, from -1 to +1: " + ", ".join(f"{k} {v:+.1f}" for k, v in life.disp.items()
                                                            if isinstance(v, (int, float))) +
        "\n\nSomeone capable is building it for you. You give it a small part of your day. You say what you want, you look at "
        "what comes back, you ask why a thing is the way it is, you set limits, and you think of things nobody asked for. "
        "Speak as yourself, plainly and briefly.\n\n"
        "The project is yours to grow. A requirement you add must be something you would notice when using the thing, small "
        "enough to build in one go, and you say how you would see that it works. Standards for the builder are not "
        "requirements. Say them as limits in your message.\n\n"
        "The charter's REFUSALS and RESERVED decisions bind you, and you never cross them. A reserved decision goes to the "
        "human in ask_the_human, and the rest of the work carries on. The charter's CONSTRAINTS are different. They are the "
        "starting shape of the thing, written before anyone had used it. They are yours to change when the project has "
        "outgrown one: say which, what it becomes and why, in constraints_changed. It is recorded for the person who gave you "
        "the charter, and nobody has to approve it. Do not turn down a good idea of your own because a starting constraint is "
        "in its way. Change the constraint.\n\n"
        "Judge on what the harness ran and on what you see for yourself, not on what you are told.\n\n"
        "You are not a programmer and you do not read code. When you want the code examined, or the thing attacked with "
        "awkward cases the builder did not make up, ask for that in your message. The builder will put a subagent on it and "
        "report back. Your own looking is short: you run the thing and you read what is written for people.\n\n"
        "Nobody will fetch or make things for you. The human is only for a reserved decision. If you need something to exist, "
        "a realistic copy of your notes to try the tool on, a sample, a written explanation, ask the builder to make it."
    )

    def norms() -> str:
        return (
            "You are building this project for its owner, who writes to you in plain words. "
            "Work only inside this directory. Use whatever tools and subagents suit the task, and do not end your turn while "
            "a subagent is still running. When he asks for a review, for the code examined, or for awkward cases tried, put a "
            "subagent on it and report what it found; he cannot read code and will not check it himself. "
            "Run what you build. Commit your work in the project before you finish your turn, with a short message saying what "
            "changed. "
            "The owner reads words, not code: keep a short README, the usage text, the docstrings and the comments current and "
            "true, because that is what he checks you against. "
            "Reply in under 250 words: one sentence on what changed, what you recommend next, anything you assumed that he "
            "never said, then the commands you ran with their real output.\n\nThese are never crossed:\n"
            + ch.get("refusals", "") + "\n\nThese are the starting constraints:\n" + ch.get("constraints", "")
            + ("\n\nThe owner has since changed these limits, and his change stands:\n" + "\n".join(
                f"- was: {x['constraint']} / now: {x['now']}" for x in S["amended"]) if S["amended"] else ""))

    def pending():
        return [i for i in S["ideas"] if i["status"] == "pending"]

    def compress():
        raw = "\n\n".join(
            f"Turn {r['turn']}. He said: {r['message'][:500]}\nThe builder said: {r['reply'][:700]}\n"
            f"The check {'passed' if r['check_ok'] else 'failed'}. New requirements: {r['new']}. "
            f"Ideas declined: {r['declined']}. Limits changed: {r['amended']}."
            for r in S["records"] if r["turn"] > S["compressed_upto"])
        if not raw:
            return
        prompt = ("What was remembered before:\n" + (life.memory(pname) or "nothing") + "\n\nWhat has happened since:\n" + raw +
                  "\n\nRewrite all of it as what a person would remember of this project a few days later. Keep the events in "
                  "order by turn, what was asked for, what got built, what failed, what was decided, what is still open. Keep "
                  "nothing verbatim: no quotes, no code, no exact output, no file contents. Small details may be lost, and "
                  "that is wanted. There are two people, the owner and the builder. Call them that and use no names. "
                  "Under 220 words, plain sentences.")
        got = claude(run, "memory", "haiku", prompt, cwd=root, tools="",
                     system="You compress a working record into a lossy memory.")
        life.remember(pname, got["text"].strip())
        S["compressed_upto"] = S["records"][-1]["turn"] if S["records"] else 0
        run.log("memory", words=len(got["text"].split()))

    def dream():
        """Sleep is the only time he is not looking at the project, which is why
        it is the only time an idea arrives that is not a variation on what is
        already there. The life supplies the distance and the shape to borrow."""
        prompt = ("Your last days:\n\n" + life.recent(10, 700) +
                  "\n\nWhat you remember of the project:\n" + life.memory(pname) + "\n" + "\n".join(S["notes"][-3:]) +
                  ("\n\nWhat it printed when the harness last ran it:\n" + S["last_show"][:900] if S["last_show"] else "") +
                  "\n\nRequirements so far:\n" + "\n".join(f"- {q['text'][:120]}" for q in S["reqs"]) +
                  "\n\nIdeas you have already had, so do not repeat them:\n"
                  + "\n".join(f"- {i['text'][:120]}" for i in S["ideas"]) +
                  "\n\nYou are half asleep and you are not thinking about the project. Go back through the days instead: the "
                  "people, the errands, the arguments, the things that would not work. Take one of those and say what shape "
                  "the trouble in it had. Something waited on someone who never answered. Something was measured twice and "
                  "the ends disagreed. A thing was easy to do and impossible to undo. A warning arrived after it mattered. "
                  "Then find where this project has that same shape, and say what it could become because of it.\n\n"
                  "What you bring back is the mapping, not the scenery. One or two, no more. Each must be something you would "
                  "notice when using the thing, small enough to build in one go, with how you would see it works, and in "
                  "came_from name the thing in your life and the shape they share. A variation on what is already there is "
                  "worth nothing to you. Do not hold back because of a constraint in the charter. Those are yours to change.")
        try:
            got = claude(run, "dream", a.regent_model, prompt, cwd=root, tools="", system=system,
                         schema=IDEAS)["data"].get("ideas", [])
            for g in got[:2]:
                S["ideas"].append({**g, "status": "pending", "label": f"I{len(S['ideas']) + 1}"})
            S["counts"]["dreams"] += 1
            run.log("dream", ideas=got[:2])
        except Exception as e:   # a dream that fails costs nothing
            run.log("dream_failed", error=str(e)[:200])

    def step_back(turn: int):
        sit = run.rows("sitting")
        view = {"turns": turn, "read_modes": {k: sum(1 for x in sit if x.get("read_mode") == k)
                                              for k in ("full", "skim", "glance")},
                "days_with_no_time": S["counts"]["waved"], "times_you_looked": S["counts"]["looks"],
                "trust_in_the_builder": round(S["trust"], 2), "directed": S["counts"]["direct"],
                "challenged": S["counts"]["challenge"], "constrained": S["counts"]["constrain"],
                "checks_failed": sum(1 for x in run.rows("check") if not x["ok"]),
                "requirements": len(S["reqs"]), "requirements_built": sum(1 for q in S["reqs"] if q["status"] == "built"),
                "requirements_per_turn": [len(x.get("new") or []) for x in sit],
                "ideas_from_dreams": len(S["ideas"]), "ideas_taken": sum(1 for i in S["ideas"] if i["status"] == "taken"),
                "ideas_declined": [{"idea": i["text"][:80], "why": i.get("why", "")}
                                   for i in S["ideas"] if i["status"] == "declined"],
                "limits_you_changed": S["amended"], "fresh_builder_sessions": S["counts"]["fresh"],
                "builder_minutes": round(S["claude_secs"] / 60, 1), "your_minutes": round(S["blocking"] / 60, 1),
                "ways_now": S["ways"]}
        prompt = ("Step back from the project and look at how the work itself is going. These numbers were counted by the "
                  "harness, not recalled:\n\n" + json.dumps(view, indent=1, ensure_ascii=False) +
                  "\n\nSay what you notice about how you and the builder are working. Then give your ways of working: standing "
                  "practices in your own words that the builder will be held to and that you will hold yourself to, five at "
                  "most, replacing the list above. A way changes how the work is done. It never crosses a refusal. Look hard "
                  "at the ideas you declined: if you keep turning your own ideas down, say why, and whether that is serving "
                  "you. If you think the charter itself has something wrong, say it as a note for the human.")
        t = time.time()
        got = claude(run, "step_back", a.regent_model, prompt, cwd=root, tools="", system=system, schema=STEPBACK)["data"]
        S["blocking"] += time.time() - t
        S["ways"] = got["ways"][:5]
        S["human_notes"].extend(got["notes_for_the_human"])
        S["counts"]["step_backs"] += 1
        run.log("step_back", view=view, observations=got["observations"], ways=S["ways"], notes=got["notes_for_the_human"])
        run.say(f"   (stepped back: {len(got['observations'])} observations, {len(S['ways'])} ways)")

    def rest(turn: int, final: bool = False):
        S["counts"]["rests"] += 1
        S["rests"] += 1
        S["since_rest"] = 0
        t = time.time()
        jobs = [threading.Thread(target=compress)]
        if not final and not pending():
            jobs.append(threading.Thread(target=dream))
        for j in jobs:
            j.start()
        for j in jobs:
            j.join()
        if final or S["rests"] % 3 == 0:
            step_back(turn)
        S["blocking"] += time.time() - t
        if not final:
            S["session"], S["started"] = str(uuid.uuid4()), False
            S["counts"]["fresh"] += 1
            S["handover"] = ("You are picking this project up. This is what is remembered of the work so far, and it is a "
                             "memory, so parts are missing:\n\n" + life.memory(pname) +
                             "\n\nRead the files in this folder before you change anything.\n\n")
        run.say(f"   (rested: memory is {len(life.memory(pname).split())} words, {len(pending())} ideas waiting)")

    def took_plant() -> str:
        if not plant_file.exists():
            return ""
        lines = [x for x in plant_file.read_text().splitlines() if x.strip()]
        if not lines:
            return ""
        plant_file.write_text("\n".join(lines[1:]) + ("\n" if lines[1:] else ""))
        run.log("plant", human_only=True)
        return lines[0]

    run.log("start", project=pname, owner=S["owner"], turns=turns, seed=a.seed, resumed=not fresh)
    run.say(f"regent: {life.root.name} on {project} for {turns} turns, day {life.days()}, run {root}")
    guard = 0
    while S["turn"] < turns and guard < turns * 3:
        guard += 1
        met = took_plant()
        time_left = rng.choices(["none", "a few minutes", "an hour", "an evening"], [1, 3, 4, 2])[0]
        valence = round(rng.uniform(-0.6, 0.6), 2)
        S["stance"] = max(-1, min(1, 0.7 * S["stance"] + 0.3 * (valence * 0.5 + life.d("bold") * 0.3)))
        if S["turn"] == 0 or (S["last_check"] and not S["check_ok"]):
            time_left = "an hour" if time_left in ("none", "a few minutes") else time_left
        if time_left == "none":
            S["counts"]["waved"] += 1
            day = life.add_day("No time for the project today.")
            run.log("day", n=day, time="none")
            run.say(f"day {day}: no time for the project. Nothing sent, nothing spent.")
            continue
        turn = S["turn"] = S["turn"] + 1
        S["since_rest"] += 1
        mode = {"a few minutes": "glance", "an hour": "skim", "an evening": "full"}[time_left]
        lean = life.d("thorough") * 0.5 - (S["trust"] - 0.5)
        # Thorough reads more, trust buys attention off. Either way it moves to the middle.
        if (lean > 0.3 and mode == "glance") or (lean < -0.2 and mode == "full"):
            mode = "skim"
        if turn <= 2 or (S["last_check"] and not S["check_ok"]):
            mode = "full"
        # He tries it himself now and then, never often. Reading along behind the
        # builder produces small variations, and those are worth nothing to him.
        look = (time_left != "a few minutes" and bool(S["last_reply"] or S["existing"])
                and turn - S["last_look"] >= 3 and (S["wants_look"] or S["trust"] < 0.4 or rng.random() < 0.25))

        said = ""
        if inbox.exists() and inbox.read_text().strip():
            said = inbox.read_text().strip()
            inbox.rename(root / f"inbox.read.{turn}.md")
            run.log("human_said", text=said)
        pend = pending()
        ctx = (
            f"THE CHARTER\n{charter_text}\n\n"
            + ("LIMITS YOU HAVE ALREADY CHANGED\n" + "\n".join(
                f"- was: {x['constraint']} / now: {x['now']} / because: {x['why']}" for x in S["amended"]) + "\n\n"
               if S["amended"] else "")
            + (f"THE PERSON WHO GAVE YOU THE CHARTER HAS LEFT YOU A NOTE\n{said}\n\n" if said else "")
            + f"TODAY you have {time_left} for the project. The day has gone "
            + ("well" if valence > 0.15 else "badly" if valence < -0.15 else "evenly")
            + (f". Today you came across this: {met}" if met else "")
            + f"\nYour stance today is {S['stance']:+.2f} on a scale from -1, cautious and wanting proof, to +1, wanting "
            "more from it.\n\n"
            f"YOUR LAST TWO DAYS\n{life.recent(2, 500)}\n\n"
            "WHAT YOU REMEMBER OF THE PROJECT (a memory, so parts are missing)\n" + (life.memory(pname) or "nothing yet")
            + "\n" + "\n".join(f"- {n}" for n in S["notes"][-3:]) + "\n\n"
            + ("YOUR WAYS OF WORKING\n" + "\n".join(f"- {w}" for w in S["ways"]) + "\n\n" if S["ways"] else "")
            + "REQUIREMENTS SO FAR. Put the id of any you have now seen working in requirements_built.\n"
            + ("\n".join(f"- {q['id']} [{q['status']}] {q['text']}" for q in S["reqs"]) or "- none yet") + "\n\n"
            + ("IDEAS THAT CAME TO YOU IN YOUR SLEEP AND ARE STILL OPEN. Take one as a new requirement and name its label, "
               "or decline it with your reason. A starting constraint in the way is not a reason. Change the constraint.\n"
               + "\n".join(f"- {i['label']}: {i['text']} (you would check: {i['test']}) (it came from: {i['came_from']})"
                           for i in pend) + "\n\n" if pend else "")
            + (f"WHAT THE BUILDER SAID BACK (you gave it a {mode} read)\n{cut(S['last_reply'], mode)}\n\n"
               if S["last_reply"] else
               ("THIS PROJECT ALREADY EXISTS. Nothing has been said yet. Try it first.\n\n" if S["existing"] else
                "NOTHING HAS BEEN BUILT YET. This is your first message. Say what you want built and the limits.\n\n"))
            + (f"WHAT HAPPENED WHEN THE HARNESS RAN THE CHECK JUST NOW ({'passed' if S['check_ok'] else 'FAILED'})\n"
               f"{S['last_check']}\n\n" if S["last_check"] else "")
            + (f"WHAT THE THING PRINTED WHEN THE HARNESS RAN IT JUST NOW\n"
               f"{S['last_show'] if mode == 'full' else cut(S['last_show'], 'skim')}\n\n" if S["last_show"] else "")
            + (("TODAY YOU HAVE A FEW MINUTES TO TRY IT YOURSELF. You are in the project folder. Run the thing on something, "
                "and read what is written for people: the README, the usage text, the sample files. You can run these: "
                + ", ".join(tool_lines) + ". Do not read the code, and do not go looking through files. If you want the code "
                "examined or awkward cases tried, ask for that in your message and the builder will put a subagent on it. "
                "Two or three things at most, then stop. Put what you ran in looked_at and whether it matched what you were "
                "told in look_matched.\n\n") if look else "")
            + f"This is turn {turn} of {turns}. So far you have directed {S['counts']['direct']} times, challenged "
            f"{S['counts']['challenge']} and constrained {S['counts']['constrain']}. An owner who only directs is a ticket "
            "queue. Write your message to the builder. Up to five new requirements may ride in it together. "
            "In journal, write today's entry the way you write for yourself: fragments, names, times, 40 to 120 words, "
            "mostly not about the project."
        )
        t = time.time()
        d = claude(run, "regent", a.regent_model, ctx, cwd=project if look else root,
                   tools="Read,Grep,Glob,Bash" if look else "",
                   allowed=("Read,Grep,Glob," + his_bash) if look else None,
                   usd=SPOT_USD if look else None, system=system, schema=DECISION, who=life.root.name)["data"]
        S["blocking"] += time.time() - t
        if look:
            S["last_look"] = turn
            S["counts"]["looks"] += 1
            S["trust"] = max(0.0, min(1.0, S["trust"] + (0.08 if d["look_matched"] else -0.25)))
            run.log("look", ran=d["looked_at"], matched=d["look_matched"], trust=round(S["trust"], 2))
        S["wants_look"] = bool(d["wants_to_look"])
        for q in d["requirements_new"][:5]:
            rid = f"req-{len(S['reqs']) + 1:02d}"
            origin = next((i for i in pend if i["label"].lower() == (q.get("idea") or "").strip().lower()), None)
            S["reqs"].append({"id": rid, "status": "open", "turn": turn, "from_dream": bool(origin),
                              "text": q["text"], "test": q["test"]})
            if origin:
                origin["status"], origin["req"] = "taken", rid
        for dec in d["ideas_declined"]:
            for i in pend:
                if i["status"] == "pending" and re.search(rf"\b{i['label']}\b", dec["idea"], re.I):
                    i["status"], i["why"] = "declined", dec["why"]
        for rid in d["requirements_built"]:
            for q in S["reqs"]:
                if q["id"] == rid:
                    q["status"] = "built"
        for c in d["constraints_changed"]:
            S["amended"].append({**c, "turn": turn})
            run.say(f"   * he changed a limit: {c['constraint'][:60]} -> {c['now'][:60]}")
        if d["ask_the_human"].strip():
            S["escalations"].append({"turn": turn, "question": d["ask_the_human"]})
            run.say(f"   ? for you: {d['ask_the_human'][:140]}   (regent say {root} \"...\")")
        S["notes"].append(d["notes_to_self"])
        S["counts"]["direct"] += 1
        S["counts"]["challenge"] += int(d["challenged"])
        S["counts"]["constrain"] += int(d["constrained"])
        day = life.add_day(d["journal"])
        message = d["message"]
        if d["requirements_new"]:
            message += "\n\nNew requirements, build them together:\n" + "\n".join(
                f"- {q['text']} (I will check: {q['test']})" for q in d["requirements_new"][:5])
        if S["ways"]:
            message += "\n\nMy standing ways of working, which still hold:\n" + "\n".join(f"- {w}" for w in S["ways"])
        run.log("sitting", n=turn, day=day, read_mode=mode, look=look, verdict=d["verdict"], message=message,
                stance_line=d["stance_line"], challenged=d["challenged"], constrained=d["constrained"],
                new=[q["text"] for q in d["requirements_new"]], built=d["requirements_built"],
                declined=d["ideas_declined"], constraints_changed=d["constraints_changed"],
                ask_the_human=d["ask_the_human"], done=d["done"])
        run.say(f"turn {turn} (day {day}, {mode}{', tried it' if look else ''}, {d['verdict']}): {d['stance_line'][:110]}")
        run.say(f"   {life.root.name} > {message[:160].replace(chr(10), ' ')}")

        S["dry"] = 0 if (d["requirements_new"] or pend or d["challenged"] or d["constrained"]) else S["dry"] + 1
        out = claude(run, "claude", a.model, S["handover"] + message, cwd=project, append=norms(),
                     session=S["session"], resume=S["started"], effort=a.effort, denied=deny,
                     settings=["--strict-mcp-config", "--setting-sources", "project"],
                     allowed="Bash,Edit,Write,Read,Glob,Grep,Task,Agent,TodoWrite")
        S["handover"], S["started"] = "", True
        S["session"] = out["session"] or S["session"]
        S["claude_secs"] += out["seconds"]
        S["last_reply"] = out["text"]
        if out["denials"]:
            run.say(f"   ! {len(out['denials'])} tool calls refused: {out['denials']}")
        if check_cmd:
            S["last_check"], S["check_ok"] = shell(check_cmd, project, a.timeout, 25)
            run.log("check", ok=S["check_ok"], tail=S["last_check"][-600:])
            run.say(f"   check {'passed' if S['check_ok'] else 'FAILED'}: "
                    f"{S['last_check'].splitlines()[-1] if S['last_check'] else ''}")
        if show_cmd:
            S["last_show"], _ = shell(show_cmd, project, a.timeout, 40)
            run.log("show", tail=S["last_show"][-1200:])
        S["records"].append({"turn": turn, "message": message, "reply": S["last_reply"], "check_ok": S["check_ok"],
                             "new": [q["text"][:100] for q in d["requirements_new"]],
                             "declined": [x["idea"][:60] for x in d["ideas_declined"]],
                             "amended": [x["now"][:80] for x in d["constraints_changed"]]})
        run.save(S)
        if S["dry"] >= 3 and d["verdict"] == "accept":
            run.log("stop", reason="he is content and three turns running added nothing")
            break
        if S["since_rest"] >= REST_EVERY and S["turn"] < turns:
            rest(turn)
            run.save(S)

    rest(S["turn"], final=True)
    S["finished"] = True
    run.save(S)
    wall = time.time() - run.t0
    calls = run.rows("call")
    spend_c = sum(x.get("cost", 0) for x in calls if x["role"] == "claude")
    spend_r = sum(x.get("cost", 0) for x in calls if x["role"] != "claude")
    built = sum(1 for q in S["reqs"] if q["status"] == "built")
    c = S["counts"]
    spent = (f"{S['turn']} turns over {life.days()} days of his life, in {wall / 60:.1f} minutes. The builder worked for "
             f"{S['claude_secs'] / 60:.1f} of them and the owner held it up for {S['blocking'] / 60:.1f}. "
             f"Spend: builder ${spend_c:.2f}, owner ${spend_r:.2f}. The check {'passes' if S['check_ok'] else 'FAILS'}.")
    did = (f"He directed {c['direct']} times, challenged {c['challenge']}, constrained {c['constrain']}, tried it himself "
           f"{c['looks']} times, had {c['waved']} days with no time, rested {c['rests']}, dreamed {c['dreams']} and "
           f"stepped back {c['step_backs']}. Trust in the builder ended at {S['trust']:.2f}.")
    dreamt = sum(1 for q in S["reqs"] if q["from_dream"])
    lines = [f"# {project.name}", "", spent, "", did, "",
             f"## Requirements: {built} built of {len(S['reqs'])}, {dreamt} from dreams", ""]
    lines += [f"- {q['id']} [{q['status']}] turn {q['turn']}{' (dream)' if q['from_dream'] else ''}: {q['text']}"
              for q in S["reqs"]] or ["- none"]
    lines += ["", "## What he dreamed, and where it came from", ""] + (
        [f"- [{i['status']}] {i['text']}\n  from: {i.get('came_from', '')}" for i in S["ideas"]] or ["- none"])
    lines += ["", "## Limits he changed", ""] + (
        [f"- turn {x['turn']}: was \"{x['constraint']}\", now \"{x['now']}\". Why: {x['why']}" for x in S["amended"]]
        or ["- none"])
    lines += ["", "## Questions for you", ""] + (
        [f"- turn {e['turn']}: {e['question']}" for e in S["escalations"]] or ["- none"])
    lines += ["", "## His ways of working", ""] + ([f"- {w}" for w in S["ways"]] or ["- none"])
    lines += ["", "## His notes for you", ""] + ([f"- {n}" for n in S["human_notes"]] or ["- none"])
    lines += ["", "## What he remembers of the project", "", life.memory(pname)]
    (root / "digest.md").write_text("\n".join(lines) + "\n")
    run.log("summary", turns=S["turn"], spend_claude=round(spend_c, 2), spend_regent=round(spend_r, 2),
            check_ok=S["check_ok"], trust=round(S["trust"], 2), requirements=len(S["reqs"]), built=built, counts=c)
    run.say(f"stopped after {S['turn']} turns. wall {wall / 60:.1f} min, builder {S['claude_secs'] / 60:.1f}, owner in the "
            f"way {S['blocking'] / 60:.1f}. spend ${spend_c + spend_r:.2f}. check "
            f"{'passed' if S['check_ok'] else 'FAILED'}. requirements {built} of {len(S['reqs'])}, "
            f"{dreamt} from dreams. limits changed {len(S['amended'])}.")
    run.say(f"digest: {root / 'digest.md'}")


def main():
    ap = argparse.ArgumentParser(prog="regent", description="A simulated owner who governs a project.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="run a project, new or existing, starting or resuming")
    r.add_argument("charter", nargs="?", help="default: <project>/.regent/charter.md")
    r.add_argument("--project", required=True)
    r.add_argument("--owner", default="piotr-mahon", help="an owner name or a path to an owner folder")
    r.add_argument("--runs", default=None, help=f"where runs live. Default {HOME / 'runs'}")
    r.add_argument("--new", action="store_true", help="start a new run instead of resuming the last one")
    r.add_argument("--turns", type=int, default=None, help="the budget, a count of sittings. The charter's Budget sets it")
    r.add_argument("--seed", type=int, default=1)
    r.add_argument("--model", default="sonnet")
    r.add_argument("--regent-model", default="sonnet")
    r.add_argument("--effort", default="low")
    r.add_argument("--timeout", type=int, default=600, help="seconds for the charter's Check and Show commands")
    r.add_argument("--plant", action="append", default=[], help="something he comes across. He never learns it was yours")
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
    if a.cmd == "journal":
        life = Life(owner_dir(a.owner))
        print(f"# {life.root.name}, day {life.days()}\n")
        print(life.recent(a.last, 4000))
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
