"""The wall between the builder's words and the owner's, and the gauge on it.

Nothing here calls a model. `crossed` is how a reading reaches him once a model
has made it; `words`, `gauge` and `plain_english` measure how far his own words
have drifted into the builder's; `unmark` and `places_named` are the two places
the day writer's plain text is cut up. The crossing itself, the call that reads
the builder for him, is `owner.take`.
"""
from __future__ import annotations

import difflib
import re
import sqlite3
from pathlib import Path

from regent import HOME, OWNERS

# Bold, bulleted or headed, a mark is still a mark: "**THREAD 1:**" went into two of his entries as prose.
MARK = re.compile(r"^[ \t*_#>-]*(THREAD 1|THREAD 2|NEW|PROJECT)[ \t*_]*:[ \t*_]*(.+?)[ \t*_]*$", re.M)
NAMEY = re.compile(r"(?<![.!?]\s)(?<!^)\b[A-Z][a-z]{2,}\b", re.M)
WORDS = re.compile(r"[a-z][a-z'\-]{3,}")
CODEISH = re.compile(r"`[^`]+`|\b\w+_\w+\b|\breq-\d+\b|\b[\w/]+\.(?:py|md|json|txt|html|sh|toml|ya?ml|cfg|ini)\b")


def shares_a_name(a: str, b: str) -> bool:
    """Cheap and good enough: one thing puts him in mind of another when the same person or place
    is in both. A capitalised word that does not start a sentence is a name often enough."""
    return bool(set(NAMEY.findall(a)) & set(NAMEY.findall(b)))


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


def opening(text: str, n: int = 8) -> list[str]:
    """The first few words of an entry, past any date or day number the writer put at the top."""
    return re.findall(r"\w+", re.sub(r"^\W*(\d{4}-\d\d-\d\d|day \d+)\W*", "", text.lower().strip()))[:n]


def echoes(text: str, before: list[str]) -> bool:
    """Whether an entry opens the way one of the last few did. Measured, never shown: the writer
    told "do not open like this" and handed the opening copied it into some twenty-five entries."""
    o = opening(text)
    return any(o[:3] == (b := opening(x))[:3] or difflib.SequenceMatcher(None, o, b).ratio() >= 0.6 for x in before)


def crossed(t: dict) -> str:
    """A reading as it reaches him: what he took, and the two honest edges of it."""
    return (t["taken"].strip()
            + ("\nWhat you did not follow: " + "; ".join(t["not_followed"]) if t["not_followed"] else "")
            + ("\nWhat you did not get to: " + t["not_reached"] if t["not_reached"].strip() else ""))


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
    for base in (HOME / "owners", OWNERS):
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
