"""Unit tests for scripts/jev_serve.py's request-validation helpers.

Stdlib unittest only, no server started and no API key needed: importing the
module is side-effect free (JevClient and the knowledge graph are only built in
main()), so the student-id allowlist can be exercised directly.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import jev_serve


class TestValidStudentId(unittest.TestCase):
    """Regression coverage for the path-traversal fix: every student-scoped
    endpoint checks the URL segment against this allowlist before it ever
    reaches learner.student_dir(). An allowlist, not a denylist, because
    blocking known-bad characters misses encodings, backslashes, and absolute
    paths that reach the filesystem exactly as effectively."""

    def test_ordinary_ids_are_valid(self):
        for student_id in ("S001", "S999", "S_1-a"):
            self.assertTrue(jev_serve._valid_student_id(student_id))

    def test_underscore_prefixed_ids_are_rejected(self):
        """_template (and any _-prefixed folder) is not a student - list_students()
        already skips these on read, and the write path must refuse them too, or
        POST /api/student/_template/session rewrites the checked-in blank template."""
        for student_id in ("_template", "_anything"):
            self.assertFalse(jev_serve._valid_student_id(student_id))

    def test_dot_dot_traversal_is_rejected(self):
        self.assertFalse(jev_serve._valid_student_id("../../students/S001"))

    def test_backslash_traversal_is_rejected(self):
        self.assertFalse(jev_serve._valid_student_id("..\\..\\students\\S001"))

    def test_percent_encoded_traversal_is_rejected(self):
        self.assertFalse(jev_serve._valid_student_id("%2e%2e%2f%2e%2e%2fetc"))

    def test_absolute_paths_are_rejected(self):
        self.assertFalse(jev_serve._valid_student_id("C:/Windows/System32"))
        self.assertFalse(jev_serve._valid_student_id("/etc/passwd"))

    def test_empty_id_is_rejected(self):
        self.assertFalse(jev_serve._valid_student_id(""))


if __name__ == "__main__":
    unittest.main()
