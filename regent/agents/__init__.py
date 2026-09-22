"""How the harness talks to a model, and the one interface a second builder would have to meet.

An adapter has one method, `call`, and knows nothing of the ledger: it reports a
tool use through `on_tool` and an attempt through `on_event`, and the harness
side of that wiring is `call` and `ask` below, which are the only things in the
package that touch both an adapter and a `Run`.

An adapter must honour:

    prompt        the words, on stdin
    model         which model
    session       an id to start a session under, or to resume when resume is True
    resume        whether that session already exists
    cwd           the directory the call runs in
    on_tool       on_tool(who, name, what) for every tool use as it happens
    role          a label for the ledger and for how long the watchdog waits

and must return a dict with these keys, whatever it has to invent for them:

    text          the final message
    data          the structured answer, or None
    seconds       how long it took
    denials       the tool calls that were refused, by name
    session       the session id it actually ran in
    error         "" or what went wrong
    cost          US dollars

A builder-only adapter may ignore the rest, because they are how the harness
seals a call that is not the builder's: system, append, tools, allowed, denied,
schema, effort, usd, settings, thinking, and on_event. Ignoring `schema` means
the adapter cannot serve the owner or the nights, only the builder's turns.
"""
from __future__ import annotations

from pathlib import Path

from regent.prompts import PLAIN


class Adapter:
    """The interface. One method, and no knowledge of the run it serves."""

    name = "adapter"

    def call(self, prompt: str, *, model: str, cwd: Path, on_tool, role: str = "claude",
             system: str | None = None, append: str | None = None, tools: str | None = None,
             allowed: str | None = None, denied: list[str] | None = None, schema: dict | None = None,
             session: str | None = None, resume: bool = False, effort: str | None = None,
             usd: float | None = None, settings: list[str] | None = None, who: str = "claude",
             thinking: bool = True, on_event=None) -> dict:
        raise NotImplementedError


def builder(name: str = "claude") -> Adapter:
    """Which builder runs the calls. One today, and the name is where a second one lands."""
    if name == "claude":
        from regent.agents.claude import Claude
        return Claude()
    raise SystemExit(f"no builder {name!r}")


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
