"""What can be proved without spending anything: the pure draws, the charter, and one whole run.

The whole-run test puts `tests/fake_claude.py` on PATH as `claude` and drives
three days of a life end to end, then reads the ledger back. It skips itself
cleanly when git is missing, because the builder's turn commits.
"""
from __future__ import annotations

import json
import os
import random
import shutil
import sqlite3
import string
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import ClassVar

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from regent import agents, prompts
from regent.agents import Adapter
from regent.agents.claude import Claude
from regent.agents.cursor import schema_in_words
from regent.charter import charter_faults, sections
from regent.crossing import crossed, echoes, gauge, places_named, unmark, words
from regent.dice import REGISTERS, clip, due, how_it_goes, in_words, poisson, thread_due, thread_move
from regent.field import CAME, STREAMS, alike, appetite, cool, feed, ignite, theta
from regent.life import Life
from regent.night import catch
from regent.schemas import DECISION, PICTURE, SIFTED, TAKEN

CHARTER = """# A tiny thing

## Intent
A one-line tool that writes a line to a file, for somebody who cannot read code.

## Constraints
- one file, no dependencies

## Refusals
- never delete anything of his

## Reserved
- whether it is ever given to anyone else

## Budget
days: 3
turns_per_day: 2

## Tools
- cat built.txt

## Check
test -f built.txt

## Show
cat built.txt

## Stop
When it writes a line and he has seen it.
"""


class Dice(unittest.TestCase):
    def test_clip(self):
        self.assertEqual(clip(2.0), 1.0)
        self.assertEqual(clip(-2.0), -1.0)
        self.assertEqual(clip(5, 0, 10), 5)

    def test_poisson_mean(self):
        rng = random.Random(7)
        draws = [poisson(rng, 1.5) for _ in range(4000)]
        self.assertTrue(all(k >= 0 for k in draws))
        self.assertAlmostEqual(sum(draws) / len(draws), 1.5, delta=0.15)
        self.assertEqual(poisson(rng, 0.0), 0)

    def test_due_is_a_hazard_not_a_schedule(self):
        rng = random.Random(3)
        near = sum(due(rng, 1, 10) for _ in range(2000))
        far = sum(due(rng, 20, 10) for _ in range(2000))
        self.assertLess(near, far)
        self.assertFalse(due(rng, 0, 5))

    def test_a_neglected_thread_comes_due(self):
        rng = random.Random(11)
        threads = [{"id": 1, "moved": 10, "moves": 0}, {"id": 2, "moved": 1, "moves": 0}]
        picks = [thread_due(rng, threads, 11, 0.0)["id"] for _ in range(400)]
        self.assertGreater(picks.count(2), picks.count(1) * 2)

    def test_thread_move_is_one_of_four(self):
        rng = random.Random(5)
        moves = {thread_move(rng, {"moves": 0}, 0.0, lambda k: 0.0) for _ in range(200)}
        self.assertTrue(moves <= {"toward", "turns", "against", "ends"})

    def test_a_good_mood_turns_things_better(self):
        rng = random.Random(2)
        good = [how_it_goes(rng, 0.9) for _ in range(600)]
        bad = [how_it_goes(rng, -0.9) for _ in range(600)]
        better = "and it goes better than it might have"
        self.assertGreater(good.count(better), bad.count(better) * 2)

    def test_in_words_never_names_a_dial(self):
        class Fake:
            def d(self, k):
                return {"curious": 0.8, "patient": -0.7}.get(k, 0.0)
        said = in_words(Fake())
        self.assertIn("go and find out about it", said)
        self.assertIn("want it done now", said)
        for dial in ("curious", "patient", "bold"):
            self.assertNotIn(dial, said)

    def test_nothing_marked_is_still_an_answer(self):
        class Flat:
            def d(self, k):
                return 0.0
        self.assertEqual(in_words(Flat()), "- Nothing marked strongly either way.")


class Field(unittest.TestCase):
    def notion(self, **kw):
        return {"id": "n1", "text": "a thing", "a": 0.0, "streams": [], "fed": [],
                "born": 1, "last": 1, "arrived": [], **kw}

    def test_a_fresh_stream_is_worth_more(self):
        one = [self.notion()]
        feed(one, [{"notion": "n1", "stream": "life", "strength": 1, "because": "x"}], 1, 0)
        first = one[0]["a"]
        feed(one, [{"notion": "n1", "stream": "life", "strength": 1, "because": "x"}], 1, 0)
        self.assertLess(one[0]["a"] - first, first)

    def test_one_stream_saying_it_again_adds_less_each_time(self):
        f, gains = [self.notion()], []
        for _ in range(4):
            before = f[0]["a"]
            feed(f, [{"notion": "n1", "stream": "use", "strength": 3, "because": "x"}], 1, 0)
            gains.append(f[0]["a"] - before)
        self.assertEqual(gains, sorted(gains, reverse=True))
        self.assertLess(gains[3], gains[1] / 2 + 0.01)

    def test_life_and_project_meeting_lifts_it_once(self):
        f = [self.notion()]
        feed(f, [{"notion": "n1", "stream": "life", "strength": 1, "because": "x"}], 1, 0)
        before = f[0]["a"]
        feed(f, [{"notion": "n1", "stream": "reading", "strength": 1, "because": "y"}], 1, 0)
        bridged = f[0]["a"] - before
        feed(f, [{"notion": "n1", "stream": "use", "strength": 1, "because": "z"}], 1, 0)
        self.assertLess(f[0]["a"] - before - bridged, bridged)

    def test_a_seed_makes_a_notion_and_an_id_is_never_reused(self):
        f: list[dict] = []
        made = feed(f, [{"notion": "", "seed": "a shape", "stream": "night", "strength": 2, "because": "x"}], 1, 0)
        self.assertEqual(made, 1)
        self.assertEqual(f[0]["id"], "n1")
        made = feed(f, [{"notion": "", "seed": "another", "stream": "night", "strength": 2, "because": "x"}], 1, made)
        self.assertEqual([n["id"] for n in f], ["n1", "n2"])

    def test_nothing_without_a_seed_or_a_notion(self):
        f: list[dict] = []
        self.assertEqual(feed(f, [{"notion": "nope", "seed": "", "stream": "life"}], 1, 0), 0)
        self.assertEqual(f, [])

    def test_the_faint_and_unfed_are_gone(self):
        f = [self.notion(a=0.5, last=1), self.notion(id="n2", a=9.0, last=1)]
        kept = cool(f, 9)
        self.assertEqual([n["id"] for n in kept], ["n2"])

    def test_curiosity_lowers_the_threshold_and_patience_raises_it(self):
        keen = theta(lambda k: 1.0 if k == "curious" else 0.0, False, 0.0)
        calm = theta(lambda k: 1.0 if k == "patient" else 0.0, False, 0.0)
        self.assertLess(keen, calm)
        self.assertLess(theta(lambda k: 0.0, True, 0.0), theta(lambda k: 0.0, False, 0.0))
        self.assertLess(theta(lambda k: 0.0, False, 0.0), theta(lambda k: 0.0, False, 3.0))

    def test_one_crosses_at_a_time_and_an_arrival_raises_the_bar(self):
        rng = random.Random(1)
        f = [self.notion(a=9.0), self.notion(id="n2", a=1.0)]
        self.assertEqual(ignite(f, 8.0, rng)["id"], "n1")
        self.assertIsNone(ignite([self.notion(a=9.0, arrived=["I1", "I2"])], 8.0, rng))

    def test_every_stream_is_on_a_side(self):
        for s in STREAMS.values():
            self.assertIn(s, ("life", "project", ""))
        self.assertEqual(sorted(CAME), ["away", "sitting", "woke"])

    def test_alike(self):
        self.assertEqual(alike("", ""), 1.0)
        self.assertEqual(alike("same", "same"), 1.0)
        self.assertLess(alike("a line", "something else entirely, and longer"), 0.6)

    def test_boredom_pushes_only_when_it_is_standing_up(self):
        dials = lambda k: 0.0
        push, altitude = appetite(1.0, 0.8, True, False, dials, 0.0)
        self.assertTrue(push)
        self.assertEqual(altitude, "direction")
        self.assertFalse(appetite(1.0, 0.8, False, False, dials, 0.0)[0])   # the check is failing
        self.assertFalse(appetite(1.0, 0.8, True, True, dials, 0.0)[0])     # something already arrived
        self.assertEqual(appetite(0.0, 0.1, True, False, dials, 0.0)[1], "proof")


class Catch(unittest.TestCase):
    def link(self, anchors, other="somewhere"):
        return {"text": "a link", "anchors": anchors, "other": other, "mechanism": "m"}

    def test_a_link_with_no_anchor_in_the_project_is_a_miss(self):
        rng = random.Random(0)
        kept = catch([self.link(["req-01"]), self.link(["nowhere"], "b"), self.link(["req-01"], "c")],
                     {"req-01"}, rng)
        self.assertEqual([k["other"] for k in kept], ["somewhere", "c"])

    def test_the_spoon_drops_on_a_run_of_misses(self):
        rng = random.Random(0)
        kept = catch([self.link(["x"], str(i)) for i in range(12)] + [self.link(["why"])], {"why"}, rng)
        self.assertEqual(kept, [])

    def test_the_same_pair_twice_is_a_miss(self):
        rng = random.Random(4)
        kept = catch([self.link(["why"]), self.link(["why"])], {"why"}, rng)
        self.assertEqual(len(kept), 1)


class Crossing(unittest.TestCase):
    def test_words_splits_on_the_underscore_seam(self):
        self.assertIn("lines", words("bad_lines here"))
        self.assertNotIn("bad_lines", words("bad_lines here"))

    def test_the_gauge_counts_only_what_is_theirs_and_not_his(self):
        share, codeish = gauge("the parser threw", {"parser", "threw"}, {"threw"})
        self.assertAlmostEqual(share, 0.5)   # "the" is too short to count as a word at all
        self.assertEqual(codeish, 0)
        self.assertEqual(gauge("run regent.py and check req-01", set(), set())[1], 2)

    def test_crossed_carries_both_honest_edges(self):
        said = crossed({"taken": "it works now", "not_followed": ["the second half"], "not_reached": "the end"})
        self.assertTrue(said.startswith("it works now"))
        self.assertIn("What you did not follow: the second half", said)
        self.assertIn("What you did not get to: the end", said)
        self.assertEqual(crossed({"taken": "it works", "not_followed": [], "not_reached": " "}), "it works")

    def test_unmark_takes_the_marks_off_the_entry(self):
        text, marks = unmark("a day of it.\n\nTHREAD 1: the gate is hung\nNEW: the pump is loose\n")
        self.assertEqual(text, "a day of it.")
        self.assertEqual(marks, {"THREAD 1": "the gate is hung", "NEW": "the pump is loose"})

    def test_a_bold_mark_is_still_a_mark(self):
        text, marks = unmark("a day of it.\n\n**THREAD 1:** the gate is hung\n- PROJECT: it found the letter.\n")
        self.assertEqual(text, "a day of it.")
        self.assertEqual(marks, {"THREAD 1": "the gate is hung", "PROJECT": "it found the letter."})

    def test_an_entry_that_opens_like_a_recent_one_echoes(self):
        before = ["# 2019-03-21  Twenty to six. Fog. Window a blank.", "Day 43. Up 5:40, tea, Argyle mug, chip."]
        self.assertTrue(echoes("# 2019-03-22  Twenty to six. Frost on the glass.", before))
        self.assertTrue(echoes("Day 44. Up 5:40, tea, Argyle mug, thumb on the chip.", before))
        self.assertFalse(echoes("Couldn't settle all morning after Nula rang about the van.", before))

    def test_his_own_day_leaves_the_project_out(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "bible.md").write_text("## Who this is\nhim\n")
            life = Life(Path(d))
            life.add_day("Rang Nula.\n\nThe thing found the letter.", "The thing found the letter.")
            self.assertIn("found the letter", life.recent(1))
            self.assertNotIn("found the letter", life.recent(1, own=True))
            self.assertIn("Rang Nula.", life.sample(random.Random(1), 1, own=True))
            self.assertIn(life.register, REGISTERS)

    def test_places_are_cut_at_the_first_fault(self):
        bible = "## Places\n**The yard.** Where he works. The gate is broken.\n\n## History\nall of it.\n"
        cut = places_named(bible)
        self.assertIn("**The yard.** Where he works.", cut)
        self.assertNotIn("The gate is broken", cut)
        self.assertIn("all of it.", cut)


class Charter(unittest.TestCase):
    def test_sections_keeps_both_halves_of_a_repeated_heading(self):
        ch = sections("## Intent\none\n\n## Check\nx\n\n## Intent\ntwo\n")
        self.assertEqual(ch["intent"], "one\n\ntwo")
        self.assertEqual(ch["check"], "x")

    def test_a_near_miss_heading_is_said_out_loud(self):
        faults = charter_faults("## Intent\nx\n\n## Constraint\n- one\n", sections("## Intent\nx\n\n## Constraint\n- one\n"))
        self.assertTrue(any("did you mean constraints" in f for f in faults))

    def test_a_heading_with_no_space_is_not_read_as_one(self):
        md = "##Intent\nx\n"
        self.assertTrue(any("looks like a heading" in f for f in charter_faults(md, sections(md))))

    def test_no_intent_is_a_fault(self):
        self.assertTrue(any("no Intent" in f for f in charter_faults("## Check\nx\n", sections("## Check\nx\n"))))

    def test_a_budget_that_is_not_a_number_is_ignored_out_loud(self):
        md = "## Intent\nx\n\n## Budget\ndays: a fortnight\n"
        self.assertTrue(any("is not a number" in f for f in charter_faults(md, sections(md))))

    def test_a_tools_line_with_no_dash_is_ignored_out_loud(self):
        md = "## Intent\nx\n\n## Tools\nls\n"
        self.assertTrue(any("Tools line has no dash" in f for f in charter_faults(md, sections(md))))

    def test_a_network_line_that_is_not_a_domain(self):
        md = "## Intent\nx\n\n## Network\n- https://example.com/path\n"
        self.assertTrue(any("is not a bare domain" in f for f in charter_faults(md, sections(md))))

    def test_a_two_line_check_runs_as_one_command(self):
        md = "## Intent\nx\n\n## Check\npytest\nruff check\n"
        self.assertTrue(any("more than one line" in f for f in charter_faults(md, sections(md))))

    def test_a_clean_charter_has_nothing_to_say(self):
        self.assertEqual(charter_faults(CHARTER, sections(CHARTER)), [])


class Prompts(unittest.TestCase):
    def test_every_prompt_parses_and_formats(self):
        self.assertGreater(len(prompts.names()), 40)
        for name in prompts.names():
            text = prompts.load(name)
            fields = {f for _, f, _, _ in string.Formatter().parse(text) if f}
            try:
                text.format(**{f: "x" for f in fields})
            except (KeyError, IndexError, ValueError) as e:
                self.fail(f"{name}.md does not format: {e}")

    def test_the_machinery_is_disowned_first(self):
        self.assertTrue(prompts.PLAIN.startswith(prompts.UNSEEN))
        self.assertTrue(prompts.UNSEEN.endswith(". "))
        self.assertIn("belongs to the machinery", prompts.UNSEEN)


class Stub(Adapter):
    """An adapter that answers from a list, so the base class's retry can be watched."""

    PAUSE = 0

    def __init__(self, answers):
        self.answers, self.seen = list(answers), []

    def _run(self, prompt, **kw):
        self.seen.append(kw)
        raw = {"text": "", "data": None, "seconds": 0.1, "denials": [], "session": kw.get("session"),
               "error": "", "cost": 0, "tools": 0, "subtype": "success"}
        return {**raw, **self.answers.pop(0)}


class Agents(unittest.TestCase):
    ANSWER: ClassVar[dict] = {"type": "object", "properties": {"said": {"type": "string"}}, "required": ["said"]}

    def test_a_bare_json_object_is_the_answer(self):
        self.assertEqual(Adapter.parse_structured('{"said": "aye"}', self.ANSWER), {"said": "aye"})

    def test_a_fenced_block_is_found_in_prose(self):
        text = 'Here you are.\n\n```json\n{"said": "aye"}\n```\n\nHope that helps.'
        self.assertEqual(Adapter.parse_structured(text, self.ANSWER), {"said": "aye"})

    def test_the_outermost_braces_are_found_in_prose(self):
        self.assertEqual(Adapter.parse_structured('Sure: {"said": "aye"} — done.', self.ANSWER), {"said": "aye"})

    def test_half_an_answer_is_not_an_answer(self):
        self.assertIsNone(Adapter.parse_structured('{"other": 1}', self.ANSWER))
        self.assertIsNone(Adapter.parse_structured("[1, 2]", self.ANSWER))
        self.assertIsNone(Adapter.parse_structured("no json at all", self.ANSWER))
        self.assertIsNone(Adapter.parse_structured("", self.ANSWER))

    def test_the_builder_is_given_longer_than_anything_else(self):
        a = Claude()
        self.assertGreater(a.patience("claude"), a.patience("take"))

    def test_the_factory_finds_each_one_that_is_written(self):
        self.assertIsInstance(agents.builder("claude"), Claude)
        self.assertIsInstance(agents.builder(), Claude)
        self.assertEqual([agents.builder(n).name for n in ("codex", "cursor")], ["codex", "cursor"])
        with self.assertRaises(SystemExit) as e:
            agents.builder("gemini")
        self.assertIn("regent/agents/gemini.py", str(e.exception))

    def test_only_claude_can_be_handed_the_charters_domains(self):
        self.assertTrue(agents.builder("claude").holds_network)
        self.assertFalse(any(agents.builder(n).holds_network for n in ("codex", "cursor")))

    def test_a_schema_said_in_words_carries_its_whole_shape(self):
        said = schema_in_words(SIFTED)
        self.assertIn('- "candidates": a list of an object with kind (one of "ask", "doubt", '
                      '"wish", "worry"), text (text), test (text), from_indexes (a list of a whole '
                      "number), why_it_might_fail (text)", said)
        self.assertEqual(schema_in_words(TAKEN).splitlines()[:2],
                         ['- "taken": text', '- "not_followed": a list of text'])
        self.assertIn('- "challenged": true or false', schema_in_words(DECISION))
        # Every key the harness will read off the answer has to be named, or the stage cannot answer.
        for schema in (DECISION, TAKEN, SIFTED, PICTURE):
            for key in schema["required"]:
                self.assertIn(f'- "{key}":', schema_in_words(schema))

    def call(self, stub, **kw):
        events = []
        got = stub.call("say something", model="sonnet", cwd=Path("."), on_tool=lambda *a: None,
                        on_event=lambda kind, **f: events.append((kind, f)), **kw)
        return got, events

    def test_a_call_that_came_back_with_nothing_goes_again(self):
        stub = Stub([{"error": "overloaded"}, {"text": "second time lucky"}])
        got, events = self.call(stub, session="s1")
        self.assertEqual(got["text"], "second time lucky")
        self.assertEqual([k for k, _ in events], ["empty", "call", "call"])
        self.assertNotEqual(stub.seen[1]["session"], "s1")   # the id may be held by the session that fell over

    def test_an_answer_missing_from_the_text_goes_again_then_gives_up(self):
        stub = Stub([{"text": "I would rather explain."}, {"text": '{"said": "aye"}'}])
        got, events = self.call(stub, schema=self.ANSWER)
        self.assertEqual(got["data"], {"said": "aye"})
        self.assertIn("retry", [k for k, _ in events])
        with self.assertRaises(RuntimeError) as e:
            self.call(Stub([{"text": "no"}, {"text": "still no"}]), schema=self.ANSWER)
        self.assertIn("no structured output", str(e.exception))

    def test_a_cli_that_enforced_the_schema_is_believed(self):
        got, _ = self.call(Stub([{"data": {"said": "aye"}, "text": "ignored"}]), schema=self.ANSWER)
        self.assertEqual(got["data"], {"said": "aye"})

    def test_running_out_of_money_is_not_retried(self):
        stub = Stub([{"text": "", "subtype": "error_max_budget_usd"}])
        with self.assertRaises(RuntimeError):
            self.call(stub, schema=self.ANSWER)
        self.assertEqual(len(stub.seen), 1)

    def test_what_comes_back_is_the_seven_keys(self):
        got, _ = self.call(Stub([{"text": "hello", "cost": 0.5}]))
        self.assertEqual(sorted(got), ["cost", "data", "denials", "error", "seconds", "session", "text"])


def has_git() -> bool:
    return shutil.which("git") is not None


@unittest.skipUnless(has_git(), "the builder's turn commits, so a whole run needs git")
class WholeRun(unittest.TestCase):
    """Three days of a life, end to end, against a stand-in for the CLI.

    Subclassed once per agent, because a run is the only thing that proves an adapter: every
    stage of it goes through the one, and a sealed call that came back the wrong shape or a
    session that was not carried stops the run rather than failing quietly somewhere."""

    AGENT = ""              # the flag, left off for Claude so the default is exercised too
    CLI = "claude"          # what the adapter looks for on PATH
    FAKE = "fake_claude.py"

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        tmp = Path(cls.tmp.name)
        cls.home = tmp / "home"
        (cls.home / "owners").mkdir(parents=True)
        # The owner as the repo ships him: bible, disposition, events. The days are his own and not the repo's.
        shutil.copytree(REPO / "owners" / "piotr-mahon", cls.home / "owners" / "piotr-mahon",
                        ignore=shutil.ignore_patterns("life.db*"))
        cls.project = tmp / "thing"
        (cls.project / ".regent").mkdir(parents=True)
        (cls.project / ".regent" / "charter.md").write_text(CHARTER)
        bin_dir = tmp / "bin"
        bin_dir.mkdir()
        shim = bin_dir / cls.CLI
        shim.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{REPO / "tests" / cls.FAKE}" "$@"\n')
        shim.chmod(0o755)
        cls.env = {**os.environ, "REGENT_HOME": str(cls.home), "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}"}
        cls.env.pop("ANTHROPIC_API_KEY", None)
        cls.out = cls.regent("run", "--project", str(cls.project), "--owner", "piotr-mahon",
                             *(["--agent", cls.AGENT] if cls.AGENT else []),
                             "--days", "3", "--turns-per-day", "2", "--dream-gap", "1", "--new")
        cls.root = max((cls.home / "runs").glob("thing-*"))

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    @classmethod
    def tried(cls, *args) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, "-m", "regent", *args], cwd=REPO, env=cls.env,
                              capture_output=True, text=True, timeout=900)

    @classmethod
    def regent(cls, *args) -> str:
        p = cls.tried(*args)
        if p.returncode != 0:
            raise AssertionError(f"regent {' '.join(args)} failed:\n{p.stdout[-3000:]}\n{p.stderr[-3000:]}")
        return p.stdout

    def kinds(self) -> dict[str, int]:
        c = sqlite3.connect(f"file:{self.root / 'run.db'}?mode=ro", uri=True)
        rows = c.execute("SELECT kind, COUNT(*) FROM event GROUP BY kind").fetchall()
        c.close()
        return dict(rows)

    def test_it_finished_and_said_so(self):
        self.assertIn("stopped after", self.out)
        self.assertIn("digest:", self.out)

    def test_the_charter_was_read_out_loud(self):
        agent = self.AGENT or "claude"
        self.assertIn(f"charter: 3 days at 2 sittings a day, run by {agent}", self.out)
        # Only Claude Code can be handed the charter's domains, and a run that cannot says so at the start.
        if agent == "claude":
            self.assertIn("web off", self.out)
        else:
            self.assertIn(f"web is {agent}'s own sandbox to decide", self.out)

    def test_the_digest_is_written(self):
        digest = (self.root / "digest.md").read_text()
        self.assertIn("## Requirements", digest)
        self.assertIn("## Why he wants it, and how that moved", digest)
        self.assertIn("## What was stirring", digest)
        self.assertIn("## What he remembers of the project", digest)

    def test_the_ledger_has_what_the_page_reads(self):
        kinds = self.kinds()
        for kind in ("start", "dawn", "sitting", "reply", "taken", "readback", "field", "day",
                     "picture", "stake", "step_back", "check", "call", "summary"):
            self.assertIn(kind, kinds, f"no {kind} in the ledger: {sorted(kinds)}")
        self.assertTrue({"arrival", "spoon"} & set(kinds), f"neither an arrival nor a spoon: {sorted(kinds)}")

    def test_the_builder_worked_in_the_project(self):
        self.assertTrue((self.project / "built.txt").exists())
        log = subprocess.run(["git", "-C", str(self.project), "log", "--oneline"], capture_output=True, text=True)
        self.assertIn("a turn of the builder's", log.stdout)

    def state(self) -> dict:
        c = sqlite3.connect(str(self.root / "run.db"))
        try:
            return json.loads(c.execute("SELECT v FROM state WHERE k='run'").fetchone()[0])
        finally:
            c.close()

    def save(self, state: dict):
        c = sqlite3.connect(str(self.root / "run.db"))
        c.execute("INSERT OR REPLACE INTO state(k, v) VALUES('run', ?)", (json.dumps(state),))
        c.commit()
        c.close()

    def test_the_agent_is_the_runs_own(self):
        self.assertEqual(self.state()["agent"], self.AGENT or "claude")
        self.assertIn("--agent", self.regent("run", "--help"))

    def test_a_resume_under_another_agent_is_refused(self):
        """The builder's session and its memory of the work are inside the CLI that made them,
        so swapping one for another mid-run is refused rather than half honoured."""
        state = self.state()
        state["finished"] = False
        self.save(state)
        other = "codex" if (self.AGENT or "claude") != "codex" else "cursor"
        try:
            p = self.tried("run", "--project", str(self.project), "--owner", "piotr-mahon", "--agent", other)
            self.assertNotEqual(p.returncode, 0)
            self.assertIn(f"belongs to {self.AGENT or 'claude'}, not {other}", p.stdout + p.stderr)
            self.assertFalse(self.state()["finished"])   # it stopped before it did anything to the run
        finally:
            state["finished"] = True
            self.save(state)

    def test_the_state_is_resumable(self):
        state = self.state()
        for key in ("charter", "owner", "day_i", "turn", "reqs", "ideas", "field", "stakes", "counts", "session",
                    "agent"):
            self.assertIn(key, state)
        self.assertTrue(state["finished"])
        self.assertGreater(state["turn"], 0)

    def test_the_journal_reads_back(self):
        said = self.regent("journal", "piotr-mahon", "--last", "3")
        self.assertIn("# piotr-mahon, day", said)
        self.assertIn("## What is hanging over him", said)

    def test_the_page_exports_with_the_run_inside_it(self):
        out = Path(self.tmp.name) / "page.html"
        self.regent("watch", str(self.root), "--export", str(out))
        page = out.read_text()
        self.assertIn("daybook", page)
        self.assertNotIn('type="application/json">null<', page)
        raw = page.split('type="application/json">', 1)[1].split("</script>", 1)[0]
        data = json.loads(raw.replace("<\\/", "</"))
        self.assertEqual(data["run"], self.root.name)
        self.assertTrue(data["events"])

    def test_say_and_plant_reach_the_run(self):
        self.regent("say", str(self.root), "stop adding flags, I want it faster")
        self.regent("plant", str(self.root), "a story about a bridge that was measured twice")
        self.assertIn("I want it faster", (self.root / "inbox.md").read_text())
        self.assertIn("measured twice", (self.root / "plant.md").read_text())

    def test_an_unfinished_run_is_picked_up_where_it_stopped(self):
        state = self.state()
        turns_before = state["turn"]
        state["finished"], state["day_i"] = False, 1
        c = sqlite3.connect(str(self.root / "run.db"))
        c.execute("INSERT OR REPLACE INTO state(k, v) VALUES('run', ?)", (json.dumps(state),))
        c.commit()
        c.close()
        said = self.regent("run", "--project", str(self.project), "--owner", "piotr-mahon")
        self.assertIn("resuming", said)
        self.assertIn(self.root.name, said)
        after = self.state()
        self.assertGreater(after["turn"], turns_before)
        self.assertTrue(after["finished"])


class WholeRunOnCodex(WholeRun):
    """The same three days again, driven entirely by the Codex CLI's JSONL event stream."""

    AGENT = CLI = "codex"
    FAKE = "fake_codex.py"


class WholeRunOnCursor(WholeRun):
    """And again on Cursor, where nothing but the message binds and the schema is asked for in words."""

    AGENT, CLI = "cursor", "agent"
    FAKE = "fake_cursor.py"


if __name__ == "__main__":
    unittest.main()
