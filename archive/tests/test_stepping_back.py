"""Step 12. The subject is the run and never the project."""

from __future__ import annotations

import unittest

from helpers import HarnessCase, a_dispatch, decision, fake

from regent import process_view as pv
from regent import ways as w
from regent.config import Config
from regent.loop import Harness


def a_way(**over) -> dict:
    row = {
        "action": "add", "id": "", "text": "Ask for a screenshot in every return.",
        "pattern": "three returns in a row had no evidence a reader could open",
        "metric": "unread_share", "direction": "down",
        "review_in_turns": 5, "setting": "", "value": 0.0,
    }
    row.update(over)
    return row


def stepping_runner(ways=None, notes=None, observations=None, **over):
    r = fake(**over)
    r.scripts["stepping_back"] = [{
        "observations": observations if observations is not None
        else ["turns_per_accept is 4.0, which is two turns more than last period"],
        "ways": ways if ways is not None else [a_way()],
        "process_notes": notes or [],
    }]
    return r


class TestProcessView(HarnessCase):
    def a_run(self, turns=3):
        runner = stepping_runner(
            wake=[decision(dispatches=[a_dispatch()]),
                  decision(judgements=[{"return_id": "r00001", "outcome": "accept",
                                        "reason": "met"}]),
                  decision()])
        ctx = self.boot(runner)
        h = Harness(ctx)
        for _ in range(turns):
            h.turn()
        return ctx

    def test_the_view_is_counted_from_the_record(self):
        ctx = self.a_run()
        v = pv.build(ctx, since_turn=0)
        self.assertEqual(v.flow["dispatches"], 1)
        self.assertEqual(v.flow["accepts"], 1)
        self.assertEqual(v.reading["returns_read"], 1)
        self.assertIn(v.reading["mode_mix"] and list(v.reading["mode_mix"])[0],
                      ("full", "skim", "glance", "wave-through"))

    def test_it_carries_all_seven_blocks(self):
        ctx = self.a_run()
        d = pv.build(ctx, since_turn=0).to_dict()
        for block in ("flow", "reading", "trust", "asking", "mood", "invention",
                      "faults"):
            self.assertIn(block, d)

    def test_it_is_scoped_to_its_period(self):
        ctx = self.a_run()
        whole = pv.build(ctx, since_turn=0)
        late = pv.build(ctx, since_turn=2)
        self.assertGreaterEqual(whole.flow["dispatches"], late.flow["dispatches"])

    def test_a_number_never_counted_is_null_and_not_zero(self):
        ctx = self.boot(stepping_runner(wake=[decision()]))
        Harness(ctx).turn()
        v = pv.build(ctx, since_turn=0)
        self.assertIsNone(v.flow["turns_per_accept"])
        self.assertIsNone(v.reading["unread_share"])

    def test_a_named_metric_can_be_read_back(self):
        ctx = self.a_run()
        v = pv.build(ctx, since_turn=0)
        self.assertEqual(v.metric("dispatches"), 1.0)
        self.assertIsNone(v.metric("no_such_number"))
        self.assertIn("dispatches", v.metric_names())

    def test_the_view_reads_no_project_file(self):
        marker = "ZZQ_PROCESS_5521"
        (self.project / "linkcheck.py").write_text(f"# {marker}\n")
        ctx = self.a_run()
        self.assertNotIn(marker, pv.render(pv.build(ctx, since_turn=0)))


class TestWaysCannotLowerAFloor(unittest.TestCase):
    def setUp(self):
        self.cfg = Config()

    def refuse(self, **over):
        return w.refuse_reason(a_way(**over), self.cfg)

    def test_a_floor_may_rise(self):
        self.assertEqual(self.refuse(setting="spot_check.rate", value=0.5), "")
        self.assertEqual(self.refuse(setting="attention.audit_rate", value=0.4), "")
        self.assertEqual(self.refuse(setting="attention.debt_cap", value=5), "")

    def test_a_floor_may_never_fall(self):
        for setting, value in (("spot_check.rate", 0.01),
                               ("attention.audit_rate", 0.05),
                               ("attention.debt_cap", 1),
                               ("spot_check.max_per_turn", 0)):
            why = self.refuse(setting=setting, value=value)
            self.assertTrue(why, setting)
            self.assertIn("never fall", why)

    def test_a_setting_outside_the_list_is_refused(self):
        for setting in ("charter.refusals", "tiers.names", "drift.groundedness_floor",
                        "requirements.default_appetite", "sift.weights"):
            why = self.refuse(setting=setting, value=1)
            self.assertIn("may not move", why)

    def test_a_prose_way_that_loosens_scrutiny_is_refused(self):
        for text in ("Relax the refusals when the branch is small.",
                     "Lower the tier on anything revertible.",
                     "Skip the disconfirming gate for small candidates.",
                     "Widen the appetite when the run is going well."):
            self.assertTrue(self.refuse(text=text), text)

    def test_an_ordinary_prose_way_passes(self):
        self.assertEqual(self.refuse(
            text="Write the brief as one paragraph and one list, never more."), "")
        self.assertEqual(self.refuse(
            text="Ask for a screenshot in every return."), "")

    def test_a_way_cannot_stop_a_thing_entirely(self):
        self.assertIn("stops the thing", self.refuse(setting="drift.passes", value=0))


class TestWaysApply(HarnessCase):
    def ways_for(self, cfg=None):
        return w.Ways(cfg or Config())

    def test_a_way_that_names_a_setting_moves_it(self):
        cfg = Config()
        ways = self.ways_for(cfg)
        before = cfg.spot_check.rate
        ways.apply([a_way(setting="spot_check.rate", value=0.5)], turn=1)
        self.assertGreater(cfg.spot_check.rate, before)
        self.assertEqual(cfg.spot_check.rate, 0.5)

    def test_a_refused_way_is_kept_out_and_the_setting_is_untouched(self):
        cfg = Config()
        ways = self.ways_for(cfg)
        before = cfg.attention.audit_rate
        out = ways.apply([a_way(setting="attention.audit_rate", value=0.01)], turn=1)
        self.assertEqual(ways.live(), [])
        self.assertEqual(len(out.refused), 1)
        self.assertEqual(cfg.attention.audit_rate, before)

    def test_the_cap_of_seven_displaces(self):
        cfg = Config()
        ways = self.ways_for(cfg)
        for i in range(7):
            ways.apply([a_way(text=f"way number {i}")], turn=i + 1)
        self.assertEqual(len(ways.live()), 7)
        out = ways.apply([a_way(text="the eighth")], turn=8)
        self.assertEqual(len(ways.live()), 7)
        self.assertEqual(len(out.displaced), 1)
        self.assertEqual(out.displaced[0]["text"], "way number 0")
        self.assertIn("the eighth", [x["text"] for x in ways.live()])

    def test_displacement_prefers_a_way_that_is_not_holding_a_floor_up(self):
        cfg = Config()
        ways = self.ways_for(cfg)
        ways.apply([a_way(text="holds a floor up",
                          setting="spot_check.rate", value=0.5)], turn=1)
        for i in range(6):
            ways.apply([a_way(text=f"plain way {i}")], turn=i + 2)
        ways.apply([a_way(text="the eighth")], turn=9)
        live = [x["text"] for x in ways.live()]
        self.assertIn("holds a floor up", live)
        self.assertNotIn("plain way 0", live)

    def test_a_way_can_be_dropped_by_id(self):
        ways = self.ways_for()
        ways.apply([a_way(id="way-001")], turn=1)
        ways.apply([{"action": "drop", "id": "way-001", "text": "", "pattern": "",
                     "metric": "", "direction": "down", "review_in_turns": 0,
                     "setting": "", "value": 0}], turn=2)
        self.assertEqual(ways.live(), [])

    def test_a_new_way_records_the_baseline_of_the_number_it_names(self):
        class View:
            def metric(self, name):
                return 0.8 if name == "unread_share" else None
        ways = self.ways_for()
        out = ways.apply([a_way(metric="unread_share")], turn=1, view=View())
        self.assertEqual(out.kept[0]["baseline"], 0.8)
        self.assertEqual(out.kept[0]["review_turn"], 6)


class TestWaysReview(unittest.TestCase):
    class View:
        def __init__(self, value):
            self.value = value

        def metric(self, name):
            return self.value

    def setUp(self):
        self.cfg = Config()
        self.ways = w.Ways(self.cfg)

    def a_live_way(self, direction="down", baseline=0.8):
        self.ways.apply([a_way(metric="unread_share", direction=direction,
                               review_in_turns=5)], turn=1,
                        view=self.View(baseline))
        return self.ways.live()[0]

    def test_a_way_is_kept_where_its_number_moved(self):
        self.a_live_way()
        results = self.ways.review(turn=6, view=self.View(0.3))
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["status"], "live")
        self.assertIn("kept", results[0]["outcome"])
        self.assertEqual(results[0]["after"], 0.3)

    def test_a_way_is_dropped_where_its_number_did_not_move(self):
        self.a_live_way()
        results = self.ways.review(turn=6, view=self.View(0.9))
        self.assertEqual(results[0]["status"], "dropped")
        self.assertIn("did not move", results[0]["outcome"])
        self.assertEqual(self.ways.live(), [])

    def test_direction_up_is_read_the_other_way(self):
        self.a_live_way(direction="up", baseline=2.0)
        results = self.ways.review(turn=6, view=self.View(5.0))
        self.assertEqual(results[0]["status"], "live")

    def test_a_way_whose_number_was_never_counted_is_dropped(self):
        self.a_live_way()
        results = self.ways.review(turn=6, view=self.View(None))
        self.assertEqual(results[0]["status"], "dropped")
        self.assertIn("never counted", results[0]["outcome"])

    def test_a_way_is_not_reviewed_before_its_date(self):
        self.a_live_way()
        self.assertEqual(self.ways.review(turn=3, view=self.View(0.1)), [])

    def test_a_kept_way_gets_a_fresh_baseline_and_date(self):
        self.a_live_way()
        self.ways.review(turn=6, view=self.View(0.3))
        row = self.ways.live()[0]
        self.assertEqual(row["baseline"], 0.3)
        self.assertEqual(row["review_turn"], 6 + self.cfg.ways.review_in_turns)


class TestTheCall(HarnessCase):
    def test_it_runs_before_a_digest_and_writes_the_ways_file(self):
        ctx = self.boot(stepping_runner(wake=[decision()]))
        ctx.charter.digest_every = 2
        h = Harness(ctx)
        h.turn()
        h.turn()
        self.assertEqual(ctx.state.stepped_back, 1)
        self.assertTrue(ctx.store.ways.exists())
        self.assertIn("Ask for a screenshot", ctx.store.ways.read_text())
        rows = [r for r in ctx.ledger.all() if r["kind"] == "stepping_back"]
        self.assertEqual(rows[0]["trigger"], "before a digest")

    def test_the_call_has_no_tools_and_runs_in_the_sandbox(self):
        ctx = self.boot(stepping_runner(wake=[decision()]))
        ctx.charter.digest_every = 2
        h = Harness(ctx)
        h.turn()
        h.turn()
        req = self.runner.calls_for("stepping_back")[0]
        self.assertTrue(req.toolless)
        self.assertEqual(req.cwd, str(self.store.sandbox))

    def test_the_prompt_carries_counted_numbers_and_the_current_ways(self):
        ctx = self.boot(stepping_runner(wake=[decision()]))
        ctx.charter.digest_every = 2
        h = Harness(ctx)
        h.turn()
        h.turn()
        prompt = self.runner.calls_for("stepping_back")[0].prompt
        self.assertIn("## Flow", prompt)
        self.assertIn("## Reading", prompt)
        self.assertIn("counted from the record", prompt)
        self.assertIn("spot_check.rate", prompt)
        self.assertIn("may rise and never fall", prompt)

    def test_a_detector_firing_triggers_it(self):
        ctx = self.boot(stepping_runner(wake=[decision()]))
        ctx.state.turn = 30
        ctx.state.returns_read = 40
        ctx.state.last_stepped_back = 0
        self.assertEqual(Harness(ctx).stepping_back_due(), "a detector fired")

    def test_rung_four_triggers_it(self):
        runner = stepping_runner(wake=[decision(dispatches=[a_dispatch()]),
                                       decision()])
        ctx = self.boot(runner)
        h = Harness(ctx)
        h.turn()
        for _ in range(4):
            ctx.ladder.record_failure("d0001")
        ctx.state.last_stepped_back = 0
        ctx.state.turn = 5
        self.assertIn("rung", h.stepping_back_due())

    def test_collapsed_trust_triggers_it(self):
        ctx = self.boot(stepping_runner(wake=[decision()]))
        ctx.trust.table["k"] = 0.1
        ctx.state.turn = 5
        ctx.state.last_stepped_back = 0
        self.assertEqual(Harness(ctx).stepping_back_due(),
                         "trust in a configuration collapsed")

    def test_it_does_not_run_twice_in_quick_succession(self):
        ctx = self.boot(stepping_runner(wake=[decision()]))
        ctx.state.turn = 5
        ctx.state.last_stepped_back = 5
        ctx.trust.table["k"] = 0.1
        self.assertEqual(Harness(ctx).stepping_back_due(), "")

    def test_a_refused_way_is_logged_and_never_applied(self):
        runner = stepping_runner(ways=[a_way(setting="attention.audit_rate",
                                             value=0.01)], wake=[decision()])
        ctx = self.boot(runner)
        ctx.charter.digest_every = 2
        before = ctx.cfg.attention.audit_rate
        h = Harness(ctx)
        h.turn()
        h.turn()
        self.assertEqual(ctx.cfg.attention.audit_rate, before)
        refused = [r for r in ctx.ledger.all()
                   if r["kind"] == "rejected" and r.get("bucket") == "ways"]
        self.assertTrue(refused)
        self.assertIn("never fall", refused[0]["reason"])

    def test_a_process_note_goes_to_the_human_and_is_never_applied(self):
        runner = stepping_runner(
            ways=[],
            notes=[{"text": "The appetite of 30 percent is too small.",
                    "why": "two requirements were filed for want of room"}],
            wake=[decision()])
        ctx = self.boot(runner)
        ctx.charter.digest_every = 2
        before = ctx.charter.appetite
        h = Harness(ctx)
        h.turn()
        h.turn()
        self.assertEqual(ctx.charter.appetite, before)
        self.assertEqual(len(ctx.state.process_notes), 1)
        from regent.digest import build_digest
        text = build_digest(ctx, 0)
        self.assertIn("what it thinks the charter has wrong", text.lower())
        self.assertIn("too small", text)

    def test_the_observations_enter_the_manifold_as_friction(self):
        ctx = self.boot(stepping_runner(wake=[decision()]))
        ctx.charter.digest_every = 2
        h = Harness(ctx)
        h.turn()
        h.turn()
        texts = " ".join(e.text for e in ctx.manifold.warm())
        self.assertIn("About how the work is going", texts)

    def test_a_failed_call_does_not_stop_the_turn(self):
        from regent.runner import ModelResponse
        runner = stepping_runner(wake=[decision(), decision()])
        runner.scripts["stepping_back"] = [ModelResponse(role="stepping_back",
                                                         is_error=True)]
        ctx = self.boot(runner)
        ctx.charter.digest_every = 2
        h = Harness(ctx)
        h.turn()
        h.turn()
        self.assertEqual(ctx.state.turn, 2)
        self.assertEqual(ctx.ways.live(), [])


class TestWaysReachTheWork(HarnessCase):
    def test_wake_reads_the_ways(self):
        ctx = self.boot(stepping_runner(wake=[decision(), decision()]))
        ctx.ways.apply([a_way(text="Ask for a screenshot in every return.")], turn=1)
        Harness(ctx).wake([])
        self.assertIn("Ask for a screenshot",
                      self.runner.calls_for("wake")[0].prompt)

    def test_the_ways_go_down_with_every_dispatch(self):
        runner = stepping_runner(wake=[decision(dispatches=[a_dispatch()]),
                                       decision()])
        ctx = self.boot(runner)
        ctx.ways.apply([a_way(text="Keep a dispatch to one afternoon.")], turn=1)
        Harness(ctx).turn()
        prompt = runner.calls_for("orchestrator")[0].prompt
        self.assertIn("How the owner works", prompt)
        self.assertIn("Keep a dispatch to one afternoon.", prompt)

    def test_a_resumed_dispatch_carries_them_too(self):
        d = a_dispatch()
        runner = stepping_runner(wake=[decision(dispatches=[d]),
                                       decision(dispatches=[d]), decision()])
        ctx = self.boot(runner)
        ctx.ways.apply([a_way(text="Keep a dispatch to one afternoon.")], turn=1)
        h = Harness(ctx)
        h.turn()
        h.turn()
        resumed = [c for c in runner.calls_for("orchestrator") if c.resume]
        self.assertTrue(resumed)
        self.assertIn("Keep a dispatch to one afternoon.", resumed[0].prompt)

    def test_no_ways_means_no_empty_section_in_the_brief(self):
        runner = stepping_runner(wake=[decision(dispatches=[a_dispatch()]),
                                       decision()])
        ctx = self.boot(runner)
        Harness(ctx).turn()
        self.assertNotIn("How the owner works",
                         runner.calls_for("orchestrator")[0].prompt)


class TestSteppingBackIsExported(HarnessCase):
    def test_the_export_and_series_carry_ways_and_process_notes(self):
        from regent.export import build_export
        runner = stepping_runner(
            notes=[{"text": "the appetite is too small", "why": "two were filed"}],
            wake=[decision()])
        ctx = self.boot(runner)
        ctx.charter.digest_every = 2
        h = Harness(ctx)
        h.turn()
        h.turn()
        ctx.save()
        row = ctx.store.read_jsonl(ctx.store.metrics)[-1]
        self.assertEqual(row["stepped_back"], 1)
        self.assertTrue(row["ways"])
        data = build_export(ctx.store.root)
        self.assertTrue(data["ways"])
        self.assertTrue(data["stepping_back"])
        self.assertTrue(data["way_events"])
        self.assertTrue(data["process_views"])
        self.assertEqual(len(data["process_notes"]), 1)
        self.assertEqual(data["run"]["stepped_back"], 1)


if __name__ == "__main__":
    unittest.main()


class TestPace(HarnessCase):
    """Nothing the owner does should make the builders wait."""

    def test_judgement_never_waits_on_a_cycle(self):
        import threading
        started = threading.Event()
        release = threading.Event()

        def slow_saturate(req):
            started.set()
            release.wait(timeout=20)
            from regent.runner import ModelResponse
            return ModelResponse(role="saturate", structured={
                "motifs": [], "tensions": [], "questions": []})

        runner = stepping_runner(wake=[decision(), decision(), decision()])
        runner.scripts["saturate"] = [slow_saturate]
        cfg = Config()
        cfg.life.enabled = False
        cfg.cycle_in_background = True
        cfg.cycle_every_n_turns = 1
        ctx = self.boot(runner, cfg=cfg)
        h = Harness(ctx)
        try:
            import time
            h.turn()
            self.assertTrue(started.wait(timeout=10), "the cycle never started")
            # The cycle is blocked in its saturate call. The next turn has to
            # complete anyway, and quickly.
            began = time.time()
            h.turn()
            took = time.time() - began
            self.assertEqual(ctx.state.turn, 2)
            self.assertLess(took, 5, "judgement waited on the cycle")
            self.assertFalse(release.is_set())
        finally:
            release.set()
            h.wait_for_cycle(timeout=20)

    def test_one_cycle_runs_at_a_time(self):
        import threading
        release = threading.Event()

        def slow_saturate(req):
            release.wait(timeout=20)
            from regent.runner import ModelResponse
            return ModelResponse(role="saturate", structured={
                "motifs": [], "tensions": [], "questions": []})

        runner = stepping_runner(wake=[decision(), decision(), decision()])
        runner.scripts["saturate"] = [slow_saturate]
        cfg = Config()
        cfg.life.enabled = False
        cfg.cycle_in_background = True
        cfg.cycle_every_n_turns = 1
        ctx = self.boot(runner, cfg=cfg)
        h = Harness(ctx)
        try:
            self.assertTrue(h.start_cycle("first", "none", None))
            self.assertFalse(h.start_cycle("second", "none", None))
        finally:
            release.set()
            h.wait_for_cycle(timeout=20)

    def test_a_finished_cycle_lands_on_the_next_turn(self):
        runner = stepping_runner(wake=[decision(), decision()],
                                 drift=[{"links": []}])
        cfg = Config()
        cfg.life.enabled = False
        cfg.cycle_in_background = True
        cfg.cycle_every_n_turns = 1
        ctx = self.boot(runner, cfg=cfg)
        h = Harness(ctx)
        h.turn()
        h.wait_for_cycle(timeout=20)
        h.turn()
        landed = [r for r in ctx.ledger.all()
                  if r["kind"] == "cycle" and r.get("state") == "landed"]
        self.assertTrue(landed)

    def test_a_week_of_journal_is_one_call(self):
        from test_life import life_runner
        cfg = Config()
        cfg.life.enabled = True
        cfg.life.backstory_days = 7
        cfg.life.days_per_call = 7
        cfg.cycle_in_background = False
        runner = life_runner(wake=[decision()])
        ctx = self.boot(runner, cfg=cfg)
        ctx.life_writer.bootstrap()
        self.assertEqual(ctx.life.index().day_count, 7)
        self.assertEqual(len(runner.calls_for("life_week")), 1)
        self.assertEqual(runner.calls_for("life_day"), [])

    def test_thirty_days_is_five_calls_not_thirty(self):
        from test_life import life_runner
        cfg = Config()
        cfg.life.enabled = True
        cfg.life.backstory_days = 30
        cfg.life.days_per_call = 7
        cfg.cycle_in_background = False
        runner = life_runner(wake=[decision()])
        ctx = self.boot(runner, cfg=cfg)
        ctx.life_writer.bootstrap()
        self.assertEqual(ctx.life.index().day_count, 30)
        self.assertLessEqual(len(runner.calls_for("life_week")), 5)

    def test_an_entry_is_a_journal_and_not_a_novel(self):
        cfg = Config()
        self.assertEqual(cfg.life.day_words_min, 120)
        self.assertEqual(cfg.life.day_words_max, 300)
        self.assertEqual(cfg.life.long_day_words, 800)

    def test_an_owner_is_written_once_and_reused(self):
        import tempfile
        from pathlib import Path

        from test_life import life_runner
        with tempfile.TemporaryDirectory() as d:
            cfg = Config()
            cfg.life.enabled = True
            cfg.life.backstory_days = 2
            cfg.life.owners_dir = d
            cfg.life.owner = "piotr-mahon"
            cfg.cycle_in_background = False
            ctx = self.boot(life_runner(wake=[decision()]), cfg=cfg)
            self.assertEqual(ctx.life.root, Path(d).resolve() / "piotr-mahon")
            ctx.life_writer.bootstrap()
            self.assertTrue((Path(d) / "piotr-mahon" / "bible.md").exists())
            # Nothing of the life is in the run directory.
            self.assertFalse((self.store.root / "life" / "bible.md").exists())

    def test_the_cycle_runs_every_fifteenth_turn_and_nothing_else(self):
        """Dreaming guides the project. It does not delay it."""
        cfg = Config()
        self.assertEqual(cfg.cycle_every_n_turns, 15)
        self.assertEqual(cfg.drift.passes, 1)
        self.assertFalse(cfg.spot_check.opens_drift)

    def test_drift_asks_for_twenty_links_not_sixty(self):
        cfg = Config()
        self.assertLessEqual(cfg.drift.target_links_max, 25)


class TestAdoptingAnOwner(HarnessCase):
    def a_life(self, days=3):
        from test_life import life_runner
        cfg = Config()
        cfg.life.enabled = True
        cfg.life.backstory_days = days
        cfg.life.days_per_call = days
        cfg.cycle_in_background = False
        runner = life_runner(wake=[decision()])
        ctx = self.boot(runner, cfg=cfg)
        ctx.life_writer.bootstrap()
        return ctx, runner

    def test_the_life_moves_under_owners_and_the_originals_are_kept(self):
        import tempfile
        from pathlib import Path

        from regent.owner import adopt
        ctx, runner = self.a_life()
        before = (ctx.life.journal / "day-0001.md").read_text()
        with tempfile.TemporaryDirectory() as d:
            runner.scripts["life_condense"] = [{"entries": [
                {"entry": "Frost until ten.", "kept": ["frost"]}] * 3}]
            out = adopt(ctx, "piotr-mahon", d)
            root = Path(d) / "piotr-mahon"
            self.assertTrue((root / "bible.md").exists())
            self.assertEqual(out.days, 3)
            self.assertEqual(out.condensed, 3)
            # The originals sit beside the journal.
            self.assertEqual((root / "journal" / "long" / "day-0001.md").read_text(),
                             before)
            self.assertIn("Frost until ten.",
                          (root / "journal" / "day-0001.md").read_text())

    def test_condensing_shrinks_the_journal_and_updates_the_index(self):
        import json
        import tempfile
        from pathlib import Path

        from regent.owner import adopt
        ctx, runner = self.a_life()
        with tempfile.TemporaryDirectory() as d:
            runner.scripts["life_condense"] = [{"entries": [
                {"entry": "Frost until ten.", "kept": ["frost"]}] * 3}]
            out = adopt(ctx, "piotr-mahon", d)
            self.assertLess(out.words_after, out.words_before)
            index = json.loads((Path(d) / "piotr-mahon" / "index.json").read_text())
            self.assertEqual(index["days"][0]["words"], 3)

    def test_it_runs_on_the_smallest_model(self):
        import tempfile

        from regent.owner import adopt
        ctx, runner = self.a_life()
        with tempfile.TemporaryDirectory() as d:
            runner.scripts["life_condense"] = [{"entries": [
                {"entry": "Frost.", "kept": ["frost"]}] * 3}]
            adopt(ctx, "piotr-mahon", d)
        calls = runner.calls_for("life_condense")
        self.assertTrue(calls)
        self.assertEqual(calls[0].model, ctx.cfg.models.life_condense)
        self.assertEqual(ctx.cfg.models.life_condense, "haiku")

    def test_an_adopted_owner_is_reused_and_the_run_starts_at_turn_one(self):
        import tempfile
        from pathlib import Path

        from test_life import life_runner

        from regent.owner import adopt
        ctx, runner = self.a_life()
        with tempfile.TemporaryDirectory() as d:
            runner.scripts["life_condense"] = [{"entries": [
                {"entry": "Frost.", "kept": ["frost"]}] * 3}]
            adopt(ctx, "piotr-mahon", d)

            cfg = Config()
            cfg.life.enabled = True
            cfg.life.owners_dir = d
            cfg.life.owner = "piotr-mahon"
            cfg.life.backstory_days = 3
            cfg.cycle_in_background = False
            self.tearDown()
            self.setUp()
            ctx2 = self.boot(life_runner(wake=[decision()]), cfg=cfg)
            self.assertEqual(ctx2.life.index().day_count, 3)
            self.assertTrue(ctx2.life.index().bootstrapped)
            # Nothing is rewritten, so no week call is made.
            written = ctx2.life_writer.bootstrap()
            self.assertEqual(written, 0)
            self.assertEqual(ctx2.runners["claude"].calls_for("life_week"), [])
            self.assertTrue(Path(d).exists())


class TestTheChartersTools(HarnessCase):
    """The first run's builders could not run Python, so the first return came
    back unproven and cost a full round trip.
    """

    def a_run(self):
        runner = stepping_runner(wake=[decision(dispatches=[a_dispatch()]),
                                       decision()])
        ctx = self.boot(runner)
        ctx.charter.tools = ["python3", "python3 -m unittest"]
        Harness(ctx).turn()
        return ctx, runner

    def test_the_commands_reach_the_orchestrator_as_allowed_tools(self):
        from regent.runner import ClaudeCliRunner
        ctx, runner = self.a_run()
        req = runner.calls_for("orchestrator")[0]
        argv = ClaudeCliRunner().argv(req)
        self.assertIn("--allowedTools", argv)
        joined = " ".join(argv)
        self.assertIn("Bash(python3:*)", joined)
        self.assertIn("Bash(python3 -m unittest:*)", joined)

    def test_the_brief_names_them_so_the_builder_knows(self):
        ctx, runner = self.a_run()
        prompt = runner.calls_for("orchestrator")[0].prompt
        self.assertIn("Commands you may run", prompt)
        self.assertIn("python3 -m unittest", prompt)

    def test_a_charter_with_no_tools_adds_nothing(self):
        from regent.runner import ClaudeCliRunner
        runner = stepping_runner(wake=[decision(dispatches=[a_dispatch()]),
                                       decision()])
        ctx = self.boot(runner)
        ctx.charter.tools = []
        Harness(ctx).turn()
        argv = ClaudeCliRunner().argv(runner.calls_for("orchestrator")[0])
        self.assertNotIn("--allowedTools", argv)
        self.assertNotIn("Commands you may run",
                         runner.calls_for("orchestrator")[0].prompt)


class TestCasting(HarnessCase):
    """A regent is cast and not specified."""

    def test_every_trait_not_pinned_is_rolled(self):
        from regent import disposition as disp
        from regent.rng import Rng
        d = disp.roll(Rng(seed=4), {"patient": -0.6})
        self.assertEqual(d.patient, -0.6)
        self.assertEqual(d.pinned, ["patient"])
        rolled = [getattr(d, t) for t in disp.TRAITS if t != "patient"]
        self.assertTrue(any(abs(v) > 0.1 for v in rolled))

    def test_the_same_seed_rolls_the_same_person(self):
        from regent import disposition as disp
        from regent.rng import Rng
        a = disp.roll(Rng(seed=9)).to_dict()
        b = disp.roll(Rng(seed=9)).to_dict()
        self.assertEqual(a, b)

    def test_a_dial_never_leaves_its_range(self):
        from regent import disposition as disp
        d = disp.Disposition(bold=5.0, patient=-9.0)
        self.assertEqual(d.bold, 1.0)
        self.assertEqual(d.patient, -1.0)

    def test_a_pin_can_be_a_dial_or_a_word(self):
        from regent import disposition as disp
        dials, words = disp.parse_pins(["patient=-0.4", "impatient, thorough",
                                        'occupation=a lock keeper'])
        self.assertEqual(dials["traits"], {"patient": -0.4})
        self.assertEqual(dials["facts"]["occupation"], "a lock keeper")
        self.assertEqual(words, ["impatient", "thorough"])

    def test_each_trait_moves_the_thing_it_names(self):
        from regent import disposition as disp
        cfg = Config()
        before = (cfg.stance.start, cfg.drift.target_links_max,
                  cfg.signals.frustration_per_failure, cfg.attention.trust_start,
                  cfg.attention.base_score, cfg.requirements.max_per_cycle)
        d = disp.Disposition(bold=0.8, curious=0.8, patient=-0.8, trusting=0.8,
                             thorough=0.8, stubborn=0.8, restless=0.8)
        disp.apply(d, cfg)
        after = (cfg.stance.start, cfg.drift.target_links_max,
                 cfg.signals.frustration_per_failure, cfg.attention.trust_start,
                 cfg.attention.base_score, cfg.requirements.max_per_cycle)
        for i, (b, a) in enumerate(zip(before, after, strict=True)):
            self.assertNotEqual(b, a, f"dial {i} moved nothing")

    def test_no_personality_lowers_a_floor(self):
        from regent import disposition as disp
        cfg = Config()
        floor = cfg.spot_check.rate
        d = disp.Disposition(thorough=-1.0)
        changed = disp.apply(d, cfg)
        self.assertEqual(cfg.spot_check.rate, floor)
        held = [c for c in changed if c.get("held")]
        self.assertTrue(held)
        self.assertIn("never fall", held[0]["held"])

    def test_a_thorough_disposition_raises_the_rate_above_its_floor(self):
        from regent import disposition as disp
        cfg = Config()
        floor = cfg.spot_check.rate
        disp.apply(disp.Disposition(thorough=1.0), cfg)
        self.assertGreater(cfg.spot_check.rate, floor)

    def test_casting_writes_nothing(self):
        from regent.owner import cast
        ctx = self.boot(stepping_runner(wake=[decision()]))
        rows = cast(ctx, pins=["patient=-0.5"], candidates=3)
        self.assertEqual(len(rows), 3)
        self.assertTrue(all(r["paragraph"] for r in rows))
        self.assertFalse((self.store.root / "life" / "bible.md").exists())

    def test_candidates_differ(self):
        from regent.owner import cast
        ctx = self.boot(stepping_runner(wake=[decision()]))
        rows = cast(ctx, candidates=3)
        names = {r["seed"]["name"] for r in rows}
        self.assertGreater(len(names), 1)

    def test_a_pinned_fact_is_kept(self):
        from regent.owner import cast
        ctx = self.boot(stepping_runner(wake=[decision()]))
        rows = cast(ctx, pins=["occupation=a lock keeper"], candidates=1)
        self.assertEqual(rows[0]["seed"]["occupation"], "a lock keeper")

    def test_a_disposition_on_disk_is_loaded_and_applied(self):
        import json

        from regent import disposition as disp
        ctx = self.boot(stepping_runner(wake=[decision()]))
        (ctx.life.root).mkdir(parents=True, exist_ok=True)
        (ctx.life.root / "disposition.json").write_text(
            json.dumps(disp.Disposition(thorough=0.9).to_dict()))
        self.tearDown()
        self.setUp()
        ctx2 = self.boot(stepping_runner(wake=[decision()]))
        self.assertIsInstance(ctx2.disposition, disp.Disposition)


class TestSittings(HarnessCase):
    """A turn is a sitting, and the day says what it left for the project."""

    def test_the_day_rolls_how_much_time_the_project_got(self):
        from regent import lifetables
        from regent.rng import Rng
        r = Rng(seed=7)
        got = [lifetables.roll_day(r, [])["sitting"] for _ in range(40)]
        self.assertGreater(len(set(got)), 1)
        for name in set(got):
            self.assertIn(name, [n for n, _, _ in lifetables.SITTINGS])

    def test_a_day_with_no_time_forces_a_wave_through(self):
        from helpers import return_block

        from regent import attention
        from regent.returns import parse_return
        from regent.rng import Rng
        ret = parse_return(return_block())
        d = attention.draw_mode(ret, Config(), Rng(seed=2), trust=0.1,
                                queue_depth=0, unease=1.0, stance=-1.0, debt=5,
                                sitting="none", sitting_share=0.0)
        self.assertEqual(d.mode, attention.WAVE)
        self.assertIn("no time", d.forced)

    def test_a_high_tier_flag_still_beats_a_day_with_no_time(self):
        from helpers import return_block

        from regent import attention
        from regent.returns import parse_return
        from regent.rng import Rng
        ret = parse_return(return_block(
            flags=[{"tier": "high", "text": "it writes outside the folder"}]))
        d = attention.draw_mode(ret, Config(), Rng(seed=2), trust=0.9,
                                queue_depth=0, unease=0.0, stance=0.0, debt=0,
                                sitting="none", sitting_share=0.0)
        self.assertEqual(d.mode, attention.FULL)

    def test_more_time_buys_more_attention(self):
        from helpers import return_block

        from regent import attention
        from regent.returns import parse_return
        from regent.rng import Rng
        ret = parse_return(return_block())
        cfg = Config()

        def modes(share):
            return [attention._MODE_RANK[attention.draw_mode(
                ret, cfg, Rng(seed=i), trust=0.5, queue_depth=0, unease=0.0,
                stance=0.0, debt=0, sitting="an evening" if share > 0.5
                else "a few minutes", sitting_share=share).mode]
                for i in range(30)]
        self.assertGreater(sum(modes(1.0)), sum(modes(0.25)))

    def test_a_thorough_disposition_buys_more_and_a_trusting_one_less(self):
        from helpers import return_block

        from regent import attention
        from regent.returns import parse_return
        from regent.rng import Rng
        ret = parse_return(return_block())
        cfg = Config()

        def modes(**kw):
            return [attention._MODE_RANK[attention.draw_mode(
                ret, cfg, Rng(seed=i), trust=0.5, queue_depth=0, unease=0.0,
                stance=0.0, debt=0, **kw).mode] for i in range(30)]
        self.assertGreater(sum(modes(thorough=0.9)), sum(modes(thorough=-0.9)))
        self.assertLess(sum(modes(trusting=0.9)), sum(modes(trusting=-0.9)))

    def test_the_draw_records_the_sitting_and_the_dials(self):
        from helpers import return_block

        from regent import attention
        from regent.returns import parse_return
        from regent.rng import Rng
        d = attention.draw_mode(parse_return(return_block()), Config(),
                                Rng(seed=1), trust=0.5, queue_depth=0,
                                unease=0.0, stance=0.0, debt=0,
                                sitting="an hour", sitting_share=0.6,
                                thorough=0.3, trusting=-0.2)
        self.assertEqual(d.inputs["sitting"], "an hour")
        self.assertEqual(d.inputs["thorough"], 0.3)

    def test_a_day_passes_between_sittings_rather_than_being_drawn(self):
        cfg = Config()
        self.assertTrue(cfg.life.day_between_sittings)
        self.assertEqual(cfg.interlude.weights["day"], 0.0)

    def test_a_turn_writes_the_day_when_the_life_is_running(self):
        from test_life import life_runner
        cfg = Config()
        cfg.life.enabled = True
        cfg.life.backstory_days = 1
        cfg.cycle_in_background = False
        runner = life_runner(wake=[decision(), decision()])
        ctx = self.boot(runner, cfg=cfg)
        ctx.life_writer.bootstrap()
        before = ctx.life.index().day_count
        ctx.state.life_day_count = before
        Harness(ctx).turn()
        self.assertGreater(ctx.life.index().day_count, before)


class TestInventionHasAFloor(unittest.TestCase):
    """A cautious regent invents a different kind of requirement, hardening
    over reach, and as many of them.
    """

    def test_a_content_regent_does_not_invent_fewer(self):
        from regent import disposition as disp
        cfg = Config()
        before = cfg.requirements.max_per_cycle
        changed = disp.apply(disp.Disposition(restless=-1.0), cfg)
        self.assertEqual(cfg.requirements.max_per_cycle, before)
        held = [c for c in changed
                if c["setting"] == "requirements.max_per_cycle" and c.get("held")]
        self.assertTrue(held)
        self.assertIn("never fall", held[0]["held"])

    def test_a_restless_regent_invents_more(self):
        from regent import disposition as disp
        cfg = Config()
        before = cfg.requirements.max_per_cycle
        disp.apply(disp.Disposition(restless=1.0), cfg)
        self.assertGreater(cfg.requirements.max_per_cycle, before)

    def test_piotrs_own_dials_leave_invention_at_the_default(self):
        from regent import disposition as disp
        cfg = Config()
        before = cfg.requirements.max_per_cycle
        disp.apply(disp.Disposition(bold=-0.40, curious=-0.10, patient=0.40,
                                    trusting=0.20, thorough=0.40, stubborn=0.40,
                                    restless=-0.30), cfg)
        self.assertEqual(cfg.requirements.max_per_cycle, before)

    def test_all_four_floors_hold_against_the_worst_disposition(self):
        from regent import disposition as disp
        cfg = Config()
        floors = {
            "spot_check.rate": cfg.spot_check.rate,
            "attention.audit_rate": cfg.attention.audit_rate,
            "attention.debt_cap": cfg.attention.debt_cap,
            "requirements.max_per_cycle": cfg.requirements.max_per_cycle,
        }
        disp.apply(disp.Disposition(thorough=-1.0, trusting=1.0, restless=-1.0,
                                    patient=1.0, bold=-1.0, curious=-1.0,
                                    stubborn=-1.0), cfg)
        self.assertGreaterEqual(cfg.spot_check.rate, floors["spot_check.rate"])
        self.assertGreaterEqual(cfg.attention.audit_rate,
                                floors["attention.audit_rate"])
        self.assertGreaterEqual(cfg.attention.debt_cap, floors["attention.debt_cap"])
        self.assertGreaterEqual(cfg.requirements.max_per_cycle,
                                floors["requirements.max_per_cycle"])


class TestADispositionIsASample(HarnessCase):
    """Two readings of one regent minutes apart disagreed on five of seven
    dials and one changed sign, so a reading is taken three times.
    """

    def a_reader(self, *samples):
        runner = stepping_runner(wake=[decision()])
        runner.scripts["disposition"] = [
            {"dials": s, "reasons": {t: f"because of {t}" for t in s}}
            for s in samples]
        return runner

    def dials(self, **over):
        from regent import disposition as disp
        d = {t: 0.0 for t in disp.TRAITS}
        d.update(over)
        return d

    def test_it_reads_three_times_by_default(self):
        from regent.owner import read_disposition
        runner = self.a_reader(self.dials(bold=-0.4), self.dials(bold=-0.2),
                               self.dials(bold=-0.3))
        ctx = self.boot(runner)
        reading = read_disposition(ctx, "a description")
        self.assertEqual(len(runner.calls_for("disposition")), 3)
        self.assertEqual(len(reading.samples), 3)

    def test_the_number_shown_is_the_median(self):
        from regent.owner import read_disposition
        ctx = self.boot(self.a_reader(self.dials(bold=-0.9),
                                      self.dials(bold=-0.1),
                                      self.dials(bold=-0.5)))
        reading = read_disposition(ctx, "x")
        self.assertEqual(reading.dials["bold"], -0.5)

    def test_the_spread_shows_how_far_the_readings_sat_apart(self):
        from regent.owner import read_disposition
        ctx = self.boot(self.a_reader(self.dials(stubborn=0.4),
                                      self.dials(stubborn=-0.2),
                                      self.dials(stubborn=0.1)))
        reading = read_disposition(ctx, "x")
        self.assertAlmostEqual(reading.spread["stubborn"], 0.6, places=3)
        self.assertEqual(reading.widest()[0][0], "stubborn")

    def test_a_dial_that_changed_sign_is_called_out(self):
        from regent import disposition as disp
        from regent.owner import read_disposition
        ctx = self.boot(self.a_reader(self.dials(stubborn=0.4),
                                      self.dials(stubborn=-0.2),
                                      self.dials(stubborn=0.1)))
        reading = read_disposition(ctx, "x")
        text = disp.render(reading.disposition(), None, reading)
        self.assertIn("Least settled", text)
        self.assertIn("stubborn", text)
        self.assertIn("spread", text)

    def test_the_reason_kept_is_from_the_sample_nearest_the_median(self):
        from regent.owner import read_disposition
        runner = stepping_runner(wake=[decision()])
        def why(text):
            from regent import disposition as disp
            return {t: (text if t == "bold" else "x") for t in disp.TRAITS}

        runner.scripts["disposition"] = [
            {"dials": self.dials(bold=-0.9), "reasons": why("far one")},
            {"dials": self.dials(bold=-0.5), "reasons": why("the middle")},
            {"dials": self.dials(bold=-0.1), "reasons": why("other far")},
        ]
        ctx = self.boot(runner)
        reading = read_disposition(ctx, "x")
        self.assertEqual(reading.reasons["bold"], "the middle")


class TestApplyStoresWhatWasShown(HarnessCase):
    """Approval has to mean the numbers that were on the screen."""

    def a_life(self):
        from test_life import life_runner
        cfg = Config()
        cfg.life.enabled = True
        cfg.life.backstory_days = 2
        cfg.life.days_per_call = 2
        cfg.cycle_in_background = False
        cfg.life.owners_dir = str(self.root / "owners")
        cfg.life.owner = "piotr"
        runner = life_runner(wake=[decision()])
        runner.scripts["disposition"] = [
            {"dials": {"bold": -0.4, "curious": -0.1, "patient": 0.4,
                       "trusting": 0.2, "thorough": 0.4, "stubborn": 0.4,
                       "restless": -0.3},
             "reasons": {t: "x" for t in
                         ("bold", "curious", "patient", "trusting", "thorough",
                          "stubborn", "restless")}},
            {"dials": {"bold": -0.2, "curious": 0.5, "patient": 0.25,
                       "trusting": 0.25, "thorough": 0.65, "stubborn": -0.2,
                       "restless": -0.55},
             "reasons": {t: "y" for t in
                         ("bold", "curious", "patient", "trusting", "thorough",
                          "stubborn", "restless")}},
            {"dials": {"bold": -0.35, "curious": 0.1, "patient": 0.35,
                       "trusting": 0.2, "thorough": 0.5, "stubborn": 0.1,
                       "restless": -0.4},
             "reasons": {t: "z" for t in
                         ("bold", "curious", "patient", "trusting", "thorough",
                          "stubborn", "restless")}},
        ]
        ctx = self.boot(runner, cfg=cfg)
        ctx.life_writer.bootstrap()
        return ctx, runner

    def call(self, ctx, **kw):
        from regent.owner import disposition_command
        return disposition_command(ctx, "piotr", ctx.cfg.life.owners_dir, **kw)

    def test_apply_makes_no_model_call(self):
        ctx, runner = self.a_life()
        code, _ = self.call(ctx)
        self.assertEqual(code, 0)
        before = len(runner.calls_for("disposition"))
        self.assertEqual(before, 3)

        code, out = self.call(ctx, apply=True)
        self.assertEqual(code, 0)
        self.assertEqual(len(runner.calls_for("disposition")), before)
        self.assertIn("stored exactly as shown", out)

    def test_what_is_stored_is_what_was_shown(self):
        import json
        ctx, _ = self.a_life()
        self.call(ctx)
        shown = ctx.store.read_json(ctx.life.root / "disposition.reading.json")
        self.call(ctx, apply=True)
        stored = json.loads((ctx.life.root / "disposition.json").read_text())
        from regent import disposition as disp
        for t in disp.TRAITS:
            self.assertEqual(stored[t], shown["dials"][t], t)
        # And the median, not any one sample.
        self.assertEqual(stored["stubborn"], 0.1)

    def test_apply_before_any_reading_refuses(self):
        ctx, runner = self.a_life()
        code, out = self.call(ctx, apply=True)
        self.assertEqual(code, 1)
        self.assertIn("nothing has been read yet", out)
        self.assertEqual(runner.calls_for("disposition"), [])

    def test_a_stored_disposition_is_fixed_until_someone_asks(self):
        ctx, runner = self.a_life()
        self.call(ctx)
        self.call(ctx, apply=True)
        before = len(runner.calls_for("disposition"))
        code, out = self.call(ctx)
        self.assertEqual(code, 0)
        self.assertEqual(len(runner.calls_for("disposition")), before)
        self.assertIn("already stored", out)

    def test_reread_takes_a_new_reading(self):
        ctx, runner = self.a_life()
        self.call(ctx)
        self.call(ctx, apply=True)
        before = len(runner.calls_for("disposition"))
        self.call(ctx, reread=True)
        self.assertGreater(len(runner.calls_for("disposition")), before)

    def test_a_word_pin_is_read_the_same_three_times(self):
        from regent.owner import cast
        runner = stepping_runner(wake=[decision()])
        runner.scripts["disposition"] = [
            {"dials": {t: 0.3 for t in
                       ("bold", "curious", "patient", "trusting", "thorough",
                        "stubborn", "restless")}, "reasons": {}}]
        ctx = self.boot(runner)
        rows = cast(ctx, pins=["impatient, thorough"], candidates=1)
        self.assertEqual(len(runner.calls_for("disposition")), 3)
        self.assertIsNotNone(rows[0]["reading"])
