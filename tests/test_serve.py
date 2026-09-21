"""Unit tests for scripts/jev_serve.py's request-validation helpers.

Stdlib unittest only, no API key needed: importing the module is side-effect
free (JevClient and the knowledge graph are only built in main()), so the
student-id allowlist can be exercised directly. The endpoint-guard tests below
do start a real ThreadingHTTPServer, but against a temp directory - never the
real students/ folder - by monkeypatching learner.student_dir's default root.
"""
import http.client
import json
import shutil
import sys
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import jev_serve
import learner


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


class _FakeKG:
    """Enough of KG's surface for reproject()'s question index / strand lookup
    to run over an empty graph - these tests never reach that code (they exist
    to prove the 404 guard fires first), but Console.kg must be something."""
    nodes = []
    by_id = {}


class TestSessionAndReprojectGuardEndpoints(unittest.TestCase):
    """Regression for the ZZTEST bug: POST /api/student/ZZTEST/session used to
    400 (the projection rejects a profile with no required fields) but only
    after append_session had already mkdir'd sessions/ and written a log -
    leaving an orphan ledger behind for an id that was never a student. /next,
    /gaps and GET /student/<id> all 404 on a missing profile.json before doing
    anything; /session and /reproject must too.

    Runs a real server so the fix is proven at the HTTP layer, not just by
    reading the source - but against a temp root, never the checked-in
    students/ folder, via monkeypatching learner.student_dir's default.
    """

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        cls._orig_student_dir = learner.student_dir
        learner.student_dir = (
            lambda student_id, root=cls.tmp: cls._orig_student_dir(student_id, root)
        )
        jev_serve.Console.kg = _FakeKG()
        jev_serve.Console.client = None
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), jev_serve.Console)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=5)
        learner.student_dir = cls._orig_student_dir
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def _post(self, path, body):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        try:
            conn.request("POST", path, body=json.dumps(body),
                        headers={"Content-Type": "application/json"})
            resp = conn.getresponse()
            return resp.status, json.loads(resp.read().decode("utf-8"))
        finally:
            conn.close()

    def test_session_404s_on_nonexistent_student_and_creates_nothing(self):
        status, data = self._post(
            "/api/student/ZZTEST/session", {"log": {"date": "2026-09-21"}}
        )
        self.assertEqual(status, 404)
        self.assertIn("error", data)
        self.assertFalse((self.tmp / "students" / "ZZTEST").exists(),
                         "a rejected id must leave nothing on disk, not even sessions/")

    def test_reproject_404s_on_nonexistent_student_and_creates_nothing(self):
        status, data = self._post("/api/student/ZZTEST2/reproject", {})
        self.assertEqual(status, 404)
        self.assertIn("error", data)
        self.assertFalse((self.tmp / "students" / "ZZTEST2").exists())


if __name__ == "__main__":
    unittest.main()
