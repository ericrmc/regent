"""Unit tests for the parts that have to be reliable."""

from __future__ import annotations

import json
import unittest

from helpers import CHARTER, ROOT, HarnessCase, return_block

from regent import attention, schemas, spoon
from regent import decision as dec
from regent import signals as sig
from regent import stance as stn
from regent.charter import parse_charter
from regent.config import Config
from regent.manifold import ManifoldStore
from regent.prompts import Prompts
from regent.returns import parse_return
from regent.rng import Rng
from regent.runner import (
    ClaudeCliRunner,
    CommandRunner,
    FakeRunner,
    ModelRequest,
    parse_claude_json,
)
from regent.store import Store


class TestConfig(unittest.TestCase):
    def test_defaults_carry_the_documents_numbers(self):
        c = Config()
        self.assertEqual(c.manifold.decay_cycles, 20)
        # Pace: twenty links a pass, since the real passes stopped at 35, 18
        # and 14 on motif lock.
        self.assertEqual(c.drift.target_links_min, 15)
        self.assertEqual(c.drift.target_links_max, 20)
        self.assertEqual(c.drift.max_links, 60)
        self.assertEqual(c.drift.max_tokens, 4000)
        self.assertEqual(c.drift.motif_lock_repeats, 3)
        self.assertEqual(c.drift.groundedness_floor, 3)
        self.assertEqual(c.sift.keep, 5)
        self.assertEqual(c.attention.debt_cap, 3)
        self.assertAlmostEqual(c.attention.audit_rate, 0.2)
        self.assertEqual(c.signals.kill_after_idle_cycles, 5)
        self.assertEqual(c.signals.ladder_rungs, 6)

    def test_models_default_to_the_three_aliases(self):
        c = Config()
        self.assertEqual(c.models.wake, "opus")
        self.assertEqual(c.models.saturate, "sonnet")
        self.assertEqual(c.models.salience, "haiku")
        self.assertEqual(c.dispatching.permission_mode, "acceptEdits")

    def test_a_file_overrides_by_name(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "c.json"
            p.write_text(json.dumps({"models": {"sift": "gpt-x"}, "sift": {"keep": 3}}))
            c = Config.load(p)
            self.assertEqual(c.models.sift, "gpt-x")
            self.assertEqual(c.sift.keep, 3)
            self.assertEqual(c.models.wake, "opus")

    def test_an_unknown_key_is_refused(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "c.json"
            p.write_text(json.dumps({"nonsense": 1}))
            with self.assertRaises(ValueError):
                Config.load(p)


class TestRng(unittest.TestCase):
    def test_the_same_seed_replays(self):
        a = [Rng(seed=11).random() for _ in range(5)]
        b = [Rng(seed=11).random() for _ in range(5)]
        self.assertEqual(a, b)

    def test_resuming_from_a_draw_count_continues_the_stream(self):
        r = Rng(seed=11)
        first = [r.random() for _ in range(5)]
        resumed = Rng.from_state(r.state())
        fresh = Rng(seed=11)
        [fresh.random() for _ in range(5)]
        self.assertEqual([resumed.random() for _ in range(3)],
                         [fresh.random() for _ in range(3)])
        self.assertEqual(len(first), 5)

    def test_weighted_draws_respect_the_table(self):
        r = Rng(seed=3)
        counts = {}
        for _ in range(2000):
            k = r.weighted({"a": 9.0, "b": 1.0})
            counts[k] = counts.get(k, 0) + 1
        self.assertGreater(counts["a"], counts["b"] * 4)

    def test_sample_never_repeats_an_item(self):
        r = Rng(seed=5)
        got = r.sample(list(range(20)), 8)
        self.assertEqual(len(got), 8)
        self.assertEqual(len(set(got)), 8)


class TestCharter(unittest.TestCase):
    def setUp(self):
        import tempfile
        from pathlib import Path
        self.d = tempfile.TemporaryDirectory()
        p = Path(self.d.name) / "charter.md"
        p.write_text(CHARTER)
        self.ch = parse_charter(p)

    def tearDown(self):
        self.d.cleanup()

    def test_every_section_parses(self):
        self.assertIn("broken internal links", self.ch.intent)
        self.assertEqual(len(self.ch.refusals), 3)
        self.assertEqual(len(self.ch.reserved), 4)
        self.assertEqual(len(self.ch.constraints), 3)
        self.assertEqual(self.ch.missing, [])

    def test_the_budget_parses_into_numbers(self):
        self.assertEqual(self.ch.budget.tokens, 2_000_000)
        self.assertEqual(self.ch.budget.spend_usd, 10.0)
        self.assertEqual(self.ch.budget.wall_time_s, 7200)

    def test_the_digest_cadence_is_read_from_stop(self):
        self.assertEqual(self.ch.digest_every, 10)

    def test_a_quoted_line_is_recognised_as_a_citation(self):
        self.assertTrue(self.ch.cites("Never make a network request"))
        self.assertTrue(self.ch.cites("it is for one person maintaining a notes folder"))
        self.assertFalse(self.ch.cites("build a distributed queue for the team"))

    def test_the_hash_changes_when_the_text_does(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "c.md"
            p.write_text(CHARTER + "\nextra\n")
            self.assertNotEqual(parse_charter(p).sha256, self.ch.sha256)


class TestReturnContract(unittest.TestCase):
    def test_a_well_formed_block_parses(self):
        r = parse_return(return_block(), return_id="r1", dispatch_id="d1")
        self.assertTrue(r.parsed)
        self.assertEqual(r.headline, "The link checker now walks the folder.")
        self.assertEqual(len(r.evidence), 2)
        self.assertEqual(len(r.detail), 1)

    def test_a_missing_block_is_still_a_return_and_is_flagged(self):
        r = parse_return("I did the thing and it went fine.", return_id="r1")
        self.assertFalse(r.parsed)
        self.assertEqual(r.parse_error, "no return block found")
        self.assertEqual(r.top_tier(), "medium")
        self.assertIn("I did the thing", r.detail[0].body)

    def test_a_block_that_is_not_json_is_flagged_and_kept(self):
        text = "===RETURN===\nnot json at all\n===END RETURN===\n"
        r = parse_return(text)
        self.assertFalse(r.parsed)
        self.assertIn("not JSON", r.parse_error)
        self.assertIn("not json at all", r.detail[0].body)

    def test_a_fenced_block_still_parses(self):
        payload = {"headline": "h", "recommendation": "r", "flags": [],
                   "evidence": [], "detail": []}
        text = "===RETURN===\n```json\n" + json.dumps(payload) + "\n```\n===END RETURN===\n"
        self.assertTrue(parse_return(text).parsed)

    def test_the_top_tier_is_the_highest_flag(self):
        r = parse_return(return_block(flags=[
            {"tier": "low", "text": "a"}, {"tier": "high", "text": "b"}]))
        self.assertEqual(r.top_tier(), "high")

    def test_the_whole_text_is_kept_whatever_happens(self):
        r = parse_return("junk " + return_block())
        self.assertIn("junk", r.raw_text)


class TestAttention(unittest.TestCase):
    def setUp(self):
        self.cfg = Config()
        self.rng = Rng(seed=1)

    def draw(self, ret, **over):
        kw = {"trust": 0.5, "queue_depth": 0, "unease": 0.0, "stance": 0.0, "debt": 0}
        kw.update(over)
        return attention.draw_mode(ret, self.cfg, self.rng, **kw)

    def test_a_high_tier_flag_is_full_always(self):
        ret = parse_return(return_block(flags=[{"tier": "high", "text": "it writes outside the dir"}]))
        for _ in range(20):
            d = self.draw(ret, trust=1.0, queue_depth=9)
            self.assertEqual(d.mode, attention.FULL)
            self.assertEqual(d.forced, "high-tier flag")

    def test_a_medium_tier_flag_is_skim_at_least(self):
        ret = parse_return(return_block(flags=[{"tier": "medium", "text": "a criterion is unmet"}]))
        for _ in range(30):
            d = self.draw(ret, trust=1.0, queue_depth=9)
            self.assertGreaterEqual(attention._MODE_RANK[d.mode],
                                    attention._MODE_RANK[attention.SKIM])

    def test_debt_at_the_cap_forces_a_full_read(self):
        ret = parse_return(return_block())
        d = self.draw(ret, debt=self.cfg.attention.debt_cap, trust=1.0)
        self.assertEqual(d.mode, attention.FULL)
        self.assertIn("unread debt", d.forced)

    def test_low_trust_forces_a_full_read(self):
        ret = parse_return(return_block())
        d = self.draw(ret, trust=0.1)
        self.assertEqual(d.mode, attention.FULL)

    def test_high_trust_and_a_deep_queue_buy_less_attention(self):
        ret = parse_return(return_block())
        deep = [self.draw(ret, trust=1.0, queue_depth=5).mode for _ in range(40)]
        shallow = [self.draw(ret, trust=0.5, queue_depth=0, unease=0.9).mode
                   for _ in range(40)]
        self.assertLess(sum(attention._MODE_RANK[m] for m in deep),
                        sum(attention._MODE_RANK[m] for m in shallow))

    def test_the_draw_replays_on_the_same_seed(self):
        ret = parse_return(return_block())
        a = [attention.draw_mode(ret, self.cfg, Rng(seed=4), trust=0.5, queue_depth=1,
                                 unease=0.2, stance=0.0, debt=0).mode for _ in range(5)]
        b = [attention.draw_mode(ret, self.cfg, Rng(seed=4), trust=0.5, queue_depth=1,
                                 unease=0.2, stance=0.0, debt=0).mode for _ in range(5)]
        self.assertEqual(a, b)


class TestTheCut(unittest.TestCase):
    def setUp(self):
        self.cfg = Config()
        self.ret = parse_return(return_block(
            flags=[{"tier": "low", "text": "anchors are unchecked", "criterion": ""}],
            detail=[{"heading": "What was built",
                     "body": "The checker walks the folder. "
                             "It resolves relative links against the containing file. "
                             "It took 0.4 seconds over 120 files. "
                             "The queue is unbounded and that worries me."}]))

    def test_wave_through_is_the_recommendation_only(self):
        text = attention.cut(self.ret, attention.WAVE, self.cfg)
        self.assertIn("Ship it", text)
        self.assertNotIn("walks the folder", text)
        self.assertNotIn("anchors are unchecked", text)

    def test_glance_is_headline_recommendation_and_flags(self):
        text = attention.cut(self.ret, attention.GLANCE, self.cfg)
        self.assertIn("The link checker now walks the folder.", text)
        self.assertIn("anchors are unchecked", text)
        self.assertNotIn("resolves relative links", text)
        self.assertNotIn("evidence/run.txt", text)

    def test_skim_keeps_the_first_sentence_and_every_number(self):
        text = attention.cut(self.ret, attention.SKIM, self.cfg)
        self.assertIn("The checker walks the folder.", text)
        self.assertIn("0.4 seconds over 120 files", text)
        self.assertNotIn("resolves relative links", text)
        self.assertIn("evidence/run.txt", text)
        self.assertNotIn("the tool on a real folder", text)

    def test_the_skim_says_how_much_it_dropped(self):
        text = attention.cut(self.ret, attention.SKIM, self.cfg)
        self.assertIn("the skim dropped", text)

    def test_full_carries_everything(self):
        text = attention.cut(self.ret, attention.FULL, self.cfg)
        self.assertIn("resolves relative links", text)
        self.assertIn("the tool on a real folder", text)
        self.assertIn("unbounded", text)

    def test_a_worried_eye_catches_the_thing_it_is_worried_about(self):
        text = attention.cut(self.ret, attention.SKIM, self.cfg,
                             motifs=["an unbounded queue"], unease=0.6)
        self.assertIn("CAUGHT BY A WORRIED EYE", text)
        self.assertIn("unbounded", text)

    def test_the_salience_model_chooses_which_lines_pass(self):
        seen = {}

        def salience(lines, motifs, unease):
            seen["lines"] = lines
            return [len(lines) - 1]

        text = attention.cut(self.ret, attention.SKIM, self.cfg, salience=salience,
                             motifs=["anything"], unease=0.9)
        self.assertIn("CAUGHT BY A WORRIED EYE", text)
        self.assertIn("unbounded", text)
        self.assertTrue(seen["lines"])

    def test_a_failing_salience_model_falls_back_to_keywords(self):
        def salience(lines, motifs, unease):
            raise RuntimeError("the small model died")

        text = attention.cut(self.ret, attention.SKIM, self.cfg, salience=salience,
                             motifs=["unbounded queue"], unease=0.5)
        self.assertIn("unbounded", text)

    def test_the_ledger_phrase_matches_the_mode(self):
        self.assertEqual(attention.ledger_phrase(attention.WAVE),
                         "accepted on recommendation, unread")
        self.assertEqual(attention.ledger_phrase(attention.SKIM), "judged on a skim")


class TestTrust(unittest.TestCase):
    def test_agreement_raises_and_a_buried_defect_drops_hard(self):
        t = attention.Trust(Config())
        start = t.get("k")
        self.assertAlmostEqual(t.agreed("k"), start + 0.05)
        after = t.missed("k", "buried")
        self.assertLess(after, start - 0.25)

    def test_trust_never_leaves_zero_to_one(self):
        t = attention.Trust(Config())
        for _ in range(50):
            t.agreed("k")
        self.assertLessEqual(t.get("k"), 1.0)
        for _ in range(50):
            t.missed("k", "buried")
        self.assertGreaterEqual(t.get("k"), 0.0)


class TestManifold(HarnessCase):
    def setUp(self):
        super().setUp()
        self.store.ensure()
        self.m = ManifoldStore(self.store, self.cfg)

    def test_every_element_carries_an_id_a_timestamp_and_a_texture(self):
        el = self.m.write("friction", "the build took 40 minutes")
        self.assertTrue(el.id.startswith("m"))
        self.assertGreater(el.ts, 0)
        self.assertEqual(el.texture, "friction")

    def test_an_unknown_texture_falls_back_rather_than_raising(self):
        self.assertEqual(self.m.write("nonsense", "x").texture, "friction")

    def test_decay_cools_an_element_uncited_for_the_window(self):
        el = self.m.write("sensory", "a screenshot", cycle=0)
        self.assertEqual(self.m.decay(cycle=5), [])
        cooled = self.m.decay(cycle=self.cfg.manifold.decay_cycles)
        self.assertEqual(cooled, [el.id])
        self.assertEqual([e.id for e in self.m.cold()], [el.id])

    def test_refusals_never_decay(self):
        el = self.m.write("refusal", "never make a network request", cycle=0)
        self.m.decay(cycle=500)
        self.assertIn(el.id, [e.id for e in self.m.warm()])

    def test_a_citation_brings_a_cold_element_back(self):
        el = self.m.write("sensory", "a log tail", cycle=0)
        self.m.decay(cycle=self.cfg.manifold.decay_cycles)
        self.m.cite([el.id], cycle=30)
        self.assertIn(el.id, [e.id for e in self.m.warm()])
        self.assertEqual(self.m.cold(), [])

    def test_the_forgetting_pass_is_probabilistic_and_replays(self):
        for i in range(30):
            self.m.write("sensory", f"element {i}", cycle=0)
        a = self.m.forget(Rng(seed=21), cycle=4)
        self.assertTrue(a)
        self.assertLess(len(a), 30)
        # The same seed over the same field drops the same elements.
        m2 = ManifoldStore(Store(self.root / "run2"), self.cfg)
        m2.store.ensure()
        for i in range(30):
            m2.write("sensory", f"element {i}", cycle=0)
        b = m2.forget(Rng(seed=21), cycle=4)
        self.assertEqual(a, b)

    def test_a_cited_element_is_shielded_from_forgetting(self):
        el = self.m.write("sensory", "cited often", cycle=0)
        self.m.cite([el.id] * 1, cycle=1)
        self.m.cite([el.id], cycle=2)
        self.m.forget(Rng(seed=2), cycle=1)
        self.assertIn(el.id, [e.id for e in self.m.warm()])

    def test_replay_resurfaces_a_cold_element(self):
        el = self.m.write("unfinished", "a branch nobody finished", cycle=0)
        self.m.decay(cycle=100)
        back = self.m.replay(Rng(seed=3), cycle=101)
        self.assertEqual(back.id, el.id)
        self.assertIn(el.id, [e.id for e in self.m.warm()])

    def test_each_subset_differs(self):
        for i in range(40):
            self.m.write("sensory", f"e{i}", cycle=0)
        r = Rng(seed=9)
        a = {e.id for e in self.m.subset(r)}
        b = {e.id for e in self.m.subset(r)}
        self.assertNotEqual(a, b)
        self.assertTrue(a)

    def test_the_render_leads_with_the_id_so_a_link_can_cite_it(self):
        from regent.manifold import render
        el = self.m.write("foreign", "a bridge inspector taps the steel")
        self.assertTrue(render(self.m.warm()).startswith(el.id))


class TestCatch(unittest.TestCase):
    """Catch is the falling spoon. The stop rules run in code."""

    def setUp(self):
        self.cfg = Config()
        self.ids = {f"m{i:05d}" for i in range(1, 200)}

    def link(self, anchors, text="a link"):
        return {"kind": "seed", "text": text, "anchors": anchors,
                "ingredients": [], "mechanism": "m"}

    def test_the_groundedness_floor_ends_the_pass(self):
        links = [self.link(["m00001"]), self.link([]), self.link([]), self.link([]),
                 self.link(["m00002"])]
        kept, stop = spoon.catch(links, self.cfg, manifold_ids=self.ids)
        self.assertEqual(stop["rule"], spoon.STOP_GROUNDEDNESS)
        self.assertEqual(len(kept), 1)

    def test_motif_lock_ends_the_pass(self):
        pair = ["m00001", "m00002"]
        links = [self.link(pair), self.link(pair), self.link(pair), self.link(pair)]
        kept, stop = spoon.catch(links, self.cfg, manifold_ids=self.ids)
        self.assertEqual(stop["rule"], spoon.STOP_MOTIF_LOCK)
        self.assertEqual(len(kept), 1)

    def test_the_link_budget_ends_the_pass(self):
        links = [self.link([f"m{i:05d}"]) for i in range(1, 120)]
        kept, stop = spoon.catch(links, self.cfg, manifold_ids=self.ids)
        self.assertEqual(stop["rule"], spoon.STOP_BUDGET)
        self.assertEqual(len(kept), self.cfg.drift.max_links)

    def test_the_token_budget_ends_the_pass(self):
        big = "word " * 400
        links = [self.link([f"m{i:05d}"], big) for i in range(1, 40)]
        kept, stop = spoon.catch(links, self.cfg, manifold_ids=self.ids)
        self.assertEqual(stop["rule"], spoon.STOP_BUDGET)
        self.assertLess(len(kept), 40)

    def test_an_anchor_that_is_not_a_real_id_does_not_count(self):
        links = [self.link(["invented-id"]), self.link(["also-invented"]),
                 self.link(["still-invented"])]
        kept, stop = spoon.catch(links, self.cfg, manifold_ids=self.ids)
        self.assertEqual(kept, [])
        self.assertEqual(stop["rule"], spoon.STOP_GROUNDEDNESS)

    def test_a_clean_pass_runs_to_the_end(self):
        links = [self.link([f"m{i:05d}"]) for i in range(1, 10)]
        kept, stop = spoon.catch(links, self.cfg, manifold_ids=self.ids)
        self.assertEqual(stop["rule"], spoon.STOP_EXHAUSTED)
        self.assertEqual(len(kept), 9)


class TestTheGate(unittest.TestCase):
    def test_a_candidate_with_no_disconfirming_observation_is_filed(self):
        passed, filed = spoon.gate([
            {"text": "a", "disconfirming": "Run the checker on a folder with a symlink loop."},
            {"text": "b", "disconfirming": ""},
            {"text": "c", "disconfirming": "  "},
            {"text": "d", "disconfirming": "short"},
        ])
        self.assertEqual([c["text"] for c in passed], ["a"])
        self.assertEqual(len(filed), 3)
        self.assertIn("no disconfirming observation", filed[0]["filed_reason"])


class TestDecisionValidation(unittest.TestCase):
    def setUp(self):
        import tempfile
        from pathlib import Path
        self.d = tempfile.TemporaryDirectory()
        p = Path(self.d.name) / "charter.md"
        p.write_text(CHARTER)
        self.ch = parse_charter(p)
        self.cfg = Config()

    def tearDown(self):
        self.d.cleanup()

    def base(self, **over):
        from helpers import decision
        return decision(**over)

    def test_a_reserved_class_becomes_an_escalation(self):
        # Medium tier, because low tier launches first and is checked beside.
        d = self.base(dispatches=[{
            "id": "d1", "objective_id": "obj-1", "title": "Publish the results",
            "intent": "Publish the report outside the project directory for review.",
            "acceptance": ["it is published"], "tier": "medium",
            "classes": ["publishing outside the project directory"]}])
        v = dec.validate_decision(d, self.ch, self.cfg)
        self.assertEqual(v.decision["dispatches"], [])
        self.assertEqual(len(v.escalations), 1)
        self.assertIn("reserved class", v.escalations[0]["why"])

    def test_a_high_tier_dispatch_escalates_rather_than_running(self):
        d = self.base(dispatches=[{
            "id": "d1", "objective_id": "obj-1", "title": "Rewrite the notes folder",
            "intent": "Rewrite every note in place.", "acceptance": ["done"],
            "tier": "high", "classes": ["irreversible"]}])
        v = dec.validate_decision(d, self.ch, self.cfg)
        self.assertEqual(v.decision["dispatches"], [])
        self.assertEqual(v.escalations[0]["tier"], "high")

    def test_a_dispatch_naming_a_refusal_is_rejected_and_logged(self):
        d = self.base(dispatches=[{
            "id": "d1", "objective_id": "obj-1", "title": "Fetch the schema",
            "intent": "Make a network request to fetch the link schema.",
            "acceptance": ["it fetches"], "tier": "medium",
            "classes": ["network"]}])
        v = dec.validate_decision(d, self.ch, self.cfg)
        self.assertEqual(v.decision["dispatches"], [])
        self.assertFalse(v.clean)
        self.assertIn("refusal", v.rejections[0]["reason"])

    def test_editing_the_charter_is_rejected(self):
        d = self.base(objectives=[{
            "action": "add", "id": "obj-9",
            "text": "I will relax the refusals so the tool can fetch link targets.",
            "weight": 0.5, "charter_line": "Never make a network request.",
            "trigger": "the work needs it"}])
        v = dec.validate_decision(d, self.ch, self.cfg)
        self.assertEqual(v.decision["objectives"], [])
        self.assertIn("charter", v.rejections[0]["reason"])

    def test_rewriting_ledger_history_is_rejected(self):
        d = self.base(dispatches=[{
            "id": "d1", "objective_id": "obj-1", "title": "Tidy the record",
            "intent": "Rewrite the ledger to remove the failed turns.",
            "acceptance": ["it is tidy"], "tier": "low", "classes": ["records"]}])
        v = dec.validate_decision(d, self.ch, self.cfg)
        self.assertEqual(v.decision["dispatches"], [])
        self.assertIn("charter", v.rejections[0]["reason"])

    def test_an_objective_that_cites_nothing_is_drift_and_is_rejected(self):
        d = self.base(objectives=[{
            "action": "add", "id": "obj-9", "text": "I will build a web dashboard.",
            "weight": 0.5, "charter_line": "", "trigger": "it seemed good"}])
        v = dec.validate_decision(d, self.ch, self.cfg)
        self.assertEqual(v.decision["objectives"], [])
        self.assertIn("drift", v.rejections[0]["reason"])

    def test_an_objective_citing_a_real_charter_line_survives(self):
        d = self.base(objectives=[{
            "action": "add", "id": "obj-2",
            "text": "I will make the report readable at a glance.",
            "weight": 0.6,
            "charter_line": "It is for one person maintaining a notes folder.",
            "trigger": "the first return"}])
        v = dec.validate_decision(d, self.ch, self.cfg)
        self.assertEqual(len(v.decision["objectives"]), 1)
        self.assertTrue(v.clean)

    def test_a_low_tier_dispatch_launches_without_waiting_for_the_reader(self):
        """Low tier means revertible, so optimism costs a revert at worst."""
        from helpers import a_dispatch
        d = self.base(dispatches=[a_dispatch(
            intent="Make a network request to fetch the link schema.")])
        v = dec.validate_decision(d, self.ch, self.cfg)
        self.assertEqual(len(v.decision["dispatches"]), 1)
        self.assertEqual(v.readings, [])

    def test_a_low_tier_dispatch_passes_untouched(self):
        from helpers import a_dispatch
        d = self.base(dispatches=[a_dispatch()])
        v = dec.validate_decision(d, self.ch, self.cfg)
        self.assertEqual(len(v.decision["dispatches"]), 1)
        self.assertEqual(v.escalations, [])
        self.assertTrue(v.clean)

    def test_many_mediums_compound_into_a_high_one(self):
        from helpers import a_dispatch
        d = self.base(dispatches=[a_dispatch("d1", tier="medium"),
                                  a_dispatch("d2", tier="medium")])
        v = dec.validate_decision(d, self.ch, self.cfg,
                                  recent_medium=self.cfg.tiers.medium_runaway_count)
        self.assertEqual(v.decision["dispatches"], [])
        self.assertEqual(len(v.escalations), 2)
        self.assertIn("aggregate", v.escalations[0]["why"])

    def test_an_agent_raised_escalation_passes_through(self):
        d = self.base(escalations=[{"question": "May I spend money?", "tier": "high",
                                    "why": "the charter reserves it"}])
        v = dec.validate_decision(d, self.ch, self.cfg)
        self.assertEqual(len(v.escalations), 1)
        self.assertEqual(v.escalations[0]["source"], "agent")

    def test_a_ledger_that_only_relaxes_fires_the_detector(self):
        amendments = [{"direction": "relax"} for _ in range(8)]
        self.assertIn("below the floor", dec.check_amendment_ratio(amendments, self.cfg))
        mixed = [{"direction": "raise"} for _ in range(4)] + \
                [{"direction": "relax"} for _ in range(4)]
        self.assertEqual(dec.check_amendment_ratio(mixed, self.cfg), "")


class TestSchemas(unittest.TestCase):
    def test_a_good_decision_validates(self):
        from helpers import decision
        schemas.validate(decision(), schemas.DECISION)

    def test_a_missing_required_key_raises(self):
        from helpers import decision
        d = decision()
        del d["rationale"]
        with self.assertRaises(schemas.SchemaError):
            schemas.validate(d, schemas.DECISION)

    def test_a_bad_enum_raises(self):
        from helpers import decision
        d = decision(judgements=[{"return_id": "r1", "outcome": "maybe", "reason": "x"}])
        with self.assertRaises(schemas.SchemaError):
            schemas.validate(d, schemas.DECISION)

    def test_an_unexpected_key_raises(self):
        from helpers import decision
        d = decision()
        d["writes"] = [{"path": "charter.md", "content": "new"}]
        with self.assertRaises(schemas.SchemaError):
            schemas.validate(d, schemas.DECISION)

    def test_coerce_fills_a_missing_list_but_not_a_missing_scalar(self):
        from helpers import decision
        d = decision()
        del d["ladder"]
        del d["rationale"]
        out = schemas.coerce(d, schemas.DECISION)
        self.assertEqual(out["ladder"], [])
        self.assertNotIn("rationale", out)

    def test_every_role_has_a_schema(self):
        for role in ("wake", "react", "saturate", "drift", "sift", "consolidate",
                     "salience", "day_fragment", "audit"):
            self.assertIn(role, schemas.BY_ROLE)


class TestStanceAndSignals(unittest.TestCase):
    def setUp(self):
        self.cfg = Config()

    def test_the_step_per_turn_is_bounded(self):
        s = stn.StanceState(value=0.0)
        stn.tilt(s, self.cfg, friction=50)
        self.assertGreaterEqual(s.value, -self.cfg.stance.max_step_per_turn - 1e-9)

    def test_stance_never_leaves_its_bounds(self):
        s = stn.StanceState(value=0.0)
        for _ in range(100):
            stn.tilt(s, self.cfg, friction=50)
        self.assertGreaterEqual(s.value, -1.0)
        for _ in range(200):
            stn.tilt(s, self.cfg, unfinished=50, foreign=50)
        self.assertLessEqual(s.value, 1.0)

    def test_friction_tilts_to_risk_and_unfinished_tilts_to_opportunity(self):
        a = stn.StanceState(value=0.0)
        stn.tilt(a, self.cfg, friction=5)
        b = stn.StanceState(value=0.0)
        stn.tilt(b, self.cfg, unfinished=5)
        self.assertLess(a.value, b.value)

    def test_a_drift_that_died_at_the_floor_tilts_to_risk(self):
        a = stn.StanceState(value=0.0)
        stn.tilt(a, self.cfg, drift_died_grounded=True)
        self.assertLess(a.value, 0)

    def test_the_interlude_perturbation_stays_inside_the_amplitude(self):
        s = stn.StanceState(value=0.0)
        r = Rng(seed=8)
        for _ in range(50):
            before = s.value
            stn.perturb(s, self.cfg, r)
            self.assertLessEqual(abs(s.value - before),
                                 self.cfg.stance.interlude_drift_amplitude + 1e-9)

    def test_stance_moves_sifts_weights_and_the_drift_budget(self):
        risk = stn.sift_weights(stn.StanceState(value=-1.0), self.cfg)
        opp = stn.sift_weights(stn.StanceState(value=1.0), self.cfg)
        self.assertGreater(opp["novelty"], risk["novelty"])
        self.assertGreater(risk["mechanism"], opp["mechanism"])
        self.assertAlmostEqual(sum(opp.values()), 1.0, places=2)
        self.assertGreater(stn.drift_target(stn.StanceState(value=1.0), self.cfg, 1.0),
                           stn.drift_target(stn.StanceState(value=-1.0), self.cfg, 0.0))

    def test_the_drift_target_stays_in_the_documents_range(self):
        for v in (-1.0, 0.0, 1.0):
            for c in (0.0, 0.5, 1.0):
                t = stn.drift_target(stn.StanceState(value=v), self.cfg, c)
                self.assertGreaterEqual(t, self.cfg.drift.target_links_min)
                self.assertLessEqual(t, self.cfg.drift.target_links_max)

    def test_signals_stay_between_zero_and_one(self):
        s = sig.SignalSet()
        sig.update(s, self.cfg, failures=50, questions=50, accepts=50, thin_evidence=50)
        for v in (s.frustration, s.curiosity, s.satisfaction, s.unease):
            self.assertGreaterEqual(v, 0.0)
            self.assertLessEqual(v, 1.0)

    def test_an_interlude_decays_the_signals(self):
        s = sig.SignalSet(frustration=1.0, unease=1.0)
        sig.decay(s, self.cfg)
        self.assertLess(s.frustration, 1.0)
        self.assertGreater(s.frustration, 0.0)

    def test_thin_evidence_is_no_openable_reference(self):
        self.assertTrue(sig.thin_evidence(parse_return(return_block(evidence=[]))))
        self.assertTrue(sig.thin_evidence(parse_return(return_block(
            evidence=[{"kind": "output", "ref": "", "note": "it worked"}]))))
        self.assertFalse(sig.thin_evidence(parse_return(return_block())))

    def test_the_ladder_climbs_one_rung_per_failure_and_stops_at_six(self):
        L = sig.Ladder(self.cfg)
        rungs = [L.record_failure("d1") for _ in range(9)]
        self.assertEqual(rungs[:6], [1, 2, 3, 4, 5, 6])
        self.assertEqual(rungs[-1], 6)

    def test_progress_resets_the_ladder(self):
        L = sig.Ladder(self.cfg)
        L.record_failure("d1")
        L.record_failure("d1")
        L.record_progress("d1")
        self.assertEqual(L.rung("d1"), 1)

    def test_an_idle_subgoal_loses_its_allocation_without_frustration(self):
        L = sig.Ladder(self.cfg)
        killed = []
        for _ in range(self.cfg.signals.kill_after_idle_cycles):
            killed = L.tick_idle(["d1"])
        self.assertEqual(killed, ["d1"])
        self.assertEqual(L.rung("d1"), 6)


class TestRunners(unittest.TestCase):
    def test_the_toolless_call_carries_the_flags_that_make_it_toolless(self):
        argv = ClaudeCliRunner().argv(ModelRequest(
            role="wake", prompt="p", model="opus", schema={"type": "object"},
            system="s", toolless=True, max_budget_usd=2.0))
        self.assertIn("--tools", argv)
        self.assertEqual(argv[argv.index("--tools") + 1], "")
        self.assertIn("--strict-mcp-config", argv)
        self.assertIn("--setting-sources", argv)
        self.assertIn("--disable-slash-commands", argv)
        self.assertIn("--no-session-persistence", argv)
        self.assertIn("--json-schema", argv)
        self.assertIn("--system-prompt", argv)
        self.assertEqual(argv[argv.index("--output-format") + 1], "json")
        self.assertEqual(argv[argv.index("--max-budget-usd") + 1], "2.0")

    def test_the_toolless_call_never_carries_a_permission_mode_or_plugin(self):
        argv = ClaudeCliRunner().argv(ModelRequest(
            role="wake", prompt="p", toolless=True, permission_mode="acceptEdits",
            plugin_dirs=["/plugin"], agents={"b": {}}))
        self.assertNotIn("--permission-mode", argv)
        self.assertNotIn("--plugin-dir", argv)
        self.assertNotIn("--agents", argv)

    def test_the_orchestrator_call_carries_tools_a_session_and_the_plugin(self):
        argv = ClaudeCliRunner().argv(ModelRequest(
            role="orchestrator", prompt="p", model="opus", toolless=False,
            tools=["Bash", "Read"], permission_mode="acceptEdits",
            plugin_dirs=["/p"], agents={"builder": {"prompt": "x"}},
            session_id="abc", add_dirs=["/proj"], persist_session=True,
            allow_settings=True))
        self.assertEqual(argv[argv.index("--tools") + 1], "Bash,Read")
        self.assertEqual(argv[argv.index("--permission-mode") + 1], "acceptEdits")
        self.assertEqual(argv[argv.index("--plugin-dir") + 1], "/p")
        self.assertEqual(argv[argv.index("--session-id") + 1], "abc")
        self.assertEqual(argv[argv.index("--add-dir") + 1], "/proj")
        self.assertIn("--agents", argv)
        # Named opt-outs, the only two in the tree.
        self.assertNotIn("--no-session-persistence", argv)
        self.assertNotIn("--setting-sources", argv)
        # Strict MCP config is never opted out of.
        self.assertIn("--strict-mcp-config", argv)

    def test_resuming_uses_resume_and_not_session_id(self):
        argv = ClaudeCliRunner().argv(ModelRequest(
            role="orchestrator", prompt="p", toolless=False, session_id="abc",
            resume=True, persist_session=True))
        self.assertIn("--resume", argv)
        self.assertNotIn("--session-id", argv)

    def test_bare_is_off_by_default_and_opt_in(self):
        self.assertNotIn("--bare", ClaudeCliRunner().argv(ModelRequest(role="wake", prompt="p")))
        self.assertIn("--bare", ClaudeCliRunner(use_bare=True).argv(
            ModelRequest(role="wake", prompt="p")))

    def test_the_envelope_is_parsed_into_a_response(self):
        payload = {"result": "{\"ok\": true}", "structured_output": {"ok": True},
                   "session_id": "s1", "total_cost_usd": 0.003,
                   "usage": {"input_tokens": 10, "output_tokens": 5,
                             "cache_creation_input_tokens": 100,
                             "cache_read_input_tokens": 0},
                   "is_error": False}
        r = parse_claude_json("wake", json.dumps(payload), "", 0)
        self.assertEqual(r.structured, {"ok": True})
        self.assertEqual(r.session_id, "s1")
        self.assertAlmostEqual(r.cost_usd, 0.003)
        self.assertEqual(r.input_tokens, 110)
        self.assertFalse(r.is_error)

    def test_a_non_json_failure_is_kept_rather_than_lost(self):
        r = parse_claude_json("wake", "something went wrong", "stderr text", 1)
        self.assertTrue(r.is_error)
        self.assertEqual(r.text, "something went wrong")

    def test_an_empty_stdout_is_an_error(self):
        self.assertTrue(parse_claude_json("wake", "", "boom", 1).is_error)

    def test_the_command_runner_builds_argv_and_digs_out_the_result(self):
        r = CommandRunner(template=["echo", "{model}"], output="json",
                          result_path="choices.text")
        self.assertEqual(r.template, ["echo", "{model}"])
        from regent.runner import _dig
        self.assertEqual(_dig({"choices": {"text": "hi"}}, "choices.text"), "hi")

    def test_the_command_runner_reads_loose_json_out_of_prose(self):
        from regent.runner import _loose_json
        self.assertEqual(_loose_json("here you go ```json\n{\"a\": 1}\n``` done"), {"a": 1})
        self.assertIsNone(_loose_json("no object here"))

    def test_the_fake_runner_scripts_by_role_and_repeats_the_last(self):
        f = FakeRunner(scripts={"wake": [{"a": 1}, {"a": 2}]})
        self.assertEqual(f.run(ModelRequest(role="wake", prompt="")).structured, {"a": 1})
        self.assertEqual(f.run(ModelRequest(role="wake", prompt="")).structured, {"a": 2})
        self.assertEqual(f.run(ModelRequest(role="wake", prompt="")).structured, {"a": 2})
        self.assertEqual(len(f.calls_for("wake")), 3)

    def test_the_fake_runner_spends_nothing(self):
        f = FakeRunner(scripts={"wake": [{"a": 1}]})
        self.assertEqual(f.run(ModelRequest(role="wake", prompt="")).cost_usd, 0.0)

    def test_an_unscripted_role_is_an_error_not_a_silent_pass(self):
        f = FakeRunner(scripts={})
        self.assertTrue(f.run(ModelRequest(role="wake", prompt="")).is_error)


class TestPrompts(unittest.TestCase):
    def setUp(self):
        self.p = Prompts(ROOT / "prompts")

    def test_every_state_has_a_prompt_file(self):
        for name in ("wake", "react", "saturate", "drift", "sift", "consolidate",
                     "salience", "day_fragment", "audit"):
            self.assertTrue(self.p.text(name).strip(), name)

    def test_an_unfilled_placeholder_raises_rather_than_shipping(self):
        with self.assertRaises(KeyError):
            self.p.fill("saturate", manifold_warm="x")

    def test_filling_substitutes_literally(self):
        out = self.p.fill("saturate", manifold_warm="ELEMENTS", objectives="OBJ")
        self.assertIn("ELEMENTS", out)
        self.assertNotIn("{{", out)

    def test_sift_never_reveals_where_the_list_came_from(self):
        """An evaluator that knows it is reading its own output is captured."""
        text = self.p.text("sift").lower()
        for word in ("drift", "dream", "spoon", "hypnagog", "manifold",
                     "you generated", "your own"):
            self.assertNotIn(word, text)

    def test_drift_demands_anchors_provenance_and_mechanism(self):
        text = self.p.text("drift").lower()
        self.assertIn("anchor", text)
        self.assertIn("mechanism", text)
        self.assertIn("outside", text)

    def test_wake_presents_the_charter_as_first_person_objectives(self):
        text = self.p.text("wake")
        self.assertIn("{{self}}", text)
        self.assertIn("first person", text.lower())


class TestPlugin(unittest.TestCase):
    def test_the_manifest_is_valid_json_with_a_name(self):
        data = json.loads((ROOT / "plugin" / ".claude-plugin" / "plugin.json").read_text())
        self.assertEqual(data["name"], "regent")

    def test_both_skills_exist_with_frontmatter(self):
        for skill in ("return-report", "evidence-capture"):
            text = (ROOT / "plugin" / "skills" / skill / "SKILL.md").read_text()
            self.assertTrue(text.startswith("---"))
            self.assertIn(f"name: {skill}", text)

    def test_return_report_specifies_the_delimiters_the_parser_reads(self):
        text = (ROOT / "plugin" / "skills" / "return-report" / "SKILL.md").read_text()
        from regent.returns import CLOSE, OPEN
        self.assertIn(OPEN, text)
        self.assertIn(CLOSE, text)
        for key in ("headline", "recommendation", "flags", "evidence", "detail"):
            self.assertIn(key, text)

    def test_the_orchestrator_system_prompt_carries_the_contract_itself(self):
        """A skill that does not trigger would cost the run a return, so the
        contract is in the system prompt and the skill is reinforcement.
        """
        from regent.dispatch import SYSTEM
        from regent.returns import CLOSE, OPEN
        self.assertIn(OPEN, SYSTEM)
        self.assertIn(CLOSE, SYSTEM)
        for key in ("headline", "recommendation", "flags", "evidence", "detail"):
            self.assertIn(key, SYSTEM)
        self.assertIn("never amend an acceptance criterion", SYSTEM.lower())

    def test_the_skill_example_parses_with_the_harnesss_parser(self):
        text = (ROOT / "plugin" / "skills" / "return-report" / "SKILL.md").read_text()
        r = parse_return(text)
        self.assertTrue(r.parsed, r.parse_error)
        self.assertTrue(r.headline)


class TestExampleCharter(unittest.TestCase):
    def test_the_example_charter_parses_fully(self):
        ch = parse_charter(ROOT / "examples" / "charter.md")
        self.assertEqual(ch.missing, [])
        self.assertTrue(ch.intent)
        self.assertGreaterEqual(len(ch.refusals), 3)
        self.assertGreaterEqual(len(ch.reserved), 4)
        self.assertGreater(ch.budget.spend_usd, 0)
        self.assertGreater(ch.budget.tokens, 0)
        self.assertGreater(ch.budget.wall_time_s, 0)
        self.assertGreater(ch.digest_every, 0)


if __name__ == "__main__":
    unittest.main()
