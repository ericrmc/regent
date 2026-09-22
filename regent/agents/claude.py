"""The Claude Code CLI as an adapter: the flags, and the stream-json events they come back as.

Everything Claude-specific is here — the sealed settings, `--bare`, the session
flags, how a tool use looks on the wire. The subprocess, the watchdog, the one
retry and the ledger are the base class's. Nothing above this file knows how a
call is made, only what comes back.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import ClassVar

from regent.agents import Adapter


class Claude(Adapter):
    """Claude Code, which enforces the schema itself and says what a call cost."""

    name = "claude"
    SEALED: ClassVar[list[str]] = ["--strict-mcp-config", "--setting-sources", ""]   # no tools, no servers, no settings
    holds_network = True   # the sandbox takes the charter's domains, and nothing else here does

    def _run(self, prompt: str, *, role: str, model: str, cwd: Path, on_tool, system: str | None,
             append: str | None, tools: str | None, allowed: str | None, denied: list[str] | None,
             schema: dict | None, session: str | None, resume: bool, effort: str | None,
             usd: float | None, settings: list[str] | None, who: str, thinking: bool) -> dict:
        """Always streamed, so every tool use is seen as it happens.

        Thinking is on unless a stage says otherwise. A stage that only supplies prose does not need
        it and pays dearly for it: the day writer took 86 seconds with it and 4 without, for the same
        day. It stays on for the regent, the builder and the stages that judge."""
        cmd = ["claude", "-p", "--model", model, *(settings if settings is not None else self.SEALED),
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
        result, used = {}, []

        def on_line(line: str):
            nonlocal result
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                return
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

        err, secs = self.stream(cmd, prompt, cwd=cwd, env=env, limit=self.patience(role), on_line=on_line)
        err = "" if result else err   # stderr only matters when no result event arrived at all
        if result.get("is_error") or (result.get("result") or "").startswith("API Error"):
            err = (result.get("result") or "API error")[:400]
            result = {}
        return {"text": result.get("result") or "", "data": result.get("structured_output"), "seconds": secs,
                "denials": [x.get("tool_name") for x in result.get("permission_denials", [])],
                "session": result.get("session_id"), "error": err, "cost": result.get("total_cost_usd", 0),
                "tools": len(used), "subtype": result.get("subtype")}


AGENT = Claude
