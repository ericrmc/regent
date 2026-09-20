"""Each of these pins a defect an independent review found and reproduced."""

from __future__ import annotations

import unittest

from helpers import HarnessCase, a_dispatch, a_wake_requirement, decision, fake

from regent.charter import parse_charter
from regent.config import Config
from regent.digest import build_digest
from regent.loop import Harness
from regent.runner import ClaudeCliRunner


class TestIsolationFlags(HarnessCase):
    """`--tools ""` alone leaves the user's MCP servers attached, and one of
    those can edit files. The same is true of `--tools "Read,Grep,Glob"`.
    """

    def argv_for(self, role: str) -> list[str]:
        ctx = self.boot(fake(wake=[decision()]))
        if role == "spot_check":
            from regent import spotcheck as sc
            sc.run_spot_check(ctx, "what is there?")
            req = self.runner.calls_for("spot_check")[0]
        elif role == "orchestrator":
            Harness(ctx).turn()
            ctx2 = self.boot(fake(wake=[decision(dispatches=[a_dispatch()])]))
            Harness(ctx2).turn()
            req = self.runner.calls_for("orchestrator")[0]
        else:
            Harness(ctx).turn()
            req = self.runner.calls_for(role)[0]
        return ClaudeCliRunner().argv(req)

    def test_the_spot_check_argv_carries_the_isolation_flags(self):
        argv = self.argv_for("spot_check")
        self.assertIn("--strict-mcp-config", argv)
        self.assertIn("--setting-sources", argv)
        self.assertEqual(argv[argv.index("--setting-sources") + 1], "")
        self.assertIn("--disable-slash-commands", argv)
        self.assertIn("--no-session-persistence", argv)
        self.assertEqual(argv[argv.index("--tools") + 1], "Read,Grep,Glob")
        for banned in ("Write", "Edit", "Bash"):
            self.assertNotIn(banned, argv[argv.index("--tools") + 1])

    def test_the_wake_argv_carries_them_too(self):
        argv = self.argv_for("wake")
        self.assertIn("--strict-mcp-config", argv)
        self.assertIn("--no-session-persistence", argv)
        self.assertEqual(argv[argv.index("--tools") + 1], "")

    def test_the_orchestrator_opts_out_of_one_thing_only(self):
        """It resumes its session. It still gets every isolation flag."""
        argv = self.argv_for("orchestrator")
        self.assertIn("--strict-mcp-config", argv)
        self.assertIn("--setting-sources", argv)
        self.assertEqual(argv[argv.index("--setting-sources") + 1], "")
        self.assertNotIn("--no-session-persistence", argv)

    def test_the_project_settings_opt_in_is_off_and_has_to_be_named(self):
        cfg = Config()
        self.assertFalse(cfg.dispatching.allow_project_settings)

    def test_every_role_carries_strict_mcp_config_and_empty_setting_sources(self):
        """A user-scoped MCP server started with --project-from-cwd would
        otherwise attach to any child whose cwd sits inside a repository.
        """
        runner = fake(
            wake=[decision(dispatches=[a_dispatch()],
                           inspect=[{"question": "q", "dispatch_id": ""}]),
                  decision()],
            drift=[{"links": [{"kind": "seed", "text": "a link",
                               "anchors": ["m00001"], "ingredients": [],
                               "mechanism": "m"}]}])
        ctx = self.boot(runner)
        h = Harness(ctx)
        h.turn()
        h.turn()
        ctx.spoon.run(trigger="test")
        seen = set()
        for req in self.runner.calls:
            argv = ClaudeCliRunner().argv(req)
            seen.add(req.role)
            self.assertIn("--strict-mcp-config", argv, req.role)
            self.assertIn("--setting-sources", argv, req.role)
            self.assertEqual(argv[argv.index("--setting-sources") + 1], "", req.role)
            self.assertNotIn("--mcp-config", argv, req.role)
        for role in ("wake", "orchestrator", "spot_check", "saturate", "drift",
                     "sift", "consolidate"):
            self.assertIn(role, seen, f"{role} was never exercised")

    def test_no_call_in_the_tree_skips_permissions(self):
        for role in ("wake", "spot_check"):
            argv = self.argv_for(role)
            self.assertNotIn("--dangerously-skip-permissions", argv)
            self.assertNotIn("bypassPermissions", " ".join(argv))


class TestCwdOnEveryChild(HarnessCase):
    def test_every_harness_child_gets_a_working_directory(self):
        ctx = self.boot(fake(wake=[decision(dispatches=[a_dispatch()],
                                            inspect=[{"question": "q",
                                                      "dispatch_id": ""}]),
                                   decision()]))
        h = Harness(ctx)
        h.turn()
        h.turn()
        self.assertTrue(self.runner.calls)
        for req in self.runner.calls:
            self.assertIsNotNone(req.cwd, req.role)
            self.assertNotEqual(req.cwd, "", req.role)

    def test_a_toolless_child_runs_in_an_empty_harness_directory(self):
        ctx = self.boot(fake(wake=[decision()]))
        Harness(ctx).turn()
        for req in self.runner.calls:
            if req.toolless:
                self.assertEqual(req.cwd, str(self.store.sandbox))
        self.assertTrue(self.store.sandbox.is_dir())
        self.assertEqual(list(self.store.sandbox.iterdir()), [])

    def test_a_child_with_tools_runs_in_the_project(self):
        ctx = self.boot(fake(wake=[decision(dispatches=[a_dispatch()]), decision()]))
        Harness(ctx).turn()
        for req in self.runner.calls_for("orchestrator"):
            self.assertEqual(req.cwd, str(self.project))


class TestRelaxReplaces(HarnessCase):
    def with_dispatch(self):
        ctx = self.boot(fake(wake=[decision()]))
        from regent.dispatch import Dispatch
        ctx.state.put_dispatch(Dispatch(
            id="d1", title="t", intent="i",
            acceptance=["It responds in under 200ms.",
                        "It exits zero when nothing is broken."]))
        return ctx, Harness(ctx)

    def test_a_relax_removes_the_criterion_it_names(self):
        ctx, h = self.with_dispatch()
        h.apply_amendments([{"dispatch_id": "d1", "direction": "relax",
                             "trigger": "the timing cost more than it was worth",
                             "criterion": "It responds in under 800ms.",
                             "replaces": "It responds in under 200ms."}])
        acceptance = ctx.state.dispatch("d1").acceptance
        self.assertIn("It responds in under 800ms.", acceptance)
        self.assertNotIn("It responds in under 200ms.", acceptance)
        self.assertIn("It exits zero when nothing is broken.", acceptance)

    def test_a_relax_matches_by_overlap_when_replaces_is_empty(self):
        ctx, h = self.with_dispatch()
        h.apply_amendments([{"dispatch_id": "d1", "direction": "relax",
                             "trigger": "too strict", "replaces": "",
                             "criterion": "It responds in under 800ms."}])
        acceptance = ctx.state.dispatch("d1").acceptance
        self.assertNotIn("It responds in under 200ms.", acceptance)
        self.assertEqual(len(acceptance), 2)

    def test_the_removed_text_is_kept_in_the_amendment_row(self):
        ctx, h = self.with_dispatch()
        h.apply_amendments([{"dispatch_id": "d1", "direction": "relax",
                             "trigger": "too strict",
                             "criterion": "It responds in under 800ms.",
                             "replaces": "It responds in under 200ms."}])
        row = ctx.state.dispatch("d1").amendments[-1]
        self.assertEqual(row["removed"], ["It responds in under 200ms."])

    def test_a_raise_still_adds_without_removing(self):
        ctx, h = self.with_dispatch()
        h.apply_amendments([{"dispatch_id": "d1", "direction": "raise",
                             "trigger": "there was headroom",
                             "criterion": "It checks heading anchors.",
                             "replaces": ""}])
        self.assertEqual(len(ctx.state.dispatch("d1").acceptance), 3)

    def test_the_orchestrator_brief_never_carries_both_halves_of_a_relax(self):
        ctx, h = self.with_dispatch()
        h.apply_amendments([{"dispatch_id": "d1", "direction": "relax",
                             "trigger": "too strict",
                             "criterion": "It responds in under 800ms.",
                             "replaces": "It responds in under 200ms."}])
        brief = ctx.state.dispatch("d1").brief()
        self.assertIn("800ms", brief)
        self.assertNotIn("200ms.\n", brief.split("## Amendments")[0])


class TestGuardrailSeesMutation(HarnessCase):
    def test_an_in_place_mutation_of_the_refusals_is_caught(self):
        ctx = self.boot(fake(wake=[decision()]))
        h = Harness(ctx)
        before = h.guard_snapshot()
        ctx.charter.refusals.append("SMUGGLED IN")
        broken = __import__("regent.interlude", fromlist=["guardrail_check"]) \
            .guardrail_check(before, h.guard_snapshot(before["ledger_len"]))
        self.assertIn("refusals", broken)

    def test_an_ordinary_interlude_trips_nothing(self):
        ctx = self.boot(fake(wake=[decision()]))
        ctx.cfg.interlude.weights = {k: (1.0 if k == "stance_drift" else 0.0)
                                     for k in ctx.cfg.interlude.weights}
        Harness(ctx).interlude()
        self.assertFalse(ctx.state.stopped)


class TestDigestPeriod(HarnessCase):
    def test_a_digest_carries_its_period_and_not_the_whole_run(self):
        runner = fake(wake=[
            decision(amendments=[{"dispatch_id": "d1", "direction": "raise",
                                  "trigger": "an early trigger on turn one",
                                  "criterion": "c1", "replaces": ""}]),
            decision(), decision(),
            decision(amendments=[{"dispatch_id": "d1", "direction": "raise",
                                  "trigger": "a later trigger on turn four",
                                  "criterion": "c2", "replaces": ""}]),
            decision()])
        ctx = self.boot(runner)
        from regent.dispatch import Dispatch
        ctx.state.put_dispatch(Dispatch(id="d1", title="t", intent="i"))
        h = Harness(ctx)
        for _ in range(4):
            h.turn()
        late = build_digest(ctx, 3)
        self.assertIn("a later trigger on turn four", late)
        self.assertNotIn("an early trigger on turn one", late)
        whole = build_digest(ctx, 0)
        self.assertIn("an early trigger on turn one", whole)

    def test_every_ledger_row_carries_its_turn(self):
        ctx = self.boot(fake(wake=[decision()]))
        h = Harness(ctx)
        h.turn()
        h.turn()
        rows = [r for r in ctx.ledger.all() if r["seq"] > 1]
        self.assertTrue(rows)
        for r in rows:
            self.assertIn("turn", r)
        self.assertEqual({r["turn"] for r in rows}, {1, 2})

    def test_the_read_mode_tally_is_scoped_to_the_period(self):
        runner = fake(wake=[decision(dispatches=[a_dispatch()]), decision(),
                            decision(), decision()])
        ctx = self.boot(runner)
        h = Harness(ctx)
        h.turn()
        h.turn()
        h.turn()
        self.assertNotIn("How returns were read", build_digest(ctx, 2))
        self.assertIn("How returns were read", build_digest(ctx, 0))


class TestCitesResolves(unittest.TestCase):
    def setUp(self):
        import tempfile
        from pathlib import Path

        from helpers import CHARTER
        self.d = tempfile.TemporaryDirectory()
        p = Path(self.d.name) / "charter.md"
        p.write_text(CHARTER)
        self.ch = parse_charter(p)

    def tearDown(self):
        self.d.cleanup()

    def test_a_heading_is_not_a_charter_line(self):
        self.assertFalse(self.ch.cites("the Intent of this run"))
        self.assertFalse(self.ch.cites("constraints and more words"))
        self.assertFalse(self.ch.cites("Budget"))

    def test_a_real_line_still_resolves(self):
        self.assertTrue(self.ch.cites("Never make a network request."))
        self.assertTrue(self.ch.cites("It is for one person maintaining a notes folder."))

    def test_nonsense_never_resolves(self):
        self.assertFalse(self.ch.cites("total nonsense xyzzy"))
        self.assertFalse(self.ch.cites(""))

    def test_an_objective_citing_a_heading_is_rejected_as_drift(self):
        from helpers import decision as a_decision

        from regent import decision as dec
        d = a_decision(objectives=[{
            "action": "add", "id": "obj-9",
            "text": "I will build a web dashboard.", "weight": 0.9,
            "charter_line": "the Intent of this run", "trigger": "a hunch"}])
        v = dec.validate_decision(d, self.ch, Config())
        self.assertEqual(v.decision["objectives"], [])
        self.assertIn("drift", v.rejections[0]["reason"])


class TestSignalsAreSpent(HarnessCase):
    def test_frustration_advances_the_rung_without_a_fresh_reject(self):
        runner = fake(wake=[decision(dispatches=[a_dispatch()]), decision(),
                            decision()])
        ctx = self.boot(runner)
        h = Harness(ctx)
        h.turn()
        ctx.state.signals.frustration = 1.0
        h.turn()
        self.assertGreaterEqual(ctx.ladder.rung("d0001"), 1)
        rows = [r for r in ctx.ledger.all()
                if r["kind"] == "signal" and "moved it to rung" in str(r.get("summary", ""))]
        self.assertTrue(rows)
        self.assertEqual(rows[0]["dispatch_id"], "d0001")

    def test_frustration_is_spent_when_it_moves_the_rung(self):
        runner = fake(wake=[decision(dispatches=[a_dispatch()]), decision(),
                            decision()])
        ctx = self.boot(runner)
        h = Harness(ctx)
        h.turn()
        ctx.state.signals.frustration = 1.0
        h.turn()
        self.assertLess(ctx.state.signals.frustration, 1.0)

    def test_satisfaction_releases_the_closed_branch(self):
        runner = fake(wake=[decision(dispatches=[a_dispatch()]),
                            decision(judgements=[{"return_id": "r00001",
                                                  "outcome": "accept",
                                                  "reason": "met"}]),
                            decision()])
        ctx = self.boot(runner)
        h = Harness(ctx)
        h.turn()
        ctx.state.debt["obj-1"] = 2
        ctx.state.signals.satisfaction = 1.0
        h.turn()
        self.assertEqual(ctx.state.debt_for("obj-1"), 0)
        rows = [r for r in ctx.ledger.all()
                if r["kind"] == "signal" and "satisfaction" in str(r.get("summary", ""))]
        self.assertTrue(rows)

    def test_the_plan_carries_each_dispatchs_rung_so_the_agent_can_name_it(self):
        runner = fake(wake=[decision(dispatches=[a_dispatch()]), decision()])
        ctx = self.boot(runner)
        h = Harness(ctx)
        h.turn()
        ctx.ladder.record_failure("d0001")
        ctx.ladder.record_failure("d0001")
        plan = h.render_plan()
        self.assertIn('"rung": 2', plan)
        self.assertIn('"failures": 2', plan)


class TestEscalationDeduplication(HarnessCase):
    def test_the_same_blocked_dispatch_does_not_escalate_twice(self):
        d = a_dispatch(tier="high")
        runner = fake(wake=[decision(dispatches=[d]), decision(dispatches=[d]),
                            decision()])
        ctx = self.boot(runner)
        h = Harness(ctx)
        h.turn()
        self.assertEqual(len(ctx.state.open_escalations()), 1)
        h.turn()
        self.assertEqual(len(ctx.state.open_escalations()), 1)
        self.assertEqual(len(self.notifier.sent), 1)
        skipped = [r for r in ctx.ledger.all()
                   if r["kind"] == "escalation" and "already open" in str(r.get("summary"))]
        self.assertTrue(skipped)


class TestLedgerCost(HarnessCase):
    def test_the_sequence_is_counted_once_and_then_held(self):
        ctx = self.boot(fake(wake=[decision()]))
        reads = {"n": 0}
        original = ctx.ledger._count

        def counted():
            reads["n"] += 1
            return original()
        ctx.ledger._count = counted
        for i in range(30):
            ctx.ledger.write("signal", summary=f"row {i}")
        self.assertEqual(reads["n"], 1)
        seqs = [r["seq"] for r in ctx.ledger.all()]
        self.assertEqual(seqs, sorted(seqs))
        self.assertEqual(len(set(seqs)), len(seqs))


class TestWakeRequirementGate(HarnessCase):
    def test_a_wake_requirement_passes_the_same_four_conditions(self):
        ctx = self.boot(fake(wake=[decision(requirements=[
            a_wake_requirement(text="fine one"),
            a_wake_requirement(text="no rework", rework=""),
        ])]))
        Harness(ctx).turn()
        self.assertEqual(len(ctx.requirements.rows), 1)
        self.assertEqual(ctx.requirements.rows[0]["text"], "fine one")


if __name__ == "__main__":
    unittest.main()


class TestSourceNeverRidesInWithFindings(HarnessCase):
    def test_a_code_fence_is_stripped_from_the_findings(self):
        from regent import spotcheck as sc
        runner = fake(wake=[decision()])
        runner.scripts["spot_check"] = [{
            "findings": "It walks the folder.\n```python\ndef walk(root):\n"
                        "    return list(root.glob('*.md'))\n```\nAnchors are unchecked.",
            "verdicts": [], "gap": False, "openings": []}]
        ctx = self.boot(runner)
        f = sc.run_spot_check(ctx, "q")
        self.assertIn("It walks the folder.", f.findings)
        self.assertIn("Anchors are unchecked.", f.findings)
        self.assertNotIn("def walk", f.findings)
        self.assertNotIn("```", f.findings)
        self.assertNotIn("def walk", " ".join(e.text for e in ctx.manifold.warm()))

    def test_a_long_line_with_no_sentence_punctuation_is_dropped(self):
        from regent.spotcheck import strip_source
        line = "x = " + " + ".join(f"value_{i}" for i in range(30))
        kept, dropped = strip_source(f"It works.\n{line}\nThat is all.")
        self.assertIn("It works.", kept)
        self.assertNotIn("value_29", kept)
        self.assertEqual(len(dropped), 1)

    def test_ordinary_prose_survives_untouched(self):
        from regent.spotcheck import strip_source
        text = ("The checker walks the folder and resolves each link against the "
                "file that holds it. It does not handle heading anchors at all, "
                "which the return did not mention.")
        kept, dropped = strip_source(text)
        self.assertEqual(kept, text)
        self.assertEqual(dropped, [])


class TestStanceReplaysAndStaysInBand(HarnessCase):
    def test_stance_moves_on_the_simulated_day_not_the_wall_clock(self):
        from regent import stance as stn
        a = stn.StanceState(value=0.4)
        stn.tilt(a, self.cfg, day=0, recent=10)
        self.assertEqual(a.baseline, 0.0)
        stn.tilt(a, self.cfg, day=1, recent=10)
        self.assertNotEqual(a.baseline, 0.0)

    def test_a_field_of_friction_does_not_pin_the_stance_to_a_bound(self):
        from regent import stance as stn
        s = stn.StanceState(value=0.0)
        for _ in range(6):
            stn.tilt(s, self.cfg, friction=30, recent=30)
        self.assertLess(s.value, 0.0)
        self.assertGreater(s.value, -1.0)

    def test_the_same_inputs_give_the_same_stance_every_time(self):
        from regent import stance as stn

        def walk():
            s = stn.StanceState(value=0.0)
            for day in range(4):
                stn.tilt(s, self.cfg, friction=5, unfinished=2, recent=20, day=day)
            return round(s.value, 9), round(s.baseline, 9)
        self.assertEqual(walk(), walk())


class TestCatchCounters(unittest.TestCase):
    def setUp(self):
        self.cfg = Config()
        self.ids = {f"m{i:05d}" for i in range(1, 50)}

    def link(self, anchors, text="a link"):
        return {"kind": "seed", "text": text, "anchors": anchors,
                "ingredients": [], "mechanism": "m"}

    def test_an_unanchored_link_between_repeats_resets_the_motif_counter(self):
        from regent.spoon import STOP_EXHAUSTED, catch
        pair = ["m00001", "m00002"]
        links = [self.link(pair), self.link(pair), self.link([]),
                 self.link(pair), self.link([]), self.link(pair)]
        kept, stop = catch(links, self.cfg, manifold_ids=self.ids)
        self.assertEqual(stop["rule"], STOP_EXHAUSTED)
        self.assertEqual(len(kept), 1)

    def test_a_pass_that_kept_links_then_ran_out_of_anchors_still_died_there(self):
        from regent.spoon import STOP_GROUNDEDNESS, catch
        links = [self.link([f"m{i:05d}"]) for i in range(1, 6)]
        links += [self.link([]), self.link([]), self.link([])]
        kept, stop = catch(links, self.cfg, manifold_ids=self.ids)
        self.assertEqual(stop["rule"], STOP_GROUNDEDNESS)
        self.assertEqual(len(kept), 5)


class TestMatcherFalsePositives(unittest.TestCase):
    """The first real run escalated a legitimate low-tier dispatch and rejected
    another, both because the dispatch promised to comply with the rule it was
    matched against. The texts below are verbatim from that run.
    """

    REAL_INTENT = (
        "Write the command line tool as one Python 3.11 standard-library file "
        "that anyone can read top to bottom, with a test file beside it. Given "
        "a directory of markdown files it reports each broken internal link "
        "(to another file, to a file in another folder, or to a heading inside "
        "a file) as file and line. It exits non-zero if it finds any and zero "
        "if it finds none. It only reads files and only writes to stdout."
    )
    REAL_ACCEPTANCE = (
        "It is one source file plus one test file and imports only the "
        "standard library. It makes no network calls and never writes to, "
        "moves, or deletes any file in the folder it checks."
    )

    def real_text(self) -> str:
        return f"{self.REAL_INTENT} {self.REAL_ACCEPTANCE}"

    def test_a_promise_to_comply_is_not_a_reserved_class(self):
        from regent.decision import reserved_match
        self.assertEqual(
            reserved_match(self.real_text(),
                           ["Reading or writing a file outside the project directory."]),
            "")

    def test_a_promise_to_comply_is_not_a_refusal(self):
        from regent.decision import refusal_match
        self.assertEqual(
            refusal_match(self.real_text(), ["Never install a package."]), "")

    def test_scattered_words_across_a_long_text_do_not_match(self):
        from regent.decision import reserved_match
        long_text = (
            "Build the test folder that proves the tool. It covers relative "
            "paths, nested directories, heading anchors and links to files "
            "that do not exist. " + ("Filler sentence about the work. " * 40)
            + "The project keeps its own directory."
        )
        self.assertEqual(
            reserved_match(long_text,
                           ["Reading or writing a file outside the project directory."]),
            "")

    def test_the_real_thing_close_together_still_matches(self):
        from regent.decision import reserved_match
        self.assertEqual(
            reserved_match("It will read and write files outside the project directory.",
                           ["Reading or writing a file outside the project directory."]),
            "Reading or writing a file outside the project directory.")

    def test_a_genuine_refusal_still_matches(self):
        from regent.decision import refusal_match
        for text in ("Install the markdown package from pip.",
                     "Make a network request to fetch each link target.",
                     "Delete and modify the user's files once the check passes."):
            self.assertTrue(
                refusal_match(text, ["Never install a package.",
                                     "Never make a network request.",
                                     "Never delete or modify the user's files."]),
                text)

    def test_the_real_dispatch_now_passes_the_charter_check(self):
        import tempfile
        from pathlib import Path

        from helpers import CHARTER, a_dispatch, decision

        from regent import decision as dec
        from regent.charter import parse_charter
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "charter.md"
            p.write_text(CHARTER)
            ch = parse_charter(p)
        item = a_dispatch(intent=self.REAL_INTENT,
                          acceptance=[self.REAL_ACCEPTANCE],
                          tier="low", classes=["code", "tests"])
        v = dec.validate_decision(decision(dispatches=[item]), ch, Config())
        self.assertEqual(len(v.decision["dispatches"]), 1)
        self.assertEqual(v.escalations, [])
        self.assertTrue(v.clean)


class TestStemmerIsSymmetric(unittest.TestCase):
    """A class written one way has to match a dispatch written the other."""

    def test_both_forms_reach_one_stem(self):
        from regent.decision import _stem
        for a, b in (("writing", "write"), ("writes", "write"),
                     ("publishing", "publish"), ("reading", "read"),
                     ("installs", "install"), ("packages", "package"),
                     ("deletes", "delete"), ("modifying", "modify")):
            self.assertEqual(_stem(a), _stem(b), f"{a} vs {b}")

    def test_stemming_is_idempotent(self):
        from regent.decision import _stem
        for word in ("writing", "files", "directories", "publishing",
                     "packages", "spending", "contacting"):
            once = _stem(word)
            self.assertEqual(_stem(once), once, word)
