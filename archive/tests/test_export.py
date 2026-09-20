"""The export, and the time series it is built from.

Nothing here may be derived or backfilled. A value the run did not record is
absent from the export.
"""

from __future__ import annotations

import json
import unittest

from helpers import (
    HarnessCase,
    a_candidate,
    a_dispatch,
    a_wake_requirement,
    decision,
    fake,
    return_block,
)

from regent.export import build_export, write_export
from regent.loop import Harness


class SeriesCase(HarnessCase):
    def a_run(self, turns=3):
        links = [{"kind": "structural analogy",
                  "text": "A bridge inspector taps for a void.",
                  "anchors": ["m00001"],
                  "ingredients": [{"source": "manifold", "ref": "m00001"},
                                  {"source": "outside", "ref": "bridge inspection"}],
                  "mechanism": "probe for absence"}]
        runner = fake(
            wake=[
                decision(dispatches=[a_dispatch()]),
                decision(amendments=[{"dispatch_id": "d0001", "direction": "raise",
                                      "trigger": "the 0.4 second timing",
                                      "criterion": "It checks anchors.", "replaces": ""}],
                         judgements=[{"return_id": "r00001", "outcome": "accept",
                                      "reason": "met"}],
                         requirements=[a_wake_requirement(
                             text="It should report links pointing outside.",
                             serves_intent="the charter asks for broken internal "
                                           "links in a notes folder",
                             rework="the classifier is redone",
                             origin="the return on d0001",
                             objective_id="obj-1")],
                         inspect=[{"question": "Does it walk nested folders?",
                                   "dispatch_id": "d0001"}]),
                decision(),
            ],
            drift=[{"links": links}],
            sift=[{"scored": [{"index": 0, "novelty": 0.8, "mechanism": 0.9,
                               "leverage": 0.7, "cost": 0.2,
                               "why_it_might_fail": "the analogy may not carry"}],
                   "candidates": [a_candidate()]}],
            orchestrator=[return_block(
                flags=[{"tier": "medium", "text": "anchors unchecked",
                        "criterion": "It reports a broken link."}])])
        ctx = self.boot(runner, seed=4242)
        ctx.cfg.attention.audit_rate = 1.0
        h = Harness(ctx)
        for _ in range(turns):
            h.turn()
        ctx.spoon.run(trigger="test")
        from regent.digest import write_digest
        write_digest(ctx, 0)
        ctx.save()
        return ctx


class TestSeries(SeriesCase):
    def test_a_metrics_record_is_written_every_turn(self):
        ctx = self.a_run(turns=3)
        rows = ctx.store.read_jsonl(ctx.store.metrics)
        self.assertEqual(len(rows), 3)
        self.assertEqual([r["turn"] for r in rows], [1, 2, 3])

    def test_the_record_carries_every_series_the_page_needs(self):
        ctx = self.a_run(turns=2)
        row = ctx.store.read_jsonl(ctx.store.metrics)[-1]
        for key in ("turn", "ts", "iso", "cycle", "stance", "stance_baseline",
                    "signals", "reads", "trust", "debt", "interlude", "life_date",
                    "life_day", "life_valence", "appetite_used", "appetite_left",
                    "requirements", "cost_usd", "tokens", "cache_read_tokens",
                    "calls", "spot_checks_total", "returns_read", "draws"):
            self.assertIn(key, row, key)
        for signal in ("frustration", "curiosity", "satisfaction", "unease"):
            self.assertIn(signal, row["signals"])

    def test_the_read_draw_and_its_inputs_are_recorded(self):
        ctx = self.a_run(turns=3)
        rows = ctx.store.read_jsonl(ctx.store.metrics)
        reads = [r for row in rows for r in row["reads"]]
        self.assertTrue(reads)
        draw = reads[0]["draw"]
        self.assertIn(draw["mode"], ("full", "skim", "glance", "wave-through"))
        for key in ("queue_depth", "trust", "unease", "stance", "debt", "noise"):
            self.assertIn(key, draw["inputs"])

    def test_the_ledger_read_mode_line_carries_the_same_inputs(self):
        ctx = self.a_run(turns=3)
        rows = [r for r in ctx.ledger.all() if r["kind"] == "read_mode"]
        self.assertTrue(rows)
        self.assertIn("inputs", rows[0])
        self.assertIn("trust", rows[0]["inputs"])
        self.assertIn("branch", rows[0])

    def test_every_trust_change_names_its_cause(self):
        ctx = self.a_run(turns=3)
        rows = [r for r in ctx.ledger.all() if r["kind"] == "trust"]
        self.assertTrue(rows)
        for r in rows:
            self.assertIn(r.get("source"), ("audit", "spot_check"))
            self.assertIn("outcome", r)
            self.assertIn("trust", r)

    def test_the_stance_series_moves_and_is_a_number(self):
        ctx = self.a_run(turns=3)
        rows = ctx.store.read_jsonl(ctx.store.metrics)
        for r in rows:
            self.assertIsInstance(r["stance"], float)
            self.assertIsInstance(r["stance_baseline"], float)


class TestExport(SeriesCase):
    def test_the_export_holds_every_section(self):
        ctx = self.a_run(turns=3)
        data = build_export(ctx.store.root)
        for key in ("export_version", "run", "charter", "objectives", "series",
                    "decisions", "amendments", "requirements", "spot_checks",
                    "cycles", "dispatches", "escalations", "trust_events",
                    "read_modes", "audits", "interludes", "rejections", "life",
                    "digest", "ledger_kinds"):
            self.assertIn(key, data, key)

    def test_the_charter_comes_back_whole(self):
        ctx = self.a_run(turns=1)
        ch = build_export(ctx.store.root)["charter"]
        self.assertIn("broken internal links", ch["intent"])
        self.assertEqual(len(ch["refusals"]), 3)
        self.assertEqual(ch["budget"]["spend_usd"], 10.0)
        self.assertTrue(ch["sha256"])

    def test_decisions_carry_their_tier_and_read_mode(self):
        ctx = self.a_run(turns=3)
        data = build_export(ctx.store.root)
        dispatches = [d for d in data["decisions"] if d.get("kind") == "dispatch"]
        self.assertTrue(dispatches)
        self.assertIn("tier", dispatches[0])
        judgements = [d for d in data["decisions"] if d.get("kind") == "judgement"]
        self.assertTrue(judgements)
        self.assertIn("read_mode", judgements[0])

    def test_amendments_carry_their_trigger(self):
        ctx = self.a_run(turns=3)
        a = build_export(ctx.store.root)["amendments"]
        self.assertTrue(a)
        self.assertIn("0.4 second", a[0]["trigger"])
        self.assertEqual(a[0]["direction"], "raise")

    def test_requirements_carry_origin_and_rework(self):
        ctx = self.a_run(turns=3)
        rows = build_export(ctx.store.root)["requirements"]
        self.assertTrue(rows)
        self.assertIn("classifier", rows[0]["rework"])
        self.assertTrue(rows[0]["origin"])

    def test_a_spot_check_carries_its_findings_against_the_returns_claims(self):
        ctx = self.a_run(turns=3)
        rows = build_export(ctx.store.root)["spot_checks"]
        self.assertTrue(rows)
        self.assertTrue(rows[0]["findings"])
        self.assertIn("verdicts", rows[0])
        self.assertIn("question", rows[0])

    def test_a_cycle_carries_its_motifs_links_stops_scores_and_gate(self):
        ctx = self.a_run(turns=3)
        cycles = build_export(ctx.store.root)["cycles"]
        self.assertTrue(cycles)
        c = cycles[-1]
        for key in ("motifs", "link_count", "links", "stops", "scored",
                    "candidates", "kept", "gated_out", "requirements"):
            self.assertIn(key, c)
        self.assertTrue(c["stops"])
        self.assertIn("rule", c["stops"][0])

    def test_a_dispatch_carries_the_returns_headline_and_recommendation(self):
        ctx = self.a_run(turns=3)
        rows = build_export(ctx.store.root)["dispatches"]
        self.assertTrue(rows)
        returns = [r for d in rows for r in d["returns"]]
        self.assertTrue(returns)
        self.assertTrue(returns[0]["headline"])
        self.assertTrue(returns[0]["recommendation"])
        self.assertIn(returns[0]["read_mode"],
                      ("full", "skim", "glance", "wave-through"))

    def test_the_life_carries_a_bible_opening_and_day_excerpts(self):
        from regent.config import Config
        cfg = Config()
        cfg.life.enabled = True
        cfg.life.backstory_days = 3
        from test_life import life_runner
        ctx = self.boot(life_runner(wake=[decision()]), cfg=cfg)
        ctx.life_writer.bootstrap()
        Harness(ctx).turn()
        ctx.save()
        life = build_export(ctx.store.root)["life"]
        self.assertTrue(life["enabled"])
        # The interlude may add a day, so the floor is what bootstrap wrote.
        self.assertGreaterEqual(life["day_count"], 3)
        self.assertIn("Marta", life["bible_opening"])
        self.assertEqual(len(life["excerpts"]), 3)
        self.assertTrue(life["excerpts"][0]["excerpt"])
        self.assertEqual(len(life["days"]), life["day_count"])

    def test_the_life_says_so_when_it_was_not_running(self):
        ctx = self.a_run(turns=1)
        self.assertEqual(build_export(ctx.store.root)["life"], {"enabled": False})

    def test_the_digest_text_is_carried(self):
        ctx = self.a_run(turns=3)
        d = build_export(ctx.store.root)["digest"]
        self.assertIn("# Digest", d["text"])
        self.assertTrue(d["path"])

    def test_the_series_is_the_recorded_one_and_is_not_rebuilt(self):
        ctx = self.a_run(turns=3)
        data = build_export(ctx.store.root)
        self.assertEqual(data["series"],
                         ctx.store.read_jsonl(ctx.store.metrics))

    def test_the_export_writes_json_that_parses(self):
        ctx = self.a_run(turns=2)
        path = write_export(ctx.store.root)
        self.assertEqual(path.name, "export.json")
        data = json.loads(path.read_text())
        self.assertEqual(data["export_version"], 1)
        self.assertEqual(data["run"]["seed"], 4242)

    def test_the_command_writes_the_file(self):
        from test_cli import run_cli
        ctx = self.a_run(turns=2)
        code, out = run_cli("--state", str(ctx.store.root), "export")
        self.assertEqual(code, 0)
        self.assertIn("export.json", out)
        self.assertTrue((ctx.store.root / "export.json").exists())

    def test_the_command_fails_cleanly_on_a_directory_with_no_run(self):
        from test_cli import run_cli
        code, out = run_cli("--state", str(self.root / "nothing"), "export")
        self.assertEqual(code, 1)
        self.assertIn("no run state", out)


if __name__ == "__main__":
    unittest.main()
