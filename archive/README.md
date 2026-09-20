# Regent

A Python harness that stands in for a human product owner. It holds a charter,
dispatches orchestrators into a real project, reads what comes back through an
attention filter, invents requirements nobody asked for, and escalates only what
the charter reserves. The design is in `design.md`.

The harness is the one long-lived process. Every model call is a `claude -p`
child. The super-orchestrator has no tools. It returns a JSON decision and the
harness applies it.

Python 3.11 or later. `uv sync` installs it.

## Run

```
uv run regent run examples/charter.md --project /tmp/linkcheck --profile cheap
```

`uv run python -m regent ...` is the same program. `--dry-run` prints the
assembled prompt and calls nothing. `--profile cheap` holds the run to sonnet
and haiku.

## Watch

```
uv run regent status     # objectives, requirements, budget, stance, the life
uv run regent watch      # one line per ledger record as it lands
uv run regent digest     # the page for the current period
uv run regent answer e0001 "yes, proceed"
uv run regent stop       # finish the turn in flight, then halt
```

All state is on disk under `--state` (default `run/`), so `stop` then `run`
resumes. Every return is stored whole under `returns/`, read or not. Escalations
notify through `osascript`.

## Test

```
uv run pytest
uv run ruff check .
```

268 tests, under two seconds, every one on `FakeRunner`. Nothing is spent.

## Configure

Every tuned number is in `regent/config.py` with the design value as its
default. Override any field with a JSON file and `--config`. Role to model
mapping, spend ceilings, the permission mode and a second vendor CLI for Sift
live there.

`prompts/` holds one prompt per state. `plugin/` holds the two skills. The
agent's invented life is written under `<state>/life/`.
