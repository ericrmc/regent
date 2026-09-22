#!/usr/bin/env python3
"""A stand-in for the `claude` CLI, so a whole run can be driven for nothing.

It speaks the only part of the protocol the harness reads: a `stream-json`
line or two on stdout, ending in a `result` event. Given `--json-schema` it
hands back a `structured_output` that satisfies the schema, filling strings with
short plausible text, arrays with an item or two, booleans false and enums with
their first value. Given a builder's turn — no `--system-prompt`, and Write
among the allowed tools — it also writes a file in the project and commits it,
so the charter's Check has something to pass on.

Put a `claude` shim pointing at this first on PATH and the run is free.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import uuid

VALUED = ("--model", "--system-prompt", "--append-system-prompt", "--tools", "--allowedTools", "--disallowedTools",
          "--json-schema", "--effort", "--max-budget-usd", "--settings", "--setting-sources", "--session-id",
          "--resume", "--permission-mode", "--output-format")


def parse(argv: list[str]) -> dict:
    out: dict[str, str] = {}
    i = 0
    while i < len(argv):
        a = argv[i]
        if a in VALUED and i + 1 < len(argv):
            out[a] = argv[i + 1]
            i += 2
        else:
            out[a] = ""
            i += 1
    return out


def text_for(key: str) -> str:
    """Short plausible prose, and a question mark where the field is a question."""
    if key in ("question", "ask_the_human"):
        return "Who is this actually for?"
    if key in ("name", "idea", "notion"):
        return ""
    if key == "stream":
        return "reading"
    if key == "seed":
        return f"a small thing that keeps coming back ({uuid.uuid4().hex[:6]})"
    return f"plain words about {key}, said the way he would say it"


def fill(schema: dict, key: str = ""):
    kind = schema.get("type")
    if "enum" in schema:
        return schema["enum"][0]
    if kind == "object":
        return {k: fill(v, k) for k, v in schema.get("properties", {}).items()}
    if kind == "array":
        if key == "anchors":
            return ["why"]          # a real element id, so the spoon's catch keeps the link
        if key == "from_indexes":
            return [0]
        return [fill(schema["items"], key)] * (2 if key in ("links", "feeds") else 1)
    if kind == "boolean":
        return False
    if kind == "integer":
        return 2
    return text_for(key)


def build(args: dict):
    """A builder's turn leaves something behind, because the harness runs the charter's Check after it."""
    line = f"built at turn {uuid.uuid4().hex[:8]}\n"
    with open("built.txt", "a") as f:
        f.write(line)
    env = {**os.environ, "GIT_AUTHOR_NAME": "fake", "GIT_AUTHOR_EMAIL": "fake@example.com",
           "GIT_COMMITTER_NAME": "fake", "GIT_COMMITTER_EMAIL": "fake@example.com"}
    subprocess.run(["git", "add", "-A"], capture_output=True, env=env)
    subprocess.run(["git", "commit", "-q", "-m", "a turn of the builder's"], capture_output=True, env=env)


def main() -> int:
    args = parse(sys.argv[1:])
    sys.stdin.read()
    schema = json.loads(args["--json-schema"]) if args.get("--json-schema") else None
    building = "--system-prompt" not in args and "Write" in (args.get("--allowedTools") or "")
    if building:
        build(args)
        print(json.dumps({"type": "assistant", "message": {"content": [
            {"type": "tool_use", "name": "Write", "input": {"file_path": "built.txt"}}]}}), flush=True)
    print(json.dumps({
        "type": "result", "subtype": "success", "is_error": False,
        "result": "I added a line to the file and committed it. Nothing surprising came up.",
        "structured_output": fill(schema) if schema else None,
        "session_id": args.get("--resume") or args.get("--session-id") or str(uuid.uuid4()),
        "total_cost_usd": 0.01, "permission_denials": []}), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
