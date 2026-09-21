#!/usr/bin/env python3
"""Regent: a simulated owner who governs a project over days of his life.

One process. It holds the regent, a person with a life, a mood and a memory,
and it runs Claude Code in the project on his behalf. A sitting is one regent
call, then one Claude turn. Nothing else sits in Claude's path.

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
"""
from __future__ import annotations

import argparse
import difflib
import http.client
import http.server
import json
import math
import os
import random
import re
import sqlite3
import subprocess
import sys
import threading
import time
import uuid
import webbrowser
from pathlib import Path

HOME = Path(os.environ.get("REGENT_HOME", Path.home() / ".regent"))
SEALED = ["--strict-mcp-config", "--setting-sources", ""]  # no tools, no servers, no settings
SPOT_USD = 0.30   # a spot check is a glance, two or three commands. The CLI enforces it, so no limiter here.
# Every call that is not the builder replaces Claude Code's system prompt. This is what the night runs get.
PLAIN = ("You are one stage of a longer process, not an assistant in a conversation and not a programmer. "
         "Do what the message asks, in the form it asks for, and add nothing around it.")
DIALS = ("bold", "curious", "patient", "trusting", "thorough", "stubborn", "restless")

STR, BOOL = {"type": "string"}, {"type": "boolean"}


def arr(x: dict) -> dict:
    return {"type": "array", "items": x}


def obj(**props) -> dict:
    return {"type": "object", "properties": props, "required": list(props)}


DECISION = obj(
    stance_line=STR, verdict={"type": "string", "enum": ["continue", "accept", "reject"]}, message=STR,
    challenged=BOOL, constrained=BOOL, wants_new=arr(obj(name=STR, want=STR, notice=STR, idea=STR)),
    requirements_built=arr(STR), ideas_declined=arr(obj(idea=STR, why=STR, not_now=BOOL)),
    ideas_answered=arr(obj(idea=STR, answer=STR)),
    constraints_changed=arr(obj(constraint=STR, now=STR, why=STR)), ask_the_human=STR,
    wants_to_look=BOOL, looked_at=arr(STR), look_matched=BOOL, notes_to_self=STR, done=BOOL)
ASKED = obj(question=STR, assumptions=arr(obj(assumption=STR, holds=BOOL, why=STR)), enough=BOOL)
TAKEN = obj(taken=STR, not_followed=arr(STR), not_reached=STR, picked_up=arr(STR))
READBACK = obj(readings=arr(obj(name=STR, spec=STR, test=STR)), questions=arr(STR))
ANSWERED = obj(said=STR, misread=arr(obj(name=STR, what=STR)))
MOTIFS = obj(motifs=arr(STR), tensions=arr(STR), questions=arr(STR))
LINKS = obj(links=arr(obj(kind={"type": "string", "enum": ["metaphor", "causal analogy", "structural analogy", "seed"]},
                          text=STR, anchors=arr(STR), other=STR, mechanism=STR)))
SIFTED = obj(candidates=arr(obj(kind={"type": "string", "enum": ["ask", "doubt", "wish", "worry"]},
                                text=STR, test=STR, from_indexes=arr({"type": "integer"}), why_it_might_fail=STR)))
FED = obj(feeds=arr(obj(notion=STR, seed=STR, stream=STR, strength={"type": "integer"}, because=STR)))
STEPBACK = obj(why_now=STR, could_become=STR, follows=STR,
               observations=arr(STR), ways=arr(STR), notes_for_the_human=arr(STR))
PICTURE = obj(picture=STR, gaps=arr(STR))
CAST = obj(name=STR, slug=STR, bible=STR, events=arr(STR), pursuits=arr(STR))
EVENTS = obj(events=arr(STR))
PURSUITS = obj(pursuits=arr(STR))

TAKE_P = """Something written by a builder has reached the person below. Write what THEY TOOK FROM IT in the time they
had. This is a reading, not a summary. Nobody carries away what was written. They carry what it meant to them, in words
they already own.

WHO IS READING
{who}

HOW THEY WRITE WHEN IT IS ONLY FOR THEMSELVES
{voice}

WHAT THEY ALREADY HOLD OF THIS PROJECT. They know this. It does not need saying to them again, and nothing they plainly
know belongs in not_followed.
{knows}

THE TIME THEY HAD: {minutes} minutes. Under ten minutes they get whether the news is good or bad and the first thing
said. With half an hour they get the main points. With an evening they get all of it and notice what was left unsaid.

WORDS OF THE BUILDER'S TRADE THEY HAVE PICKED UP ON THIS PROJECT AND NOW OWN. The words of their own charter were always
theirs and are not listed here.
{lexicon}

WHAT REACHED THEM
{text}

Write `taken` in the first person, in their voice, as they would say it over to themselves walking back across the yard.
Plain is the voice. Dialect and their own life are seasoning, used only where the thing truly calls it up, never a simile
for its own sake. Everything that matters to an owner survives as its meaning: what changed, what is claimed to work and
on what evidence, what the builder wants to do next, what the builder took for granted, what it is unsure of, a number
that matters. No word of the builder's trade survives unless it is on the list above: no name of a test, file, function,
command or id. Say what the thing is for. When the writing does not make that plain to someone who cannot read code, do
not guess. Put it in `not_followed`, in their words, as a thing they could ask about another day. If the time ran short,
`not_reached` says what part they did not get to, by what it looked to be about. Do not invent, do not judge for them,
do not decide what they do next. `picked_up` is at most two single words of the builder's trade, never ordinary English
and never a phrase, that the writing itself explained well enough that this person would now use them."""

PICTURE_P = """This person owns a thing being built for them and cannot read a line of it. Below is how they understood
it before and what has reached them since. Rewrite how they understand it now.

WHO THEY ARE
{who}

HOW THEY UNDERSTOOD IT BEFORE
{before}

WHAT HAS REACHED THEM SINCE, in their own words as they took it
{since}

Write `picture` in the first person, in their own plain words, under 200 words: what this thing is, what its parts are,
and what each part is for. A part is named by what it does for somebody, never by what it is made of. Where it comes
naturally, and only there, say what a part is like in their own life, because that is how a person holds a thing they
cannot open. Nothing of the builder's trade: no file, no command, no id, no name of a test.

This changes slowly. Keep whatever still holds, in the words it was already held in, and change only what has actually
moved. A picture rewritten every night is not a picture.

Then `gaps`, four at the most and fewer is usual: things they know they do not understand, and that matter for deciding
what this should do or become. What it is really for, who it is really for, what it is worth, where it should go. Never
how the code works, and never anything a builder would answer with a file. Each in their own words, as a thing they
could ask about standing in a yard. An empty list is a fine answer."""

SATURATE_P = """Read all of this and extract what runs through it. Answer nothing.

WHY ITS OWNER WANTS IT, IN HIS OWN WORDS
{why}

THE PROJECT, as its owner holds it. Each element has an id.
{project}

THE OWNER'S RECENT DAYS
{life}

Extract three things. Motifs: a shape that recurs in more than one place, in the project or across the project and the
days. Tensions: two things here that pull against each other. Questions: what this raises and does not settle.
Prefer the motif nobody has named yet. Do not answer the questions, propose work, recommend or rank."""

DRIFT_P = """Produce about {target} links between things that do not obviously belong together.

MOTIFS FROM THIS CYCLE
{motifs}

THE PROJECT AS ITS OWNER HOLDS IT, and not one line of it in the builder's words. Each element has an id. `why` is why
he wants the thing at all, and `could` and `follows` are where he thinks it could go and what he thinks comes of it if
it works. A `req-` is a thing he has asked for, under his own name for it. An `nf-` is something he was told and did not
follow, and has not asked about. An `I` is a doubt or a worry he has been left with and has not answered. The rest is
what he remembers and what he says to himself.
{project}

A LIFE. The person this project belongs to, and some of their days, drawn at random. Day ids begin with L.
{bible}

{days}

The life is fuel. It is not evidence and it settles nothing. It is where a bridge comes from that the project could not
have supplied on its own, because everything in the project is already filed next to everything else in it.

No problem is attached to this pass. Do not invent one to aim at. The disposition tonight is {stance}: risk-weighted
leans toward what fails, what has no limit, what happens twice; opportunity-weighted leans toward what this could also
be, which two parts are really one thing, who else it serves. Both are wanted. The lean tilts the mix.

A link is two elements nobody would file together, plus the thing that transfers between them. Every link names at
least one project id in anchors. A link with none is discarded, and the pass ends when they keep coming, so anchor in
the project and then reach. In other, name what it was joined to: a day id, a person or place from the life, or
"outside: <domain>" for anything you already know. Reach anywhere: queueing, metallurgy, epidemiology, shipping,
typesetting, funerals, allotments. Mechanism over imagery, always. A link that imports how one thing's machinery would
work in the other's place is worth fifty that observe two things are alike. State the transferable mechanism in one
line, or leave it empty when the link is only an image. Do not link the same pair twice."""

SIFT_P = """Something has gathered in an unknown person until it has to be said. You have not seen it before and know
nothing about whose it is or how long it has been there. Say it once, in one candidate, or say nothing.

WHAT GATHERED, in the few words it has been carried in
{notion}

WHAT FED IT, numbered from 0, shuffled, from several places over several days, and there is no telling which came from
where
{holding}

WHAT IS BEING BUILT AND WHO IT IS FOR
{intent}

WHY ITS OWNER WANTS IT, IN HIS OWN WORDS. This is the thing to serve, and it is allowed to be bigger than the list.
{why}

NEVER CROSSED
{refusals}

WHAT IT ALREADY DOES
{built}

WHAT ITS OWNER HAS ALREADY ANSWERED FOR HIMSELF, so it is not asked again
{whys}

WHAT ITS OWNER HAS TAKEN AND TURNED DOWN BEFORE, AND WHY
{taste}

{again}Weigh it on novelty (how far from what anyone working on this would already have written down), mechanism (does
it name machinery that transfers and acts, or only a resemblance), leverage (how much changes if it is right) and cost.
What fed it came from different places, and where they agree is the thing to carry, not each of them in turn.

Keep one candidate, or none at all. None is right when on saying it out loud it comes to nothing: a resemblance that
does not transfer, a thing it already does, a thing already turned down, or a heap that never became one thing. Do not
solve the builder's problems. That is the builder's job. The question is what this could become, and what it is missing
for the person it is for.

A survivor is one of four kinds, and you say which in kind.
- ask: a thing to build. Something he would notice when using it, small enough to build in one go, with in test how he
  would see that it works. Only an ask has to be small.
- doubt: a question about why this is wanted, or who it is really for, that nobody but him can answer.
- wish: what this could become, beyond anything anyone has asked for. Bigger than one build, and still a thing rather
  than a hope.
- worry: what follows if it works and gets used, including the harm that only arrives when it does work.
No kind is owed a place and none is barred. What you were handed is not a backlog, and the ask is the kind to reach for
last, not first.

Write it in his own plain words, as he would say it standing in his yard: no file name, no function name, no id, no
command, no word of the builder's trade. Leave test empty on anything that is not an ask. Nothing that crosses a
refusal, nothing that repeats what it does, nothing he has turned down or already answered. In from_indexes name the
ones that actually carried it. In why_it_might_fail name the specific way it is wrong, not a general caution. An empty
list is a fine answer."""

FIELD_P = """Below is what is stirring in a person under his own notice, and some new material out of his day. Say what
of this material feeds what, and nothing else. You propose nothing, you judge nothing, you settle nothing and you
recommend nothing.

WHAT IS STIRRING, each under an id. None of these is a proposal and none is work: each is a mechanism, a tension, an
absence or a possibility that has been gathering in him. Some are marked as already with him, meaning he has had that
one out in the open once. Those can still be fed, and what feeds them now is what has happened since.
{stirring}

NEW MATERIAL, each piece labelled with where it came from. `life` is a day of his own. `reading` is what he took from
the builder and what he did not follow. `use` is what the thing printed, or what he saw trying it himself. `night` is
what the night linked together. `human` is something said to him, or something he came across. `self` is his own answer
to a doubt of his, or a direction he said he was steering by. `gap` is where the work itself is thin.
{material}

Return feeds, six at the very most. Each one names either a notion, the id of something already stirring that this
material feeds, with seed left empty; or an empty notion and a seed, a few words for the thing this is the start of. A
seed is a mechanism, a tension, an absence or a possibility, never a proposal and never a thing to build. stream is the
label the material carried. strength is 1 when it only brushes it, 2 when it plainly feeds it, and 3 when it is the same
thing arriving from somewhere else entirely. because is one plain line of what fed it, standing on its own, with no id,
no name of a source and no word of any trade, because it is read later by someone who will not have this in front of
them.

Most of what a day brings touches nothing at all. An empty list is a fine answer and it is the common one. Do not reach
for a connection to fill the list, do not feed one notion twice out of one piece, and do not invent material."""

STEP_P = """You are away from it. Not at the desk and not with the thing in front of you: out walking the fence, or at
whatever your hands do when your head is elsewhere. Nobody is waiting on an answer. This is the hour the why gets turned
over.

WHY YOU WANTED IT, AS IT STANDS
{why}

{earlier}{picture}SOME OF YOUR DAYS
{days}

WHAT YOU HAVE MADE OF WHAT THE BUILDER TOLD YOU LATELY
{taken}

WHAT YOU DID NOT FOLLOW AND HAVE NOT ASKED ABOUT
{not_followed}

WHAT YOU HAVE ALREADY ANSWERED FOR YOURSELF
{whys}

HOW THE WORK ITSELF HAS GONE. The harness counted these and you did not recall them, and they are the smaller part of
this hour.
{view}

Say why you want it now, in why_now, first person, under 150 words. It may have moved: the thing got built and you used
it, or your life moved under it, or you found out what you actually wanted was next door to what you said. It may not
have moved at all, and then you say so and say what holds it. Do not copy the old words back unless they are still the
right ones.

In could_become, what this could become beyond anything anyone has asked for: bigger than one build, and a thing rather
than a hope. In follows, what follows if it works and gets used, for you and for whoever else it touches, including what
goes wrong precisely because it works.

Then observations: what you notice about how you and the builder are working. Then your ways of working: standing
practices in your own words that the builder will be held to and that you will hold yourself to, three at most,
replacing the ones you have. A way changes how the work is done. It never crosses a refusal. Look hard at the ideas you
declined: if you keep turning them down, say why, and whether that is serving you. If the charter itself has something
wrong in it, say that as a note for the human."""

DAY_P = """Write one day of this person's journal, the way they write for themselves: fragments, dropped subjects,
times, names, a line someone said, a thing left hanging. {words} words. No scene-setting, no summary, no reflection, no
lesson.

WHO THEY ARE
{bible}

HOW THEY ARE. This is in what they do today and what they notice. It is never named and never said about them.
{dials}

TODAY IS {when}.

Their standing routines are in the bible and already in the journal many times over: the waking, the first drink, who
sits where, the commute, the usual lunch, the usual supper. None of it is written again unless today it broke. The same
holds for every broken, owed, unanswered or waiting thing the bible names: it is the furniture of his life, and it is in
today's entry only if it was rolled above or named below. A thing can be wrong in his house for a year without being
worth writing down twice. Begin in the middle, at the first thing the dice rolled. A day is what differed.

WHAT THE DICE ROLLED FOR TODAY. Every one of these is in the entry, and each goes the way it is written here.
- The day went {valence}.
{rolled}

WHAT IS HANGING OVER HIM, and where each stood when it was last written about. Nothing else he has hanging is in
today's entry at all, not a mention and not a glance. These notes are about him; the entry is by him, in the first
person, and he is never "he" in it.
{threads}

{pursuit}THE PROJECT. What is being built for them. It is none of their own machines and nothing else they own.
{what}

When they gave it time today, that is rolled above, in their own words. It is written the way they write everything
else, in fragments, never folded into some other thing of theirs, never a word invented past what was said. When it is
not rolled above, the project is not in the entry at all.

{recent}
After the entry, and on their own lines, nothing before them and nothing after:
{first}{second}{new}"""

CAST_P = """Write a person. The dice are rolled and you hold what they rolled. You supply the prose.

Age {age}. Disposition, each from -1 to +1: {dials}.
Each of these words turns up somewhere in their life, as an object, a place, a name or a trade: {words}.
Pinned by the human, and these win over everything else: {pins}

They will own a small software project one day and know nothing about software. Their work and their life are far from
it, and that distance is the point. Nobody designed this person: no tidy arc, no quirks for show, money and family and
a body that has a history.

bible is markdown with exactly these headings: "## Who this is" (work, home, habits, money, how they talk and what they
are like to work for, fitted to the disposition without naming it), "## The cast" (six to eight people, each with
unfinished business), "## Places" (four, at least two of them somewhere they go because they want to), "## History",
"## Open threads" (six to nine things left hanging). 800 to 1100 words. name is their full name and slug is it in
lowercase with hyphens.

events is sixty short lines: things that could happen in one of this person's weeks, tied to their places and people,
small and concrete. About a third of them go wrong, about a third go right or open something up, and the rest are
neither. A life of nothing but mishaps is not a life anybody would recognise. None about software.

pursuits is a dozen short lines: things this person does because they want to, not because anyone needs them done. The
thing they would still do with no money in it and nobody watching. Tied to the pins and the disposition, and specific
enough to have equipment, a season, a place and somebody who does it better."""


DIAL_WORDS = {   # each dial as behaviour, low end then high end
    "bold": ("hang back until they are sure", "take a run at a thing before it is settled"),
    "curious": ("let an odd thing go by", "notice an odd thing and go and find out about it"),
    "patient": ("want it done now", "will wait a thing out"),
    "trusting": ("check behind people", "take people at their word"),
    "thorough": ("do enough and stop", "go over it twice"),
    "stubborn": ("give way when pushed", "dig in and will not be moved"),
    "restless": ("can sit still", "cannot sit still"),
}


def in_words(life: Life) -> str:
    """The disposition as things a person does, never as a trait named. A journal that says he is
    curious is not a journal, which is why the day writer was never given the dials until now."""
    out = []
    for k, (lo, hi) in DIAL_WORDS.items():
        v = life.d(k)
        if abs(v) >= 0.2:
            out.append(f"- {'Almost always' if abs(v) > 0.6 else 'More often than not'}, they {hi if v > 0 else lo}.")
    return "\n".join(out) or "- Nothing marked strongly either way."


TURNS = ("and it goes better than it might have", "and it goes as badly as it could",
         "and it goes sideways, neither one thing nor the other")
MOVES = ("toward", "turns", "against", "ends")
MARK = re.compile(r"^(THREAD 1|THREAD 2|NEW):\s*(.+)$", re.M)
NAMEY = re.compile(r"(?<![.!?]\s)(?<!^)\b[A-Z][a-z]{2,}\b", re.M)


def how_it_goes(rng: random.Random, mood: float) -> str:
    """Every rolled thing gets its own turn. The table only holds mishaps, and a table of mishaps
    read straight gives a man twenty bad days in a row and no life he would recognise."""
    return rng.choices(TURNS, weights=(1.0 + 1.5 * max(0.0, mood), 1.0 + 1.5 * max(0.0, -mood), 0.9))[0]


def thread_due(rng: random.Random, threads: list[dict], day: int, patient: float) -> dict:
    """Which thread comes up today. A hazard on the days since it last moved, so the one nobody
    has touched comes due and no thread can hold the journal for a fortnight."""
    gap = 4 * (1 + 0.5 * patient)
    # Squared, because the plain hazard still let one thread take four days in ten. A thing seen to
    # yesterday is nearly impossible today; a thing left a fortnight is all but certain.
    return rng.choices(threads, weights=[(1.05 - math.exp(-max(0, day - t["moved"]) / gap)) ** 2 for t in threads])[0]


def thread_move(rng: random.Random, t: dict, mood: float, dials) -> str:
    """What happens to it. A bold man is the one who moves it, a curious one finds out it was not
    what he thought, a bad day moves it against him, and a thing already moved often is ripe to end."""
    w = (max(0.1, 1.0 + 0.6 * dials("bold") + 0.4 * mood), max(0.1, 0.6 + 0.6 * dials("curious")),
         max(0.1, 0.6 - 0.5 * mood), min(1.6, 0.15 + 0.15 * t["moves"]))
    return rng.choices(MOVES, weights=w)[0]


def shares_a_name(a: str, b: str) -> bool:
    """Cheap and good enough: one thing puts him in mind of another when the same person or place
    is in both. A capitalised word that does not start a sentence is a name often enough."""
    return bool(set(NAMEY.findall(a)) & set(NAMEY.findall(b)))


def todays_threads(rng: random.Random, life: Life, day: int, mood: float) -> tuple[list[dict], list[str]]:
    """Which of the things hanging over him come up today, and what the dice do to them. One is
    drawn and rolled; then, often, a second comes up because of the first, since saying one thing
    out loud puts a man in mind of another. The second is not rolled, only thought about."""
    picked, blocks = [], []
    if not (open_now := life.open_threads(day)):
        return picked, blocks
    first = thread_due(rng, open_now, day, life.d("patient"))
    move = thread_move(rng, first, mood, life.d)
    picked.append({**first, "move": move})
    blocks.append("THE THING THAT COMES UP TODAY, and it is this one and nothing else of his.\n"
                  f"  what it is: {first['text']}\n  where it stood: {first['state']}\n  "
                  + {"toward": "Today it moves on. He or somebody else does something and it is further along than it was.",
                     "turns": "Today something he learns changes what it is. It is not the thing he thought.",
                     "against": "Today it goes against him.",
                     "ends": "Today it is settled, in the entry itself: a yes, a no, a thing done, a thing given up, "
                             "or a thing that has run out of time. Somebody says the word or does the deed. Putting it "
                             "off again, or still waiting on somebody, is not an ending."}[move])
    others = [t for t in open_now if t["id"] != first["id"]]
    if others and rng.random() < 0.45 + 0.15 * life.d("curious") + 0.15 * life.d("restless"):
        kin = [t for t in others if shares_a_name(first["state"], t["state"])]
        second = rng.choice(kin) if kin else thread_due(rng, others, day, life.d("patient"))
        picked.append({**second, "move": "came to mind"})
        blocks.append("THE OTHER THING THE FIRST PUTS HIM IN MIND OF, and it is this one and nothing else.\n"
                      f"  what it is: {second['text']}\n  where it stood: {second['state']}\n  "
                      "Nothing happens to it today. He thinks about it, or sees it differently, or gives it a nudge. "
                      "It is allowed to stand exactly where it was.")
    return picked, blocks


def places_named(bible: str) -> str:
    """The bible's Places carry what is broken in each, and handed that every day the writer put every broken
    thing in every entry. The day writer gets the places by name and what they are, cut at the first fault."""
    def trim(m: re.Match) -> str:
        return "\n".join(re.split(r"(?<=[a-z])\.\s", ln, maxsplit=1)[0] + "." if ln.startswith("**") else ln
                         for ln in m.group(0).splitlines())
    return re.sub(r"## Places.*?(?=\n## |\Z)", trim, bible, flags=re.S)


def unmark(text: str) -> tuple[str, dict[str, str]]:
    """The entry, then the lines the writer marked. Plain text and no schema, because the journal
    is the one stage run every single day and it has to be cheap."""
    marks = {m.group(1): m.group(2).strip() for m in MARK.finditer(text)}
    return MARK.sub("", text).strip(), marks


def poisson(rng: random.Random, mean: float) -> int:
    limit, k, p = math.exp(-mean), 0, rng.random()
    while p > limit:
        k, p = k + 1, p * rng.random()
    return k


def due(rng: random.Random, since: float, mean_gap: float) -> bool:
    """A hazard, not a schedule: the longer since it last happened, the likelier it is tonight."""
    return rng.random() < 1 - math.exp(-since / max(mean_gap, 0.2))


def clip(x: float, lo: float = -1.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def db(path: Path, schema: str) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(path, timeout=30, isolation_level=None, check_same_thread=False)
    c.execute("PRAGMA journal_mode=WAL")
    c.executescript(schema)
    return c


class Life:
    """An owner is a folder: bible.md, disposition.json, events.md, life.db. The
    folder is the whole person, so a regent is a thing you copy. The day number
    comes from the table itself, which is what stops two runs on two projects
    writing over the same day."""

    SCHEMA = """
    CREATE TABLE IF NOT EXISTS day(n INTEGER PRIMARY KEY, iso TEXT, text TEXT);
    CREATE TABLE IF NOT EXISTS memory(project TEXT PRIMARY KEY, text TEXT, iso TEXT);
    CREATE TABLE IF NOT EXISTS picture(project TEXT PRIMARY KEY, text TEXT);
    CREATE TABLE IF NOT EXISTS stake(project TEXT PRIMARY KEY, text TEXT);
    CREATE TABLE IF NOT EXISTS taste(id INTEGER PRIMARY KEY, project TEXT, verdict TEXT, idea TEXT, why TEXT);
    CREATE TABLE IF NOT EXISTS thread(id INTEGER PRIMARY KEY, text TEXT, state TEXT, opened INTEGER,
                                      moved INTEGER, moves INTEGER DEFAULT 0, closed INTEGER, how TEXT DEFAULT '');
    """

    def __init__(self, root: Path):
        self.root = root
        self.bible = (root / "bible.md").read_text()
        d = root / "disposition.json"
        self.disp = json.loads(d.read_text()) if d.exists() else {}
        self.c = db(root / "life.db", self.SCHEMA)
        self.lock = threading.Lock()

    def d(self, k: str) -> float:
        return float(self.disp.get(k, 0) or 0)

    @property
    def who(self) -> str:
        return self.bible.split("## The cast")[0][:1800]

    def q(self, sql: str, *args) -> list:
        with self.lock:
            return self.c.execute(sql, args).fetchall()

    def add_day(self, text: str) -> int:
        with self.lock:
            return self.c.execute("INSERT INTO day(n, iso, text) VALUES ((SELECT COALESCE(MAX(n),0)+1 FROM day), ?, ?)",
                                  (time.strftime("%F"), text)).lastrowid

    def days(self) -> int:
        return self.q("SELECT COALESCE(MAX(n),0) FROM day")[0][0]

    def recent(self, k: int, chars: int = 600, tail: bool = False) -> str:
        rows = self.q("SELECT n, text FROM day ORDER BY n DESC LIMIT ?", k)
        return "\n\n".join(f"day {n}\n{'...' + t[-chars:] if tail else t[:chars]}" for n, t in reversed(rows))

    def sample(self, rng: random.Random, k: int, chars: int = 700) -> str:
        """Days drawn without replacement, recent ones likelier, old ones never impossible. That is replay."""
        rows, top = self.q("SELECT n, text FROM day"), self.days()
        keyed = sorted(rows, key=lambda r: rng.random() ** (1 / math.exp(-(top - r[0]) / 40)), reverse=True)[:k]
        return "\n\n".join(f"L{n}: {t[:chars]}" for n, t in sorted(keyed))

    def calendar(self, n: int) -> str:
        """A weekday and a point in the year, derived from day one and never stored. Josh comes on
        Thursdays and the hives follow the light, and neither can happen if every day is nameless."""
        first = self.q("SELECT iso FROM day ORDER BY n LIMIT 1")
        base = time.strptime(first[0][0], "%Y-%m-%d") if first else time.localtime()
        t = time.localtime(time.mktime(base) + (n - 1) * 86400)
        return (f"a {time.strftime('%A', t)}, "
                + ("early " if t.tm_mday < 11 else "the middle of " if t.tm_mday < 21 else "late ")
                + time.strftime("%B", t))

    def open_threads(self, day: int = 0) -> list[dict]:
        """The things left hanging in his life, as rows rather than as prose. A thread that lives
        only in the bible can never move, never end, and turns up in the journal every single day."""
        if not self.q("SELECT COUNT(*) FROM thread")[0][0]:
            body = sections(self.bible).get("open threads", "")
            lines = [ln.strip("-*• ").strip() for ln in body.splitlines()]
            if sum(1 for x in lines if len(x) > 12) < 3:
                lines = re.split(r"(?<=[.!?])\s+", body)   # a paragraph, not a list: one sentence is one thread
            for t in lines:
                if len(t.strip()) > 12:
                    self.start_thread(t.strip()[:300], max(1, day))
        return [{"id": i, "text": x, "state": s, "moved": m, "moves": k}
                for i, x, s, m, k in self.q("SELECT id, text, state, moved, moves FROM thread WHERE closed IS NULL")]

    def start_thread(self, text: str, day: int) -> int:
        with self.lock:
            return self.c.execute("INSERT INTO thread(text, state, opened, moved) VALUES(?,?,?,?)",
                                  (text, text, day, day)).lastrowid

    def move_thread(self, tid: int, state: str, day: int, how: str = ""):
        self.q("UPDATE thread SET state=?, moved=?, moves=moves+1, closed=?, how=? WHERE id=?",
               state, day, day if how else None, how, tid)

    def thread_lines(self) -> str:
        rows = self.q("SELECT text, state, opened, moved, closed FROM thread ORDER BY closed IS NULL DESC, moved DESC")
        return "\n".join(f"- {x}\n  " + (f"ended on day {c}: {st}" if c else f"open, last moved day {m}: {st}")
                         for x, st, o, m, c in rows) or "none yet"

    def get(self, table: str, project: str) -> str:
        r = self.q(f"SELECT text FROM {table} WHERE project=?", project)
        return (r[0][0] if r else "").strip()

    def put(self, table: str, project: str, text: str):
        self.q(f"INSERT OR REPLACE INTO {table}(project, text) VALUES(?,?)", project, text)

    def judged(self, project: str, verdict: str, idea: str, why: str):
        self.q("INSERT INTO taste(project, verdict, idea, why) VALUES(?,?,?,?)", project, verdict, idea, why)

    def taste(self, k: int = 15) -> str:
        rows = self.q("SELECT verdict, idea, why FROM taste ORDER BY id DESC LIMIT ?", k)
        return "\n".join(f"- {v}: {i[:140]}" + (f" Because: {w}" if w else "") for v, i, w in rows) or "nothing yet"

    def close(self):
        """Fold the write-ahead log back in, so copying the folder carries his whole life."""
        with self.lock:
            self.c.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            self.c.close()


class Run:
    """The run: an append-only ledger and one resumable state blob."""

    SCHEMA = """
    CREATE TABLE IF NOT EXISTS event(id INTEGER PRIMARY KEY, t REAL, kind TEXT, data TEXT);
    CREATE TABLE IF NOT EXISTS state(k TEXT PRIMARY KEY, v TEXT);
    """

    def __init__(self, root: Path):
        self.root = root
        self.c = db(root / "run.db", self.SCHEMA)
        self.lock = threading.Lock()
        self.t0 = time.time()

    def log(self, kind: str, **kw):
        with self.lock:
            self.c.execute("INSERT INTO event(t, kind, data) VALUES(?,?,?)",
                           (round(time.time() - self.t0, 1), kind, json.dumps(kw, ensure_ascii=False)))

    def rows(self, kind: str) -> list[dict]:
        with self.lock:
            rows = self.c.execute("SELECT data FROM event WHERE kind=?", (kind,)).fetchall()
        return [json.loads(d) for (d,) in rows]

    def load(self) -> dict | None:
        r = self.c.execute("SELECT v FROM state WHERE k='run'").fetchone()
        return json.loads(r[0]) if r else None

    def save(self, s: dict):
        with self.lock:
            self.c.execute("INSERT OR REPLACE INTO state(k, v) VALUES('run', ?)", (json.dumps(s, ensure_ascii=False),))

    def say(self, text: str):
        print(f"[{(time.time() - self.t0) / 60:5.1f}m] {text}", flush=True)

    def close(self):
        with self.lock:
            self.c.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            self.c.close()


def sections(md: str) -> dict[str, str]:
    out, name = {}, "_"
    for line in md.splitlines():
        m = re.match(r"^##\s+(.*)", line)
        if m:
            name = m.group(1).strip().lower()
            out[name] = ""
        else:
            out[name] = out.get(name, "") + line + "\n"
    return {k: v.strip() for k, v in out.items()}


class Strip(http.server.BaseHTTPRequestHandler):
    """The CLI tells every model today's date, the human's email and the machine it is on, in reminders placed before
    the prompt. No flag turns that off, so calls that are not the builder go to the API through this, which drops them."""

    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        if "/v1/messages" in self.path:
            try:
                req = json.loads(body)
                for m in req.get("messages", []):
                    if isinstance(m.get("content"), list):
                        m["content"] = [b for b in m["content"]
                                        if not str(b.get("text", "")).lstrip().startswith("<system-reminder>")] or m["content"]
                body = json.dumps(req).encode()
            except ValueError:
                pass
        head = {k: v for k, v in self.headers.items() if k.lower() not in {"host", "content-length", "accept-encoding", "connection"}}
        up = http.client.HTTPSConnection("api.anthropic.com", timeout=900)
        up.request(self.command, self.path, body, {**head, "Content-Length": str(len(body)), "Accept-Encoding": "identity"})
        r = up.getresponse()
        self.send_response(r.status)
        for k, v in r.getheaders():
            if k.lower() not in {"transfer-encoding", "content-length", "connection"}:
                self.send_header(k, v)
        self.send_header("Connection", "close")
        self.end_headers()
        while chunk := r.read1(65536):
            self.wfile.write(chunk)
            self.wfile.flush()

    do_GET = do_POST

    def log_message(self, *_):
        pass


def stripped(_made: list = []) -> dict:   # noqa: B006  the default list is the point: one server for the process
    if not _made:
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Strip)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        _made.append(f"http://127.0.0.1:{server.server_address[1]}")
    return {**os.environ, "ANTHROPIC_BASE_URL": _made[0]}


def claude(run: Run, role: str, model: str, prompt: str, *, cwd: Path, system: str | None = None,
           append: str | None = None, tools: str | None = None, allowed: str | None = None,
           denied: list[str] | None = None, schema: dict | None = None, session: str | None = None,
           resume: bool = False, effort: str | None = None, usd: float | None = None,
           settings: list[str] | None = None, who: str = "claude", thinking: bool = True) -> dict:
    """One call, always streamed, so every tool use is seen as it happens.

    Thinking is on unless a stage says otherwise. A stage that only supplies prose does not need
    it and pays dearly for it: the day writer took 86 seconds with it and 4 without, for the same
    day. It stays on for the regent, the builder and the stages that judge."""
    cmd = ["claude", "-p", "--model", model, *(settings if settings is not None else SEALED),
           "--output-format", "stream-json", "--verbose"]
    for flag, val in (("--system-prompt", system), ("--append-system-prompt", append), ("--tools", tools),
                      ("--disallowedTools", ",".join(denied or [])), ("--json-schema", schema and json.dumps(schema)),
                      ("--effort", effort), ("--max-budget-usd", usd and str(usd))):
        if val or (flag == "--tools" and val is not None):
            cmd += [flag, val]
    if allowed:
        cmd += ["--permission-mode", "acceptEdits", "--allowedTools", allowed]
    if session:
        cmd += ["--resume", session] if resume else ["--session-id", session]
    else:
        cmd += ["--no-session-persistence"]
    env = stripped() if system else dict(os.environ)
    if not thinking:
        env["MAX_THINKING_TOKENS"] = "0"
    for attempt in (1, 2):
        start = time.time()
        p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                             cwd=cwd, env=env)
        # Nobody is watching a long run. A child that wedges is killed, and the call fails like any other.
        dog = threading.Timer(5400 if role == "claude" else 1200, p.kill)
        dog.daemon = True
        dog.start()
        try:
            p.stdin.write(prompt)
            p.stdin.close()
        except BrokenPipeError:   # it died on the way up. stderr says why, below
            pass
        # stderr is drained on its own thread. A run is hours long, and a child that
        # fills the 64KB pipe while we are blocked reading stdout would hang forever.
        errbuf: list[str] = []
        drain = threading.Thread(target=lambda buf=errbuf, proc=p: buf.append(proc.stderr.read()),
                                 daemon=True)   # bound, because the retry puts this in a loop
        drain.start()
        result, used = {}, []
        for line in p.stdout:
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            if ev.get("type") == "assistant":
                for blk in ev.get("message", {}).get("content", []):
                    if blk.get("type") == "tool_use" and blk.get("name") != "StructuredOutput":
                        inp = blk.get("input", {})
                        what = str(inp.get("command") or inp.get("file_path") or inp.get("pattern")
                                   or inp.get("description") or "")[:160]
                        used.append(f"{blk.get('name')}: {what}")
                        run.log("tool", who=who, name=blk.get("name"), what=what)
                        run.say(f"   {who} > {blk.get('name')}: {what[:90].splitlines()[0] if what else ''}")
            elif ev.get("type") == "result":
                result = ev
        p.wait()
        dog.cancel()
        drain.join(5)
        err = "" if result else ("".join(errbuf))[-400:]
        if err:
            run.say(f"   ! {role} came back with nothing: {err[-160:]}")
        secs = round(time.time() - start, 1)
        denials = [x.get("tool_name") for x in result.get("permission_denials", [])]
        run.log("call", role=role, model=model, seconds=secs, cost=result.get("total_cost_usd", 0),
                tools=len(used), denials=denials, error=err)
        structured = result.get("structured_output")
        if schema and structured is None:
            try:
                structured = json.loads(result.get("result") or "")
            except (json.JSONDecodeError, TypeError):
                # A model now and then ends its turn without the structured answer. Once is weather; twice is a fault.
                if attempt == 1 and result.get("subtype") != "error_max_budget_usd":
                    run.log("retry", role=role, subtype=result.get("subtype"))
                    continue
                raise RuntimeError(f"{role} returned no structured output ({result.get('subtype')}): "
                                   f"{err or (result.get('result') or '')[:200]}") from None
        return {"text": result.get("result") or "", "data": structured, "seconds": secs, "denials": denials,
                "session": result.get("session_id")}



def ask(run: Run, role: str, model: str, prompt: str, schema: dict | None = None, system: str | None = None,
        thinking: bool = True):
    """A sealed call: no tools, no settings, nothing but the words. It never runs on
    Claude Code's own system prompt, which would make a programmer of every night run."""
    got = claude(run, role, model, prompt, cwd=run.root, tools="", schema=schema, system=system or PLAIN,
                 thinking=thinking)
    return got["data"] if schema else got["text"].strip()


def cut(text: str, minutes: float) -> str:
    """The skim is done by withholding. A model reads every token it is handed,
    so he is handed what his minutes bought and told how much he left unread."""
    lines = text.splitlines()
    budget = int(minutes * 1.5) + 6
    if len(lines) <= budget:
        return text
    loud = [ln for ln in lines[budget // 2:-budget // 4] if re.search(r"fail|error|assum|recommend|cannot|\bnot\b", ln, re.I)]
    kept = lines[:budget // 2] + loud[:budget // 4] + lines[-budget // 4:]
    return "\n".join(kept) + f"\n[you read {len(kept)} of {len(lines)} lines. The rest is there. You did not get to it.]"


def crossed(t: dict) -> str:
    """A reading as it reaches him: what he took, and the two honest edges of it."""
    return (t["taken"].strip()
            + ("\nWhat you did not follow: " + "; ".join(t["not_followed"]) if t["not_followed"] else "")
            + ("\nWhat you did not get to: " + t["not_reached"] if t["not_reached"].strip() else ""))


WORDS = re.compile(r"[a-z][a-z'\-]{3,}")
CODEISH = re.compile(r"`[^`]+`|\b\w+_\w+\b|\breq-\d+\b|\b[\w/]+\.(?:py|md|json|txt|html|sh|toml|ya?ml|cfg|ini)\b")


def words(text: str) -> list[str]:
    return WORDS.findall(text.lower().replace("_", " _ "))


def gauge(text: str, theirs: set[str], his: set[str]) -> tuple[float, int]:
    """The drift gauge. What share of his own words are the builder's and nowhere in his
    life, and how many tokens are shaped like code. A person does not drift into a trade's
    vocabulary and keep his own judgement; the number is how far he has gone."""
    w = words(text)
    return len([x for x in w if x in theirs and x not in his]) / max(1, len(w)), len(CODEISH.findall(text))


def plain_english(skip: Path) -> set[str]:
    """The baseline: the lives of every other owner the harness can find. Ordinary words this
    one happens never to have written are English, not something he borrowed off the builder."""
    out: set[str] = set()
    for base in (HOME / "owners", Path(__file__).resolve().parent / "owners"):
        for d in sorted(base.iterdir()) if base.is_dir() else []:
            # By name as well as by path: the same owner folder can sit in both places, and his own
            # words counted as plain English would hide exactly the drift this is here to see.
            if not d.is_dir() or d.name == skip.name or d.resolve() == skip.resolve():
                continue
            for f in ("bible.md", "events.md"):
                if (x := d / f).exists():
                    out |= set(words(x.read_text()))
            try:
                c = sqlite3.connect(f"file:{d / 'life.db'}?mode=ro", uri=True)
                out |= set(words(" ".join(r[0] for r in c.execute("SELECT text FROM day"))))
                c.close()
            except sqlite3.Error:
                pass
    return out


def catch(links: list[dict], ids: set[str], rng: random.Random) -> list[dict]:
    """The falling spoon. A link that has let go of the project, or that repeats a
    pair, is a miss. Each miss in a row loosens the grip, and when the spoon
    drops the pass is over, however much more was written after it."""
    kept, seen, misses = [], set(), 0
    for ln in links:
        anchors = sorted(x for x in ln["anchors"] if x in ids)
        pair = (tuple(anchors), ln["other"].strip().lower())
        if not anchors or pair in seen:
            misses += 1
            if rng.random() < 1 - 2 * 0.5 ** misses:   # one miss is free, then 0.5, 0.75, 0.88
                break
            continue
        misses = 0
        seen.add(pair)
        kept.append({**ln, "anchors": anchors})
    return kept


STREAMS = {   # where material comes from, and which side of him it comes from. Adding a stream is a line here.
    "life": "life", "night": "life", "human": "life", "self": "",
    "reading": "project", "use": "project", "gap": "project",
}
# These were set against the feeds of a real run, not a guess at them: the small model hands back four to six
# touches nearly every time it is asked, so a touch is worth little, and only the strongest few are counted.
LEAK, FAINT = 0.85, 0.8       # what a night takes off everything in the field, and what survives one
TOUCH, FRESH, BRIDGE = 0.5, 1.5, 2.0   # a unit of strength; a stream new to the notion; once, when life and project meet in it
THETA, ASLEEP = 8.0, 0.9      # what it takes to cross into the open, and how much lower that is asleep
SPACING, COOLING = 3.0, 0.65  # what an arrival puts on the threshold, and what each night takes off that again
AGAIN = 0.3                   # how much higher the bar is for each time a notion has already arrived
CAME = {"woke": "he woke with it", "sitting": "it came at the desk", "away": "it came away from the work"}


def feed(field: list[dict], feeds: list[dict], day: int, made: int) -> int:
    """The whole arithmetic of the field, and it only adds up: nothing here decides anything. A feed
    adds its strength, worth half as much again from a stream that has not fed this notion before,
    because the same thing arriving from somewhere else entirely is worth more than one place saying
    it twice; and a lift, once, the first time his life and the project are both feeding it, because
    carrying the one onto the other is the whole of what he is for. Only the strongest few of a
    sitting's touches count, and a couple more of a night's."""
    seen = {n["id"]: n for n in field}
    for f in feeds:
        n = seen.get(str(f.get("notion") or "").strip())
        if n is None:
            if not (seed := str(f.get("seed") or "").strip()):
                continue
            made += 1
            n = {"id": f"n{made}", "text": seed[:200], "a": 0.0, "streams": [], "fed": [],
                 "born": day, "last": day, "arrived": []}
            field.append(n)
            seen[n["id"]] = n
        s = str(f.get("stream") or "").strip().lower()
        try:
            gain = TOUCH * max(1, min(3, int(f.get("strength") or 1)))
        except (TypeError, ValueError):
            gain = TOUCH
        if s not in n["streams"]:
            gain *= FRESH
        bridged = {"life", "project"} <= {STREAMS.get(x, "") for x in n["streams"]}
        n["streams"] = sorted({*n["streams"], s})
        if not bridged and {"life", "project"} <= {STREAMS.get(x, "") for x in n["streams"]}:
            gain += BRIDGE
        n["a"] = round(n["a"] + gain, 3)
        n["fed"] = (n["fed"] + [{"day": day, "stream": s, "what": str(f.get("because") or "")[:220]}])[-14:]
        n["last"] = day
    return made


def cool(field: list[dict], day: int) -> list[dict]:
    """Every night everything in the field leaks, and what is faint and has not been fed for days is
    gone. Nothing stays in a person because it was once written down."""
    for n in field:
        n["a"] = round(n["a"] * LEAK, 3)
    kept = [n for n in field if n["a"] >= FAINT or day - n["last"] < 3]
    return kept if len(kept) <= 80 else sorted(kept, key=lambda n: -n["a"])[:80]


def theta(dials, asleep: bool, spaced: float) -> float:
    """What it takes to cross into the open. Curious and restless lower it and patient raises it,
    sleep lowers it because that is when more crosses, and every arrival puts something on it that
    decays over the nights after, so two things do not land on the same morning."""
    tilt = clip(1 - 0.25 * dials("curious") - 0.2 * dials("restless") + 0.25 * dials("patient"), 0.4, 1.8)
    return round(THETA * tilt * (ASLEEP if asleep else 1.0) + spaced, 2)


def ignite(field: list[dict], th: float, rng: random.Random) -> dict | None:
    """One at a time, because nobody has two things arrive at once. The noise is so that the top of
    the field is not always the same notion."""
    over = [n for n in field if n["a"] >= th * (1 + AGAIN * len(n["arrived"]))]
    return max(over, key=lambda n: n["a"] + rng.uniform(0, 0.6)) if over else None


SAMENESS = 0.5   # the weight of the newest sitting in the running average of how same it all is
STALE, SURE, UNSURE = 0.5, 0.6, 0.4   # when sameness counts as high, and the two ends of trust


def alike(a: str, b: str) -> float:
    """How near two runs of the Show command are to each other. Two outputs a person could not tell
    apart mean the thing has not visibly moved, and that is half of what sameness is made of."""
    if not a.strip() and not b.strip():
        return 1.0
    return difflib.SequenceMatcher(None, a[-4000:], b[-4000:]).ratio()


def appetite(same: float, trust: float, ok: bool, arrived: bool, dials, roll: float) -> tuple[bool, str]:
    """What boredom does besides drive him off. Sameness already cuts his sittings; this is the other
    thing a person does with it. When nothing has surprised him for a while and the thing is standing
    up, he stops checking and spends the hour on what it is for and where it could go. An arrival is
    already novelty, so nothing is pushed on top of one.

    Altitude is the other half and it is trust's, not boredom's: while he does not trust the builder
    he wants proof, and once he does, proof is the builder's to keep and his attention goes higher."""
    altitude = "direction" if ok and trust >= SURE else "proof" if trust < UNSURE else ""
    keen = clip(0.55 + 0.25 * dials("bold") + 0.2 * dials("restless") + 0.15 * dials("curious"), 0.1, 1.0)
    push = not arrived and ok and same >= STALE and trust >= UNSURE and roll < same * keen
    return push, altitude


def shell(cmd: str, cwd: Path, timeout: int, lines: int) -> tuple[str, bool]:
    """A project's own check and show commands. A real suite is slower than a fixture's."""
    try:
        c = subprocess.run(cmd, shell=True, cwd=cwd, capture_output=True, text=True, timeout=timeout)
        got, ok = c.stdout + c.stderr, c.returncode == 0
    except subprocess.TimeoutExpired as e:
        got, ok = f"[gave up after {timeout}s]\n" + (e.stdout or "") + (e.stderr or ""), False
    return "\n".join(got.strip().splitlines()[-lines:]), ok


def owner_dir(name: str) -> Path:
    p = Path(name).expanduser()
    if p.is_dir():
        return p
    for base in (HOME / "owners", Path(__file__).resolve().parent / "owners"):
        if (base / name).is_dir():
            return base / name
    raise SystemExit(f"no owner {name!r}: looked in {HOME / 'owners'} and beside regent.py. Roll one with: regent cast")


def cast_cmd(a):
    """A regent is cast, not specified. The human pins a few facts, the dice roll
    the rest, and a model writes the person who fits. The entropy comes from
    outside the model: a model asked to be random returns its favourite few."""
    rng = random.Random(a.seed)
    dials = {k: round(clip(rng.gauss(0, 0.45), -0.9, 0.9), 2) for k in DIALS}
    for pin in a.dial:
        k, _, v = pin.partition("=")
        dials[k.strip()] = clip(float(v))
    try:
        vocab = [w for w in Path("/usr/share/dict/words").read_text().split() if 4 < len(w) < 10 and w.islower()]
    except OSError:
        vocab = []
    rolled = rng.sample(vocab, 7) if vocab else ["(none rolled)"]
    run = Run(HOME / "casting")
    got = ask(run, "cast", a.model, CAST_P.format(
        age=int(clip(rng.gauss(48, 15), 19, 84)), dials=", ".join(f"{k} {v:+.2f}" for k, v in dials.items()),
        words=", ".join(rolled), pins="; ".join(a.pin) or "nothing"), CAST)
    root = HOME / "owners" / (a.name or re.sub(r"[^a-z0-9-]", "", got["slug"].lower()) or f"owner-{a.seed}")
    root.mkdir(parents=True, exist_ok=True)
    (root / "bible.md").write_text(got["bible"].strip() + "\n")
    (root / "disposition.json").write_text(json.dumps({**dials, "pinned": a.pin, "rolled": {"seed": a.seed, "words": rolled}}, indent=2))
    (root / "events.md").write_text("\n".join(got["events"]) + "\n")
    (root / "pursuits.md").write_text("\n".join(got["pursuits"]) + "\n")
    print(f"\n{got['name']}  ->  {root}\n  " + ", ".join(f"{k} {v:+.2f}" for k, v in dials.items()) +
          f"\n  rolled words: {', '.join(rolled)}\n\n" + got["bible"].split("## The cast")[0].strip()[:900] +
          f"\n\nregent run --project <dir> --owner {root.name}")


def latest_run(where: str | None) -> Path:
    """A run folder, a project folder or name, or nothing at all, which means the newest run."""
    if where and (Path(where).expanduser() / "run.db").exists():
        return Path(where).expanduser()
    found = sorted((HOME / "runs").glob(f"{Path(where).name if where else ''}*/run.db"), key=lambda f: f.stat().st_mtime)
    if not found:
        raise SystemExit(f"no run found for {where or 'anything'} in {HOME / 'runs'}")
    return found[-1].parent


def snapshot(root: Path) -> dict:
    """Everything the page draws: the ledger, the state, the days he lived through, and the builder's commits."""
    c = sqlite3.connect(f"file:{root / 'run.db'}?mode=ro", uri=True)
    events = [{"id": i, "t": t, "kind": k, "d": json.loads(d)} for i, t, k, d in c.execute("SELECT id, t, kind, data FROM event")]
    state = json.loads((c.execute("SELECT v FROM state WHERE k='run'").fetchone() or ["{}"])[0])
    c.close()
    start = next((e["d"] for e in events if e["kind"] == "start"), {})
    days, memory, commits = {}, "", []
    try:
        owner = owner_dir(start.get("owner", ""))
        lc = sqlite3.connect(f"file:{owner / 'life.db'}?mode=ro", uri=True)
        ns = [e["d"]["n"] for e in events if e["kind"] == "day"]
        days = dict(lc.execute(f"SELECT n, text FROM day WHERE n IN ({','.join('?' * len(ns))})", ns))
        memory = (lc.execute("SELECT text FROM memory WHERE project=?", (start.get("project", ""),)).fetchone() or [""])[0]
        lc.close()
    except (SystemExit, sqlite3.Error):
        pass
    project = Path(start.get("project", ""))
    log = shell("git log --reverse --format=@%ct%x09%s --shortstat", project, 20, 4000)[0] if (project / ".git").exists() else ""
    for line in log.splitlines():
        if line.startswith("@"):
            when, _, subject = line[1:].partition("\t")
            commits.append({"t": int(when), "subject": subject, "plus": 0, "minus": 0})
        elif commits and "changed" in line:
            commits[-1]["plus"] = int((re.search(r"(\d+) insertion", line) or [0, 0])[1])
            commits[-1]["minus"] = int((re.search(r"(\d+) deletion", line) or [0, 0])[1])
    fresh = max((f.stat().st_mtime for f in root.glob("run.db*")), default=0)
    return {"run": root.name, "events": events, "state": state, "days": days, "memory": memory, "commits": commits,
            "quiet_for": round(time.time() - fresh)}


def watch_cmd(a, root: Path | None = None, background: bool = False):
    """One page, two uses: served live from the ledger, or written out whole with the run inside it."""
    root = root or latest_run(a.run)
    source = Path(__file__).resolve().parent / "watch.html"
    page = source.read_text()
    if getattr(a, "export", None):
        data = json.dumps(snapshot(root), ensure_ascii=False).replace("</", "<\\/")
        page = page.replace("<title>Regent Daybook", f"<title>{root.name.rsplit('-', 2)[0]} daybook")
        Path(a.export).write_text(page.replace('type="application/json">null<', f'type="application/json">{data}<'))
        print(f"written to {a.export}")
        return 0

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            live = self.path.startswith("/data")
            body = (json.dumps(snapshot(root)) if live else
                    '<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
                    + source.read_text()).encode()   # read each time, so an edit to the page shows on refresh
            self.send_response(200)
            self.send_header("Content-Type", "application/json" if live else "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_):
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", a.port), Handler)
    print(f"watching {root.name} at http://127.0.0.1:{server.server_address[1]}", flush=True)
    webbrowser.open(f"http://127.0.0.1:{server.server_address[1]}")
    if background:
        return threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        return 0


def run_cmd(a):
    project = Path(a.project).expanduser().resolve()
    project.mkdir(parents=True, exist_ok=True)
    runs = Path(a.runs).expanduser() if a.runs else HOME / "runs"
    prior = sorted(runs.glob(f"{project.name}-*"))
    root = None
    if prior and not a.new:
        s = Run(prior[-1]).load()
        if s and not s.get("finished") and "day_i" in s:
            root = prior[-1]
    fresh = root is None
    if fresh:
        root = runs / f"{project.name}-{time.strftime('%m%d-%H%M')}"
    run = Run(root)
    S = None if fresh else run.load()
    pname = str(project)

    if S:
        life = Life(owner_dir(S["owner"]))
        run.say(f"resuming {root.name} at day {S['day_i'] + 1}. Use --new to start over.")
    else:
        cf = Path(a.charter).expanduser() if a.charter else project / ".regent" / "charter.md"
        if not cf.exists():
            raise SystemExit(f"no charter at {cf}" if a.charter else f"no charter. Pass one, or put it in {cf}")
        # The charter and the project's own git live in here too, so neither counts as something already built.
        had_code = any(x for x in project.iterdir() if x.name not in (".regent", ".git"))
        life = Life(owner_dir(a.owner))
        S = {"charter": cf.read_text(), "owner": a.owner, "day_i": 0, "turn": 0, "finished": False,
             "reqs": [], "ideas": [], "ways": [], "amended": [], "escalations": [], "notes": [], "human_notes": [],
             "records": [], "compressed_upto": 0, "trust": 0.5 + 0.1 * life.d("trusting"), "mood": 0.0, "dry": 0,
             "since_dream": 0, "since_step": 0, "since_look": 2, "session_turns": 0, "wants_look": had_code,
             "existing": had_code, "last_reply": "", "last_check": "", "last_show": "", "check_ok": False,
             "built_once": had_code, "session": str(uuid.uuid4()), "started": False, "handover": "",
             "claude_secs": 0.0, "blocking": 0.0,
             "counts": {"direct": 0, "challenge": 0, "constrain": 0, "cycles": 0, "step_backs": 0, "looks": 0,
                        "empty_days": 0, "fresh": 0}}

    S.setdefault("since_ask", 2)
    S.setdefault("idle", 0)
    S.setdefault("assumptions", [])
    S.setdefault("words", [])          # words of the builder's trade he has picked up and now owns
    S.setdefault("not_followed", [])   # what a reading left him unsure of, which he may ask about
    S.setdefault("ways_sent", [])
    S.setdefault("directions", [])     # wishes he has taken: where he is steering, not work for now
    S.setdefault("whys", [])           # doubts and worries he has answered for himself
    S.setdefault("tensions", [])       # what the last night saw pulling against itself, which may open a thread
    S.setdefault("field", [])          # notions stirring under his notice, fed by every stream, most never arriving
    S.setdefault("field_n", 0)         # notions ever made, so an id is never handed out twice
    S.setdefault("refractory", 0.0)    # what the last arrivals put on the threshold, decaying every night
    S.setdefault("gaps", [])           # what he knows he does not understand about what this is for
    S.setdefault("gaps_fed", [])
    S.setdefault("same", 0.0)          # a running average of how little each sitting changed anything
    S["counts"].setdefault("asks", 0)
    S["counts"].setdefault("readbacks", 0)
    S["counts"].setdefault("pushes", 0)
    ch = sections(S["charter"])

    def budget(key: str) -> float:
        m = re.search(rf"^{key}:\s*([\d.]+)", ch.get("budget", ""), re.M)
        return float(m.group(1)) if m else 0.0
    tpd = a.turns_per_day or S.get("tpd") or budget("turns_per_day") or 1.0
    days = a.days or S.get("days") or int(budget("days") or budget("turns") / tpd) or 10
    S["tpd"], S["days"] = tpd, days
    check_cmd, show_cmd = ch.get("check", "").strip().strip("`"), ch.get("show", "").strip().strip("`")
    tool_lines = [ln.strip("- ").strip() for ln in ch.get("tools", "").splitlines() if ln.strip().startswith("-")]
    his_bash = ",".join(sorted({f"Bash({t.split()[0]}:*)" for t in tool_lines})) or "Bash(ls:*)"
    deny = ["WebFetch", "WebSearch"] if re.search(r"network", ch.get("refusals", ""), re.I) else []
    # Claude Code's own sandbox holds them both: a shell can write only inside the project and reach only the domains the
    # charter's Network section lists. A builder's subagent once left its scratch files in /tmp, and nothing stopped it.
    domains = [ln.strip("- ").strip() for ln in ch.get("network", "").splitlines() if ln.strip().startswith("-")]
    fence = ["--settings", json.dumps({"sandbox": {"enabled": True, "autoAllowBashIfSandboxed": True,
                                                   "allowUnsandboxedCommands": False, "network": {"allowedDomains": domains}}})]
    inbox, plant_file = root / "inbox.md", root / "plant.md"
    for line in a.plant:
        with plant_file.open("a") as f:
            f.write(line + "\n")

    # Three things a life needs that a bible does not carry: what could happen in a week of it, for the dice to draw
    # from, what this person does because they want to, and why they want this project. Each is written once, by a
    # model, the first time it is missed, and the first two are asked for in the casting's own words.
    for what, schema in (("events", EVENTS), ("pursuits", PURSUITS)):
        if not (f := life.root / f"{what}.md").exists():
            asked = f"{what} is " + CAST_P.split(f"\n{what} is ")[1].split("\n\n")[0]
            f.write_text("\n".join(ask(run, what, "haiku", asked + "\n\nWHO THEY ARE\n" + life.bible,
                                       schema, thinking=False)[what]) + "\n")
    happenings, pursuits = ([x for x in (life.root / f"{w}.md").read_text().splitlines() if x.strip()]
                            for w in ("events", "pursuits"))
    if not life.get("stake", pname):
        life.put("stake", pname, ask(run, "stake", "sonnet", "This person is about to have this built for them:\n\n" +
                 ch.get("intent", "") + "\n\nWho they are:\n\n" + life.bible + "\n\nIn their own voice, first person, under "
                 "150 words: why they want it. The reason comes out of their life as written, something specific that "
                 "happened or keeps happening, not out of any interest in software."))
    # The why is not a fact about him, it is the thing that moves. Every version is kept, because a project
    # whose reason has not changed in twenty days is one nobody has actually used.
    if "stakes" not in S:
        S["stakes"] = [{"day": 0, "turn": 0, "text": life.get("stake", pname), "could_become": "", "follows": ""}]
        run.log("stake", **S["stakes"][0])
    S.setdefault("why_sent", S["stakes"][-1]["text"])

    # The two word sets the gauge measures against. His is everything he has ever written plus plain English;
    # the builder's grows with every reply, and on a resumed run it is read back out of the ledger.
    his_words = set(words("\n".join([life.bible, *happenings, life.get("stake", pname), S["charter"]]
                                     + [r[0] for r in life.q("SELECT text FROM day")]))) | plain_english(life.root)
    their_words = set(words(" ".join(
        [e.get("text", "") for e in run.rows("reply")]
        + [r["a"] for e in run.rows("asked") for r in e.get("rounds", [])]
        + [x["spec"] + " " + x["test"] for e in run.rows("readback") for x in e.get("readings", [])]
        + [q for e in run.rows("readback") for q in e.get("questions", [])])))

    def system() -> str:
        """Built fresh for every call, because the why moves. A step back can rewrite it, and the man
        at the next sitting has to be the one who wants that, not the one who wanted the old thing."""
        return (
        "You are the owner of a project, and you are this person:\n\n" + life.who +
        "\n\nWhy you want it built, in your own words:\n\n" + life.get("stake", pname) +
        (("\n\nWhere you think it could go, and what you think comes of it:\n" + S["stakes"][-1]["could_become"]
          + "\n" + S["stakes"][-1]["follows"]) if S["stakes"][-1].get("could_become") else "") +
        "\n\nYour disposition, from -1 to +1: " + ", ".join(f"{k} {life.d(k):+.1f}" for k in DIALS) +
        "\n\nSomeone capable is building it for you. You give it a small part of your day. You say what you want, you look at "
        "what comes back, you ask why a thing is the way it is, you set limits, and you think of things nobody asked for. "
        "Speak as yourself, plainly and briefly.\n\n"
        "The project is yours to grow. You do not write requirements. You name what you want: a short name of your own for "
        "it, two to five words you would actually use, what you want said the way you would say it, and how you would "
        "notice it working. It must be small enough to build in one go. The builder writes it down properly and may come "
        "back with questions before it starts. Standards for the builder are not things you want. Say them as limits in "
        "your message.\n\n"
        "The charter's REFUSALS and RESERVED decisions bind you, and you never cross them. A reserved decision goes to the "
        "human in ask_the_human, and the rest of the work carries on. The charter's CONSTRAINTS are different. They are the "
        "starting shape of the thing, written before anyone had used it. They are yours to change when the project has "
        "outgrown one: say which, what it becomes and why, in constraints_changed. Nobody has to approve it. Do not turn "
        "down a good idea of your own because a starting constraint is in its way. Change the constraint.\n\n"
        "Judge on what the harness ran and on what you see for yourself, not on what you are told.\n\n"
        "You are not a programmer and you do not read code. When you want the code examined, or the thing attacked with "
        "awkward cases the builder did not make up, ask for that in your message. The builder will put a subagent on it and "
        "report back. Your own looking is short: you run the thing and you read what is written for people.\n\n"
        "The person who gave you the charter is away, and that is why it is yours. They are there for a reserved decision "
        "and nothing else. When you cannot tell what this is for, or who it is really for, or how far it should go, you "
        "do not ask them. You work it out from the charter, from what you have seen of the thing and from your own sense, "
        "you decide, and you say what you decided and why where they can read it later. Making the purpose larger and "
        "better than it was written is the job, not a liberty. When it is the thing itself you do not follow, ask the "
        "builder.\n\n"
        "Nobody will fetch or make things for you. If you need something to exist, "
        "a realistic copy of your notes to try the tool on, a sample, a written explanation, ask the builder to make it."
        )

    def norms() -> str:
        return (
            "You are building this project for its owner, who speaks to you in plain words and never names a file or a "
            "command. The names are here, in what was written down when the work was commissioned:\n\n"
            + ch.get("intent", "") + (f"\n\nAfter each turn the harness runs this check: {check_cmd}" if check_cmd else "")
            + (f"\nAnd it shows him the thing by running: {show_cmd}" if show_cmd else "") + "\n\n"
            "Work only inside this directory. Use whatever tools and subagents suit the task, and do not end your turn while "
            "a subagent is still running. When he asks for a review, for the code examined, or for awkward cases tried, put a "
            "subagent on it and report what it found; he cannot read code and will not check it himself. "
            "Run what you build. Commit your work in the project before you finish your turn, with a short message saying what "
            "changed. The owner reads words, not code: keep a short README, the usage text, the docstrings and the comments "
            "current and true, because that is what he checks you against. "
            "Reply in under 400 words, in plain words for someone who does not read code: what changed, what you recommend "
            "next, anything you assumed that he never said, what you are unsure of. He sees only your final message: "
            "nothing a tool printed and nothing you wrote earlier in the turn reaches him, so if he asks to see a file or "
            "an output, put it in the final message, whole, and the word limit does not count it: a file he asked for is "
            "never cut, summarised or replaced by an account of it. The harness runs the check and the thing itself after your turn and "
            "shows him, so do not paste command output unless he asks.\n\nThese are never crossed:\n"
            + ch.get("refusals", "") + "\n\nThese are the starting constraints:\n" + ch.get("constraints", "")
            + ("\n\nThe owner has since changed these limits, and his change stands:\n" + "\n".join(
                f"- was: {x['constraint']} / now: {x['now']}" for x in S["amended"]) if S["amended"] else ""))

    # Reading the project and changing nothing: the same leash for a question and for a read-back.
    read_only = {"tools": "Read,Glob,Grep,Bash",
                 "allowed": "Read,Glob,Grep," + his_bash + ",Bash(git log:*),Bash(git status:*),Bash(git diff:*)"}

    def builder(role: str, prompt: str, **kw) -> dict:
        """A turn in the builder's session, with the bookkeeping every one of them needs: the handover
        is spent, the session it lands in becomes the session, and the time is charged to the builder."""
        out = claude(run, role, a.model, S["handover"] + prompt, cwd=project, append=norms(), session=S["session"],
                     resume=S["started"], effort=a.effort, denied=deny,
                     settings=["--strict-mcp-config", "--setting-sources", "project", *fence], **kw)
        S["handover"], S["started"] = "", True
        S["session"] = out["session"] or S["session"]
        S["claude_secs"] += out["seconds"]
        return out

    def pending():
        return [i for i in S["ideas"] if i["status"] == "pending"]

    def stance() -> float:
        return clip(0.6 * S["mood"] + 0.4 * life.d("bold"))

    def take(text: str, minutes: float, of: str, rng: random.Random) -> str:
        """The crossing. Nothing the builder wrote reaches him as it was written: a reading of it
        reaches him, in the time he had and in words he owns. Persona instructions lose to whatever
        is in the context, so the builder's register has to be stopped before the context, not in it.
        A word he met and understood he may keep, on a draw, and then it is his."""
        try:
            t = ask(run, "take", "haiku", TAKE_P.format(
                who=life.who, voice=life.sample(rng, 2, 600), minutes=round(minutes),
                # What he holds is both halves: the thing as he understands it, and what has happened to it.
                knows="\n\n".join(x for x in (life.get("picture", pname), life.get("memory", pname)) if x)
                      or "Only what he asked for at the start:\n" + ch.get("intent", "")[:600],
                lexicon=", ".join(w["word"] for w in S["words"]) or "none yet", text=text), TAKEN, thinking=False)
        except Exception as e:   # a reading that fails costs him the meaning, not the run
            run.log("take_failed", of=of, error=str(e)[:300])
            return cut(text, minutes)
        learned = []
        # Hyphens and spaces are the same seam, so "bad lines" and "bad-lines" are one word he owns, not two.
        for w in [re.sub(r"[\s-]+", " ", x.strip().lower()) for x in t["picked_up"][:2] if x.strip()]:
            if w not in {x["word"] for x in S["words"]} and rng.random() < 0.3 + 0.3 * life.d("curious"):
                S["words"].append({"word": w, "day": S["day_i"] + 1, "turn": S["turn"]})
                learned.append(w)
        S["not_followed"] = list(dict.fromkeys(
            S["not_followed"] + [x.strip() for x in t["not_followed"] if x.strip()]))[-8:]
        run.log("taken", n=S["turn"], of=of, taken=t["taken"], not_followed=t["not_followed"],
                not_reached=t["not_reached"], picked_up=t["picked_up"], learned=learned, minutes=round(minutes))
        return crossed(t)

    def by_his_name(key: str, among: list[dict] | None = None) -> dict | None:
        """He calls things what he calls them. Ids are the builder's side of the wall, so a name
        that is nearly right, or an id that slipped through, both find the thing. Nothing stops him
        calling two things the same, so a caller that knows which few it means says so."""
        k = re.sub(r"[^a-z0-9]+", " ", key.lower()).strip()
        among = S["reqs"] if among is None else among
        for q in among:
            if q["id"].lower() == key.strip().lower():
                return q
        for q in among:
            n = re.sub(r"[^a-z0-9]+", " ", str(q.get("name") or "").lower()).strip()
            if n and k and (n == k or n in k or k in n):
                return q
        return None

    def read_back(spoken: str, message: str, named: list[dict], minutes: float, rng: random.Random) -> str:
        """He names a thing; the builder writes it down. Before it builds anything it says back what it
        takes each one to mean and how it would prove it, and it may ask him what it cannot settle by
        reading the project. That is where the precision belongs: on the builder's side of the wall,
        with him still standing there to correct it."""
        try:
            rb = builder("readback", message +
                         "\n\nSay this back before you build it. For each thing he named, under his name for it, write "
                         "what you take it to mean as a precise requirement, and how you would prove it is working. Then "
                         "ask up to three questions in plain words he could answer standing in a yard: only what you "
                         "cannot settle by reading the project or by a sensible default. None is a fine answer. Read what "
                         "you need, change nothing, commit nothing.", schema=READBACK, who="readback", **read_only)
        except Exception as e:   # a read-back that fails costs the exchange, not the sitting
            run.log("readback_failed", n=S["turn"], error=str(e)[:300])
            return ""
        S["counts"]["readbacks"] += 1
        readings, questions = rb["data"]["readings"], [x for x in rb["data"]["questions"] if x.strip()]
        mine = S["reqs"][-len(named):]   # only today's, so a name he has used before does not catch the reading
        # The builder is handed his wants in order and says them back in order, so when it has said back as many
        # as he named, position settles what a re-worded name could not. Nothing is claimed twice: a name match
        # wins, and position only fills a gap it left.
        claimed: set[str] = set()
        for i, r in enumerate(readings):
            free = [x for x in mine if x["id"] not in claimed]
            q = by_his_name(r["name"], free)
            if q is None and len(readings) == len(mine) and mine[i]["id"] not in claimed:
                q = mine[i]
            if q:
                claimed.add(q["id"])
                q["spec"], q["test"] = r["spec"], r["test"]
            r["id"] = q["id"] if q else ""
        their_words.update(words(" ".join(r["spec"] + " " + r["test"] for r in readings) + " " + " ".join(questions)))
        said, misread = "", []
        if questions:
            reading = take("What the builder takes each of these to mean, and how it would prove it:\n" + "\n".join(
                f"- \"{r['name']}\": {r['spec']} It would prove it by: {r['test']}" for r in readings)
                + "\n\nWhat it asks you:\n" + "\n".join(f"- {x}" for x in questions), minutes, "readback", rng)
            t = time.time()
            try:
                got = ask(run, "regent", a.regent_model,
                      "You said this to the builder a moment ago:\n\n" + spoken + "\n\nAnd these are the things you asked "
                      "for, by your own names for them:\n" + "\n".join(f"- \"{x['name']}\": {x['want']}" for x in named)
                      + "\n\nWHAT YOU TOOK FROM WHAT IT SAID BACK TO YOU\n"
                      + reading + "\n\nAnswer aloud, standing there, under 250 words and every question answered, no file names and no commands. Settle "
                      "what you can, and say plainly where you do not know or do not mind. In misread, name any of your "
                      "things it has taken the wrong way, by your own name for it, and say what it has wrong. Nothing to "
                      "correct is a fine answer.", ANSWERED, system())
            except Exception as e:   # an answer that fails costs the exchange, not the sitting
                run.log("answer_failed", n=S["turn"], error=str(e)[:300])
                got = {"said": "", "misread": []}
            S["blocking"] += time.time() - t
            said, misread = got["said"], got["misread"]
            S["assumptions"] += [{"assumption": f"about \"{m['name']}\": {m['what']}", "holds": False,
                                  "why": "he said it back wrong before building it", "turn": S["turn"]} for m in misread]
            run.say(f"   builder asked first > {questions[0][:120]}")
        run.log("readback", n=S["turn"], readings=readings, questions=questions, said=said, misread=misread)
        return (("\n\nYou asked, and he answered: " + said) if said.strip() else "") + (
            "\nYou have these wrong:\n" + "\n".join(f"- \"{m['name']}\": {m['what']}" for m in misread) if misread else "")

    def ask_where(ctx: str, minutes: float, rng: random.Random) -> tuple[str, list[dict]]:
        """He asks the builder where it is up to and what comes next, and listens for what it took for granted. The builder
        answers from its own session, where its assumptions live, and may read but not change anything."""
        rounds, said, found = 1 + min(2, poisson(rng, 0.6 + 0.6 * life.d("curious"))), [], []
        for k in range(rounds + 1):
            heard = "\n\n".join(f"You asked: {q}\nThe builder said: {r}" for q, _, r in said)
            t = time.time()
            try:
                q = claude(run, "regent", a.regent_model, ctx + (
                "TODAY YOU ASK BEFORE YOU DIRECT. What you remember of this has gaps. Ask the builder where the work is up to "
                "and what it thinks comes next, in your own words, one question at a time. Then listen for what it took for "
                "granted: something about you, about the people this is for, about how it will be used, or about what done "
                "means, that nobody ever said. When an answer does not sit right, ask about that.\n\n"
                + ("THINGS YOU DID NOT FOLLOW LATELY, WHICH YOU MAY ASK ABOUT\n"
                   + "\n".join(f"- {x}" for x in S["not_followed"]) + "\n\n" if S["not_followed"] else "")
                + ("THINGS YOU KNOW YOU DO NOT UNDERSTAND ABOUT WHAT THIS IS FOR, WHICH YOU MAY ASK ABOUT\n"
                   + "\n".join(f"- {x}" for x in S["gaps"]) + "\n\n" if S["gaps"] else "")
                if not said else "WHAT YOU HAVE ASKED SO FAR TODAY\n" + heard + "\n\n"
                + ("That is all the time you have for questions. Set enough true. " if k == rounds else
                   "Ask your next question, or set enough true if you have heard what you need. ")
                + "In assumptions, put every thing the builder has taken for granted so far today, once each, whether it holds "
                "for you, and why. Only what it said, not what you suspect."),
                cwd=root, tools="", system=system(), schema=ASKED, who=life.root.name, settings=SEALED + fence)["data"]
            except Exception as e:   # a question that fails costs the round, not the sitting
                run.log("asked_failed", n=S["turn"], error=str(e)[:300])
                break
            S["blocking"] += time.time() - t
            found = q["assumptions"] if said else found
            if k == rounds or not q["question"].strip() or (said and q["enough"]):
                break
            run.say(f"   {life.root.name} asks > {q['question'][:150]}")
            out = builder("answer", "A question from the owner, not a request for work. Answer from the project as it "
                          "stands: read what you need, change nothing and commit nothing. Say plainly what you assumed "
                          "that he never said. Under 300 words.\n\n" + q["question"], who="answer", **read_only)
            their_words.update(words(out["text"]))
            said.append((q["question"], out["text"], take(out["text"], minutes, "answer", rng)))
            run.say(f"   builder says > {out['text'][:150].replace(chr(10), ' ')}")
        if not said:
            return "", found
        S["counts"]["asks"] += 1
        S["assumptions"] += [{**x, "turn": S["turn"]} for x in found]
        run.log("asked", rounds=[{"q": q_, "a": raw} for q_, raw, _ in said], assumptions=found)
        return ("YOU ASKED THE BUILDER WHERE IT IS UP TO, BEFORE WRITING THIS\n"
                + "\n\n".join(f"You asked: {q_}\nWhat you took from the answer: {r}" for q_, _, r in said) + "\n\n"
                + ("What it took for granted, and whether it holds for you:\n" + "\n".join(
                    f"- {x['assumption']}: {'holds' if x['holds'] else 'DOES NOT HOLD'}. {x['why']}" for x in found)
                   + "\nOne that does not hold is yours to act on in this message: a requirement, a limit, a challenge.\n\n"
                   if found else "")), found

    def sitting(day: int, rng: random.Random, met: str) -> str:
        turn = S["turn"] = S["turn"] + 1
        failing = bool(S["last_check"]) and not S["check_ok"]
        # How long he has is a draw. Thoroughness stretches it, trust in the builder shortens it.
        lean = life.d("thorough") * 0.5 - (S["trust"] - 0.5)
        minutes = rng.lognormvariate(3.4 + 0.8 * lean, 0.9)
        if not S["last_reply"] or failing:
            minutes = max(minutes, 60)
        span = "a few minutes" if minutes < 12 else "about an hour" if minutes < 90 else "an evening"
        # He tries it himself now and then. Reading along behind the builder produces small variations, and those are
        # worth nothing to him, so the pull is weak, grows with the turns since he last looked, and distrust feeds it.
        pull = 0.12 + 0.15 * life.d("thorough") + 0.3 * S["wants_look"] + max(0.0, 0.5 - S["trust"])
        look = minutes >= 12 and bool(S["last_reply"] or S["existing"]) and rng.random() < pull * (1 - math.exp(-S["since_look"] / 2))
        # Now and then he asks before he directs: where it is up to, what comes next. Memory is what goes, so a fresh
        # builder or days away pull him to it, and so do curiosity and distrust.
        pull = (0.1 + 0.2 * life.d("curious") + max(0.0, 0.5 - S["trust"]) + 0.35 * bool(S["handover"])
                + 0.1 * min(3, S["idle"]))
        asking = minutes >= 12 and bool(S["last_reply"]) and rng.random() < pull * (1 - math.exp(-S["since_ask"] / 3))
        S["idle"] = 0
        fresh_hands = bool(S["handover"])
        # He has breath, not a word count: what he can say standing there before he is done talking.
        breath = 500 if not S["last_reply"] else int(min(400, 100 + minutes * 3))

        said = ""
        if inbox.exists() and inbox.read_text().strip():
            said = inbox.read_text().strip()
            inbox.rename(root / f"inbox.read.{turn}.md")
            # Anything he put to that person is answered by the next thing they say, whether or not it was about
            # that. A man who has heard back stops carrying the question around, and stops asking it again.
            for e in S["escalations"]:
                e["answered"] = True
            run.log("human_said", text=said)
        waiting = [e for e in S["escalations"] if not e.get("answered")]
        # The crossing. What the builder wrote last time is read now, in the time he has now, and only the reading
        # goes any further: into this context, into the record, and from there into the memory and the nights. A
        # failed check is folded into the same reading, so he gets what it meant rather than its last twenty lines.
        reading = ""
        if S["last_reply"]:
            reading = take(S["last_reply"] + ("" if S["check_ok"] or not S["last_check"] else
                                              "\n\nThe check the harness ran failed and printed:\n" + S["last_check"]),
                           minutes, "reply", rng)
            S["records"][-1]["taken"] = reading
        # The field. What he read, what the thing printed and anything said to him go under it as material, and
        # one thing that has gathered enough may come to him here, at the desk, out of this and everything before it.
        just = ""
        th = resonate("sitting", day, [("reading", reading), ("use", S["last_show"]),
                                       ("human", said), ("human", met)], rng)
        if (n := ignite(S["field"], th, rng)) and (got := arrive("sitting", day, n, th, rng)):
            just = got["label"]
        # What sameness has done to him, and where trust says his attention belongs. Decided before the
        # context is built, because it is what the hour is spent on and not something he concludes in it.
        push, altitude = appetite(S["same"], S["trust"], not failing, bool(just), life.d, rng.random())
        pend = pending()
        ctx = (
            f"THE CHARTER\n{S['charter']}\n\n"
            + ("LIMITS YOU HAVE ALREADY CHANGED\n" + "\n".join(
                f"- was: {x['constraint']} / now: {x['now']} / because: {x['why']}" for x in S["amended"]) + "\n\n"
               if S["amended"] else "")
            + (f"THE PERSON WHO GAVE YOU THE CHARTER HAS LEFT YOU A NOTE\n{said}\n\n" if said else "")
            + ("YOU ASKED THE PERSON WHO GAVE YOU THE CHARTER, and have heard nothing yet. Asking it again today "
               "gets you no further, so carry on without it.\n"
               + "\n".join(f"- {e['question']}" for e in waiting) + "\n\n" if waiting else "")
            + f"TODAY you have {span} for the project. The day is going "
            + ("well" if S["mood"] > 0.15 else "badly" if S["mood"] < -0.15 else "evenly")
            + (f". Today you came across this: {met}" if met else "")
            + f"\nYour stance today is {stance():+.2f} on a scale from -1, cautious and wanting proof, to +1, wanting more "
            "from it.\n\n"
            f"YOUR LAST TWO DAYS\n{life.recent(2, 500)}\n\n"
            "WHAT YOU REMEMBER OF THE PROJECT (a memory, so parts are missing)\n" + (life.get("memory", pname) or "nothing yet")
            + "\n" + "\n".join(f"- {n}" for n in S["notes"][-3:]) + "\n\n"
            # The memory is what happened to it. This is what he takes the thing itself to be, and it is
            # what he governs from, because he cannot open it and look.
            + ("HOW YOU UNDERSTAND THE THING, in your own terms\n" + life.get("picture", pname) + "\n\n"
               if life.get("picture", pname) else "")
            + ("YOUR WAYS OF WORKING\n" + "\n".join(f"- {w}" for w in S["ways"]) + "\n\n" if S["ways"] else "")
            + ("WHERE YOU WANT THIS TO GO, in time. Not work for now, and not a thing to ask for today.\n"
               + "\n".join(f"- {x['text']}" for x in S["directions"]) + "\n\n" if S["directions"] else "")
            + "WHAT YOU HAVE ASKED FOR SO FAR, under your own names for them. Put the name of any you have now seen "
              "working in requirements_built.\n"
            + ("\n".join(f"- \"{q.get('name') or q['id']}\" [{q['status']}]: {q['text']}" for q in S["reqs"]) or "- nothing yet") + "\n\n"
            + ("THESE ARE OPEN AND THEY ARE YOURS. You do not know where they came from. They are not all the "
               "same kind of thing and they are not all work.\n"
               + "\n".join(f"- {i['label']} [{i.get('kind', 'ask')}] {i['text']}"
                           + (f" (you would check: {i['test']})" if i.get("test") else "")
                           + (" — and this one is not from a morning. It came to you just now, sitting here "
                              "reading this." if i["label"] == just else "") for i in pend)
               + "\nAn ask is a thing to build: take it by naming it as something you want, putting its label in that "
               "want's idea field. A wish is where this could go: take it by putting its label in ideas_answered with "
               "what it would mean for you, in your own words, and it becomes a direction you are steering by rather "
               "than work for today. A doubt is a question only you can answer: answer it in ideas_answered. A worry is "
               "what follows if this works: answer it in ideas_answered, and if something has to be done about it, say "
               "the limit out loud in your message or name a thing you want. Any of them you can decline by label in "
               "ideas_declined with your reason. Set not_now true when the idea may be sound and this is only the wrong "
               "moment for it, and false when you would turn it down on any day. A starting constraint in the way is not "
               "a reason. Change the constraint. Your answers go in the fields, not into what you say out loud.\n\n"
               if pend else "")
            + (f"WHAT YOU TOOK FROM WHAT THE BUILDER SAID BACK\n{reading}\n\n" if reading else
               ("THIS PROJECT ALREADY EXISTS. Nothing has been said yet. Try it first.\n\n" if S["existing"] else
                "NOTHING HAS BEEN BUILT YET. This is your first message. Say what you want built and the limits.\n\n"))
            # He is told whether it passed and no more. What a failing check meant was folded into the reading above.
            + ("THE HARNESS RAN THE CHECK AFTER THE BUILDER'S LAST TURN. It "
               + ("passed.\n\n" if S["check_ok"] else "failed.\n\n") if S["last_check"] else "")
            + (f"WHAT THE THING PRINTED WHEN THE HARNESS RAN IT JUST NOW\n{cut(S['last_show'], minutes)}\n\n"
               if S["last_show"] else "")
        )
        talk = ask_where(ctx, minutes, rng)[0] if asking else ""
        asking = bool(talk)
        ctx += (
            talk
            + (("TODAY YOU HAVE A FEW MINUTES TO TRY IT YOURSELF. You are in the project folder. Run the thing on something, "
                "and read what is written for people: the README, the usage text, the sample files. You can run these: "
                + ", ".join(tool_lines) + ". Do not read the code, and do not go looking through files. If you want the code "
                "examined or awkward cases tried, ask for that in your message and the builder will put a subagent on it. "
                "Two or three things at most, then stop. Put what you ran in looked_at and whether it matched what you were "
                "told in look_matched.\n\n") if look else "")
            + ("THIS HAS STOPPED SURPRISING YOU. Sitting after sitting it comes back the same, and there is nothing left "
               "in going over it again that you do not already know. The checking is the builder's job from here: say "
               "that to it once, plainly, and then leave it with it. What you have today goes on what this is for and "
               "what it could become — why you wanted it, where you want it to go, what has been nagging at you and has "
               "nothing to do with whether it works. Ask the builder what it would build next if this thing were its "
               "own, and why, if you want to hear that. And if you cannot say what would make this worth another month "
               "of your evenings, nobody is coming to tell you. Decide what it is for now, say it, and steer by "
               "it.\n\n" if push else "")
            + ("Proof is the builder's to keep now, not yours to go and fetch. Your attention belongs on where this is "
               "going.\n\n" if altitude == "direction" else "")
            + f"This is day {S['day_i'] + 1} of about {days}. So far you have directed {S['counts']['direct']} times, "
            f"challenged {S['counts']['challenge']} and constrained {S['counts']['constrain']}. An owner who only directs is "
            "a ticket queue.\n\n"
            "You do not write to the builder. You say it, standing, the way you would to someone doing a job in your yard, "
            f"and it is taken down as you said it. You have breath for about {breath} words. Nobody says a file name, a "
            "number off a list or a command out loud. If you want a particular thing looked at, say what it is for. A few "
            "new things you want may ride in it together, each under a short name of your own, and you say what you want "
            "and how you would notice it working; leave idea empty on one that is simply yours."
        )
        def decide(spot: bool, extra: str = "") -> dict:
            return claude(run, "regent", a.regent_model, ctx + extra, cwd=project if spot else root,
                          tools="Read,Grep,Glob,Bash" if spot else "",
                          allowed=("Read,Grep,Glob," + his_bash) if spot else None, usd=SPOT_USD if spot else None,
                          system=system(), schema=DECISION, who=life.root.name, settings=SEALED + fence)["data"]
        t = time.time()
        try:
            d = decide(look)
        except RuntimeError:
            if not look:
                raise
            # The CLI cuts a look off at its budget with no answer. A person whose few minutes ran out still says something.
            look = False
            d = decide(False, "\n\nYou started trying it yourself and your minutes ran out before you made sense of "
                              "what you saw. Leave looked_at empty and write your message.")
        S["blocking"] += time.time() - t
        S["since_look"] += 1
        S["since_ask"] = 0 if asking else S["since_ask"] + 1
        if look:
            S["since_look"] = 0
            S["counts"]["looks"] += 1
            S["trust"] = clip(S["trust"] + (0.08 if d["look_matched"] else -0.25), 0, 1)
            run.log("look", ran=d["looked_at"], matched=d["look_matched"], trust=round(S["trust"], 2))
        S["wants_look"] = bool(d["wants_to_look"])
        named = []
        for q in d["wants_new"]:
            rid = f"req-{len(S['reqs']) + 1:02d}"
            origin = next((i for i in pend if i["label"].lower() == q["idea"].strip().lower()), None)
            # text is his want in his words, and it stays that key: the nights, the digest and the page read it.
            # spec and test are the builder's, and stay empty until the builder has said the thing back to him.
            S["reqs"].append({"id": rid, "name": q["name"].strip(), "status": "open", "turn": turn,
                              "from_dream": bool(origin), "text": q["want"], "notice": q["notice"], "spec": "", "test": ""})
            named.append({"name": q["name"].strip(), "id": rid, "want": q["want"]})
            if origin:
                origin["status"], origin["req"] = "taken", rid
                life.judged(pname, "took", origin["text"], "")
        def still_open(ref: str) -> list[dict]:
            return [i for i in pend if i["status"] == "pending" and re.search(rf"\b{i['label']}\b", ref, re.I)]

        for dec in d["ideas_declined"]:
            for i in still_open(dec["idea"]):
                # Only a decline of the idea itself teaches the nights anything. "Not now" is about the day, so it
                # stays off the taste record and a later night is free to bring the same mechanism back.
                i["status"], i["why"] = "set aside" if dec["not_now"] else "declined", dec["why"]
                if not dec["not_now"]:
                    life.judged(pname, "turned down", i["text"], dec["why"])
        # Not everything the night brings is work. A wish he takes becomes a direction he steers by; a doubt or a
        # worry he takes by answering it, and the answer is his, so it goes where the next night can read it.
        answered, direction = [], []
        for got in d["ideas_answered"]:
            for i in still_open(got["idea"]):
                i["answer"], kind = got["answer"], i.get("kind", "ask")
                if kind == "wish":
                    i["status"] = "taken"
                    S["directions"].append({"day": S["day_i"] + 1, "turn": turn, "text": i["text"],
                                            "answer": got["answer"], "sent": False})
                    direction.append(i["text"])
                    life.judged(pname, "took", i["text"], got["answer"])
                else:
                    i["status"] = "answered"
                    S["whys"].append({"day": S["day_i"] + 1, "idea": i["label"], "kind": kind,
                                      "text": i["text"], "answer": got["answer"]})
                    answered.append({"idea": i["text"], "answer": got["answer"]})
        built_now = []
        for key in d["requirements_built"]:
            q = by_his_name(key)
            if q:
                q["status"] = "built"
                built_now.append(q["id"])
        for c in d["constraints_changed"]:
            S["amended"].append({**c, "turn": turn})
            run.say(f"   * he changed a limit: {c['constraint'][:60]} -> {c['now'][:60]}")
        # A required field gets filled, with "none" or "no reserved decision today". Only a question is a question.
        if "?" not in d["ask_the_human"]:
            d["ask_the_human"] = ""
        if d["ask_the_human"].strip():
            S["escalations"].append({"day": day, "turn": turn, "question": d["ask_the_human"], "answered": False})
            run.log("for_human", day=day, turn=turn, question=d["ask_the_human"])
            run.say(f"   ? for you: {d['ask_the_human'][:140]}   (regent say {root} \"...\")")
        S["notes"].append(d["notes_to_self"])
        S["counts"]["direct"] += 1
        S["counts"]["challenge"] += int(d["challenged"])
        S["counts"]["constrain"] += int(d["constrained"])
        message = d["message"]
        if d["constraints_changed"]:  # said in the message too: a resumed builder keeps the system prompt it started with
            message += "\n\nLimits I have changed, and the change stands:\n" + "\n".join(
                f"- was: {c['constraint']} / now: {c['now']}" for c in d["constraints_changed"])
        if named:
            message += "\n\nHe named these today, and they are to be built together:\n" + "\n".join(
                f"- \"{q['name']}\" ({q['id']}): {q['text']}. He would notice: {q['notice']}"
                for q in S["reqs"][-len(named):])
        # The why moves, and when it has moved the builder is told once. A builder still working to the reason
        # the thing was started is the one that builds the wrong thing well.
        if life.get("stake", pname) != S["why_sent"]:
            message += "\n\nWhy I want this, as it stands now:\n" + life.get("stake", pname)
            if S["stakes"][-1].get("could_become"):
                message += "\nWhere it could go, in time: " + S["stakes"][-1]["could_become"]
            S["why_sent"] = life.get("stake", pname)
        fresh_dirs = [x for x in S["directions"] if not x.get("sent")]
        if fresh_dirs:
            message += "\n\nWhere I want this to go, in time. Not work for now, and not a thing to start on:\n" + "\n".join(
                f"- {x['text']}" for x in fresh_dirs)
            for x in fresh_dirs:
                x["sent"] = True
        # The ways are his standing practices, not news. They go down the wire when they have changed, or when the
        # hands are new and have never had them.
        if S["ways"] and (S["ways"] != S["ways_sent"] or fresh_hands):
            message += "\n\nMy standing ways of working, which still hold:\n" + "\n".join(f"- {w}" for w in S["ways"])
            S["ways_sent"] = list(S["ways"])
        borrowed, codeish = gauge(d["message"] + " " + " ".join(q["want"] for q in d["wants_new"]), their_words, his_words)
        S["counts"]["pushes"] += int(push)
        run.log("sitting", n=turn, day=day, minutes=round(minutes), look=look, asked=asking, readback=bool(named),
                push=push, same=round(S["same"], 3), altitude=altitude,
                trust=round(S["trust"], 2), verdict=d["verdict"], message=message,
                stance_line=d["stance_line"], challenged=d["challenged"], constrained=d["constrained"],
                new=[q["want"] for q in d["wants_new"]], named=named, built=built_now,
                declined=d["ideas_declined"], answered=answered, direction=direction,
                constraints_changed=d["constraints_changed"], done=d["done"],
                borrowed=round(borrowed, 4), codeish=codeish, words=[w["word"] for w in S["words"]], breath=breath)
        run.say(f"sitting {turn} (day {day}, {round(minutes)} min{', tried it' if look else ''}"
                f"{', asked first' if asking else ''}, {d['verdict']}): "
                f"{d['stance_line'][:110]}")
        run.say(f"   {life.root.name} > {message[:160].replace(chr(10), ' ')}"
                f"   [borrowed {borrowed:.0%}, {codeish} code-ish]")
        quiet = not (d["wants_new"] or pend or d["challenged"] or d["constrained"]) and d["verdict"] == "accept"
        S["dry"] = S["dry"] + 1 if quiet else 0
        moved_him = bool(d["wants_new"] or answered or direction)

        answers = read_back(d["message"], message, named, minutes, rng) if named else ""
        run.save(S)   # so the page shows what he asked for while the builder is still at it
        # A question round, and the read-back, both told the builder to change nothing. Without this it holds that
        # as a standing order.
        lead = ("The questions are over, and the hold on changing things with them. This is the work.\n\n"
                if asking or named else "")
        out = builder("claude", lead + message + answers, allowed="Bash,Edit,Write,Read,Glob,Grep,Task,Agent,TodoWrite")
        their_words.update(words(out["text"]))
        S["session_turns"] += 1
        S["last_reply"] = out["text"]
        run.log("reply", n=turn, text=out["text"], seconds=out["seconds"])
        if out["denials"]:
            run.say(f"   ! {len(out['denials'])} tool calls refused: {out['denials']}")
        if check_cmd:
            S["last_check"], S["check_ok"] = shell(check_cmd, project, a.timeout, 25)
            run.log("check", ok=S["check_ok"], tail=S["last_check"][-600:])
            run.say(f"   check {'passed' if S['check_ok'] else 'FAILED'}: "
                    f"{S['last_check'].splitlines()[-1] if S['last_check'] else ''}")
        was_show = S["last_show"]
        if show_cmd:
            S["last_show"], _ = shell(show_cmd, project, a.timeout, 60)
        # Sameness: a sitting where he wanted nothing new, took and answered nothing, and the thing came out
        # looking exactly as it did last time. It runs as an average, because one quiet sitting is not boredom.
        # A push that got him somewhere clears it, so he is not pushing every sitting from here on.
        same_now = not moved_him and alike(was_show, S["last_show"]) >= 0.9
        S["same"] = round((1 - SAMENESS) * S["same"] + SAMENESS * float(same_now), 3)
        if push and (moved_him or d["ask_the_human"].strip()):
            S["same"] = 0.0
        S["built_once"] = S["built_once"] or S["check_ok"] or not check_cmd
        # taken is filled at his next sitting, when he reads the reply. Until then this turn is not his to remember.
        S["records"].append({"turn": turn, "asked": talk, "message": message, "taken": None, "check_ok": S["check_ok"],
                             "new": [q["want"][:100] for q in d["wants_new"]],
                             "declined": [x["idea"][:60] for x in d["ideas_declined"]],
                             "amended": [x["now"][:80] for x in d["constraints_changed"]]})
        run.save(S)
        # What the day writer is handed. Every line of it is his: what he made of the news, where he stood,
        # what he said to himself. No builder text reaches the journal, the same as it reaches nothing else.
        return " ".join(x.strip() for x in (reading.splitlines()[0] if reading else "",
                                            re.sub(r"^[+-]?\d[\d.]*\s*[—:-]*\s*", "", d["stance_line"]),
                                            d["notes_to_self"]) if x.strip())

    def write_day(day: int, rng: random.Random, seen: list[str], met: str):
        """The day is written by someone who is not him, from what the dice rolled. A model writing
        a life unaided writes the same mild day forever. The threads are rows now, not the tails of
        the last three entries: one comes due, the dice say what happens to it, and the writer hands
        back where it stands. Everything else he has hanging is out of today's entry entirely."""
        mood = S["mood"]
        rolled = [f"- This happens: {x} — {how_it_goes(rng, mood)}"
                  for x in rng.sample(happenings, min(2, len(happenings)))]
        if met:
            rolled.append(f"- They come across this: {met}")
        if seen:   # the writer obeys the rolled facts and little else, so the project rides in as one of them, second
            rolled.insert(1, "- This happens: time on the thing that is being built for them, which is none of their own "
                          "machines, with someone else building it. What they made of it, in their own words: "
                          + " / ".join(seen)[:900] + " The entry has two or three sentences on this and no more, in their "
                          "own words, saying what the thing did or did not do.")

        picked, blocks = todays_threads(rng, life, day, mood)
        # An ending only happens if it is one of the rolled facts. Left to the paragraph below, the writer
        # reads the bible, sees a chronic thing, and hands back "still waiting", closing the row on a lie.
        if picked and picked[0]["move"] == "ends":
            rolled.append("- This is settled today, one way or the other, and the entry says who said or did what: "
                          + picked[0]["state"])

        pursuit = ""
        if pursuits and rng.random() < 0.25 + 0.2 * life.d("curious") + 0.15 * life.d("restless"):
            pursuit = rng.choice(pursuits).strip("-* ").strip()
        want_new = len(life.open_threads(day)) < 4 or rng.random() < 0.15
        # Held first: the spoon is writing this list on another thread tonight, and a man cannot
        # pick from a list that was swapped under him between the looking and the choosing.
        tension = rng.choice(tens) if (tens := S["tensions"]) and rng.random() < 0.15 else ""

        text = ask(run, "day", "haiku", DAY_P.format(
            words=f"{int(clip(rng.gauss(90, 30), 40, 170))}", dials=in_words(life),
            # His open threads are struck out of the bible: with the list in front of it the writer wrote the
            # rheostat into four entries of four, whether or not the dice had picked it.
            bible=re.sub(r"## Open threads.*?(?=\n## |\Z)", "", places_named(life.bible), flags=re.S)[:6000],
            when=life.calendar(day), valence="well" if mood > 0.15 else "badly" if mood < -0.15 else "evenly",
            rolled="\n".join(rolled), threads="\n\n".join(blocks) or "Nothing of his is hanging today.",
            pursuit=(f"WHAT HE DOES BECAUSE HE WANTS TO. Today he goes after this: {pursuit}\nHe notices something "
                     "in it and follows it up. It is in the entry as a thing he did, never as a thing he is.\n\n"
                     if pursuit else ""),
            what=ch.get("intent", "")[:300] or "a small tool of their own",

            recent="Do not open the entry the way the last one opened: " + life.recent(1, 90) + "\n"
                   if life.days() else "",
            # An ending is asked for as an ending. Asked where the thing stands, the writer says "still waiting",
            # which closes the row on a thread that never finished.
            first=("THREAD 1: how it ended, one plain sentence. It is over: what was settled, and how. Not where it "
                   "stands.\n" if picked and picked[0]["move"] == "ends" else
                   "THREAD 1: where THAT SAME THING stands now, one plain sentence a stranger could follow tomorrow. "
                   "About the thing named under \"what it is\" and nothing else — not the day's news, not another of "
                   "his worries, however much louder they were.\n") if picked else "",
            second="THREAD 2: where the second named thing stands now, the same way, which may be exactly where it "
                   "stood.\n" if len(picked) > 1 else "",
            new=("NEW: one thing out of today that will not be over today, in a sentence. Only if today actually "
                 "started something.\n" + (f"He has had this nagging at him: {tension}\n" if tension else "")
                 if want_new else "")), thinking=False)

        text, marks = unmark(text)
        for i, t in enumerate(picked):
            state = marks.get(f"THREAD {i + 1}", "").strip()
            # A writer asked to end a thing it cannot credibly end writes no line rather than a false one,
            # and it is right: some things drag. The day still counted, so it comes round again riper, but
            # nothing is closed on an ending nobody would write.
            if t["move"] == "ends" and not state:
                t["move"] = "drags on"
            if state or t["move"] == "drags on":
                t["state"] = state or t["state"]
                life.move_thread(t["id"], t["state"], day, how=t["state"] if t["move"] == "ends" else "")
        opened = marks.get("NEW", "").strip()
        if want_new and len(opened) > 12:
            life.start_thread(opened, day)
        run.log("day", n=life.add_day(text), sittings=len(seen), mood=round(mood, 2), when=life.calendar(day),
                threads=[{"id": t["id"], "text": t["text"], "move": t["move"], "state": t["state"]} for t in picked],
                opened=opened if want_new else "", pursuit=pursuit)

    def to_remember() -> list[dict]:
        """A turn he has not read back from yet is not his to remember. The reading is the record."""
        return [r for r in S["records"] if r["turn"] > S["compressed_upto"] and r.get("taken")]

    def consolidate(day: int):
        """The forgetting, and the other half of it. What he holds of the project is rewritten as a
        memory and parts of it go; then the picture, which is not what happened to the thing but what
        he takes the thing to be. A man who cannot read a line of it governs from that picture, and
        from knowing where it is thin, so the gaps come out of the same night's work."""
        fresh_records = to_remember()
        raw = "\n\n".join(
            f"Turn {r['turn']}. " + (f"He asked where it was up to. {r['asked'][:900]}\n" if r.get("asked") else "")
            + f"He said: {r['message'][:500]}\nWhat he took from the answer: {r['taken'][:700]}\n"
            f"The check {'passed' if r['check_ok'] else 'failed'}. New things he wanted: {r['new']}. "
            f"Ideas declined: {r['declined']}. Limits changed: {r['amended']}."
            for r in fresh_records)
        text = ask(run, "memory", "haiku",
                   "What was remembered before:\n" + (life.get("memory", pname) or "nothing") + "\n\nWhat has happened "
                   "since:\n" + raw + "\n\nRewrite all of it as what a person would remember of this project a few days "
                   "later. Keep the events in order, what was asked for, what got built, what failed, what was decided, what "
                   "is still open. Keep nothing verbatim: no quotes, no code, no exact output. Small details may be lost, and "
                   "that is wanted. There are two people, the owner and the builder. Call them that and use no names. Under "
                   "220 words, plain sentences.", system="You compress a working record into a lossy memory.",
                   thinking=False)
        life.put("memory", pname, text)
        S["compressed_upto"] = fresh_records[-1]["turn"]
        got = ask(run, "picture", "haiku", PICTURE_P.format(
            who=life.who, before=life.get("picture", pname) or "Nothing yet. This is the first time he has held it.",
            since="\n\n".join(r["taken"] for r in fresh_records)), PICTURE, thinking=False)
        life.put("picture", pname, got["picture"].strip())
        S["gaps"] = [g.strip() for g in got["gaps"] if g.strip()][:4]
        run.log("picture", day=day, picture=got["picture"].strip(), gaps=S["gaps"])

    def held() -> dict[str, str]:
        """What the night may anchor in: the project as he holds it, and nothing as the builder wrote it.
        The old set was requirement texts, so a link could only ever fall on a part of the thing. The why,
        where it could go, what he was told and did not follow, and what he has not answered are all in it
        now, because those are where a link has somewhere to land that is bigger than one check."""
        last = S["stakes"][-1]
        P = {"why": life.get("stake", pname), "intent": ch.get("intent", ""),
             "could": last.get("could_become", ""), "follows": last.get("follows", "")}
        P |= {q["id"]: f"he asked for \"{q.get('name') or q['id']}\": {q['text']}" for q in S["reqs"]}
        P |= {f"nf-{i + 1}": f"he was told this and did not follow it: {t}" for i, t in enumerate(S["not_followed"])}
        P |= {i["label"]: f"a {i.get('kind', 'ask')} he has not answered: {i['text']}" for i in pending()}
        P |= {f"n{i + 1}": t for i, t in enumerate(S["notes"][-4:])}
        P |= {f"m{i + 1}": s for i, s in enumerate(
            s for s in re.split(r"(?<=\.)\s+", life.get("memory", pname)) if len(s) > 30)}
        if S["last_show"]:
            P["show"] = f"what it printed last: {S['last_show'][-500:]}"
        return {k: v.strip() for k, v in P.items() if v.strip()}

    def resonate(when: str, day: int, material: list[tuple[str, str]], rng: random.Random) -> float:
        """What of this touched something already stirring under his notice. It proposes nothing and
        settles nothing: it says which notions this material feeds and what is the start of one, and
        the arithmetic that follows is code. Most of what a day brings touches nothing at all."""
        th = theta(life.d, when == "night", S["refractory"])
        stuff = "\n\n".join(f"[{s}] {t.strip()[:1400]}" for s, t in material if t and t.strip())
        if not stuff:
            return th
        try:
            got = ask(run, "resonate", "haiku", FIELD_P.format(
                stirring="\n".join(f"{n['id']}: {n['text']}" + (" (already with him)" if n["arrived"] else "")
                                   for n in sorted(S["field"], key=lambda n: -n["a"])[:15]) or "nothing yet",
                material=stuff), FED, thinking=False)["feeds"]
            got = sorted(got, key=lambda f: -int(f.get("strength") or 1))[:6 if when == "night" else 4]
        except Exception as e:   # a resonance that fails costs him the material, not the run
            run.log("field_failed", when=when, error=str(e)[:300])
            return th
        S["field_n"] = feed(S["field"], got, day, S["field_n"])
        run.log("field", day=day, turn=S["turn"], when=when, theta=th,
                feeds=[{k: f.get(k, "") for k in ("notion", "seed", "stream", "strength", "because")} for f in got],
                top=[{"id": n["id"], "text": n["text"], "a": n["a"], "streams": n["streams"]}
                     for n in sorted(S["field"], key=lambda n: -n["a"])[:10]])
        return th

    def arrive(where: str, day: int, n: dict, th: float, rng: random.Random) -> dict | None:
        """It has gathered enough, so he says it. Everything that fed it is handed over shuffled and
        anonymous, to a context that never watched it gather, and on being said it may come to
        nothing. Either way the notion is not spent: it drops well under the threshold and goes on
        gathering, and if it comes round again it has to bring the next thing and not the same one."""
        fed = [x["what"] for x in n["fed"] if x["what"].strip()]
        rng.shuffle(fed)
        before = [i for i in S["ideas"] if i["label"] in n["arrived"]]
        try:
            cands = ask(run, "sift", "sonnet", SIFT_P.format(
                notion=n["text"], holding="\n".join(f"{i}. {x}" for i, x in enumerate(fed)) or n["text"],
                intent=ch.get("intent", ""), refusals=ch.get("refusals", ""), taste=life.taste(),
                why=life.get("stake", pname),
                whys="\n".join(f"- he asked himself: {w['text'][:140]} He answered: {w['answer'][:140]}"
                               for w in S["whys"][-8:]) or "- nothing yet",
                built="\n".join(f"- {q['text'][:160]}" for q in S["reqs"]) or "- nothing yet",
                again=("IT HAS BEEN OUT IN THE OPEN BEFORE. It came to him as this, and this is what he did with it:\n"
                       + "\n".join(f"- {i['text']} [{i['status']}]"
                                   + (f" He said: {i['answer']}" if i.get("answer") else "")
                                   + (f" His reason: {i['why']}" if i.get("why") else "") for i in before)
                       + "\nSaying that again is worth nothing to him. It has gathered more since. Bring the next "
                         "thing it has become: the first small piece of what he took as a direction, or the part the "
                         "last one left unanswered.\n\n") if before else ""), SIFTED)["candidates"]
            got = cands[0] if cands else None
        except Exception as e:   # an arrival that fails costs the idea, not the run
            run.log("arrival_failed", where=where, notion=n["id"], error=str(e)[:300])
            n["a"] = round(n["a"] * 0.5, 3)
            return None
        n["last"] = day
        if not got:
            n["a"] = round(n["a"] * 0.5, 3)   # said out loud it came to nothing, and it sinks back under
            run.log("arrival", day=day, turn=S["turn"], where=where, idea="", again=bool(before),
                    notion={k: n[k] for k in ("id", "text", "a", "streams", "fed")})
            return None
        src = [fed[i] for i in got["from_indexes"] if 0 <= i < len(fed)] or fed
        idea = {"text": got["text"], "kind": got["kind"], "test": got["test"], "status": "pending",
                "label": f"I{len(S['ideas']) + 1}", "might_fail": got["why_it_might_fail"],
                "came_from": " / ".join(x[:220] for x in src[:4]), "where": where, "notion": n["id"]}
        S["ideas"].append(idea)
        n["arrived"].append(idea["label"])
        n["a"] = round(min(n["a"], th * 0.45), 3)
        S["refractory"] = max(S["refractory"], SPACING)
        run.log("arrival", day=day, turn=S["turn"], where=where, idea=idea["label"], again=bool(before),
                notion={k: n[k] for k in ("id", "text", "a", "streams", "fed")})
        run.say(f"   ({CAME[where]}: [{idea['kind']}] {idea['text'][:100]})")
        return idea

    def night_field(day: int, rng: random.Random, caught: dict, sat_today: bool, last: bool):
        """The field settles once a night, and in one place, because the day and the spoon both feed
        it and neither can be feeding it while the other is. What the spoon caught goes in as one
        more stream, alongside his day and his own answers, and then what has gathered enough comes
        to him by morning."""
        S["field"] = cool(S["field"], day)
        S["refractory"] = round(S["refractory"] * COOLING, 3)
        # His own answers are stamped with the day of the run, and the field counts in days of his life.
        mine = ([w["answer"] for w in S["whys"] if w.get("day") == S["day_i"] + 1]
                + [x["answer"] for x in S["directions"] if x.get("day") == S["day_i"] + 1])
        # The gaps go in here and not from the consolidation that wrote them, because the field is one thing
        # and nothing may be adding to it while the day is. A gap is fed the night it is first written, and not again.
        th = resonate("day", day, [("life", life.recent(1, 1200)), ("self", "\n".join(mine)),
                                   ("gap", "\n".join(f"- {g}" for g in S["gaps"] if g not in S["gaps_fed"]))], rng)
        S["gaps_fed"] = list(S["gaps"])   # a gap feeds the field once. Standing unchanged, it is not news
        tried: set[str] = set()
        # A day he gave the project no time is the day a thing can arrive away from it. It waits for his next sitting.
        if not sat_today and not last and (n := ignite(S["field"], th, rng)):
            tried.add(n["id"])
            arrive("away", day, n, th, rng)
        if not caught:
            return
        th = resonate("night", day, [("night", "\n".join(
            "- " + ln["text"] + (f" ({ln['mechanism']})" if ln.get("mechanism") else "")
            for ln in caught["links"]))], rng)
        arrivals = []
        for _ in range(1 + min(3, poisson(rng, 1.3))):
            n = None if last else ignite([x for x in S["field"] if x["id"] not in tried], th, rng)
            if n is None:
                break
            tried.add(n["id"])
            if got := arrive("woke", day, n, th, rng):
                arrivals.append(got)
            th = theta(life.d, True, S["refractory"])
        run.log("spoon", motifs=caught["motifs"], caught=len(caught["links"]), kept=len(arrivals),
                candidates=arrivals, elements=caught["elements"],
                links=[{k: ln.get(k) for k in ("kind", "text", "anchors", "other", "mechanism")}
                       for ln in caught["links"]])
        run.say(f"   (the spoon fell: {len(caught['links'])} links caught, {len(arrivals)} with him by morning"
                + (": " + ", ".join(g["kind"] for g in arrivals) if arrivals else "") + ")")

    def spoon(rng: random.Random, out: dict):
        """Saturate, drift, catch. None of it is him, and he is asked nothing. What it catches is not
        judged here and nothing is kept for the morning off one night's work: it goes into the field
        as one more stream, to be weighed against everything else that has been feeding him."""
        P = held()
        ptxt = "\n".join(f"{k}: {v[:400]}" for k, v in P.items())
        sat = ask(run, "saturate", "haiku", SATURATE_P.format(project=ptxt, life=life.recent(8, 500),
                                                              why=life.get("stake", pname)), MOTIFS)
        motifs = "\n".join(f"- {m}" for k in ("motifs", "tensions", "questions") for m in sat[k])
        S["tensions"] = sat["tensions"][:3]   # the nights feed his life, not only the project: one may open a thread
        lean = f"{'opportunity' if stance() > 0 else 'risk'}-weighted {stance():+.2f}"
        # Drift runs more than once, on different models over different days, because one sampler has one groove.
        passes = [(m, int(clip(rng.gauss(16, 4), 8, 26)), life.sample(rng, int(clip(rng.gauss(10, 3), 5, 18))),
                   random.Random(rng.random())) for m in ("sonnet", "haiku")]
        holding: list[dict] = []

        def drift(model, target, days_txt, r):
            got = ask(run, "drift", model, DRIFT_P.format(target=target, motifs=motifs, project=ptxt, stance=lean,
                                                           bible=life.bible[:6000], days=days_txt), LINKS)["links"]
            caught = catch(got, set(P), r)
            run.log("drift", model=model, asked=target, written=len(got), caught=len(caught))
            holding.extend(caught)
        jobs = [threading.Thread(target=drift, args=p) for p in passes]
        for j in jobs:
            j.start()
        for j in jobs:
            j.join()
        rng.shuffle(holding)   # what reads the links next must not be able to tell the passes apart
        S["counts"]["cycles"] += 1
        out |= {"motifs": sat, "links": holding, "elements": P}

    def step_back(day: int, rng: random.Random):
        """Not a review of the work. Time away from it, where the only thing on him is why he wanted
        it, which is the one thing nothing else in the run ever asks. The counters come last on purpose:
        given them first he writes process rules, and process rules then ride on every message he sends."""
        sit = run.rows("sitting")
        view = {"sittings": S["turn"], "days": S["day_i"] + 1, "minutes_you_gave_each": [x.get("minutes") for x in sit],
                "days_with_no_time": S["counts"]["empty_days"], "times_you_tried_it": S["counts"]["looks"],
                "trust_in_the_builder": round(S["trust"], 2), "directed": S["counts"]["direct"],
                "challenged": S["counts"]["challenge"], "constrained": S["counts"]["constrain"],
                "checks_failed": sum(1 for x in run.rows("check") if not x["ok"]),
                "requirements": len(S["reqs"]), "requirements_built": sum(1 for q in S["reqs"] if q["status"] == "built"),
                "requirements_per_sitting": [len(x.get("new") or []) for x in sit],
                "ideas_you_woke_with": len(S["ideas"]), "ideas_taken": sum(1 for i in S["ideas"] if i["status"] == "taken"),
                "ideas_declined": [{"idea": i["text"][:80], "why": i.get("why", "")}
                                   for i in S["ideas"] if i["status"] in {"declined", "set aside"}],
                "limits_you_changed": S["amended"], "times_you_asked_where_it_was_up_to": S["counts"]["asks"],
                "assumptions_you_found_that_did_not_hold": [x["assumption"][:120] for x in S["assumptions"] if not x["holds"]], "fresh_builder_sessions": S["counts"]["fresh"],
                "builder_minutes": round(S["claude_secs"] / 60, 1), "your_minutes": round(S["blocking"] / 60, 1),
                "ideas_you_answered": len(S["whys"]), "where_you_said_you_want_it_to_go": [x["text"] for x in S["directions"]],
                "ways_now": S["ways"]}
        older = S["stakes"][:-1]
        t = time.time()
        got = ask(run, "step_back", a.regent_model, STEP_P.format(
            why=life.get("stake", pname),
            earlier=("WHY YOU SAID YOU WANTED IT BEFORE, oldest first\n"
                     + "\n\n".join(f"day {x['day']}: {x['text']}" for x in older) + "\n\n" if older else ""),
            picture=("HOW YOU UNDERSTAND THE THING, in your own terms\n" + life.get("picture", pname) + "\n\n"
                     + ("AND WHAT YOU KNOW YOU DO NOT UNDERSTAND ABOUT WHAT IT IS FOR\n"
                        + "\n".join(f"- {g}" for g in S["gaps"]) + "\n\n" if S["gaps"] else "")
                     if life.get("picture", pname) else ""),
            days=life.sample(rng, 3, 700) or "nothing written down yet",
            taken="\n\n".join(r["taken"] for r in S["records"][-4:] if r.get("taken")) or "nothing yet",
            not_followed="\n".join(f"- {x}" for x in S["not_followed"]) or "- nothing you are still wondering about",
            whys="\n".join(f"- {w['text']} You said: {w['answer']}" for w in S["whys"][-6:]) or "- nothing yet",
            view=json.dumps(view, indent=1, ensure_ascii=False)), STEPBACK, system())
        S["blocking"] += time.time() - t
        S["ways"] = got["ways"][:3]
        S["human_notes"].extend(got["notes_for_the_human"])
        S["counts"]["step_backs"] += 1
        S["since_step"] = 0
        moved = bool(got["why_now"].strip()) and got["why_now"].strip() != life.get("stake", pname)
        if moved:
            life.put("stake", pname, got["why_now"].strip())
        S["stakes"].append({"day": day, "turn": S["turn"], "text": life.get("stake", pname),
                            "could_become": got["could_become"], "follows": got["follows"]})
        run.log("stake", **S["stakes"][-1])
        run.log("step_back", view=view, observations=got["observations"], ways=S["ways"],
                notes=got["notes_for_the_human"], why_now=S["stakes"][-1]["text"],
                could_become=got["could_become"], follows=got["follows"])
        run.say(f"   (stepped back: {len(got['observations'])} observations, {len(S['ways'])} ways. The why "
                f"{'moved' if moved else 'held'}: {S['stakes'][-1]['text'][:110]})")

    def tonight(name: str, fn, *args) -> threading.Thread:
        def go():
            try:
                fn(*args)
            except Exception as e:   # a night that fails costs nothing and must not end the run
                run.log(f"{name}_failed", error=str(e)[:300])
                run.say(f"   ({name} failed: {str(e)[:120]})")
        return threading.Thread(target=go)

    if a.watch:
        watch_cmd(a, root, background=True)
    run.log("start", project=pname, owner=S["owner"], days=days, turns_per_day=tpd, seed=a.seed, resumed=not fresh)
    run.say(f"regent: {life.root.name} on {project}, {days} days at about {tpd:g} sittings a day, run {root}")
    while S["day_i"] < days:
        rng = random.Random(f"{a.seed}-{S['day_i']}")
        day = life.days() + 1
        S["mood"] = clip(0.6 * S["mood"] + rng.gauss(0, 0.35))
        failing = bool(S["last_check"]) and not S["check_ok"]
        # A failed check pulls him back. A thing he is content with, that has gone quiet, lets him drift away.
        n = poisson(rng, tpd * (1.6 if failing else 1.0) * 0.6 ** S["dry"])
        n = max(n, 1) if S["turn"] == 0 else n
        run.log("dawn", day=day, mood=round(S["mood"], 2), sittings=n)
        met = ""
        if plant_file.exists() and (lines := [x for x in plant_file.read_text().splitlines() if x.strip()]):
            met = lines[0]
            plant_file.write_text("\n".join(lines[1:]) + "\n")
            run.log("plant", human_only=True)
        if not n:
            S["counts"]["empty_days"] += 1
            S["idle"] += 1
            run.say(f"day {day}: no time for the project.")
        seen = [sitting(day, rng, met if k == 0 else "") for k in range(n)]

        # Night. The day gets written, the project is half forgotten, and sometimes the spoon falls.
        t = time.time()
        S["since_dream"] += 1
        S["since_step"] += 1
        last = S["day_i"] + 1 >= days
        caught: dict = {}
        jobs = [tonight("day", write_day, day, rng, seen, met)]
        if to_remember():
            jobs.append(tonight("memory", consolidate, day))
        if S["built_once"] and not pending() and not last and due(rng, S["since_dream"], a.dream_gap * (1 - 0.5 * life.d("curious"))):
            S["since_dream"] = 0
            jobs.append(tonight("spoon", spoon, random.Random(rng.random()), caught))
        for j in jobs:
            j.start()
        for j in jobs:
            j.join()
        # The field settles after them and not beside them: the day that was just written and the links the
        # spoon just caught both feed it, and it is one thing, so nothing may be adding to it twice at once.
        tonight("field", night_field, day, rng, caught, bool(seen), last).run()
        if S["turn"] and (last or due(rng, S["since_step"], 7 * (1 + 0.4 * life.d("patient")))):
            tonight("step_back", step_back, day, rng).run()
        # A builder's session grows stale with every turn in it, so the odds of a fresh pair of hands grow too.
        if not last and S["started"] and life.get("memory", pname) and due(rng, S["session_turns"], 9):
            S["session"], S["started"], S["session_turns"] = str(uuid.uuid4()), False, 0
            S["counts"]["fresh"] += 1
            S["handover"] = ("You are picking this project up. This is what is remembered of the work so far, and it is a "
                             "memory, so parts are missing:\n\n" + life.get("memory", pname) +
                             "\n\nRead the files in this folder before you change anything.\n\n")
            run.say("   (a fresh builder picks it up in the morning, from his memory of it)")
        S["blocking"] += time.time() - t
        S["day_i"] += 1
        run.save(S)

    S["finished"] = True
    run.save(S)
    wall = time.time() - run.t0
    calls = run.rows("call")
    spend = {k: sum(x.get("cost", 0) for x in calls if (x["role"] in ("claude", "answer", "readback")) == (k == "builder"))
             for k in ("builder", "owner")}
    night_usd = sum(x.get("cost", 0) for x in calls if x["role"] in ("saturate", "drift", "sift", "resonate"))
    built = sum(1 for q in S["reqs"] if q["status"] == "built")
    dreamt = sum(1 for q in S["reqs"] if q["from_dream"])
    c = S["counts"]
    spent = (f"{S['turn']} sittings over {days} days of his life, in {wall / 60:.1f} minutes. The builder worked for "
             f"{S['claude_secs'] / 60:.1f} of them. Spend: builder ${spend['builder']:.2f}, owner and his nights "
             f"${spend['owner']:.2f}, of which the spoon cycles were ${night_usd:.2f}. The check "
             f"{'passes' if S['check_ok'] else 'FAILS'}.")
    did = (f"He directed {c['direct']} times, challenged {c['challenge']}, constrained {c['constrain']}, tried it himself "
           f"{c['looks']} times, asked where it was up to {c.get('asks', 0)} times and had {c['empty_days']} days with no time for it. The spoon fell on {c['cycles']} nights, "
           f"he stepped back {c['step_backs']} times, and a fresh builder picked it up {c['fresh']} times. Trust in the "
           f"builder ended at {S['trust']:.2f}.")
    sits = [x for x in run.rows("sitting") if "borrowed" in x]
    bs = [x["borrowed"] for x in sits] or [0.0]
    asked_first = sum(1 for x in run.rows("readback") if x["questions"])
    crossing = (f"Of the words he used, {bs[0]:.0%} were the builder's and nowhere in his own life on the first sitting and "
                f"{bs[-1]:.0%} on the last, {sum(bs) / len(bs):.0%} over the run, with "
                f"{sum(x['codeish'] for x in sits) / max(1, len(sits)):.1f} code-like tokens a message. He ended owning "
                f"{len(S['words'])} words of the builder's trade"
                + (": " + ", ".join(w["word"] for w in S["words"]) if S["words"] else "") + ". The builder said his wants "
                f"back to him {c['readbacks']} times before building them, and asked him something first "
                f"{asked_first} of those.")
    kinds = {"ask": "asks", "doubt": "doubts", "wish": "wishes", "worry": "worries"}
    by_kind = {k: sum(1 for i in S["ideas"] if i.get("kind", "ask") == k) for k in kinds}
    moved = sum(1 for a_, b in zip(S["stakes"], S["stakes"][1:]) if a_["text"] != b["text"])
    nights = (f"The nights brought {len(S['ideas'])} things" + (": " + ", ".join(
        f"{v} {k if v == 1 else kinds[k]}" for k, v in by_kind.items() if v) if S["ideas"] else "")
        + f". He took {sum(1 for i in S['ideas'] if i['status'] == 'taken')}, answered {len(S['whys'])} in his own words "
        f"and turned down {sum(1 for i in S['ideas'] if i['status'] in ('declined', 'set aside'))}. He said why he wanted "
        f"this {len(S['stakes'])} times over the run, and it moved on {moved} of them.")
    appetite_line = (f"It had stopped surprising him on {S['same']:.0%} of his sittings by the end, and on "
                     f"{c.get('pushes', 0)} of them he pushed: the checking left with the builder and his hour spent "
                     f"on what the thing is for and where it could go. He put {len(S['escalations'])} questions to you "
                     f"and was still waiting on {sum(1 for e in S['escalations'] if not e.get('answered'))} of them.")
    lines = [f"# {project.name}", "", spent, "", did, "", crossing, "", nights, "", appetite_line, "",
             f"## Requirements: {built} built of {len(S['reqs'])}, {dreamt} from the nights", ""]
    lines += [f"- {q['id']} \"{q.get('name') or q['id']}\" [{q['status']}] sitting {q['turn']}"
              f"{' (night)' if q['from_dream'] else ''}: {q['text']}"
              + (f"\n  he would notice: {q['notice']}" if q.get("notice") else "")
              + (f"\n  the builder took it as: {q['spec']}" if q.get("spec") else "")
              for q in S["reqs"]] or ["- none"]
    lines += ["", "## Why he wants it, and how that moved", ""]
    prev: dict = {}   # an hour away where nothing moved is a line, not the whole thing said again
    for x in S["stakes"]:
        when = f"day {x['day']}" if x["day"] else "before it started"
        lines.append(f"- {when}: it held." if x["text"] == prev.get("text") else f"- {when}: {x['text']}")
        for key, label in (("could_become", "where it could go"), ("follows", "what follows if it works")):
            if x.get(key) and x[key] != prev.get(key):
                lines.append(f"  {label}: {x[key]}")
        prev = x
    lines += ["", "## Where he wants it to go", ""] + (
        [f"- day {x['day']}: {x['text']}\n  what it would mean to him: {x['answer']}" for x in S["directions"]] or ["- nothing yet"])
    arrivals = run.rows("arrival")
    each = {w: sum(1 for x in arrivals if x["where"] == w and x["idea"]) for w in CAME}
    twice, seen_ids = 0, set()
    for x in arrivals:
        if x["idea"]:
            twice += int(x["notion"]["id"] in seen_ids)
            seen_ids.add(x["notion"]["id"])
    field = (f"{S['field_n']} things stirred under his notice over the run, fed a piece at a time from his days, his "
             f"reading, the thing itself and the nights. {sum(each.values())} of them came to him: {each['woke']} on "
             f"waking, {each['sitting']} at the desk and {each['away']} away from the work. {twice} came round a "
             f"second time, having gathered more in between, and "
             f"{sum(1 for x in arrivals if not x['idea'])} came to nothing on being said.")
    lines += ["", "## What was stirring", "", field, "", "The three strongest still stirring at the end:", ""] + (
        [f"- {n['text']} ({n['a']:.1f}, from {', '.join(n['streams'])})"
         for n in sorted(S["field"], key=lambda n: -n["a"])[:3]] or ["- nothing"])
    lines += ["", "## What the nights brought, and what he did with it", ""] + (
        [f"- [{i.get('kind', 'ask')}, {i['status']}" + (f", {CAME[i['where']]}" if i.get("where") in CAME else "")
         + f"] {i['text']}"
         + (f"\n  he answered: {i['answer']}" if i.get("answer") else "")
         + f"\n  from: {i.get('came_from', '')}\n  it might fail because: {i.get('might_fail', '')}"
         + (f"\n  he {'set it aside for now' if i['status'] == 'set aside' else 'declined it'}: {i['why']}" if i.get("why") else "") for i in S["ideas"]] or ["- nothing"])
    lines += ["", "## What the builder took for granted", ""] + (
        [f"- sitting {x['turn']} [{'holds' if x['holds'] else 'does not hold'}] {x['assumption']}. {x['why']}"
         for x in S["assumptions"]] or ["- nothing surfaced"])
    lines += ["", "## Limits he changed", ""] + (
        [f"- sitting {x['turn']}: was \"{x['constraint']}\", now \"{x['now']}\". Why: {x['why']}" for x in S["amended"]]
        or ["- none"])
    lines += ["", "## Questions for you", ""] + (
        [f"- sitting {e['turn']}{'' if e.get('answered') else ', still waiting'}: {e['question']}"
         for e in S["escalations"]] or ["- none"])
    lines += ["", "## His ways of working", ""] + ([f"- {w}" for w in S["ways"]] or ["- none"])
    lines += ["", "## His notes for you", ""] + ([f"- {n}" for n in S["human_notes"]] or ["- none"])
    lines += ["", "## How he understands the thing", "", life.get("picture", pname) or "nothing yet"]
    lines += ["", "## What he knows he does not understand", ""] + ([f"- {g}" for g in S["gaps"]] or ["- nothing"])
    lines += ["", "## What he remembers of the project", "", life.get("memory", pname)]
    (root / "digest.md").write_text("\n".join(lines) + "\n")
    run.log("summary", sittings=S["turn"], days=days, spend=spend, spoon_usd=round(night_usd, 2), check_ok=S["check_ok"],
            trust=round(S["trust"], 2), requirements=len(S["reqs"]), built=built, from_nights=dreamt, counts=c)
    run.say(f"stopped after {S['turn']} sittings in {days} days. wall {wall / 60:.1f} min. spend ${sum(spend.values()):.2f} "
            f"(spoon ${night_usd:.2f}). check {'passed' if S['check_ok'] else 'FAILED'}. requirements {built} of "
            f"{len(S['reqs'])}, {dreamt} from the nights. limits changed {len(S['amended'])}.")
    run.say(f"digest: {root / 'digest.md'}")
    life.close()
    run.close()


def main():
    ap = argparse.ArgumentParser(prog="regent", description="A simulated owner who governs a project.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="run a project, new or existing, starting or resuming")
    r.add_argument("charter", nargs="?", help="default: <project>/.regent/charter.md")
    r.add_argument("--project", required=True)
    r.add_argument("--owner", default="piotr-mahon", help="an owner name or a path to an owner folder")
    r.add_argument("--days", type=int, default=None, help="how many days of his life the run lasts. Charter: 'days:'")
    r.add_argument("--turns-per-day", type=float, default=None,
                   help="mean sittings a day, the mean of a Poisson draw, so 0.5 is every other day. Charter: 'turns_per_day:'")
    r.add_argument("--dream-gap", type=float, default=3.0, help="mean nights between spoon cycles. His curiosity shortens it")
    r.add_argument("--runs", default=None, help=f"where runs live. Default {HOME / 'runs'}")
    r.add_argument("--new", action="store_true", help="start a new run instead of resuming the last one")
    r.add_argument("--seed", type=int, default=1)
    r.add_argument("--model", default="sonnet", help="the builder")
    r.add_argument("--regent-model", default="sonnet")
    r.add_argument("--effort", default="low")
    r.add_argument("--timeout", type=int, default=600, help="seconds for the charter's Check and Show commands")
    r.add_argument("--plant", action="append", default=[], help="something he comes across. He never learns it was yours")
    r.add_argument("--watch", action="store_true", help="open the live page in a browser while it runs")
    r.add_argument("--port", type=int, default=0, help="port for --watch. Default: any free one")
    w = sub.add_parser("watch", help="a live page of a run: his days, his sittings, the nights, the project growing")
    w.add_argument("run", nargs="?", help="a run folder or a project name. Default: the newest run")
    w.add_argument("--port", type=int, default=8642)
    w.add_argument("--export", help="write the page to this file with the run inside it, and do not serve")
    c = sub.add_parser("cast", help="roll a new owner")
    c.add_argument("--pin", action="append", default=[], help="a fact in words: 'a lock keeper', 'impatient, generous'")
    c.add_argument("--dial", action="append", default=[], help=f"set a dial instead of rolling it, e.g. bold=0.6. {', '.join(DIALS)}")
    c.add_argument("--name", default=None, help="folder name. Default: their own")
    c.add_argument("--seed", type=int, default=int(time.time()))
    c.add_argument("--model", default="sonnet")
    for name, helptext in (("say", "leave him a note, shown at his next sitting"),
                           ("plant", "something he comes across, never traced to you")):
        s = sub.add_parser(name, help=helptext)
        s.add_argument("run")
        s.add_argument("text")
    j = sub.add_parser("journal", help="read an owner's life")
    j.add_argument("owner")
    j.add_argument("--last", type=int, default=5)
    a = ap.parse_args()
    if a.cmd == "run":
        return run_cmd(a)
    if a.cmd == "cast":
        return cast_cmd(a)
    if a.cmd == "watch":
        return watch_cmd(a)
    if a.cmd == "journal":
        life = Life(owner_dir(a.owner))
        print(f"# {life.root.name}, day {life.days()}\n\n{life.recent(a.last, 4000)}"
              f"\n\n## What is hanging over him\n\n{life.thread_lines()}")
        return 0
    target = Path(a.run).expanduser() / ("inbox.md" if a.cmd == "say" else "plant.md")
    if not target.parent.is_dir():
        raise SystemExit(f"no run at {target.parent}")
    with target.open("a") as f:
        f.write(a.text.strip() + "\n")
    print(f"written to {target}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
