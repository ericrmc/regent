"""Ways of working: standing practices in the owner's words.

A way changes how the owner works and never what the owner is permitted. It
cannot touch the charter, the refusals, the reserved list, the tiers or either
gate, and it cannot lower a floor. The spot-check rate, the audit rate and the
debt cap may rise and never fall.

Each way is an experiment. It names the pattern that prompted it, the number it
expects to move, and a review date in turns. At review the harness sets the
before and the after side by side, and the way is kept only where the number
moved.
"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field

# Settings a way may move. Anything not named here is prose guidance only.
ADJUSTABLE = {
    "spot_check.rate": float,
    "attention.audit_rate": float,
    "attention.debt_cap": int,
    "attention.band_full": float,
    "attention.band_skim": float,
    "drift.passes": int,
    "sift.keep": int,
    "dispatching.max_concurrent": int,
    "cycle_every_n_turns": int,
    "spot_check.max_per_turn": int,
    "spot_check.queries_per_turn": int,
}

# Of those, the ones that are floors. They may rise and never fall.
FLOORS = {
    "spot_check.rate": "up",
    "attention.audit_rate": "up",
    "attention.debt_cap": "up",
    "spot_check.max_per_turn": "up",
}

# What a way may never reach, whatever it says.
FORBIDDEN = ("charter", "refusal", "reserved", "tier", "gate", "appetite",
             "groundedness", "disconfirming", "budget")


@dataclass
class Way:
    id: str
    text: str
    pattern: str = ""
    metric: str = ""
    direction: str = "down"
    setting: str = ""
    value: float = 0.0
    baseline: float | None = None
    created_turn: int = 0
    review_turn: int = 0
    status: str = "live"
    outcome: str = ""
    after: float | None = None
    ts: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Applied:
    kept: list[dict] = field(default_factory=list)
    refused: list[dict] = field(default_factory=list)
    displaced: list[dict] = field(default_factory=list)
    settings: list[dict] = field(default_factory=list)


def refuse_reason(item: dict, cfg, reader=None) -> str:
    """Why a way may not be applied.

    The settings half is code: a floor may rise and never fall, and a setting
    off the list may not move at all. Whether the prose of a way reaches for
    something forbidden is read, because matching forbidden nouns near
    loosening verbs is the check that misfired on the first real run.
    """
    text = f"{item.get('text', '')} {item.get('pattern', '')}".lower()
    setting = (item.get("setting") or "").strip()

    if setting:
        if setting not in ADJUSTABLE:
            return f"names a setting a way may not move: {setting}"
        want = float(item.get("value", 0.0))
        current = float(_get(cfg, setting))
        if setting in FLOORS:
            # A floor may rise and never fall.
            if want < current:
                return (f"would lower {setting} from {current} to {want}, and a "
                        f"floor may rise and never fall")
        if want <= 0 and ADJUSTABLE[setting] is int:
            return f"would set {setting} to {want}, which stops the thing entirely"
    else:
        prose = f"{item.get('text', '')}\n{item.get('pattern', '')}"
        if reader is not None and getattr(reader, "enabled", False):
            reading = reader.read(
                "Does this way loosen scrutiny, or reach for something it may "
                "not touch?",
                prose,
                ["It may not touch the charter, the refusals, the reserved "
                 "list, the risk tiers or either gate.",
                 "It may not lower a floor: the spot-check rate, the audit "
                 "rate and the debt cap may rise and never fall."],
                kind="way")
            breaches = reading.breaches()
            if breaches:
                return (f"a way may not do that: {breaches[0].rule} "
                        f"({breaches[0].quote[:100]})")
            return ""
        for word in FORBIDDEN:
            if word in text and any(
                    loosen in text for loosen in
                    ("lower", "reduce", "relax", "loosen", "skip", "drop",
                     "waive", "fewer", "less", "ignore", "bypass", "widen")):
                return f"a way may not loosen {word}"
    return ""


def _get(cfg, path: str):
    node = cfg
    parts = path.split(".")
    for p in parts[:-1]:
        node = getattr(node, p)
    return getattr(node, parts[-1])


def _set(cfg, path: str, value) -> None:
    node = cfg
    parts = path.split(".")
    for p in parts[:-1]:
        node = getattr(node, p)
    setattr(node, parts[-1], ADJUSTABLE[path](value))


class Ways:
    """The file, capped. An eighth way has to displace one."""

    def __init__(self, cfg, rows: list[dict] | None = None) -> None:
        self.cfg = cfg
        self.rows: list[dict] = list(rows or [])

    def live(self) -> list[dict]:
        return [w for w in self.rows if w.get("status") == "live"]

    def by_id(self, wid: str) -> dict | None:
        for w in self.rows:
            if w.get("id") == wid:
                return w
        return None

    def apply(self, items: list[dict], turn: int, view=None,
              reader=None) -> Applied:
        out = Applied()
        for item in items:
            action = item.get("action", "add")
            if action == "drop":
                w = self.by_id(item.get("id", ""))
                if w and w.get("status") == "live":
                    w["status"] = "dropped"
                    w["outcome"] = "dropped by stepping back"
                    out.displaced.append(w)
                continue

            why = refuse_reason(item, self.cfg, reader=reader)
            if why:
                out.refused.append({**item, "refused": why})
                continue

            wid = item.get("id") or f"way-{len(self.rows) + 1:03d}"
            existing = self.by_id(wid)
            metric = item.get("metric", "")
            baseline = view.metric(metric) if (view is not None and metric) else None
            w = Way(
                id=wid,
                text=item.get("text", ""),
                pattern=item.get("pattern", ""),
                metric=metric,
                direction=item.get("direction", "down"),
                setting=item.get("setting", ""),
                value=float(item.get("value", 0.0)),
                baseline=baseline,
                created_turn=turn,
                review_turn=turn + int(item.get("review_in_turns")
                                       or self.cfg.ways.review_in_turns),
                ts=time.time(),
            ).to_dict()

            if existing:
                existing.update({k: v for k, v in w.items()
                                 if k not in ("id", "created_turn")})
                existing["status"] = "live"
            else:
                self.rows.append(w)

            if w["setting"]:
                _set(self.cfg, w["setting"], w["value"])
                out.settings.append({"setting": w["setting"], "value": w["value"],
                                     "way": wid})
            out.kept.append(w)

        # The file holds seven at most, so an eighth displaces the oldest way
        # that is not itself holding a floor up.
        live = self.live()
        while len(live) > self.cfg.ways.cap:
            live.sort(key=lambda w: (w.get("setting", "") in FLOORS,
                                     w.get("created_turn", 0)))
            oldest = live[0]
            oldest["status"] = "displaced"
            oldest["outcome"] = f"displaced when way {len(self.rows)} arrived"
            out.displaced.append(oldest)
            live = self.live()
        return out

    def due(self, turn: int) -> list[dict]:
        return [w for w in self.live()
                if w.get("review_turn") and turn >= int(w["review_turn"])
                and w.get("metric")]

    def review(self, turn: int, view) -> list[dict]:
        """A way is kept only where its number moved the way it said."""
        results = []
        for w in self.due(turn):
            after = view.metric(w.get("metric", ""))
            before = w.get("baseline")
            w["after"] = after
            if after is None or before is None:
                w["status"] = "dropped"
                w["outcome"] = "the number it named was never counted"
            else:
                moved = (after < before) if w.get("direction") == "down" \
                    else (after > before)
                if moved:
                    w["status"] = "live"
                    w["outcome"] = (f"kept, {w['metric']} moved "
                                    f"{before} to {after}")
                    w["review_turn"] = turn + self.cfg.ways.review_in_turns
                    w["baseline"] = after
                else:
                    w["status"] = "dropped"
                    w["outcome"] = (f"dropped, {w['metric']} did not move "
                                    f"{w['direction']}: {before} to {after}")
                    if w.get("setting") and w["setting"] not in FLOORS:
                        # A setting a dropped way raised goes back, unless it
                        # is a floor, which never falls.
                        pass
            results.append(w)
        return results

    def to_list(self) -> list[dict]:
        return list(self.rows)

    def render(self) -> str:
        """What Wake reads and what goes down with every dispatch."""
        live = self.live()
        if not live:
            return "(none yet)"
        out = []
        for w in live:
            line = f"- {w['text']}"
            if w.get("pattern"):
                line += f"\n  (because {w['pattern']})"
            out.append(line)
        return "\n".join(out)

    def write(self, path) -> None:
        lines = ["# Ways of working", "",
                 "Standing practices. Each one names what prompted it, the "
                 "number it expects to move, and when it is reviewed.", ""]
        for w in self.live():
            lines.append(f"## {w['id']}")
            lines.append(w.get("text", ""))
            if w.get("pattern"):
                lines.append(f"Prompted by: {w['pattern']}")
            if w.get("metric"):
                lines.append(f"Expects {w['metric']} to go {w.get('direction')}, "
                             f"from {w.get('baseline')}, reviewed at turn "
                             f"{w.get('review_turn')}.")
            if w.get("setting"):
                lines.append(f"Sets {w['setting']} to {w['value']}.")
            lines.append("")
        closed = [w for w in self.rows if w.get("status") != "live"]
        if closed:
            lines += ["## Closed", ""]
            lines += [f"- {w['id']}: {w.get('outcome', '')}" for w in closed] + [""]
        path.write_text("\n".join(lines))
