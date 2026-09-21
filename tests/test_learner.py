"""Unit tests for scripts/learner.py. Stdlib unittest - no pytest, no network."""
import io
import json
import shutil
import sys
import tempfile
import threading
import unittest
from datetime import date
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


class TestRepairStaging(unittest.TestCase):
    """rules/40 §5: retest after 2 days, then 7; only then repaired."""

    def setUp(self):
        self.day0 = date(2026, 3, 1)

    def test_first_sighting_is_observed(self):
        entry = learner.observe_misconception(None, "m2", self.day0)
        self.assertEqual(entry["id"], "m2")
        self.assertEqual(entry["repair_stage"], "observed")
        self.assertEqual(entry["retests_passed"], 0)
        self.assertIsNone(entry["retest_after"])
        self.assertEqual(entry["first_seen"], "2026-03-01")

    def test_correct_answer_confronts_it_and_schedules_two_days_out(self):
        entry = learner.observe_misconception(None, "m2", self.day0)
        entry = learner.pass_retest(entry, self.day0)
        self.assertEqual(entry["repair_stage"], "confronted")
        self.assertEqual(entry["retest_after"], "2026-03-03")
        self.assertEqual(entry["retests_passed"], 0)

    def test_retest_too_early_does_not_count(self):
        entry = learner.pass_retest(
            learner.observe_misconception(None, "m2", self.day0), self.day0
        )
        entry = learner.pass_retest(entry, date(2026, 3, 2))  # one day early
        self.assertEqual(entry["retests_passed"], 0)
        self.assertEqual(entry["retest_after"], "2026-03-03")

    def test_two_retests_on_time_repair_it(self):
        entry = learner.pass_retest(
            learner.observe_misconception(None, "m2", self.day0), self.day0
        )
        entry = learner.pass_retest(entry, date(2026, 3, 3))
        self.assertEqual(entry["retests_passed"], 1)
        self.assertEqual(entry["retest_after"], "2026-03-10")
        self.assertEqual(entry["repair_stage"], "confronted")

        entry = learner.pass_retest(entry, date(2026, 3, 10))
        self.assertEqual(entry["repair_stage"], "repaired")
        self.assertIsNone(entry["retest_after"])

    def test_wrong_answer_resets_all_the_way_to_observed(self):
        entry = learner.pass_retest(
            learner.observe_misconception(None, "m2", self.day0), self.day0
        )
        entry = learner.pass_retest(entry, date(2026, 3, 3))
        entry = learner.observe_misconception(entry, "m2", date(2026, 3, 5))
        self.assertEqual(entry["repair_stage"], "observed")
        self.assertEqual(entry["retests_passed"], 0)
        self.assertIsNone(entry["retest_after"])
        self.assertEqual(entry["first_seen"], "2026-03-01", "first_seen must not move")

    def test_display_stage_derives_retest_due_from_the_date(self):
        entry = learner.pass_retest(
            learner.observe_misconception(None, "m2", self.day0), self.day0
        )
        self.assertEqual(learner.display_stage(entry, date(2026, 3, 2)), "confronted")
        self.assertEqual(learner.display_stage(entry, date(2026, 3, 3)), "retest-due")
        self.assertEqual(learner.display_stage(entry, date(2026, 3, 9)), "retest-due")


class TestReviewLadder(unittest.TestCase):
    """rules/10: 1, 3, 7, 16, 35 then monthly. rules/40 §7 scales by strand."""

    def test_the_ladder_rungs(self):
        self.assertEqual([learner.interval_days(r) for r in range(5)], [1, 3, 7, 16, 35])

    def test_beyond_the_ladder_is_monthly(self):
        self.assertEqual(learner.interval_days(5), 30)
        self.assertEqual(learner.interval_days(9), 30)

    def test_retention_multiplier_scales_the_gap(self):
        self.assertEqual(learner.interval_days(2, 1.3), 9)   # 7 * 1.3 = 9.1
        self.assertEqual(learner.interval_days(2, 0.6), 4)   # 7 * 0.6 = 4.2

    def test_interval_never_drops_below_one_day(self):
        self.assertEqual(learner.interval_days(0, 0.6), 1)

    def test_first_schedule_starts_at_rung_zero(self):
        entry = learner.schedule_review(None, True, date(2026, 3, 1), 1.0)
        self.assertEqual(entry["rung"], 0)
        self.assertEqual(entry["interval_days"], 1)
        self.assertEqual(entry["next_review"], "2026-03-02")
        self.assertEqual(entry["lapses"], 0)

    def test_passing_advances_one_rung(self):
        entry = learner.schedule_review(None, True, date(2026, 3, 1), 1.0)
        entry = learner.schedule_review(entry, True, date(2026, 3, 2), 1.0)
        self.assertEqual(entry["rung"], 1)
        self.assertEqual(entry["interval_days"], 3)
        self.assertEqual(entry["next_review"], "2026-03-05")

    def test_failing_resets_to_rung_zero_and_counts_a_lapse(self):
        entry = {"rung": 3, "lapses": 1, "interval_days": 16, "next_review": "2026-03-01"}
        entry = learner.schedule_review(entry, False, date(2026, 3, 1), 1.0)
        self.assertEqual(entry["rung"], 0)
        self.assertEqual(entry["lapses"], 2)
        self.assertEqual(entry["next_review"], "2026-03-02")

    def test_strand_multiplier_applies_on_advance(self):
        entry = {"rung": 1, "lapses": 0, "interval_days": 3, "next_review": "2026-03-01"}
        entry = learner.schedule_review(entry, True, date(2026, 3, 1), 1.5)
        self.assertEqual(entry["rung"], 2)
        self.assertEqual(entry["interval_days"], 11)  # 7 * 1.5 = 10.5 -> 11


def _item(node, question, correct, misconception=None):
    entry = {"node": node, "question": question, "correct": correct}
    if misconception:
        entry["misconception_signalled"] = misconception
    return entry


def _log(date_str, items, node="g5.num.x"):
    return {
        "student": "S001", "date": date_str, "goal": f"{node}: quiz",
        "nodes_touched": [node], "events": [],
        "assessment": {"items": items},
        "profile_updates": {}, "reflection": {},
    }


# (node_id, question_id) -> difficulty, skill, and which misconceptions it targets
QINDEX = {
    ("g5.num.x", "q1"): {"difficulty": 3, "skill": "procedural", "targets": {"m1"}},
    ("g5.num.x", "q2"): {"difficulty": 3, "skill": "conceptual", "targets": {"m1"}},
    ("g5.num.x", "q3"): {"difficulty": 3, "skill": "procedural", "targets": {"m2"}},
}
STRANDS = {"g5.num.x": "num"}


class TestProjection(unittest.TestCase):
    def setUp(self):
        self.today = date(2026, 3, 20)

    def test_empty_ledger_gives_empty_mastery(self):
        profile, warnings = learner.project({}, [], QINDEX, STRANDS, self.today)
        self.assertEqual(profile["mastery"], {})
        self.assertEqual(profile["session_count"], 0)
        self.assertEqual(warnings, [])

    def test_correct_items_accumulate_mastery(self):
        logs = [_log("2026-03-01", [_item("g5.num.x", "q1", True)]),
                _log("2026-03-02", [_item("g5.num.x", "q1", True)])]
        profile, _ = learner.project({}, logs, QINDEX, STRANDS, self.today)
        node = profile["mastery"]["g5.num.x"]
        self.assertAlmostEqual(node["score"], 0.5345, places=4)
        self.assertEqual(node["evidence_count"], 2)
        self.assertEqual(node["last_seen"], "2026-03-02")

    def test_conceptual_ok_needs_a_conceptual_item_specifically(self):
        procedural_only = [_log("2026-03-01", [_item("g5.num.x", "q1", True)])]
        profile, _ = learner.project({}, procedural_only, QINDEX, STRANDS, self.today)
        self.assertFalse(profile["mastery"]["g5.num.x"]["conceptual_ok"])

        with_conceptual = procedural_only + [
            _log("2026-03-02", [_item("g5.num.x", "q2", True)])
        ]
        profile, _ = learner.project({}, with_conceptual, QINDEX, STRANDS, self.today)
        self.assertTrue(profile["mastery"]["g5.num.x"]["conceptual_ok"])

    def test_a_wrong_conceptual_item_does_not_set_the_flag(self):
        logs = [_log("2026-03-01", [_item("g5.num.x", "q2", False)])]
        profile, _ = learner.project({}, logs, QINDEX, STRANDS, self.today)
        self.assertFalse(profile["mastery"]["g5.num.x"]["conceptual_ok"])

    def test_signalled_misconception_is_recorded(self):
        logs = [_log("2026-03-01", [_item("g5.num.x", "q1", False, "m1")])]
        profile, _ = learner.project({}, logs, QINDEX, STRANDS, self.today)
        active = profile["mastery"]["g5.num.x"]["misconceptions_active"]
        self.assertEqual([m["id"] for m in active], ["m1"])
        self.assertEqual(active[0]["repair_stage"], "observed")

    def test_correct_answer_on_a_targeting_item_advances_the_repair(self):
        logs = [_log("2026-03-01", [_item("g5.num.x", "q1", False, "m1")]),
                _log("2026-03-02", [_item("g5.num.x", "q1", True)])]
        profile, _ = learner.project({}, logs, QINDEX, STRANDS, self.today)
        active = profile["mastery"]["g5.num.x"]["misconceptions_active"]
        self.assertEqual(active[0]["repair_stage"], "confronted")

    def test_correct_answer_on_an_unrelated_item_does_not(self):
        logs = [_log("2026-03-01", [_item("g5.num.x", "q1", False, "m1")]),
                _log("2026-03-02", [_item("g5.num.x", "q3", True)])]  # q3 targets m2
        profile, _ = learner.project({}, logs, QINDEX, STRANDS, self.today)
        active = profile["mastery"]["g5.num.x"]["misconceptions_active"]
        self.assertEqual(active[0]["repair_stage"], "observed")

    def test_review_is_scheduled_once_the_node_is_mastered(self):
        items = [_item("g5.num.x", "q2", True)] * 6
        logs = [_log("2026-03-01", items)]
        profile, _ = learner.project({}, logs, QINDEX, STRANDS, self.today)
        self.assertGreaterEqual(profile["mastery"]["g5.num.x"]["score"], 0.8)
        self.assertIn("g5.num.x", profile["spaced_repetition"])

    def test_unmastered_node_is_not_scheduled(self):
        logs = [_log("2026-03-01", [_item("g5.num.x", "q1", True)])]
        profile, _ = learner.project({}, logs, QINDEX, STRANDS, self.today)
        self.assertNotIn("g5.num.x", profile["spaced_repetition"])

    def test_session_count_and_last_session_follow_the_ledger(self):
        logs = [_log("2026-03-01", [_item("g5.num.x", "q1", True)]),
                _log("2026-03-04", [_item("g5.num.x", "q1", True)])]
        profile, _ = learner.project({}, logs, QINDEX, STRANDS, self.today)
        self.assertEqual(profile["session_count"], 2)
        self.assertEqual(profile["last_session"], "2026-03-04")

    def test_seed_fields_are_carried_through_untouched(self):
        seed = {
            "id": "S001", "created": "2026-01-01", "grade": 9,
            "interests": ["cricket"], "goals": {"target": "boards"},
            "language": {"explanation": "english"},
            "strategy_stats": {"visual:num": {"tried": 3, "worked": 2}},
            "retention": {"num": 1.2},
        }
        logs = [_log("2026-03-01", [_item("g5.num.x", "q1", True)])]
        profile, _ = learner.project(seed, logs, QINDEX, STRANDS, self.today)
        self.assertEqual(profile["interests"], ["cricket"])
        self.assertEqual(profile["goals"]["target"], "boards")
        self.assertEqual(profile["strategy_stats"]["visual:num"]["worked"], 2)
        self.assertEqual(profile["grade"], 9)

    def test_retention_multiplier_is_applied_to_scheduling(self):
        seed = {"id": "S001", "created": "2026-01-01", "grade": 9,
                "retention": {"num": 1.5}}
        logs = [_log("2026-03-01", [_item("g5.num.x", "q2", True)] * 6)]
        profile, _ = learner.project(seed, logs, QINDEX, STRANDS, self.today)
        self.assertEqual(profile["spaced_repetition"]["g5.num.x"]["interval_days"], 2)

    def test_unknown_question_is_warned_and_skipped(self):
        logs = [_log("2026-03-01", [_item("g5.num.x", "q99", True)])]
        profile, warnings = learner.project({}, logs, QINDEX, STRANDS, self.today)
        self.assertEqual(profile["mastery"], {})
        self.assertEqual(len(warnings), 1)
        self.assertIn("q99", warnings[0])

    def test_validate_accepts_a_complete_profile(self):
        profile = {
            "id": "S001", "created": "2026-01-01", "grade": 5,
            "mastery": {"g5.num.x": {"score": 0.5, "evidence_count": 2,
                                     "last_seen": "2026-03-01"}},
            "strategy_stats": {}, "behavior": {},
            "spaced_repetition": {"g5.num.x": {"next_review": "2026-03-05",
                                               "interval_days": 3}},
        }
        self.assertEqual(learner.validate_profile(profile), [])

    def test_validate_names_every_missing_required_root_key(self):
        problems = learner.validate_profile({"id": "S001"})
        joined = " ".join(problems)
        for key in ("created", "grade", "mastery", "strategy_stats", "behavior",
                    "spaced_repetition"):
            self.assertIn(key, joined)

    def test_validate_catches_a_mastery_score_out_of_range(self):
        profile = {
            "id": "S001", "created": "2026-01-01", "grade": 5,
            "mastery": {"g5.num.x": {"score": 1.4, "evidence_count": 1,
                                     "last_seen": "2026-03-01"}},
            "strategy_stats": {}, "behavior": {}, "spaced_repetition": {},
        }
        problems = learner.validate_profile(profile)
        self.assertTrue(any("score" in p and "g5.num.x" in p for p in problems))

    def test_validate_catches_an_incomplete_review_entry(self):
        profile = {
            "id": "S001", "created": "2026-01-01", "grade": 5, "mastery": {},
            "strategy_stats": {}, "behavior": {},
            "spaced_repetition": {"g5.num.x": {"interval_days": 3}},
        }
        problems = learner.validate_profile(profile)
        self.assertTrue(any("next_review" in p for p in problems))

    def test_projection_is_deterministic(self):
        logs = [_log("2026-03-01", [_item("g5.num.x", "q1", True)]),
                _log("2026-03-02", [_item("g5.num.x", "q2", False, "m1")])]
        first, _ = learner.project({}, logs, QINDEX, STRANDS, self.today)
        second, _ = learner.project({}, logs, QINDEX, STRANDS, self.today)
        self.assertEqual(json.dumps(first, sort_keys=True),
                         json.dumps(second, sort_keys=True))

    def _seed_with_history(self):
        """A migrated student: frozen pre-ledger state under `seed`, derived state on top
        (as save_profile would have written it back)."""
        frozen = {
            "session_count": 6,
            "last_session": "2026-03-01",
            "mastery": {
                "g5.num.x": {"score": 0.91, "evidence_count": 12,
                             "last_seen": "2026-03-01", "conceptual_ok": True,
                             "misconceptions_active": []},
                "g9.other": {"score": 0.85, "evidence_count": 8,
                             "last_seen": "2026-02-20", "conceptual_ok": True,
                             "misconceptions_active": []},
            },
            "spaced_repetition": {
                "g9.other": {"next_review": "2026-04-01", "interval_days": 16,
                             "lapses": 0, "rung": 3},
            },
        }
        return {
            "id": "S001", "created": "2026-01-01", "grade": 5,
            "projection_from": "2026-03-02",
            "seed": frozen,
            "session_count": frozen["session_count"],
            "last_session": frozen["last_session"],
            "mastery": json.loads(json.dumps(frozen["mastery"])),
            "spaced_repetition": json.loads(json.dumps(frozen["spaced_repetition"])),
            "strategy_stats": {}, "behavior": {},
        }

    def test_seeded_profile_keeps_mastery_the_ledger_cannot_explain(self):
        seed = self._seed_with_history()
        profile, _ = learner.project(seed, [], QINDEX, STRANDS, self.today)
        self.assertIn("g9.other", profile["mastery"],
                      "a seeded node with no log must survive the projection")
        self.assertEqual(profile["mastery"]["g9.other"]["score"], 0.85)
        self.assertEqual(profile["spaced_repetition"]["g9.other"]["rung"], 3)

    def test_seeded_profile_still_applies_logs_after_the_marker(self):
        seed = self._seed_with_history()
        frozen_score = seed["seed"]["mastery"]["g5.num.x"]["score"]
        logs = [_log("2026-03-05", [_item("g5.num.x", "q1", False, "m1")])]
        profile, _ = learner.project(seed, logs, QINDEX, STRANDS, self.today)
        score = profile["mastery"]["g5.num.x"]["score"]
        self.assertLess(score, frozen_score,
                        "a wrong answer after the marker must move the score down")
        # A record starting fresh (the unseeded path) would fall straight to the 0.05
        # floor; only starting from the frozen 0.91 lands above 0.5 after one miss.
        self.assertGreater(score, 0.5,
                           "the wrong answer must be applied on top of the frozen "
                           "score, not on top of a freshly-created record")
        self.assertEqual(
            [m["id"] for m in profile["mastery"]["g5.num.x"]["misconceptions_active"]],
            ["m1"])

    def test_seeded_profile_ignores_logs_before_the_marker(self):
        seed = self._seed_with_history()
        # Dated before projection_from: already baked into the seed, must not double-count.
        logs = [_log("2026-02-15", [_item("g5.num.x", "q1", False, "m1")])]
        profile, _ = learner.project(seed, logs, QINDEX, STRANDS, self.today)
        self.assertEqual(profile["mastery"]["g5.num.x"]["score"], 0.91)
        self.assertEqual(profile["mastery"]["g5.num.x"]["misconceptions_active"], [])

    def test_seeded_session_count_adds_to_the_seeds_count(self):
        seed = self._seed_with_history()
        logs = [_log("2026-03-05", [_item("g5.num.x", "q1", True)]),
                _log("2026-03-06", [_item("g5.num.x", "q1", True)])]
        profile, _ = learner.project(seed, logs, QINDEX, STRANDS, self.today)
        self.assertEqual(profile["session_count"], 8, "6 seeded + 2 replayed")
        self.assertEqual(profile["last_session"], "2026-03-06")

    def test_seeded_profile_with_no_new_logs_keeps_its_last_session(self):
        seed = self._seed_with_history()
        profile, _ = learner.project(seed, [], QINDEX, STRANDS, self.today)
        self.assertEqual(profile["session_count"], 6)
        self.assertEqual(profile["last_session"], "2026-03-01")

    def test_unseeded_projection_is_unchanged(self):
        """The default path must not shift: no marker means pure replay."""
        logs = [_log("2026-03-01", [_item("g5.num.x", "q1", True)])]
        profile, _ = learner.project({}, logs, QINDEX, STRANDS, self.today)
        self.assertEqual(profile["session_count"], 1)
        self.assertAlmostEqual(profile["mastery"]["g5.num.x"]["score"], 0.335, places=3)

    def test_project_does_not_mutate_the_seed(self):
        seed = self._seed_with_history()
        before = json.dumps(seed, sort_keys=True)
        logs = [_log("2026-03-05", [_item("g5.num.x", "q1", False, "m1")])]
        learner.project(seed, logs, QINDEX, STRANDS, self.today)
        self.assertEqual(json.dumps(seed, sort_keys=True), before)

    def test_seeded_minimal_mastery_record_survives_a_replay(self):
        """The schema requires only score/evidence_count/last_seen on a mastery record;
        conceptual_ok and misconceptions_active are optional and must not be assumed
        present just because a record came from a seed rather than the replay loop."""
        frozen = {
            "session_count": 1,
            "last_session": "2026-03-01",
            "mastery": {
                "g5.num.x": {"score": 0.6, "evidence_count": 3, "last_seen": "2026-03-01"},
            },
            "spaced_repetition": {},
        }
        seed = {
            "id": "S001", "created": "2026-01-01", "grade": 5,
            "projection_from": "2026-03-02",
            "seed": frozen,
            "session_count": frozen["session_count"],
            "last_session": frozen["last_session"],
            "mastery": json.loads(json.dumps(frozen["mastery"])),
            "spaced_repetition": {}, "strategy_stats": {}, "behavior": {},
        }
        logs = [_log("2026-03-05", [_item("g5.num.x", "q1", False, "m1")])]
        profile, _ = learner.project(seed, logs, QINDEX, STRANDS, self.today)
        score = profile["mastery"]["g5.num.x"]["score"]
        self.assertLess(score, 0.6)
        # A freshly-created record (the unseeded path) would fall to the 0.05 floor;
        # this must land above that, proving it started from the frozen 0.6.
        self.assertGreater(score, 0.05)
        self.assertEqual(
            [m["id"] for m in profile["mastery"]["g5.num.x"]["misconceptions_active"]],
            ["m1"])

    def test_seeded_student_is_not_frozen_by_a_later_session(self):
        """A migrated student must keep improving: a post-marker session on a seeded
        node moves its score, other seeded nodes stay put, and the count advances."""
        seed = self._seed_with_history()
        logs = [_log("2026-03-05", [_item("g5.num.x", "q1", False, "m1")])]
        profile, _ = learner.project(seed, logs, QINDEX, STRANDS, self.today)
        self.assertNotEqual(profile["mastery"]["g5.num.x"]["score"], 0.91)
        self.assertIn("g9.other", profile["mastery"])
        self.assertEqual(profile["session_count"], 7)

    def _frozen_seed_profile(self):
        """A migrated student: frozen pre-ledger state under `seed`, derived state on top."""
        frozen = {
            "mastery": {
                "g5.num.x": {"score": 0.91, "evidence_count": 12,
                             "last_seen": "2026-03-01", "conceptual_ok": True},
            },
            "spaced_repetition": {},
            "session_count": 6,
            "last_session": "2026-03-01",
        }
        return {
            "id": "S001", "created": "2026-01-01", "grade": 5,
            "projection_from": "2026-03-02",
            "seed": frozen,
            # The derived top level, as save_profile would have written it.
            "mastery": json.loads(json.dumps(frozen["mastery"])),
            "spaced_repetition": {}, "session_count": 6,
            "last_session": "2026-03-01",
            "strategy_stats": {}, "behavior": {},
        }

    def test_repeated_projections_do_not_double_count(self):
        """The bug this task exists to kill.

        Simulates what POST /session does: project, save the result over the profile,
        then project again with one more log. The second projection must not re-apply
        the first log, however many times the cycle runs.
        """
        profile = self._frozen_seed_profile()
        logs = []
        for day in ("2026-03-05", "2026-03-08", "2026-03-11"):
            logs.append(_log(day, [_item("g5.num.x", "q1", False, "m1")]))
            # Feed the SAVED profile back in, exactly as reproject() would.
            profile, _ = learner.project(profile, logs, QINDEX, STRANDS, self.today)

        once, _ = learner.project(
            self._frozen_seed_profile(), logs, QINDEX, STRANDS, self.today
        )
        self.assertAlmostEqual(profile["mastery"]["g5.num.x"]["score"],
                               once["mastery"]["g5.num.x"]["score"], places=6,
                               msg="three save-and-reproject cycles must equal one "
                                   "projection of the same three logs")
        self.assertEqual(profile["session_count"], once["session_count"])
        self.assertEqual(profile["session_count"], 9, "6 frozen + 3 replayed")

    def test_the_frozen_seed_survives_every_projection_unchanged(self):
        profile = self._frozen_seed_profile()
        original = json.dumps(profile["seed"], sort_keys=True)
        logs = [_log("2026-03-05", [_item("g5.num.x", "q1", False, "m1")])]
        for _ in range(3):
            profile, _ = learner.project(profile, logs, QINDEX, STRANDS, self.today)
            self.assertEqual(json.dumps(profile["seed"], sort_keys=True), original,
                             "the frozen seed must be re-emitted byte-identical")

    def test_frozen_seed_still_applies_post_marker_logs(self):
        profile = self._frozen_seed_profile()
        logs = [_log("2026-03-05", [_item("g5.num.x", "q1", False, "m1")])]
        result, _ = learner.project(profile, logs, QINDEX, STRANDS, self.today)
        self.assertLess(result["mastery"]["g5.num.x"]["score"], 0.91)
        self.assertEqual(
            [m["id"] for m in result["mastery"]["g5.num.x"]["misconceptions_active"]],
            ["m1"])

    def test_frozen_seed_still_ignores_pre_marker_logs(self):
        profile = self._frozen_seed_profile()
        logs = [_log("2026-02-15", [_item("g5.num.x", "q1", False, "m1")])]
        result, _ = learner.project(profile, logs, QINDEX, STRANDS, self.today)
        self.assertEqual(result["mastery"]["g5.num.x"]["score"], 0.91)
        self.assertEqual(result["session_count"], 6)


class TestAppendSession(unittest.TestCase):
    """A log's `date` is spliced straight into a filename, so an unvalidated value
    is a path-traversal write primitive, not just a malformed log (see
    scripts/jev_serve.py's student-scoped POST routes, the caller of this)."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_a_valid_date_is_accepted(self):
        target = learner.append_session("S001", {"date": "2026-09-21"}, root=self.tmp)
        self.assertTrue(target.is_file())
        self.assertEqual(target.name, "2026-09-21-01.json")

    def test_two_sittings_same_day_get_sequential_suffixes(self):
        first = learner.append_session("S001", {"date": "2026-09-21"}, root=self.tmp)
        second = learner.append_session("S001", {"date": "2026-09-21"}, root=self.tmp)
        self.assertEqual(first.name, "2026-09-21-01.json")
        self.assertEqual(second.name, "2026-09-21-02.json")

    def test_a_traversal_date_is_rejected_and_nothing_is_created(self):
        with self.assertRaises(ValueError):
            learner.append_session("S001", {"date": "../../evil"}, root=self.tmp)
        self.assertFalse((self.tmp / "students").exists(),
                         "an invalid date must not create so much as the sessions folder")

    def test_a_non_string_date_is_rejected(self):
        with self.assertRaises(ValueError):
            learner.append_session("S001", {"date": 20260921}, root=self.tmp)

    def test_a_malformed_date_string_is_rejected(self):
        with self.assertRaises(ValueError):
            learner.append_session("S001", {"date": "21-09-2026"}, root=self.tmp)


class TestAppendSessionConcurrency(unittest.TestCase):
    """jev_serve.py is a ThreadingHTTPServer: two /session POSTs for the same
    student can call append_session concurrently. The old implementation chose
    the next free index with a `.exists()` loop and then wrote through
    atomic_write_json (os.replace - an unconditional overwrite). Two threads
    racing for the same "next free" index before either has written end with
    one silently overwriting the other's log - the one thing the ledger's
    append-only design says can never happen. This proves the fix (exclusive
    os.O_CREAT | os.O_EXCL create, retry on collision) holds under real
    concurrency, not just in a single-threaded happy path."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_concurrent_appends_all_survive_with_distinct_filenames(self):
        n = 40
        # Pre-create the session folder so every thread's student_dir() call
        # resolves the same, already-existing path. Path.resolve() on Windows can
        # briefly disagree with itself while students/<id>/ is *first* being
        # created concurrently (a real but separate race, outside what this test
        # targets) - this isolates the test to the filename-allocation race in
        # append_session itself, which is what fix 1 is about.
        (self.tmp / "students" / "S001" / "sessions").mkdir(parents=True)
        barrier = threading.Barrier(n)
        results = [None] * n
        errors = []

        def worker(i):
            try:
                barrier.wait(timeout=10)  # force every thread to race at once
                results[i] = learner.append_session(
                    "S001", {"date": "2026-09-21", "marker": i}, root=self.tmp
                )
            except Exception as exc:  # noqa: BLE001
                errors.append((i, exc))

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(n)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=15)

        self.assertEqual(errors, [], f"append_session raised under concurrency: {errors}")

        names = [p.name for p in results]
        self.assertEqual(
            len(names), len(set(names)),
            "two sittings landed on the same filename - a race in index selection",
        )

        sessions_dir = self.tmp / "students" / "S001" / "sessions"
        on_disk = sorted(sessions_dir.glob("*.json"))
        self.assertEqual(
            len(on_disk), n,
            f"expected {n} distinct session logs, found {len(on_disk)} - a "
            "concurrent write clobbered another",
        )

        # The stronger check: every sitting's own content survived, not merely
        # that n files exist. A race that overwrites one thread's file with
        # another's (same content shape, different `marker`) would pass a
        # filename-count check but fail this one.
        markers = sorted(learner.read_json(p)["marker"] for p in on_disk)
        self.assertEqual(markers, list(range(n)))


class TestStudentDirContainment(unittest.TestCase):
    """Defence in depth alongside the server's id allowlist (jev_serve.py): even a
    caller that skips that check cannot walk student_dir() out of students/."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_an_ordinary_id_resolves_inside_students(self):
        folder = learner.student_dir("S001", root=self.tmp)
        self.assertEqual(folder, (self.tmp / "students" / "S001").resolve())

    def test_a_dot_dot_id_is_rejected(self):
        with self.assertRaises(ValueError):
            learner.student_dir("../../evil", root=self.tmp)

    def test_a_multi_level_dot_dot_id_is_rejected(self):
        with self.assertRaises(ValueError):
            learner.student_dir("../../../../evil", root=self.tmp)


class TestSessionLogSchema(unittest.TestCase):
    """No validator anywhere in the server enforces session-log.schema.json - not
    even the endpoint that writes one. That is what let buildSessionLog() in
    web/console.js ship with an incomplete `reflection` block: nothing failed, it
    just wrote logs the schema does not actually describe. Sessions are an
    append-only ledger, so a log written non-conforming stays that way forever;
    this test is the only thing that would have caught it. Required fields are
    read from the schema file itself, not hard-coded, so the test keeps up if the
    schema changes."""

    @classmethod
    def setUpClass(cls):
        schema_path = (Path(__file__).resolve().parent.parent
                        / "harness" / "schemas" / "session-log.schema.json")
        cls.schema = json.loads(schema_path.read_text(encoding="utf-8"))

    @staticmethod
    def _representative_log():
        # Mirrors the shape web/console.js's buildSessionLog() produces for a
        # finished quiz sitting where Jev named a persistent misconception.
        return {
            "student": "S001",
            "date": "2026-09-21",
            "goal": "g5.num.fractions-add-sub: quiz",
            "nodes_touched": ["g5.num.fractions-add-sub"],
            "reviews_done": [],
            "events": [],
            "assessment": {
                "items": [{
                    "node": "g5.num.fractions-add-sub",
                    "question": "q1",
                    "correct": False,
                    "answer_text": "you just add the tops and bottoms straight across",
                    "misconception_signalled": "m1",
                    "jev": {
                        "is_correct": 0.21, "misconception": "m1",
                        "confident": 0.8, "model": "jev-latest",
                    },
                }],
            },
            "profile_updates": {},
            "reflection": {
                "goal_met": False,
                "evidence": 'Jev read the sitting as "Not yet" (0.0/2).',
                "what_worked": [],
                "what_failed": ["m1: adds tops and bottoms separately"],
                "next_time": "reteach differently — teach this again a different way",
            },
        }

    def test_top_level_required_fields_are_present(self):
        log = self._representative_log()
        for key in self.schema["required"]:
            self.assertIn(key, log, f"missing top-level required field {key!r}")

    def test_assessment_item_required_fields_are_present(self):
        log = self._representative_log()
        required = self.schema["properties"]["assessment"]["properties"]["items"]["items"]["required"]
        for item in log["assessment"]["items"]:
            for key in required:
                self.assertIn(key, item, f"assessment item missing required field {key!r}")

    def test_reflection_required_fields_are_present(self):
        log = self._representative_log()
        required = self.schema["properties"]["reflection"]["required"]
        for key in required:
            self.assertIn(key, log["reflection"], f"reflection missing required field {key!r}")


if __name__ == "__main__":
    unittest.main()
