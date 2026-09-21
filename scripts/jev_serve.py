#!/usr/bin/env python3
"""Local server for the Jev console. Python stdlib only - no pip install, no build step.

    python3 scripts/jev_serve.py
    -> http://localhost:8770

Why a server at all, in a repo that has proudly avoided one: the TypeSafe API key
must never reach the browser. Every Jev call is made from this process; the page
only ever talks to localhost. The 2.6 MB graph also stays here, and the browser is
sent only the slice it is displaying.

Bind address is 127.0.0.1 deliberately. This serves an authenticated API key to
anything that can reach it, so it is not something to expose on a network.
"""
import argparse
import json
import mimetypes
import re
import sys
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from jev_brain import (KG, audit_edges, audit_questions, compare, diagnose, quiz_verdict,
                       route, route_batch)
from datetime import date

import jev_guide
import learner
import path as pathmod
from jev_client import JevClient, JevError

ROOT = Path(__file__).resolve().parent.parent
WEB_DIR = ROOT / "web"

# Guard rails on anything that fans out into many paid API calls, so a typo in a
# request body cannot spend the whole quota.
MAX_BATCH_PROMPTS = 40
MAX_AUDIT_ROWS = 60

# Every student-scoped route takes this straight from the URL and hands it to
# learner.student_dir(), which joins it onto a filesystem path. An allowlist, not
# a denylist: blocking ".." is not enough, since encodings, backslashes (this
# repo runs on Windows) and absolute paths all reach the filesystem the same way
# and none of them contain two literal dots. Every id in this repo looks like
# "S001", so this costs nothing legitimate.
STUDENT_ID_RE = re.compile(r"[A-Za-z0-9_-]+")


def _valid_student_id(student_id: str) -> bool:
    # `_`-prefixed folders (e.g. _template) are not students - list_students()
    # already skips them on read (see child.name.startswith("_") below), so the
    # write path must refuse them too. Without this, POST /api/student/_template/
    # session rewrites the checked-in blank template that every real student is
    # migrated from.
    if student_id.startswith("_"):
        return False
    return bool(STUDENT_ID_RE.fullmatch(student_id))


def list_students(root=learner.ROOT):
    """Every student folder that has a profile, newest activity first."""
    folder = root / "students"
    if not folder.is_dir():
        return []
    out = []
    for child in sorted(folder.iterdir()):
        if not child.is_dir() or child.name.startswith("_"):
            continue
        profile_path = child / "profile.json"
        if not profile_path.is_file():
            continue
        try:
            profile = learner.read_json(profile_path)
        except (ValueError, OSError):
            continue
        out.append({
            "id": profile.get("id", child.name),
            "grade": profile.get("grade"),
            "session_count": profile.get("session_count", 0),
            "last_session": profile.get("last_session"),
            "mastered": len([
                node for node in (profile.get("mastery") or {})
                if pathmod.is_mastered(profile, node)
            ]),
        })
    out.sort(key=lambda s: (s["last_session"] or "", s["id"]), reverse=True)
    return out


def _mastery_delta(before: dict, after: dict) -> list:
    """Which nodes moved, and by how much. What the UI shows after a sitting."""
    old = before.get("mastery") or {}
    new = after.get("mastery") or {}
    rows = []
    for node_id, record in new.items():
        was = (old.get(node_id) or {}).get("score")
        now = record.get("score")
        if was is None or abs(now - was) > 1e-9:
            rows.append({
                "node": node_id, "from": was, "to": now,
                "newly_mastered": (pathmod.is_mastered(after, node_id)
                                   and not pathmod.is_mastered(before, node_id)),
            })
    rows.sort(key=lambda r: -abs((r["to"] or 0) - (r["from"] or 0)))
    return rows


class Console(BaseHTTPRequestHandler):
    server_version = "SubjectKG-Jev"
    kg: KG = None
    client: JevClient = None

    # -- plumbing ---------------------------------------------------------------

    def log_message(self, fmt, *args):
        sys.stderr.write(f"  {self.address_string()} {fmt % args}\n")

    def _send(self, status: int, body: bytes, content_type: str):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, payload, status: int = 200):
        self._send(status, json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                   "application/json; charset=utf-8")

    def _body(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        return json.loads(self.rfile.read(length).decode("utf-8"))

    # -- static -----------------------------------------------------------------

    def _serve_file(self, relative: str):
        target = (WEB_DIR / relative).resolve()
        # Refuse anything that escapes web/ - this server reads from disk on request.
        if not str(target).startswith(str(WEB_DIR.resolve())) or not target.is_file():
            self._send(404, b"not found", "text/plain")
            return
        guessed = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        if guessed.startswith("text/") or guessed.endswith(("javascript", "json")):
            guessed += "; charset=utf-8"
        self._send(200, target.read_bytes(), guessed)

    # -- routes -----------------------------------------------------------------

    def do_GET(self):
        path = self.path.split("?")[0]
        try:
            if path in ("/", "/index.html"):
                return self._serve_file("index.html")

            if path == "/api/graph":
                # The index the browser needs to populate pickers: ids and labels only.
                return self._json({
                    "strands": self.kg.strands,
                    "strand_summaries": self.kg.strand_summaries,
                    "counts": {
                        "nodes": len(self.kg.nodes),
                        "edges": len(self.kg.edges()),
                        "questions": len(self.kg.all_questions()),
                        "misconceptions": sum(len(n.get("misconceptions", []))
                                              for n in self.kg.nodes),
                        "micros": sum(len(n.get("micros", [])) for n in self.kg.nodes),
                    },
                    "nodes": [
                        {"id": n["id"], "title": n["title"], "grade": n["grade"],
                         "strand": n["strand"],
                         "questions": len(n.get("questions", [])),
                         "misconceptions": len(n.get("misconceptions", []))}
                        for n in self.kg.nodes
                    ],
                })

            if path.startswith("/api/node/"):
                node_id = path[len("/api/node/"):]
                node = self.kg.by_id.get(node_id)
                if not node:
                    return self._json({"error": f"no node {node_id}"}, 404)
                return self._json(self.kg.summary(node))

            if path == "/api/students":
                return self._json({"students": list_students()})

            if path.startswith("/api/student/"):
                student_id = path[len("/api/student/"):]
                if not _valid_student_id(student_id):
                    return self._json({"error": f"invalid student id {student_id!r}"}, 400)
                profile_path = learner.student_dir(student_id) / "profile.json"
                if not profile_path.is_file():
                    return self._json({"error": f"no student {student_id}"}, 404)
                profile = learner.read_json(profile_path)
                today = date.today()
                return self._json({
                    "profile": profile,
                    "mastered": sorted(pathmod.mastered_set(profile)),
                    "ready": pathmod.ready_nodes(self.kg, profile),
                    "locked": pathmod.locked_nodes(self.kg, profile),
                    "reviews_due": pathmod.reviews_due(profile, today),
                    "review_debt": pathmod.review_debt(profile, today),
                    "debt_limit": pathmod.REVIEW_DEBT_LIMIT,
                    "misconceptions": [
                        {"node": node_id, "node_title": self.kg.by_id[node_id]["title"],
                         **entry, "stage": learner.display_stage(entry, today)}
                        for node_id, record in (profile.get("mastery") or {}).items()
                        if node_id in self.kg.by_id
                        for entry in record.get("misconceptions_active", [])
                        if entry.get("repair_stage") != "repaired"
                    ],
                })

            if path == "/api/stats":
                return self._json(dict(self.client.stats, model=self.client.model))

            return self._serve_file(path.lstrip("/"))
        except Exception as exc:  # noqa: BLE001
            traceback.print_exc()
            return self._json({"error": str(exc)}, 500)

    def do_POST(self):
        path = self.path.split("?")[0]
        try:
            payload = self._body()

            if path == "/api/route":
                utterance = (payload.get("utterance") or "").strip()
                if not utterance:
                    return self._json({"error": "utterance is required"}, 400)
                return self._json(route(self.client, self.kg, utterance))

            if path == "/api/route/batch":
                prompts = [p.strip() for p in payload.get("utterances", []) if p and p.strip()]
                if not prompts:
                    return self._json({"error": "at least one prompt is required"}, 400)
                if len(prompts) > MAX_BATCH_PROMPTS:
                    return self._json(
                        {"error": f"{len(prompts)} prompts exceeds the {MAX_BATCH_PROMPTS} "
                                  f"limit for one run"}, 400)
                return self._json({"results": route_batch(self.client, self.kg, prompts)})

            if path == "/api/diagnose":
                node_id = payload.get("node_id")
                if not node_id or node_id not in self.kg.by_id:
                    return self._json({"error": f"unknown node {node_id!r}"}, 400)
                answer = (payload.get("answer") or "").strip()
                if not answer:
                    return self._json({"error": "the student's answer is required"}, 400)
                return self._json(diagnose(
                    self.client, self.kg, node_id,
                    payload.get("prompt", ""), payload.get("correct", ""), answer,
                ))

            if path == "/api/quiz/verdict":
                node_id = payload.get("node_id")
                if not node_id or node_id not in self.kg.by_id:
                    return self._json({"error": f"unknown node {node_id!r}"}, 400)
                transcript = payload.get("transcript") or []
                if not transcript:
                    return self._json({"error": "answer at least one question first"}, 400)
                return self._json(quiz_verdict(self.client, self.kg, node_id, transcript))

            if path.startswith("/api/student/") and path.endswith("/session"):
                student_id = path[len("/api/student/"):-len("/session")]
                if not _valid_student_id(student_id):
                    return self._json({"error": f"invalid student id {student_id!r}"}, 400)
                log = payload.get("log")
                if not isinstance(log, dict) or "date" not in log:
                    return self._json({"error": "log with a date is required"}, 400)
                # Checked before anything touches disk: append_session mkdirs and
                # writes the ledger entry unconditionally, so a typo'd id (ZZTEST,
                # say) would otherwise leave an orphan sessions/ folder behind even
                # though the request is ultimately rejected. /next, /gaps and GET
                # /student/<id> all 404 here first; this endpoint must too.
                profile_path = learner.student_dir(student_id) / "profile.json"
                if not profile_path.is_file():
                    return self._json({"error": f"no student {student_id}"}, 404)
                previous = learner.read_json(profile_path)
                written = learner.append_session(student_id, log)
                profile, warnings = learner.reproject(student_id, self.kg, date.today())
                learner.save_profile(student_id, profile)
                return self._json({
                    "written": written.name, "warnings": warnings, "profile": profile,
                    "mastery_delta": _mastery_delta(previous, profile),
                })

            if path.startswith("/api/student/") and path.endswith("/next"):
                student_id = path[len("/api/student/"):-len("/next")]
                if not _valid_student_id(student_id):
                    return self._json({"error": f"invalid student id {student_id!r}"}, 400)
                profile_path = learner.student_dir(student_id) / "profile.json"
                if not profile_path.is_file():
                    return self._json({"error": f"no student {student_id}"}, 404)
                return self._json(jev_guide.decide_next(
                    self.client, self.kg, learner.read_json(profile_path), date.today()
                ))

            if path.startswith("/api/student/") and path.endswith("/gaps"):
                student_id = path[len("/api/student/"):-len("/gaps")]
                if not _valid_student_id(student_id):
                    return self._json({"error": f"invalid student id {student_id!r}"}, 400)
                target = payload.get("target")
                if not target or target not in self.kg.by_id:
                    return self._json({"error": f"unknown target {target!r}"}, 400)
                profile_path = learner.student_dir(student_id) / "profile.json"
                if not profile_path.is_file():
                    return self._json({"error": f"no student {student_id}"}, 404)
                return self._json(jev_guide.rank_gaps(
                    self.client, self.kg, learner.read_json(profile_path), target
                ))

            if path.startswith("/api/student/") and path.endswith("/reproject"):
                student_id = path[len("/api/student/"):-len("/reproject")]
                if not _valid_student_id(student_id):
                    return self._json({"error": f"invalid student id {student_id!r}"}, 400)
                stored_path = learner.student_dir(student_id) / "profile.json"
                if not stored_path.is_file():
                    return self._json({"error": f"no student {student_id}"}, 404)
                stored = learner.read_json(stored_path)
                profile, warnings = learner.reproject(student_id, self.kg, date.today())
                learner.save_profile(student_id, profile)
                return self._json({
                    "profile": profile, "warnings": warnings,
                    "mastery_delta": _mastery_delta(stored, profile),
                })

            if path == "/api/audit/edges":
                limit = min(int(payload.get("limit", 20)), MAX_AUDIT_ROWS)
                return self._json(audit_edges(self.client, self.kg, limit,
                                              int(payload.get("offset", 0))))

            if path == "/api/audit/questions":
                limit = min(int(payload.get("limit", 20)), MAX_AUDIT_ROWS)
                return self._json(audit_questions(self.client, self.kg, limit,
                                                  int(payload.get("offset", 0))))

            if path == "/api/compare":
                prompts = [p.strip() for p in payload.get("utterances", []) if p and p.strip()]
                if not prompts:
                    return self._json({"error": "at least one prompt is required"}, 400)
                if len(prompts) > MAX_BATCH_PROMPTS:
                    return self._json(
                        {"error": f"{len(prompts)} prompts exceeds the {MAX_BATCH_PROMPTS} "
                                  f"limit for one run"}, 400)
                return self._json(compare(self.client, self.kg, prompts))

            return self._json({"error": f"no endpoint {path}"}, 404)

        except JevError as exc:
            # A model/transport failure is expected operationally and is the user's
            # to see in full - never swallowed into a generic 500.
            return self._json({"error": f"Jev request failed: {exc}"}, 502)
        except (ValueError, KeyError) as exc:
            return self._json({"error": f"bad request: {exc}"}, 400)
        except Exception as exc:  # noqa: BLE001
            traceback.print_exc()
            return self._json({"error": str(exc)}, 500)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--port", type=int, default=8770)
    parser.add_argument("--no-cache", action="store_true",
                        help="bypass the local answer cache (costs tokens; use when "
                             "measuring real latency)")
    args = parser.parse_args()

    try:
        Console.client = JevClient(cache=not args.no_cache)
    except JevError as exc:
        print(f"\n{exc}\n", file=sys.stderr)
        return 1

    print("Loading the knowledge graph...", file=sys.stderr)
    Console.kg = KG()
    print(f"  {len(Console.kg.nodes)} nodes, {len(Console.kg.edges())} edges, "
          f"{len(Console.kg.all_questions())} diagnostic questions", file=sys.stderr)

    server = ThreadingHTTPServer(("127.0.0.1", args.port), Console)
    print(f"\n  Jev console -> http://localhost:{args.port}"
          f"\n  model: {Console.client.model}   cache: "
          f"{'off' if args.no_cache else 'on'}\n  Ctrl-C to stop\n", file=sys.stderr)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
