"""The Codex CLI as an adapter: `codex exec --json`, and files for the two things it has no flag for.

Written against `codex exec --help` (0.135.0), its published docs and its own
event stream, and tested against `tests/fake_codex.py`. Nothing here has been
run against a signed-in Codex: the event names and the config keys were checked
against the real binary, the answers were not.

Three things Codex does its own way, and they are most of this file:

- Its instructions are a file, not a flag. The stage's system prompt is written
  to a temp file and `model_instructions_file` points at it, which replaces
  Codex's base instructions outright, which is what every sealed call wants. The
  builder's norms are an addition rather than a replacement, so they go at the
  end of the turn's own words instead.
- Its schema is a file too, `--output-schema`, and the final message comes back
  as the object. The base reads it out of the message either way.
- Its fence is its own sandbox, `-s read-only` or `-s workspace-write`, and it
  is the only fence there is here, so the bypass flag is never passed. The
  charter's Network section cannot be applied: Codex decides for itself what a
  command may reach, and the harness has no way to hand it a list of domains.
  The run says so when it prints the charter.

Codex also reads an `AGENTS.md` out of the directory it runs in. The builder's
turns run in the project, where that is the owner's business and not the
harness's; every sealed call runs in the run directory, which has none.
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from regent.agents import BUILD_TOOLS, Adapter

SHORTHAND = ("haiku", "sonnet", "opus")   # the sizes the harness names its own stages in, which Codex never heard of


def temp_file(text: str, suffix: str) -> Path:
    """A file that lives as long as the attempt. Codex reads it at startup and never again."""
    fd, path = tempfile.mkstemp(prefix="regent-", suffix=suffix)
    with os.fdopen(fd, "w") as f:
        f.write(text)
    return Path(path)


def closed(schema: dict) -> dict:
    """The schema as a structured-output schema wants it: every object closed to anything it did
    not ask for. Ours already require every property, which is the other half of the same demand."""
    if schema.get("type") == "object":
        return {**schema, "additionalProperties": False,
                "properties": {k: closed(v) for k, v in schema.get("properties", {}).items()}}
    if schema.get("type") == "array" and "items" in schema:
        return {**schema, "items": closed(schema["items"])}
    return schema


class Codex(Adapter):
    """Codex, which takes the prompt on stdin, says what it did as JSONL, and never says what it cost."""

    name = "codex"

    def _run(self, prompt: str, *, role: str, model: str, cwd: Path, on_tool, system: str | None,
             append: str | None, tools: str | None, allowed: str | None, denied: list[str] | None,
             schema: dict | None, session: str | None, resume: bool, effort: str | None,
             usd: float | None, settings: list[str] | None, who: str, thinking: bool) -> dict:
        """One `codex exec`, streamed as JSONL, with the prompt on stdin because `-` is stdin.

        `settings` and `usd` are Claude's and are ignored: Codex has no settings sources to shut
        off, and no way to cap what one call may spend."""
        temps: list[Path] = []
        cmd = ["codex", "exec"]
        if session and resume:
            cmd += ["resume", session]
        cmd += ["--json", "--skip-git-repo-check"]
        if not resume:
            cmd += ["-C", str(cwd)]   # `resume` takes no -C, and the child runs in cwd either way
        if model not in SHORTHAND:
            cmd += ["-m", model]
        if system:
            # It refuses an empty instructions file, so a stage with nothing to say still says a line.
            temps.append(temp_file(system.strip() or "Do what the message asks.", ".md"))
            cmd += ["-c", f'model_instructions_file="{temps[-1]}"']
        if schema:
            temps.append(temp_file(json.dumps(closed(schema)), ".json"))
            cmd += ["--output-schema", str(temps[-1])]
        if level := (effort or ("" if thinking else "low")):
            cmd += ["-c", f'model_reasoning_effort="{level}"']
        if denied:   # no Network section, so no web. It is the one tool of Codex's the harness can name
            cmd += ["-c", "tools.web_search=false"]
        # The only fence. A sealed call and a read-back may read; the builder's turn may write.
        mode = "workspace-write" if tools == BUILD_TOOLS else "read-only"
        cmd += ["-c", f'sandbox_mode="{mode}"'] if resume else ["-s", mode]
        if tools == "":
            cmd.append("--ephemeral")   # a sealed call is one shot, and none of it is worth a session file
        cmd.append("-")
        said = prompt + (f"\n\n{append.strip()}" if append else "")

        text, thread, usage, failed, used = "", "", {}, "", []

        def on_line(line: str):
            nonlocal text, thread, usage, failed
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                return   # the CLI's own logging, which goes to stderr, but be ready for it here too
            kind = ev.get("type", "")
            if kind == "thread.started":
                thread = ev.get("thread_id") or thread
            elif kind == "turn.completed":
                usage = ev.get("usage") or {}
            elif kind in ("turn.failed", "error"):
                bad = ev.get("error") or ev.get("message") or ""
                failed = (bad.get("message") if isinstance(bad, dict) else str(bad)) or "the turn failed"
            elif kind.startswith("item."):
                item = ev.get("item") or {}
                what = item.get("type") or ""
                if what == "agent_message" and (says := (item.get("text") or "").strip()):
                    text = says          # the last one is the turn's final message
                elif what == "command_execution" and kind == "item.started":
                    say_tool("command", str(item.get("command") or ""))
                elif what == "file_change" and kind == "item.completed":
                    paths = [c.get("path", "") for c in item.get("changes") or []] or [item.get("path") or ""]
                    say_tool("file", ", ".join(p for p in paths if p))

        def say_tool(name: str, what: str):
            used.append(f"{name}: {what[:160]}")
            on_tool(who, name, what[:160])

        try:
            err, secs = self.stream(cmd, said, cwd=cwd, env=dict(os.environ), limit=self.patience(role),
                                    on_line=on_line)
        finally:
            for f in temps:
                f.unlink(missing_ok=True)
        # A turn that said nothing is a turn that failed, whatever it printed on the way.
        err = failed[:400] or ("" if text else err or "the turn ended without a message")
        return {"text": text, "data": None, "seconds": secs, "denials": [], "session": thread or session,
                "error": err, "cost": 0.0, "tools": len(used), "subtype": "", "tokens": usage}


AGENT = Codex
