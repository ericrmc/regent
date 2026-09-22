#!/usr/bin/env python3
"""A stand-in for the Cursor `agent` CLI, so a whole run can be driven on it for nothing.

It speaks the part of `--output-format stream-json` the adapter reads: an init
line, a tool call on a turn that builds, and a `result` carrying the text and
the session id. The prompt is an argument and not stdin, and there is no schema
flag, so the answer is built from the adapter's own closing instruction: the
"exactly these keys" block is read back and turned into an object of that shape.
That is the test of the instruction as much as of the adapter, because it is the
only thing standing where a schema would be.

Put an `agent` shim pointing at this first on PATH and `--agent cursor` is free.
"""
from __future__ import annotations

import json
import os
import sys
import uuid

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
# The same short plausible prose, and the same commit, as the claude stand-in.
from fake_claude import build, text_for

VALUED = ("-p", "--print", "--output-format", "--model", "--workspace", "--resume", "--mode", "--sandbox")


def parse(argv: list[str]) -> dict:
    out: dict[str, str] = {}
    i = 0
    while i < len(argv):
        if argv[i] in VALUED and i + 1 < len(argv):
            out[argv[i]] = argv[i + 1]
            i += 2
        else:
            out[argv[i]] = ""
            i += 1
    return out


def fields(s: str):
    """`key (what it is), key (what it is)`, split on the commas outside the parentheses,
    because an enum's own commas sit inside them."""
    parts, depth, start = [], 0, 0
    for i, ch in enumerate(s):
        depth += (ch == "(") - (ch == ")")
        if ch == "," and depth == 0:
            parts.append(s[start:i])
            start = i + 1
    parts.append(s[start:])
    for part in parts:
        key, _, rest = part.strip().partition(" (")
        yield key, rest.rstrip(")")


def value(said: str, key: str):
    """A value of the shape the words describe, the same way fake_claude fills a schema."""
    said = said.strip()
    if said.startswith("one of "):
        return said[len("one of "):].split(",")[0].strip().strip('"')
    if said.startswith("a list of "):
        if key == "anchors":
            return ["why"]          # a real element id, so the spoon's catch keeps the link
        if key == "from_indexes":
            return [0]
        return [value(said[len("a list of "):], key)] * (2 if key in ("links", "feeds") else 1)
    if said.startswith("an object with "):
        return {k: value(v, k) for k, v in fields(said[len("an object with "):])}
    if said == "true or false":
        return False
    if said == "a whole number":
        return 2
    return text_for(key)


def answer(prompt: str) -> dict | None:
    """The object the closing instruction asked for, read back off the instruction itself."""
    if "exactly these keys:" not in prompt:
        return None
    out = {}
    for line in prompt.rsplit("exactly these keys:", 1)[1].splitlines():
        if not line.startswith('- "'):
            continue
        key, _, said = line[3:].partition('": ')
        out[key] = value(said, key)
    return out


def say(**ev):
    print(json.dumps(ev), flush=True)


def main() -> int:
    args = parse(sys.argv[1:])
    prompt = args.get("-p") or args.get("--print") or ""
    session = args.get("--resume") or str(uuid.uuid4())
    say(type="system", subtype="init", session_id=session, model=args.get("--model", "default"),
        cwd=args.get("--workspace", os.getcwd()))
    if "--force" in args:   # the one turn Cursor is allowed to change anything in
        build(args)
        say(type="tool_call", subtype="started", call_id="call_0",
            tool_call={"writeToolCall": {"args": {"path": "built.txt"}}})
        say(type="tool_call", subtype="completed", call_id="call_0",
            tool_call={"writeToolCall": {"args": {"path": "built.txt"}, "result": {"linesCreated": 1}}})
    got = answer(prompt)
    text = (json.dumps(got) if got else
            "I added a line to the file and committed it. Nothing surprising came up.")
    say(type="assistant", message={"content": [{"type": "text", "text": text}]}, session_id=session)
    say(type="result", subtype="success", is_error=False, result=text, session_id=session, duration_ms=1200)
    return 0


if __name__ == "__main__":
    sys.exit(main())
