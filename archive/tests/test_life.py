"""The life: bible, backstory, journal, and the read split in context assembly."""

from __future__ import annotations

import unittest

from helpers import ROOT, HarnessCase, decision, fake

from regent import lifetables
from regent.config import Config
from regent.loop import Harness, bootstrap
from regent.rng import Rng
from regent.runner import ModelResponse
from regent.spoon import catch
from regent.store import Store


def life_runner(days: int = 3, **over):
    """A runner that writes a distinguishable day each time it is asked."""
    counter = {"n": 0}

    def a_day(req):
        counter["n"] += 1
        n = counter["n"]
        return ModelResponse(role="life_day", structured={
            "entry": f"Day number {n}. " + ("The frost held until ten. " * 40),
            "valence": -0.6 if n % 3 == 0 else 0.3,
            "keywords": [f"kw{n}", "frost"],
            "thread_notes": [f"thread from day {n}"] if n == 2 else [],
        })

    def a_week(req):
        import re as _re
        m = _re.search(r"Write (\d+) consecutive days", req.prompt)
        n = int(m.group(1)) if m else 1
        entries = []
        for _ in range(n):
            counter["n"] += 1
            k = counter["n"]
            entries.append({
                "entry": f"Day number {k}. " + ("The frost held until ten. " * 8),
                "valence": -0.6 if k % 3 == 0 else 0.3,
                "keywords": [f"kw{k}", "frost"],
                "thread_notes": [f"thread from day {k}"] if k == 2 else [],
            })
        return ModelResponse(role="life_week", structured={"entries": entries})

    r = fake(**over)
    r.scripts["life_day"] = [a_day]
    r.scripts["life_week"] = [a_week]
    r.scripts["life_bible"] = [{
        "bible": "# Marta Vasi\n\nMarta is 44, a bridge inspector in Hull.",
        "threads": ["whether to sell the house", "the roof, and what it will cost"],
    }]
    return r


class LifeCase(HarnessCase):
    def setUp(self):
        super().setUp()
        self.cfg = Config()
        self.cfg.life.enabled = True
        self.cfg.life.backstory_days = 3
        self.cfg.life.bible_words = 200


class TestTables(unittest.TestCase):
    def test_the_harness_rolls_the_day_and_the_model_does_not_choose(self):
        plan = lifetables.roll_day(Rng(seed=3), ["a thread"])
        self.assertIn(len(plan["events"]), (2, 3))
        self.assertTrue(plan["weather"])
        self.assertTrue(plan["place"])
        self.assertTrue(plan["object"])
        self.assertIn(plan["mood_seed"], [m[0] for m in lifetables.MOOD_SEEDS])

    def test_the_same_seed_rolls_the_same_events(self):
        r1 = Rng(seed=11)
        a = [lifetables.roll_day(r1, ["t"]) for _ in range(5)]
        r2 = Rng(seed=11)
        b = [lifetables.roll_day(r2, ["t"]) for _ in range(5)]
        self.assertEqual(a, b)
        # A run of five must not be five of the same day.
        self.assertGreater(len({d["weather"] for d in a}), 1)

    def test_different_seeds_roll_different_days(self):
        a = lifetables.roll_day(Rng(seed=1), [])
        b = lifetables.roll_day(Rng(seed=2), [])
        self.assertNotEqual(a, b)

    def test_the_bible_seed_carries_a_person_who_does_not_work_in_software(self):
        seed = lifetables.roll_bible_seed(Rng(seed=5))
        for key in ("name", "age", "city", "occupation", "household", "upheaval"):
            self.assertTrue(seed[key], key)
        self.assertEqual(len(seed["relationships"]), 3)
        self.assertEqual(len(seed["open_threads"]), 3)
        joined = " ".join(lifetables.OCCUPATIONS).lower()
        for word in ("software", "developer", "programmer", "engineer"):
            self.assertNotIn(word, joined)

    def test_the_tables_are_big_enough_not_to_repeat_immediately(self):
        self.assertGreaterEqual(len(lifetables.EVENTS), 40)
        self.assertGreaterEqual(len(lifetables.PLACES), 15)
        self.assertGreaterEqual(len(lifetables.OBJECTS), 15)


class TestBootstrap(LifeCase):
    def test_bootstrap_writes_the_bible_and_the_backstory(self):
        ctx = self.boot(life_runner(), cfg=self.cfg)
        written = ctx.life_writer.bootstrap()
        self.assertEqual(written, 3)
        self.assertTrue(ctx.life.bible_path.exists())
        self.assertIn("Marta", ctx.life.bible())
        idx = ctx.life.index()
        self.assertEqual(idx.day_count, 3)
        self.assertTrue(idx.bootstrapped)
        self.assertEqual(len(list((ctx.life.journal).glob("day-*.md"))), 3)
        self.assertGreater(ctx.life.total_words(), 100)

    def test_bootstrap_runs_once_and_not_again(self):
        ctx = self.boot(life_runner(), cfg=self.cfg)
        ctx.life_writer.bootstrap()
        self.assertEqual(ctx.life_writer.bootstrap(), 0)
        self.assertEqual(ctx.life.index().day_count, 3)

    def test_the_bible_threads_are_carried_into_the_index(self):
        ctx = self.boot(life_runner(), cfg=self.cfg)
        ctx.life_writer.write_bible()
        self.assertIn("whether to sell the house", ctx.life.index().threads)

    def test_a_failed_bible_call_still_leaves_a_bible(self):
        runner = life_runner()
        runner.scripts["life_bible"] = [ModelResponse(role="life_bible", is_error=True)]
        ctx = self.boot(runner, cfg=self.cfg)
        ctx.life_writer.write_bible()
        self.assertTrue(ctx.life.bible_path.exists())
        self.assertIn("Open threads", ctx.life.bible())

    def test_the_run_bootstraps_the_life_before_the_first_turn(self):
        ctx = self.boot(life_runner(wake=[decision()]), cfg=self.cfg)
        Harness(ctx).run(max_turns=1)
        self.assertGreaterEqual(ctx.life.index().day_count, 3)
        boot = [r for r in ctx.ledger.all() if r["kind"] == "life"
                and r.get("state") == "bootstrapped"]
        self.assertEqual(len(boot), 1)


class TestJournal(LifeCase):
    def test_a_day_appends_one_entry_and_advances_the_date(self):
        ctx = self.boot(life_runner(), cfg=self.cfg)
        ctx.life_writer.write_bible()
        before = ctx.life.index()
        ctx.life_writer.write_day()
        after = ctx.life.index()
        self.assertEqual(after.day_count, before.day_count + 1)
        ctx.life_writer.write_day()
        third = ctx.life.index()
        self.assertEqual(third.day_count, 2)
        self.assertNotEqual(third.days[0]["date"], third.days[1]["date"])
        self.assertLess(third.days[0]["date"], third.days[1]["date"])

    def test_the_journal_is_append_only(self):
        ctx = self.boot(life_runner(), cfg=self.cfg)
        ctx.life_writer.write_bible()
        ctx.life_writer.write_day()
        first = (ctx.life.journal / "day-0001.md").read_text()
        ctx.life_writer.write_day()
        ctx.life_writer.write_day()
        self.assertEqual((ctx.life.journal / "day-0001.md").read_text(), first)
        self.assertEqual(len(list(ctx.life.journal.glob("day-*.md"))), 3)

    def test_each_day_enters_the_manifold_with_a_life_id(self):
        ctx = self.boot(life_runner(), cfg=self.cfg)
        ctx.life_writer.write_bible()
        ctx.life_writer.write_day()
        life = [e for e in ctx.manifold.warm() if e.texture == "life"]
        self.assertEqual(len(life), 1)
        self.assertTrue(life[0].id.startswith("L"))
        self.assertTrue(life[0].synthetic)
        self.assertIn("date", life[0].meta)

    def test_a_project_element_keeps_an_m_id(self):
        ctx = self.boot(life_runner(), cfg=self.cfg)
        el = ctx.manifold.write("friction", "the build took 40 minutes")
        self.assertTrue(el.id.startswith("m"))

    def test_thread_notes_are_carried_forward(self):
        ctx = self.boot(life_runner(), cfg=self.cfg)
        ctx.life_writer.write_bible()
        ctx.life_writer.write_day()
        ctx.life_writer.write_day()
        self.assertIn("thread from day 2", ctx.life.index().threads)

    def test_the_day_prompt_carries_the_rolled_plan_and_the_signals(self):
        ctx = self.boot(life_runner(), cfg=self.cfg)
        ctx.state.signals.frustration = 0.9
        ctx.life_writer.write_bible()
        ctx.life_writer.write_day()
        prompt = self.runner.calls_for("life_day")[0].prompt
        self.assertIn("frustration 0.90", prompt)
        self.assertIn("weather", prompt)
        self.assertIn("mood_seed", prompt)

    def test_the_valence_moves_the_stance_baseline_by_a_bounded_amount(self):
        ctx = self.boot(life_runner(), cfg=self.cfg)
        ctx.life_writer.write_bible()
        before = ctx.state.stance.baseline
        ctx.life_writer.write_day()
        moved = ctx.state.stance.baseline
        self.assertNotEqual(moved, before)
        self.assertLessEqual(abs(moved - before), self.cfg.life.valence_baseline_step)

    def test_a_backstory_day_does_not_move_the_stance(self):
        ctx = self.boot(life_runner(), cfg=self.cfg)
        ctx.life_writer.write_bible()
        before = ctx.state.stance.baseline
        ctx.life_writer.write_day(backstory=True)
        self.assertEqual(ctx.state.stance.baseline, before)

    def test_the_same_seed_writes_the_same_life(self):
        def once():
            import tempfile
            from pathlib import Path
            with tempfile.TemporaryDirectory() as d:
                cp = Path(d) / "charter.md"
                cp.write_text(self.charter_path.read_text())
                cfg = Config()
                cfg.life.enabled = True
                cfg.life.backstory_days = 3
                ctx = bootstrap(Store(Path(d) / "run"), cfg, str(cp), str(self.project),
                                seed=808, prompts_dir=ROOT / "prompts",
                                plugin_dir=ROOT / "plugin",
                                runners={"claude": life_runner()},
                                notifier=self.notifier)
                ctx.life_writer.bootstrap()
                return [c.prompt for c in ctx.runners["claude"].calls_for("life_day")]
        self.assertEqual(once(), once())


class TestReadSplit(LifeCase):
    def boot_with_days(self, n=4):
        cfg = self.cfg
        cfg.life.backstory_days = n
        ctx = self.boot(life_runner(), cfg=cfg)
        ctx.life_writer.bootstrap()
        return ctx

    def test_drift_gets_the_bible_and_the_window_oldest_first(self):
        ctx = self.boot_with_days(4)
        text = ctx.life.for_drift("sonnet")
        self.assertIn("# The bible", text)
        self.assertIn("Marta", text)
        # Oldest first, so the journal is a stable prefix the cache can carry.
        self.assertLess(text.index("Day number 1."), text.index("Day number 4."))

    def test_the_window_cuts_the_oldest_days_when_it_is_small(self):
        ctx = self.boot_with_days(4)
        ctx.cfg.life.drift_window_words = 40
        text = ctx.life.for_drift("sonnet")
        self.assertIn("Day number 4.", text)
        self.assertNotIn("Day number 1.", text)

    def test_a_window_can_be_sized_per_model(self):
        ctx = self.boot_with_days(4)
        ctx.cfg.life.window_by_model = {"haiku": 40}
        self.assertNotIn("Day number 1.", ctx.life.for_drift("haiku"))
        self.assertIn("Day number 1.", ctx.life.for_drift("sonnet"))

    def test_judgement_gets_the_last_two_days_and_the_mood(self):
        ctx = self.boot_with_days(4)
        text = ctx.life.for_judgement()
        self.assertIn("Day number 4.", text)
        self.assertIn("Day number 3.", text)
        self.assertNotIn("Day number 1.", text)
        self.assertIn("valence", ctx.life.mood_line())

    def test_wake_receives_the_last_two_days_and_never_the_whole_journal(self):
        ctx = self.boot_with_days(4)
        Harness(ctx).wake([])
        prompt = self.runner.calls_for("wake")[0].prompt
        self.assertIn("Day number 4.", prompt)
        self.assertNotIn("Day number 1.", prompt)

    def test_sift_never_sees_the_life(self):
        """Sift reads the holding file and nothing else."""
        ctx = self.boot_with_days(4)
        runner = self.runner
        runner.scripts["drift"] = [{"links": [
            {"kind": "seed", "text": "a link", "anchors": ["m00001"],
             "ingredients": [], "mechanism": "m"}]}]
        ctx.manifold.write("friction", "the build took 40 minutes")
        ctx.spoon.run(trigger="test")
        sift_prompt = runner.calls_for("sift")[0].prompt
        self.assertNotIn("Day number", sift_prompt)
        self.assertNotIn("Marta", sift_prompt)
        self.assertNotIn("bible", sift_prompt.lower())

    def test_drift_is_given_the_life_and_saturate_is_too(self):
        ctx = self.boot_with_days(4)
        ctx.manifold.write("friction", "the build took 40 minutes")
        self.runner.scripts["drift"] = [{"links": []}]
        ctx.spoon.run(trigger="test")
        self.assertIn("Marta", self.runner.calls_for("drift")[0].prompt)
        self.assertIn("Marta", self.runner.calls_for("saturate")[0].prompt)


class TestLifeIsNotAnAnchor(LifeCase):
    def test_a_life_only_link_trips_the_groundedness_floor(self):
        ctx = self.boot(life_runner(), cfg=self.cfg)
        ctx.manifold.write("friction", "a real project element")
        ctx.life_writer.write_bible()
        for _ in range(3):
            ctx.life_writer.write_day()
        project = ctx.manifold.project_ids()
        life_ids = [e.id for e in ctx.manifold.warm() if e.texture == "life"]
        self.assertTrue(life_ids)
        for lid in life_ids:
            self.assertNotIn(lid, project)

        links = [{"kind": "seed", "text": f"life only {i}", "anchors": [lid],
                  "ingredients": [], "mechanism": ""}
                 for i, lid in enumerate(life_ids[:3])]
        while len(links) < 3:
            links.append(dict(links[0]))
        kept, stop = catch(links, ctx.cfg, manifold_ids=project)
        self.assertEqual(kept, [])
        self.assertEqual(stop["rule"], "groundedness floor")

    def test_a_link_with_a_project_anchor_and_a_life_anchor_is_kept(self):
        ctx = self.boot(life_runner(), cfg=self.cfg)
        el = ctx.manifold.write("friction", "a real project element")
        ctx.life_writer.write_bible()
        ctx.life_writer.write_day()
        lid = [e.id for e in ctx.manifold.warm() if e.texture == "life"][0]
        links = [{"kind": "structural analogy", "text": "a bridge and a link",
                  "anchors": [el.id, lid], "ingredients": [], "mechanism": "probe"}]
        kept, _ = catch(links, ctx.cfg, manifold_ids=ctx.manifold.project_ids())
        self.assertEqual(len(kept), 1)
        self.assertEqual(kept[0].anchors, [el.id])

    def test_the_life_stays_out_of_the_project_manifold_render(self):
        ctx = self.boot(life_runner(), cfg=self.cfg)
        ctx.manifold.write("friction", "a real project element")
        ctx.life_writer.write_bible()
        ctx.life_writer.write_day()
        ids = [e.id for e in ctx.manifold.project()]
        self.assertTrue(all(i.startswith("m") for i in ids))


class TestDayInterlude(LifeCase):
    def test_the_day_event_writes_a_journal_entry_and_advances_the_date(self):
        ctx = self.boot(life_runner(), cfg=self.cfg)
        ctx.life_writer.write_bible()
        ctx.cfg.interlude.weights = {k: (1.0 if k == "day" else 0.0)
                                     for k in ctx.cfg.interlude.weights}
        rec = Harness(ctx).interlude()
        self.assertEqual(rec["event"], "day")
        self.assertEqual(ctx.life.index().day_count, 1)
        self.assertIn("words", rec)
        self.assertTrue(rec["element_id"].startswith("L"))


if __name__ == "__main__":
    unittest.main()
