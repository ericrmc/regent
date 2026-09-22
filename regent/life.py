"""The owner as a folder and a sqlite file: his days, his threads, his taste, and what he holds of a project.

`Life` is the only thing in the package that outlives a run. It is continuous
across every project the same person governs, which is why the day number comes
out of the table rather than out of the run. `todays_threads` is the dice and
this file meeting: which of the things hanging over him comes up today, and what
the day writer is told about it. `cast_cmd` makes one of these folders.
"""
from __future__ import annotations

import json
import math
import random
import re
import threading
import time
from pathlib import Path

from regent import HOME, OWNERS, agents, prompts
from regent.charter import sections
from regent.crossing import shares_a_name
from regent.dice import DIALS, MOVES, REGISTERS, clip, roll_register, thread_due, thread_move
from regent.ledger import Run, db
from regent.schemas import CAST

MOVE_TEXT = {m: prompts.load(f"thread_{m}") for m in MOVES}


class Life:
    """An owner is a folder: bible.md, disposition.json, events.md, life.db. The
    folder is the whole person, so a regent is a thing you copy. The day number
    comes from the table itself, which is what stops two runs on two projects
    writing over the same day."""

    SCHEMA = """
    CREATE TABLE IF NOT EXISTS day(n INTEGER PRIMARY KEY, iso TEXT, text TEXT, project TEXT DEFAULT '');
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
        if "project" not in {r[1] for r in self.c.execute("PRAGMA table_info(day)")}:   # a life from before
            self.c.execute("ALTER TABLE day ADD COLUMN project TEXT DEFAULT ''")
        self.lock = threading.Lock()

    def d(self, k: str) -> float:
        return float(self.disp.get(k, 0) or 0)

    @property
    def who(self) -> str:
        return self.bible.split("## The cast")[0][:1800]

    def q(self, sql: str, *args) -> list:
        with self.lock:
            return self.c.execute(sql, args).fetchall()

    @property
    def register(self) -> str:
        return r if (r := self.disp.get("register")) in REGISTERS else "account"

    def add_day(self, text: str, project: str = "") -> int:
        """The entry is kept whole, and the part of it that is the project is kept again beside it, so
        whatever reads his life as his own can leave the project out without guessing where it was."""
        with self.lock:
            return self.c.execute("INSERT INTO day(n, iso, text, project) VALUES "
                                  "((SELECT COALESCE(MAX(n),0)+1 FROM day), ?, ?, ?)",
                                  (time.strftime("%F"), text, project)).lastrowid

    @staticmethod
    def _own(text: str, project: str, own: bool) -> str:
        return re.sub(r"\n{3,}", "\n\n", text.replace(project, "")).strip() if own and project else text

    def days(self) -> int:
        return self.q("SELECT COALESCE(MAX(n),0) FROM day")[0][0]

    def recent(self, k: int, chars: int = 600, tail: bool = False, own: bool = False) -> str:
        """`own` leaves out what he wrote about the project, for whatever takes the day as his life and
        not as the project: the project told back to the field as life is the project meeting itself."""
        rows = [(n, self._own(t, p, own)) for n, t, p in
                self.q("SELECT n, text, project FROM day ORDER BY n DESC LIMIT ?", k)]
        return "\n\n".join(f"day {n}\n{'...' + t[-chars:] if tail else t[:chars]}" for n, t in reversed(rows))

    def latest(self, k: int) -> list[str]:
        return [t for (t,) in self.q("SELECT text FROM day ORDER BY n DESC LIMIT ?", k)]

    def sample(self, rng: random.Random, k: int, chars: int = 1800, own: bool = False) -> str:
        """Days drawn without replacement, recent ones likelier, old ones never impossible. That is replay."""
        rows, top = [(n, self._own(t, p, own)) for n, t, p in self.q("SELECT n, text, project FROM day")], self.days()
        keyed = sorted(rows, key=lambda r: rng.random() ** (1 / math.exp(-(top - r[0]) / 40)), reverse=True)[:k]
        return "\n\n".join(f"L{n}: {t[:chars]}" for n, t in sorted(keyed))

    def calendar(self, n: int) -> str:
        """A weekday and a point in the year, derived from day one and never stored. Josh comes on
        Thursdays and the hives follow the light, and neither can happen if every day is nameless."""
        first = self.q("SELECT iso FROM day WHERE iso IS NOT NULL ORDER BY n LIMIT 1")   # an old life may have undated days
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
    blocks.append(prompts.load("thread_first").format(what=first["text"], state=first["state"], move=MOVE_TEXT[move]))
    others = [t for t in open_now if t["id"] != first["id"]]
    if others and rng.random() < 0.45 + 0.15 * life.d("curious") + 0.15 * life.d("restless"):
        kin = [t for t in others if shares_a_name(first["state"], t["state"])]
        second = rng.choice(kin) if kin else thread_due(rng, others, day, life.d("patient"))
        picked.append({**second, "move": "came to mind"})
        blocks.append(prompts.load("thread_second").format(what=second["text"], state=second["state"]))
    return picked, blocks


def owner_dir(name: str) -> Path:
    p = Path(name).expanduser()
    if p.is_dir():
        return p
    for base in (HOME / "owners", OWNERS):
        if (base / name).is_dir():
            return base / name
    raise SystemExit(f"no owner {name!r}: looked in {HOME / 'owners'} and {OWNERS}. Roll one with: regent cast")


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
    got = agents.ask(run, agents.builder(a.agent), "cast", a.model, prompts.load("cast").format(
        age=int(clip(rng.gauss(48, 15), 19, 84)), dials=", ".join(f"{k} {v:+.2f}" for k, v in dials.items()),
        words=", ".join(rolled), pins="; ".join(a.pin) or "nothing"), CAST)
    root = HOME / "owners" / (a.name or re.sub(r"[^a-z0-9-]", "", got["slug"].lower()) or f"owner-{a.seed}")
    root.mkdir(parents=True, exist_ok=True)
    (root / "bible.md").write_text(got["bible"].strip() + "\n")
    (root / "disposition.json").write_text(json.dumps({**dials, "register": a.register or roll_register(rng), "pinned": a.pin,
                                                       "rolled": {"seed": a.seed, "words": rolled}}, indent=2))
    (root / "events.md").write_text("\n".join(got["events"]) + "\n")
    (root / "pursuits.md").write_text("\n".join(got["pursuits"]) + "\n")
    print(f"\n{got['name']}  ->  {root}\n  " + ", ".join(f"{k} {v:+.2f}" for k, v in dials.items()) +
          f"\n  rolled words: {', '.join(rolled)}\n\n" + got["bible"].split("## The cast")[0].strip()[:900] +
          f"\n\nregent run --project <dir> --owner {root.name}")
