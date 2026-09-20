"""The one source of randomness in the run.

A model asked to be random returns its favourite few answers, so every draw is
made here. The seed is logged and the draw counter is saved, so a stopped run
resumes on the same stream and a finished run replays.
"""

from __future__ import annotations

import hashlib
import random
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Rng:
    seed: int
    draws: int = 0
    _r: random.Random = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._r = random.Random(self.seed)
        for _ in range(self.draws):
            self._r.random()

    def random(self) -> float:
        self.draws += 1
        return self._r.random()

    def uniform(self, low: float, high: float) -> float:
        return low + (high - low) * self.random()

    def randint(self, low: float, high: float) -> int:
        """Inclusive on both ends."""
        span = int(high) - int(low) + 1
        return int(low) + int(self.random() * span) % span

    def choice(self, items: Sequence[Any]) -> Any:
        if not items:
            raise ValueError("choice from an empty sequence")
        return items[self.randint(0, len(items) - 1)]

    def sample(self, items: Sequence[Any], k: int) -> list[Any]:
        pool = list(items)
        k = max(0, min(k, len(pool)))
        out = []
        for _ in range(k):
            out.append(pool.pop(self.randint(0, len(pool) - 1)))
        return out

    def shuffled(self, items: Sequence[Any]) -> list[Any]:
        return self.sample(items, len(items))

    def weighted(self, weights: dict[str, float]) -> str:
        """Draw one key. Weights need not sum to one."""
        keys = sorted(weights)
        total = sum(max(0.0, weights[k]) for k in keys)
        if total <= 0:
            raise ValueError("weights must include one positive value")
        point = self.random() * total
        running = 0.0
        for key in keys:
            running += max(0.0, weights[key])
            if point < running:
                return key
        return keys[-1]

    def chance(self, probability: float) -> bool:
        return self.random() < probability

    def substream(self, label: str) -> Rng:
        """A generator derived from this seed and a label.

        Draws for one return must not depend on which other child happened to
        finish first, so each return draws from its own stream rather than from
        the shared counter.
        """
        digest = hashlib.sha256(f"{self.seed}:{label}".encode()).hexdigest()
        return Rng(seed=int(digest[:12], 16))

    def state(self) -> dict:
        return {"seed": self.seed, "draws": self.draws}

    @classmethod
    def from_state(cls, data: dict) -> Rng:
        return cls(seed=int(data["seed"]), draws=int(data.get("draws", 0)))
