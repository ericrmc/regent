"""Every prompt the harness sends, one file per prompt, loaded by name.

A prompt is a `.md` file beside this one, holding the text exactly as it goes
down the wire. `{braces}` in it are `str.format` placeholders, so a literal
brace is doubled, the same as it was when these were Python literals. Where a
prompt is assembled from runtime pieces the assembly stays in the code that
knows the pieces, and only the constant text lives here.

`load` strips the file's final newline, so a prompt that must end in a space or
mid-sentence keeps ending that way. UNSEEN is the one text with a trailing
space, and the space is added here rather than left invisible at the end of a
file.
"""
from __future__ import annotations

from functools import cache
from pathlib import Path

HERE = Path(__file__).resolve().parent


@cache
def load(name: str) -> str:
    text = (HERE / f"{name}.md").read_text()
    return text.removesuffix("\n")


def names() -> list[str]:
    """Every prompt there is, for the test that proves they all still parse."""
    return sorted(p.stem for p in HERE.glob("*.md"))


# Every call that is not the builder replaces Claude Code's system prompt. This is what the night runs get.
# The CLI puts today's date, the human's email and the machine into every call. That is the machinery's and not the
# owner's, and no stage may let it in. On an API key --bare leaves it out; on a login one sentence has to do.
UNSEEN = load("unseen") + " "
PLAIN = UNSEEN + load("plain")
