# Regent

A simulated owner who governs a project over a long run.

Regent holds a person — a life, a mood, a memory that loses things — and runs
Claude Code in your project on his behalf. A turn is a sitting: one regent
call, then one Claude turn. Nothing else sits in Claude's path.

He is an owner, not a reviewer, and he does not read code. He directs,
challenges, sets limits, changes his mind about a limit, uses the thing, and
when he wants the code examined he asks for that in plain words — the builder
puts a subagent on it, because Claude Code already does reviews well.

What the harness adds is only what a person has and a prompt does not:

- **A life** that goes on whether the project does or not. Most days the
  project is absent from it.
- **A memory** of the project that is compressed and partly lost every few
  turns, so the builder is handed a memory rather than a transcript.
- **Sleep.** Asleep he is not looking at the code, so what he brings back is
  not a variation on what is already there. The dream takes a problem from his
  life — something waited on someone who never answered, something measured
  twice whose ends disagreed, a thing easy to do and impossible to undo — and
  finds where the project has that same shape. The mapping is the idea. This is
  the point of the whole thing.

## Install

```
uv tool install -e .
```

Python 3.11+, no dependencies. Needs the `claude` CLI on PATH.

## Run

```
regent run --project ~/code/thing
```

The charter is `<project>/.regent/charter.md` unless you pass one. It is a
markdown file whose `##` headings the harness reads: Intent, Constraints,
Refusals, Reserved, Budget, Tools, Check, Show, Stop. `examples/linkcheck.md`
is a worked one.

Constraints are the *starting* shape and he may change them, recording why.
Refusals and Reserved bind him absolutely. Check and Show are shell commands
the harness runs in your project after each turn — how he sees the thing work
without reading code.

Re-running the same project resumes the last unfinished run. `--new` starts
over.

```
regent run --project ~/code/thing --turns 20 --owner piotr-mahon
regent say  <run-dir> "stop adding flags, I want it faster"
regent plant <run-dir> "a story about a bridge that was measured twice"
regent journal piotr-mahon --last 10
```

`say` is from you and he knows it. `plant` is something he comes across, and he
never learns it was you.

## Where things live

```
regent/
  regent.py                  the harness, one file
  owners/<name>/             bible.md, disposition.json, life.db
  examples/                  worked charters
  archive/                   the old harness, as a parts bin

~/.regent/                   $REGENT_HOME, or --runs
  runs/<project>-<stamp>/
    run.db                   ledger and resumable state
    digest.md                the page you read
```

An owner is a folder you can copy — to another machine, or to point a different
regent at a project. His life is one SQLite file, continuous across every
project he governs; what he remembers is per project, so a new regent on an old
project starts with no memory of it.

## A note on scope

`archive/` is the first version of this: 10,914 lines of source, 7,670 of
tests, 1,758 of prompts, a 592-line config holding **224 tunables**, 17 model
roles each with its own prompt and schema, three storage layers, and a
hand-rolled `===RETURN===` wire protocol propped up by a plugin skill. It
worked. Nobody could tune it.

The whole of that is now ~750 lines, because almost everything it did is
something Claude Code already does. The harness's job is the owner, and the
owner is a life, a memory and a dream. Read the archive before adding a module.
