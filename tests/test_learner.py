"""Unit tests for scripts/learner.py. Stdlib unittest - no pytest, no network."""
import io
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import learner


class TestAtomicWrite(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_writes_and_reads_utf8(self):
        target = self.tmp / "out.json"
        learner.atomic_write_json(target, {"note": "radius – ₹12.50 – en-dash"})
        self.assertEqual(
            learner.read_json(target)["note"], "radius – ₹12.50 – en-dash"
        )

    def test_leaves_no_temp_files_behind(self):
        learner.atomic_write_json(self.tmp / "out.json", {"a": 1})
        self.assertEqual([p.name for p in self.tmp.iterdir()], ["out.json"])

    def test_overwrites_existing_file(self):
        target = self.tmp / "out.json"
        learner.atomic_write_json(target, {"v": 1})
        learner.atomic_write_json(target, {"v": 2})
        self.assertEqual(learner.read_json(target)["v"], 2)


class TestReadSessions(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.sessions = self.tmp / "students" / "S001" / "sessions"
        self.sessions.mkdir(parents=True)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write(self, name, payload):
        io.open(self.sessions / name, "w", encoding="utf-8").write(
            json.dumps(payload, ensure_ascii=False)
        )

    def test_returns_logs_in_chronological_order(self):
        self._write("2026-03-02-01.json", {"date": "2026-03-02", "student": "S001"})
        self._write("2026-01-05-01.json", {"date": "2026-01-05", "student": "S001"})
        self._write("2026-01-05-02.json", {"date": "2026-01-05", "student": "S001"})
        logs, warnings = learner.read_sessions("S001", root=self.tmp)
        self.assertEqual([p["_file"] for p in logs],
                         ["2026-01-05-01.json", "2026-01-05-02.json", "2026-03-02-01.json"])
        self.assertEqual(warnings, [])

    def test_corrupt_log_is_skipped_and_warned_not_raised(self):
        self._write("2026-01-05-01.json", {"date": "2026-01-05", "student": "S001"})
        io.open(self.sessions / "2026-01-06-01.json", "w", encoding="utf-8").write("{ broken")
        logs, warnings = learner.read_sessions("S001", root=self.tmp)
        self.assertEqual(len(logs), 1)
        self.assertEqual(len(warnings), 1)
        self.assertIn("2026-01-06-01.json", warnings[0])

    def test_missing_student_returns_empty_not_error(self):
        logs, warnings = learner.read_sessions("S404", root=self.tmp)
        self.assertEqual(logs, [])
        self.assertEqual(warnings, [])


class TestItemWeight(unittest.TestCase):
    """rules/30 gives 0.8 easy / 1.0 medium / 1.2 hard; the data has difficulty 1-5."""

    def test_endpoints_match_the_stated_weights(self):
        self.assertAlmostEqual(learner.item_weight(1, "procedural"), 0.8, places=6)
        self.assertAlmostEqual(learner.item_weight(5, "procedural"), 1.2, places=6)

    def test_medium_is_one(self):
        self.assertAlmostEqual(learner.item_weight(3, "procedural"), 1.0, places=6)

    def test_conceptual_and_application_count_more(self):
        self.assertAlmostEqual(learner.item_weight(3, "conceptual"), 1.2, places=6)
        self.assertAlmostEqual(learner.item_weight(3, "application"), 1.2, places=6)

    def test_recall_weighted_same_as_procedural(self):
        self.assertAlmostEqual(
            learner.item_weight(3, "recall"), learner.item_weight(3, "procedural"), places=6
        )

    def test_unknown_difficulty_falls_back_to_medium(self):
        self.assertAlmostEqual(learner.item_weight(None, "procedural"), 1.0, places=6)


class TestMasteryCurve(unittest.TestCase):
    def test_five_correct_medium_items_cross_the_threshold(self):
        score = learner.INITIAL_MASTERY
        for _ in range(5):
            score = learner.update_mastery(score, True, 1.0)
        self.assertAlmostEqual(score, 0.8403, places=4)
        self.assertGreater(score, 0.8)

    def test_four_correct_medium_items_do_not(self):
        score = learner.INITIAL_MASTERY
        for _ in range(4):
            score = learner.update_mastery(score, True, 1.0)
        self.assertLess(score, 0.8)

    def test_wrong_answer_applies_the_stated_penalty(self):
        self.assertAlmostEqual(learner.update_mastery(0.8, False, 1.0), 0.52, places=6)

    def test_clamped_above(self):
        score = 0.99
        for _ in range(20):
            score = learner.update_mastery(score, True, 1.44)
        self.assertLessEqual(score, 0.99)

    def test_clamped_below(self):
        score = 0.05
        for _ in range(20):
            score = learner.update_mastery(score, False, 1.44)
        self.assertGreaterEqual(score, 0.05)

    def test_heavier_weight_moves_further(self):
        light = learner.update_mastery(0.5, True, 0.8)
        heavy = learner.update_mastery(0.5, True, 1.44)
        self.assertGreater(heavy, light)


if __name__ == "__main__":
    unittest.main()
