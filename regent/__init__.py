"""Regent: a simulated owner who governs a project over days of his life.

The package holds the regent, a person with a life, a mood and a memory, and it
runs Claude Code in the project on his behalf. A sitting is one regent call,
then one Claude turn. Nothing else sits in Claude's path.

    regent cast --pin "impatient, generous, cannot leave a loose end"
    regent run --project ~/code/thing --days 10 --turns-per-day 1.5
    regent say <run> "a note from you, shown at his next sitting"
    regent plant <run> "something he comes across, never traced to you"
    regent watch
    regent journal piotr-mahon

The unit is a day. The dice decide how the day went, how many sittings the
project gets and how long each one is; models write the prose. Awake he is an
owner, not a reviewer: he directs, challenges, sets limits, uses the thing, and
asks the builder for a review when he wants one, because the builder has
subagents for that.

Between them is the crossing, and nothing of the builder's gets over it as it
was written. Every reply, every answer, every read-back is read for him by a
small model that is not him, in the time he had, and only that reading goes on
into his context, his record, his memory and his nights. Going the other way he
speaks rather than writes and names what he wants rather than specifying it,
and the builder says it back to him as a requirement before it builds. Without
this he drifts: by the fourteenth sitting of a twenty-day run he was dictating
shell commands, because a system prompt saying he is a farmer loses to a
context full of someone else's trade.

At night the work he cannot be asked to do happens without him. Nobody dreams
on request, so he is never asked to. The spoon cycle is four runs that are not
him. Saturate reads the project and his days and extracts what runs through
them, answering nothing. Drift, a different run, links things that nobody would
file together, every link anchored in the project and reaching into his life
or anything else it knows, mechanism over imagery. Catch is the falling spoon,
in code: the pass ends when the links let go of the project.

Nothing arrives off one night. What is caught goes into the field, where notions
stir under his notice and are fed a piece at a time by his days, his reading,
the thing itself and the nights, and where all of it leaks every night. What
gathers enough crosses, one at a time, and Sift says that one notion and
everything that ever fed it, shuffled and anonymous, in a context that never
watched it gather: an ask to build, a doubt only he can answer, a wish for what
this could become, a worry about what follows if it works. He wakes with one, or
it comes to him at the desk, or on a day he gave the work no time at all. He
takes them, answers them or turns them down, and that is the gate. What arrived
is not spent: it goes on gathering, and has to bring the next thing when it
comes round again. Consolidate is the
forgetting: his memory of the project is rewritten lossy, and what he declined
for good goes on his taste record so it is not dreamt twice. What he only set
aside does not.

Now and then he is away from it altogether, and that is where the why moves. He
is handed why he wanted it, every earlier version of it, his own days, and the
counters last and smallest, and he says why he wants it now, what it could
become and what follows if it works. That is written back to his life, so the
next sitting is the man who wants that. A project whose reason has not changed
in twenty days is one nobody has used.

Every cadence here is a draw from a distribution, never a count. The first
harness was 10,914 lines and 224 tunables, and nobody could tune it. Almost
everything it did, Claude Code already does. Think of that before adding a
module.

This file holds only where things live on disk. Nothing here imports a
submodule, so every other module may import it.
"""
from __future__ import annotations

import os
from pathlib import Path

HOME = Path(os.environ.get("REGENT_HOME", Path.home() / ".regent"))
PACKAGE = Path(__file__).resolve().parent
OWNERS = PACKAGE.parent / "owners"   # the sample owners, which ship beside the package rather than in it
