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


if __name__ == "__main__":
    unittest.main()
