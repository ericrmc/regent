"""Spot checks, queries, and invented requirements."""

from __future__ import annotations

import unittest

from helpers import (
    HarnessCase,
    a_candidate,
    a_dispatch,
    a_requirement,
    a_wake_requirement,
    decision,
    fake,
    return_block,
)

from regent import requirements as req
from regent import spotcheck as sc
from regent.charter import parse_charter
from regent.config import Config
from regent.loop import Harness
from regent.runner import ModelResponse


class SpotCase(HarnessCase):
    def a_return(self, ctx, runner=None):
        """Run two turns so one return exists and has been read."""
        h = Harness(ctx)
        h.turn()
        h.turn()
        return h


class TestTheCall(SpotCase):
    def test_the_call_is_built_with_read_only_tools_and_nothing_else(self):
        ctx = self.boot(fake(wake=[decision()]))
        sc.run_spot_check(ctx, "Does it walk the folder?")
        calls = self.runner.calls_for("spot_check")
        self.assertEqual(len(calls), 1)
        c = calls[0]
        self.assertEqual(sorted(c.tools), ["Glob", "Grep", "Read"])
        for banned in ("Write", "Edit", "Bash", "NotebookEdit"):
            self.assertNotIn(banned, c.tools)
        self.assertFalse(c.toolless)
        self.assertEqual(c.cwd, str(self.project))
        self.assertEqual(c.permission_mode, "dontAsk")
        self.assertIsNone(c.agents)

    def test_only_the_findings_enter_the_manifold(self):
        ctx = self.boot(fake(wake=[decision()]))
        sc.run_spot_check(ctx, "What is there?")
        texts = " ".join(e.text for e in ctx.manifold.warm())
        self.assertIn("It does not resolve anchors at all.", texts)

    def test_source_text_never_reaches_an_assembled_judgement_context(self):
        """The source it read is gone when the call ends.

        A real file with a distinctive string sits in the project. The spot
        check reads the project, and only its findings are kept, so that string
        must never appear in the prompt where judgement happens.
        """
        marker = "ZZQ_SOURCE_MARKER_9471"
        (self.project / "linkcheck.py").write_text(
            f"def walk():\n    # {marker}\n    return []\n")
        runner = fake(wake=[decision()])
        runner.scripts["spot_check"] = [{
            "findings": "It walks the folder and misses anchors.",
            "verdicts": [], "gap": False, "openings": []}]
        ctx = self.boot(runner)
        sc.run_spot_check(ctx, "What is there?")
        Harness(ctx).wake([])
        prompt = runner.calls_for("wake")[0].prompt
        self.assertIn("It walks the folder and misses anchors.", prompt)
        self.assertNotIn(marker, prompt)
        self.assertNotIn(marker, " ".join(e.text for e in ctx.manifold.warm()))
        self.assertNotIn(marker, ctx.store.self_md.read_text())

    def test_the_findings_are_capped_in_words(self):
        runner = fake(wake=[decision()])
        runner.scripts["spot_check"] = [{
            "findings": "word " * 2000, "verdicts": [], "gap": False, "openings": []}]
        ctx = self.boot(runner)
        f = sc.run_spot_check(ctx, "q")
        self.assertLessEqual(len(f.findings.split()),
                             ctx.cfg.spot_check.findings_word_cap + 1)

    def test_a_failed_spot_check_is_logged_and_does_not_stop_the_turn(self):
        runner = fake(wake=[decision()])
        runner.scripts["spot_check"] = [ModelResponse(role="spot_check", is_error=True)]
        ctx = self.boot(runner)
        self.assertIsNone(sc.run_spot_check(ctx, "q"))
        rows = [r for r in ctx.ledger.all() if r["kind"] == "spot_check"]
        self.assertEqual(rows[0]["outcome"], "failed")

    def test_the_claims_come_from_the_return(self):
        from regent.returns import parse_return
        ret = parse_return(return_block(flags=[{"tier": "medium", "text": "anchors unchecked"}]))
        claims = sc.claims_from(ret)
        ids = [c["id"] for c in claims]
        self.assertIn("c1", ids)
        self.assertTrue(any(i.startswith("f") for i in ids))
        self.assertTrue(any(i.startswith("e") for i in ids))


class TestTriggers(SpotCase):
    def test_high_unease_triggers_a_look(self):
        ctx = self.boot(fake(wake=[decision()]))
        ctx.state.signals.unease = 1.0
        self.assertEqual(
            sc.should_spot_check(ctx, None, None, trust=0.9), "unease high")

    def test_low_trust_triggers_a_look(self):
        ctx = self.boot(fake(wake=[decision()]))
        self.assertEqual(
            sc.should_spot_check(ctx, None, None, trust=0.1), "trust low")

    def test_the_one_in_six_draw_replays_from_the_seed(self):
        def draws(seed):
            ctx = self.boot(fake(wake=[decision()]), seed=seed)
            return [bool(sc.should_spot_check(ctx, None, None, trust=0.6))
                    for _ in range(40)]
        a = draws(99)
        self.assertEqual(a, draws(99))
        self.assertTrue(any(a))
        self.assertFalse(all(a))

    def test_the_per_turn_budget_stops_further_looks(self):
        ctx = self.boot(fake(wake=[decision()]))
        ctx.state.signals.unease = 1.0
        ctx.state.spot_checks_this_turn = ctx.cfg.spot_check.max_per_turn
        self.assertEqual(sc.should_spot_check(ctx, None, None, trust=0.1), "")

    def test_disabling_it_stops_every_trigger(self):
        ctx = self.boot(fake(wake=[decision()]))
        ctx.cfg.spot_check.enabled = False
        ctx.state.signals.unease = 1.0
        self.assertEqual(sc.should_spot_check(ctx, None, None, trust=0.0), "")


class TestGapsAndTrust(SpotCase):
    def test_a_match_raises_trust(self):
        ctx = self.boot(fake(wake=[decision()]))
        f = sc.run_spot_check(ctx, "q")
        before = ctx.trust.get("k")
        after = sc.apply_trust(ctx, f, "k")
        self.assertGreater(after, before)

    def test_a_gap_drops_trust_hard_and_writes_friction(self):
        runner = fake(wake=[decision()])
        runner.scripts["spot_check"] = [{
            "findings": "It does not walk nested folders at all.",
            "verdicts": [{"claim_id": "c1", "verdict": "contradicted",
                          "note": "nested folders are skipped"}],
            "gap": True, "openings": []}]
        ctx = self.boot(runner)
        f = sc.run_spot_check(ctx, "q")
        self.assertTrue(f.gap)
        before = ctx.trust.get("k")
        after = sc.apply_trust(ctx, f, "k")
        self.assertLess(after, before - 0.3)
        friction = [e for e in ctx.manifold.warm() if e.texture == "friction"]
        self.assertTrue(any("does not match what the return claimed" in e.text
                            for e in friction))

    def test_a_gap_forces_full_reads_on_that_branch(self):
        runner = fake(wake=[decision(dispatches=[a_dispatch()]), decision()])
        runner.scripts["spot_check"] = [{
            "findings": "It is not there.", "verdicts": [], "gap": True,
            "openings": []}]
        ctx = self.boot(runner)
        h = Harness(ctx)
        h.turn()
        d = ctx.state.dispatch("d0001")
        f = sc.run_spot_check(ctx, "q", dispatch=d)
        h.after_spot_check(f, d)
        self.assertEqual(ctx.state.debt_for("obj-1"), ctx.cfg.attention.debt_cap)

    def test_a_gap_is_surfaced_to_the_next_judgement(self):
        runner = fake(wake=[decision(), decision()])
        runner.scripts["spot_check"] = [{
            "findings": "The tool reports nothing on a folder with two broken links.",
            "verdicts": [], "gap": True, "openings": []}]
        ctx = self.boot(runner)
        sc.run_spot_check(ctx, "q")
        Harness(ctx).wake([])
        prompt = runner.calls_for("wake")[0].prompt
        self.assertIn("a gap, the project does not match the return", prompt)
        self.assertIn("reports nothing on a folder", prompt)

    def test_an_opening_queues_a_bounded_drift(self):
        """Off by default now, since a cycle in the path delays the work."""
        runner = fake(wake=[decision(dispatches=[a_dispatch()]), decision()])
        runner.scripts["spot_check"] = [{
            "findings": "It works.", "verdicts": [], "gap": False,
            "openings": ["it could report duplicate targets too"]}]
        ctx = self.boot(runner)
        ctx.cfg.spot_check.opens_drift = True
        h = Harness(ctx)
        h.turn()
        d = ctx.state.dispatch("d0001")
        f = sc.run_spot_check(ctx, "q", dispatch=d)
        h.after_spot_check(f, d)
        self.assertTrue(ctx.state.pending_drift)
        self.assertIn("duplicate targets", ctx.state.pending_drift[0]["problem"])
        unfinished = [e for e in ctx.manifold.warm() if e.texture == "unfinished"]
        self.assertTrue(any("duplicate targets" in e.text for e in unfinished))


class TestInspectAndQuery(SpotCase):
    def test_the_agent_can_ask_to_go_and_look(self):
        ctx = self.boot(fake(wake=[decision(
            inspect=[{"question": "Does it handle nested folders?",
                      "dispatch_id": ""}])]))
        Harness(ctx).turn()
        calls = self.runner.calls_for("spot_check")
        self.assertEqual(len(calls), 1)
        self.assertIn("nested folders", calls[0].prompt)

    def test_inspect_is_budgeted(self):
        items = [{"question": f"q{i}", "dispatch_id": ""} for i in range(6)]
        ctx = self.boot(fake(wake=[decision(inspect=items)]))
        Harness(ctx).turn()
        self.assertLessEqual(len(self.runner.calls_for("spot_check")),
                             ctx.cfg.spot_check.max_per_turn)
        refused = [r for r in ctx.ledger.all()
                   if r["kind"] == "spot_check" and r.get("outcome") == "not granted"]
        self.assertTrue(refused)

    def test_a_query_resumes_the_orchestrators_session(self):
        runner = fake(wake=[decision(dispatches=[a_dispatch()]),
                            decision(query=[{"dispatch_id": "d0001",
                                             "question": "Which files did you change?",
                                             "assumption": ""}]),
                            decision()])
        ctx = self.boot(runner)
        h = Harness(ctx)
        h.turn()
        session = ctx.state.dispatch("d0001").session_id
        h.turn()
        asked = [c for c in runner.calls_for("orchestrator") if c.resume]
        self.assertTrue(asked)
        self.assertEqual(asked[-1].session_id, session)
        self.assertIn("Which files did you change?", asked[-1].prompt)
        self.assertEqual(sorted(asked[-1].tools), ["Glob", "Grep", "Read"])

    def test_a_query_with_no_session_is_logged_and_not_run(self):
        ctx = self.boot(fake(wake=[decision()]))
        self.assertEqual(sc.run_query(ctx, None, "anything?"), "")
        rows = [r for r in ctx.ledger.all() if r["kind"] == "query"]
        self.assertEqual(rows[0]["outcome"], "no session to resume")

    def test_queries_are_budgeted(self):
        runner = fake(wake=[decision(dispatches=[a_dispatch()]),
                            decision(query=[{"dispatch_id": "d0001", "question": f"q{i}",
                                             "assumption": ""}
                                            for i in range(5)]),
                            decision()])
        ctx = self.boot(runner)
        h = Harness(ctx)
        h.turn()
        before = len(runner.calls_for("orchestrator"))
        h.turn()
        asked = len(runner.calls_for("orchestrator")) - before
        self.assertLessEqual(asked, ctx.cfg.spot_check.queries_per_turn + 1)


class TestRequirementGate(unittest.TestCase):
    def setUp(self):
        import tempfile
        from pathlib import Path

        from helpers import CHARTER
        self.d = tempfile.TemporaryDirectory()
        p = Path(self.d.name) / "charter.md"
        p.write_text(CHARTER)
        self.ch = parse_charter(p)
        self.cfg = Config()

    def tearDown(self):
        self.d.cleanup()

    def gate(self, *cands, appetite=0.3):
        return req.requirement_gate(list(cands), self.ch, self.cfg, appetite)

    def test_a_good_requirement_passes(self):
        r = self.gate(a_requirement())
        self.assertEqual(len(r.passed), 1)
        self.assertEqual(r.filed, [])
        self.assertEqual(r.escalated, [])

    def test_a_requirement_that_does_not_say_how_it_serves_the_intent_is_filed(self):
        r = self.gate(a_requirement(serves_intent="  "))
        self.assertEqual(r.passed, [])
        self.assertIn("serves the intent", r.filed[0]["filed_reason"])

    def test_a_requirement_that_names_no_rework_is_filed(self):
        r = self.gate(a_requirement(rework=""))
        self.assertEqual(r.passed, [])
        self.assertIn("rework", r.filed[0]["filed_reason"])

    def test_a_requirement_beyond_the_remaining_appetite_is_filed(self):
        r = self.gate(a_requirement(appetite_share=0.9), appetite=0.1)
        self.assertEqual(r.passed, [])
        self.assertIn("appetite", r.filed[0]["filed_reason"])

    def test_a_requirement_that_changes_the_charter_becomes_a_process_note(self):
        """Not blocked and not escalated. He builds toward the charter he has."""
        r = self.gate(a_requirement(changes_charter=True,
                                    cost_note="it would serve a different audience"))
        self.assertEqual(r.passed, [])
        self.assertEqual(r.escalated, [])
        self.assertEqual(len(r.notes), 1)
        self.assertIn("contradicts a charter line", r.notes[0]["why"])

    def test_a_requirement_naming_a_refusal_is_filed(self):
        r = self.gate(a_requirement(
            text="It should make a network request to check each external link."))
        self.assertEqual(r.passed, [])
        self.assertIn("refusal", r.filed[0]["filed_reason"])

    def test_a_requirement_touching_a_reserved_class_escalates(self):
        r = self.gate(a_requirement(
            text="It should publish the report outside the project directory."))
        self.assertEqual(r.passed, [])
        self.assertEqual(len(r.escalated), 1)
        self.assertIn("reserved", r.escalated[0]["why"])

    def test_a_solution_is_left_to_the_other_gate(self):
        r = self.gate(a_candidate())
        self.assertEqual(r.passed, [])
        self.assertEqual(r.filed, [])
        self.assertEqual(r.escalated, [])


class TestRegisterAndAppetite(SpotCase):
    def test_a_requirement_is_recorded_with_its_origin_and_rework(self):
        ctx = self.boot(fake(wake=[decision(requirements=[a_wake_requirement(
            text="It should report a link to a file outside the folder.",
            serves_intent="The charter asks for broken internal links.",
            rework="The classifier is redone.",
            origin="the return on d0001",
            objective_id="obj-1")])]))
        Harness(ctx).turn()
        rows = [r for r in ctx.ledger.all() if r["kind"] == "requirement"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["id"], "req-0001")
        self.assertIn("classifier", rows[0]["rework"])
        self.assertTrue(rows[0]["origin"])
        self.assertEqual(len(ctx.requirements.rows), 1)

    def test_a_requirement_over_the_remaining_appetite_is_refused(self):
        ctx = self.boot(fake(wake=[decision()]))
        h = Harness(ctx)
        h.apply_requirements([a_wake_requirement(text="a", appetite_share=0.45)],
                             source="wake")
        h.apply_requirements([a_wake_requirement(text="b", appetite_share=0.45)],
                             source="wake")
        self.assertEqual(len(ctx.requirements.rows), 1)
        refused = [r for r in ctx.ledger.all()
                   if r["kind"] == "gate" and r.get("bucket") == "requirements"]
        self.assertTrue(refused)
        self.assertIn("appetite left", refused[0]["reason"])

    def test_the_wake_path_runs_the_same_gate_as_the_cycle(self):
        """Every requirement passes all four conditions, whatever produced it."""
        ctx = self.boot(fake(wake=[decision()]))
        h = Harness(ctx)
        h.apply_requirements([
            a_wake_requirement(text="no rework named", rework="  "),
            a_wake_requirement(text="no intent named", serves_intent=""),
            a_wake_requirement(
                text="It should make a network request to check each link."),
        ], source="wake")
        self.assertEqual(ctx.requirements.rows, [])
        reasons = [r["reason"] for r in ctx.ledger.all()
                   if r["kind"] == "gate" and r.get("bucket") == "requirements"]
        self.assertEqual(len(reasons), 3)
        self.assertTrue(any("rework" in r for r in reasons))
        self.assertTrue(any("serves the intent" in r for r in reasons))
        self.assertTrue(any("refusal" in r for r in reasons))

    def test_a_wake_requirement_that_changes_the_charter_becomes_a_note(self):
        ctx = self.boot(fake(wake=[decision()]))
        h = Harness(ctx)
        h.apply_requirements([a_wake_requirement(
            text="It should serve a whole team, not one person.",
            changes_charter=True)], source="wake")
        self.assertEqual(ctx.requirements.rows, [])
        self.assertEqual(ctx.state.open_escalations(), [])
        self.assertEqual(len(ctx.state.process_notes), 1)

    def test_appetite_left_falls_as_requirements_are_invented(self):
        ctx = self.boot(fake(wake=[decision()]))
        self.assertAlmostEqual(ctx.appetite_left(), 0.50)
        Harness(ctx).apply_requirements([{
            "text": "a", "serves_intent": "s", "rework": "r", "origin": "o",
            "objective_id": "", "appetite_share": 0.1}], source="wake")
        self.assertAlmostEqual(ctx.appetite_left(), 0.40)

    def test_the_charter_sets_the_appetite(self):
        ch = parse_charter("examples/charter.md")
        self.assertGreater(ch.appetite, 0)

    def test_a_requirement_reaches_the_next_wake_and_the_manifold(self):
        ctx = self.boot(fake(wake=[decision(requirements=[a_wake_requirement(
            text="It should report duplicate link targets.",
            serves_intent="fewer surprises for one person maintaining notes",
            rework="none", origin="a spot check", objective_id="")]), decision()]))
        h = Harness(ctx)
        h.turn()
        h.wake([])
        prompt = self.runner.calls_for("wake")[1].prompt
        self.assertIn("duplicate link targets", prompt)
        unfinished = [e for e in ctx.manifold.warm() if e.texture == "unfinished"]
        self.assertTrue(any("nobody asked for" in e.text for e in unfinished))


class TestDetectors(SpotCase):
    def test_the_timid_owner_detector_fires_on_a_period_with_none(self):
        ctx = self.boot(fake(wake=[decision()]))
        self.assertEqual(req.timid_owner(ctx.requirements, 5, ctx.cfg), "")
        msg = req.timid_owner(ctx.requirements, 30, ctx.cfg)
        self.assertIn("No requirement was invented", msg)

    def test_the_timid_owner_detector_is_quiet_when_one_was_invented(self):
        ctx = self.boot(fake(wake=[decision()]))
        ctx.state.turn = 30
        Harness(ctx).apply_requirements([{
            "text": "a", "serves_intent": "s", "rework": "r", "origin": "o",
            "objective_id": ""}], source="wake")
        self.assertEqual(req.timid_owner(ctx.requirements, 30, ctx.cfg), "")

    def test_the_trusting_owner_detector_fires_below_the_floor(self):
        ctx = self.boot(fake(wake=[decision()]))
        ctx.state.returns_read = 30
        ctx.state.spot_checks_total = 0
        self.assertIn("below the floor", req.trusting_owner(ctx.state, ctx.cfg))
        ctx.state.spot_checks_total = 5
        self.assertEqual(req.trusting_owner(ctx.state, ctx.cfg), "")

    def test_the_churn_detector_fires_on_a_reversal_with_the_same_trigger(self):
        ctx = self.boot(fake(wake=[decision()]))
        from regent.dispatch import Dispatch
        ctx.state.put_dispatch(Dispatch(id="d1", title="t", intent="i"))
        h = Harness(ctx)
        for _ in range(2):
            h.apply_amendments([{"dispatch_id": "d1", "direction": "redirect",
                                 "trigger": "the artefact looked wrong",
                                 "criterion": "do it the other way", "replaces": ""}])
        self.assertIn("same trigger", req.churn(ctx.ledger, ctx.cfg))

    def test_the_churn_detector_is_quiet_when_the_trigger_is_new(self):
        ctx = self.boot(fake(wake=[decision()]))
        from regent.dispatch import Dispatch
        ctx.state.put_dispatch(Dispatch(id="d1", title="t", intent="i"))
        h = Harness(ctx)
        h.apply_amendments([{"dispatch_id": "d1", "direction": "redirect",
                             "trigger": "the first return showed a slow walk",
                             "criterion": "a", "replaces": ""}])
        h.apply_amendments([{"dispatch_id": "d1", "direction": "redirect",
                             "trigger": "a spot check found nested folders skipped",
                             "criterion": "b", "replaces": ""}])
        self.assertEqual(req.churn(ctx.ledger, ctx.cfg), "")

    def test_the_detectors_reach_the_digest(self):
        ctx = self.boot(fake(wake=[decision()]))
        ctx.state.turn = 40
        ctx.state.returns_read = 30
        from regent.digest import build_digest
        text = build_digest(ctx, 0)
        self.assertIn("Detectors firing", text)
        self.assertIn("No requirement was invented", text)


if __name__ == "__main__":
    unittest.main()
