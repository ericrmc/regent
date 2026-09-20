#!/usr/bin/env python3
"""Regent, the one harness.

One process. It holds the regent, a simulated owner with a life and a mood,
and it runs Claude Code in the project on the owner's behalf. The regent talks
to Claude the way a person would: he directs, challenges, constrains, changes
his mind about a limit, and thinks of things nobody asked for. Claude uses its
own tools and subagents.

    python3 regent.py run examples/linkcheck.md --project /tmp/links
    python3 regent.py say runs/NAME "a note from you, shown to him next turn"
    python3 regent.py influence runs/NAME "plant: something he comes across"

A turn is a sitting: one regent call, then one Claude turn. Nothing else sits
in Claude's path. The budget is a count of turns, set by the charter.

Every few turns he rests. A rest is where the slow things happen together: his
memory of the project is compressed and some of it lost, he dreams, Claude
starts a fresh session from that memory, and now and then he steps back to
look at how the work is going. Once the thing is stable, rests come more often.

The older multi-call harness is in archive/, kept working, as a parts bin.
"""
from __future__ import annotations

import argparse
import json
import random
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

ISOLATE = ["--strict-mcp-config", "--setting-sources", ""]
REST_BUILDING, REST_GROWTH = 4, 2

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
            "idea": {"type": "string", "description": "the label of the open idea this takes up, such as I2, or empty"}},
            "required": ["text", "test", "idea"]}},
        "requirements_built": {"type": "array", "items": {"type": "string"}},
        "ideas_declined": {"type": "array", "items": {"type": "object", "properties": {
            "idea": {"type": "string"}, "why": {"type": "string"}}, "required": ["idea", "why"]}},
        "constraints_changed": {"type": "array", "items": {"type": "object", "properties": {
            "constraint": {"type": "string"}, "now": {"type": "string"}, "why": {"type": "string"}},
            "required": ["constraint", "now", "why"]}},
        "ask_the_human": {"type": "string", "description": "only for a reserved decision, otherwise empty"},
        "wants_to_look": {"type": "boolean", "description": "true if you want to look at the project yourself next time"},
        "review_request": {"type": "string", "description": "what you want an independent reviewer to examine and try to break, or empty"},
        "looked_at": {"type": "array", "items": {"type": "string"}},
        "look_matched": {"type": "boolean", "description": "if you looked today, did what you found match what you were told"},
        "notes_to_self": {"type": "string"},
        "journal": {"type": "string"},
        "done": {"type": "boolean"},
    },
    "required": ["stance_line", "verdict", "message", "challenged", "constrained", "requirements_new",
                 "requirements_built", "ideas_declined", "constraints_changed", "ask_the_human", "wants_to_look", "review_request",
                 "looked_at", "look_matched", "notes_to_self", "journal", "done"],
}
IDEAS = {"type": "object", "properties": {"ideas": {"type": "array", "items": {"type": "object", "properties": {
    "text": {"type": "string"}, "test": {"type": "string"}, "came_from": {"type": "string"}},
    "required": ["text", "test", "came_from"]}}}, "required": ["ideas"]}
STEPBACK = {"type": "object", "properties": {
    "observations": {"type": "array", "items": {"type": "string"}},
    "ways": {"type": "array", "items": {"type": "string"}},
    "requirements_per_turn_limit": {"type": "integer", "description": "a limit on new requirements per turn that the harness will count and hold you to, or 0 for none"},
    "notes_for_the_human": {"type": "array", "items": {"type": "string"}}},
    "required": ["observations", "ways", "requirements_per_turn_limit", "notes_for_the_human"]}
REVIEW = {"type": "object", "properties": {"report": {"type": "string"}, "matched": {"type": "boolean"}}, "required": ["report", "matched"]}


class Run:
    def __init__(self, root: Path):
        self.root = root
        root.mkdir(parents=True, exist_ok=True)
        self.ledger = root / "ledger.jsonl"
        self.lock = threading.Lock()
        self.t0 = time.time()

    def log(self, kind: str, **kw):
        row = {"t": round(time.time() - self.t0, 1), "iso": time.strftime("%H:%M:%S"), "kind": kind, **kw}
        with self.lock, self.ledger.open("a") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
        return row

    def rows(self):
        return [json.loads(x) for x in self.ledger.read_text().splitlines()]

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
           resume: bool = False, effort: str | None = None, who: str = "claude") -> dict:
    """One call, always streamed, so every tool use is seen as it happens and nothing waits unseen."""
    start = time.time()
    cmd = ["claude", "-p", "--model", model, *ISOLATE, "--output-format", "stream-json", "--verbose"]
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
                    what = str(inp.get("command") or inp.get("file_path") or inp.get("pattern") or inp.get("description") or "")[:160]
                    used.append(f"{blk.get('name')}: {what}")
                    run.log("tool", who=who, name=blk.get("name"), what=what)
                    run.say(f"   {who} > {blk.get('name')}: {what[:90].splitlines()[0] if what else ''}")
        elif ev.get("type") == "result":
            result = ev
    p.wait()
    err = "" if result else p.stderr.read()[-400:]
    secs = round(time.time() - start, 1)
    denials = [d.get("tool_name") for d in result.get("permission_denials", [])]
    run.log("call", role=role, model=model, seconds=secs, cost=result.get("total_cost_usd", 0),
            out_tokens=(result.get("usage") or {}).get("output_tokens"), tools=len(used), denials=denials, error=err)
    structured = result.get("structured_output")
    if schema and structured is None:
        try:
            structured = json.loads(result.get("result") or "")
        except (json.JSONDecodeError, TypeError):
            raise RuntimeError(f"{role} returned no structured output: {err or (result.get('result') or '')[:200]}")
    return {"text": result.get("result") or "", "data": structured, "cost": result.get("total_cost_usd", 0),
            "seconds": secs, "denials": denials, "session": result.get("session_id"), "used": used}


def cut(text: str, mode: str, worries: list[str] = ()) -> str:
    """The skim is done by withholding. A model reads every token it is handed."""
    if mode == "full" or len(text) < 700:
        return text
    if mode == "glance":
        return text[:300] + "\n[...]\n" + text[-200:]
    pat = r"\d|fail|error|assum|recommend|cannot|not " + "".join("|" + re.escape(w) for w in worries)
    keep = [ln for ln in text.splitlines() if re.search(pat, ln, re.I)][:14]
    return text[:500] + "\n[...]\n" + "\n".join(keep) + "\n[...]\n" + text[-300:]


def run_cmd(args):
    repo = Path(__file__).parent
    a = args
    charter_text = Path(a.charter).read_text()
    ch = sections(charter_text)
    m = re.search(r"turns:\s*(\d+)", ch.get("budget", ""))
    turns = a.turns or (int(m.group(1)) if m else 12)
    check_cmd = ch.get("check", "").strip().strip("`")
    show_cmd = ch.get("show", "").strip().strip("`")
    project = Path(a.project).resolve()
    existing = project.exists() and any(project.iterdir())
    project.mkdir(parents=True, exist_ok=True)
    run = Run(repo / (a.run or f"runs/{time.strftime('%m%d-%H%M')}"))
    rng = random.Random(a.seed)
    owner = repo / a.owner
    bible = (owner / "bible.md").read_text()
    who = bible.split("## The cast")[0][:1800]
    stake = re.search(r"^## Why I want this\s*\n(.*?)(?=^## |\Z)", bible, re.S | re.M)
    stake = stake.group(1).strip() if stake else ""
    disp = json.loads((owner / "disposition.json").read_text()) if (owner / "disposition.json").exists() else {}
    dv = lambda k: float(disp.get(k, 0) or 0)  # noqa: E731
    journal_dir = owner / "journal"
    day_n = len(list(journal_dir.glob("day-*.md")))
    inbox, influence_file, memory_file = run.root / "inbox.md", run.root / "influence.md", run.root / "memory.md"
    for line in a.plant:
        with influence_file.open("a") as f:
            f.write(f"plant: {line}\n")

    regent_system = (
        "You are the owner of a small project, and you are this person:\n\n" + who +
        "\n\nWhy you want it built, in your own words:\n\n" + stake +
        "\n\nYour disposition, from -1 to +1: " + ", ".join(f"{k} {v:+.1f}" for k, v in disp.items() if isinstance(v, (int, float))) +
        "\n\nSomeone capable is building it for you. You give it a small part of your day. You say what you want, you look at what "
        "comes back, you ask why a thing is the way it is, you set limits, and you think of things nobody asked for. "
        "Speak as yourself, plainly and briefly.\n\n"
        "The project is yours to grow. A requirement you add must be something you would notice when using the thing, small enough "
        "to build in one go, and you say how you would see that it works. Standards for the builder are not requirements. Say them "
        "as limits in your message.\n\n"
        "The charter's REFUSALS and RESERVED decisions bind you, and you never cross them. A reserved decision goes to the human in "
        "ask_the_human, and the rest of the work carries on. The charter's CONSTRAINTS are different. They are the starting shape "
        "of the thing, written before anyone had used it. They are yours to change when the project has outgrown one: say which, "
        "what it becomes and why, in constraints_changed. It is recorded for the person who gave you the charter, and nobody has to "
        "approve it. Do not turn down a good idea of your own because a starting constraint is in its way. Change the constraint.\n\n"
        "Judge on what the harness ran and on what you see for yourself, not on what you are told.\n\n"
        "Nobody else will fetch or make things for you. The human is only for a reserved decision. If you need something to exist, "
        "a realistic copy of your notes to try the tool on, a sample, a written explanation, ask the builder to make it from what you "
        "tell them. You are not a programmer and you do not read code line by line. When you look for yourself you read what is "
        "written for people: the README, the usage text, the docstrings and comments, the test names, the sample files, and you "
        "run the thing. When you want the code itself examined, or the thing attacked with awkward cases the builder did not "
        "make up, commission an independent reviewer with review_request. The reviewer has never spoken to the builder."
    )

    def norms(amended: list[dict]) -> str:
        return (
            "You are building this project for its owner, who writes to you in plain words. "
            "Work only inside this directory. Use whatever tools and subagents suit the task, and do not end your turn while a "
            "subagent is still running. Write a file once and patch it after. Run what you build. "
            "The owner reads words, not code: keep a short README, the usage text, the docstrings and the comments current and true, "
            "because that is what he checks you against. "
            "Reply in under 250 words: one sentence on what changed, what you recommend next, anything you assumed that he never "
            "said, then the commands you ran with their real output.\n\nThese are never crossed:\n" + ch.get("refusals", "") +
            "\n\nThese are the starting constraints:\n" + ch.get("constraints", "") +
            ("\n\nThe owner has since changed these limits, and his change stands:\n" + "\n".join(
                f"- was: {x['constraint']} / now: {x['now']}" for x in amended) if amended else "")
        )
    deny = ["WebFetch", "WebSearch"] if re.search(r"network", ch.get("refusals", ""), re.I) else []

    # Everything he and the harness carry from turn to turn.
    reqs, notes, ideas, ways, human_notes, amended, escalations, records = [], [], [], [], [], [], [], []
    worries: list[str] = []
    dream_theme, itch, mood_bias, mood_days = "", "", 0.0, 0
    stance = dv("bold") * 0.4
    trust = 0.5 + 0.1 * dv("trusting")
    counts = {"direct": 0, "challenge": 0, "constrain": 0, "dreams": 0, "step_backs": 0, "rests": 0, "looks": 0,
              "waved": 0, "fresh_sessions": 0, "reviews": 0, "held_back": 0}
    blocking = [0.0]
    last_reply, last_check, last_show, check_ok = "", "", "", False
    ok_streak, reject_streak, stable, dry_rounds, since_rest = 0, 0, False, 0, 0
    wants_look, last_look = existing, -9
    review_report, review_thread, last_review, req_limit, later = [""], None, -9, 0, []
    tool_lines = [ln.strip("- ").strip() for ln in ch.get("tools", "").splitlines() if ln.strip().startswith("-")]
    his_bash = ",".join(sorted({f"Bash({t.split()[0]}:*)" for t in tool_lines})) or "Bash(ls:*)"
    session, session_started, handover = str(uuid.uuid4()), False, ""
    claude_seconds = 0.0
    run.log("start", charter=a.charter, project=str(project), owner=a.owner, turns=turns, seed=a.seed, existing=existing)
    run.say(f"regent run: {a.charter} in {project}, budget {turns} turns" + (", an existing project" if existing else ""))

    def pending():
        return [i for i in ideas if i["status"] == "pending"]

    def remembered() -> str:
        return memory_file.read_text().strip() if memory_file.exists() else ""

    def compress():
        raw = "\n\n".join(
            f"Turn {r['turn']}. He said: {r['message'][:500]}\nThe builder said: {r['reply'][:700]}\n"
            f"The check {'passed' if r['check_ok'] else 'failed'}. New requirements: {r['new']}. Ideas declined: {r['declined']}. "
            f"Limits changed: {r['amended']}." for r in records if r["turn"] > compress.upto)
        prompt = ("What was remembered before:\n" + (remembered() or "nothing") + "\n\nWhat has happened since:\n" + raw +
                  "\n\nRewrite all of it as what a person would remember of this project a few days later. Keep the events in order "
                  "by turn, what was asked for, what got built, what failed, what was decided, what is still open. Keep nothing "
                  "verbatim: no quotes, no code, no exact output, no file contents. Small details may be lost, and that is wanted. "
                  "There are two people, the owner and the builder. Call them that and use no names. "
                  "Under 220 words, plain sentences.")
        got = claude(run, "memory", "haiku", prompt, cwd=run.root, tools="", system="You compress a working record into a lossy memory.")
        memory_file.write_text(got["text"].strip() + "\n")
        compress.upto = records[-1]["turn"] if records else 0
        run.log("memory", words=len(got["text"].split()), text=got["text"].strip())
    compress.upto = 0

    def dream():
        recent = "\n\n".join(p.read_text()[:700] for p in sorted(journal_dir.glob("day-*.md"))[-10:])
        prompt = ("Your last days:\n\n" + recent + "\n\nWhat you remember of the project:\n" + remembered() + "\n" + "\n".join(notes[-3:]) +
                  ("\n\nWhat it printed when the harness last ran it:\n" + last_show[:900] if last_show else "") +
                  "\n\nRequirements so far:\n" + "\n".join(f"- {q['text'][:120]}" for q in reqs) +
                  "\n\nIdeas you already had, so do not repeat them:\n" + "\n".join(f"- {i['text'][:120]}" for i in ideas) +
                  (f"\n\nSomething is on your mind tonight: {dream_theme}" if dream_theme else "") +
                  "\n\nYou are half asleep. Let the days and the project run together. Then give one or two things the project could "
                  "become, or is missing for you. Each must be something you would notice when using it, small enough to build in "
                  "one go, with how you would see it works, and the thing in your days it came from. Borrow how things work "
                  "elsewhere, not how they look. Do not hold back because of a constraint in the charter. Those are yours to change.")
        try:
            got = claude(run, "dream", a.regent_model, prompt, cwd=run.root, tools="", system=regent_system, schema=IDEAS)["data"].get("ideas", [])
            for g in got[:2]:
                ideas.append({**g, "status": "pending", "label": f"I{len(ideas) + 1}"})
            counts["dreams"] += 1
            run.log("dream", ideas=got[:2], phase="growth" if stable else "building")
        except Exception as e:  # a dream that fails costs nothing
            run.log("dream_failed", error=str(e)[:200])

    def step_back(turn: int):
        nonlocal req_limit
        rows = run.rows()
        sit = [x for x in rows if x["kind"] == "sitting"]
        wt = [x for x in rows if x["kind"] == "call" and x["role"] == "claude"]
        view = {
            "turns": turn, "read_modes": {k: sum(1 for x in sit if x.get("read_mode") == k) for k in ("full", "skim", "glance")},
            "days_with_no_time": counts["waved"], "times_you_looked_for_yourself": counts["looks"], "trust_in_the_builder": round(trust, 2),
            "directed": counts["direct"], "challenged": counts["challenge"], "constrained": counts["constrain"],
            "checks_failed": sum(1 for x in rows if x["kind"] == "check" and not x["ok"]),
            "tool_calls_refused": sum(len(x.get("denials") or []) for x in wt),
            "requirements": len(reqs), "requirements_built": sum(1 for q in reqs if q["status"] == "built"),
            "requirements_per_turn": [len(x.get("new") or []) for x in sit],
            "ideas_from_dreams": len(ideas), "ideas_taken": sum(1 for i in ideas if i["status"] == "taken"),
            "ideas_declined": [{"idea": i["text"][:80], "why": i.get("why", "")} for i in ideas if i["status"] == "declined"],
            "limits_you_changed": amended, "requirements_per_turn_limit_now": req_limit, "held_back_by_that_limit": counts["held_back"],
            "independent_reviews": counts["reviews"], "fresh_builder_sessions": counts["fresh_sessions"],
            "builder_minutes": round(claude_seconds / 60, 1), "your_minutes": round(blocking[0] / 60, 1),
            "ways_now": ways,
        }
        prompt = ("Step back from the project and look at how the work itself is going. These numbers were counted by the harness, "
                  "not recalled:\n\n" + json.dumps(view, indent=1, ensure_ascii=False) +
                  "\n\nSay what you notice about how you and the builder are working. Then give your ways of working: standing "
                  "practices in your own words that the builder will be held to and that you will hold yourself to, seven at "
                  "most, replacing the list above. A way changes how the work is done. It never crosses a refusal. Look hard at "
                  "the ideas you declined: if you keep turning your own ideas down, say why, and whether that is serving you. "
                  "If you think the charter itself has something wrong, say it as a note for the human.")
        t = time.time()
        got = claude(run, "step_back", a.regent_model, prompt, cwd=run.root, tools="", system=regent_system, schema=STEPBACK)["data"]
        blocking[0] += time.time() - t
        ways[:] = got["ways"][:7]
        req_limit = max(0, int(got.get("requirements_per_turn_limit") or 0))
        human_notes.extend(got["notes_for_the_human"])
        counts["step_backs"] += 1
        run.log("step_back", view=view, observations=got["observations"], ways=ways, notes_for_the_human=got["notes_for_the_human"])
        run.say(f"   (stepped back: {len(got['observations'])} observations, {len(ways)} ways)")

    def review(turn: int, question: str, told: str):
        """An independent pair of eyes on a snapshot. It has never spoken to the builder, and it cannot touch the project."""
        nonlocal trust
        snap = run.root / f"review-{turn}"
        shutil.copytree(project, snap, dirs_exist_ok=True, ignore=shutil.ignore_patterns("__pycache__", ".git"))
        prompt = ("You are an independent reviewer. The owner of this small project is not a programmer and has asked you to examine "
                  "it for him. You have never spoken to whoever built it. This folder is a copy, so do what you like in it.\n\n"
                  "What the project is for:\n" + ch.get("intent", "") + "\n\nWhat the owner wants looked at:\n" + question +
                  "\n\nWhat the builder last told him:\n" + told[:1500] +
                  "\n\nRead the code and the words written for people, and check each claim against what is really there. Then attack it: "
                  "make deliberately awkward inputs the builder would not have thought of, run the thing on them, and see where it is "
                  "wrong or goes quiet. Report to the owner in plain words, under 250 words: what matched, what did not, the awkward "
                  "cases and what happened, and the one or two questions most worth putting to the builder. Set matched to false if "
                  "anything he was told is not true or the thing gave a wrong answer.")
        try:
            got = claude(run, "reviewer", a.model, prompt, cwd=snap, effort=a.effort, denied=deny, schema=REVIEW, who="reviewer",
                         allowed="Bash,Edit,Write,Read,Glob,Grep")["data"]
            review_report[0] = got["report"]
            trust = max(0.0, min(1.0, trust + (0.08 if got["matched"] else -0.25)))
            counts["reviews"] += 1
            run.log("review", turn=turn, question=question, matched=got["matched"], report=got["report"], trust=round(trust, 2))
            run.say(f"   (the reviewer reported: {'it matched' if got['matched'] else 'it did NOT match'})")
        except Exception as e:
            run.log("review_failed", error=str(e)[:200])

    def rest(turn: int, final: bool = False):
        """The slow things happen together, between sittings: forgetting, dreaming, a fresh builder, sometimes stepping back."""
        nonlocal session, session_started, handover, since_rest
        counts["rests"] += 1
        since_rest = 0
        t = time.time()
        jobs = [threading.Thread(target=compress)]
        if not final and not pending():
            jobs.append(threading.Thread(target=dream))
        for j in jobs:
            j.start()
        for j in jobs:
            j.join()
        if final or counts["rests"] % 3 == 0:
            step_back(turn)
        blocking[0] += time.time() - t
        if not final:
            session, session_started = str(uuid.uuid4()), False
            counts["fresh_sessions"] += 1
            handover = ("You are picking this project up. This is what is remembered of the work so far, and it is a memory, "
                        "so parts are missing:\n\n" + remembered() + "\n\nRead the files in this folder before you change anything.\n\n")
        run.say(f"   (rested: memory compressed to {len(remembered().split())} words, {len(pending())} ideas waiting, a fresh builder session next)")

    def take_influence():
        nonlocal dream_theme, itch, mood_bias, mood_days
        met = ""
        if not influence_file.exists():
            return met
        keep = []
        for line in influence_file.read_text().splitlines():
            k, _, v = line.partition(":")
            k, v = k.strip().lower(), v.strip()
            if not v:
                continue
            if k in ("plant", "voice", "reading") and not met:
                met = v if k != "voice" else f"someone said to you: {v}"
            elif k == "mood":
                mood_bias, mood_days = (-0.4 if "risk" in v else 0.4), int(re.search(r"\d+", v).group()) if re.search(r"\d+", v) else 3
            elif k == "worry":
                worries.append(v)
            elif k == "itch":
                itch = v
            elif k == "dream":
                dream_theme = v
            elif k == "recall":
                met = f"you found yourself remembering: {v}"
            else:
                keep.append(line)
                continue
            run.log("influence", channel=k, human_only=True)
        influence_file.write_text("\n".join(keep) + ("\n" if keep else ""))
        return met

    turn, day_guard = 0, 0
    while turn < turns and day_guard < turns * 3:
        day_guard += 1
        # A day passes. The harness rolls it. He never rolls his own luck.
        day_n += 1
        met = take_influence()
        time_left = rng.choices(["none", "a few minutes", "an hour", "an evening"], [1, 3, 4, 2])[0]
        valence = round(max(-1, min(1, rng.uniform(-0.6, 0.6) + (mood_bias if mood_days > 0 else 0))), 2)
        mood_days -= 1
        stance = max(-1, min(1, 0.7 * stance + 0.3 * (valence * 0.5 + dv("bold") * 0.3) + rng.uniform(-0.05, 0.05)))
        if turn == 0 or (last_check and not check_ok):
            time_left = "an hour" if time_left in ("none", "a few minutes") else time_left
        if time_left == "none":
            counts["waved"] += 1
            run.log("day", n=day_n, time_for_project="none", valence=valence)
            run.say(f"day {day_n}: no time for the project today. Nothing is sent and nothing is spent.")
            continue
        turn += 1
        since_rest += 1
        mode = {"a few minutes": "glance", "an hour": "skim", "an evening": "full"}[time_left]
        lean = dv("thorough") * 0.5 - (trust - 0.5)     # thorough reads more, trust buys attention off
        if lean > 0.25 and mode == "glance":
            mode = "skim"
        elif lean > 0.45 and mode == "skim":
            mode = "full"
        elif lean < -0.2 and mode == "full":
            mode = "skim"
        if turn <= 2 or (last_check and not check_ok):
            mode = "full"
        # He looks for himself now and then, not every day. Reading the code every turn is the builder's job done twice.
        rested_eyes = turn - last_look >= 3 or trust < 0.4 or bool(itch) or (existing and turn == 1)
        look = time_left != "a few minutes" and bool(last_reply or existing) and rested_eyes and (
            wants_look or bool(itch) or rng.random() < 0.2 + 0.15 * dv("thorough") + (0.2 if trust < 0.4 else 0))
        run.log("day", n=day_n, turn=turn, time_for_project=time_left, valence=valence, stance=round(stance, 2),
                read_mode=mode, look=look, trust=round(trust, 2), met=bool(met), phase="growth" if stable else "building")

        said = ""
        if inbox.exists() and inbox.read_text().strip():
            said = inbox.read_text().strip()
            inbox.rename(run.root / f"inbox.read.{turn}.md")
            run.log("human_said", text=said)
        pend = pending()
        recent = "\n\n".join(p.read_text()[:500] for p in sorted(journal_dir.glob("day-*.md"))[-2:])
        ctx = (
            f"THE CHARTER\n{charter_text}\n\n"
            + ("LIMITS YOU HAVE ALREADY CHANGED\n" + "\n".join(f"- was: {x['constraint']} / now: {x['now']} / because: {x['why']}" for x in amended) + "\n\n" if amended else "")
            + (f"THE PERSON WHO GAVE YOU THE CHARTER HAS LEFT YOU A NOTE\n{said}\n\n" if said else "")
            + f"TODAY is day {day_n}. You have {time_left} for the project. The day has gone {'well' if valence > 0.15 else 'badly' if valence < -0.15 else 'evenly'}."
            + (f" Today you came across this: {met}" if met else "")
            + f"\nYour stance today is {stance:+.2f} on a scale from -1, cautious and wanting proof, to +1, wanting more from it.\n\n"
            f"YOUR LAST TWO DAYS\n{recent}\n\n"
            "WHAT YOU REMEMBER OF THE PROJECT (a memory, so parts are missing)\n" + (remembered() or "nothing yet") + "\n"
            + "\n".join(f"- {n}" for n in notes[-3:]) + "\n\n"
            + ("YOUR WAYS OF WORKING\n" + "\n".join(f"- {w}" for w in ways) + "\n\n" if ways else "")
            + "REQUIREMENTS SO FAR. Put the id of any you have now seen working in requirements_built.\n"
            + ("\n".join(f"- {q['id']} [{q['status']}] {q['text']}" for q in reqs) or "- none yet") + "\n\n"
            + ("IDEAS THAT CAME TO YOU AND ARE STILL OPEN. Take one as a new requirement and name its label, or decline it with your "
               "reason. A starting constraint in the way is not a reason. Change the constraint.\n"
               + "\n".join(f"- {i['label']}: {i['text']} (you would check: {i['test']}) (it came from: {i['came_from']})" for i in pend) + "\n\n" if pend else "")
            + (f"WHAT THE BUILDER SAID BACK (you gave it a {mode} read)\n{cut(last_reply, mode, worries)}\n\n" if last_reply else
               ("THIS PROJECT ALREADY EXISTS. Nothing has been said yet. Look around first.\n\n" if existing else
                "NOTHING HAS BEEN BUILT YET. This is your first message. Say what you want built and the limits.\n\n"))
            + (f"THE INDEPENDENT REVIEWER YOU ASKED FOR HAS REPORTED\n{review_report[0]}\n\n" if review_report[0] else "")
            + (f"WHAT HAPPENED WHEN THE HARNESS RAN THE CHECK JUST NOW ({'passed' if check_ok else 'FAILED'})\n{last_check}\n\n" if last_check else "")
            + (f"WHAT THE THING PRINTED WHEN THE HARNESS RAN IT JUST NOW\n{last_show if mode == 'full' else cut(last_show, 'skim', worries)}\n\n" if last_show else "")
            + (("TODAY YOU HAVE TIME TO LOOK FOR YOURSELF. You are in the project folder with Read, Grep and Glob, and you can run "
                "these yourself: " + ", ".join(tool_lines) + ". Read what is written for people, the README, the usage text, the "
                "docstrings and comments, the test names, the sample files, and run the thing on something. Do not read the code line "
                "by line. That is what a reviewer is for. Go where you are uneasy" + (f", and you have had an itch about this: {itch}" if itch else "") +
                ". See whether what is there matches what you were told, and find something worth asking about. Put what you opened "
                "or ran in looked_at and whether it matched in look_matched.\n\n") if look else "")
            + f"This is turn {turn} of {turns}. So far you have directed {counts['direct']} times, challenged {counts['challenge']} and constrained {counts['constrain']}. "
            "An owner who only directs is a ticket queue. "
            + (f"You set yourself a limit of {req_limit} new requirements a turn, and the harness holds you to it. Anything past it waits on your later pile. " if req_limit else "")
            + ("The thing has been stable for a while. The work now is to make it more use to you, not to polish it. " if stable else "")
            + "Write your message to the builder. Up to five new requirements may ride in it together. "
            "In journal, write today's entry the way you write for yourself: fragments, names, times, 40 to 120 words, mostly not about the project."
        )
        t = time.time()
        d = claude(run, "regent", a.regent_model, ctx, cwd=project if look else run.root, tools="Read,Grep,Glob,Bash" if look else "",
                   allowed=("Read,Grep,Glob," + his_bash) if look else None,
                   system=regent_system, schema=DECISION, who="piotr")["data"]
        blocking[0] += time.time() - t
        if look:
            last_look = turn
            counts["looks"] += 1
            trust = max(0.0, min(1.0, trust + (0.08 if d["look_matched"] else -0.25)))
            run.log("look", files=d["looked_at"], matched=d["look_matched"], trust=round(trust, 2), itch=itch)
            itch = ""
        wants_look = bool(d["wants_to_look"])
        review_report[0] = ""
        cap = req_limit or 5
        for q in d["requirements_new"][cap:]:   # the harness counts, so he does not have to say no to himself
            counts["held_back"] += 1
            ideas.append({"text": q["text"], "test": q["test"], "came_from": "your later pile, held back by your own limit",
                          "status": "pending", "label": f"I{len(ideas) + 1}"})
        if len(d["requirements_new"]) > cap:
            run.say(f"   (his own limit of {cap} a turn held back {len(d['requirements_new']) - cap}, now on his later pile)")
        d["requirements_new"] = d["requirements_new"][:cap]
        for q in d["requirements_new"][:5]:
            rid = f"req-{len(reqs) + 1:02d}"
            origin = next((i for i in pend if i["label"].lower() == (q.get("idea") or "").strip().lower()), None)
            reqs.append({"id": rid, "status": "open", "turn": turn, "from_dream": bool(origin), "text": q["text"], "test": q["test"]})
            if origin:
                origin["status"], origin["req"] = "taken", rid
        for dec in d["ideas_declined"]:
            for i in pend:
                if i["status"] == "pending" and re.search(rf"\b{i['label']}\b", dec["idea"], re.I):
                    i["status"], i["why"] = "declined", dec["why"]
        for rid in d["requirements_built"]:
            for q in reqs:
                if q["id"] == rid:
                    q["status"] = "built"
        for c in d["constraints_changed"]:
            amended.append({**c, "turn": turn})
            run.say(f"   * he changed a limit: {c['constraint'][:60]} -> {c['now'][:60]}")
        if d["ask_the_human"].strip():
            escalations.append({"turn": turn, "question": d["ask_the_human"]})
            run.say(f"   ? for you: {d['ask_the_human'][:140]}  (answer with: regent.py say {run.root} \"...\")")
        notes.append(d["notes_to_self"])
        counts["direct"] += 1
        counts["challenge"] += int(d["challenged"])
        counts["constrain"] += int(d["constrained"])
        (journal_dir / f"day-{day_n:04d}.md").write_text(f"# day {day_n}\n\n{d['journal']}\n")
        message = d["message"]
        if d["requirements_new"]:
            message += "\n\nNew requirements, build them together:\n" + "\n".join(
                f"- {q['text']} (I will check: {q['test']})" for q in d["requirements_new"][:5])
        if ways:
            message += "\n\nMy standing ways of working, which still hold:\n" + "\n".join(f"- {w}" for w in ways)
        run.log("sitting", n=turn, read_mode=mode, look=look, verdict=d["verdict"], stance_line=d["stance_line"],
                phase="growth" if stable else "building", message=message, challenged=d["challenged"], constrained=d["constrained"],
                new=[q["text"] for q in d["requirements_new"]], built=d["requirements_built"], declined=d["ideas_declined"],
                constraints_changed=d["constraints_changed"], ask_the_human=d["ask_the_human"], done=d["done"])
        run.say(f"turn {turn} ({'growth' if stable else 'building'}, {mode}{', looked' if look else ''}, {d['verdict']}): {d['stance_line'][:110]}")
        run.say(f"   piotr > {message[:160].replace(chr(10), ' ')}")

        # Growth starts on either signal: the check has passed a few rounds running, or he thinks it is finished.
        content = d["verdict"] == "accept" or d["done"]
        ok_streak = ok_streak + 1 if check_ok else 0
        if not stable and (ok_streak >= 3 or (content and check_ok)):
            stable = True
            run.log("phase", to="growth", turn=turn)
            run.say("   -- stable. The run turns to growth: he rests, forgets and dreams every second turn.")
        # Frustration has somewhere to go. Three rejections running and a fresh pair of hands picks it up.
        reject_streak = reject_streak + 1 if d["verdict"] == "reject" else 0
        if reject_streak >= 3:
            reject_streak = 0
            run.say("   -- three rejections running. The builder starts fresh.")
            rest(turn)
        send = True
        if stable:
            dry_rounds = 0 if (d["requirements_new"] or pend) else dry_rounds + 1
            send = bool(d["requirements_new"]) or d["challenged"] or d["constrained"] or not check_ok
            if dry_rounds >= 3:
                run.log("stop", reason="three growth rounds in a row added nothing")
                break

        ask = d["review_request"].strip()
        if not ask and stable and counts["reviews"] == 0 and last_review < 0:
            ask = ("It has just gone stable. Attack it with awkward cases the builder did not make up, and check what he has been "
                   "told against what is there.")
        if ask and last_reply and turn - last_review >= 3 and (review_thread is None or not review_thread.is_alive()):
            last_review = turn
            run.say(f"   (a reviewer is commissioned: {ask[:100]})")
            review_thread = threading.Thread(target=review, args=(turn, ask, last_reply), daemon=True)
            review_thread.start()

        if send:
            out = claude(run, "claude", a.model, handover + message, cwd=project, append=norms(amended), session=session,
                         resume=session_started, effort=a.effort, denied=deny,
                         allowed="Bash,Edit,Write,Read,Glob,Grep,Task,Agent,TodoWrite")
            handover, session_started = "", True
            session = out["session"] or session
            claude_seconds += out["seconds"]
            last_reply = out["text"]
            if out["denials"]:
                run.say(f"   ! {len(out['denials'])} tool calls refused: {out['denials']}")
            if check_cmd:
                c = subprocess.run(check_cmd, shell=True, cwd=project, capture_output=True, text=True, timeout=120)
                last_check = "\n".join((c.stdout + c.stderr).strip().splitlines()[-25:])
                check_ok = c.returncode == 0
                run.log("check", ok=check_ok, tail=last_check[-600:])
                run.say(f"   check {'passed' if check_ok else 'FAILED'}: {last_check.splitlines()[-1] if last_check else ''}")
            if show_cmd:
                c = subprocess.run(show_cmd, shell=True, cwd=project, capture_output=True, text=True, timeout=120)
                last_show = "\n".join((c.stdout + c.stderr).strip().splitlines()[-40:])
                run.log("show", tail=last_show[-1200:])
        if review_thread is not None and review_thread.is_alive():
            t = time.time()
            review_thread.join()
            blocking[0] += time.time() - t
        records.append({"turn": turn, "message": message, "reply": last_reply if send else "(nothing was sent)", "check_ok": check_ok,
                        "new": [q["text"][:100] for q in d["requirements_new"]], "declined": [x["idea"][:60] for x in d["ideas_declined"]],
                        "amended": [x["now"][:80] for x in d["constraints_changed"]]})
        if since_rest >= (REST_GROWTH if stable else REST_BUILDING) and turn < turns:
            rest(turn)

    rest(turn, final=True)
    wall = time.time() - run.t0
    rows = run.rows()
    cost_claude = sum(x.get("cost", 0) for x in rows if x["kind"] == "call" and x["role"] == "claude")
    cost_regent = sum(x.get("cost", 0) for x in rows if x["kind"] == "call" and x["role"] != "claude")
    summary = {"turns": turn, "wall_min": round(wall / 60, 1), "claude_min": round(claude_seconds / 60, 1),
               "regent_blocking_min": round(blocking[0] / 60, 1), "claude_share": round(claude_seconds / wall, 2),
               "cost_claude": round(cost_claude, 2), "cost_regent": round(cost_regent, 2), "check_ok": check_ok, "trust": round(trust, 2),
               "counts": counts, "requirements": reqs, "ideas": ideas, "constraints_changed": amended, "escalations": escalations,
               "ways": ways, "notes_for_the_human": human_notes, "memory": remembered(), "project": str(project)}
    run.log("summary", **summary)
    (run.root / "summary.json").write_text(json.dumps(summary, indent=1, ensure_ascii=False))
    built = sum(1 for q in reqs if q["status"] == "built")
    lines = [f"# Digest: {Path(a.charter).stem}", "",
             f"{turn} turns in {summary['wall_min']} minutes. The builder worked for {summary['claude_min']} of them and the owner held it up for {summary['regent_blocking_min']}. "
             f"Spend: builder ${cost_claude:.2f}, owner ${cost_regent:.2f}. The check {'passes' if check_ok else 'FAILS'}.", "",
             f"He directed {counts['direct']} times, challenged {counts['challenge']}, constrained {counts['constrain']}, looked for himself {counts['looks']} times, "
             f"commissioned {counts['reviews']} independent reviews, had {counts['waved']} days with no time, rested {counts['rests']} times, dreamed {counts['dreams']} and stepped back {counts['step_backs']}. Trust in the builder ended at {trust:.2f}.", "",
             f"## Requirements: {built} built of {len(reqs)}, {sum(1 for q in reqs if q['from_dream'])} from dreams", ""]
    lines += [f"- {q['id']} [{q['status']}] turn {q['turn']}{' (dream)' if q['from_dream'] else ''}: {q['text']}" for q in reqs]
    lines += ["", "## Ideas he declined, and why", ""] + ([f"- {i['text']} Why: {i.get('why', '')}" for i in ideas if i["status"] == "declined"] or ["- none"])
    lines += ["", "## Limits he changed", ""] + ([f"- turn {x['turn']}: was \"{x['constraint']}\", now \"{x['now']}\". Why: {x['why']}" for x in amended] or ["- none"])
    lines += ["", "## Questions for you", ""] + ([f"- turn {e['turn']}: {e['question']}" for e in escalations] or ["- none"])
    lines += ["", "## His ways of working", ""] + ([f"- {w}" for w in ways] or ["- none"])
    lines += ["", "## His notes for you", ""] + ([f"- {n}" for n in human_notes] or ["- none"])
    lines += ["", "## What he remembers of the project", "", remembered()]
    (run.root / "digest.md").write_text("\n".join(lines) + "\n")
    run.say(f"stopped after {turn} turns. wall {summary['wall_min']} min, claude {summary['claude_min']} min ({summary['claude_share']:.0%}), "
            f"owner in the way {summary['regent_blocking_min']} min. spend claude ${cost_claude:.2f}, owner ${cost_regent:.2f}. "
            f"check {'passed' if check_ok else 'FAILED'}. requirements {built} built of {len(reqs)}, {sum(1 for q in reqs if q['from_dream'])} from dreams. "
            f"limits changed {len(amended)}. digest: {run.root / 'digest.md'}")


def main():
    ap = argparse.ArgumentParser(description="Regent, the one harness.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="run a charter in a project, new or existing")
    r.add_argument("charter")
    r.add_argument("--project", required=True)
    r.add_argument("--owner", default="owners/piotr-mahon")
    r.add_argument("--run", default=None)
    r.add_argument("--turns", type=int, default=None, help="the budget, a count of sittings. The charter's Budget sets it")
    r.add_argument("--seed", type=int, default=1)
    r.add_argument("--model", default="sonnet")
    r.add_argument("--regent-model", default="sonnet")
    r.add_argument("--effort", default="low")
    r.add_argument("--plant", action="append", default=[], help="something he comes across in his day. He never learns it was yours")
    for name, helptext in (("say", "leave him a note, shown at his next sitting"),
                           ("influence", "steer unseen: 'plant: ...', 'voice: ...', 'mood: risk 3', 'worry: ...', 'itch: ...', 'dream: ...', 'recall: ...'")):
        s = sub.add_parser(name, help=helptext)
        s.add_argument("run")
        s.add_argument("text")
    a = ap.parse_args()
    if a.cmd == "run":
        return run_cmd(a)
    target = Path(a.run) / ("inbox.md" if a.cmd == "say" else "influence.md")
    with target.open("a") as f:
        f.write(a.text.strip() + "\n")
    print(f"written to {target}")


if __name__ == "__main__":
    sys.exit(main())
