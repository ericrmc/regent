"""What happens when a call fails. A model that returns nothing usable must not
turn into a loop that spends the budget and moves no work.
"""

from __future__ import annotations

import unittest

from helpers import HarnessCase, a_dispatch, decision, fake, return_block

from regent.loop import Harness
from regent.runner import ModelResponse


class TestFailedCalls(HarnessCase):
    def test_a_run_of_useless_wake_calls_stops_the_run(self):
        runner = fake()
        runner.scripts["wake"] = [ModelResponse(role="wake", is_error=True, error="boom")]
        ctx = self.boot(runner)
        reason = Harness(ctx).run(max_turns=0)
        self.assertIn("no usable decision", reason)
        self.assertEqual(ctx.state.turn, ctx.cfg.max_failed_turns)

    def test_a_run_of_turns_that_change_nothing_stops(self):
        ctx = self.boot(fake(wake=[decision()]))
        reason = Harness(ctx).run(max_turns=0)
        self.assertIn("changed nothing", reason)
        self.assertEqual(ctx.state.turn, ctx.cfg.max_idle_turns)

    def test_one_bad_turn_does_not_stop_a_run_that_recovers(self):
        runner = fake()
        runner.scripts["wake"] = [
            ModelResponse(role="wake", is_error=True, error="boom"),
            decision(),
            decision(stop={"requested": True, "reason": "done"}),
        ]
        ctx = self.boot(runner)
        reason = Harness(ctx).run(max_turns=0)
        self.assertEqual(reason, "done")
        self.assertEqual(ctx.state.failed_turns, 0)

    def test_an_orchestrator_that_returns_nothing_is_a_flagged_return(self):
        runner = fake(wake=[decision(dispatches=[a_dispatch()]), decision()])
        runner.scripts["orchestrator"] = [
            ModelResponse(role="orchestrator", is_error=True, error="the process died")]
        ctx = self.boot(runner)
        h = Harness(ctx)
        h.turn()
        h.turn()
        ret = ctx.store.read_json(ctx.store.returns / "r00001.json")
        self.assertFalse(ret["parsed"])
        self.assertEqual(ret["flags"][0]["tier"], "medium")

    def test_a_failed_saturate_does_not_stop_the_cycle(self):
        runner = fake()
        runner.scripts["saturate"] = [ModelResponse(role="saturate", is_error=True)]
        ctx = self.boot(runner)
        rec = ctx.spoon.run(trigger="test")
        self.assertEqual(rec.motifs, [])
        self.assertTrue(runner.calls_for("drift"))

    def test_a_failed_sift_leaves_the_links_held_and_nothing_gated_through(self):
        runner = fake(drift=[{"links": [
            {"kind": "seed", "text": "a link", "anchors": ["m00001"],
             "ingredients": [], "mechanism": "m"}]}])
        runner.scripts["sift"] = [ModelResponse(role="sift", is_error=True)]
        ctx = self.boot(runner)
        rec = ctx.spoon.run(trigger="test")
        self.assertTrue(rec.links)
        self.assertEqual(rec.kept, [])
        self.assertTrue((ctx.store.holding / f"cycle-{rec.cycle:04d}.jsonl").exists())

    def test_a_model_that_returns_prose_around_json_is_still_read(self):
        runner = fake()
        runner.scripts["wake"] = [ModelResponse(
            role="wake", structured=None,
            text="Here is my decision:\n```json\n"
                 + __import__("json").dumps(decision()) + "\n```\nThat is all.")]
        ctx = self.boot(runner)
        h = Harness(ctx)
        h.turn()
        self.assertEqual(ctx.state.failed_turns, 0)

    def test_an_unknown_runner_name_is_an_error_at_the_call_and_not_at_import(self):
        ctx = self.boot(fake())
        ctx.cfg.runners.by_role["sift"] = "a-vendor-that-is-not-configured"
        with self.assertRaises(KeyError):
            ctx.runner_for("sift")


class TestConcurrency(HarnessCase):
    def test_dispatches_run_up_to_the_cap_and_the_rest_wait(self):
        """The cap binds only while children are alive, so the fake blocks."""
        import threading
        gate = threading.Event()

        def slow(req):
            gate.wait(timeout=10)
            return ModelResponse(role=req.role, text=return_block())

        items = [a_dispatch(f"d{i:04d}") for i in range(6)]
        runner = fake(wake=[decision(dispatches=items), decision()])
        runner.scripts["orchestrator"] = [slow]
        ctx = self.boot(runner)
        h = Harness(ctx)
        try:
            h.start_dispatches(items)
            self.assertLessEqual(len(runner.calls_for("orchestrator")),
                                 ctx.cfg.dispatching.max_concurrent)
            self.assertEqual(len(ctx.pool.in_flight), ctx.cfg.dispatching.max_concurrent)
            self.assertFalse(ctx.pool.has_room())
        finally:
            gate.set()
            ctx.pool.collect(timeout=10)

    def test_a_dispatch_resumes_its_session_for_the_life_of_the_task(self):
        d = a_dispatch()
        runner = fake(wake=[decision(dispatches=[d]), decision(dispatches=[d]),
                            decision()])
        ctx = self.boot(runner)
        h = Harness(ctx)
        h.turn()
        first = runner.calls_for("orchestrator")[0]
        h.turn()
        second = runner.calls_for("orchestrator")[1]
        self.assertEqual(first.session_id, second.session_id)
        self.assertFalse(first.resume)
        self.assertTrue(second.resume)

    def test_unease_blocks_a_dispatch_and_demands_a_check(self):
        ctx = self.boot(fake(wake=[decision(dispatches=[a_dispatch()])]))
        ctx.state.signals.unease = 1.0
        Harness(ctx).turn()
        self.assertEqual(self.runner.calls_for("orchestrator"), [])
        blocked = [r for r in ctx.ledger.all()
                   if r["kind"] == "signal" and "unease blocked" in str(r.get("summary"))]
        self.assertTrue(blocked)


if __name__ == "__main__":
    unittest.main()
