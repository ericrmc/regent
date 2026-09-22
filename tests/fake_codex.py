#!/usr/bin/env python3
"""A stand-in for the `codex` CLI, so a whole run can be driven on it for nothing.

It speaks the part of `codex exec --json` the adapter reads: `thread.started`
with a thread id, a `turn.started`, an item or two, and a `turn.completed`. The
prompt comes up stdin because the argv ends in `-`, and the schema is read from
the file `--output-schema` points at, so the answer is the shape the stage asked
for. On a turn Codex would be allowed to write in, it writes a file in the
project and commits it, so the charter's Check has something to pass on.

Put a `codex` shim pointing at this first on PATH and `--agent codex` is free.
"""
from __future__ import annotations

import json
import os
import sys
import uuid

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
# The schema is filled and the turn is committed the same way the claude stand-in does it.
from fake_claude import build, fill

VALUED = ("-m", "--model", "-C", "--cd", "-c", "--config", "--output-schema", "-s", "--sandbox", "-p", "--profile",
          "-o", "--output-last-message", "-i", "--image")


def parse(argv: list[str]) -> tuple[dict, list[str], str]:
    """The flags, every `-c key=value` in order, and the session id if this is a resume."""
    out: dict[str, str] = {}
    configs: list[str] = []
    session = ""
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "resume" and i + 1 < len(argv) and not argv[i + 1].startswith("-"):
            session = argv[i + 1]
            i += 2
        elif a in ("-c", "--config") and i + 1 < len(argv):
            configs.append(argv[i + 1])   # repeatable, so it is a list and not a flag
            i += 2
        elif a in VALUED and i + 1 < len(argv):
            out[a] = argv[i + 1]
            i += 2
        else:
            out[a] = ""
            i += 1
    return out, configs, session


def say(**ev):
    print(json.dumps(ev), flush=True)


def main() -> int:
    args, configs, session = parse(sys.argv[1:])
    sys.stdin.read()
    schema = None
    if path := args.get("--output-schema"):
        with open(path) as f:
            schema = json.load(f)
    sandbox = args.get("-s") or args.get("--sandbox") or ""
    for c in configs:
        if c.startswith("sandbox_mode="):
            sandbox = c.split("=", 1)[1].strip('"')
    say(type="thread.started", thread_id=session or str(uuid.uuid4()))
    say(type="turn.started")
    if sandbox == "workspace-write":   # the one turn Codex would be allowed to change anything in
        build(args)
        say(type="item.started", item={"id": "item_0", "type": "command_execution", "command": "git commit -am ..."})
        say(type="item.completed", item={"id": "item_1", "type": "file_change",
                                         "changes": [{"path": "built.txt", "kind": "add"}]})
    text = (json.dumps(fill(schema)) if schema else
            "I added a line to the file and committed it. Nothing surprising came up.")
    say(type="item.completed", item={"id": "item_2", "type": "agent_message", "text": text})
    say(type="turn.completed", usage={"input_tokens": 1200, "output_tokens": 150})
    return 0


if __name__ == "__main__":
    sys.exit(main())
