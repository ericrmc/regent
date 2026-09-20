"""Multi-dispatch, multi-turn and crash paths.

The review that prompted these found that almost every other test is one turn,
one process, one dispatch, which is why three live defects were invisible.
"""

from __future__ import annotations

import threading
import unittest

from helpers import HarnessCase, a_dispatch, decision, fake, return_block

from regent.config import Config
from regent.loop import Harness, bootstrap
from regent.rng import Rng
from regent.runner import ModelResponse


def latent_runner(order: list[str], wake_script=None):
    """Orchestrators that return in the order given, not the order started.

    `order` names dispatch ids. A dispatch returns once every dispatch before it
    in the list has returned, which lets a test permute child latency exactly.
    """
    gates = {did: threading.Event() for did in order}
    started = threading.Event()

    def orchestrator(req):
        did = req.stream_log.split("/")[-1].replace(".log", "")
        started.set()
        if did in gates:
            gates[did].wait(timeout=10)
        return ModelResponse(
            role="orchestrator",
            text=return_block(headline=f"{did} is done.",
                              recommendation=f"Accept {did}."))

    runner = fake(wake=wake_script or [decision()])
    runner.scripts["orchestrator"] = [orchestrator]
    runner.gates = gates
    runner.started = started
    return runner


def release(runner, order: list[str]) -> None:
    for did in order:
        runner.gates[did].set()


class TestReplayUnderConcurrency(HarnessCase):
    """A return's mode must not depend on which child finished first."""

    def modes_for(self, completion_order: list[str], seed=777) -> list[tuple]:
        items = [a_dispatch(f"d{i:04d}") for i in range(3)]
        wake = [decision(dispatches=items), decision(), decision(), decision()]
        runner = latent_runner([f"d{i:04d}" for i in range(3)], wake_script=wake)
        cfg = Config()
        cfg.life.enabled = False
        cfg.dispatching.max_concurrent = 3
        ctx = self.boot(runner, seed=seed, cfg=cfg)
        h = Harness(ctx)
        h.turn()
        release(runner, completion_order)
        for _ in range(3):
            h.turn()
        return [(r["return_id"], r["read_mode"]) for r in ctx.ledger.all()
                if r["kind"] == "read_mode"]

    def test_the_same_seed_gives_the_same_modes_whatever_the_latency_order(self):
        forward = self.modes_for(["d0000", "d0001", "d0002"])
        self.tearDown()
        self.setUp()
        reverse = self.modes_for(["d0002", "d0001", "d0000"])
        self.assertTrue(forward)
        self.assertEqual(len(forward), len(reverse))
        self.assertEqual(dict(forward), dict(reverse))

    def test_a_returns_draw_does_not_move_the_shared_counter_for_others(self):
        """Each return draws from its own substream."""
        a = Rng(seed=5).substream("return:r00001")
        b = Rng(seed=5).substream("return:r00001")
        self.assertEqual([a.random() for _ in range(4)],
                         [b.random() for _ in range(4)])
        other = Rng(seed=5).substream("return:r00002")
        self.assertNotEqual(a.seed, other.seed)

    def test_a_substream_is_stable_across_processes_for_one_seed(self):
        self.assertEqual(Rng(seed=99).substream("return:r1").seed,
                         Rng(seed=99).substream("return:r1").seed)


class TestMultipleDispatches(HarnessCase):
    def test_returns_are_read_in_dispatch_order_not_completion_order(self):
        items = [a_dispatch(f"d{i:04d}") for i in range(3)]
        wake = [decision(dispatches=items), decision(), decision()]
        runner = latent_runner([f"d{i:04d}" for i in range(3)], wake_script=wake)
        cfg = Config()
        cfg.life.enabled = False
        cfg.dispatching.max_concurrent = 3
        ctx = self.boot(runner, seed=11, cfg=cfg)
        h = Harness(ctx)
        h.turn()
        release(runner, ["d0002", "d0000", "d0001"])
        h.turn()
        read = [r["dispatch_id"] for r in ctx.ledger.all() if r["kind"] == "read_mode"]
        self.assertEqual(read, sorted(read))

    def test_three_dispatches_each_get_a_stored_return(self):
        items = [a_dispatch(f"d{i:04d}") for i in range(3)]
        wake = [decision(dispatches=items), decision(), decision()]
        runner = latent_runner([f"d{i:04d}" for i in range(3)], wake_script=wake)
        cfg = Config()
        cfg.life.enabled = False
        cfg.dispatching.max_concurrent = 3
        ctx = self.boot(runner, seed=11, cfg=cfg)
        h = Harness(ctx)
        h.turn()
        release(runner, ["d0001", "d0002", "d0000"])
        h.turn()
        stored = sorted(p.name for p in ctx.store.returns.glob("r*.json")
                        if not p.name.endswith(".view.json"))
        self.assertEqual(len(stored), 3)

    def test_a_dispatch_thread_that_raises_becomes_a_flagged_return(self):
        def boom(req):
            raise OSError("the claude binary is missing")

        runner = fake(wake=[decision(dispatches=[a_dispatch()]), decision()])
        runner.scripts["orchestrator"] = [boom]
        ctx = self.boot(runner)
        h = Harness(ctx)
        h.turn()
        h.turn()
        rows = [r for r in ctx.ledger.all() if r["kind"] == "read_mode"]
        self.assertEqual(len(rows), 1)
        ret = ctx.store.read_json(ctx.store.returns / "r00001.json")
        self.assertFalse(ret["parsed"])
        self.assertIn("the dispatch thread raised", ret["raw_text"])
        self.assertEqual(ret["flags"][0]["tier"], "medium")


class TestCrashAndResume(HarnessCase):
    """A kill between applying a decision and saving state must not re-run it."""

    def crashing_run(self, kill_after: str):
        """Run one turn, killing at a named point inside apply()."""
        items = [a_dispatch()]
        runner = fake(wake=[decision(dispatches=items, escalations=[
            {"question": "May I spend money?", "tier": "high", "why": "reserved"}]),
            decision(), decision()])
        ctx = self.boot(runner, seed=31)
        h = Harness(ctx)

        class Kill(Exception):
            pass

        if kill_after == "escalations":
            # After escalations are minted and written, before dispatches.
            def stop(*a, **k):
                raise Kill()
            h.prepare_dispatches = stop
        elif kill_after == "dispatches":
            original = h.run_inspections

            def stop(*a, **k):
                raise Kill()
            h.run_inspections = stop
            self.assertTrue(original)

        try:
            h.turn()
        except Kill:
            pass
        return ctx

    def test_a_kill_after_escalations_does_not_mint_the_id_twice_on_resume(self):
        ctx = self.crashing_run("escalations")
        first = [p.name for p in ctx.store.escalations.glob("e*.json")]
        self.assertEqual(len(first), 1)

        ctx2 = bootstrap(self.store, self.cfg, str(self.charter_path),
                         str(self.project),
                         prompts_dir=ctx.prompts.root, plugin_dir=ctx.plugin_dir,
                         runners={"claude": fake(wake=[decision()])},
                         notifier=self.notifier)
        # The escalation file is on disk and the state carries it, so a resume
        # neither loses it nor mints the id a second time.
        self.assertEqual(len(ctx2.state.escalations), 1)
        self.assertEqual(ctx2.state.escalations[0]["id"], first[0].replace(".json", ""))
        Harness(ctx2).turn()
        after = [p.name for p in ctx2.store.escalations.glob("e*.json")]
        self.assertEqual(sorted(after), sorted(first))

    def test_a_kill_after_dispatches_leaves_the_session_id_on_disk(self):
        """State is saved before any child starts, so a resume does not start
        a second orchestrator on the same objective.
        """
        ctx = self.crashing_run("dispatches")
        on_disk = self.store.read_json(self.store.state)
        d = on_disk["dispatches"]["d0001"]
        self.assertTrue(d["session_id"])
        self.assertEqual(d["status"], "open")

        ctx2 = bootstrap(self.store, self.cfg, str(self.charter_path),
                         str(self.project),
                         prompts_dir=ctx.prompts.root, plugin_dir=ctx.plugin_dir,
                         runners={"claude": fake(wake=[decision(
                             dispatches=[a_dispatch()])])},
                         notifier=self.notifier)
        self.assertEqual(ctx2.state.dispatch("d0001").session_id, d["session_id"])
        h2 = Harness(ctx2)
        h2.turn()
        # The same id resumes its session rather than starting a fresh one.
        calls = ctx2.runners["claude"].calls_for("orchestrator")
        self.assertTrue(calls)
        self.assertTrue(calls[-1].resume)
        self.assertEqual(calls[-1].session_id, d["session_id"])

    def test_the_apply_intent_and_done_rows_bracket_the_children(self):
        runner = fake(wake=[decision(dispatches=[a_dispatch()]), decision()])
        ctx = self.boot(runner)
        Harness(ctx).turn()
        rows = [r for r in ctx.ledger.all() if r["kind"] == "apply"]
        self.assertEqual([r["state"] for r in rows], ["intent", "done"])
        dispatch_seq = [r["seq"] for r in ctx.ledger.all()
                        if r["kind"] == "dispatch"][0]
        self.assertLess(rows[0]["seq"], dispatch_seq)
        self.assertGreater(rows[1]["seq"], dispatch_seq)

    def test_the_rng_counter_is_on_disk_before_any_child_starts(self):
        ctx = self.crashing_run("dispatches")
        on_disk = self.store.read_json(self.store.state)
        self.assertEqual(on_disk["draws"], ctx.rng.draws)
        self.assertEqual(on_disk["seed"], 31)

    def test_an_orphaned_escalation_file_is_reconciled_on_resume(self):
        """A file written before a crash that never reached state.json."""
        ctx = self.boot(fake(wake=[decision()]))
        Harness(ctx).turn()
        orphan = {"id": "e999900", "question": "left by a crash", "tier": "high",
                  "why": "the file was written, the save never happened",
                  "source": "dispatch", "payload": {}, "turn": 1, "answer": "",
                  "answered_at": 0.0, "consumed": False}
        self.store.write_json(self.store.escalations / "e999900.json", orphan)
        ctx2 = bootstrap(self.store, self.cfg, str(self.charter_path),
                         str(self.project), prompts_dir=ctx.prompts.root,
                         plugin_dir=ctx.plugin_dir,
                         runners={"claude": fake(wake=[decision()])},
                         notifier=self.notifier)
        self.assertIn("e999900", [e.get("id") for e in ctx2.state.escalations])
        self.assertTrue([r for r in ctx2.ledger.all() if r["kind"] == "resume"])


class TestLongerHorizon(HarnessCase):
    def test_a_run_of_twelve_turns_keeps_the_ledger_ordered_and_unique(self):
        runner = fake(wake=[decision()])
        cfg = Config()
        cfg.life.enabled = False
        cfg.max_idle_turns = 99
        ctx = self.boot(runner, cfg=cfg)
        Harness(ctx).run(max_turns=12)
        seqs = [r["seq"] for r in ctx.ledger.all()]
        self.assertEqual(seqs, sorted(seqs))
        self.assertEqual(len(seqs), len(set(seqs)))
        self.assertEqual(len(ctx.store.read_jsonl(ctx.store.metrics)), 12)

    def test_the_warm_cap_cools_the_oldest_and_keeps_the_refusals(self):
        ctx = self.boot(fake(wake=[decision()]))
        ctx.cfg.manifold.warm_cap = 12
        for i in range(40):
            ctx.manifold.write("sensory", f"element {i}", cycle=1)
        ctx.manifold.decay(cycle=2)
        warm = ctx.manifold.warm()
        self.assertLessEqual(len(warm), 12)
        refusals = [e for e in warm if e.texture == "refusal"]
        self.assertEqual(len(refusals), 3)


if __name__ == "__main__":
    unittest.main()


class TestAMovedRun(HarnessCase):
    """`state.json` holds an absolute project path. A renamed repository or a
    moved run directory leaves it pointing at nothing.
    """

    def a_saved_run(self):
        ctx = self.boot(fake(wake=[decision()]))
        Harness(ctx).run(max_turns=1)
        return ctx

    def test_the_project_is_found_again_beside_the_moved_run(self):
        import shutil
        import tempfile
        from pathlib import Path

        from regent.config import Config
        from regent.store import Store

        ctx = self.a_saved_run()
        self.assertTrue(Path(ctx.state.project).is_dir())

        with tempfile.TemporaryDirectory() as d:
            new = Path(d) / "regent"
            new.mkdir()
            shutil.copytree(self.store.root, new / "state")
            shutil.copytree(self.project, new / "project")
            charter = new / "charter.md"
            charter.write_text(self.charter_path.read_text())

            # The repository moved, so the stored absolute path is gone.
            store = Store(new / "state")
            saved = store.read_json(store.state)
            saved["project"] = "/Development/superorchestrator/runs/first/project"
            store.write_json(store.state, saved)

            cfg = Config()
            cfg.life.enabled = False
            cfg.cycle_in_background = False
            moved = bootstrap(store, cfg, str(charter), "",
                              prompts_dir=ctx.prompts.root,
                              plugin_dir=ctx.plugin_dir,
                              runners={"claude": fake(wake=[decision()])},
                              notifier=self.notifier)
            self.assertEqual(Path(moved.state.project).resolve(),
                             (new / "project").resolve())
            self.assertTrue(Path(moved.state.project).is_dir())

    def test_an_explicit_project_still_wins(self):
        ctx = self.a_saved_run()
        from regent.config import Config
        cfg = Config()
        cfg.life.enabled = False
        cfg.cycle_in_background = False
        again = bootstrap(self.store, cfg, str(self.charter_path),
                          str(self.project), prompts_dir=ctx.prompts.root,
                          plugin_dir=ctx.plugin_dir,
                          runners={"claude": fake(wake=[decision()])},
                          notifier=self.notifier)
        self.assertEqual(again.state.project, str(self.project))

    def test_a_path_that_still_exists_is_left_alone(self):
        from regent.loop import _resolve_project
        ctx = self.a_saved_run()
        self.assertEqual(_resolve_project(self.store, ctx.state.project),
                         ctx.state.project)

    def test_a_path_that_cannot_be_found_is_returned_unchanged(self):
        from regent.loop import _resolve_project
        self.a_saved_run()
        self.assertEqual(_resolve_project(self.store, "/nowhere/at/all"),
                         "/nowhere/at/all")


class TestWallTimeIsTimeSpentRunning(HarnessCase):
    """A run stopped overnight and resumed has spent no wall time in between."""

    def test_a_resumed_run_does_not_inherit_the_hours_it_was_not_running(self):
        import time

        from regent.config import Config
        ctx = self.boot(fake(wake=[decision()]))
        ctx.charter.budget.wall_time_s = 3600
        Harness(ctx).run(max_turns=1)
        # As if the run had been left alone for a day.
        saved = self.store.read_json(self.store.state)
        saved["started"] = time.time() - 90_000
        self.store.write_json(self.store.state, saved)

        cfg = Config()
        cfg.life.enabled = False
        cfg.cycle_in_background = False
        again = bootstrap(self.store, cfg, str(self.charter_path),
                          str(self.project), prompts_dir=ctx.prompts.root,
                          plugin_dir=ctx.plugin_dir,
                          runners={"claude": fake(wake=[decision()])},
                          notifier=self.notifier)
        again.charter.budget.wall_time_s = 3600
        reason = Harness(again).run(max_turns=2)
        self.assertNotIn("wall time", reason)
        self.assertGreater(again.state.turn, 1)

    def test_the_budget_still_stops_a_run_that_really_has_spent_it(self):
        ctx = self.boot(fake(wake=[decision()]))
        ctx.charter.budget.wall_time_s = 60
        ctx.state.elapsed_s = 120
        reason = Harness(ctx).run(max_turns=5)
        self.assertIn("wall time", reason)

    def test_time_spent_running_accumulates_across_starts(self):
        ctx = self.boot(fake(wake=[decision()]))
        Harness(ctx).run(max_turns=1)
        first = ctx.state.elapsed_s
        self.assertGreaterEqual(first, 0.0)
        Harness(ctx).run(max_turns=2)
        self.assertGreaterEqual(ctx.state.elapsed_s, first)
