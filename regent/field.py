"""The field: the arithmetic under his notice, and none of it decides anything.

Notions gather, are fed a piece at a time from wherever material comes from, leak
every night, and one of them crosses into the open when it has gathered enough.
The constants were set against the feeds of real runs rather than derived, so
they are all here, in one place, with what each one is for beside it. What the
crossing means is said by `night.arrive`; nothing here calls a model.
"""
from __future__ import annotations

import difflib
import random

from regent.dice import clip

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

SAMENESS = 0.5   # the weight of the newest sitting in the running average of how same it all is
STALE, SURE, UNSURE = 0.5, 0.6, 0.4   # when sameness counts as high, and the two ends of trust


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
