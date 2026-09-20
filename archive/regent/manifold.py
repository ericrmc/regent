"""The super-orchestrator's working experience.

Written continuously, never summarised, read whole while warm. Every element
carries an id, a timestamp and a texture tag. Ids are how a later claim proves
it came from lived material rather than from invention.
"""

from __future__ import annotations

import json
import time
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field

from .store import Store


@dataclass
class Element:
    id: str
    ts: float
    texture: str
    text: str
    cycle: int = 0
    citations: int = 0
    last_cited_cycle: int = 0
    source: str = ""
    synthetic: bool = False
    meta: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> Element:
        known = {f: d.get(f) for f in cls.__dataclass_fields__ if f in d}
        known.setdefault("meta", d.get("meta") or {})
        return cls(**known)


class ManifoldStore:
    def __init__(self, store: Store, cfg) -> None:
        self.store = store
        self.cfg = cfg

    def _load(self, path) -> list[Element]:
        return [Element.from_dict(d) for d in self.store.read_jsonl(path)]

    def warm(self) -> list[Element]:
        return self._load(self.store.warm)

    def cold(self) -> list[Element]:
        return self._load(self.store.cold)

    def _save_warm(self, elements: Iterable[Element]) -> None:
        self.store.rewrite_jsonl(self.store.warm, [e.to_dict() for e in elements])

    def _save_cold(self, elements: Iterable[Element]) -> None:
        self.store.rewrite_jsonl(self.store.cold, [e.to_dict() for e in elements])

    def next_id(self, texture: str = "") -> str:
        """A life element's id begins with L, a project element's with m.

        The groundedness floor counts project anchors only, so the prefix is
        what stops a link anchored purely in the life from passing. Nothing in
        the life is evidence.
        """
        n = len(self.warm()) + len(self.cold()) + 1
        return f"{'L' if texture == 'life' else 'm'}{n:05d}"

    def write(self, texture: str, text: str, cycle: int = 0, source: str = "",
              synthetic: bool = False, meta: dict | None = None) -> Element:
        text = (text or "").strip()
        if not text:
            raise ValueError("a manifold element needs text")
        if texture not in self.cfg.manifold.textures:
            texture = "friction"
        el = Element(
            id=self.next_id(texture),
            ts=time.time(),
            texture=texture,
            text=text,
            cycle=cycle,
            last_cited_cycle=cycle,
            source=source,
            synthetic=synthetic,
            meta=meta or {},
        )
        self.store.append_jsonl(self.store.warm, el.to_dict())
        return el

    def write_many(self, notes: Iterable[dict], cycle: int = 0, source: str = "",
                   synthetic: bool = False) -> list[Element]:
        out = []
        for note in notes or []:
            text = (note.get("text") or "").strip()
            if not text:
                continue
            out.append(self.write(note.get("texture") or "friction", text, cycle=cycle,
                                  source=source, synthetic=synthetic,
                                  meta=note.get("meta") or {}))
        return out

    def cite(self, ids: Iterable[str], cycle: int) -> list[str]:
        """A citation keeps an element warm. A cold element cited comes back."""
        wanted = {i for i in ids if i}
        if not wanted:
            return []
        warm = self.warm()
        cold = self.cold()
        touched = []
        for el in warm:
            if el.id in wanted:
                el.citations += 1
                el.last_cited_cycle = cycle
                touched.append(el.id)
        returning = [el for el in cold if el.id in wanted]
        for el in returning:
            el.citations += 1
            el.last_cited_cycle = cycle
            touched.append(el.id)
        if returning:
            back = {el.id for el in returning}
            self._save_cold([el for el in cold if el.id not in back])
            warm = warm + returning
        self._save_warm(warm)
        return touched

    def decay(self, cycle: int) -> list[str]:
        """An element goes cold by decay, N cycles uncited. Refusals never decay."""
        warm = self.warm()
        keep, cooled = [], []
        for el in warm:
            if el.texture in self.cfg.manifold.protected_textures:
                keep.append(el)
            elif cycle - el.last_cited_cycle >= self.cfg.manifold.decay_cycles:
                cooled.append(el)
            else:
                keep.append(el)
        if len(keep) > self.cfg.manifold.warm_cap:
            keep.sort(key=lambda e: (e.texture in self.cfg.manifold.protected_textures,
                                     e.last_cited_cycle, e.ts))
            overflow = len(keep) - self.cfg.manifold.warm_cap
            cooled.extend(keep[:overflow])
            keep = keep[overflow:]
        if cooled:
            self._save_warm(keep)
            for el in cooled:
                self.store.append_jsonl(self.store.cold, el.to_dict())
        return [e.id for e in cooled]

    def forget(self, rng, cycle: int) -> list[str]:
        """The forgetting pass. Warm elements drop by age and citation count.

        Forgetting is what makes the agent re-encounter its own system as a
        reader rather than as its author. It is also how the context stays
        affordable. The draw is the harness's, never the model's.
        """
        m = self.cfg.manifold
        warm = self.warm()
        keep, dropped = [], []
        for el in warm:
            if el.texture in m.protected_textures:
                keep.append(el)
                continue
            age = max(0, cycle - el.cycle)
            p = m.forget_base_probability + age * m.forget_age_weight
            p -= el.citations * m.forget_citation_shield
            p = max(0.0, min(0.95, p))
            if rng.chance(p):
                dropped.append(el)
            else:
                keep.append(el)
        if dropped:
            self._save_warm(keep)
            for el in dropped:
                self.store.append_jsonl(self.store.cold, el.to_dict())
        return [e.id for e in dropped]

    def replay(self, rng, cycle: int) -> Element | None:
        """Resurface a cold element, chosen at random."""
        cold = self.cold()
        if not cold:
            return None
        el = rng.choice(cold)
        self.cite([el.id], cycle)
        return el

    def subset(self, rng) -> list[Element]:
        """Each drift pass gets a different random subset of the warm manifold."""
        warm = self.project()
        if not warm:
            return []
        k = max(self.cfg.drift.subset_min, int(len(warm) * self.cfg.drift.subset_fraction))
        return rng.sample(warm, min(k, len(warm)))

    def by_texture(self, texture: str) -> list[Element]:
        return [e for e in self.warm() if e.texture == texture]

    def project(self) -> list[Element]:
        """The warm manifold without the life.

        The life is read from the journal by the readers entitled to it, so it
        does not also arrive here and dilute a judgement context.
        """
        return [e for e in self.warm() if e.texture != "life"]

    def project_ids(self) -> set[str]:
        """Ids that count as a project anchor. Life ids are not among them."""
        return {e.id for e in self.warm() if e.texture != "life"} | \
               {e.id for e in self.cold() if e.texture != "life"}

    def recent(self, n: int) -> list[Element]:
        return self.warm()[-n:]

    def ids(self) -> set[str]:
        return {e.id for e in self.warm()} | {e.id for e in self.cold()}


def render(elements: Iterable[Element], limit: int = 0) -> str:
    """The manifold is read whole while warm. Ids lead, so a link can cite one."""
    items = list(elements)
    if limit:
        items = items[-limit:]
    if not items:
        return "(empty)"
    lines = []
    for el in items:
        tag = el.texture + (" synthetic" if el.synthetic else "")
        lines.append(f"{el.id} [{tag}] {el.text}")
    return "\n".join(lines)


def render_json(elements: Iterable[Element]) -> str:
    return json.dumps([{"id": e.id, "texture": e.texture, "text": e.text,
                        "synthetic": e.synthetic} for e in elements], indent=2)
