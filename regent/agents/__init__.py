"""How a model is called, and the one interface an entire Regent can be rebuilt on.

Every call the harness makes goes through one adapter: the owner's decision, the
sealed night runs with their schemas, the readings, the read-backs and the
builder's turns. A run picks its agent once, with `--agent`, and keeps it in the
run state, so a resume is the same agent as the run it resumes.

What the harness means by each argument, so another CLI can honour it in its own
way rather than in Claude's:

    prompt      the words, on stdin, or wherever that CLI takes them
    role        a label: the ledger writes it down and the watchdog waits longer
                for the builder's turn than for anything else
    model       which model. The harness says "sonnet" or "haiku"; map them
    cwd         the directory the call runs in, and the project the builder edits
    system      the whole system prompt. Where a CLI cannot set one, prepend it
                to the prompt: it must arrive before the rest, because a persona
                loses to whatever is in the context after it
    schema      the JSON Schema of the answer. Where a CLI cannot enforce it, ask
                for it in words and hand the text to `parse_structured`
    tools=""    a sealed call: it must run no tools and touch nothing. Every
                stage but the builder is sealed
    allowed     the builder's leash, as tool names. Map them to what that CLI has
    denied      what it may not use, the same way
    append      added to the system prompt rather than replacing it
    session     an id to run under, and with resume=True an id to carry on from.
                Honour this or the builder forgets the project every turn
    effort      how hard to think, where that is a setting
    usd         a spending cap on this one call, where that exists
    settings    Claude-shaped, and any other adapter may ignore it
    thinking    False means reasoning off if the CLI has a switch for it
    who         who the tool uses belong to, for `on_tool` and the watch page
    on_tool     on_tool(who, name, what) for every tool use as it happens

and what must come back, whatever the adapter has to invent for it:

    text        the final message
    data        the structured answer, or None if there was no schema
    seconds     how long it took
    denials     the tool calls that were refused, by name, or []
    session     the session it actually ran in, or None
    error       "" or what went wrong
    cost        US dollars, and 0 when the CLI does not say

An adapter implements `_run` and nothing else. The subprocess, the watchdog, the
one retry, the ledger events and pulling an answer out of free text are all in
the base class, so a new agent is about a screen of code.
"""
from __future__ import annotations

import importlib
import json
import re
import subprocess
import threading
import time
import uuid
from pathlib import Path
from typing import ClassVar

from regent.prompts import PLAIN

BUILD_TOOLS = "Bash,Edit,Write,Read,Glob,Grep,Task,Agent,TodoWrite,MultiEdit,NotebookEdit"   # a headless turn's tools
FENCED = re.compile(r"```(?:json)?\s*(.+?)```", re.S)


class Adapter:
    """One agent, running every call of a run. Subclass it and write `_run`."""

    name = "adapter"
    SEALED: ClassVar[list[str]] = []   # what this CLI is given for a call the harness wants nothing around
    holds_network = False   # whether this CLI can be handed the charter's Network section, or only its own sandbox
    PAUSE = 30        # what a call that came back with nothing waits before its one retry
    SLOW, QUICK = 5400, 1200   # how long a builder's turn may take, and how long anything else may

    # --- what a subclass writes ------------------------------------------------

    def _run(self, prompt: str, *, role: str, model: str, cwd: Path, on_tool, system: str | None,
             append: str | None, tools: str | None, allowed: str | None, denied: list[str] | None,
             schema: dict | None, session: str | None, resume: bool, effort: str | None,
             usd: float | None, settings: list[str] | None, who: str, thinking: bool) -> dict:
        """One attempt: build the command, run it through `stream`, map its event stream.

        Return the seven keys `call` returns, plus `tools`, how many tool uses there were,
        and `subtype`, why the CLI stopped if it says. `data` is filled only where the CLI
        enforced the schema itself; leave it None and the base class will read the text."""
        raise NotImplementedError

    # --- what every adapter gets -----------------------------------------------

    def patience(self, role: str) -> int:
        """Nobody is watching a long run, so a child that wedges is killed and the call
        fails like any other. A builder's turn earns the long wait; nothing else does."""
        return self.SLOW if role == "claude" else self.QUICK

    def stream(self, cmd: list[str], prompt: str, *, cwd: Path, env: dict, limit: int, on_line) -> tuple[str, float]:
        """Run it, feed it the prompt, hand over every line of stdout as it lands, and come
        back with what it said on stderr and how long it took.

        stderr is drained on its own thread. A run is hours long, and a child that fills the
        64KB pipe while we are blocked reading stdout would hang forever."""
        start = time.time()
        p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                             cwd=cwd, env=env)
        dog = threading.Timer(limit, p.kill)
        dog.daemon = True
        dog.start()
        try:
            p.stdin.write(prompt)
            p.stdin.close()
        except BrokenPipeError:   # it died on the way up. stderr says why, below
            pass
        errbuf: list[str] = []
        drain = threading.Thread(target=lambda buf=errbuf, proc=p: buf.append(proc.stderr.read()),
                                 daemon=True)   # bound, because the retry puts this in a loop
        drain.start()
        for line in p.stdout:
            on_line(line)
        p.wait()
        dog.cancel()
        drain.join(5)
        return ("".join(errbuf))[-400:], round(time.time() - start, 1)

    @staticmethod
    def parse_structured(text: str, schema: dict) -> dict | None:
        """The answer out of free text, for a CLI that cannot be made to return only JSON.

        A fenced block first, then the outermost braces, and it must carry the keys that were
        asked for: half an answer is worse than none, because every caller reads its fields
        without looking. None is the hook for the one retry in `call`."""
        if not text:
            return None
        chunks = [m.strip() for m in FENCED.findall(text)]
        i, j = text.find("{"), text.rfind("}")
        if 0 <= i < j:
            chunks.append(text[i:j + 1])
        for chunk in chunks:
            try:
                got = json.loads(chunk)
            except json.JSONDecodeError:
                continue
            if isinstance(got, dict) and all(k in got for k in schema.get("required", ())):
                return got
        return None

    def call(self, prompt: str, *, model: str, cwd: Path, on_tool, role: str = "claude",
             system: str | None = None, append: str | None = None, tools: str | None = None,
             allowed: str | None = None, denied: list[str] | None = None, schema: dict | None = None,
             session: str | None = None, resume: bool = False, effort: str | None = None,
             usd: float | None = None, settings: list[str] | None = None, who: str = "claude",
             thinking: bool = True, on_event=None) -> dict:
        """One call, and one retry, because once is weather and twice is a fault.

        A call that comes back with nothing was the API overloaded or a server falling over;
        it waits and goes again, under a new session id, because the id may be held by the
        session that just fell over. A call that ends without the structured answer it was
        asked for goes again too, unless it stopped because it ran out of money.

        `on_event(kind, **fields)` is the ledger, and an adapter never sees it: "call" for
        every attempt, "retry" when the answer was missing, "empty" when nothing came back."""
        say = on_event or (lambda kind, **kw: None)
        for attempt in (1, 2):
            raw = self._run(prompt, role=role, model=model, cwd=cwd, on_tool=on_tool, system=system, append=append,
                            tools=tools, allowed=allowed, denied=denied, schema=schema, session=session,
                            resume=resume, effort=effort, usd=usd, settings=settings, who=who, thinking=thinking)
            err = raw["error"]
            if err:
                say("empty", err=err)
                if attempt == 1:
                    say("call", model=model, seconds=raw["seconds"], cost=0, tools=raw["tools"], denials=[], error=err)
                    time.sleep(self.PAUSE)
                    if session and not resume:   # the id may be taken by the session that just fell over
                        session = str(uuid.uuid4())
                    continue
            say("call", model=model, seconds=raw["seconds"], cost=raw["cost"], tools=raw["tools"],
                denials=raw["denials"], error=err)
            data = raw["data"]
            if schema and data is None:
                data = self.parse_structured(raw["text"], schema)
                if data is None:
                    # A model now and then ends its turn without the structured answer. Once is weather; twice is a fault.
                    if attempt == 1 and raw["subtype"] != "error_max_budget_usd":
                        say("retry", subtype=raw["subtype"])
                        continue
                    raise RuntimeError(f"{role} returned no structured output ({raw['subtype']}): "
                                       f"{err or raw['text'][:200]}")
            return {"text": raw["text"], "data": data, "seconds": raw["seconds"], "denials": raw["denials"],
                    "session": raw["session"], "error": err, "cost": raw["cost"]}


def builder(name: str = "claude") -> Adapter:
    """Which agent runs every call of this run. One is written; the others are a file each."""
    try:
        mod = importlib.import_module(f"regent.agents.{name}")
    except ModuleNotFoundError:
        raise SystemExit(f"no agent {name!r}. It would be regent/agents/{name}.py: an Adapter with a _run that "
                         f"builds a command and maps its event stream, and AGENT naming the class") from None
    return mod.AGENT()


def call(run, adapter: Adapter, role: str, model: str, prompt: str, **kw) -> dict:
    """One call, with the ledger wired to it. Every tool use is logged and said as it happens,
    and every attempt, including one that came back with nothing, is a call in the ledger."""
    def on_tool(who: str, tool: str, what: str):
        run.log("tool", who=who, name=tool, what=what)
        run.say(f"   {who} > {tool}: {what[:90].splitlines()[0] if what else ''}")

    def on_event(kind: str, **fields):
        if kind == "empty":
            run.say(f"   ! {role} came back with nothing: {fields['err'][-160:]}")
        else:
            run.log(kind, role=role, **fields)

    return adapter.call(prompt, role=role, model=model, on_tool=on_tool, on_event=on_event, **kw)


def ask(run, adapter: Adapter, role: str, model: str, prompt: str, schema: dict | None = None,
        system: str | None = None, thinking: bool = True):
    """A sealed call: no tools, no settings, nothing but the words. It never runs on
    Claude Code's own system prompt, which would make a programmer of every night run."""
    got = call(run, adapter, role, model, prompt, cwd=run.root, tools="", schema=schema, system=system or PLAIN,
               thinking=thinking)
    return got["data"] if schema else got["text"].strip()
