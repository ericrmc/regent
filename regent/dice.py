"""The draws. Nothing in a life runs on a count, so this is where the counts would be.

Pure functions over a `random.Random` and a disposition: how a day goes, which
of the things hanging over him comes up and what happens to it, how many
sittings the project gets, and whether a thing that has not happened for a while
is due tonight. A hazard rather than a schedule, everywhere, so the longer since
a thing last happened the likelier it is now.
"""
from __future__ import annotations

import math
import random
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from regent.life import Life

DIALS = ("bold", "curious", "patient", "trusting", "thorough", "stubborn", "restless")

DIAL_WORDS = {   # each dial as behaviour, low end then high end
    "bold": ("hang back until they are sure", "take a run at a thing before it is settled"),
    "curious": ("let an odd thing go by", "notice an odd thing and go and find out about it"),
    "patient": ("want it done now", "will wait a thing out"),
    "trusting": ("check behind people", "take people at their word"),
    "thorough": ("do enough and stop", "go over it twice"),
    "stubborn": ("give way when pushed", "dig in and will not be moved"),
    "restless": ("can sit still", "cannot sit still"),
}

# How a person keeps a journal, and how many of them keep it that way. Most people who write a day down are
# getting it off their chest or telling it in order; few write it the way a novelist's notebook does. Each is
# a prompt file, register_<name>.md, because the writer follows an example far better than a list of adjectives.
# Each is how many keep it that way, and how long they write against the ordinary day.
REGISTERS = {"unload": (0.45, 1.2), "account": (0.35, 1.0), "terse": (0.2, 0.5)}

TURNS = ("and it goes better than it might have", "and it goes as badly as it could",
         "and it goes sideways, neither one thing nor the other")
MOVES = ("toward", "turns", "against", "ends")


def in_words(life: Life) -> str:
    """The disposition as things a person does, never as a trait named. A journal that says he is
    curious is not a journal, which is why the day writer was never given the dials until now."""
    out = []
    for k, (lo, hi) in DIAL_WORDS.items():
        v = life.d(k)
        if abs(v) >= 0.2:
            out.append(f"- {'Almost always' if abs(v) > 0.6 else 'More often than not'}, they {hi if v > 0 else lo}.")
    return "\n".join(out) or "- Nothing marked strongly either way."


def roll_register(rng: random.Random) -> str:
    return rng.choices(list(REGISTERS), weights=[w for w, _ in REGISTERS.values()])[0]


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
