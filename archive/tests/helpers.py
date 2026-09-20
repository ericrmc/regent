"""Shared fixtures. Every test runs on FakeRunner, so nothing is spent."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from regent.config import Config  # noqa: E402
from regent.loop import Context, bootstrap  # noqa: E402
from regent.notify import Notifier  # noqa: E402
from regent.runner import FakeRunner  # noqa: E402
from regent.store import Store  # noqa: E402

CHARTER = """# Charter

## Intent
A command line tool that reports broken internal links in a folder of markdown notes.
It is for one person maintaining a notes folder.

## Constraints
- Python 3.11, standard library only.
- One file plus tests.
- No network access.

## Refusals
- Never delete or modify the user's files.
- Never make a network request.
- Never install a package.

## Reserved
- Spending money.
- Publishing outside the project directory.
- Contacting a person.
- Touching a file outside the project directory.

## Budget
- tokens: 2000000
- spend_usd: 10
- wall_time: 2h

## Stop
- The tool reports broken links on a real folder and the tests pass.
- Stop unsuccessfully if three dispatches in a row fail on the same criterion.
- digest_every: 10 turns
"""


def return_block(headline="The link checker now walks the folder.",
                 recommendation="Ship it. The criteria are met.",
                 flags=None, evidence=None, detail=None, assumptions=None) -> str:
    payload = {
        "headline": headline,
        "recommendation": recommendation,
        "flags": flags if flags is not None else [],
        "evidence": evidence if evidence is not None else [
            {"kind": "test", "ref": "python3 -m pytest tests/", "note": "9 passed, 0 failed"},
            {"kind": "output", "ref": "evidence/run.txt", "note": "the tool on a real folder"},
        ],
        "assumptions": assumptions if assumptions is not None else [],
        "detail": detail if detail is not None else [
            {"heading": "What was built",
             "body": "The checker walks the folder and resolves each link. "
                     "It resolves relative links against the containing file. "
                     "It took 0.4 seconds over 120 files. "
                     "Anchors are not checked yet."},
        ],
    }
    return ("Work is done.\n\n===RETURN===\n" + json.dumps(payload) + "\n===END RETURN===\n")


def decision(**over) -> dict:
    d = {
        "stance_line": "Even. The evidence is thin but the work is small.",
        "notes": [],
        "judgements": [],
        "amendments": [],
        "objectives": [],
        "dispatches": [],
        "escalations": [],
        "ladder": [],
        "inspect": [],
        "query": [],
        "requirements": [],
        "stop": {"requested": False, "reason": ""},
        "rationale": "One step at a time.",
    }
    d.update(over)
    return d


def a_candidate(**over) -> dict:
    c = {
        "text": "Probe for unresolvable links first.",
        "from_indexes": [0],
        "kind": "solution",
        "disconfirming": "Run it on a folder with one known bad link.",
        "serves_intent": "",
        "rework": "",
        "appetite_share": 0.0,
        "changes_charter": False,
        "cost_note": "one afternoon",
    }
    c.update(over)
    return c


def a_requirement(**over) -> dict:
    base = {
        "text": "It should report a link that points at a file outside the folder.",
        "kind": "requirement",
        "disconfirming": "",
        "serves_intent": "The charter asks for broken internal links and an outside "
                         "link is the case a notes folder hits most.",
        "rework": "The walker's link classifier is redone. One accepted dispatch reopens.",
        "appetite_share": 0.1,
    }
    base.update(over)
    return a_candidate(**base)


def a_wake_requirement(**over) -> dict:
    """The shape Wake returns. It passes the same gate as Sift's."""
    r = {
        "text": "It should report a link that points outside the folder.",
        "serves_intent": "The charter asks for broken internal links and an "
                         "outside link is the case a notes folder hits most.",
        "rework": "The link classifier is redone.",
        "origin": "the return on d0001",
        "objective_id": "obj-1",
        "appetite_share": 0.1,
        "changes_charter": False,
    }
    r.update(over)
    return r


def a_dispatch(did="d0001", **over) -> dict:
    d = {
        "id": did,
        "objective_id": "obj-1",
        "title": "Walk the folder and resolve links",
        "intent": "Build the walker and resolve every internal link against the file that holds it.",
        "acceptance": ["It reports a broken link on a folder that has one.",
                       "It exits zero when nothing is broken."],
        "tier": "low",
        "classes": ["file reading", "cli"],
    }
    d.update(over)
    return d


DEFAULTS = {
    "saturate": {"motifs": [{"text": "links resolve against the file that holds them",
                             "element_ids": ["m00001"]}],
                 "tensions": [], "questions": ["what counts as internal"]},
    "drift": {"links": []},
    "sift": {"scored": [], "candidates": []},
    "life_bible": {"bible": "# Marta Vasi\n\nMarta is 44, a bridge inspector in Hull.",
                   "threads": ["whether to sell the house"]},
    "life_condense": {"entries": [{"entry": "Frost until ten. New chip in the jug.",
                                   "kept": ["frost", "jug"]}]},
    "life_week": {"entries": [{"entry": "The frost held until ten. The jug has a new chip.",
                               "valence": -0.2, "keywords": ["frost", "jug"],
                               "thread_notes": []}]},
    "life_day": {"entry": "The frost was still on the shadowed side of the yard at ten. "
                          "The jug had a new chip in it and nobody owned up.",
                 "valence": -0.2, "keywords": ["frost", "jug"],
                 "thread_notes": []},
    "stepping_back": {"observations": [], "ways": [], "process_notes": []},
    "spot_check": {"findings": "The checker runs and reports two broken links. "
                               "It does not resolve anchors at all.",
                   "verdicts": [{"claim_id": "c1", "verdict": "confirmed", "note": "it walks"}],
                   "gap": False, "openings": []},
    "consolidate": {"memory": [], "taste": [], "objectives": []},
    "react": {"notes": [{"texture": "sensory", "text": "9 passed, 0 failed."}]},
    "salience": {"keep": []},
    "day_fragment": {"fragment": "The bus was eleven minutes late and the gravel was wet.",
                     "keywords": ["bus", "gravel"]},
    "audit": {"agrees": True, "missed": [], "severity": "none"},
}


def _fake_reader(req):
    """A stand-in reader that answers the way a competent one would.

    It finds intent where a rule's words appear in a clause that does not
    promise not to do the thing, and quotes that clause verbatim so the
    harness's own quote check passes. Tests that want a particular verdict
    script `reader` themselves.
    """
    import re as _re

    from regent.runner import ModelResponse

    prompt = req.prompt
    rules_block = prompt.split("## The rules", 1)[-1].split("## The text", 1)[0]
    rules = [line[2:].strip() for line in rules_block.splitlines()
             if line.startswith("- ")]
    text = prompt.split("## The text", 1)[-1].rsplit("That is a", 1)[0].strip()
    clauses = [c.strip() for c in _re.split(r"(?<=[.!?])\s+|\n", text) if c.strip()]
    stop = {"the", "a", "an", "and", "or", "of", "to", "in", "on", "any", "all",
            "never", "not", "no", "for", "with", "that", "this", "is", "are",
            "it", "its", "be", "by", "at", "from", "outside", "project"}
    negators = {"no", "not", "never", "without", "none", "only", "avoid",
                "avoids", "cannot"}
    findings = []
    for rule in rules:
        words = {w for w in _re.findall(r"[a-z]{3,}", rule.lower())
                 if w not in stop}
        if not words:
            continue
        for clause in clauses:
            got = set(_re.findall(r"[a-z]{3,}", clause.lower()))
            hit = {w for w in words if any(g.startswith(w[:5]) for g in got)}
            if len(hit) < max(1, len(words) - 1):
                continue
            direction = "complies" if got & negators else "intends"
            findings.append({"rule": rule, "direction": direction,
                             "quote": clause, "why": "the clause names it",
                             "tier": "low"})
            break
    return ModelResponse(role="reader",
                         structured={"findings": findings, "unsure": False})


def fake(**scripts) -> FakeRunner:
    """A runner with a safe default for every role a turn can reach."""
    base = {k: [v] for k, v in DEFAULTS.items()}
    base["orchestrator"] = [return_block()]
    base["wake"] = [decision()]
    base["reader"] = [_fake_reader]
    base["tool_denials"] = [{"denials": []}]
    for role, items in scripts.items():
        base[role] = list(items) if isinstance(items, list) else [items]
    return FakeRunner(scripts=base)


class HarnessCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.charter_path = self.root / "charter.md"
        self.charter_path.write_text(CHARTER)
        self.project = self.root / "project"
        self.project.mkdir()
        self.store = Store(self.root / "run")
        self.cfg = Config()
        self.cfg.life.enabled = False
        # A cycle beside the work makes every other test nondeterministic. The
        # pace tests turn it back on and join.
        self.cfg.cycle_in_background = False
        self.notifier = Notifier()

    def tearDown(self) -> None:
        ctx = getattr(self, "ctx", None)
        t = getattr(ctx, "cycle_thread", None) if ctx else None
        if t is not None and t.is_alive():
            t.join(timeout=20)
        self.tmp.cleanup()

    def boot(self, runner=None, seed=7, cfg=None) -> Context:
        runner = runner or fake()
        self.runner = runner
        self.ctx = bootstrap(self.store, cfg or self.cfg, str(self.charter_path),
                             str(self.project), seed=seed,
                             prompts_dir=ROOT / "prompts", plugin_dir=ROOT / "plugin",
                             runners={"claude": runner}, notifier=self.notifier)
        return self.ctx
