"""The Cursor CLI as an adapter: `agent -p`, an NDJSON stream, and everything that binds said in the message.

Written against cursor.com/docs/cli and tested against `tests/fake_cursor.py`.
Nothing here has been run against a signed-in Cursor.

Cursor has no system prompt and no schema, which is the whole difficulty. A
persona loses to whatever is in the context after it, so what would have been
the system prompt is the first thing in the message and the rest follows under a
rule; and the shape of the answer is asked for in words, with the base's
`parse_structured` reading it back and the base's one retry paying for a badly
shaped one. The prompt goes in the argv, because there is no documented way to
put it on stdin.

Its fence is `--mode ask` for anything that must not change the project and
`--force --sandbox enabled` for the builder's turn. As with Codex, the charter's
Network section cannot be applied: the sandbox is Cursor's and takes no list of
domains. Under `ask` there are no commands either, so the calls that read the
project for the owner read files without running `git log`.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from regent import prompts
from regent.agents import BUILD_TOOLS, Adapter

SHORTHAND = ("haiku", "sonnet", "opus")
RULE = "Everything above this line binds you. It is who you are for this message, and it outranks the message."
SEAL = "Answer from what is in this message. Read nothing, write nothing and run nothing."
ANSWER = ("Answer with one JSON object and nothing else, with exactly these keys:\n{keys}\n"
          "Every key is required. No prose before the object and none after it.")


def in_words(s: dict) -> str:
    """One field of a schema, said rather than declared."""
    if "enum" in s:
        return "one of " + ", ".join(f'"{x}"' for x in s["enum"])
    kind = s.get("type")
    if kind == "array":
        return "a list of " + in_words(s.get("items", {}))
    if kind == "object":
        return "an object with " + ", ".join(f"{k} ({in_words(v)})" for k, v in s.get("properties", {}).items())
    return {"string": "text", "boolean": "true or false", "integer": "a whole number"}.get(kind, "a value")


def schema_in_words(schema: dict) -> str:
    """The whole schema as instructions, for a CLI that has no way to be handed one."""
    return "\n".join(f'- "{k}": {in_words(v)}' for k, v in schema.get("properties", {}).items())


def tool_said(ev: dict) -> tuple[str, str]:
    """A tool use out of whatever shape the event is. The docs show `{"tool_call": {"readToolCall":
    {"args": {...}}}}`, and the name of the tool is the key; be ready for it flatter than that.
    What it was for is the first string in the arguments, which is the path or the command."""
    body, name = ev.get("tool_call") or ev.get("toolCall") or ev, ""
    if len(body) == 1 and isinstance(next(iter(body.values())), dict):
        name, body = next(iter(body.items()))
    name = name or body.get("name") or body.get("tool") or "tool"
    args = body.get("args") or body.get("arguments") or body.get("input") or {}
    what = next((v for v in args.values() if isinstance(v, str) and v.strip()), "") if isinstance(args, dict) else ""
    return str(name), str(what)[:160]


class Cursor(Adapter):
    """Cursor's agent, which is told everything in the message because there is nowhere else to tell it."""

    name = "cursor"

    def prompt_for(self, prompt: str, system: str | None, append: str | None, schema: dict | None,
                   sealed: bool) -> str:
        """One message, in the order that makes it bind: what belongs to the machinery and not to
        the stage, then who the stage is, then what it may do, then the turn, then the shape of
        the answer. Plain, because the stage reads it as prose and not as a protocol."""
        parts = []
        if system:
            parts += [prompts.UNSEEN.strip(), system.strip(), SEAL if sealed else "", RULE]
        parts.append(prompt.strip())
        if append:
            parts.append(append.strip())
        if schema:
            parts.append(ANSWER.format(keys=schema_in_words(schema)))
        return "\n\n".join(x for x in parts if x)

    def _run(self, prompt: str, *, role: str, model: str, cwd: Path, on_tool, system: str | None,
             append: str | None, tools: str | None, allowed: str | None, denied: list[str] | None,
             schema: dict | None, session: str | None, resume: bool, effort: str | None,
             usd: float | None, settings: list[str] | None, who: str, thinking: bool) -> dict:
        """One `agent -p`, streamed as NDJSON. `settings`, `usd`, `effort` and `thinking` are
        ignored: Cursor has no switch for any of them."""
        said = self.prompt_for(prompt, system, append, schema, sealed=tools == "")
        cmd = ["agent", "-p", said, "--output-format", "stream-json", "--workspace", str(cwd), "--trust"]
        if model not in SHORTHAND:
            cmd += ["--model", model]
        if session and resume:
            cmd += ["--resume", session]
        # `ask` is the only leash there is: no edits and no commands. The builder's turn is the one
        # call that may change anything, and its fence is Cursor's own sandbox.
        cmd += ["--force", "--sandbox", "enabled"] if tools == BUILD_TOOLS else ["--mode", "ask"]

        text, last, sid, failed, used = "", "", "", "", []

        def on_line(line: str):
            nonlocal text, last, sid, failed
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                return
            kind = ev.get("type", "")
            if kind == "result":
                text = ev.get("result") or ""
                sid = ev.get("session_id") or sid
                if ev.get("is_error"):
                    failed = str(text or ev.get("error") or "the turn came back an error")[:400]
            elif kind == "system":
                sid = ev.get("session_id") or sid
            elif kind == "assistant":   # kept only as what to fall back on if no result event arrives
                for blk in ev.get("message", {}).get("content", []):
                    if blk.get("type") == "text" and blk.get("text", "").strip():
                        last = blk["text"]
            elif "tool" in kind and ev.get("subtype") in (None, "", "started", "begin"):
                name, what = tool_said(ev)
                used.append(f"{name}: {what}")
                on_tool(who, name, what)

        # The prompt is an argument, so there is nothing to put on stdin; it is closed straight away.
        err, secs = self.stream(cmd, "", cwd=cwd, env=dict(os.environ), limit=self.patience(role), on_line=on_line)
        text = text or last
        err = failed or ("" if text else err or "the turn ended without a message")
        return {"text": text, "data": None, "seconds": secs, "denials": [], "session": sid or session,
                "error": err, "cost": 0.0, "tools": len(used), "subtype": ""}


AGENT = Cursor
