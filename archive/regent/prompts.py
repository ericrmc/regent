"""Prompt files, one per state, filled by literal substitution of {{name}}.

Each state of the super-orchestrator is a prompt file the harness fills. It has
no tools and no slash commands, so a skill gives it nothing.
"""

from __future__ import annotations

import re
from pathlib import Path

_PLACEHOLDER = re.compile(r"\{\{([a-z0-9_]+)\}\}")


class Prompts:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self._cache: dict[str, str] = {}

    def text(self, name: str) -> str:
        if name not in self._cache:
            path = self.root / f"{name}.md"
            if not path.exists():
                raise FileNotFoundError(f"no prompt file at {path}")
            self._cache[name] = path.read_text()
        return self._cache[name]

    def placeholders(self, name: str) -> set[str]:
        return set(_PLACEHOLDER.findall(self.text(name)))

    def fill(self, name: str, /, **values) -> str:
        """`self` and `name` are positional only, because the wake prompt has a
        placeholder named `self` and a keyword of that name has to reach values.
        """
        text = self.text(name)
        for key, value in values.items():
            text = text.replace("{{" + key + "}}", "" if value is None else str(value))
        left = _PLACEHOLDER.findall(text)
        if left:
            raise KeyError(f"prompt {name} left unfilled: {sorted(set(left))}")
        return text


SYSTEM_JSON = (
    "You return one JSON object that matches the schema you were given. "
    "You return nothing else, no preamble and no code fence."
)

SYSTEM_OWNER = (
    "You are the owner of this project's intent. You hold a mission, not a ticket. "
    "You have no tools. You read no source and you write no files. "
    "You return one JSON object that matches the schema you were given, and the harness applies it. "
    "You return nothing else, no preamble and no code fence."
)
