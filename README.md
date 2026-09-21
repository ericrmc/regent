# Regent

A simulated owner who governs a project over a long run.

Regent holds a person — a life, a mood, a memory that loses things — and runs
Claude Code in your project on his behalf. A turn is a sitting: one regent
call, then one Claude turn. Nothing else sits in Claude's path.

He is an owner, not a reviewer, and he does not read code. He directs,
challenges, sets limits, changes his mind about a limit, uses the thing, and
when he wants the code examined he asks for that in plain words — the builder
puts a subagent on it, because Claude Code already does reviews well.

What the harness adds is only what a person has and a prompt does not.

**A life.** The unit is a day. Dice decide how the day went, how many sittings
the project gets (a Poisson draw, often none) and how long each one is
(lognormal, bent by how thorough he is and how far he trusts the builder). A
separate small model writes the day's journal from what the dice rolled: two
draws from a table of things that happen in *his* weeks, an open thread that
moves, and at most a quarter of it about the project. He is never asked to
write it, because a model writing its own life unaided writes the same mild day
forever.

**A memory that loses things.** Each night the record of the project is
rewritten as what a person would remember of it, and parts go. The builder is
now and then replaced by a fresh one who gets only that memory.

**Asking where it is up to.** Some sittings he asks before he directs: where the
work is, what the builder thinks comes next. The builder answers from its own
session, where its assumptions live, able to read the project and not change
it. He probes what does not sit right, a few questions at most, and names what
the builder took for granted and whether it holds for him. One that does not
hold is his to act on in the same sitting. The exchange goes into the record the
night's memory is written from, so what he forgot, he can find out again. It is
a draw like the rest: a fresh builder, days away, curiosity and distrust all
pull him to it.

**Sleep.** Nobody dreams on request, so he is never asked to. The spoon cycle
is four runs that are not him:

| | model | reads | does |
| --- | --- | --- | --- |
| Saturate | haiku | the project as he holds it, his recent days | extracts motifs, tensions, questions. Answers nothing |
| Drift | sonnet + haiku, in parallel, over different random days | motifs, the project by id, his bible, days drawn at random with old ones never impossible | links things nobody would file together. Every link anchors in the project and reaches into his life or anything the model knows. Mechanism over imagery |
| Catch | code | the links, in order | the falling spoon: a link that let go of the project is a miss, each miss in a row loosens the grip, and when it drops the pass is over |
| Sift | sonnet, fresh context | the caught links as an anonymous shuffled list, the intent, his taste record | keeps a few as requirements: not fixes for the builder, but what the thing could become for the person it is for, each with why it might fail |

He meets the survivors awake, not knowing where they came from, and takes them
or turns them down. That is the gate. A decline is one of two kinds. Turned
down for good, it goes on his taste record, which Sift reads, so it is not
dreamt twice. Set aside as "not now", it stays off the record, because that is
about his day and not the idea, and a later night may bring the same mechanism
back in another form. Every candidate ends in a row with his reason: taken,
declined, set aside, or still open. The digest and the watch page list them
all, so a declined idea you still want is yours to action.

**Nothing runs on a count.** Sittings, their length, whether he tries the thing
himself, when the spoon falls, when he steps back to look at how the work is
going, when a fresh builder takes over: each is a draw from a distribution or a
hazard that grows with the time since it last happened, tilted by his
disposition. A curious regent dreams more often; a patient one steps back less.

## Install

```
uv tool install -e .
```

Python 3.11+, no dependencies. Needs the `claude` CLI on PATH.

## Run

```
regent cast --pin "a lock keeper" --pin "cannot leave a loose end"
regent run --project ~/code/thing --days 14 --turns-per-day 1.5 --owner <name>
```

`cast` rolls a new owner: the dials from a normal draw, an age, and seven words
from the system dictionary that must turn up in their life, then a model writes
the person who fits, far from software, plus the table of things that happen in
their weeks. `--dial bold=0.6` sets a dial instead of rolling it.

`--days` is how long the run lasts in his life and `--turns-per-day` is the mean
sittings a day, so `0.5` is every other day. Both can live in the charter's
Budget as `days:` and `turns_per_day:`. `--dream-gap` is the mean nights between
spoon cycles.

The charter is `<project>/.regent/charter.md` unless you pass one: a markdown
file whose `##` headings the harness reads: Intent, Constraints, Refusals,
Reserved, Budget, Tools, Network, Check, Show. `examples/linkcheck.md` is a
worked one.
Constraints are the *starting* shape and he may change them, recording why.
Refusals and Reserved bind him absolutely. Check and Show are shell commands
run in your project after each sitting, which is how he sees the thing work
without reading code.

Both he and the builder work inside Claude Code's sandbox. A shell can write
only inside the project and reach only the domains listed under `## Network`,
one per `-` line. No Network section means no network.

The CLI tells every model today's date, your email and the machine it runs on.
He and the night runs never see that: their calls go through a pass-through in
the harness that drops those reminders. The builder's calls go direct.

Re-running the same project resumes the last unfinished run at its next day.
`--new` starts over.

```
regent say  <run-dir> "stop adding flags, I want it faster"
regent plant <run-dir> "a story about a bridge that was measured twice"
regent journal piotr-mahon --last 10
```

`say` is from you and he knows it. `plant` is something he comes across, and he
never learns it was you.

## Watch

```
regent run --project ~/code/thing --watch     # opens the page as the run starts
regent watch                                  # the newest run, at http://127.0.0.1:8642
regent watch thing                            # the newest run of that project
regent watch thing --export thing.html        # one file with the run inside it
```

One page, `watch.html`, read straight from the run's ledger every three
seconds: what is happening now and the builder's tool uses as they land, each
day with what he wrote and what came back, each night with the spoon cycle laid
out (motifs, both drift passes, every link caught, what Sift kept and what he
did with it), his mood, the time he gave, requirements asked and built, the
project's lines by commit, and the spend. `--export` writes the same page as a
single file that needs no server.

## Where things live

```
regent/
  regent.py                  the harness, one file
  owners/<name>/             bible.md, disposition.json, events.md (tracked), life.db (not)
  examples/                  worked charters
  watch.html                 the live page

~/.regent/                   $REGENT_HOME, or --runs
  owners/<name>/             owners you cast
  runs/<project>-<stamp>/
    run.db                   ledger and resumable state
    digest.md                the page you read
```

An owner is a folder you can copy — to another machine, or to point a different
regent at a project. His life is one SQLite file, continuous across every
project he governs, with his taste record; what he remembers, and why he wants it, is per project, so a new regent on an old
project starts with no memory of it.

## A note on scope

The first version of this was 10,914 lines of source, 7,670 of tests, 1,758 of
prompts, a 592-line config holding **224 tunables**, 17 model roles each with
its own prompt and schema, three storage layers, and a hand-rolled wire
protocol propped up by a plugin skill. It worked. Nobody could tune it.

All of that is now one file and one page, because almost everything it did is
something Claude Code already does: sessions, subagents, permissions, the
sandbox, structured output. The harness's job is the owner, and the owner is a
life, a memory and the nights. Think of that before adding a module.
