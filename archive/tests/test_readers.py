"""Step 14. Meaning is read by a model, never matched by words.

The fixtures are the verbatim texts from the first real run, which a keyword
check escalated for promising to obey a refusal in the refusal's own words.
"""

from __future__ import annotations

import unittest

from helpers import HarnessCase, a_dispatch, a_wake_requirement, decision, fake

from regent import reader as rdr
from regent.config import Config
from regent.loop import Harness
from regent.runner import ModelResponse

# Verbatim from the run that halted on turn 1.
REAL_INTENT = (
    "Write the command line tool as one Python 3.11 standard-library file "
    "that anyone can read top to bottom, with a test file beside it. It only "
    "reads files and only writes to stdout."
)
REAL_ACCEPTANCE = (
    "It is one source file plus one test file and imports only the standard "
    "library. It makes no network calls and never writes to, moves, or "
    "deletes any file in the folder it checks."
)


def reading(findings, unsure=False):
    return {"findings": findings, "unsure": unsure}


def a_finding(rule="Never install a package.", direction="intends",
              quote="", why="x", tier="low"):
    return {"rule": rule, "direction": direction, "quote": quote, "why": why,
            "tier": tier}


class TestTheQuoteMustBeReal(unittest.TestCase):
    """A reader that invents grounds is the failure this exists to catch."""

    TEXT = "It makes no network calls and never writes to any file."

    def test_a_verbatim_quote_passes(self):
        self.assertTrue(rdr.quote_is_real("makes no network calls", self.TEXT))

    def test_whitespace_and_case_do_not_matter(self):
        self.assertTrue(rdr.quote_is_real("MAKES   NO\n network CALLS", self.TEXT))

    def test_an_invented_quote_is_refused(self):
        self.assertFalse(rdr.quote_is_real("it will call the network", self.TEXT))

    def test_a_quote_too_short_to_mean_anything_is_refused(self):
        self.assertFalse(rdr.quote_is_real("no", self.TEXT))
        self.assertFalse(rdr.quote_is_real("", self.TEXT))

    def test_verify_keeps_the_real_and_discards_the_invented(self):
        good = rdr.Finding(rule="r", direction="intends",
                           quote="makes no network calls")
        bad = rdr.Finding(rule="r", direction="intends",
                          quote="will call out to the internet")
        kept, discarded = rdr.verify([good, bad], self.TEXT)
        self.assertEqual(len(kept), 1)
        self.assertTrue(kept[0].verified)
        self.assertEqual(len(discarded), 1)
        self.assertIn("not in the text", discarded[0]["why"])

    def test_an_invented_finding_is_not_a_breach(self):
        f = rdr.Finding(rule="r", direction="intends", quote="invented")
        self.assertFalse(f.is_breach)


class TestDirection(HarnessCase):
    """A promise to comply, a description and an intent are three answers."""

    def read_with(self, findings, unsure=False):
        runner = fake(wake=[decision()])
        runner.scripts["reader"] = [reading(findings, unsure)]
        ctx = self.boot(runner)
        text = f"{REAL_INTENT} {REAL_ACCEPTANCE}"
        return ctx.reader.read("q", text, ["Never install a package."]), text

    def test_a_promise_to_comply_is_not_a_breach(self):
        r, _ = self.read_with([a_finding(
            direction="complies",
            quote="imports only the standard library")])
        self.assertEqual(len(r.findings), 1)
        self.assertEqual(r.breaches(), [])

    def test_a_description_is_not_a_breach(self):
        r, _ = self.read_with([a_finding(
            direction="describes",
            quote="imports only the standard library")])
        self.assertEqual(r.breaches(), [])

    def test_unrelated_is_not_a_breach(self):
        r, _ = self.read_with([a_finding(
            direction="unrelated", quote="with a test file beside it")])
        self.assertEqual(r.breaches(), [])

    def test_only_intent_is_a_breach(self):
        r, _ = self.read_with([a_finding(
            direction="intends", quote="imports only the standard library")])
        self.assertEqual(len(r.breaches()), 1)

    def test_the_readers_tier_is_kept(self):
        r, _ = self.read_with([a_finding(
            direction="intends", tier="high",
            quote="imports only the standard library")])
        self.assertEqual(r.top_tier(), "high")


class TestUnsureGoesUp(HarnessCase):
    def runner_with(self, first, second=None):
        runner = fake(wake=[decision()])
        scripts = [first] + ([second] if second is not None else [])
        runner.scripts["reader"] = scripts
        return runner

    def test_an_unsure_answer_is_asked_again_of_the_mid_model(self):
        runner = self.runner_with(
            reading([], unsure=True),
            reading([a_finding(direction="complies",
                               quote="imports only the standard library")]))
        ctx = self.boot(runner)
        r = ctx.reader.read("q", REAL_ACCEPTANCE, ["Never install a package."])
        self.assertTrue(r.escalated_to_mid)
        self.assertEqual(len(runner.calls_for("reader")), 2)
        self.assertEqual(runner.calls_for("reader")[0].model, ctx.cfg.models.reader)
        self.assertEqual(runner.calls_for("reader")[1].model,
                         ctx.cfg.models.reader_unsure)
        self.assertFalse(r.unsure)

    def test_still_unsure_is_treated_as_a_finding(self):
        unsure = reading([a_finding(direction="unsure",
                                    quote="imports only the standard library")],
                         unsure=True)
        ctx = self.boot(self.runner_with(unsure, unsure))
        r = ctx.reader.read("q", REAL_ACCEPTANCE, ["Never install a package."])
        self.assertTrue(r.unsure)
        self.assertEqual(len(r.breaches()), 1)

    def test_a_failed_reader_call_says_nothing_and_is_unsure(self):
        runner = fake(wake=[decision()])
        runner.scripts["reader"] = [ModelResponse(role="reader", is_error=True)]
        ctx = self.boot(runner)
        r = ctx.reader.read("q", REAL_ACCEPTANCE, ["Never install a package."])
        self.assertTrue(r.unsure)
        self.assertEqual(r.findings, [])


class TestTheRealDispatch(HarnessCase):
    """The dispatch the word matcher escalated, read instead."""

    def a_real_dispatch(self):
        return a_dispatch(intent=REAL_INTENT, acceptance=[REAL_ACCEPTANCE],
                          tier="low", classes=["code", "tests"])

    def test_a_promise_to_comply_no_longer_escalates(self):
        runner = fake(wake=[decision(dispatches=[self.a_real_dispatch()]),
                            decision()])
        runner.scripts["reader"] = [reading([
            a_finding(rule="Never install a package.", direction="complies",
                      quote="imports only the standard library"),
            a_finding(rule="Reading or writing a file outside the project directory.",
                      direction="complies",
                      quote="never writes to, moves, or deletes any file"),
        ])]
        ctx = self.boot(runner)
        Harness(ctx).turn()
        self.assertEqual(len(ctx.state.open_escalations()), 0)
        self.assertEqual(len(runner.calls_for("orchestrator")), 1)
        self.assertEqual(ctx.state.dispatch("d0001").status, "open")

    def test_a_real_intent_to_breach_still_escalates(self):
        d = a_dispatch(tier="medium",
                       intent="Publish the report outside the project directory.")
        runner = fake(wake=[decision(dispatches=[d]), decision()])
        runner.scripts["reader"] = [reading([a_finding(
            rule="Publishing outside the project directory.",
            direction="intends", tier="high",
            quote="Publish the report outside the project directory.")])]
        ctx = self.boot(runner)
        Harness(ctx).turn()
        self.assertEqual(len(ctx.state.open_escalations()), 1)
        self.assertEqual(runner.calls_for("orchestrator"), [])

    def test_a_real_refusal_is_still_rejected(self):
        d = a_dispatch(tier="medium",
                       intent="Make a network request to fetch each link target.")
        runner = fake(wake=[decision(dispatches=[d]), decision()])
        runner.scripts["reader"] = [reading([a_finding(
            rule="Never make a network request.", direction="intends",
            quote="Make a network request to fetch each link target.")])]
        ctx = self.boot(runner)
        Harness(ctx).turn()
        self.assertEqual(runner.calls_for("orchestrator"), [])
        reasons = [r["reason"] for r in ctx.ledger.all() if r["kind"] == "rejected"]
        self.assertTrue(any("refusal" in r for r in reasons))

    def test_an_invented_quote_cannot_stop_a_dispatch(self):
        """A reader that invents grounds is discarded, and the work proceeds."""
        runner = fake(wake=[decision(dispatches=[
            a_dispatch(tier="medium", intent=REAL_INTENT,
                       acceptance=[REAL_ACCEPTANCE])]), decision()])
        runner.scripts["reader"] = [reading([a_finding(
            rule="Never install a package.", direction="intends",
            quote="it will pip install the markdown library")])]
        ctx = self.boot(runner)
        Harness(ctx).turn()
        self.assertEqual(len(runner.calls_for("orchestrator")), 1)
        rows = [r for r in ctx.ledger.all() if r["kind"] == "reading"]
        self.assertEqual(rows[0]["discarded"], 1)

    def test_the_reading_is_recorded_with_its_quote(self):
        runner = fake(wake=[decision(dispatches=[self.a_real_dispatch()]),
                            decision()])
        runner.scripts["reader"] = [reading([a_finding(
            rule="Never install a package.", direction="complies",
            quote="imports only the standard library")])]
        ctx = self.boot(runner)
        Harness(ctx).turn()
        rows = [r for r in ctx.ledger.all() if r["kind"] == "reading"]
        self.assertEqual(len(rows), 1)
        f = rows[0]["findings"][0]
        self.assertEqual(f["direction"], "complies")
        self.assertIn("standard library", f["quote"])

    def test_the_declared_tier_still_governs_when_it_is_higher(self):
        d = a_dispatch(intent=REAL_INTENT, acceptance=[REAL_ACCEPTANCE],
                       tier="high")
        runner = fake(wake=[decision(dispatches=[d]), decision()])
        runner.scripts["reader"] = [reading([])]
        ctx = self.boot(runner)
        Harness(ctx).turn()
        self.assertEqual(len(ctx.state.open_escalations()), 1)

    def test_the_readers_tier_governs_when_it_is_higher(self):
        runner = fake(wake=[decision(dispatches=[
            a_dispatch(tier="medium", intent=REAL_INTENT,
                       acceptance=[REAL_ACCEPTANCE])]), decision()])
        runner.scripts["reader"] = [reading([a_finding(
            rule="Never install a package.", direction="intends", tier="high",
            quote="imports only the standard library")])]
        ctx = self.boot(runner)
        Harness(ctx).turn()
        self.assertEqual(runner.calls_for("orchestrator"), [])


class TestTheReaderCall(HarnessCase):
    def test_it_is_the_smallest_model_and_never_the_judges(self):
        cfg = Config()
        self.assertNotEqual(cfg.models.reader, cfg.models.wake)
        self.assertEqual(cfg.models.reader, "haiku")
        cheap = Config.load(profile="cheap")
        self.assertNotEqual(cheap.models.reader, cheap.models.wake)

    def test_it_is_toolless_and_isolated_in_the_sandbox(self):
        runner = fake(wake=[decision(dispatches=[a_dispatch()]), decision()])
        ctx = self.boot(runner)
        Harness(ctx).turn()
        calls = runner.calls_for("reader")
        self.assertTrue(calls)
        for c in calls:
            self.assertTrue(c.toolless)
            self.assertEqual(c.cwd, str(self.store.sandbox))
            self.assertTrue(c.isolate)

    def test_it_gets_the_rules_and_the_text_and_nothing_else(self):
        runner = fake(wake=[decision(dispatches=[a_dispatch()]), decision()])
        ctx = self.boot(runner)
        Harness(ctx).turn()
        prompt = runner.calls_for("reader")[0].prompt
        self.assertIn("## The rules", prompt)
        self.assertIn("## The text", prompt)
        for leak in ("warm manifold", "Recent ledger", "stance_line",
                     "Your objectives"):
            self.assertNotIn(leak, prompt)

    def test_the_prompt_names_the_three_answers_that_are_not_findings(self):
        import re

        from helpers import ROOT

        from regent.prompts import Prompts
        text = Prompts(ROOT / "prompts").text("reader")
        for word in ("complies", "describes", "unrelated", "intends", "unsure"):
            self.assertIn(word, text)
        flat = re.sub(r"\s+", " ", text)
        self.assertIn("character for character", flat)
        self.assertIn("throws away any finding whose quote is not there", flat)

    def test_readers_can_be_switched_off_and_the_fallback_stands(self):
        runner = fake(wake=[decision(dispatches=[a_dispatch(
            tier="medium",
            intent="Make a network request to fetch each link target.")]),
            decision()])
        cfg = Config()
        cfg.life.enabled = False
        cfg.readers.enabled = False
        ctx = self.boot(runner, cfg=cfg)
        Harness(ctx).turn()
        self.assertEqual(runner.calls_for("reader"), [])
        self.assertEqual(runner.calls_for("orchestrator"), [])


class TestTheOtherSites(HarnessCase):
    def test_a_way_is_read_rather_than_word_matched(self):
        from regent import ways as w
        runner = fake(wake=[decision()])
        runner.scripts["reader"] = [reading([a_finding(
            rule="It may not lower a floor: the spot-check rate, the audit "
                 "rate and the debt cap may rise and never fall.",
            direction="intends",
            quote="Look at fewer returns when the branch is going well")])]
        ctx = self.boot(runner)
        why = w.refuse_reason(
            {"text": "Look at fewer returns when the branch is going well",
             "pattern": "", "setting": "", "value": 0},
            ctx.cfg, reader=ctx.reader)
        self.assertTrue(why)
        self.assertIn("may not do that", why)

    def test_an_ordinary_way_is_allowed_by_the_reader(self):
        from regent import ways as w
        runner = fake(wake=[decision()])
        runner.scripts["reader"] = [reading([])]
        ctx = self.boot(runner)
        self.assertEqual(w.refuse_reason(
            {"text": "Ask for a screenshot in every return.", "pattern": "",
             "setting": "", "value": 0}, ctx.cfg, reader=ctx.reader), "")

    def test_a_floor_is_still_held_in_code_not_by_the_reader(self):
        from regent import ways as w
        runner = fake(wake=[decision()])
        runner.scripts["reader"] = [reading([])]
        ctx = self.boot(runner)
        why = w.refuse_reason({"text": "x", "pattern": "",
                               "setting": "attention.audit_rate", "value": 0.01},
                              ctx.cfg, reader=ctx.reader)
        self.assertIn("never fall", why)
        self.assertEqual(runner.calls_for("reader"), [])

    def test_churn_is_read_rather_than_compared_as_text(self):
        from regent import requirements as req
        from regent.dispatch import Dispatch
        runner = fake(wake=[decision()])
        runner.scripts["reader"] = [reading([a_finding(
            rule="A reversal must cite a trigger the first decision lacked. "
                 "The later trigger repeating an earlier one is churn.",
            direction="intends",
            quote="the artefact looked wrong again")])]
        ctx = self.boot(runner)
        ctx.state.put_dispatch(Dispatch(id="d1", title="t", intent="i"))
        h = Harness(ctx)
        h.apply_amendments([{"dispatch_id": "d1", "direction": "redirect",
                             "trigger": "the artefact looked wrong",
                             "criterion": "a", "replaces": ""}])
        h.apply_amendments([{"dispatch_id": "d1", "direction": "redirect",
                             "trigger": "the artefact looked wrong again",
                             "criterion": "b", "replaces": ""}])
        self.assertIn("already had", req.churn(ctx.ledger, ctx.cfg,
                                               reader=ctx.reader))

    def test_a_reader_may_overrule_his_false_by_quoting_a_contradiction(self):
        from regent import requirements as req
        runner = fake(wake=[decision()])
        # The quote has to be a charter line, not the requirement's own words.
        runner.scripts["reader"] = [reading([a_finding(
            rule="the charter intent", direction="intends",
            quote="It is for one person maintaining a notes folder.")])]
        ctx = self.boot(runner)
        c = a_wake_requirement(
            text="It should serve a whole team with a shared web dashboard.",
            changes_charter=False)
        c["kind"] = "requirement"
        out = req.requirement_gate([c], ctx.charter, ctx.cfg, 0.5,
                                   reader=ctx.reader)
        self.assertEqual(out.passed, [])
        self.assertEqual(out.escalated, [])
        self.assertEqual(len(out.notes), 1)

    def test_a_citation_is_read_rather_than_word_counted(self):
        runner = fake(wake=[decision()])
        runner.scripts["reader"] = [reading([])]
        ctx = self.boot(runner)
        self.assertFalse(ctx.cites_charter("the Intent of this run", "x"))

    def test_a_real_citation_is_accepted_by_the_reader(self):
        runner = fake(wake=[decision()])
        runner.scripts["reader"] = [reading([a_finding(
            rule="the charter", direction="intends",
            quote="It is for one person maintaining a notes folder.")])]
        ctx = self.boot(runner)
        self.assertTrue(ctx.cites_charter(
            "It is for one person maintaining a notes folder.",
            "I will keep the report readable at a glance."))


class TestToolDenials(HarnessCase):
    def test_a_proposal_is_made_once_and_recorded(self):
        runner = fake(wake=[decision()])
        runner.scripts["tool_denials"] = [{"denials": [
            {"tool": "WebFetch", "rule": "Never make a network request.",
             "why": "the tool is the only way to reach the network"}]}]
        runner.scripts["reader"] = [{"denials": [
            {"tool": "WebFetch", "rule": "Never make a network request.",
             "why": "the tool is the only way to reach the network"}]}]
        ctx = self.boot(runner)
        Harness(ctx).run(max_turns=1)
        rows = [r for r in ctx.ledger.all() if r["kind"] == "denials"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["tools"], ["WebFetch"])
        self.assertFalse(rows[0]["confirmed"])

    def test_nothing_is_denied_until_the_human_confirms(self):
        runner = fake(wake=[decision(dispatches=[a_dispatch()]), decision()])
        ctx = self.boot(runner)
        ctx.cfg.readers.confirmed_denials = ["WebFetch", "Bash"]
        ctx.cfg.readers.denials_confirmed = False
        Harness(ctx).turn()
        tools = runner.calls_for("orchestrator")[0].tools
        self.assertIn("Bash", tools)

    def test_a_confirmed_denial_removes_the_tool(self):
        runner = fake(wake=[decision(dispatches=[a_dispatch()]), decision()])
        ctx = self.boot(runner)
        ctx.cfg.readers.confirmed_denials = ["Bash", "WebFetch"]
        ctx.cfg.readers.denials_confirmed = True
        Harness(ctx).turn()
        tools = runner.calls_for("orchestrator")[0].tools
        self.assertNotIn("Bash", tools)
        self.assertIn("Read", tools)

    def test_a_tool_outside_the_deniable_list_is_ignored(self):
        runner = fake(wake=[decision()])
        runner.scripts["reader"] = [{"denials": [
            {"tool": "Read", "rule": "x", "why": "y"},
            {"tool": "WebFetch", "rule": "x", "why": "y"}]}]
        ctx = self.boot(runner)
        ctx.cfg.readers.deniable_tools = ["WebFetch"]
        out = rdr.propose_denials(ctx)
        self.assertEqual(out["denials"], ["WebFetch"])

    def test_the_export_carries_the_proposal_and_whether_it_was_applied(self):
        from regent.export import build_export
        runner = fake(wake=[decision()])
        runner.scripts["reader"] = [{"denials": [
            {"tool": "WebFetch", "rule": "Never make a network request.",
             "why": "z"}]}]
        ctx = self.boot(runner)
        Harness(ctx).run(max_turns=1)
        data = build_export(ctx.store.root)
        self.assertIn("tool_denials", data)
        self.assertFalse(data["tool_denials"]["applied"])
        self.assertEqual(data["tool_denials"]["proposed"]["denials"], ["WebFetch"])


class TestWhatStaysInCode(HarnessCase):
    """The attention cut, the Catch rules, every draw, schema validation, the
    floors, the surfaces an influence may enter, and the quote check.
    """

    def test_the_attention_cut_calls_no_reader(self):
        from helpers import return_block

        from regent import attention
        from regent.returns import parse_return
        runner = fake(wake=[decision()])
        ctx = self.boot(runner)
        before = len(runner.calls_for("reader"))
        attention.cut(parse_return(return_block()), attention.SKIM, ctx.cfg)
        self.assertEqual(len(runner.calls_for("reader")), before)

    def test_the_catch_rules_call_no_reader(self):
        from regent.spoon import catch
        runner = fake(wake=[decision()])
        ctx = self.boot(runner)
        before = len(runner.calls_for("reader"))
        catch([{"kind": "seed", "text": "x", "anchors": [], "ingredients": [],
                "mechanism": ""}] * 4, ctx.cfg, manifold_ids={"m00001"})
        self.assertEqual(len(runner.calls_for("reader")), before)

    def test_an_influence_surface_is_held_in_code(self):
        from regent import influence as infl
        with self.assertRaises(infl.EvidenceLine):
            infl.check_surface(infl.PLANT, "ledger")

    def test_schema_validation_is_code(self):
        from regent import schemas
        with self.assertRaises(schemas.SchemaError):
            schemas.validate({"findings": "not a list", "unsure": False},
                             schemas.READER)


if __name__ == "__main__":
    unittest.main()


class TestTheOwnersAuthority(HarnessCase):
    """The first run escalated every requirement he invented and built none.
    Building his requirements is the point, so the rule runs the other way.
    """

    def a_growth_requirement(self, **over):
        r = a_wake_requirement(
            text="It should also report a link that points at a heading that "
                 "was renamed, not only one whose file is gone.",
            serves_intent="A notes folder renames headings constantly and that "
                          "is the case the person actually hits.",
            rework="The anchor resolver is redone. One accepted dispatch reopens.",
            appetite_share=0.1)
        r.update(over)
        return r

    def test_a_requirement_extending_the_charter_becomes_work_with_no_escalation(self):
        """Even when the reader sees that it changes what is being built.

        Extending a line is not contradicting it, so the reader's answer to the
        contradiction question is not a breach and the work goes ahead.
        """
        from regent import requirements as req
        runner = fake(wake=[decision()])
        runner.scripts["reader"] = [reading([a_finding(
            rule="the charter intent", direction="describes", tier="high",
            quote="It should also report a link that points at a heading that "
                  "was renamed")])]
        ctx = self.boot(runner)
        c = self.a_growth_requirement(changes_charter=False)
        c["kind"] = "requirement"
        out = req.requirement_gate([c], ctx.charter, ctx.cfg, 0.5,
                                   reader=ctx.reader)
        self.assertEqual(len(out.passed), 1)
        self.assertEqual(out.escalated, [])
        self.assertEqual(out.notes, [])

    def test_it_reaches_the_register_and_nobody_is_asked(self):
        runner = fake(wake=[decision(requirements=[self.a_growth_requirement()]),
                            decision()])
        ctx = self.boot(runner)
        Harness(ctx).turn()
        self.assertEqual(len(ctx.requirements.rows), 1)
        self.assertEqual(ctx.state.open_escalations(), [])
        self.assertEqual(ctx.state.process_notes, [])

    def test_only_a_quoted_contradiction_produces_a_process_note(self):
        from regent import requirements as req
        runner = fake(wake=[decision()])
        runner.scripts["reader"] = [reading([a_finding(
            rule="the charter intent", direction="intends",
            quote="It should replace the command line tool with a web service "
                  "for a whole team")])]
        ctx = self.boot(runner)
        c = self.a_growth_requirement(
            text="It should replace the command line tool with a web service "
                 "for a whole team",
            changes_charter=True)
        c["kind"] = "requirement"
        out = req.requirement_gate([c], ctx.charter, ctx.cfg, 0.5,
                                   reader=ctx.reader)
        self.assertEqual(out.passed, [])
        self.assertEqual(out.escalated, [])
        self.assertEqual(len(out.notes), 1)

    def test_an_unquoted_reader_verdict_cannot_overrule_his_false(self):
        from regent import requirements as req
        runner = fake(wake=[decision()])
        runner.scripts["reader"] = [reading([a_finding(
            rule="the charter intent", direction="intends",
            quote="a quote that is nowhere in the requirement")])]
        ctx = self.boot(runner)
        c = self.a_growth_requirement(changes_charter=False)
        c["kind"] = "requirement"
        out = req.requirement_gate([c], ctx.charter, ctx.cfg, 0.5,
                                   reader=ctx.reader)
        self.assertEqual(len(out.passed), 1)
        self.assertEqual(out.notes, [])

    def test_a_reader_cannot_talk_him_out_of_his_own_true(self):
        from regent import requirements as req
        runner = fake(wake=[decision()])
        runner.scripts["reader"] = [reading([])]
        ctx = self.boot(runner)
        c = self.a_growth_requirement(changes_charter=True)
        c["kind"] = "requirement"
        out = req.requirement_gate([c], ctx.charter, ctx.cfg, 0.5,
                                   reader=ctx.reader)
        self.assertEqual(out.passed, [])
        self.assertEqual(len(out.notes), 1)

    def test_a_reserved_class_is_still_the_one_wait(self):
        from regent import requirements as req
        runner = fake(wake=[decision()])
        runner.scripts["reader"] = [reading([])]
        ctx = self.boot(runner)
        c = self.a_growth_requirement(
            text="It should publish the report outside the project directory.",
            changes_charter=False)
        c["kind"] = "requirement"
        out = req.requirement_gate([c], ctx.charter, ctx.cfg, 0.5,
                                   reader=ctx.reader)
        self.assertEqual(out.passed, [])
        self.assertEqual(len(out.escalated), 1)
        self.assertIn("reserved class", out.escalated[0]["why"])

    def test_a_refusal_still_refuses(self):
        from regent import requirements as req
        runner = fake(wake=[decision()])
        runner.scripts["reader"] = [reading([])]
        ctx = self.boot(runner)
        c = self.a_growth_requirement(
            text="It should make a network request to check each link target.",
            changes_charter=False)
        c["kind"] = "requirement"
        out = req.requirement_gate([c], ctx.charter, ctx.cfg, 0.5,
                                   reader=ctx.reader)
        self.assertEqual(out.passed, [])
        self.assertIn("refusal", out.filed[0]["filed_reason"])

    def test_the_appetite_is_the_governor(self):
        from regent import requirements as req
        runner = fake(wake=[decision()])
        runner.scripts["reader"] = [reading([])]
        ctx = self.boot(runner)
        c = self.a_growth_requirement(appetite_share=0.9, changes_charter=False)
        c["kind"] = "requirement"
        out = req.requirement_gate([c], ctx.charter, ctx.cfg, 0.2,
                                   reader=ctx.reader)
        self.assertEqual(out.passed, [])
        self.assertIn("appetite", out.filed[0]["filed_reason"])

    def test_the_charter_default_appetite_is_half_the_budget(self):
        self.assertEqual(Config().requirements.default_appetite, 0.50)
        import tempfile
        from pathlib import Path

        from helpers import CHARTER

        from regent.charter import parse_charter
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "c.md"
            p.write_text(CHARTER.replace("- appetite: 30%\n", ""))
            self.assertEqual(parse_charter(p).appetite, 0.50)


class TestALineSaysWhoItBinds(unittest.TestCase):
    """The first run rejected a fixture dispatch for creating files, against a
    line about what the tool does.
    """

    def a_charter(self, body: str):
        import tempfile
        from pathlib import Path

        from regent.charter import parse_charter
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "c.md"
            p.write_text(body)
            return parse_charter(p)

    BODY = """# C

## Intent
A tool.

## Constraints
- The tool writes only to stdout. [product]
- Never install a package. [work]
- Python 3.11 only.

## Refusals
- Never make a network request. [both]

## Reserved
- Spending money.

## Budget
- spend_usd: 1

## Tools
- python3
- python3 -m unittest

## Stop
- When it works.
"""

    def test_the_mark_is_read_and_stripped_from_the_line(self):
        ch = self.a_charter(self.BODY)
        self.assertIn("The tool writes only to stdout.", ch.constraints)
        self.assertNotIn("[product]", " ".join(ch.constraints))
        self.assertEqual(ch.binds["The tool writes only to stdout."], "product")
        self.assertEqual(ch.binds["Never install a package."], "work")

    def test_an_unmarked_line_binds_both(self):
        ch = self.a_charter(self.BODY)
        self.assertEqual(ch.binds["Python 3.11 only."], "both")

    def test_the_tools_line_is_read(self):
        ch = self.a_charter(self.BODY)
        self.assertEqual(ch.tools, ["python3", "python3 -m unittest"])


class TestAContradictionMustQuoteTheCharter(HarnessCase):
    """The second run produced six process notes whose "charter line" was the
    requirement's own text, and one that quoted an objective.
    """

    def a_requirement(self, **over):
        r = a_wake_requirement(
            text="The tool prints a count of wiki style links it saw and did "
                 "not check.",
            serves_intent="obj-4: the owner will print the fixture and ask "
                          "Nula which cards are wrong.",
            changes_charter=False)
        r.update(over)
        r["kind"] = "requirement"
        return r

    def test_quoting_the_requirement_back_is_not_a_contradiction(self):
        from regent import requirements as req
        runner = fake(wake=[decision()])
        runner.scripts["reader"] = [reading([a_finding(
            rule="the charter intent", direction="intends",
            quote="The tool prints a count of wiki style links it saw and did "
                  "not check.")])]
        ctx = self.boot(runner)
        out = req.requirement_gate([self.a_requirement()], ctx.charter,
                                   ctx.cfg, 0.5, reader=ctx.reader)
        self.assertEqual(out.notes, [])
        self.assertEqual(len(out.passed), 1)

    def test_quoting_an_objective_is_not_a_contradiction(self):
        from regent import requirements as req
        runner = fake(wake=[decision()])
        runner.scripts["reader"] = [reading([a_finding(
            rule="the charter intent", direction="intends",
            quote="obj-4: the owner will print the fixture and ask Nula which "
                  "cards are wrong.")])]
        ctx = self.boot(runner)
        out = req.requirement_gate([self.a_requirement()], ctx.charter,
                                   ctx.cfg, 0.5, reader=ctx.reader)
        self.assertEqual(out.notes, [])
        self.assertEqual(len(out.passed), 1)

    def test_a_real_charter_line_is_a_contradiction(self):
        from regent import requirements as req
        runner = fake(wake=[decision()])
        runner.scripts["reader"] = [reading([a_finding(
            rule="the charter intent", direction="intends",
            quote="It is for one person maintaining a notes folder.")])]
        ctx = self.boot(runner)
        out = req.requirement_gate([self.a_requirement()], ctx.charter,
                                   ctx.cfg, 0.5, reader=ctx.reader)
        self.assertEqual(out.passed, [])
        self.assertEqual(len(out.notes), 1)
        self.assertIn("one person", out.notes[0]["why"])

    def test_the_quote_is_checked_against_a_named_text(self):
        runner = fake(wake=[decision()])
        runner.scripts["reader"] = [reading([a_finding(
            rule="r", direction="intends", quote="only in the other text")])]
        ctx = self.boot(runner)
        r = ctx.reader.read("q", "the text being read", ["r"],
                            quote_from="a passage that has only in the other "
                                       "text inside it")
        self.assertEqual(len(r.breaches()), 1)
        r2 = ctx.reader.read("q", "the text being read", ["r"],
                             quote_from="nothing of the sort here")
        self.assertEqual(r2.breaches(), [])


class TestLaunchFirstCheckBeside(HarnessCase):
    """Nothing of the regent's sits in the builders' path."""

    def test_a_low_tier_dispatch_starts_before_the_reader_has_read_it(self):
        runner = fake(wake=[decision(dispatches=[a_dispatch()]), decision()])
        ctx = self.boot(runner)
        Harness(ctx).turn()
        started = runner.calls_for("orchestrator")
        self.assertEqual(len(started), 1)
        # The reader ran too, but beside the work.
        beside = [r for r in ctx.ledger.all()
                  if r["kind"] == "reading" and r.get("beside")]
        self.assertTrue(beside)

    def test_a_breach_kills_the_running_dispatch(self):
        runner = fake(wake=[decision(dispatches=[a_dispatch(
            intent="Make a network request to fetch each link target.")]),
            decision()])
        runner.scripts["reader"] = [reading([a_finding(
            rule="Never make a network request.", direction="intends",
            quote="Make a network request to fetch each link target.")])]
        ctx = self.boot(runner)
        Harness(ctx).turn()
        self.assertEqual(ctx.state.dispatch("d0001").status, "killed")
        killed = [r for r in ctx.ledger.all() if r["kind"] == "kill"]
        self.assertTrue(killed)
        self.assertIn("while it ran", killed[0]["summary"])

    def test_a_killed_dispatch_produces_no_return(self):
        runner = fake(wake=[decision(dispatches=[a_dispatch(
            intent="Make a network request to fetch each link target.")]),
            decision(), decision()])
        runner.scripts["reader"] = [reading([a_finding(
            rule="Never make a network request.", direction="intends",
            quote="Make a network request to fetch each link target.")])]
        ctx = self.boot(runner)
        h = Harness(ctx)
        h.turn()
        h.turn()
        self.assertEqual(list(ctx.store.returns.glob("r*.json")), [])

    def test_a_clean_low_tier_dispatch_is_left_running(self):
        runner = fake(wake=[decision(dispatches=[a_dispatch()]), decision()])
        runner.scripts["reader"] = [reading([])]
        ctx = self.boot(runner)
        h = Harness(ctx)
        h.turn()
        self.assertEqual(ctx.state.dispatch("d0001").status, "open")
        h.turn()
        self.assertTrue(list(ctx.store.returns.glob("r*.json")))

    def test_a_medium_tier_dispatch_still_waits_for_the_reader(self):
        runner = fake(wake=[decision(dispatches=[a_dispatch(
            tier="medium",
            intent="Make a network request to fetch each link target.")]),
            decision()])
        runner.scripts["reader"] = [reading([a_finding(
            rule="Never make a network request.", direction="intends",
            quote="Make a network request to fetch each link target.")])]
        ctx = self.boot(runner)
        Harness(ctx).turn()
        self.assertEqual(runner.calls_for("orchestrator"), [])
