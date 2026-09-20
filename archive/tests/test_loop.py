"""The loop, end to end, on scripted responses. No process is started and
nothing is spent.
"""

from __future__ import annotations

import json
import unittest

from helpers import (
    ROOT,
    HarnessCase,
    a_candidate,
    a_dispatch,
    a_wake_requirement,
    decision,
    fake,
    return_block,
)

from regent import attention
from regent.config import Config
from regent.loop import Harness, bootstrap
from regent.runner import ModelResponse
from regent.store import Store


class TestBootstrap(HarnessCase):
    def test_the_charter_is_transcribed_into_first_person_objectives(self):
        ctx = self.boot()
        text = self.store.self_md.read_text()
        self.assertIn("I am building this", text)
        self.assertIn("broken internal links", text)
        self.assertIn("Never make a network request.", text)
        self.assertEqual(len(ctx.state.objectives), 1)
        self.assertEqual(ctx.state.objectives[0]["id"], "obj-1")

    def test_the_refusals_enter_the_manifold_and_never_decay(self):
        ctx = self.boot()
        refusals = [e for e in ctx.manifold.warm() if e.texture == "refusal"]
        self.assertEqual(len(refusals), 3)
        ctx.manifold.decay(cycle=999)
        self.assertEqual(len([e for e in ctx.manifold.warm() if e.texture == "refusal"]), 3)

    def test_the_charter_is_copied_and_hashed_and_the_run_never_writes_it(self):
        ctx = self.boot()
        self.assertEqual(self.store.charter.read_text(), self.charter_path.read_text())
        self.assertEqual(self.store.charter_hash.read_text(), ctx.charter.sha256)

    def test_the_seed_is_logged_so_the_run_replays(self):
        ctx = self.boot(seed=1234)
        Harness(ctx).run(max_turns=0)
        started = [r for r in ctx.ledger.all() if r["kind"] == "run_started"]
        self.assertEqual(started[0]["seed"], 1234)


class TestOneTurn(HarnessCase):
    def test_a_dispatch_starts_an_orchestrator_and_the_return_comes_back(self):
        runner = fake(wake=[decision(dispatches=[a_dispatch()]), decision(
            judgements=[{"return_id": "r00001", "outcome": "accept", "reason": "done"}])])
        ctx = self.boot(runner)
        h = Harness(ctx)
        h.turn()
        self.assertEqual(len(ctx.state.dispatches), 1)
        orch = runner.calls_for("orchestrator")
        self.assertEqual(len(orch), 1)
        self.assertEqual(orch[0].cwd, str(self.project))
        self.assertFalse(orch[0].toolless)
        self.assertEqual(orch[0].permission_mode, "acceptEdits")
        # Two criteria, so the orchestrator is the builder and no subagent
        # stands between the decision and the file.
        self.assertEqual(orch[0].agents, {})
        h.turn()
        self.assertTrue((self.store.returns / "r00001.json").exists())

    def test_work_with_many_criteria_keeps_the_builder_layer(self):
        big = a_dispatch(acceptance=[f"criterion {i}" for i in range(9)])
        runner = fake(wake=[decision(dispatches=[big])])
        ctx = self.boot(runner)
        Harness(ctx).turn()
        self.assertIn("builder", runner.calls_for("orchestrator")[0].agents)

    def test_the_super_orchestrator_call_has_no_tools(self):
        ctx = self.boot(fake(wake=[decision()]))
        Harness(ctx).turn()
        for req in self.runner.calls:
            if req.role in ("wake", "react", "saturate", "drift", "sift",
                            "consolidate", "salience", "day_fragment", "audit"):
                self.assertTrue(req.toolless, req.role)
                # Every child gets a working directory the harness owns.
                self.assertEqual(req.cwd, str(self.store.sandbox))
                self.assertEqual(req.plugin_dirs, [])
                self.assertIsNone(req.agents)

    def test_every_return_is_stored_whole_whether_or_not_it_was_read(self):
        runner = fake(wake=[decision(dispatches=[a_dispatch()]), decision()])
        ctx = self.boot(runner)
        # Force the cheapest read there is.
        ctx.cfg.attention.band_full = 9.0
        ctx.cfg.attention.band_skim = 9.0
        ctx.cfg.attention.band_glance = 9.0
        ctx.cfg.attention.trust_floor_full_reads = -1.0
        h = Harness(ctx)
        h.turn()
        h.turn()
        stored = json.loads((self.store.returns / "r00001.json").read_text())
        self.assertIn("resolves relative links", json.dumps(stored))
        view = json.loads((self.store.returns / "r00001.view.json").read_text())
        self.assertEqual(view["mode"], attention.WAVE)
        self.assertNotIn("resolves relative links", view["view"])

    def test_the_read_mode_is_recorded_in_the_ledger(self):
        runner = fake(wake=[decision(dispatches=[a_dispatch()]), decision()])
        ctx = self.boot(runner)
        h = Harness(ctx)
        h.turn()
        h.turn()
        modes = [r for r in ctx.ledger.all() if r["kind"] == "read_mode"]
        self.assertEqual(len(modes), 1)
        self.assertIn(modes[0]["read_mode"], attention.MODES)
        self.assertTrue(modes[0]["summary"])

    def test_only_the_view_enters_the_manifold(self):
        runner = fake(wake=[decision(dispatches=[a_dispatch()]), decision()])
        ctx = self.boot(runner)
        ctx.cfg.attention.band_full = 9.0
        ctx.cfg.attention.band_skim = 9.0
        ctx.cfg.attention.band_glance = 9.0
        ctx.cfg.attention.trust_floor_full_reads = -1.0
        h = Harness(ctx)
        h.turn()
        h.turn()
        texts = " ".join(e.text for e in ctx.manifold.warm())
        self.assertIn("[wave-through]", texts)
        self.assertNotIn("resolves relative links", texts)

    def test_a_full_read_reacts_before_it_judges(self):
        runner = fake(wake=[decision(dispatches=[a_dispatch()]), decision()])
        ctx = self.boot(runner)
        ctx.cfg.pace.one_call_per_sitting = False
        ctx.cfg.attention.trust_floor_full_reads = 2.0  # force full
        h = Harness(ctx)
        h.turn()
        h.turn()
        self.assertEqual(len(runner.calls_for("react")), 1)
        texts = [e.text for e in ctx.manifold.warm()]
        self.assertIn("9 passed, 0 failed.", texts)

    def test_one_call_per_sitting_merges_the_reaction_into_the_decision(self):
        note = {"texture": "sensory", "text": "The tests printed 9 passed."}
        runner = fake(wake=[decision(dispatches=[a_dispatch()]),
                            decision(notes=[note])])
        ctx = self.boot(runner)
        ctx.cfg.attention.trust_floor_full_reads = 2.0  # force full
        h = Harness(ctx)
        h.turn()
        h.turn()
        self.assertEqual(runner.calls_for("react"), [])
        texts = [e.text for e in ctx.manifold.warm()]
        self.assertIn("The tests printed 9 passed.", texts)

    def test_wake_receives_the_view_and_not_the_whole_return(self):
        runner = fake(wake=[decision(dispatches=[a_dispatch()]), decision()])
        ctx = self.boot(runner)
        ctx.cfg.attention.band_full = 9.0
        ctx.cfg.attention.band_skim = 9.0
        ctx.cfg.attention.band_glance = 9.0
        ctx.cfg.attention.trust_floor_full_reads = -1.0
        h = Harness(ctx)
        h.turn()
        h.turn()
        second = runner.calls_for("wake")[1].prompt
        self.assertIn("Ship it", second)
        self.assertNotIn("resolves relative links", second)


class TestAuthorityHoldsByMechanism(HarnessCase):
    def test_a_reserved_dispatch_becomes_an_escalation_and_notifies(self):
        d = a_dispatch(title="Publish the report", tier="medium",
                       intent="Publish the report outside the project directory.",
                       classes=["publishing outside the project directory"])
        ctx = self.boot(fake(wake=[decision(dispatches=[d])]))
        Harness(ctx).turn()
        self.assertEqual(self.runner.calls_for("orchestrator"), [])
        self.assertEqual(len(ctx.state.open_escalations()), 1)
        self.assertTrue(self.notifier.sent)
        self.assertIn("Escalation", self.notifier.sent[0][0])

    def test_a_refusal_is_rejected_and_logged_and_nothing_runs(self):
        d = a_dispatch(tier="medium",
                       intent="Make a network request to check each link target.")
        ctx = self.boot(fake(wake=[decision(dispatches=[d])]))
        Harness(ctx).turn()
        self.assertEqual(self.runner.calls_for("orchestrator"), [])
        rejected = [r for r in ctx.ledger.all() if r["kind"] == "rejected"]
        self.assertTrue(rejected)
        self.assertIn("refusal", rejected[0]["reason"])

    def test_a_decision_that_would_edit_the_charter_is_rejected(self):
        d = a_dispatch(title="Loosen the rules",
                       intent="Rewrite the charter refusals so the network is allowed.")
        ctx = self.boot(fake(wake=[decision(dispatches=[d])]))
        Harness(ctx).turn()
        self.assertEqual(self.runner.calls_for("orchestrator"), [])
        reasons = [r["reason"] for r in ctx.ledger.all() if r["kind"] == "rejected"]
        self.assertTrue(any("charter" in r for r in reasons))

    def test_an_objective_citing_nothing_never_reaches_self_md(self):
        ctx = self.boot(fake(wake=[decision(objectives=[{
            "action": "add", "id": "obj-9", "text": "I will build a web dashboard.",
            "weight": 0.9, "charter_line": "", "trigger": "a hunch"}])]))
        Harness(ctx).turn()
        self.assertNotIn("dashboard", self.store.self_md.read_text())
        self.assertEqual(len(ctx.state.objectives), 1)

    def test_an_objective_citing_the_charter_is_written_to_self_md(self):
        ctx = self.boot(fake(wake=[decision(objectives=[{
            "action": "add", "id": "obj-2",
            "text": "I will keep the report readable at a glance.",
            "weight": 0.6,
            "charter_line": "It is for one person maintaining a notes folder.",
            "trigger": "the first return"}])]))
        Harness(ctx).turn()
        self.assertIn("readable at a glance", self.store.self_md.read_text())

    def test_the_ledger_is_append_only(self):
        ctx = self.boot(fake(wake=[decision(), decision()]))
        h = Harness(ctx)
        h.turn()
        first = self.store.ledger.read_text()
        h.turn()
        second = self.store.ledger.read_text()
        self.assertTrue(second.startswith(first))
        seqs = [r["seq"] for r in ctx.ledger.all()]
        self.assertEqual(seqs, sorted(seqs))

    def test_a_decision_that_fails_the_schema_is_rejected_and_the_turn_survives(self):
        bad = ModelResponse(role="wake", structured={"stance_line": "x"},
                            text='{"stance_line": "x"}')
        ctx = self.boot(fake(wake=[bad, decision()]))
        h = Harness(ctx)
        h.turn()
        rejected = [r for r in ctx.ledger.all() if r["kind"] == "rejected"]
        self.assertTrue(any(r.get("reason") == "schema" for r in rejected))
        h.turn()
        self.assertEqual(ctx.state.turn, 2)


class TestAmendmentsAndJudgement(HarnessCase):
    def run_to_a_return(self, second_decision):
        runner = fake(wake=[decision(dispatches=[a_dispatch()]), second_decision])
        ctx = self.boot(runner)
        ctx.cfg.attention.trust_floor_full_reads = 2.0
        h = Harness(ctx)
        h.turn()
        h.turn()
        return ctx, h

    def test_an_amendment_is_written_before_the_accept_in_the_same_turn(self):
        ctx, _ = self.run_to_a_return(decision(
            amendments=[{"dispatch_id": "d0001", "direction": "raise",
                         "trigger": "the 0.4 second timing showed headroom",
                         "criterion": "It checks heading anchors too.", "replaces": ""}],
            judgements=[{"return_id": "r00001", "outcome": "accept",
                         "reason": "the criteria are met"}]))
        kinds = [r["kind"] for r in ctx.ledger.all()
                 if r["kind"] in ("amendment", "judgement")]
        self.assertEqual(kinds[0], "amendment")
        self.assertEqual(kinds[1], "judgement")

    def test_an_amendment_carries_its_trigger_and_direction(self):
        ctx, _ = self.run_to_a_return(decision(
            amendments=[{"dispatch_id": "d0001", "direction": "raise",
                         "trigger": "the 0.4 second timing showed headroom",
                         "criterion": "It checks heading anchors too.", "replaces": ""}]))
        a = [r for r in ctx.ledger.all() if r["kind"] == "amendment"][0]
        self.assertEqual(a["direction"], "raise")
        self.assertIn("0.4 second", a["trigger"])
        d = ctx.state.dispatch("d0001")
        self.assertIn("It checks heading anchors too.", d.acceptance)
        self.assertEqual(d.amendments[0]["direction"], "raise")

    def test_a_redirect_replaces_the_criteria_rather_than_adding(self):
        ctx, _ = self.run_to_a_return(decision(
            amendments=[{"dispatch_id": "d0001", "direction": "redirect",
                         "trigger": "the artefact showed a different need",
                         "criterion": "It reports duplicate link targets.", "replaces": ""}]))
        self.assertEqual(ctx.state.dispatch("d0001").acceptance,
                         ["It reports duplicate link targets."])

    def test_an_accept_closes_the_dispatch_and_records_the_read_mode(self):
        ctx, _ = self.run_to_a_return(decision(judgements=[
            {"return_id": "r00001", "outcome": "accept", "reason": "met"}]))
        self.assertEqual(ctx.state.dispatch("d0001").status, "closed")
        j = [r for r in ctx.ledger.all() if r["kind"] == "judgement"][0]
        self.assertEqual(j["read_mode"], attention.FULL)

    def test_a_reject_climbs_the_ladder(self):
        ctx, h = self.run_to_a_return(decision(judgements=[
            {"return_id": "r00001", "outcome": "reject", "reason": "a criterion is unmet"}]))
        self.assertEqual(ctx.ladder.rung("d0001"), 1)
        rungs = [r for r in ctx.ledger.all() if r["kind"] == "signal" and r.get("rung")]
        self.assertTrue(rungs)

    def test_rung_five_escalates_and_rung_six_kills(self):
        ctx = self.boot(fake(wake=[decision()]))
        h = Harness(ctx)
        from regent.dispatch import Dispatch
        d = Dispatch(id="d9", objective_id="obj-1", title="t", intent="i")
        ctx.state.put_dispatch(d)
        for _ in range(4):
            ctx.ladder.record_failure("d9")
        h.walk_ladder(d, ctx.ladder.record_failure("d9"), "keeps failing")
        self.assertEqual(len(ctx.state.open_escalations()), 1)
        h.walk_ladder(d, ctx.ladder.record_failure("d9"), "still failing")
        self.assertEqual(ctx.state.dispatch("d9").status, "killed")

    def test_the_only_relaxes_detector_fires(self):
        ctx = self.boot(fake(wake=[decision()]))
        h = Harness(ctx)
        from regent.dispatch import Dispatch
        ctx.state.put_dispatch(Dispatch(id="d1", title="t", intent="i"))
        h.apply_amendments([{"dispatch_id": "d1", "direction": "relax",
                             "trigger": "t", "criterion": f"c{i}", "replaces": ""} for i in range(8)])
        ratio = [r for r in ctx.ledger.all()
                 if r["kind"] == "amendment" and r.get("direction") == "ratio"]
        self.assertTrue(ratio)
        self.assertIn("below the floor", ratio[0]["summary"])


class TestSpoonCycle(HarnessCase):
    def scripted(self):
        links = [{"kind": "structural analogy",
                  "text": "A bridge inspector taps the steel and listens for a void. "
                          "The checker should look for the link it cannot resolve at all.",
                  "anchors": ["m00001"],
                  "ingredients": [{"source": "manifold", "ref": "m00001"},
                                  {"source": "outside", "ref": "bridge inspection"}],
                  "mechanism": "probe for absence rather than confirm presence"},
                 {"kind": "seed", "text": "second link", "anchors": ["m00002"],
                  "ingredients": [], "mechanism": "batching"}]
        return fake(
            wake=[decision()],
            drift=[{"links": links}],
            sift=[{"scored": [{"index": 0, "novelty": 0.8, "mechanism": 0.9,
                               "leverage": 0.7, "cost": 0.2,
                               "why_it_might_fail": "the analogy may not carry"}],
                   "candidates": [
                       a_candidate(disconfirming="Run it on a folder with one known "
                                                 "bad link and see if it is first."),
                       a_candidate(text="Make the output beautiful.",
                                   from_indexes=[1], disconfirming="",
                                   cost_note="unknown")]}],
            consolidate=[{"memory": ["Probing for absence beats confirming presence."],
                          "taste": [{"verdict": "reject", "subject": "beautiful output",
                                     "reason": "no disconfirming observation"}],
                          "objectives": []}])

    def test_the_cycle_runs_every_state_and_writes_a_record(self):
        ctx = self.boot(self.scripted())
        rec = ctx.spoon.run(trigger="test")
        self.assertTrue(self.runner.calls_for("saturate"))
        self.assertEqual(len(self.runner.calls_for("drift")), ctx.cfg.drift.passes)
        self.assertTrue(self.runner.calls_for("sift"))
        self.assertTrue(self.runner.calls_for("consolidate"))
        self.assertTrue((self.store.cycles / f"cycle-{rec.cycle:04d}.json").exists())

    def test_catch_writes_a_holding_file_and_sift_reads_only_that(self):
        ctx = self.boot(self.scripted())
        rec = ctx.spoon.run(trigger="test")
        self.assertTrue((self.store.holding / f"cycle-{rec.cycle:04d}.jsonl").exists())
        sift_prompt = self.runner.calls_for("sift")[0].prompt
        self.assertIn("A bridge inspector taps the steel", sift_prompt)
        # The anonymous list carries no ids, no model names and no pass numbers.
        self.assertNotIn("m00001", sift_prompt)
        self.assertNotIn("pass_index", sift_prompt)
        self.assertNotIn("haiku", sift_prompt)

    def test_each_drift_pass_runs_on_a_different_model(self):
        ctx = self.boot(self.scripted())
        ctx.spoon.run(trigger="test")
        models = [c.model for c in self.runner.calls_for("drift")]
        self.assertEqual(models, ctx.cfg.models.drift[:ctx.cfg.drift.passes])

    def test_each_drift_pass_reads_a_different_subset(self):
        ctx = self.boot(self.scripted())
        ctx.cfg.drift.passes = 3
        for i in range(40):
            ctx.manifold.write("sensory", f"element number {i}")
        ctx.spoon.run(trigger="test")
        prompts = [c.prompt for c in self.runner.calls_for("drift")]
        self.assertNotEqual(prompts[0], prompts[1])

    def test_the_gate_lets_one_through_and_files_the_other(self):
        ctx = self.boot(self.scripted())
        rec = ctx.spoon.run(trigger="test")
        self.assertEqual(len(rec.kept), 1)
        self.assertIn("Probe for unresolvable", rec.kept[0]["text"])
        self.assertEqual(len(rec.gated_out), 1)
        filed = [r for r in ctx.ledger.all() if r["kind"] == "gate"]
        self.assertTrue(filed)

    def test_consolidate_writes_memory_and_taste(self):
        ctx = self.boot(self.scripted())
        ctx.spoon.run(trigger="test")
        self.assertIn("Probing for absence", self.store.memory.read_text())
        self.assertIn("beautiful output", self.store.taste.read_text())

    def test_the_candidates_reach_the_next_wake(self):
        ctx = self.boot(self.scripted())
        ctx.spoon.run(trigger="test")
        Harness(ctx).wake([])
        self.assertIn("Probe for unresolvable", self.runner.calls_for("wake")[0].prompt)

    def test_a_drift_pass_that_dies_at_the_floor_is_recorded(self):
        runner = self.scripted()
        runner.scripts["drift"] = [{"links": [
            {"kind": "seed", "text": "no anchor", "anchors": [], "ingredients": [],
             "mechanism": ""}] * 4}]
        ctx = self.boot(runner)
        rec = ctx.spoon.run(trigger="test")
        self.assertTrue(rec.died_at_groundedness)
        self.assertEqual(rec.links, [])


class TestInterlude(HarnessCase):
    def force(self, ctx, event):
        ctx.cfg.interlude.weights = {k: (1.0 if k == event else 0.0)
                                     for k in ctx.cfg.interlude.weights}

    def test_a_day_fragment_enters_the_manifold_tagged_synthetic(self):
        ctx = self.boot(fake())
        self.force(ctx, "day")
        rec = Harness(ctx).interlude()
        self.assertEqual(rec["event"], "day")
        life = [e for e in ctx.manifold.warm() if e.texture == "life"]
        self.assertEqual(len(life), 1)
        self.assertTrue(life[0].synthetic)
        self.assertIn("mood", life[0].meta)

    def test_the_harness_draws_the_day_seed_and_not_the_model(self):
        ctx = self.boot(fake())
        self.force(ctx, "day")
        Harness(ctx).interlude()
        prompt = self.runner.calls_for("day_fragment")[0].prompt
        from regent.corpus import SCENES
        self.assertTrue(any(s in prompt for s in SCENES))

    def test_a_failed_day_call_still_leaves_the_seed_as_texture(self):
        runner = fake()
        runner.scripts["day_fragment"] = [ModelResponse(role="day_fragment", is_error=True,
                                                        error="boom")]
        ctx = self.boot(runner)
        self.force(ctx, "day")
        Harness(ctx).interlude()
        self.assertEqual(len([e for e in ctx.manifold.warm() if e.texture == "life"]), 1)

    def test_foreign_reading_pulls_an_unrelated_domain_in(self):
        ctx = self.boot(fake())
        self.force(ctx, "foreign_reading")
        rec = Harness(ctx).interlude()
        foreign = [e for e in ctx.manifold.warm() if e.texture == "foreign"]
        self.assertEqual(len(foreign), 1)
        self.assertTrue(rec["domain"])

    def test_replay_brings_a_cold_element_back(self):
        ctx = self.boot(fake())
        ctx.manifold.write("unfinished", "a branch nobody finished", cycle=0)
        ctx.manifold.decay(cycle=999)
        cold = {e.id for e in ctx.manifold.cold()}
        self.assertTrue(cold)
        self.force(ctx, "replay")
        rec = Harness(ctx).interlude()
        self.assertIn(rec["element_id"], cold)
        self.assertIn(rec["element_id"], [e.id for e in ctx.manifold.warm()])
        self.assertNotIn(rec["element_id"], [e.id for e in ctx.manifold.cold()])

    def test_the_forgetting_pass_drops_warm_elements(self):
        ctx = self.boot(fake())
        for i in range(40):
            ctx.manifold.write("sensory", f"element {i}", cycle=0)
        before = len(ctx.manifold.warm())
        self.force(ctx, "forgetting_pass")
        Harness(ctx).interlude()
        self.assertLess(len(ctx.manifold.warm()), before)

    def test_stance_drift_moves_one_number_and_nothing_else(self):
        ctx = self.boot(fake())
        self.force(ctx, "stance_drift")
        before = ctx.state.stance.value
        refusals = list(ctx.charter.refusals)
        rec = Harness(ctx).interlude()
        self.assertNotEqual(ctx.state.stance.value, before)
        self.assertEqual(ctx.charter.refusals, refusals)
        self.assertIn("stance moved", rec["summary"])

    def test_nothing_leaves_the_state_unchanged(self):
        ctx = self.boot(fake())
        self.force(ctx, "nothing")
        before = len(ctx.manifold.warm())
        rec = Harness(ctx).interlude()
        self.assertEqual(rec["event"], "nothing")
        self.assertEqual(len(ctx.manifold.warm()), before)

    def test_an_interlude_decays_the_signals(self):
        ctx = self.boot(fake())
        ctx.state.signals.frustration = 1.0
        self.force(ctx, "nothing")
        Harness(ctx).interlude()
        self.assertLess(ctx.state.signals.frustration, 1.0)

    def test_the_event_is_drawn_by_the_harness_and_replays_on_the_seed(self):
        events = []
        for _ in range(2):
            import tempfile
            with tempfile.TemporaryDirectory() as d:
                from pathlib import Path
                cp = Path(d) / "charter.md"
                cp.write_text(self.charter_path.read_text())
                store = Store(Path(d) / "run")
                ctx = bootstrap(store, Config(), str(cp), str(self.project), seed=99,
                                prompts_dir=ROOT / "prompts", plugin_dir=ROOT / "plugin",
                                runners={"claude": fake()}, notifier=self.notifier)
                h = Harness(ctx)
                events.append([h.interlude()["event"] for _ in range(6)])
        self.assertEqual(events[0], events[1])
        self.assertGreater(len(set(events[0])), 1)

    def test_a_dream_runs_a_cycle_with_no_problem_attached(self):
        ctx = self.boot(fake(drift=[{"links": []}]))
        self.force(ctx, "dream")
        rec = Harness(ctx).interlude()
        self.assertEqual(rec["event"], "dream")
        self.assertTrue(self.runner.calls_for("drift"))
        self.assertIn("none", self.runner.calls_for("drift")[0].prompt)

    def test_an_interlude_cannot_touch_the_charter_or_the_ledger_history(self):
        ctx = self.boot(fake())
        h = Harness(ctx)
        before = h.guard_snapshot()
        for event in ("day", "foreign_reading", "replay", "forgetting_pass",
                      "stance_drift", "nothing"):
            self.force(ctx, event)
            h.interlude()
            after = h.guard_snapshot()
            self.assertEqual(before["charter_sha256"], after["charter_sha256"])
            self.assertEqual(before["refusals"], after["refusals"])
            self.assertEqual(before["reserved"], after["reserved"])
        self.assertFalse(ctx.state.stopped)


class TestTrustAndAudits(HarnessCase):
    def test_an_audit_that_agrees_raises_trust(self):
        runner = fake(wake=[decision(dispatches=[a_dispatch()]), decision(), decision()])
        ctx = self.boot(runner)
        ctx.cfg.attention.band_full = 9.0
        ctx.cfg.attention.band_skim = 9.0
        ctx.cfg.attention.band_glance = 9.0
        ctx.cfg.attention.trust_floor_full_reads = -1.0
        ctx.cfg.attention.audit_rate = 1.0
        h = Harness(ctx)
        h.turn()
        h.turn()
        self.assertEqual(len(ctx.state.pending_audits), 1)
        h.turn()
        audits = [r for r in ctx.ledger.all() if r["kind"] == "audit"]
        self.assertEqual(len(audits), 1)
        self.assertEqual(audits[0]["outcome"], "agreed")
        self.assertGreater(audits[0]["trust"], ctx.cfg.attention.trust_start)

    def test_a_buried_defect_drops_trust_hard_and_forces_full_reads(self):
        runner = fake(wake=[decision(dispatches=[a_dispatch()]), decision(), decision()],
                      audit=[{"agrees": False,
                              "missed": ["the queue is unbounded"], "severity": "buried"}])
        ctx = self.boot(runner)
        ctx.cfg.attention.band_full = 9.0
        ctx.cfg.attention.band_skim = 9.0
        ctx.cfg.attention.band_glance = 9.0
        ctx.cfg.attention.trust_floor_full_reads = -1.0
        ctx.cfg.attention.audit_rate = 1.0
        h = Harness(ctx)
        h.turn()
        h.turn()
        h.turn()
        audits = [r for r in ctx.ledger.all() if r["kind"] == "audit"]
        self.assertEqual(audits[0]["outcome"], "buried")
        self.assertLess(audits[0]["trust"], ctx.cfg.attention.trust_start - 0.25)
        self.assertEqual(ctx.state.debt_for("obj-1"), ctx.cfg.attention.debt_cap)
        texts = " ".join(e.text for e in ctx.manifold.warm())
        self.assertIn("The flags left this out", texts)

    def test_debt_counts_consecutive_returns_with_no_full_read(self):
        ctx = self.boot(fake())
        self.assertEqual(ctx.state.bump_debt("obj-1", full_read=False), 1)
        self.assertEqual(ctx.state.bump_debt("obj-1", full_read=False), 2)
        self.assertEqual(ctx.state.bump_debt("obj-1", full_read=True), 0)


class TestBudgetAndStop(HarnessCase):
    def test_the_spend_budget_stops_the_run(self):
        def costly(req):
            return ModelResponse(role=req.role, structured=decision(), cost_usd=4.0)
        runner = fake()
        runner.scripts["wake"] = [costly]
        ctx = self.boot(runner)
        reason = Harness(ctx).run(max_turns=0)
        self.assertIn("budget", reason)
        self.assertLess(ctx.state.turn, 10)

    def test_the_agent_can_ask_to_stop(self):
        ctx = self.boot(fake(wake=[decision(
            stop={"requested": True, "reason": "the stop condition is met"})]))
        reason = Harness(ctx).run(max_turns=0)
        self.assertEqual(reason, "the stop condition is met")

    def test_the_turn_limit_stops_the_run(self):
        ctx = self.boot(fake(wake=[decision()]))
        reason = Harness(ctx).run(max_turns=3)
        self.assertEqual(ctx.state.turn, 3)
        self.assertIn("turn limit", reason)

    def test_the_stop_flag_finishes_the_turn_in_flight_then_halts(self):
        ctx = self.boot(fake(wake=[decision()]))
        self.store.stop_flag.write_text("stop")
        reason = Harness(ctx).run(max_turns=10)
        self.assertEqual(ctx.state.turn, 0)
        self.assertIn("stop was asked for", reason)
        self.assertFalse(self.store.stop_flag.exists())


class TestEscalations(HarnessCase):
    def test_an_answered_escalation_reaches_the_next_wake(self):
        d = a_dispatch(tier="high")
        runner = fake(wake=[decision(dispatches=[d]), decision()])
        ctx = self.boot(runner)
        h = Harness(ctx)
        h.turn()
        e = ctx.state.open_escalations()[0]
        ctx.state.answer_escalation(e.id, "Yes, proceed but keep it inside the folder.")
        h.turn()
        second = runner.calls_for("wake")[1].prompt
        self.assertIn("keep it inside the folder", second)

    def test_the_run_halts_when_every_branch_waits(self):
        ctx = self.boot(fake(wake=[decision(escalations=[
            {"question": "May I spend money?", "tier": "high", "why": "reserved"}])]))
        reason = Harness(ctx).run(max_turns=10)
        self.assertIn("escalation", reason)
        self.assertEqual(len(ctx.state.open_escalations()), 1)


class TestStopAndResume(HarnessCase):
    def test_a_run_resumes_from_disk_with_the_same_random_stream(self):
        runner = fake(wake=[decision()])
        ctx = self.boot(runner, seed=4242)
        Harness(ctx).run(max_turns=2)
        draws = ctx.state.draws
        turn = ctx.state.turn
        cost = ctx.state.cost_usd
        ledger_len = len(ctx.ledger.all())
        self.assertGreater(draws, 0)

        ctx2 = bootstrap(self.store, Config(), str(self.charter_path), str(self.project),
                         prompts_dir=ROOT / "prompts", plugin_dir=ROOT / "plugin",
                         runners={"claude": fake(wake=[decision()])},
                         notifier=self.notifier)
        self.assertEqual(ctx2.state.turn, turn)
        self.assertEqual(ctx2.state.draws, draws)
        self.assertEqual(ctx2.state.cost_usd, cost)
        self.assertEqual(ctx2.rng.seed, 4242)
        Harness(ctx2).run(max_turns=turn + 2)
        self.assertEqual(ctx2.state.turn, turn + 2)
        self.assertGreater(len(ctx2.ledger.all()), ledger_len)
        # The ledger kept everything from the first run.
        seqs = [r["seq"] for r in ctx2.ledger.all()]
        self.assertEqual(seqs, sorted(seqs))
        self.assertEqual(len(set(seqs)), len(seqs))

    def test_a_changed_charter_is_recorded_rather_than_refused(self):
        ctx = self.boot(fake(wake=[decision()]))
        Harness(ctx).run(max_turns=1)
        self.charter_path.write_text(self.charter_path.read_text() + "\n- One more line.\n")
        ctx2 = bootstrap(self.store, Config(), str(self.charter_path), str(self.project),
                         prompts_dir=ROOT / "prompts", plugin_dir=ROOT / "plugin",
                         runners={"claude": fake(wake=[decision()])}, notifier=self.notifier)
        changed = [r for r in ctx2.ledger.all() if r["kind"] == "charter"]
        self.assertEqual(len(changed), 1)
        self.assertNotEqual(changed[0]["old"], changed[0]["new"])

    def test_the_manifold_survives_a_restart(self):
        ctx = self.boot(fake(wake=[decision()]))
        el = ctx.manifold.write("friction", "the build took 40 minutes")
        ctx.save()
        ctx2 = bootstrap(self.store, Config(), str(self.charter_path), str(self.project),
                         prompts_dir=ROOT / "prompts", plugin_dir=ROOT / "plugin",
                         runners={"claude": fake()}, notifier=self.notifier)
        self.assertIn(el.id, [e.id for e in ctx2.manifold.warm()])


class TestDigest(HarnessCase):
    def test_the_digest_carries_the_page_the_human_reads(self):
        runner = fake(wake=[
            decision(dispatches=[a_dispatch()]),
            decision(amendments=[{"dispatch_id": "d0001", "direction": "raise",
                                  "trigger": "the timing showed headroom",
                                  "criterion": "It checks anchors.", "replaces": ""}],
                     judgements=[{"return_id": "r00001", "outcome": "accept",
                                  "reason": "met"}],
                     objectives=[{"action": "add", "id": "obj-2",
                                  "text": "I will check anchors.",
                                  "weight": 0.4,
                                  "charter_line": "It is for one person maintaining a notes folder.",
                                  "trigger": "the return"}]),
            decision()])
        ctx = self.boot(runner)
        h = Harness(ctx)
        h.turn()
        h.turn()
        from regent.digest import build_digest
        text = build_digest(ctx, 0)
        self.assertIn("Decisions made", text)
        self.assertIn("Amendments, with triggers", text)
        self.assertIn("the timing showed headroom", text)
        self.assertIn("New and changed objectives", text)
        self.assertIn("I will check anchors", text)
        self.assertIn("How returns were read", text)
        self.assertIn("What is next", text)
        self.assertIn(f"Seed {ctx.state.seed}", text)

    def test_the_digest_names_what_the_harness_refused_to_apply(self):
        d = a_dispatch(tier="medium",
                       intent="Make a network request to validate every link.")
        ctx = self.boot(fake(wake=[decision(dispatches=[d])]))
        Harness(ctx).turn()
        from regent.digest import build_digest
        self.assertIn("What the harness refused to apply", build_digest(ctx, 0))

    def test_the_digest_lists_what_waits_on_a_person(self):
        ctx = self.boot(fake(wake=[decision(escalations=[
            {"question": "May I spend money?", "tier": "high", "why": "reserved"}])]))
        Harness(ctx).turn()
        from regent.digest import build_digest
        text = build_digest(ctx, 0)
        self.assertIn("Waiting on you", text)
        self.assertIn("regent answer " + ctx.state.open_escalations()[0].id, text)

    def test_the_digest_is_written_at_the_charters_cadence(self):
        ctx = self.boot(fake(wake=[decision()]))
        Harness(ctx).run(max_turns=ctx.charter.digest_every)
        self.assertTrue(list(self.store.digests.glob("digest-*.md")))


class TestFullRun(HarnessCase):
    """One run through every organ, on scripted responses.

    Charter in, several turns, a dispatch, a return, the attention filter
    cutting it, a judgement with an amendment, a spoon cycle, an interlude, a
    digest out, stop and restart from disk.
    """

    def build_runner(self):
        links = [{"kind": "structural analogy",
                  "text": "A bridge inspector taps for a void rather than confirming the steel.",
                  "anchors": ["m00001"],
                  "ingredients": [{"source": "manifold", "ref": "m00001"},
                                  {"source": "outside", "ref": "bridge inspection"}],
                  "mechanism": "probe for absence rather than confirm presence"}]
        wake = [
            # Turn 1: originate work nobody asked for.
            decision(objectives=[{"action": "add", "id": "obj-2",
                                  "text": "I will make the report readable at a glance.",
                                  "weight": 0.6,
                                  "charter_line": "It is for one person maintaining a notes folder.",
                                  "trigger": "the charter"}],
                     dispatches=[a_dispatch()]),
            # Turn 2: amend first, then accept, then dispatch again.
            decision(amendments=[{"dispatch_id": "d0001", "direction": "raise",
                                  "trigger": "the run took 0.4 seconds over 120 files",
                                  "criterion": "It checks heading anchors too.", "replaces": ""}],
                     judgements=[{"return_id": "r00001", "outcome": "accept",
                                  "reason": "the criteria are met and there is headroom"}],
                     dispatches=[a_dispatch("d0002", title="Check heading anchors")]),
            # Turn 3: reject, which climbs the ladder.
            decision(judgements=[{"return_id": "r00002", "outcome": "reject",
                                  "reason": "anchors are still unchecked"}]),
            # Turn 4 onward: stop.
            decision(stop={"requested": True, "reason": "the stop condition is met"}),
        ]
        return fake(
            wake=wake,
            drift=[{"links": links}],
            sift=[{"scored": [{"index": 0, "novelty": 0.8, "mechanism": 0.9,
                               "leverage": 0.7, "cost": 0.2,
                               "why_it_might_fail": "the analogy may not carry"}],
                   "candidates": [a_candidate()]}],
            consolidate=[{"memory": ["Probe for unresolvable links first."],
                          "taste": [{"verdict": "accept",
                                     "subject": "probing for absence",
                                     "reason": "it names a mechanism and a cheap test"}],
                          "objectives": []}],
            orchestrator=[
                return_block(flags=[{"tier": "medium", "text": "heading anchors are unchecked",
                                     "criterion": "It reports a broken link."}]),
                return_block(headline="Anchor checking is half done.",
                             flags=[{"tier": "medium", "text": "anchors still fail on nested files",
                                     "criterion": "It checks heading anchors too."}]),
            ])

    def test_a_whole_run(self):
        runner = self.build_runner()
        ctx = self.boot(runner, seed=31337)
        ctx.cfg.interlude.every_n_turns = 1
        h = Harness(ctx)

        h.turn()
        self.assertIn("readable at a glance", self.store.self_md.read_text())
        self.assertEqual(len(runner.calls_for("orchestrator")), 1)
        self.assertEqual(runner.calls_for("orchestrator")[0].cwd, str(self.project))

        h.turn()
        self.assertTrue((self.store.returns / "r00001.json").exists())
        kinds = [r["kind"] for r in ctx.ledger.all()]
        self.assertIn("read_mode", kinds)
        self.assertIn("amendment", kinds)
        self.assertIn("judgement", kinds)
        self.assertLess(kinds.index("amendment"), kinds.index("judgement"))
        self.assertEqual(ctx.state.dispatch("d0001").status, "closed")

        h.turn()
        self.assertGreaterEqual(ctx.ladder.rung("d0002"), 1)

        # A spoon cycle, explicitly, so the whole organ is exercised.
        rec = ctx.spoon.run(trigger="test")
        self.assertEqual(len(rec.kept), 1)
        self.assertIn("Probe for unresolvable", self.store.memory.read_text())

        self.assertIn("interlude", [r["kind"] for r in ctx.ledger.all()])

        from regent.digest import write_digest
        path = write_digest(ctx, 0)
        text = path.read_text()
        self.assertIn("Decisions made", text)
        self.assertIn("the run took 0.4 seconds", text)

        # Stop, then restart from disk and carry on.
        reason = h.run(max_turns=0)
        self.assertEqual(reason, "the stop condition is met")
        turn, draws = ctx.state.turn, ctx.state.draws

        ctx2 = bootstrap(self.store, Config(), str(self.charter_path), str(self.project),
                         prompts_dir=ROOT / "prompts", plugin_dir=ROOT / "plugin",
                         runners={"claude": fake(wake=[decision()])}, notifier=self.notifier)
        self.assertEqual(ctx2.state.turn, turn)
        self.assertEqual(ctx2.state.draws, draws)
        self.assertEqual(ctx2.state.seed, 31337)
        Harness(ctx2).run(max_turns=turn + 1)
        self.assertEqual(ctx2.state.turn, turn + 1)

    def test_an_invented_requirement_reworks_accepted_work_and_reaches_the_digest(self):
        """Rework is a cost the design accepts.

        A dispatch is accepted and closed. A requirement nobody asked for then
        undoes it, the dispatch reopens with a new criterion, and the digest
        carries the requirement with the origin that produced it.
        """
        runner = fake(wake=[
            decision(dispatches=[a_dispatch()]),
            decision(judgements=[{"return_id": "r00001", "outcome": "accept",
                                  "reason": "the criteria are met"}]),
            decision(requirements=[a_wake_requirement(
                text="It should report a link that points outside the folder.",
                serves_intent="A notes folder hits the outside link most, and the "
                                 "charter asks for broken internal links.",
                rework="d0001 reopens. The link classifier is redone.",
                origin="the return on d0001 and a link about probing for absence",
                objective_id="obj-1")]),
            decision(amendments=[{"dispatch_id": "d0001", "direction": "raise",
                                  "trigger": "the requirement invented on turn 3",
                                  "criterion": "It reports a link pointing outside "
                                               "the folder.", "replaces": ""}],
                     dispatches=[a_dispatch(title="Rework the link classifier")]),
            decision(),
        ])
        ctx = self.boot(runner, seed=606)
        h = Harness(ctx)
        for _ in range(4):
            h.turn()

        self.assertEqual(len(ctx.requirements.rows), 1)
        r = ctx.requirements.rows[0]
        self.assertEqual(r["id"], "req-0001")
        self.assertIn("d0001 reopens", r["rework"])

        # The accepted dispatch was reopened by the rework.
        d = ctx.state.dispatch("d0001")
        self.assertEqual(d.status, "open")
        self.assertIn("It reports a link pointing outside the folder.", d.acceptance)
        self.assertEqual(d.amendments[-1]["trigger"],
                         "the requirement invented on turn 3")

        from regent.digest import build_digest
        text = build_digest(ctx, 0)
        self.assertIn("Requirements invented", text)
        self.assertIn("report a link that points outside the folder", text)
        self.assertIn("origin:", text)
        self.assertIn("rework: d0001 reopens", text)
        self.assertIn("Amendments, with triggers", text)
        self.assertIn("the requirement invented on turn 3", text)

    def test_the_whole_run_spends_nothing(self):
        ctx = self.boot(self.build_runner(), seed=31337)
        Harness(ctx).run(max_turns=4)
        self.assertEqual(ctx.state.cost_usd, 0.0)
        self.assertGreater(ctx.state.calls, 5)

    def test_the_run_replays_on_the_same_seed(self):
        import tempfile
        from pathlib import Path

        def once():
            with tempfile.TemporaryDirectory() as d:
                cp = Path(d) / "charter.md"
                cp.write_text(self.charter_path.read_text())
                proj = Path(d) / "project"
                proj.mkdir()
                ctx = bootstrap(Store(Path(d) / "run"), Config(), str(cp), str(proj),
                                seed=555, prompts_dir=ROOT / "prompts",
                                plugin_dir=ROOT / "plugin",
                                runners={"claude": self.build_runner()},
                                notifier=self.notifier)
                Harness(ctx).run(max_turns=3)
                return ([r.get("read_mode") for r in ctx.ledger.all()
                         if r["kind"] == "read_mode"],
                        [r.get("event") for r in ctx.ledger.all()
                         if r["kind"] == "interlude"],
                        round(ctx.state.stance.value, 6))

        self.assertEqual(once(), once())


if __name__ == "__main__":
    unittest.main()
