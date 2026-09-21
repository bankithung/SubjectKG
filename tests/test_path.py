"""Unit tests for scripts/path.py. Pure graph+profile logic - no network."""
import sys
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import path as pathmod


class FakeKG:
    """A four-node graph: a -> b (hard), a -> c (soft), b -> d (hard)."""

    def __init__(self):
        self.nodes = [
            {"id": "a", "title": "A", "grade": 1, "strand": "num", "prerequisites": []},
            {"id": "b", "title": "B", "grade": 2, "strand": "num", "prerequisites": [
                {"id": "a", "strength": "hard", "reason": "you cannot do B without A"}]},
            {"id": "c", "title": "C", "grade": 2, "strand": "geo", "prerequisites": [
                {"id": "a", "strength": "soft", "reason": "A makes C easier"}]},
            {"id": "d", "title": "D", "grade": 3, "strand": "num", "prerequisites": [
                {"id": "b", "strength": "hard", "reason": "D builds directly on B"}]},
        ]
        self.by_id = {n["id"]: n for n in self.nodes}


def profile_with(**mastery):
    """mastery kwargs: node=(score, conceptual_ok)"""
    return {"mastery": {
        node: {"score": s, "conceptual_ok": ok, "evidence_count": 3,
               "last_seen": "2026-03-01", "misconceptions_active": []}
        for node, (s, ok) in mastery.items()
    }, "spaced_repetition": {}}


class TestIsMastered(unittest.TestCase):
    def test_needs_both_score_and_conceptual(self):
        self.assertTrue(pathmod.is_mastered(profile_with(a=(0.85, True)), "a"))
        self.assertFalse(pathmod.is_mastered(profile_with(a=(0.85, False)), "a"))
        self.assertFalse(pathmod.is_mastered(profile_with(a=(0.79, True)), "a"))

    def test_threshold_is_inclusive(self):
        self.assertTrue(pathmod.is_mastered(profile_with(a=(0.8, True)), "a"))

    def test_unknown_node_is_not_mastered(self):
        self.assertFalse(pathmod.is_mastered(profile_with(), "zzz"))


class TestFrontier(unittest.TestCase):
    def setUp(self):
        self.kg = FakeKG()

    def test_root_nodes_are_ready_when_nothing_is_mastered(self):
        ready = {n["id"] for n in pathmod.ready_nodes(self.kg, profile_with())}
        self.assertEqual(ready, {"a", "c"}, "c has only a soft prereq, so it is ready")

    def test_hard_prereq_locks_a_node(self):
        locked = {n["id"]: n for n in pathmod.locked_nodes(self.kg, profile_with())}
        self.assertIn("b", locked)
        self.assertEqual([p["id"] for p in locked["b"]["blocked_by"]], ["a"])

    def test_locked_node_carries_the_authors_reason(self):
        locked = {n["id"]: n for n in pathmod.locked_nodes(self.kg, profile_with())}
        self.assertEqual(locked["b"]["blocked_by"][0]["reason"],
                         "you cannot do B without A")

    def test_mastering_a_prereq_unlocks_the_dependent(self):
        ready = {n["id"] for n in pathmod.ready_nodes(self.kg, profile_with(a=(0.9, True)))}
        self.assertIn("b", ready)

    def test_mastered_nodes_are_not_in_the_frontier(self):
        ready = {n["id"] for n in pathmod.ready_nodes(self.kg, profile_with(a=(0.9, True)))}
        self.assertNotIn("a", ready)

    def test_soft_prereq_is_listed_as_recommended_not_blocking(self):
        ready = {n["id"]: n for n in pathmod.ready_nodes(self.kg, profile_with())}
        self.assertEqual([p["id"] for p in ready["c"]["recommended_first"]], ["a"])


class TestReviews(unittest.TestCase):
    def test_due_reviews_are_sorted_most_overdue_first(self):
        profile = {"mastery": {}, "spaced_repetition": {
            "a": {"next_review": "2026-03-10", "interval_days": 3, "lapses": 0},
            "b": {"next_review": "2026-03-01", "interval_days": 7, "lapses": 1},
            "d": {"next_review": "2026-04-01", "interval_days": 16, "lapses": 0},
        }}
        due = pathmod.reviews_due(profile, date(2026, 3, 12))
        self.assertEqual([r["id"] for r in due], ["b", "a"])
        self.assertEqual(due[0]["days_overdue"], 11)

    def test_review_debt_counts_only_due_ones(self):
        profile = {"mastery": {}, "spaced_repetition": {
            "a": {"next_review": "2026-03-01", "interval_days": 3, "lapses": 0},
            "b": {"next_review": "2026-04-01", "interval_days": 3, "lapses": 0},
        }}
        self.assertEqual(pathmod.review_debt(profile, date(2026, 3, 12)), 1)


class TestGapPath(unittest.TestCase):
    def test_gap_path_is_topologically_ordered(self):
        gaps = [n["id"] for n in pathmod.gap_path(FakeKG(), profile_with(), "d")]
        self.assertEqual(gaps, ["a", "b", "d"])

    def test_mastered_nodes_are_excluded(self):
        gaps = [n["id"] for n in
                pathmod.gap_path(FakeKG(), profile_with(a=(0.9, True)), "d")]
        self.assertEqual(gaps, ["b", "d"])

    def test_soft_prereqs_are_not_in_the_gap_path(self):
        gaps = [n["id"] for n in pathmod.gap_path(FakeKG(), profile_with(), "c")]
        self.assertEqual(gaps, ["c"], "a is only a soft prereq of c")

    def test_fully_mastered_target_has_an_empty_path(self):
        profile = profile_with(a=(0.9, True), b=(0.9, True), d=(0.9, True))
        self.assertEqual(pathmod.gap_path(FakeKG(), profile, "d"), [])

    def test_unknown_target_returns_empty(self):
        self.assertEqual(pathmod.gap_path(FakeKG(), profile_with(), "nope"), [])


if __name__ == "__main__":
    unittest.main()
