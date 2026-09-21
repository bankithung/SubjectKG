"""Tests for the parts of jev_guide.py that do not call the model."""
import sys
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
# Also this directory, so the FakeKG fixture can be shared with test_path rather
# than duplicated. Under `unittest discover -s tests -t .` these modules are
# imported as tests.test_*, so a bare `from test_path import` would not resolve.
sys.path.insert(0, str(Path(__file__).resolve().parent))

import jev_guide
from test_path import FakeKG, profile_with


class TestCandidateAssembly(unittest.TestCase):
    def test_frontier_nodes_become_candidates(self):
        candidates, forced = jev_guide.assemble_candidates(
            FakeKG(), profile_with(), date(2026, 3, 1)
        )
        self.assertFalse(forced)
        self.assertEqual({c["id"] for c in candidates}, {"a", "c"})
        self.assertTrue(all(c["kind"] == "frontier" for c in candidates))

    def test_due_reviews_are_included(self):
        profile = profile_with(a=(0.9, True))
        profile["spaced_repetition"] = {
            "a": {"next_review": "2026-02-01", "interval_days": 3, "lapses": 0}
        }
        candidates, _ = jev_guide.assemble_candidates(
            FakeKG(), profile, date(2026, 3, 1)
        )
        review = next(c for c in candidates if c["id"] == "a")
        self.assertEqual(review["kind"], "due_review")

    def test_debt_over_the_limit_forces_reviews_only(self):
        profile = profile_with(a=(0.9, True))
        profile["spaced_repetition"] = {
            f"n{i}": {"next_review": "2026-02-01", "interval_days": 3, "lapses": 0}
            for i in range(jev_guide.pathmod.REVIEW_DEBT_LIMIT + 1)
        }
        candidates, forced = jev_guide.assemble_candidates(
            FakeKG(), profile, date(2026, 3, 1)
        )
        self.assertTrue(forced)
        self.assertTrue(all(c["kind"] == "due_review" for c in candidates))

    def test_active_misconception_becomes_a_retest_candidate(self):
        profile = profile_with(a=(0.5, False))
        profile["mastery"]["a"]["misconceptions_active"] = [{
            "id": "m1", "first_seen": "2026-02-01", "repair_stage": "confronted",
            "retest_after": "2026-02-20", "retests_passed": 0,
        }]
        candidates, _ = jev_guide.assemble_candidates(
            FakeKG(), profile, date(2026, 3, 1)
        )
        retest = next(c for c in candidates if c["kind"] == "misconception_retest")
        self.assertEqual(retest["id"], "a")
        self.assertIn("m1", retest["why"])

    def test_candidate_list_is_capped(self):
        kg = FakeKG()
        kg.nodes = [{"id": f"n{i}", "title": f"N{i}", "grade": 1, "strand": "num",
                     "prerequisites": []} for i in range(40)]
        kg.by_id = {n["id"]: n for n in kg.nodes}
        candidates, _ = jev_guide.assemble_candidates(
            kg, profile_with(), date(2026, 3, 1), limit=12
        )
        self.assertEqual(len(candidates), 12)


class TestGapBatching(unittest.TestCase):
    def test_gaps_are_chunked_for_batched_requests(self):
        self.assertEqual(jev_guide._chunk([1, 2, 3, 4, 5], 2), [[1, 2], [3, 4], [5]])

    def test_empty_input_gives_no_chunks(self):
        self.assertEqual(jev_guide._chunk([], 3), [])


if __name__ == "__main__":
    unittest.main()
