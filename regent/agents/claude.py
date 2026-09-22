"""The Claude Code CLI as an adapter: one subprocess, streamed, with a watchdog and one retry.

Everything Claude-specific is here — the flags, the sealed settings, `--bare`,
the stream-json parsing, the session id that is replaced when a session falls
over. Nothing above this file knows how a call is made, only what comes back.
"""
from __future__ import annotations

import json
import os
import subprocess
import threading
import time
import uuid
from pathlib import Path

from regent.agents import Adapter

SEALED = ["--strict-mcp-config", "--setting-sources", ""]  # no tools, no servers, no settings
BUILD_TOOLS = "Bash,Edit,Write,Read,Glob,Grep,Task,Agent,TodoWrite,MultiEdit,NotebookEdit"   # a headless turn's tools


class Claude(Adapter):
    name = "claude"

    def call(self, prompt: str, *, model: str, cwd: Path, on_tool, role: str = "claude",
             system: str | None = None, append: str | None = None, tools: str | None = None,
             allowed: str | None = None, denied: list[str] | None = None, schema: dict | None = None,
             session: str | None = None, resume: bool = False, effort: str | None = None,
             usd: float | None = None, settings: list[str] | None = None, who: str = "claude",
             thinking: bool = True, on_event=None) -> dict:
        """One call, always streamed, so every tool use is seen as it happens.

        Thinking is on unless a stage says otherwise. A stage that only supplies prose does not need
        it and pays dearly for it: the day writer took 86 seconds with it and 4 without, for the same
        day. It stays on for the regent, the builder and the stages that judge."""
        say = on_event or (lambda kind, **kw: None)
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
        if system and os.environ.get("ANTHROPIC_API_KEY"):   # --bare leaves the CLI's reminders out, and needs a key
            cmd.append("--bare")
        env = dict(os.environ)
        if not thinking:
            env["MAX_THINKING_TOKENS"] = "0"
        for attempt in (1, 2):
            start = time.time()
            p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                 cwd=cwd, env=env)
            # Nobody is watching a long run. A child that wedges is killed, and the call fails like any other.
            dog = threading.Timer(5400 if role == "claude" else 1200, p.kill)
            dog.daemon = True
            dog.start()
            try:
                p.stdin.write(prompt)
                p.stdin.close()
            except BrokenPipeError:   # it died on the way up. stderr says why, below
                pass
            # stderr is drained on its own thread. A run is hours long, and a child that
            # fills the 64KB pipe while we are blocked reading stdout would hang forever.
            errbuf: list[str] = []
            drain = threading.Thread(target=lambda buf=errbuf, proc=p: buf.append(proc.stderr.read()),
                                     daemon=True)   # bound, because the retry puts this in a loop
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
                            on_tool(who, blk.get("name"), what)
                elif ev.get("type") == "result":
                    result = ev
            p.wait()
            dog.cancel()
            drain.join(5)
            err = "" if result else ("".join(errbuf))[-400:]
            if result.get("is_error") or (result.get("result") or "").startswith("API Error"):
                err = (result.get("result") or "API error")[:400]
                result = {}
            if err:
                say("empty", err=err)
                if attempt == 1:   # the API was overloaded or the server fell over. Once is weather.
                    say("call", model=model, seconds=round(time.time() - start, 1), cost=0, tools=len(used),
                        denials=[], error=err)
                    time.sleep(30)
                    if session and not resume:   # the id may be taken by the session that just fell over
                        cmd[cmd.index("--session-id") + 1] = str(uuid.uuid4())
                    continue
            secs = round(time.time() - start, 1)
            denials = [x.get("tool_name") for x in result.get("permission_denials", [])]
            say("call", model=model, seconds=secs, cost=result.get("total_cost_usd", 0),
                tools=len(used), denials=denials, error=err)
            structured = result.get("structured_output")
            if schema and structured is None:
                try:
                    structured = json.loads(result.get("result") or "")
                except (json.JSONDecodeError, TypeError):
                    # A model now and then ends its turn without the structured answer. Once is weather; twice is a fault.
                    if attempt == 1 and result.get("subtype") != "error_max_budget_usd":
                        say("retry", subtype=result.get("subtype"))
                        continue
                    raise RuntimeError(f"{role} returned no structured output ({result.get('subtype')}): "
                                       f"{err or (result.get('result') or '')[:200]}") from None
            return {"text": result.get("result") or "", "data": structured, "seconds": secs, "denials": denials,
                    "session": result.get("session_id"), "error": err, "cost": result.get("total_cost_usd", 0)}
