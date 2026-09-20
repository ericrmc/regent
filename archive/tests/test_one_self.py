"""Step 11. The person in the life is the owner of the project."""

from __future__ import annotations

import unittest

from helpers import HarnessCase, a_dispatch, decision, fake, return_block
from test_life import LifeCase, life_runner

from regent import attention
from regent import requirements as req
from regent import spotcheck as sc
from regent.config import Config
from regent.loop import Harness
from regent.returns import parse_return
from regent.runner import ModelResponse


def self_runner(**over):
    r = life_runner(**over)
    r.scripts["life_stake"] = [{
        "stake": "## Why I want this\n\nThe notes are the only thing I kept "
                 "after the house was cleared, and half the links in them go "
                 "nowhere now.",
        "threads": ["whether the notes are worth keeping at all"],
    }]
    r.scripts["self_md"] = [{
        "self_md": "# Objectives\n\n1. I want to know which links are broken.\n"
                   "\n## What I will not do\n\n- Never delete my own files.\n",
        "objectives": [{"id": "obj-1", "text": "I want to know which links "
                                               "are broken.", "weight": 1.0,
                        "charter_line": "A command line tool that reports "
                                        "broken internal links in a folder of "
                                        "markdown notes."}],
    }]
    return r


class TestTheStake(LifeCase):
    def test_the_bible_is_amended_and_not_rewritten(self):
        ctx = self.boot(self_runner(), cfg=self.cfg)
        ctx.life_writer.write_bible()
        before = ctx.life.bible()
        self.assertIn("Marta", before)
        ctx.life_writer.write_stake()
        after = ctx.life.bible()
        self.assertTrue(after.startswith(before.rstrip()))
        self.assertIn("Why I want this", after)
        self.assertIn("Marta", after)

    def test_the_stake_is_written_once_and_recorded(self):
        ctx = self.boot(self_runner(), cfg=self.cfg)
        ctx.life_writer.bootstrap()
        self.assertTrue(ctx.life.index().has_stake)
        self.assertEqual(len(self.runner.calls_for("life_stake")), 1)
        rows = [r for r in ctx.ledger.all()
                if r["kind"] == "life" and r.get("state") == "stake"]
        self.assertEqual(len(rows), 1)

    def test_a_life_already_under_way_gains_the_stake_without_losing_a_day(self):
        """The backstory is the life before the project. It stays valid."""
        ctx = self.boot(self_runner(), cfg=self.cfg)
        ctx.life_writer.write_bible()
        ctx.life_writer.write_day(backstory=True)
        ctx.life_writer.write_day(backstory=True)
        days_before = ctx.life.index().day_count
        first = (ctx.life.journal / "day-0001.md").read_text()
        ctx.life_writer.bootstrap()
        self.assertTrue(ctx.life.index().has_stake)
        self.assertGreaterEqual(ctx.life.index().day_count, days_before)
        self.assertEqual((ctx.life.journal / "day-0001.md").read_text(), first)

    def test_the_stake_is_given_the_charters_intent(self):
        ctx = self.boot(self_runner(), cfg=self.cfg)
        ctx.life_writer.write_bible()
        ctx.life_writer.write_stake()
        prompt = self.runner.calls_for("life_stake")[0].prompt
        self.assertIn("broken internal links", prompt)
        self.assertIn("Marta", prompt)

    def test_the_stake_enters_the_manifold_as_life(self):
        ctx = self.boot(self_runner(), cfg=self.cfg)
        ctx.life_writer.write_bible()
        ctx.life_writer.write_stake()
        texts = " ".join(e.text for e in ctx.manifold.warm() if e.synthetic)
        self.assertIn("after the house was cleared", texts)


class TestSelfInHisVoice(LifeCase):
    def test_self_md_is_written_from_the_charter_and_the_bible(self):
        ctx = self.boot(self_runner(), cfg=self.cfg)
        ctx.life_writer.bootstrap()
        text = ctx.store.self_md.read_text()
        self.assertIn("I want to know which links are broken.", text)
        prompt = self.runner.calls_for("self_md")[0].prompt
        self.assertIn("Marta", prompt)
        self.assertIn("Never make a network request", prompt)

    def test_the_objectives_it_names_become_the_runs_objectives(self):
        ctx = self.boot(self_runner(), cfg=self.cfg)
        ctx.life_writer.bootstrap()
        ids = [o["id"] for o in ctx.state.objectives]
        self.assertIn("obj-1", ids)
        obj = ctx.state.objective("obj-1")
        self.assertIn("broken", obj["text"])
        self.assertTrue(obj["charter_line"])

    def test_a_failed_self_call_leaves_the_seeded_self_in_place(self):
        runner = self_runner()
        runner.scripts["self_md"] = [ModelResponse(role="self_md", is_error=True)]
        ctx = self.boot(runner, cfg=self.cfg)
        ctx.life_writer.bootstrap()
        self.assertIn("Objectives", ctx.store.self_md.read_text())
        self.assertTrue(ctx.state.objectives)


class TestProjectDays(LifeCase):
    def with_a_return(self, cfg=None):
        cfg = cfg or self.cfg
        runner = self_runner(wake=[decision(dispatches=[a_dispatch()]), decision()])
        ctx = self.boot(runner, cfg=cfg)
        h = Harness(ctx)
        h.turn()
        h.turn()
        return ctx, runner

    def force_project_day(self, ctx):
        ctx.cfg.life.project_day_weight = 1.0
        ctx.cfg.life.project_day_weight_after_bad_return = 1.0

    def test_most_days_have_no_project_in_them(self):
        from regent import lifetables
        from regent.rng import Rng
        r = Rng(seed=3)
        days = [lifetables.roll_day(r, [], project_weight=0.18) for _ in range(60)]
        with_project = [d for d in days if d["project_today"]]
        self.assertGreater(len(with_project), 0)
        self.assertLess(len(with_project), 30)

    def test_a_backstory_day_never_carries_the_project(self):
        ctx = self.boot(self_runner(), cfg=self.cfg)
        self.force_project_day(ctx)
        ctx.life_writer.write_bible()
        ctx.life_writer.write_day(backstory=True)
        prompt = self.runner.calls_for("life_day")[-1].prompt
        self.assertIn("none", prompt.split("## The project")[1][:40])

    def test_a_project_day_gets_only_what_he_actually_saw(self):
        ctx, runner = self.with_a_return()
        self.force_project_day(ctx)
        ctx.life_writer.write_day()
        prompt = runner.calls_for("life_day")[-1].prompt
        block = prompt.split("## The project")[1].split("## What you return")[0]
        self.assertIn("r00001", block)
        self.assertIn("a report he read", block)

    def test_the_stored_whole_return_never_reaches_the_day_prompt(self):
        """He gets the cut view, not the return. The detail he was never shown
        must not arrive through the diary.
        """
        runner = self_runner(wake=[decision(dispatches=[a_dispatch()]), decision()])
        runner.scripts["orchestrator"] = [return_block(detail=[
            {"heading": "What was built",
             "body": "The checker walks the folder. "
                     "ZZQ_UNSEEN_DETAIL_4471 is buried in paragraph two."}])]
        cfg = self.cfg
        cfg.attention.band_full = 9.0
        cfg.attention.band_skim = 9.0
        cfg.attention.band_glance = 0.0
        cfg.attention.trust_floor_full_reads = -1.0
        ctx = self.boot(runner, cfg=cfg)
        h = Harness(ctx)
        h.turn()
        h.turn()
        self.force_project_day(ctx)
        ctx.life_writer.write_day()
        prompt = runner.calls_for("life_day")[-1].prompt
        self.assertNotIn("ZZQ_UNSEEN_DETAIL_4471", prompt)

    def test_source_never_reaches_the_day_prompt(self):
        marker = "ZZQ_SOURCE_9913"
        (self.project / "linkcheck.py").write_text(f"def walk():\n    # {marker}\n")
        ctx, runner = self.with_a_return()
        self.force_project_day(ctx)
        ctx.life_writer.write_day()
        prompt = runner.calls_for("life_day")[-1].prompt
        self.assertNotIn(marker, prompt)

    def test_a_spot_check_finding_reaches_the_day_with_its_id(self):
        ctx, runner = self.with_a_return()
        sc.run_spot_check(ctx, "does it walk nested folders?")
        self.force_project_day(ctx)
        ctx.life_writer.write_day()
        block = runner.calls_for("life_day")[-1].prompt.split("## The project")[1]
        self.assertIn("s0001", block)
        self.assertIn("what he found looking himself", block)

    def test_the_project_share_of_a_day_is_capped(self):
        ctx, runner = self.with_a_return()
        self.force_project_day(ctx)
        ctx.life_writer.write_day()
        prompt = runner.calls_for("life_day")[-1].prompt
        self.assertIn("at most a quarter of the words", prompt)
        self.assertIn("has stopped being a life", prompt)

    def test_the_harness_records_which_ids_were_offered(self):
        ctx, runner = self.with_a_return()
        self.force_project_day(ctx)
        ctx.life_writer.write_day()
        rows = [r for r in ctx.ledger.all()
                if r["kind"] == "life" and r.get("state") == "project_day"]
        self.assertEqual(len(rows), 1)
        self.assertIn("r00001", rows[0]["offered"])

    def test_a_bad_return_weights_the_project_day_up(self):
        cfg = Config()
        self.assertGreater(cfg.life.project_day_weight_after_bad_return,
                           cfg.life.project_day_weight)


class TestAssumptions(unittest.TestCase):
    def a_return(self, **over):
        return parse_return(return_block(
            assumptions=[{"text": "A link with no extension means a .md file.",
                          "why": "the fixture is written that way"}], **over))

    def test_assumptions_parse_from_the_contract(self):
        r = self.a_return()
        self.assertTrue(r.parsed)
        self.assertEqual(len(r.assumptions), 1)
        self.assertIn("no extension", r.assumptions[0].text)
        self.assertIn("fixture", r.assumptions[0].why)

    def test_a_return_with_no_assumptions_still_parses(self):
        r = parse_return(return_block())
        self.assertTrue(r.parsed)
        self.assertEqual(r.assumptions, [])

    def test_full_and_skim_carry_assumptions_and_glance_and_wave_do_not(self):
        cfg = Config()
        r = self.a_return()
        self.assertIn("no extension", attention.cut(r, attention.FULL, cfg))
        self.assertIn("no extension", attention.cut(r, attention.SKIM, cfg))
        self.assertNotIn("no extension", attention.cut(r, attention.GLANCE, cfg))
        self.assertNotIn("no extension", attention.cut(r, attention.WAVE, cfg))

    def test_a_skim_says_when_none_were_listed(self):
        cfg = Config()
        text = attention.cut(parse_return(return_block()), attention.SKIM, cfg)
        self.assertIn("ASSUMPTIONS", text)
        self.assertIn("(none listed)", text)

    def test_the_orchestrator_prompt_asks_for_them_and_how_to_defend_them(self):
        from regent.dispatch import SYSTEM
        self.assertIn("assumptions", SYSTEM)
        self.assertIn("took as given that the owner never said", SYSTEM)
        self.assertIn("You asked for it", SYSTEM)

    def test_the_plugin_skill_carries_the_sixth_part(self):
        from pathlib import Path

        from helpers import ROOT
        text = Path(ROOT / "plugin" / "skills" / "return-report" / "SKILL.md").read_text()
        self.assertIn("assumptions", text)
        example = parse_return(text)
        self.assertTrue(example.parsed)
        self.assertTrue(example.assumptions)


class TestChallenge(HarnessCase):
    def test_a_challenge_round_trips_through_the_resumed_session(self):
        runner = fake(wake=[
            decision(dispatches=[a_dispatch()]),
            decision(query=[{"dispatch_id": "d0001",
                             "question": "Why did you decide that?",
                             "assumption": "A link with no extension is a .md file."}]),
            decision()])
        runner.scripts["orchestrator"] = [
            return_block(),
            "The notes in the fixture are all written without extensions, and the "
            "criterion does not say. I would still choose it.",
        ]
        ctx = self.boot(runner)
        h = Harness(ctx)
        h.turn()
        session = ctx.state.dispatch("d0001").session_id
        h.turn()
        asked = [c for c in runner.calls_for("orchestrator") if c.resume]
        self.assertTrue(asked)
        self.assertEqual(asked[-1].session_id, session)
        self.assertIn("A link with no extension is a .md file.", asked[-1].prompt)
        self.assertIn("You asked for it", asked[-1].prompt)

    def test_the_answer_is_written_to_the_manifold(self):
        runner = fake(wake=[
            decision(dispatches=[a_dispatch()]),
            decision(query=[{"dispatch_id": "d0001", "question": "Why?",
                             "assumption": "Case is significant."}]),
            decision()])
        runner.scripts["orchestrator"] = [return_block(),
                                          "Because the filesystem here is not."]
        ctx = self.boot(runner)
        h = Harness(ctx)
        h.turn()
        h.turn()
        texts = " ".join(e.text for e in ctx.manifold.warm())
        self.assertIn("Because the filesystem here is not.", texts)

    def test_a_challenge_is_recorded_apart_from_a_plain_query(self):
        runner = fake(wake=[
            decision(dispatches=[a_dispatch()]),
            decision(query=[
                {"dispatch_id": "d0001", "question": "Why?",
                 "assumption": "Case is significant."},
                {"dispatch_id": "d0001", "question": "Which files?",
                 "assumption": ""}]),
            decision()])
        runner.scripts["orchestrator"] = [return_block(), "an answer"]
        ctx = self.boot(runner)
        h = Harness(ctx)
        h.turn()
        h.turn()
        challenges = [r for r in ctx.ledger.all() if r["kind"] == "challenge"]
        queries = [r for r in ctx.ledger.all() if r["kind"] == "query"]
        self.assertEqual(len(challenges), 1)
        self.assertEqual(len(queries), 1)
        self.assertEqual(challenges[0]["assumption"], "Case is significant.")
        self.assertEqual(ctx.state.challenges, 1)

    def test_listed_assumptions_are_recorded_when_a_return_lands(self):
        runner = fake(wake=[decision(dispatches=[a_dispatch()]), decision()])
        runner.scripts["orchestrator"] = [return_block(assumptions=[
            {"text": "one", "why": "a"}, {"text": "two", "why": "b"}])]
        ctx = self.boot(runner)
        h = Harness(ctx)
        h.turn()
        h.turn()
        rows = [r for r in ctx.ledger.all() if r["kind"] == "return_assumptions"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["assumptions"], ["one", "two"])


class TestUnchallengedDetector(HarnessCase):
    def test_the_detector_fires_on_a_period_with_assumptions_and_no_challenge(self):
        ctx = self.boot(fake(wake=[decision()]))
        ctx.state.turn = 40
        ctx.ledger.turn = 40
        ctx.ledger.write("return_assumptions", return_id="r1",
                         assumptions=["one", "two"])
        msg = req.unchallenged_assumptions(ctx.ledger, ctx.state, ctx.cfg)
        self.assertIn("none was", msg)

    def test_the_detector_is_quiet_when_one_was_challenged(self):
        ctx = self.boot(fake(wake=[decision()]))
        ctx.state.turn = 40
        ctx.ledger.turn = 40
        ctx.ledger.write("return_assumptions", return_id="r1", assumptions=["one"])
        ctx.ledger.write("challenge", dispatch_id="d1", assumption="one")
        self.assertEqual(req.unchallenged_assumptions(ctx.ledger, ctx.state, ctx.cfg), "")

    def test_the_detector_is_quiet_when_nothing_was_listed(self):
        ctx = self.boot(fake(wake=[decision()]))
        ctx.state.turn = 40
        self.assertEqual(req.unchallenged_assumptions(ctx.ledger, ctx.state, ctx.cfg), "")

    def test_it_reaches_the_digest(self):
        from regent.digest import build_digest
        ctx = self.boot(fake(wake=[decision()]))
        ctx.state.turn = 40
        ctx.ledger.turn = 40
        ctx.ledger.write("return_assumptions", return_id="r1", assumptions=["one"])
        self.assertIn("none was challenged", build_digest(ctx, 0))


class TestChallengesAreExported(HarnessCase):
    def test_the_series_and_the_export_carry_challenges(self):
        from regent.export import build_export
        runner = fake(wake=[
            decision(dispatches=[a_dispatch()]),
            decision(query=[{"dispatch_id": "d0001", "question": "Why?",
                             "assumption": "Case is significant."}]),
            decision()])
        runner.scripts["orchestrator"] = [
            return_block(assumptions=[{"text": "Case is significant.", "why": "x"}]),
            "Because the filesystem here is not.",
        ]
        ctx = self.boot(runner)
        h = Harness(ctx)
        h.turn()
        h.turn()
        ctx.save()
        row = ctx.store.read_jsonl(ctx.store.metrics)[-1]
        self.assertEqual(row["challenges"], 1)
        self.assertEqual(row["assumptions_listed"], 1)
        data = build_export(ctx.store.root)
        self.assertEqual(len(data["challenges"]), 1)
        self.assertEqual(data["challenges"][0]["assumption"], "Case is significant.")
        self.assertTrue(data["assumptions"])
        self.assertEqual(data["run"]["challenges"], 1)
        returns = [r for d in data["dispatches"] for r in d["returns"]]
        self.assertTrue(returns[0]["assumptions"])


if __name__ == "__main__":
    unittest.main()
