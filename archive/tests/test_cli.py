"""The six commands. Each one is exercised against a real run directory."""

from __future__ import annotations

import contextlib
import io
import json
import unittest

from helpers import HarnessCase, a_dispatch, decision, fake

from regent.cli import main
from regent.loop import Harness


def run_cli(*argv) -> tuple[int, str]:
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
        code = main(list(argv))
    return code, out.getvalue()


class TestCli(HarnessCase):
    def a_run(self, runner=None):
        ctx = self.boot(runner or fake(wake=[
            decision(dispatches=[a_dispatch()]),
            decision(judgements=[{"return_id": "r00001", "outcome": "accept",
                                  "reason": "met"}]),
            decision(stop={"requested": True, "reason": "done"})]))
        Harness(ctx).run(max_turns=3)
        return ctx

    def test_every_command_is_registered(self):
        from regent.cli import COMMANDS
        self.assertEqual(sorted(COMMANDS),
                         ["answer", "digest", "export", "influence", "owner",
                          "run", "status", "stop", "watch"])

    def test_status_reports_where_the_run_stands(self):
        self.a_run()
        code, out = run_cli("--state", str(self.store.root), "status")
        self.assertEqual(code, 0)
        self.assertIn("turn 3", out)
        self.assertIn("objectives", out)
        self.assertIn("obj-1", out)
        self.assertIn("budget:", out)
        self.assertIn("stance:", out)
        self.assertIn("signals:", out)
        self.assertIn("escalations waiting: 0", out)
        self.assertIn("stop condition", out)

    def test_status_shows_the_read_modes_behind_the_decisions(self):
        self.a_run()
        code, out = run_cli("--state", str(self.store.root), "status")
        self.assertIn("reads:", out)

    def test_status_on_no_run_says_so_and_fails(self):
        code, out = run_cli("--state", str(self.root / "nothing"), "status")
        self.assertEqual(code, 1)
        self.assertIn("no run", out)

    def test_watch_prints_one_line_per_ledger_record(self):
        self.a_run()
        code, out = run_cli("--state", str(self.store.root), "watch", "--once")
        self.assertEqual(code, 0)
        lines = [line for line in out.splitlines() if line.strip()]
        self.assertGreater(len(lines), 5)
        self.assertTrue(any("dispatch" in line for line in lines))
        self.assertTrue(any("read_mode" in line for line in lines))

    def test_watch_can_start_from_a_sequence_number(self):
        self.a_run()
        _, all_out = run_cli("--state", str(self.store.root), "watch", "--once")
        _, some = run_cli("--state", str(self.store.root), "watch", "--once", "--from", "5")
        self.assertLess(len(some.splitlines()), len(all_out.splitlines()))

    def test_digest_prints_the_page(self):
        self.a_run()
        code, out = run_cli("--state", str(self.store.root), "digest", "--since", "0")
        self.assertEqual(code, 0)
        self.assertIn("# Digest", out)
        self.assertIn("Objectives", out)
        self.assertIn("What is next", out)

    def test_digest_write_saves_it_under_digests(self):
        self.a_run()
        code, out = run_cli("--state", str(self.store.root), "digest", "--since", "0",
                            "--write")
        self.assertEqual(code, 0)
        self.assertTrue(list(self.store.digests.glob("digest-*.md")))

    def test_answer_writes_an_inbox_note_and_never_touches_state(self):
        """A live run holds state in memory. A second process writing
        state.json loses the answer at the next save.
        """
        ctx = self.boot(fake(wake=[decision(escalations=[
            {"question": "May I spend money?", "tier": "high", "why": "reserved"}])]))
        Harness(ctx).turn()
        eid = ctx.state.open_escalations()[0].id
        before = self.store.state.read_bytes()
        code, out = run_cli("--state", str(self.store.root), "answer", eid, "No.")
        self.assertEqual(code, 0)
        self.assertIn("next turn", out)
        self.assertEqual(self.store.state.read_bytes(), before)
        notes = list(self.store.inbox.glob("*.json"))
        self.assertEqual(len(notes), 1)
        self.assertEqual(json.loads(notes[0].read_text())["text"], "No.")

    def test_the_running_loop_picks_the_answer_up_on_its_next_turn(self):
        runner = fake(wake=[decision(escalations=[
            {"question": "May I spend money?", "tier": "high", "why": "reserved"}]),
            decision(), decision()])
        ctx = self.boot(runner)
        h = Harness(ctx)
        h.turn()
        self.assertEqual(len(ctx.state.open_escalations()), 1)
        eid = ctx.state.open_escalations()[0].id
        run_cli("--state", str(self.store.root), "answer", eid, "No, skip it.")
        h.turn()
        self.assertEqual(ctx.state.open_escalations(), [])
        self.assertEqual(ctx.state.escalation(eid).answer, "No, skip it.")
        # And it survives the save that follows.
        ctx.save()
        from regent.state import RunState
        on_disk = RunState.from_dict(self.store.read_json(self.store.state))
        self.assertEqual(on_disk.escalation(eid).answer, "No, skip it.")

    def test_the_answer_reaches_the_next_wake_across_the_process_boundary(self):
        runner = fake(wake=[decision(escalations=[
            {"question": "May I spend money?", "tier": "high", "why": "reserved"}]),
            decision(), decision()])
        ctx = self.boot(runner)
        h = Harness(ctx)
        h.turn()
        run_cli("--state", str(self.store.root), "answer",
                ctx.state.open_escalations()[0].id, "No, keep it inside the folder.")
        h.turn()
        self.assertIn("keep it inside the folder", runner.calls_for("wake")[1].prompt)

    def test_a_note_is_consumed_once_and_not_replayed_every_turn(self):
        runner = fake(wake=[decision(escalations=[
            {"question": "q", "tier": "high", "why": "reserved"}]),
            decision(), decision(), decision()])
        ctx = self.boot(runner)
        h = Harness(ctx)
        h.turn()
        run_cli("--state", str(self.store.root), "answer",
                ctx.state.open_escalations()[0].id, "yes")
        h.turn()
        h.turn()
        answered = [r for r in ctx.ledger.all()
                    if r["kind"] == "escalation_answered" and r.get("source") == "inbox"]
        self.assertEqual(len(answered), 1)
        self.assertEqual(list(self.store.inbox.glob("*.json")), [])
        self.assertEqual(len(list((self.store.inbox / "done").glob("*.json"))), 1)

    def test_answer_on_an_unknown_id_fails_and_lists_what_is_open(self):
        ctx = self.boot(fake(wake=[decision(escalations=[
            {"question": "May I?", "tier": "high", "why": "reserved"}])]))
        Harness(ctx).turn()
        eid = ctx.state.open_escalations()[0].id
        code, out = run_cli("--state", str(self.store.root), "answer", "e9999", "No.")
        self.assertEqual(code, 1)
        self.assertIn("no escalation with id", out)
        self.assertIn(eid, out)

    def test_answering_twice_is_refused(self):
        ctx = self.boot(fake(wake=[decision(escalations=[
            {"question": "May I?", "tier": "high", "why": "reserved"}])]))
        Harness(ctx).turn()
        eid = ctx.state.open_escalations()[0].id
        run_cli("--state", str(self.store.root), "answer", eid, "No.")
        code, out = run_cli("--state", str(self.store.root), "answer", eid, "Yes.")
        self.assertEqual(code, 1)
        self.assertIn("already has an answer waiting", out)

    def test_stop_writes_the_flag_the_loop_watches(self):
        self.a_run()
        code, out = run_cli("--state", str(self.store.root), "stop")
        self.assertEqual(code, 0)
        self.assertTrue(self.store.stop_flag.exists())
        self.assertIn("turn in flight finishes", out)

    def test_run_dry_prints_the_argv_and_the_assembled_prompt_and_calls_nothing(self):
        code, out = run_cli("--state", str(self.store.root), "run",
                            str(self.charter_path), "--project", str(self.project),
                            "--dry-run", "--seed", "5")
        self.assertEqual(code, 0)
        self.assertIn("argv:", out)
        self.assertIn("--tools", out)
        self.assertIn("--strict-mcp-config", out)
        self.assertIn("prompt:", out)
        self.assertIn("broken internal links", out)
        self.assertNotIn("{{", out)

    def test_the_module_entry_point_matches_the_script(self):
        import subprocess
        import sys

        from helpers import ROOT
        r = subprocess.run([sys.executable, "-m", "regent", "--help"],
                           capture_output=True, text=True, cwd=str(ROOT))
        self.assertEqual(r.returncode, 0)
        for cmd in ("run", "status", "watch", "digest", "answer", "stop"):
            self.assertIn(cmd, r.stdout)

    def test_the_console_script_is_regent(self):
        import subprocess
        import sys

        from helpers import ROOT
        r = subprocess.run([sys.executable, "-m", "regent", "--help"],
                           capture_output=True, text=True, cwd=str(ROOT))
        self.assertEqual(r.returncode, 0)
        self.assertIn("regent", r.stdout)


if __name__ == "__main__":
    unittest.main()


class TestAnsweringUnblocksAHaltedRun(HarnessCase):
    """A run that halted on an escalation has to be startable again by
    answering it. The first real run halted and could not be restarted,
    because the inbox was drained inside the turn and the blocked check ran
    before the turn.
    """

    def halted_on_an_escalation(self):
        ctx = self.boot(fake(wake=[decision(escalations=[
            {"question": "May I spend money?", "tier": "high",
             "why": "reserved"}]), decision(), decision()]))
        reason = Harness(ctx).run(max_turns=5)
        self.assertIn("escalation", reason)
        self.assertEqual(len(ctx.state.open_escalations()), 1)
        return ctx

    def test_an_answer_lets_the_run_start_again(self):
        ctx = self.halted_on_an_escalation()
        eid = ctx.state.open_escalations()[0].id
        turns_before = ctx.state.turn
        code, _ = run_cli("--state", str(self.store.root), "answer", eid, "Yes.")
        self.assertEqual(code, 0)

        from regent.config import Config
        from regent.loop import bootstrap
        ctx2 = bootstrap(self.store, Config(), str(self.charter_path),
                         str(self.project), prompts_dir=ctx.prompts.root,
                         plugin_dir=ctx.plugin_dir,
                         runners={"claude": fake(wake=[decision(), decision()])},
                         notifier=self.notifier)
        ctx2.cfg.life.enabled = False
        Harness(ctx2).run(max_turns=turns_before + 2)
        self.assertGreater(ctx2.state.turn, turns_before)
        self.assertEqual(ctx2.state.open_escalations(), [])
        self.assertEqual(ctx2.state.escalation(eid).answer, "Yes.")

    def test_the_answer_is_drained_before_the_blocked_check(self):
        ctx = self.halted_on_an_escalation()
        eid = ctx.state.open_escalations()[0].id
        run_cli("--state", str(self.store.root), "answer", eid, "Yes.")
        h = Harness(ctx)
        # Still open in memory until the inbox is drained.
        self.assertTrue(h.blocked_on_escalation())
        h.drain_inbox()
        self.assertFalse(h.blocked_on_escalation())

    def test_an_unanswered_run_still_halts(self):
        ctx = self.halted_on_an_escalation()
        reason = Harness(ctx).run(max_turns=5)
        self.assertIn("escalation", reason)
