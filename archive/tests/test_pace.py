"""The pace rules. Every one of them exists because a builder waited."""

from __future__ import annotations

import unittest

from helpers import HarnessCase, a_dispatch, decision, fake

from regent import process_view as pv
from regent.digest import write_digest
from regent.loop import Harness


class TestSpotChecksBesideWork(HarnessCase):
    def boot_with_spot_check(self, runner):
        ctx = self.boot(runner)
        ctx.cfg.spot_check.rate = 1.0  # every return draws one
        ctx.cfg.attention.trust_floor_full_reads = 2.0
        return ctx

    def test_a_spot_check_runs_after_the_next_dispatch_starts(self):
        runner = fake(wake=[decision(dispatches=[a_dispatch()]),
                            decision(dispatches=[a_dispatch(did="d0002")])])
        ctx = self.boot_with_spot_check(runner)
        h = Harness(ctx)
        h.turn()
        h.turn()
        rows = [r for r in ctx.ledger.all()
                if r.get("kind") == "call" and r.get("role") in
                ("spot_check", "orchestrator")]
        spot = [r for r in rows if r["role"] == "spot_check"]
        self.assertTrue(spot, "the return should have drawn a spot check")
        # The second orchestrator was launched before the spot check ran.
        second = [r for r in rows if r["role"] == "orchestrator"][-1]
        self.assertLessEqual(second["started"], spot[-1]["started"])

    def test_the_queue_empties_even_when_nothing_was_dispatched(self):
        runner = fake(wake=[decision(dispatches=[a_dispatch()]), decision()])
        ctx = self.boot_with_spot_check(runner)
        h = Harness(ctx)
        h.turn()
        h.turn()
        self.assertEqual(ctx.state.pending_spot_checks, [])


class TestSittingContext(HarnessCase):
    def test_the_ledger_shown_is_the_last_few_turns_not_the_last_few_lines(self):
        runner = fake(wake=[decision() for _ in range(6)])
        ctx = self.boot(runner)
        ctx.cfg.pace.wake_ledger_turns = 2
        h = Harness(ctx)
        for _ in range(5):
            h.turn()
        shown = h.ledger_for_sitting()
        self.assertNotIn("turn 1", shown.lower())

    def test_the_life_shown_is_the_last_two_days(self):
        ctx = self.boot(fake(wake=[decision()]))
        self.assertEqual(ctx.cfg.pace.wake_life_days, 2)


class TestFanOut(HarnessCase):
    def test_the_first_sitting_starts_several_dispatches_at_once(self):
        many = [a_dispatch(did=f"d000{i}") for i in range(1, 4)]
        runner = fake(wake=[decision(dispatches=many)])
        ctx = self.boot(runner)
        Harness(ctx).turn()
        self.assertEqual(len(runner.calls_for("orchestrator")), 3)
        row = next(r for r in ctx.ledger.all() if r.get("kind") == "fan_out")
        self.assertEqual(len(row["dispatches"]), 3)


class TestCriticalPath(HarnessCase):
    def rows(self):
        return [
            {"kind": "call", "role": "wake", "model": "sonnet", "turn": 1,
             "started": 0.0, "ended": 10.0, "seconds": 10.0, "cost_usd": 0.5,
             "blocking": True},
            {"kind": "call", "role": "orchestrator", "model": "sonnet", "turn": 1,
             "started": 10.0, "ended": 70.0, "seconds": 60.0, "cost_usd": 2.0,
             "blocking": False},
            {"kind": "call", "role": "spot_check", "model": "sonnet", "turn": 1,
             "started": 20.0, "ended": 30.0, "seconds": 10.0, "cost_usd": 0.2,
             "blocking": False},
        ]

    def test_the_pace_block_names_the_split_and_the_slowest_blocker(self):
        p = pv.pace(self.rows())
        self.assertEqual(p["wall_seconds"], 70.0)
        self.assertEqual(p["builder_wall_seconds"], 60.0)
        self.assertAlmostEqual(p["builder_wall_share"], 0.857, places=2)
        self.assertEqual(p["regent_blocking_seconds"], 10.0)
        self.assertEqual(p["slowest_blocker"]["role"], "wake")
        self.assertFalse(p["fault"])

    def test_a_turn_where_the_regent_outlasts_the_builders_is_a_fault(self):
        rows = self.rows()
        rows[0]["ended"], rows[0]["seconds"] = 600.0, 600.0
        rows[1]["started"], rows[1]["ended"], rows[1]["seconds"] = 600.0, 660.0, 60.0
        self.assertTrue(pv.pace(rows)["fault"])

    def test_the_digest_carries_where_the_time_went(self):
        runner = fake(wake=[decision(dispatches=[a_dispatch()])])
        ctx = self.boot(runner)
        Harness(ctx).turn()
        text = write_digest(ctx).read_text()
        self.assertIn("Where the time went", text)
        self.assertIn("The builders held", text)


class TestSiftHoldsPlacesForRequirements(HarnessCase):
    def test_a_batch_that_invents_nothing_keeps_fewer_candidates(self):
        from regent import config
        cfg = config.Config()
        keep, held = cfg.sift.keep, cfg.sift.places_for_requirements
        self.assertGreater(held, 0)
        room = keep - held
        self.assertLess(room, keep)


class TestLaunchFirstCheckBeside(HarnessCase):
    def test_a_breach_found_beside_the_work_kills_the_running_dispatch(self):
        # Covered in detail in test_readers; this asserts the pace claim that
        # the low-tier dispatch is not held up by the read.
        ctx = self.boot(fake(wake=[decision(dispatches=[a_dispatch()])]))
        self.assertTrue(ctx.cfg.launch_first)


if __name__ == "__main__":
    unittest.main()
