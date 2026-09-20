#!/usr/bin/env python3
"""Regent: a simulated owner who governs a project over days of his life.

One process. It holds the regent, a person with a life, a mood and a memory,
and it runs Claude Code in the project on his behalf. A sitting is one regent
call, then one Claude turn. Nothing else sits in Claude's path.

    regent cast --pin "impatient, generous, cannot leave a loose end"
    regent run --project ~/code/thing --days 10 --turns-per-day 1.5
    regent say <run> "a note from you, shown at his next sitting"
    regent plant <run> "something he comes across, never traced to you"
    regent journal piotr-mahon

The unit is a day. The dice decide how the day went, how many sittings the
project gets and how long each one is; models write the prose. Awake he is an
owner, not a reviewer: he directs, challenges, sets limits, uses the thing, and
asks the builder for a review when he wants one, because the builder has
subagents for that.

At night the work he cannot be asked to do happens without him. Nobody dreams
on request, so he is never asked to. The spoon cycle is four runs that are not
him. Saturate reads the project and his days and extracts what runs through
them, answering nothing. Drift, a different run, links things that nobody would
file together, every link anchored in the project and reaching into his life
or anything else it knows, mechanism over imagery. Catch is the falling spoon,
in code: the pass ends when the links let go of the project. Sift reads what
was caught as an anonymous list in a context that never saw it made, and keeps
a few as things the project could become. He meets those awake, takes them or
turns them down, and that is the gate. Consolidate is the forgetting: his
memory of the project is rewritten lossy, and what he declined goes on his
taste record so it is not dreamt twice.

Every cadence here is a draw from a distribution, never a count. The first
harness is in archive/: 10,914 lines and 224 tunables. Read it before adding
a module.
"""
from __future__ import annotations

import argparse
import http.server
import json
import math
import os
import random
import re
import sqlite3
import subprocess
import sys
import threading
import time
import uuid
import webbrowser
from pathlib import Path

HOME = Path(os.environ.get("REGENT_HOME", Path.home() / ".regent"))
SEALED = ["--strict-mcp-config", "--setting-sources", ""]  # no tools, no servers, no settings
SPOT_USD = 0.10   # a spot check is a glance. The CLI enforces it, so no limiter here.
# Every call that is not the builder replaces Claude Code's system prompt. This is what the night runs get.
PLAIN = ("You are one stage of a longer process, not an assistant in a conversation and not a programmer. "
         "Do what the message asks, in the form it asks for, and add nothing around it.")
DIALS = ("bold", "curious", "patient", "trusting", "thorough", "stubborn", "restless")

STR, BOOL = {"type": "string"}, {"type": "boolean"}


def arr(x: dict) -> dict:
    return {"type": "array", "items": x}


def obj(**props) -> dict:
    return {"type": "object", "properties": props, "required": list(props)}


DECISION = obj(
    stance_line=STR, verdict={"type": "string", "enum": ["continue", "accept", "reject"]}, message=STR,
    challenged=BOOL, constrained=BOOL, requirements_new=arr(obj(text=STR, test=STR, idea=STR)),
    requirements_built=arr(STR), ideas_declined=arr(obj(idea=STR, why=STR)),
    constraints_changed=arr(obj(constraint=STR, now=STR, why=STR)), ask_the_human=STR,
    wants_to_look=BOOL, looked_at=arr(STR), look_matched=BOOL, notes_to_self=STR, done=BOOL)
MOTIFS = obj(motifs=arr(STR), tensions=arr(STR), questions=arr(STR))
LINKS = obj(links=arr(obj(kind={"type": "string", "enum": ["metaphor", "causal analogy", "structural analogy", "seed"]},
                          text=STR, anchors=arr(STR), other=STR, mechanism=STR)))
SIFTED = obj(candidates=arr(obj(text=STR, test=STR, from_indexes=arr({"type": "integer"}), why_it_might_fail=STR)))
STEPBACK = obj(observations=arr(STR), ways=arr(STR), notes_for_the_human=arr(STR))
CAST = obj(name=STR, slug=STR, bible=STR, events=arr(STR))
EVENTS = obj(events=arr(STR))

SATURATE_P = """Read all of this and extract what runs through it. Answer nothing.

THE PROJECT, as its owner holds it. Each element has an id.
{project}

THE OWNER'S RECENT DAYS
{life}

Extract three things. Motifs: a shape that recurs in more than one place, in the project or across the project and the
days. Tensions: two things here that pull against each other. Questions: what this raises and does not settle.
Prefer the motif nobody has named yet. Do not answer the questions, propose work, recommend or rank."""

DRIFT_P = """Produce about {target} links between things that do not obviously belong together.

MOTIFS FROM THIS CYCLE
{motifs}

THE PROJECT. Each element has an id beginning with p.
{project}

A LIFE. The person this project belongs to, and some of their days, drawn at random. Day ids begin with L.
{bible}

{days}

The life is fuel. It is not evidence and it settles nothing. It is where a bridge comes from that the project could not
have supplied on its own, because everything in the project is already filed next to everything else in it.

No problem is attached to this pass. Do not invent one to aim at. The disposition tonight is {stance}: risk-weighted
leans toward what fails, what has no limit, what happens twice; opportunity-weighted leans toward what this could also
be, which two parts are really one thing, who else it serves. Both are wanted. The lean tilts the mix.

A link is two elements nobody would file together, plus the thing that transfers between them. Every link names at
least one project id in anchors. A link with none is discarded, and the pass ends when they keep coming, so anchor in
the project and then reach. In other, name what it was joined to: a day id, a person or place from the life, or
"outside: <domain>" for anything you already know. Reach anywhere: queueing, metallurgy, epidemiology, shipping,
typesetting, funerals, allotments. Mechanism over imagery, always. A link that imports how one thing's machinery would
work in the other's place is worth fifty that observe two things are alike. State the transferable mechanism in one
line, or leave it empty when the link is only an image. Do not link the same pair twice."""

SIFT_P = """Evaluate a list of proposals from an unknown source. You have not seen it before and know nothing about who
wrote it or why. Judge each on what it says, not how it is phrased.

THE LIST, numbered from 0
{holding}

WHAT IS BEING BUILT AND WHO IT IS FOR
{intent}

NEVER CROSSED
{refusals}

WHAT IT ALREADY DOES
{built}

WHAT ITS OWNER HAS TAKEN AND TURNED DOWN BEFORE, AND WHY
{taste}

Weigh each proposal on novelty (how far from what anyone working on this would already have written down), mechanism
(does it name machinery that transfers and acts, or only a resemblance), leverage (how much changes if it is right) and
cost. Where proposals share a mechanism, combine them into one candidate that carries it once.

Keep at most {keep}, and fewer if fewer are good. Do not solve the builder's problems. That is the builder's job. The
question is what this could become, and what it is missing for the person it is for. Write each survivor as a
requirement: something that person would notice when using the thing, small enough to build in one go, with in test how
they would see that it works. Nothing that crosses a refusal, nothing that repeats what it does, nothing he has turned
down. In why_it_might_fail name the specific way it is wrong, not a general caution. An empty list is a fine answer."""

DAY_P = """Write one day of this person's journal, the way they write for themselves: fragments, dropped subjects, times,
names, a line someone said, a thing left hanging. {words} words. No scene-setting, no summary, no reflection, no lesson.

WHO THEY ARE
{bible}

HOW THEIR LAST DAYS ENDED, for continuity only
{recent}

Their standing routines are in the bible and already in the journal many times over: the waking, the first drink, who
sits where, the commute, the usual lunch, the usual supper. None of it is written again unless today it broke. Begin in
the middle, at the first thing the dice rolled. A day is what differed.

WHAT THE DICE ROLLED FOR TODAY. Every one of these is in the entry.
- The day went {valence}.
{rolled}
- One of their open threads moves a little, or pointedly does not.

THE PROJECT TODAY
{project}
What they write about it comes only from the lines above, never invented, and it is at most a quarter of the entry."""

CAST_P = """Write a person. The dice are rolled and you hold what they rolled. You supply the prose.

Age {age}. Disposition, each from -1 to +1: {dials}.
Each of these words turns up somewhere in their life, as an object, a place, a name or a trade: {words}.
Pinned by the human, and these win over everything else: {pins}

They will own a small software project one day and know nothing about software. Their work and their life are far from
it, and that distance is the point. Nobody designed this person: no tidy arc, no quirks for show, money and family and
a body that has a history.

bible is markdown with exactly these headings: "## Who this is" (work, home, habits, money, how they talk and what they
are like to work for, fitted to the disposition without naming it), "## The cast" (six to eight people, each with
unfinished business), "## Places" (four, with what is broken in each), "## History", "## Open threads" (six to nine
things left hanging). 800 to 1100 words. name is their full name and slug is it in lowercase with hyphens.

events is sixty short lines: things that could happen in one of this person's weeks, tied to their places and people,
small and concrete, most of them mundane and some of them going wrong. None about software."""


def poisson(rng: random.Random, mean: float) -> int:
    limit, k, p = math.exp(-mean), 0, rng.random()
    while p > limit:
        k, p = k + 1, p * rng.random()
    return k


def due(rng: random.Random, since: float, mean_gap: float) -> bool:
    """A hazard, not a schedule: the longer since it last happened, the likelier it is tonight."""
    return rng.random() < 1 - math.exp(-since / max(mean_gap, 0.2))


def clip(x: float, lo: float = -1.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def db(path: Path, schema: str) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(path, timeout=30, isolation_level=None, check_same_thread=False)
    c.execute("PRAGMA journal_mode=WAL")
    c.executescript(schema)
    return c


class Life:
    """An owner is a folder: bible.md, disposition.json, events.md, life.db. The
    folder is the whole person, so a regent is a thing you copy. The day number
    comes from the table itself, which is what stops two runs on two projects
    writing over the same day."""

    SCHEMA = """
    CREATE TABLE IF NOT EXISTS day(n INTEGER PRIMARY KEY, iso TEXT, text TEXT);
    CREATE TABLE IF NOT EXISTS memory(project TEXT PRIMARY KEY, text TEXT, iso TEXT);
    CREATE TABLE IF NOT EXISTS stake(project TEXT PRIMARY KEY, text TEXT);
    CREATE TABLE IF NOT EXISTS taste(id INTEGER PRIMARY KEY, project TEXT, verdict TEXT, idea TEXT, why TEXT);
    """

    def __init__(self, root: Path):
        self.root = root
        self.bible = (root / "bible.md").read_text()
        d = root / "disposition.json"
        self.disp = json.loads(d.read_text()) if d.exists() else {}
        self.c = db(root / "life.db", self.SCHEMA)
        self.lock = threading.Lock()

    def d(self, k: str) -> float:
        return float(self.disp.get(k, 0) or 0)

    @property
    def who(self) -> str:
        return self.bible.split("## The cast")[0][:1800]

    def q(self, sql: str, *args) -> list:
        with self.lock:
            return self.c.execute(sql, args).fetchall()

    def add_day(self, text: str) -> int:
        with self.lock:
            return self.c.execute("INSERT INTO day(n, iso, text) VALUES ((SELECT COALESCE(MAX(n),0)+1 FROM day), ?, ?)",
                                  (time.strftime("%F"), text)).lastrowid

    def days(self) -> int:
        return self.q("SELECT COALESCE(MAX(n),0) FROM day")[0][0]

    def recent(self, k: int, chars: int = 600, tail: bool = False) -> str:
        rows = self.q("SELECT n, text FROM day ORDER BY n DESC LIMIT ?", k)
        return "\n\n".join(f"day {n}\n{'...' + t[-chars:] if tail else t[:chars]}" for n, t in reversed(rows))

    def sample(self, rng: random.Random, k: int, chars: int = 700) -> str:
        """Days drawn without replacement, recent ones likelier, old ones never impossible. That is replay."""
        rows, top = self.q("SELECT n, text FROM day"), self.days()
        keyed = sorted(rows, key=lambda r: rng.random() ** (1 / math.exp(-(top - r[0]) / 40)), reverse=True)[:k]
        return "\n\n".join(f"L{n}: {t[:chars]}" for n, t in sorted(keyed))

    def get(self, table: str, project: str) -> str:
        r = self.q(f"SELECT text FROM {table} WHERE project=?", project)
        return (r[0][0] if r else "").strip()

    def put(self, table: str, project: str, text: str):
        self.q(f"INSERT OR REPLACE INTO {table}(project, text) VALUES(?,?)", project, text)

    def judged(self, project: str, verdict: str, idea: str, why: str):
        self.q("INSERT INTO taste(project, verdict, idea, why) VALUES(?,?,?,?)", project, verdict, idea, why)

    def taste(self, k: int = 15) -> str:
        rows = self.q("SELECT verdict, idea, why FROM taste ORDER BY id DESC LIMIT ?", k)
        return "\n".join(f"- {v}: {i[:140]}" + (f" Because: {w}" if w else "") for v, i, w in rows) or "nothing yet"

    def close(self):
        """Fold the write-ahead log back in, so copying the folder carries his whole life."""
        with self.lock:
            self.c.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            self.c.close()


class Run:
    """The run: an append-only ledger and one resumable state blob."""

    SCHEMA = """
    CREATE TABLE IF NOT EXISTS event(id INTEGER PRIMARY KEY, t REAL, kind TEXT, data TEXT);
    CREATE TABLE IF NOT EXISTS state(k TEXT PRIMARY KEY, v TEXT);
    """

    def __init__(self, root: Path):
        self.root = root
        self.c = db(root / "run.db", self.SCHEMA)
        self.lock = threading.Lock()
        self.t0 = time.time()

    def log(self, kind: str, **kw):
        with self.lock:
            self.c.execute("INSERT INTO event(t, kind, data) VALUES(?,?,?)",
                           (round(time.time() - self.t0, 1), kind, json.dumps(kw, ensure_ascii=False)))

    def rows(self, kind: str) -> list[dict]:
        with self.lock:
            rows = self.c.execute("SELECT data FROM event WHERE kind=?", (kind,)).fetchall()
        return [json.loads(d) for (d,) in rows]

    def load(self) -> dict | None:
        r = self.c.execute("SELECT v FROM state WHERE k='run'").fetchone()
        return json.loads(r[0]) if r else None

    def save(self, s: dict):
        with self.lock:
            self.c.execute("INSERT OR REPLACE INTO state(k, v) VALUES('run', ?)", (json.dumps(s, ensure_ascii=False),))

    def say(self, text: str):
        print(f"[{(time.time() - self.t0) / 60:5.1f}m] {text}", flush=True)

    def close(self):
        with self.lock:
            self.c.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            self.c.close()


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
    for flag, val in (("--system-prompt", system), ("--append-system-prompt", append), ("--tools", tools),
                      ("--disallowedTools", ",".join(denied or [])), ("--json-schema", schema and json.dumps(schema)),
                      ("--effort", effort), ("--max-budget-usd", usd and str(usd))):
        if val or (flag == "--tools" and val is not None):
            cmd += [flag, val]
    if allowed:
        cmd += ["--permission-mode", "acceptEdits", "--allowedTools", allowed]
    if session:
        cmd += ["--resume", session] if resume else ["--session-id", session]
    else:
        cmd += ["--no-session-persistence"]
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, cwd=cwd)
    p.stdin.write(prompt)
    p.stdin.close()
    # stderr is drained on its own thread. A run is hours long, and a child that
    # fills the 64KB pipe while we are blocked reading stdout would hang forever.
    errbuf: list[str] = []
    drain = threading.Thread(target=lambda: errbuf.append(p.stderr.read()), daemon=True)
    drain.start()
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
    drain.join(5)
    err = "" if result else ("".join(errbuf))[-400:]
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
    return {"text": result.get("result") or "", "data": structured, "seconds": secs, "denials": denials,
            "session": result.get("session_id")}


def ask(run: Run, role: str, model: str, prompt: str, schema: dict | None = None, system: str | None = None):
    """A sealed call: no tools, no settings, nothing but the words. It never runs on
    Claude Code's own system prompt, which would make a programmer of every night run."""
    got = claude(run, role, model, prompt, cwd=run.root, tools="", schema=schema, system=system or PLAIN)
    return got["data"] if schema else got["text"].strip()


def cut(text: str, minutes: float) -> str:
    """The skim is done by withholding. A model reads every token it is handed,
    so he is handed what his minutes bought and told how much he left unread."""
    lines = text.splitlines()
    budget = int(minutes * 1.5) + 6
    if len(lines) <= budget:
        return text
    loud = [ln for ln in lines[budget // 2:-budget // 4] if re.search(r"fail|error|assum|recommend|cannot|\bnot\b", ln, re.I)]
    kept = lines[:budget // 2] + loud[:budget // 4] + lines[-budget // 4:]
    return "\n".join(kept) + f"\n[you read {len(kept)} of {len(lines)} lines. The rest is there. You did not get to it.]"


def catch(links: list[dict], ids: set[str], rng: random.Random) -> list[dict]:
    """The falling spoon. A link that has let go of the project, or that repeats a
    pair, is a miss. Each miss in a row loosens the grip, and when the spoon
    drops the pass is over, however much more was written after it."""
    kept, seen, misses = [], set(), 0
    for ln in links:
        anchors = sorted(x for x in ln["anchors"] if x in ids)
        pair = (tuple(anchors), ln["other"].strip().lower())
        if not anchors or pair in seen:
            misses += 1
            if rng.random() < 1 - 2 * 0.5 ** misses:   # one miss is free, then 0.5, 0.75, 0.88
                break
            continue
        misses = 0
        seen.add(pair)
        kept.append({**ln, "anchors": anchors})
    return kept


def shell(cmd: str, cwd: Path, timeout: int, lines: int) -> tuple[str, bool]:
    """A project's own check and show commands. A real suite is slower than a fixture's."""
    try:
        c = subprocess.run(cmd, shell=True, cwd=cwd, capture_output=True, text=True, timeout=timeout)
        got, ok = c.stdout + c.stderr, c.returncode == 0
    except subprocess.TimeoutExpired as e:
        got, ok = f"[gave up after {timeout}s]\n" + (e.stdout or "") + (e.stderr or ""), False
    return "\n".join(got.strip().splitlines()[-lines:]), ok


def owner_dir(name: str) -> Path:
    p = Path(name).expanduser()
    if p.is_dir():
        return p
    for base in (HOME / "owners", Path(__file__).resolve().parent / "owners"):
        if (base / name).is_dir():
            return base / name
    raise SystemExit(f"no owner {name!r}: looked in {HOME / 'owners'} and beside regent.py. Roll one with: regent cast")


def cast_cmd(a):
    """A regent is cast, not specified. The human pins a few facts, the dice roll
    the rest, and a model writes the person who fits. The entropy comes from
    outside the model: a model asked to be random returns its favourite few."""
    rng = random.Random(a.seed)
    dials = {k: round(clip(rng.gauss(0, 0.45), -0.9, 0.9), 2) for k in DIALS}
    for pin in a.dial:
        k, _, v = pin.partition("=")
        dials[k.strip()] = clip(float(v))
    try:
        vocab = [w for w in Path("/usr/share/dict/words").read_text().split() if 4 < len(w) < 10 and w.islower()]
    except OSError:
        vocab = []
    words = rng.sample(vocab, 7) if vocab else ["(none rolled)"]
    run = Run(HOME / "casting")
    got = ask(run, "cast", a.model, CAST_P.format(
        age=int(clip(rng.gauss(48, 15), 19, 84)), dials=", ".join(f"{k} {v:+.2f}" for k, v in dials.items()),
        words=", ".join(words), pins="; ".join(a.pin) or "nothing"), CAST)
    root = HOME / "owners" / (a.name or re.sub(r"[^a-z0-9-]", "", got["slug"].lower()) or f"owner-{a.seed}")
    root.mkdir(parents=True, exist_ok=True)
    (root / "bible.md").write_text(got["bible"].strip() + "\n")
    (root / "disposition.json").write_text(json.dumps({**dials, "rolled": {"seed": a.seed, "words": words}}, indent=2))
    (root / "events.md").write_text("\n".join(got["events"]) + "\n")
    print(f"\n{got['name']}  ->  {root}\n  " + ", ".join(f"{k} {v:+.2f}" for k, v in dials.items()) +
          f"\n  rolled words: {', '.join(words)}\n\n" + got["bible"].split("## The cast")[0].strip()[:900] +
          f"\n\nregent run --project <dir> --owner {root.name}")


def latest_run(where: str | None) -> Path:
    """A run folder, a project folder or name, or nothing at all, which means the newest run."""
    if where and (Path(where).expanduser() / "run.db").exists():
        return Path(where).expanduser()
    found = sorted((HOME / "runs").glob(f"{Path(where).name if where else ''}*/run.db"), key=lambda f: f.stat().st_mtime)
    if not found:
        raise SystemExit(f"no run found for {where or 'anything'} in {HOME / 'runs'}")
    return found[-1].parent


def snapshot(root: Path) -> dict:
    """Everything the page draws: the ledger, the state, the days he lived through, and the builder's commits."""
    c = sqlite3.connect(f"file:{root / 'run.db'}?mode=ro", uri=True)
    events = [{"id": i, "t": t, "kind": k, "d": json.loads(d)} for i, t, k, d in c.execute("SELECT id, t, kind, data FROM event")]
    state = json.loads((c.execute("SELECT v FROM state WHERE k='run'").fetchone() or ["{}"])[0])
    c.close()
    start = next((e["d"] for e in events if e["kind"] == "start"), {})
    days, memory, commits = {}, "", []
    try:
        owner = owner_dir(start.get("owner", ""))
        lc = sqlite3.connect(f"file:{owner / 'life.db'}?mode=ro", uri=True)
        ns = [e["d"]["n"] for e in events if e["kind"] == "day"]
        days = dict(lc.execute(f"SELECT n, text FROM day WHERE n IN ({','.join('?' * len(ns))})", ns))
        memory = (lc.execute("SELECT text FROM memory WHERE project=?", (start.get("project", ""),)).fetchone() or [""])[0]
        lc.close()
    except (SystemExit, sqlite3.Error):
        pass
    project = Path(start.get("project", ""))
    log = shell("git log --reverse --format=@%ct%x09%s --shortstat", project, 20, 4000)[0] if (project / ".git").exists() else ""
    for line in log.splitlines():
        if line.startswith("@"):
            when, _, subject = line[1:].partition("\t")
            commits.append({"t": int(when), "subject": subject, "plus": 0, "minus": 0})
        elif commits and "changed" in line:
            commits[-1]["plus"] = int((re.search(r"(\d+) insertion", line) or [0, 0])[1])
            commits[-1]["minus"] = int((re.search(r"(\d+) deletion", line) or [0, 0])[1])
    fresh = max((f.stat().st_mtime for f in root.glob("run.db*")), default=0)
    return {"run": root.name, "events": events, "state": state, "days": days, "memory": memory, "commits": commits,
            "quiet_for": round(time.time() - fresh)}


def watch_cmd(a, root: Path | None = None, background: bool = False):
    """One page, two uses: served live from the ledger, or written out whole with the run inside it."""
    root = root or latest_run(a.run)
    page = (Path(__file__).resolve().parent / "watch.html").read_text()
    if getattr(a, "export", None):
        data = json.dumps(snapshot(root), ensure_ascii=False).replace("</", "<\\/")
        page = page.replace("<title>Regent Daybook", f"<title>{root.name.rsplit('-', 2)[0]} daybook")
        Path(a.export).write_text(page.replace('type="application/json">null<', f'type="application/json">{data}<'))
        print(f"written to {a.export}")
        return 0

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            live = self.path.startswith("/data")
            body = (json.dumps(snapshot(root)) if live else
                    '<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
                    + page).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json" if live else "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_):
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", a.port), Handler)
    print(f"watching {root.name} at http://127.0.0.1:{server.server_address[1]}", flush=True)
    webbrowser.open(f"http://127.0.0.1:{server.server_address[1]}")
    if background:
        return threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        return 0


def run_cmd(a):
    project = Path(a.project).expanduser().resolve()
    project.mkdir(parents=True, exist_ok=True)
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
             "claude_secs": 0.0, "blocking": 0.0,
             "counts": {"direct": 0, "challenge": 0, "constrain": 0, "cycles": 0, "step_backs": 0, "looks": 0,
                        "empty_days": 0, "fresh": 0}}

    ch = sections(S["charter"])

    def budget(key: str) -> float:
        m = re.search(rf"^{key}:\s*([\d.]+)", ch.get("budget", ""), re.M)
        return float(m.group(1)) if m else 0.0
    tpd = a.turns_per_day or S.get("tpd") or budget("turns_per_day") or 1.0
    days = a.days or S.get("days") or int(budget("days") or budget("turns") / tpd) or 10
    S["tpd"], S["days"] = tpd, days
    check_cmd, show_cmd = ch.get("check", "").strip().strip("`"), ch.get("show", "").strip().strip("`")
    tool_lines = [ln.strip("- ").strip() for ln in ch.get("tools", "").splitlines() if ln.strip().startswith("-")]
    his_bash = ",".join(sorted({f"Bash({t.split()[0]}:*)" for t in tool_lines})) or "Bash(ls:*)"
    deny = ["WebFetch", "WebSearch"] if re.search(r"network", ch.get("refusals", ""), re.I) else []
    inbox, plant_file = root / "inbox.md", root / "plant.md"
    for line in a.plant:
        with plant_file.open("a") as f:
            f.write(line + "\n")

    # Two things a life needs that a bible does not carry: what could happen in a week of it, for the dice to draw
    # from, and why this person wants this project. Each is written once, by a model, the first time it is missed.
    ev_file = life.root / "events.md"
    if not ev_file.exists():
        got = ask(run, "events", "haiku", "Sixty short lines: things that could happen in one of this person's weeks, tied to "
                  "their places and people, small and concrete, most of them mundane and some going wrong. None about "
                  "software.\n\n" + life.bible, EVENTS)
        ev_file.write_text("\n".join(got["events"]) + "\n")
    happenings = [x for x in ev_file.read_text().splitlines() if x.strip()]
    if not life.get("stake", pname):
        life.put("stake", pname, ask(run, "stake", "sonnet", "This person is about to have this built for them:\n\n" +
                 ch.get("intent", "") + "\n\nWho they are:\n\n" + life.bible + "\n\nIn their own voice, first person, under "
                 "150 words: why they want it. The reason comes out of their life as written, something specific that "
                 "happened or keeps happening, not out of any interest in software."))

    system = (
        "You are the owner of a project, and you are this person:\n\n" + life.who +
        "\n\nWhy you want it built, in your own words:\n\n" + life.get("stake", pname) +
        "\n\nYour disposition, from -1 to +1: " + ", ".join(f"{k} {life.d(k):+.1f}" for k in DIALS) +
        "\n\nSomeone capable is building it for you. You give it a small part of your day. You say what you want, you look at "
        "what comes back, you ask why a thing is the way it is, you set limits, and you think of things nobody asked for. "
        "Speak as yourself, plainly and briefly.\n\n"
        "The project is yours to grow. A requirement you add must be something you would notice when using the thing, small "
        "enough to build in one go, and you say how you would see that it works. Standards for the builder are not "
        "requirements. Say them as limits in your message.\n\n"
        "The charter's REFUSALS and RESERVED decisions bind you, and you never cross them. A reserved decision goes to the "
        "human in ask_the_human, and the rest of the work carries on. The charter's CONSTRAINTS are different. They are the "
        "starting shape of the thing, written before anyone had used it. They are yours to change when the project has "
        "outgrown one: say which, what it becomes and why, in constraints_changed. Nobody has to approve it. Do not turn "
        "down a good idea of your own because a starting constraint is in its way. Change the constraint.\n\n"
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
            "changed. The owner reads words, not code: keep a short README, the usage text, the docstrings and the comments "
            "current and true, because that is what he checks you against. "
            "Reply in under 250 words: one sentence on what changed, what you recommend next, anything you assumed that he "
            "never said, then the commands you ran with their real output.\n\nThese are never crossed:\n"
            + ch.get("refusals", "") + "\n\nThese are the starting constraints:\n" + ch.get("constraints", "")
            + ("\n\nThe owner has since changed these limits, and his change stands:\n" + "\n".join(
                f"- was: {x['constraint']} / now: {x['now']}" for x in S["amended"]) if S["amended"] else ""))

    def pending():
        return [i for i in S["ideas"] if i["status"] == "pending"]

    def stance() -> float:
        return clip(0.6 * S["mood"] + 0.4 * life.d("bold"))

    def sitting(day: int, rng: random.Random, met: str) -> str:
        turn = S["turn"] = S["turn"] + 1
        failing = bool(S["last_check"]) and not S["check_ok"]
        # How long he has is a draw. Thoroughness stretches it, trust in the builder shortens it.
        lean = life.d("thorough") * 0.5 - (S["trust"] - 0.5)
        minutes = rng.lognormvariate(3.4 + 0.8 * lean, 0.9)
        if not S["last_reply"] or failing:
            minutes = max(minutes, 60)
        span = "a few minutes" if minutes < 12 else "about an hour" if minutes < 90 else "an evening"
        # He tries it himself now and then. Reading along behind the builder produces small variations, and those are
        # worth nothing to him, so the pull is weak, grows with the turns since he last looked, and distrust feeds it.
        pull = 0.12 + 0.15 * life.d("thorough") + 0.3 * S["wants_look"] + max(0.0, 0.5 - S["trust"])
        look = minutes >= 12 and bool(S["last_reply"] or S["existing"]) and rng.random() < pull * (1 - math.exp(-S["since_look"] / 2))

        said = ""
        if inbox.exists() and inbox.read_text().strip():
            said = inbox.read_text().strip()
            inbox.rename(root / f"inbox.read.{turn}.md")
            run.log("human_said", text=said)
        pend = pending()
        ctx = (
            f"THE CHARTER\n{S['charter']}\n\n"
            + ("LIMITS YOU HAVE ALREADY CHANGED\n" + "\n".join(
                f"- was: {x['constraint']} / now: {x['now']} / because: {x['why']}" for x in S["amended"]) + "\n\n"
               if S["amended"] else "")
            + (f"THE PERSON WHO GAVE YOU THE CHARTER HAS LEFT YOU A NOTE\n{said}\n\n" if said else "")
            + f"TODAY you have {span} for the project. The day is going "
            + ("well" if S["mood"] > 0.15 else "badly" if S["mood"] < -0.15 else "evenly")
            + (f". Today you came across this: {met}" if met else "")
            + f"\nYour stance today is {stance():+.2f} on a scale from -1, cautious and wanting proof, to +1, wanting more "
            "from it.\n\n"
            f"YOUR LAST TWO DAYS\n{life.recent(2, 500)}\n\n"
            "WHAT YOU REMEMBER OF THE PROJECT (a memory, so parts are missing)\n" + (life.get("memory", pname) or "nothing yet")
            + "\n" + "\n".join(f"- {n}" for n in S["notes"][-3:]) + "\n\n"
            + ("YOUR WAYS OF WORKING\n" + "\n".join(f"- {w}" for w in S["ways"]) + "\n\n" if S["ways"] else "")
            + "REQUIREMENTS SO FAR. Put the id of any you have now seen working in requirements_built.\n"
            + ("\n".join(f"- {q['id']} [{q['status']}] {q['text']}" for q in S["reqs"]) or "- none yet") + "\n\n"
            + ("YOU WOKE WITH THESE, AND THEY ARE STILL OPEN. You do not know where they came from. Take one as a new "
               "requirement, putting its label in that requirement's idea field, or decline it by label in ideas_declined "
               "with your reason. A starting constraint in the way is not a reason. Change the constraint.\n"
               + "\n".join(f"- {i['label']}: {i['text']} (you would check: {i['test']})" for i in pend) + "\n\n" if pend else "")
            + (f"WHAT THE BUILDER SAID BACK\n{cut(S['last_reply'], minutes)}\n\n" if S["last_reply"] else
               ("THIS PROJECT ALREADY EXISTS. Nothing has been said yet. Try it first.\n\n" if S["existing"] else
                "NOTHING HAS BEEN BUILT YET. This is your first message. Say what you want built and the limits.\n\n"))
            + (f"WHAT HAPPENED WHEN THE HARNESS RAN THE CHECK JUST NOW ({'passed' if S['check_ok'] else 'FAILED'})\n"
               f"{S['last_check']}\n\n" if S["last_check"] else "")
            + (f"WHAT THE THING PRINTED WHEN THE HARNESS RAN IT JUST NOW\n{cut(S['last_show'], minutes)}\n\n"
               if S["last_show"] else "")
            + (("TODAY YOU HAVE A FEW MINUTES TO TRY IT YOURSELF. You are in the project folder. Run the thing on something, "
                "and read what is written for people: the README, the usage text, the sample files. You can run these: "
                + ", ".join(tool_lines) + ". Do not read the code, and do not go looking through files. If you want the code "
                "examined or awkward cases tried, ask for that in your message and the builder will put a subagent on it. "
                "Two or three things at most, then stop. Put what you ran in looked_at and whether it matched what you were "
                "told in look_matched.\n\n") if look else "")
            + f"This is day {S['day_i'] + 1} of about {days}. So far you have directed {S['counts']['direct']} times, "
            f"challenged {S['counts']['challenge']} and constrained {S['counts']['constrain']}. An owner who only directs is "
            "a ticket queue. Write your message to the builder. A few new requirements may ride in it together; leave idea "
            "empty on one that is simply yours."
        )
        t = time.time()
        d = claude(run, "regent", a.regent_model, ctx, cwd=project if look else root,
                   tools="Read,Grep,Glob,Bash" if look else "", allowed=("Read,Grep,Glob," + his_bash) if look else None,
                   usd=SPOT_USD if look else None, system=system, schema=DECISION, who=life.root.name)["data"]
        S["blocking"] += time.time() - t
        S["since_look"] += 1
        if look:
            S["since_look"] = 0
            S["counts"]["looks"] += 1
            S["trust"] = clip(S["trust"] + (0.08 if d["look_matched"] else -0.25), 0, 1)
            run.log("look", ran=d["looked_at"], matched=d["look_matched"], trust=round(S["trust"], 2))
        S["wants_look"] = bool(d["wants_to_look"])
        for q in d["requirements_new"]:
            rid = f"req-{len(S['reqs']) + 1:02d}"
            origin = next((i for i in pend if i["label"].lower() == q["idea"].strip().lower()), None)
            S["reqs"].append({"id": rid, "status": "open", "turn": turn, "from_dream": bool(origin),
                              "text": q["text"], "test": q["test"]})
            if origin:
                origin["status"], origin["req"] = "taken", rid
                life.judged(pname, "took", origin["text"], "")
        for dec in d["ideas_declined"]:
            for i in pend:
                if i["status"] == "pending" and re.search(rf"\b{i['label']}\b", dec["idea"], re.I):
                    i["status"], i["why"] = "declined", dec["why"]
                    life.judged(pname, "turned down", i["text"], dec["why"])
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
        message = d["message"]
        if d["constraints_changed"]:  # said in the message too: a resumed builder keeps the system prompt it started with
            message += "\n\nLimits I have changed, and the change stands:\n" + "\n".join(
                f"- was: {c['constraint']} / now: {c['now']}" for c in d["constraints_changed"])
        if d["requirements_new"]:
            message += "\n\nNew requirements, build them together:\n" + "\n".join(
                f"- {q['text']} (I will check: {q['test']})" for q in d["requirements_new"])
        if S["ways"]:
            message += "\n\nMy standing ways of working, which still hold:\n" + "\n".join(f"- {w}" for w in S["ways"])
        run.log("sitting", n=turn, day=day, minutes=round(minutes), look=look, trust=round(S["trust"], 2), verdict=d["verdict"], message=message,
                stance_line=d["stance_line"], challenged=d["challenged"], constrained=d["constrained"],
                new=[q["text"] for q in d["requirements_new"]], built=d["requirements_built"],
                declined=d["ideas_declined"], constraints_changed=d["constraints_changed"], done=d["done"])
        run.say(f"sitting {turn} (day {day}, {round(minutes)} min{', tried it' if look else ''}, {d['verdict']}): "
                f"{d['stance_line'][:110]}")
        run.say(f"   {life.root.name} > {message[:160].replace(chr(10), ' ')}")
        quiet = not (d["requirements_new"] or pend or d["challenged"] or d["constrained"]) and d["verdict"] == "accept"
        S["dry"] = S["dry"] + 1 if quiet else 0

        run.save(S)   # so the page shows what he asked for while the builder is still at it
        out = claude(run, "claude", a.model, S["handover"] + message, cwd=project, append=norms(),
                     session=S["session"], resume=S["started"], effort=a.effort, denied=deny,
                     settings=["--strict-mcp-config", "--setting-sources", "project"],
                     allowed="Bash,Edit,Write,Read,Glob,Grep,Task,Agent,TodoWrite")
        S["handover"], S["started"] = "", True
        S["session"] = out["session"] or S["session"]
        S["session_turns"] += 1
        S["claude_secs"] += out["seconds"]
        S["last_reply"] = out["text"]
        run.log("reply", n=turn, text=out["text"], seconds=out["seconds"])
        if out["denials"]:
            run.say(f"   ! {len(out['denials'])} tool calls refused: {out['denials']}")
        if check_cmd:
            S["last_check"], S["check_ok"] = shell(check_cmd, project, a.timeout, 25)
            run.log("check", ok=S["check_ok"], tail=S["last_check"][-600:])
            run.say(f"   check {'passed' if S['check_ok'] else 'FAILED'}: "
                    f"{S['last_check'].splitlines()[-1] if S['last_check'] else ''}")
        if show_cmd:
            S["last_show"], _ = shell(show_cmd, project, a.timeout, 60)
        S["built_once"] = S["built_once"] or S["check_ok"] or not check_cmd
        S["records"].append({"turn": turn, "message": message, "reply": S["last_reply"], "check_ok": S["check_ok"],
                             "new": [q["text"][:100] for q in d["requirements_new"]],
                             "declined": [x["idea"][:60] for x in d["ideas_declined"]],
                             "amended": [x["now"][:80] for x in d["constraints_changed"]]})
        run.save(S)
        return f"{d['stance_line']} {d['notes_to_self']}"

    def write_day(rng: random.Random, seen: list[str], met: str):
        """The day is written by someone who is not him, from what the dice rolled.
        A model writing a life unaided writes the same mild day forever."""
        rolled = [f"- This happens: {x}" for x in rng.sample(happenings, min(2, len(happenings)))]
        if met:
            rolled.append(f"- They come across this: {met}")
        text = ask(run, "day", "haiku", DAY_P.format(
            words=f"{int(clip(rng.gauss(90, 30), 40, 170))}", bible=life.bible[:6000], recent=life.recent(3, 220, tail=True),
            valence="well" if S["mood"] > 0.15 else "badly" if S["mood"] < -0.15 else "evenly", rolled="\n".join(rolled),
            project="\n".join(f"- {x}" for x in seen) or "No time for it today. It is not in the entry."))
        run.log("day", n=life.add_day(text), sittings=len(seen), mood=round(S["mood"], 2))

    def consolidate():
        """The forgetting. What he holds of the project is rewritten as a memory, and parts of it go."""
        raw = "\n\n".join(
            f"Turn {r['turn']}. He said: {r['message'][:500]}\nThe builder said: {r['reply'][:700]}\n"
            f"The check {'passed' if r['check_ok'] else 'failed'}. New requirements: {r['new']}. "
            f"Ideas declined: {r['declined']}. Limits changed: {r['amended']}."
            for r in S["records"] if r["turn"] > S["compressed_upto"])
        text = ask(run, "memory", "haiku",
                   "What was remembered before:\n" + (life.get("memory", pname) or "nothing") + "\n\nWhat has happened "
                   "since:\n" + raw + "\n\nRewrite all of it as what a person would remember of this project a few days "
                   "later. Keep the events in order, what was asked for, what got built, what failed, what was decided, what "
                   "is still open. Keep nothing verbatim: no quotes, no code, no exact output. Small details may be lost, and "
                   "that is wanted. There are two people, the owner and the builder. Call them that and use no names. Under "
                   "220 words, plain sentences.", system="You compress a working record into a lossy memory.")
        life.put("memory", pname, text)
        S["compressed_upto"] = S["records"][-1]["turn"]

    def spoon(rng: random.Random):
        """Saturate, drift, catch, sift. None of it is him, and he is asked nothing."""
        parts = ([ch.get("intent", "")] + [q["text"] for q in S["reqs"]] + S["notes"][-4:]
                 + [s for s in re.split(r"(?<=\.)\s+", life.get("memory", pname)) if len(s) > 30]
                 + ([f"what it printed last: {S['last_show'][-500:]}"] if S["last_show"] else []))
        P = {f"p{i + 1}": t.strip() for i, t in enumerate(parts) if t.strip()}
        ptxt = "\n".join(f"{k}: {v[:400]}" for k, v in P.items())
        sat = ask(run, "saturate", "haiku", SATURATE_P.format(project=ptxt, life=life.recent(8, 500)), MOTIFS)
        motifs = "\n".join(f"- {m}" for k in ("motifs", "tensions", "questions") for m in sat[k])
        lean = f"{'opportunity' if stance() > 0 else 'risk'}-weighted {stance():+.2f}"
        # Drift runs more than once, on different models over different days, because one sampler has one groove.
        passes = [(m, int(clip(rng.gauss(16, 4), 8, 26)), life.sample(rng, int(clip(rng.gauss(10, 3), 5, 18))),
                   random.Random(rng.random())) for m in ("sonnet", "haiku")]
        holding: list[dict] = []

        def drift(model, target, days_txt, r):
            got = ask(run, "drift", model, DRIFT_P.format(target=target, motifs=motifs, project=ptxt, stance=lean,
                                                           bible=life.bible[:6000], days=days_txt), LINKS)["links"]
            caught = catch(got, set(P), r)
            run.log("drift", model=model, asked=target, written=len(got), caught=len(caught))
            holding.extend(caught)
        jobs = [threading.Thread(target=drift, args=p) for p in passes]
        for j in jobs:
            j.start()
        for j in jobs:
            j.join()
        rng.shuffle(holding)   # Sift must not be able to tell the passes apart
        S["counts"]["cycles"] += 1
        if not holding:
            return run.log("spoon", motifs=len(sat["motifs"]), caught=0, kept=0)
        got = ask(run, "sift", "sonnet", SIFT_P.format(
            holding="\n".join(f"{i}. {ln['text']}" + (f" Mechanism: {ln['mechanism']}" if ln["mechanism"] else "")
                              for i, ln in enumerate(holding)),
            intent=ch.get("intent", ""), refusals=ch.get("refusals", ""), taste=life.taste(), keep=1 + min(3, poisson(rng, 1.3)),
            built="\n".join(f"- {q['text'][:160]}" for q in S["reqs"]) or "- nothing yet"), SIFTED)["candidates"]
        for g in got:
            src = [holding[i] for i in g["from_indexes"] if 0 <= i < len(holding)]
            S["ideas"].append({"text": g["text"], "test": g["test"], "status": "pending", "label": f"I{len(S['ideas']) + 1}",
                               "might_fail": g["why_it_might_fail"],
                               "came_from": " / ".join(f"{x['text'][:220]} [{x['other']}]" for x in src)})
        run.log("spoon", motifs=sat, caught=len(holding), kept=len(got), candidates=got, elements=P,
                links=[{k: ln[k] for k in ("kind", "text", "anchors", "other", "mechanism")} for ln in holding])
        run.say(f"   (the spoon fell: {len(holding)} links caught, {len(got)} kept for the morning)")

    def step_back():
        sit = run.rows("sitting")
        view = {"sittings": S["turn"], "days": S["day_i"] + 1, "minutes_you_gave_each": [x.get("minutes") for x in sit],
                "days_with_no_time": S["counts"]["empty_days"], "times_you_tried_it": S["counts"]["looks"],
                "trust_in_the_builder": round(S["trust"], 2), "directed": S["counts"]["direct"],
                "challenged": S["counts"]["challenge"], "constrained": S["counts"]["constrain"],
                "checks_failed": sum(1 for x in run.rows("check") if not x["ok"]),
                "requirements": len(S["reqs"]), "requirements_built": sum(1 for q in S["reqs"] if q["status"] == "built"),
                "requirements_per_sitting": [len(x.get("new") or []) for x in sit],
                "ideas_you_woke_with": len(S["ideas"]), "ideas_taken": sum(1 for i in S["ideas"] if i["status"] == "taken"),
                "ideas_declined": [{"idea": i["text"][:80], "why": i.get("why", "")}
                                   for i in S["ideas"] if i["status"] == "declined"],
                "limits_you_changed": S["amended"], "fresh_builder_sessions": S["counts"]["fresh"],
                "builder_minutes": round(S["claude_secs"] / 60, 1), "your_minutes": round(S["blocking"] / 60, 1),
                "ways_now": S["ways"]}
        t = time.time()
        got = ask(run, "step_back", a.regent_model,
                  "Step back from the project and look at how the work itself is going. These numbers were counted by the "
                  "harness, not recalled:\n\n" + json.dumps(view, indent=1, ensure_ascii=False) +
                  "\n\nSay what you notice about how you and the builder are working. Then give your ways of working: standing "
                  "practices in your own words that the builder will be held to and that you will hold yourself to, five at "
                  "most, replacing the list above. A way changes how the work is done. It never crosses a refusal. Look hard "
                  "at the ideas you declined: if you keep turning them down, say why, and whether that is serving you. If you "
                  "think the charter itself has something wrong, say it as a note for the human.", STEPBACK, system)
        S["blocking"] += time.time() - t
        S["ways"] = got["ways"][:5]
        S["human_notes"].extend(got["notes_for_the_human"])
        S["counts"]["step_backs"] += 1
        S["since_step"] = 0
        run.log("step_back", view=view, observations=got["observations"], ways=S["ways"], notes=got["notes_for_the_human"])
        run.say(f"   (stepped back: {len(got['observations'])} observations, {len(S['ways'])} ways)")

    def tonight(name: str, fn, *args) -> threading.Thread:
        def go():
            try:
                fn(*args)
            except Exception as e:   # a night that fails costs nothing and must not end the run
                run.log(f"{name}_failed", error=str(e)[:300])
                run.say(f"   ({name} failed: {str(e)[:120]})")
        return threading.Thread(target=go)

    if a.watch:
        watch_cmd(a, root, background=True)
    run.log("start", project=pname, owner=S["owner"], days=days, turns_per_day=tpd, seed=a.seed, resumed=not fresh)
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
            run.say(f"day {day}: no time for the project.")
        seen = [sitting(day, rng, met if k == 0 else "") for k in range(n)]

        # Night. The day gets written, the project is half forgotten, and sometimes the spoon falls.
        t = time.time()
        S["since_dream"] += 1
        S["since_step"] += 1
        last = S["day_i"] + 1 >= days
        jobs = [tonight("day", write_day, rng, seen, met)]
        if any(r["turn"] > S["compressed_upto"] for r in S["records"]):
            jobs.append(tonight("memory", consolidate))
        if S["built_once"] and not pending() and not last and due(rng, S["since_dream"], a.dream_gap * (1 - 0.5 * life.d("curious"))):
            S["since_dream"] = 0
            jobs.append(tonight("spoon", spoon, random.Random(rng.random())))
        for j in jobs:
            j.start()
        for j in jobs:
            j.join()
        if S["turn"] and (last or due(rng, S["since_step"], 7 * (1 + 0.4 * life.d("patient")))):
            tonight("step_back", step_back).run()
        # A builder's session grows stale with every turn in it, so the odds of a fresh pair of hands grow too.
        if not last and S["started"] and life.get("memory", pname) and due(rng, S["session_turns"], 9):
            S["session"], S["started"], S["session_turns"] = str(uuid.uuid4()), False, 0
            S["counts"]["fresh"] += 1
            S["handover"] = ("You are picking this project up. This is what is remembered of the work so far, and it is a "
                             "memory, so parts are missing:\n\n" + life.get("memory", pname) +
                             "\n\nRead the files in this folder before you change anything.\n\n")
            run.say("   (a fresh builder picks it up in the morning, from his memory of it)")
        S["blocking"] += time.time() - t
        S["day_i"] += 1
        run.save(S)

    S["finished"] = True
    run.save(S)
    wall = time.time() - run.t0
    calls = run.rows("call")
    spend = {k: sum(x.get("cost", 0) for x in calls if (x["role"] == "claude") == (k == "builder")) for k in ("builder", "owner")}
    night_usd = sum(x.get("cost", 0) for x in calls if x["role"] in ("saturate", "drift", "sift"))
    built = sum(1 for q in S["reqs"] if q["status"] == "built")
    dreamt = sum(1 for q in S["reqs"] if q["from_dream"])
    c = S["counts"]
    spent = (f"{S['turn']} sittings over {days} days of his life, in {wall / 60:.1f} minutes. The builder worked for "
             f"{S['claude_secs'] / 60:.1f} of them. Spend: builder ${spend['builder']:.2f}, owner and his nights "
             f"${spend['owner']:.2f}, of which the spoon cycles were ${night_usd:.2f}. The check "
             f"{'passes' if S['check_ok'] else 'FAILS'}.")
    did = (f"He directed {c['direct']} times, challenged {c['challenge']}, constrained {c['constrain']}, tried it himself "
           f"{c['looks']} times and had {c['empty_days']} days with no time for it. The spoon fell on {c['cycles']} nights, "
           f"he stepped back {c['step_backs']} times, and a fresh builder picked it up {c['fresh']} times. Trust in the "
           f"builder ended at {S['trust']:.2f}.")
    lines = [f"# {project.name}", "", spent, "", did, "",
             f"## Requirements: {built} built of {len(S['reqs'])}, {dreamt} from the nights", ""]
    lines += [f"- {q['id']} [{q['status']}] sitting {q['turn']}{' (night)' if q['from_dream'] else ''}: {q['text']}"
              for q in S["reqs"]] or ["- none"]
    lines += ["", "## What the nights brought, and what he did with it", ""] + (
        [f"- [{i['status']}] {i['text']}\n  from: {i.get('came_from', '')}\n  it might fail because: {i.get('might_fail', '')}"
         + (f"\n  he declined it: {i['why']}" if i.get("why") else "") for i in S["ideas"]] or ["- nothing"])
    lines += ["", "## Limits he changed", ""] + (
        [f"- sitting {x['turn']}: was \"{x['constraint']}\", now \"{x['now']}\". Why: {x['why']}" for x in S["amended"]]
        or ["- none"])
    lines += ["", "## Questions for you", ""] + ([f"- sitting {e['turn']}: {e['question']}" for e in S["escalations"]] or ["- none"])
    lines += ["", "## His ways of working", ""] + ([f"- {w}" for w in S["ways"]] or ["- none"])
    lines += ["", "## His notes for you", ""] + ([f"- {n}" for n in S["human_notes"]] or ["- none"])
    lines += ["", "## What he remembers of the project", "", life.get("memory", pname)]
    (root / "digest.md").write_text("\n".join(lines) + "\n")
    run.log("summary", sittings=S["turn"], days=days, spend=spend, spoon_usd=round(night_usd, 2), check_ok=S["check_ok"],
            trust=round(S["trust"], 2), requirements=len(S["reqs"]), built=built, from_nights=dreamt, counts=c)
    run.say(f"stopped after {S['turn']} sittings in {days} days. wall {wall / 60:.1f} min. spend ${sum(spend.values()):.2f} "
            f"(spoon ${night_usd:.2f}). check {'passed' if S['check_ok'] else 'FAILED'}. requirements {built} of "
            f"{len(S['reqs'])}, {dreamt} from the nights. limits changed {len(S['amended'])}.")
    run.say(f"digest: {root / 'digest.md'}")
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
    r.add_argument("--model", default="sonnet", help="the builder")
    r.add_argument("--regent-model", default="sonnet")
    r.add_argument("--effort", default="low")
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
    c.add_argument("--name", default=None, help="folder name. Default: their own")
    c.add_argument("--seed", type=int, default=int(time.time()))
    c.add_argument("--model", default="sonnet")
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
        print(f"# {life.root.name}, day {life.days()}\n\n{life.recent(a.last, 4000)}")
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
