"""Step 13. The human steers without ordering, and the owner never knows."""

from __future__ import annotations

import unittest

from helpers import HarnessCase, a_dispatch, decision, fake, return_block
from test_life import LifeCase, life_runner

from regent import influence as infl
from regent.loop import Harness

MARKER = "ZZQ_TOKEN_7731"
WORDS = ("influence", "planted", "plant", "nudge", "whisper", "push",
         "steer", "inf-0001", "the human", "supplied")


class TestTheFile(HarnessCase):
    def test_every_channel_takes_and_records_a_weight(self):
        ctx = self.boot(fake(wake=[decision()]))
        for channel in infl.CHANNELS:
            ctx.influence.add(channel, text="something", turn=1)
        rows = ctx.influence.all()
        self.assertEqual(len(rows), len(infl.CHANNELS))
        self.assertEqual({r.channel for r in rows}, set(infl.CHANNELS))
        self.assertTrue(all(r.status == infl.PENDING for r in rows))

    def test_the_three_weights_differ_in_how_long_they_last(self):
        ctx = self.boot(fake(wake=[decision()]))
        a = ctx.influence.add(infl.PLANT, text="a", weight="whisper", turn=1)
        b = ctx.influence.add(infl.PLANT, text="b", weight="push", turn=1)
        self.assertEqual(a.uses_left, 1)
        self.assertEqual(b.uses_left, 3)
        self.assertEqual(infl.derived_worry(b), "b")
        self.assertEqual(infl.derived_worry(a), "")

    def test_an_unknown_channel_or_weight_is_refused(self):
        ctx = self.boot(fake(wake=[decision()]))
        with self.assertRaises(infl.EvidenceLine):
            ctx.influence.add("bribe", text="x", turn=1)
        with self.assertRaises(infl.EvidenceLine):
            ctx.influence.add(infl.PLANT, text="x", weight="shove", turn=1)

    def test_the_file_sits_outside_everything_a_model_reads(self):
        ctx = self.boot(fake(wake=[decision()]))
        ctx.influence.add(infl.PLANT, text=MARKER, turn=1)
        self.assertTrue(ctx.influence.path.exists())
        self.assertIn(MARKER, ctx.influence.path.read_text())
        self.assertNotIn(MARKER, ctx.store.ledger.read_text())


class TestTheEvidenceLine(unittest.TestCase):
    """It enters through the life and through attention, never through
    evidence. The human may point the owner's eye at a real thing. The human
    may not put a false thing in front of it.
    """

    def test_no_channel_may_enter_through_evidence(self):
        for channel in infl.CHANNELS:
            for surface in ("return", "spot_check_finding", "ledger", "evidence",
                            "friction", "sensory", "verbatim", "unfinished"):
                with self.assertRaises(infl.EvidenceLine, msg=f"{channel}/{surface}"):
                    infl.check_surface(channel, surface)

    def test_a_life_channel_may_not_enter_through_attention(self):
        for channel in infl.LIFE_CHANNELS:
            with self.assertRaises(infl.EvidenceLine):
                infl.check_surface(channel, "salience")

    def test_an_attention_channel_may_not_enter_through_the_life(self):
        for channel in infl.ATTENTION_CHANNELS:
            with self.assertRaises(infl.EvidenceLine):
                infl.check_surface(channel, "life")

    def test_the_real_pairings_are_allowed(self):
        infl.check_surface(infl.PLANT, "life")
        infl.check_surface(infl.VOICE, "life")
        infl.check_surface(infl.READING, "foreign")
        infl.check_surface(infl.MOOD, "stance")
        infl.check_surface(infl.DREAM, "life")
        infl.check_surface(infl.WORRY, "salience")
        infl.check_surface(infl.ITCH, "spot_check_target")
        infl.check_surface(infl.RECALL, "replay")


class TestInvisibility(LifeCase):
    """A marker goes in through every channel. It must reach the owner's
    material and never reach anything that says where it came from.
    """

    def every_channel(self, ctx):
        ctx.influence.add(infl.PLANT, text=f"a remark about {MARKER}", turn=0)
        ctx.influence.add(infl.VOICE, text=f"they said {MARKER}",
                          subject="Roisin", turn=0)
        ctx.influence.add(infl.READING, text=f"a page about {MARKER}", turn=0)
        ctx.influence.add(infl.MOOD, text="risk", days=2, turn=0)
        ctx.influence.add(infl.WORRY, text=MARKER, days=2, turn=0)
        ctx.influence.add(infl.ITCH, text=MARKER, turn=0)
        ctx.influence.add(infl.DREAM, text=MARKER, turn=0)

    def run_with_everything(self):
        runner = life_runner(wake=[decision(dispatches=[a_dispatch()]),
                                   decision(), decision()])
        cfg = self.cfg
        cfg.life.backstory_days = 1
        cfg.attention.band_full = 9.0
        cfg.attention.band_skim = 0.0
        ctx = self.boot(runner, cfg=cfg)
        self.every_channel(ctx)
        ctx.life_writer.bootstrap()
        h = Harness(ctx)
        h.turn()
        h.turn()
        ctx.cfg.interlude.weights = {k: (1.0 if k == "day" else 0.0)
                                     for k in ctx.cfg.interlude.weights}
        h.interlude()
        ctx.save()
        return ctx, runner

    def test_no_assembled_model_context_says_where_anything_came_from(self):
        ctx, runner = self.run_with_everything()
        prompts = [c.prompt for c in runner.calls] + \
                  [c.system or "" for c in runner.calls]
        self.assertTrue(prompts)
        blob = "\n".join(prompts).lower()
        for word in ("influence", "planted", "inf-0001", "the human supplied",
                     "whisper", "was steered"):
            self.assertNotIn(word, blob, f"{word} reached a model context")

    def test_the_marker_reaches_the_owners_material_without_its_origin(self):
        ctx, runner = self.run_with_everything()
        day_prompts = [c.prompt for c in runner.calls_for("life_day")]
        self.assertTrue(day_prompts)
        reached = any(MARKER in p for p in day_prompts)
        self.assertTrue(reached, "the plant never reached a day")
        for p in day_prompts:
            if MARKER not in p:
                continue
            block = p[max(0, p.index(MARKER) - 400):p.index(MARKER) + 400].lower()
            for word in ("influence", "planted", "supplied by", "inf-"):
                self.assertNotIn(word, block)

    def test_the_ledger_never_carries_an_influence(self):
        ctx, _ = self.run_with_everything()
        text = ctx.store.ledger.read_text().lower()
        self.assertNotIn("influence", text)
        self.assertNotIn("inf-00", text)
        for row in ctx.ledger.all():
            self.assertNotEqual(row.get("kind"), "influence")

    def test_no_stored_return_carries_an_influence(self):
        ctx, _ = self.run_with_everything()
        for path in ctx.store.returns.glob("*.json"):
            blob = path.read_text().lower()
            self.assertNotIn("influence", blob)
            self.assertNotIn("inf-00", blob)

    def test_the_state_file_carries_no_influence(self):
        ctx, _ = self.run_with_everything()
        blob = ctx.store.state.read_text().lower()
        self.assertNotIn("influence", blob)
        self.assertNotIn("inf-00", blob)

    def test_the_owners_own_files_carry_no_mark(self):
        ctx, _ = self.run_with_everything()
        for path in (ctx.store.self_md, ctx.store.taste, ctx.store.memory):
            blob = path.read_text().lower()
            self.assertNotIn("influence", blob)
            self.assertNotIn("inf-00", blob)

    def test_the_day_plan_carries_no_key_naming_the_channel(self):
        """A key named for the channel would be read by the writer."""
        ctx, runner = self.run_with_everything()
        for c in runner.calls_for("life_day"):
            block = c.prompt.split("## The day")[1].split("## Threads")[0]
            for word in ("plant", "voice", "influence", "planted"):
                self.assertNotIn(word, block.lower())


class TestChannelsDoTheirThing(LifeCase):
    def test_a_plant_joins_the_rolled_events(self):
        ctx = self.boot(life_runner(), cfg=self.cfg)
        ctx.influence.add(infl.PLANT, text="a jammed gate at the allotment", turn=0)
        ctx.life_writer.write_bible()
        ctx.life_writer.write_day()
        prompt = self.runner.calls_for("life_day")[-1].prompt
        self.assertIn("a jammed gate at the allotment", prompt)
        self.assertEqual(ctx.influence.all()[0].uses_left, 0)
        self.assertGreaterEqual(ctx.influence.all()[0].entered_turn, 0)

    def test_a_voice_is_given_to_the_named_person(self):
        ctx = self.boot(life_runner(), cfg=self.cfg)
        ctx.influence.add(infl.VOICE, text="you never finish anything",
                          subject="Roisin", turn=0)
        ctx.life_writer.write_bible()
        ctx.life_writer.write_day()
        prompt = self.runner.calls_for("life_day")[-1].prompt
        self.assertIn("you never finish anything", prompt)
        self.assertIn("Roisin", prompt)

    def test_a_reading_arrives_as_foreign_material(self):
        ctx = self.boot(life_runner(), cfg=self.cfg)
        ctx.influence.add(infl.READING, text="a note on bridge inspection", turn=0)
        ctx.life_writer.write_bible()
        ctx.life_writer.write_day()
        prompt = self.runner.calls_for("life_day")[-1].prompt
        self.assertIn("a note on bridge inspection", prompt)

    def test_a_mood_lean_moves_the_stance_baseline(self):
        ctx = self.boot(life_runner(wake=[decision()]), cfg=self.cfg)
        ctx.influence.add(infl.MOOD, text="risk", days=2, turn=0)
        before = ctx.state.stance.baseline
        Harness(ctx).apply_mood_influence()
        self.assertLess(ctx.state.stance.baseline, before)

    def test_an_opportunity_lean_moves_it_the_other_way(self):
        ctx = self.boot(life_runner(wake=[decision()]), cfg=self.cfg)
        ctx.influence.add(infl.MOOD, text="opportunity", days=2, turn=0)
        before = ctx.state.stance.baseline
        Harness(ctx).apply_mood_influence()
        self.assertGreater(ctx.state.stance.baseline, before)

    def test_a_worry_reaches_the_salience_pull(self):
        """The eye catches the thing it is worried about."""
        runner = life_runner(wake=[decision(dispatches=[a_dispatch()]), decision()])
        runner.scripts["orchestrator"] = [return_block(detail=[
            {"heading": "What was built",
             "body": "The checker walks the folder. "
                     "The queue is unbounded and nobody has looked at it."}])]
        runner.scripts["salience"] = [{"keep": [0]}]
        cfg = self.cfg
        cfg.attention.band_full = 9.0
        cfg.attention.band_skim = 0.0
        ctx = self.boot(runner, cfg=cfg)
        ctx.influence.add(infl.WORRY, text="unbounded queue", days=3, turn=0)
        h = Harness(ctx)
        h.turn()
        h.turn()
        calls = runner.calls_for("salience")
        self.assertTrue(calls, "the skim never called the salience pull")
        self.assertIn("unbounded queue", calls[0].prompt)
        self.assertEqual(ctx.influence.all()[0].uses_left, 2)

    def test_an_itch_points_the_next_spot_check(self):
        runner = life_runner(wake=[decision(dispatches=[a_dispatch()]), decision()])
        ctx = self.boot(runner, cfg=self.cfg)
        ctx.influence.add(infl.ITCH, text="the anchor resolver", turn=0)
        h = Harness(ctx)
        h.turn()
        h.turn()
        calls = runner.calls_for("spot_check")
        self.assertTrue(calls)
        self.assertIn("the anchor resolver", calls[0].prompt)

    def test_a_recall_brings_the_named_element_back(self):
        ctx = self.boot(life_runner(wake=[decision()]), cfg=self.cfg)
        el = ctx.manifold.write("unfinished", "a branch nobody finished", cycle=0)
        ctx.manifold.decay(cycle=999)
        ctx.influence.add(infl.RECALL, text=el.id, turn=0)
        ctx.cfg.interlude.weights = {k: (1.0 if k == "replay" else 0.0)
                                     for k in ctx.cfg.interlude.weights}
        rec = Harness(ctx).interlude()
        self.assertEqual(rec["element_id"], el.id)
        self.assertIn(el.id, [e.id for e in ctx.manifold.warm()])

    def test_a_dream_starts_from_the_theme(self):
        runner = life_runner(wake=[decision()], drift=[{"links": []}])
        ctx = self.boot(runner, cfg=self.cfg)
        ctx.influence.add(infl.DREAM, text="things that wear out slowly", turn=0)
        ctx.cfg.interlude.weights = {k: (1.0 if k == "dream" else 0.0)
                                     for k in ctx.cfg.interlude.weights}
        h = Harness(ctx)
        h.interlude()
        # A dream is a cycle, so it runs beside the work.
        h.wait_for_cycle(timeout=20)
        self.assertIn("things that wear out slowly",
                      runner.calls_for("drift")[0].prompt)

    def test_a_plant_forces_a_day_where_none_is_due(self):
        runner = life_runner(wake=[decision(), decision(), decision(), decision()])
        cfg = self.cfg
        cfg.life.backstory_days = 1
        cfg.interlude.weights = {k: (1.0 if k == "nothing" else 0.0)
                                 for k in cfg.interlude.weights}
        ctx = self.boot(runner, cfg=cfg)
        ctx.life_writer.bootstrap()
        ctx.state.life_day_count = ctx.life.index().day_count
        before = ctx.life.index().day_count
        ctx.influence.add(infl.PLANT, text="a jammed gate", turn=0)
        h = Harness(ctx)
        for _ in range(4):
            h.turn()
        self.assertGreater(ctx.life.index().day_count, before)


class TestItMayNotTake(HarnessCase):
    def test_an_influence_that_entered_and_led_nowhere_fades(self):
        rows = [infl.Influence(id="inf-0001", channel=infl.PLANT, text="x",
                               entered_turn=1, uses_left=0)]
        out = infl.settle(rows, turn=20, fade_after=8)
        self.assertEqual(out[0].status, infl.FADED)
        self.assertIn("nothing came of it", out[0].outcome)

    def test_one_that_led_to_something_thrown_out_is_rejected(self):
        rows = [infl.Influence(id="inf-0001", channel=infl.PLANT, text="x",
                               entered_turn=1, uses_left=0,
                               traces=[{"kind": "drift", "ref": "cycle-1",
                                        "survived": False}])]
        out = infl.settle(rows, turn=20, fade_after=8)
        self.assertEqual(out[0].status, infl.REJECTED)

    def test_one_that_led_to_something_kept_took(self):
        rows = [infl.Influence(id="inf-0001", channel=infl.PLANT, text="x",
                               entered_turn=1, uses_left=0,
                               traces=[{"kind": "requirement", "ref": "req-0001",
                                        "survived": True}])]
        out = infl.settle(rows, turn=20, fade_after=8)
        self.assertEqual(out[0].status, infl.TOOK)
        self.assertIn("req-0001", out[0].outcome)

    def test_one_not_yet_met_stays_pending(self):
        rows = [infl.Influence(id="inf-0001", channel=infl.PLANT, text="x")]
        self.assertEqual(infl.settle(rows, turn=50, fade_after=8)[0].status,
                         infl.PENDING)

    def test_it_changes_nothing_the_owner_is_permitted(self):
        """A plant passes through the same gates the owner's own ideas do."""
        from regent import decision as dec
        from regent.charter import parse_charter
        ctx = self.boot(fake(wake=[decision()]))
        ctx.influence.add(infl.PLANT, text="he should just publish it outside "
                                           "the project directory", turn=0)
        d = decision(dispatches=[a_dispatch(
            tier="medium",
            intent="Publish the report outside the project directory.",
            classes=["publishing outside the project directory"])])
        v = dec.validate_decision(d, ctx.charter, ctx.cfg)
        self.assertEqual(v.decision["dispatches"], [])
        self.assertEqual(len(v.escalations), 1)
        self.assertTrue(parse_charter(ctx.store.charter).refusals)


class TestTheTrace(LifeCase):
    def test_a_drift_link_anchoring_a_planted_element_is_traced(self):
        runner = life_runner(wake=[decision()])
        ctx = self.boot(runner, cfg=self.cfg)
        ctx.life_writer.write_bible()
        ctx.influence.add(infl.PLANT, text="a jammed gate", turn=0)
        ctx.life_writer.write_day()
        planted = ctx.influence.all()[0]
        self.assertTrue(planted.element_ids)
        eid = planted.element_ids[0]

        runner.scripts["drift"] = [{"links": [
            {"kind": "structural analogy", "text": "a gate that sticks",
             "anchors": ["m00001", eid], "ingredients": [], "mechanism": "wear"}]}]
        ctx.manifold.write("friction", "a real project element")
        ctx.spoon.run(trigger="test")
        Harness(ctx).settle_influence()
        row = ctx.influence.all()[0]
        self.assertTrue(row.traces)
        self.assertEqual(row.traces[0]["kind"], "drift")
        self.assertIn(eid, row.traces[0]["detail"])

    def test_an_itch_that_found_something_is_traced_to_the_spot_check(self):
        runner = life_runner(wake=[decision(dispatches=[a_dispatch()]), decision()])
        runner.scripts["spot_check"] = [{
            "findings": "The anchors are not resolved at all.",
            "verdicts": [], "gap": True, "openings": ["it could report them"]}]
        ctx = self.boot(runner, cfg=self.cfg)
        ctx.influence.add(infl.ITCH, text="the anchor resolver", turn=0)
        h = Harness(ctx)
        h.turn()
        h.turn()
        row = ctx.influence.all()[0]
        self.assertTrue(row.traces)
        self.assertEqual(row.traces[0]["kind"], "spot_check")
        self.assertTrue(row.traces[0]["survived"])


class TestWhatTheHumanSees(HarnessCase):
    def test_the_digest_appendix_is_human_only_and_after_every_model_call(self):
        from regent.digest import human_only, write_digest
        ctx = self.boot(fake(wake=[decision()]))
        ctx.influence.add(infl.PLANT, text="a jammed gate", turn=0)
        Harness(ctx).turn()
        text = human_only(ctx)
        self.assertIn("What came of your influence", text)
        self.assertIn("This part is yours", text)
        path = write_digest(ctx, 0)
        blob = path.read_text()
        self.assertIn("What came of your influence", blob)
        # It is appended, so it is after the parts built from the ledger.
        self.assertGreater(blob.index("What came of your influence"),
                           blob.index("# Digest"))

    def test_no_model_call_ever_receives_the_digest(self):
        ctx = self.boot(fake(wake=[decision(), decision()]))
        ctx.influence.add(infl.PLANT, text="a jammed gate", turn=0)
        h = Harness(ctx)
        h.turn()
        from regent.digest import write_digest
        write_digest(ctx, 0)
        h.turn()
        for c in self.runner.calls:
            self.assertNotIn("What came of your influence", c.prompt)

    def test_the_export_carries_a_human_only_block(self):
        from regent.export import build_export
        ctx = self.boot(fake(wake=[decision()]))
        ctx.influence.add(infl.PLANT, text="a jammed gate", turn=0)
        Harness(ctx).turn()
        ctx.save()
        data = build_export(ctx.store.root)
        block = data["influence"]
        self.assertTrue(block["human_only"])
        self.assertIn("does not know", block["note"])
        self.assertEqual(len(block["supplied"]), 1)
        self.assertIn(infl.PENDING, block["by_status"])

    def test_the_puppet_detector_is_shown_to_the_human_only(self):
        rows = [infl.Influence(id=f"inf-{i:04d}", channel=infl.PLANT, text="x",
                               traces=[{"kind": "requirement", "ref": f"req-{i}",
                                        "survived": True}])
                for i in range(3)]
        msg = infl.puppet_share(rows, requirement_count=4)
        self.assertIn("being steered more than they are deciding", msg)
        self.assertEqual(infl.puppet_share(rows, requirement_count=0), "")


class TestTheCli(HarnessCase):
    def run_cli(self, *argv):
        from test_cli import run_cli
        return run_cli(*argv)

    def a_run(self):
        ctx = self.boot(fake(wake=[decision()]))
        Harness(ctx).turn()
        ctx.save()
        return ctx

    def test_every_channel_has_a_command(self):
        self.a_run()
        root = str(self.store.root)
        for argv in (["influence", "plant", "a jammed gate", "--weight", "push"],
                     ["influence", "voice", "Roisin", "you never finish"],
                     ["influence", "read", "a note on bridges"],
                     ["influence", "mood", "risk", "--days", "3"],
                     ["influence", "worry", "unbounded queues"],
                     ["influence", "itch", "the anchor resolver"],
                     ["influence", "recall", "m00001"],
                     ["influence", "dream", "things that wear out"]):
            code, out = self.run_cli("--state", root, *argv)
            self.assertEqual(code, 0, argv)
            self.assertIn("will not know where", out)
        rows = infl.InfluenceStore(self.store).all()
        self.assertEqual(len(rows), 8)
        self.assertEqual({r.channel for r in rows}, set(infl.CHANNELS))

    def test_list_shows_what_came_of_it(self):
        self.a_run()
        root = str(self.store.root)
        self.run_cli("--state", root, "influence", "plant", "a jammed gate")
        code, out = self.run_cli("--state", root, "influence", "list")
        self.assertEqual(code, 0)
        self.assertIn("What came of your influence", out)
        self.assertIn("a jammed gate", out)
        self.assertIn("PENDING", out)

    def test_list_on_an_empty_file_says_so(self):
        self.a_run()
        code, out = self.run_cli("--state", str(self.store.root), "influence", "list")
        self.assertIn("nothing supplied", out)

    def test_a_plant_is_logged_with_the_turn_it_entered(self):
        turn = self.a_run().state.turn
        self.run_cli("--state", str(self.store.root), "influence", "plant", "x")
        row = infl.InfluenceStore(self.store).all()[0]
        self.assertEqual(row.created_turn, turn)

    def test_the_cli_writes_nothing_to_the_ledger(self):
        self.a_run()
        before = self.store.ledger.read_text()
        self.run_cli("--state", str(self.store.root), "influence", "plant", MARKER)
        self.assertEqual(self.store.ledger.read_text(), before)


if __name__ == "__main__":
    unittest.main()
