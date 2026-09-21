# Learning Journey Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make SubjectKG remember a student across sessions and decide what they should study next.

**Architecture:** Session logs are append-only truth; `profile.json` is a projection rebuilt by replaying them through the rules/30 scoring rules. Code owns all arithmetic (mastery accumulation, review ladder, prerequisite gating); Jev owns the judgments (what to do next, which gaps matter). `learner.py` and `path.py` make no model calls so they are unit-testable offline.

**Tech Stack:** Python 3.10+ stdlib only. `unittest` for tests. Vanilla HTML/CSS/JS for the UI. TypeSafe Jev via the existing `scripts/jev_client.py`.

**Spec:** `docs/superpowers/specs/2026-09-21-learning-journey-design.md`

## Global Constraints

- **Stdlib only.** No `pip install`, ever. Tests use `unittest`, not pytest. This is a hard repo rule from `CLAUDE.md`.
- **Run tests with:** `python -m unittest discover -s tests -t . -v` from the repo root.
- **All file I/O is explicitly UTF-8.** `io.open(path, encoding="utf-8")`. The default on Windows is cp1252 and it will corrupt the graph's en-dashes and ₹ signs.
- **All JSON writes are atomic**: write to a temp file in the same directory, then `os.replace`. Never write in place.
- **`MASTERED(n) ≡ score >= 0.8 AND conceptual_ok`** — defined in exactly one function, `path.is_mastered`. Never re-inline this comparison anywhere else.
- **No model calls in `learner.py` or `path.py`.** They import nothing from `jev_client`. If a task tempts you to add one, the task is wrong.
- **Never fabricate observations.** Every number in a profile must derive from a logged assessment item.
- **Commit message prefixes** follow the repo: `learner:`, `path:`, `guide:`, `web:`, `schema:`.
- **Run `python scripts/validate_kg.py` before any commit that touches `kg/` or `harness/schemas/`.** It must end with 0 errors.
- Python version floor: 3.10 (the repo's stated requirement).

---

## File Structure

| File | Responsibility |
|---|---|
| `harness/schemas/session-log.schema.json` | **Modify.** Add free-text answer + Jev judgment fields to assessment items; add `retests_passed` to the profile schema. |
| `harness/schemas/student-profile.schema.json` | **Modify.** Add `retests_passed` and `projection_from`. |
| `scripts/learner.py` | **Create.** Ledger I/O, atomic writes, mastery arithmetic, repair staging, review ladder, `project()`. No model calls. |
| `scripts/path.py` | **Create.** Pure graph+profile functions: mastered / ready / locked / reviews_due / gap_path. No model calls. |
| `scripts/jev_guide.py` | **Create.** Candidate assembly, `decide_next()`, `rank_gaps()`. The only new file that talks to Jev. |
| `scripts/jev_serve.py` | **Modify.** Six new endpoints. |
| `web/index.html` | **Modify.** Two new screens + a student selector on Quiz. |
| `web/console.js` | **Modify.** Rendering and wiring for the above. |
| `tests/test_learner.py` | **Create.** Mastery curve, repair staging, ladder, projection determinism. |
| `tests/test_path.py` | **Create.** Gating, frontier, gap paths. |
| `tests/fixtures/` | **Create.** A synthetic student with hand-written logs, plus one deliberately corrupt log. |

---

### Task 1: Extend the schemas for free-text answers

The session-log schema has no field for what a student typed, and no field for the model's judgment. Without this, every later task would have to abuse `option_chosen`. The profile schema needs `retests_passed` to count confirmed retests, and `projection_from` to mark where the ledger becomes authoritative.

**Files:**
- Modify: `harness/schemas/session-log.schema.json`
- Modify: `harness/schemas/student-profile.schema.json`

**Interfaces:**
- Consumes: nothing.
- Produces: assessment items may carry `answer_text: string` and `jev: {is_correct: number, misconception: string, misconception_confidence: number, depth: number, confident: number, model: string}`. Profile misconception entries may carry `retests_passed: integer`. Profile root may carry `projection_from: string (date)`.

- [ ] **Step 1: Add the fields to the session-log schema**

In `harness/schemas/session-log.schema.json`, inside `properties.assessment.properties.items.items.properties`, add after `option_chosen`:

```json
"answer_text": {
  "type": "string",
  "description": "What the student actually typed, verbatim. Present for free-text answers; absent when they picked a listed option."
},
"jev": {
  "type": "object",
  "description": "The model's judgment of this answer. Recorded so every derived number in profile.json is traceable to the judgment that produced it.",
  "properties": {
    "is_correct": { "type": "number", "minimum": 0, "maximum": 1 },
    "misconception": { "type": "string", "description": "Misconception id, or 'no_error' / 'other_error'." },
    "misconception_confidence": { "type": "number", "minimum": 0, "maximum": 1 },
    "depth": { "type": "number", "minimum": 0, "maximum": 2, "description": "0 slip, 1 procedural, 2 conceptual." },
    "confident": { "type": "number", "minimum": 0, "maximum": 1 },
    "model": { "type": "string", "description": "e.g. jev-1.13.0, so a later re-read knows which model version judged it." }
  }
}
```

- [ ] **Step 2: Add the fields to the profile schema**

In `harness/schemas/student-profile.schema.json`, inside the misconception entry's `properties` (sibling of `repair_stage`), add:

```json
"retests_passed": {
  "type": "integer",
  "minimum": 0,
  "description": "How many targeted retests this misconception has passed since being confronted. Two are required before repair_stage becomes 'repaired' (rules/40 §5: retest after 2 days, then 7)."
}
```

And at the profile root, as a sibling of `session_count`:

```json
"projection_from": {
  "type": ["string", "null"],
  "format": "date",
  "description": "The date from which students/<id>/sessions/ is the authoritative ledger for this profile. Fields before it were seeded from a profile written before session logging existed, and cannot be reprojected. null means the whole profile is derived from logs."
}
```

- [ ] **Step 3: Verify both schemas are still valid JSON**

Run: `python -c "import json,io; [json.load(io.open(p,encoding='utf-8')) for p in ['harness/schemas/session-log.schema.json','harness/schemas/student-profile.schema.json']]; print('both parse')"`
Expected: `both parse`

- [ ] **Step 4: Verify the existing fixtures still validate**

Run: `python scripts/validate_kg.py`
Expected: ends with `0 errors`. (These are additive optional fields, so nothing existing can break. If it reports errors, they pre-date this change — stop and report rather than "fixing" unrelated data.)

- [ ] **Step 5: Commit**

```bash
git add harness/schemas/session-log.schema.json harness/schemas/student-profile.schema.json
git commit -m "schema: record free-text answers and the model judgment behind them

Assessment items gain answer_text and a jev object, so every number the
projection derives is traceable to the judgment that produced it and to the
model version that made it. Misconception entries gain retests_passed to
count confirmed retests toward repair. Profiles gain projection_from to mark
where the session ledger becomes authoritative.

All fields are additive and optional; existing logs stay valid."
```

---

### Task 2: Atomic JSON writes and ledger reads

The foundation everything else writes through. A half-written profile is the one failure the architecture must make impossible.

**Files:**
- Create: `scripts/learner.py`
- Create: `tests/test_learner.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `atomic_write_json(path: Path, data: dict) -> None`
  - `read_json(path: Path) -> dict`
  - `read_sessions(student_id: str, root: Path = ROOT) -> tuple[list[dict], list[str]]` returning `(logs_sorted_by_date_then_filename, warnings)`
  - `student_dir(student_id: str, root: Path = ROOT) -> Path`
  - `ROOT: Path` — the repo root

- [ ] **Step 1: Write the failing test**

Create `tests/test_learner.py`:

```python
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
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m unittest discover -s tests -t . -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'learner'`

- [ ] **Step 3: Write the implementation**

Create `scripts/learner.py`:

```python
#!/usr/bin/env python3
"""Persistent learner state: the ledger of sessions, and the profile projected from it.

Session logs under students/<id>/sessions/ are append-only truth. profile.json is
derived from them by replaying every recorded observation through the scoring rules
in harness/rules/30-assessment.md. Nothing in this module calls a model: the state
arithmetic must be reproducible and testable without a network or an API key.

The one rule that governs every write here: a profile is never a source of truth, so
a failed write can always be repaired by reprojecting. The reverse must never be
possible, which is why the ledger is only ever appended to.
"""
import io
import json
import os
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def student_dir(student_id: str, root: Path = ROOT) -> Path:
    return root / "students" / student_id


def read_json(path: Path) -> dict:
    return json.loads(io.open(path, encoding="utf-8").read())


def atomic_write_json(path: Path, data: dict) -> None:
    """Write via a temp file in the same directory, then os.replace.

    Same directory matters: os.replace is only atomic within one filesystem. The
    temp file is removed on any failure so a crashed write never leaves debris
    that a later glob would pick up as a session log.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temp_name = tempfile.mkstemp(
        dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp"
    )
    try:
        with io.open(handle, "w", encoding="utf-8", closefd=True) as stream:
            json.dump(data, stream, ensure_ascii=False, indent=1)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_name, path)
    except BaseException:
        try:
            os.unlink(temp_name)
        except OSError:
            pass
        raise


def read_sessions(student_id: str, root: Path = ROOT):
    """All session logs for a student, oldest first. -> (logs, warnings).

    A log that will not parse is skipped and named in `warnings`, never raised and
    never silently dropped: one bad file must not erase a student's history, and it
    must not pass unnoticed either. Each returned log carries its filename as
    `_file` so callers can report precisely.

    Ordering is by (date field, filename). Filename is the tiebreak because two
    sittings on one day are named -01, -02 and must replay in that order.
    """
    folder = student_dir(student_id, root) / "sessions"
    if not folder.is_dir():
        return [], []

    logs, warnings = [], []
    for path in sorted(folder.glob("*.json")):
        try:
            log = read_json(path)
        except (ValueError, OSError) as exc:
            warnings.append(f"{path.name}: unreadable, skipped ({exc})")
            continue
        if not isinstance(log, dict) or "date" not in log:
            warnings.append(f"{path.name}: not a session log (no date), skipped")
            continue
        log["_file"] = path.name
        logs.append(log)

    logs.sort(key=lambda entry: (entry["date"], entry["_file"]))
    return logs, warnings
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python -m unittest discover -s tests -t . -v`
Expected: 6 tests, all PASS

- [ ] **Step 5: Commit**

```bash
git add scripts/learner.py tests/test_learner.py
git commit -m "learner: atomic JSON writes and ledger reads

Session logs are read oldest-first, tie-broken by filename so two sittings on
one day replay in order. An unparseable log is skipped and named in warnings
rather than raised: one bad file must not erase a student's history, and must
not pass unnoticed either.

Writes go through a temp file in the same directory then os.replace, so a
crash can never leave a half-written profile."
```

---

### Task 3: The mastery curve

The rules/30 formula. Pure arithmetic, deliberately kept away from the model.

**Files:**
- Modify: `scripts/learner.py`
- Modify: `tests/test_learner.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces:
  - `item_weight(difficulty: int, skill: str) -> float`
  - `update_mastery(score: float, correct: bool, weight: float) -> float`
  - `INITIAL_MASTERY: float = 0.05`
  - `CONCEPTUAL_SKILLS: frozenset = frozenset({"conceptual", "application"})`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_learner.py`, before the `if __name__` block:

```python
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
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m unittest tests.test_learner -v`
Expected: FAIL with `AttributeError: module 'learner' has no attribute 'item_weight'`

- [ ] **Step 3: Write the implementation**

Append to `scripts/learner.py`:

```python
# --------------------------------------------------------------- mastery scoring

# harness/rules/30-assessment.md:
#   correct:   m <- m + 0.30 * (1 - m) * w
#   incorrect: m <- m - 0.35 * m * w
#   clamp [0.05, 0.99]
CORRECT_GAIN = 0.30
INCORRECT_LOSS = 0.35
MASTERY_FLOOR, MASTERY_CEILING = 0.05, 0.99
INITIAL_MASTERY = MASTERY_FLOOR

CONCEPTUAL_SKILLS = frozenset({"conceptual", "application"})
CONCEPTUAL_MULTIPLIER = 1.2


def item_weight(difficulty, skill: str) -> float:
    """Evidence weight of one item.

    INTERPRETATION, flagged for a curriculum author to overrule: rules/30 names
    three weights (0.8 easy, 1.0 medium, 1.2 hard) but every question in the graph
    carries difficulty on a 1-5 scale. This interpolates linearly between the two
    stated endpoints, so difficulty 1 -> 0.8 and difficulty 5 -> 1.2, with medium
    (3) landing exactly on 1.0.

    rules/30 then says conceptual and application items "count 1.2x vs procedural".
    `recall` is not mentioned, so it is weighted the same as procedural rather than
    inventing a discount the rules do not describe.
    """
    level = 3 if difficulty is None else max(1, min(5, int(difficulty)))
    weight = 0.7 + 0.1 * level
    if skill in CONCEPTUAL_SKILLS:
        weight *= CONCEPTUAL_MULTIPLIER
    return weight


def update_mastery(score: float, correct: bool, weight: float) -> float:
    """One item's effect on a node's mastery. rules/30, applied verbatim."""
    if correct:
        score = score + CORRECT_GAIN * (1.0 - score) * weight
    else:
        score = score - INCORRECT_LOSS * score * weight
    return max(MASTERY_FLOOR, min(MASTERY_CEILING, score))
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python -m unittest tests.test_learner -v`
Expected: all tests PASS (17 total)

- [ ] **Step 5: Commit**

```bash
git add scripts/learner.py tests/test_learner.py
git commit -m "learner: the rules/30 mastery curve

Five correct medium items take a node from the 0.05 floor to 0.84, crossing
the 0.8 threshold; four do not. Mastery is earned over a handful of items
rather than claimed in one.

The difficulty->weight mapping is an interpretation and is flagged as such in
the docstring: rules/30 names three weights, the data carries five levels, so
this interpolates between the two stated endpoints. recall is weighted with
procedural because rules/30 does not mention it."
```

---

### Task 4: Misconception repair staging

rules/40 §5: retest after 2 days, then 7, and only then mark repaired. rules/30 is explicit that nothing but a later correct answer on a targeting item confirms a repair.

**Files:**
- Modify: `scripts/learner.py`
- Modify: `tests/test_learner.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces:
  - `RETEST_GAPS: tuple = (2, 7)`
  - `observe_misconception(entry: dict | None, misconception_id: str, on: date) -> dict`
  - `pass_retest(entry: dict, on: date) -> dict`
  - `display_stage(entry: dict, today: date) -> str` returning one of `observed` / `confronted` / `retest-due` / `repaired`

  Entry shape: `{"id": str, "first_seen": "YYYY-MM-DD", "repair_stage": str, "retest_after": "YYYY-MM-DD" | None, "retests_passed": int}`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_learner.py`:

```python
from datetime import date


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
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m unittest tests.test_learner -v`
Expected: FAIL with `AttributeError: module 'learner' has no attribute 'observe_misconception'`

- [ ] **Step 3: Write the implementation**

Append to `scripts/learner.py` (and add `from datetime import date, timedelta` to the imports at the top of the file):

```python
# ---------------------------------------------------------- misconception repair

# rules/40 §5: "Re-test repaired misconceptions after 2 days, then 7; only then
# mark repaired." Two passes, each no earlier than its due date.
RETEST_GAPS = (2, 7)


def _iso(value: date) -> str:
    return value.isoformat()


def observe_misconception(entry, misconception_id: str, on: date) -> dict:
    """The student's answer revealed this misconception. Resets any repair progress.

    A misconception that resurfaces is not partly repaired - it is back. rules/30 is
    explicit that only a later correct answer on a targeting item confirms a repair,
    so the converse holds too: a wrong answer withdraws the confirmation.

    `first_seen` never moves. It records when this faulty idea first appeared, which
    is what a teacher wants to know; the current stage records where repair has got to.
    """
    first_seen = entry.get("first_seen") if entry else None
    return {
        "id": misconception_id,
        "first_seen": first_seen or _iso(on),
        "repair_stage": "observed",
        "retest_after": None,
        "retests_passed": 0,
    }


def pass_retest(entry: dict, on: date) -> dict:
    """A correct answer on an item that targets this misconception.

    From `observed` this confronts it and schedules the first retest. After that,
    a pass only counts once the due date has arrived - answering correctly an hour
    later shows nothing about retention, which is the whole point of the gap.
    """
    updated = dict(entry)
    stage = updated.get("repair_stage", "observed")

    if stage == "repaired":
        return updated

    if stage == "observed":
        updated["repair_stage"] = "confronted"
        updated["retests_passed"] = 0
        updated["retest_after"] = _iso(on + timedelta(days=RETEST_GAPS[0]))
        return updated

    due = updated.get("retest_after")
    if due and _iso(on) < due:
        return updated  # too early to count

    passed = updated.get("retests_passed", 0) + 1
    updated["retests_passed"] = passed
    if passed >= len(RETEST_GAPS):
        updated["repair_stage"] = "repaired"
        updated["retest_after"] = None
    else:
        updated["retest_after"] = _iso(on + timedelta(days=RETEST_GAPS[passed]))
    return updated


def display_stage(entry: dict, today: date) -> str:
    """`retest-due` is a function of the calendar, not a stored state.

    The schema's enum includes it, but storing it would mean rewriting every
    profile at midnight. It is exactly "confronted, and the due date has arrived".
    """
    stage = entry.get("repair_stage", "observed")
    due = entry.get("retest_after")
    if stage == "confronted" and due and _iso(today) >= due:
        return "retest-due"
    return stage
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python -m unittest tests.test_learner -v`
Expected: all PASS (23 total)

- [ ] **Step 5: Commit**

```bash
git add scripts/learner.py tests/test_learner.py
git commit -m "learner: misconception repair staging

rules/40 §5 requires two targeted retests, at +2 days then +7, before a
misconception counts as repaired. A pass before the due date does not count -
answering correctly an hour later shows nothing about retention, which is what
the gap exists to measure.

A wrong answer resets to observed and clears the progress: a misconception that
resurfaces is not partly repaired, it is back. first_seen never moves.

retest-due is derived from the calendar rather than stored, so no profile needs
rewriting at midnight."
```

---

### Task 5: The spaced-repetition ladder

**Files:**
- Modify: `scripts/learner.py`
- Modify: `tests/test_learner.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces:
  - `LADDER: tuple = (1, 3, 7, 16, 35)`
  - `MONTHLY: int = 30`
  - `interval_days(rung: int, multiplier: float = 1.0) -> int`
  - `schedule_review(entry: dict | None, passed: bool, on: date, multiplier: float) -> dict` returning `{"next_review": "YYYY-MM-DD", "interval_days": int, "lapses": int, "rung": int}`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_learner.py`:

```python
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
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m unittest tests.test_learner -v`
Expected: FAIL with `AttributeError: module 'learner' has no attribute 'interval_days'`

- [ ] **Step 3: Write the implementation**

Append to `scripts/learner.py`:

```python
# ------------------------------------------------------------ spaced repetition

# rules/10 §2: expanding intervals 1, 3, 7, 16, 35 days, then monthly.
LADDER = (1, 3, 7, 16, 35)
MONTHLY = 30


def interval_days(rung: int, multiplier: float = 1.0) -> int:
    """Days until the next review, scaled by the strand's personal forgetting curve.

    rules/40 §7: a student who never forgets geometry but bleeds number facts gets
    longer geometry gaps and shorter number ones. The multiplier comes from the
    profile's `retention` map and is tuned by /reflect, not here.
    """
    base = LADDER[rung] if rung < len(LADDER) else MONTHLY
    # Half-up, not round(). Python's round() is banker's rounding, so a 1.5x
    # retention multiplier on the 7-day rung would silently give 10 days instead
    # of 11 - a surprise nobody would predict from reading rules/10. Intervals are
    # never negative, so +0.5 needs no sign handling.
    return max(1, int(base * multiplier + 0.5))


def schedule_review(entry, passed: bool, on: date, multiplier: float = 1.0) -> dict:
    """Advance or reset a node's review schedule after a review attempt.

    A pass moves one rung up the ladder. A failure drops straight back to rung 0 and
    counts a lapse - there is no partial credit, because a node you could not recall
    is a node you have to rebuild.
    """
    rung = 0 if entry is None else int(entry.get("rung", 0))
    lapses = 0 if entry is None else int(entry.get("lapses", 0))

    if entry is None:
        rung = 0
    elif passed:
        rung += 1
    else:
        rung = 0
        lapses += 1

    days = interval_days(rung, multiplier)
    return {
        "rung": rung,
        "lapses": lapses,
        "interval_days": days,
        "next_review": _iso(on + timedelta(days=days)),
    }
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python -m unittest tests.test_learner -v`
Expected: all PASS (31 total)

- [ ] **Step 5: Commit**

```bash
git add scripts/learner.py tests/test_learner.py
git commit -m "learner: spaced-repetition ladder with per-strand forgetting curves

rules/10's 1/3/7/16/35-then-monthly ladder, scaled by the strand multiplier
from the profile's retention map (rules/40 §7). A failed review drops to rung
0 and counts a lapse - no partial credit, because a node you could not recall
is a node you have to rebuild.

This module reads the multiplier; tuning it stays in /reflect where rules/40
puts it."
```

---

### Task 6: The projection

Assembles the previous three tasks into `project()`. This is where the ledger becomes a profile.

**Files:**
- Modify: `scripts/learner.py`
- Modify: `tests/test_learner.py`

**Interfaces:**
- Consumes: `item_weight`, `update_mastery`, `INITIAL_MASTERY`, `CONCEPTUAL_SKILLS`, `observe_misconception`, `pass_retest`, `schedule_review`, `read_sessions`, `atomic_write_json`.
- Produces:
  - `project(seed: dict, logs: list[dict], question_index: dict, strand_of: dict, today: date) -> tuple[dict, list[str]]`
  - `build_question_index(kg) -> dict` mapping `(node_id, question_id) -> {"difficulty": int, "skill": str, "targets": set[str]}`
  - `CARRIED_FIELDS: tuple` — profile keys the ledger does not own
  - `reproject(student_id, kg, today, root=ROOT) -> tuple[dict, list[str]]`
  - `save_profile(student_id, profile, root=ROOT) -> None`

  `targets` is the set of misconception ids any option of that question is tagged with — used to decide whether a correct answer counts as a retest.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_learner.py`:

```python
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

    def test_projection_is_deterministic(self):
        logs = [_log("2026-03-01", [_item("g5.num.x", "q1", True)]),
                _log("2026-03-02", [_item("g5.num.x", "q2", False, "m1")])]
        first, _ = learner.project({}, logs, QINDEX, STRANDS, self.today)
        second, _ = learner.project({}, logs, QINDEX, STRANDS, self.today)
        self.assertEqual(json.dumps(first, sort_keys=True),
                         json.dumps(second, sort_keys=True))
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m unittest tests.test_learner -v`
Expected: FAIL with `AttributeError: module 'learner' has no attribute 'project'`

- [ ] **Step 3: Write the implementation**

Append to `scripts/learner.py`:

```python
# ------------------------------------------------------------------- projection

# Fields the ledger does not own. They come from the intake interview and from
# /reflect's cross-session mining, neither of which is an assessment observation,
# so the projection carries them forward rather than deriving them.
CARRIED_FIELDS = (
    "$schema", "id", "created", "grade", "goals", "interests", "language",
    "motivation", "retention", "error_signature", "strategy_stats", "behavior",
    "affect", "calibration", "projection_from",
)

MASTERY_THRESHOLD = 0.8


def build_question_index(kg) -> dict:
    """(node_id, question_id) -> the facts the projection needs about that item.

    `targets` is every misconception any option of the question is tagged with. A
    correct answer only counts as a retest for a misconception the item could
    actually have caught - getting an unrelated question right proves nothing about
    a faulty idea it never probed.
    """
    index = {}
    for node in kg.nodes:
        for question in node.get("questions", []):
            targets = {
                option["misconception"]
                for option in question.get("options", [])
                if option.get("misconception")
            }
            index[(node["id"], question["id"])] = {
                "difficulty": question.get("difficulty"),
                "skill": question.get("skill", "procedural"),
                "targets": targets,
            }
    return index


def project(seed: dict, logs: list, question_index: dict, strand_of: dict, today: date):
    """Replay the ledger into a profile. Pure: same inputs, same output, always.

    -> (profile, warnings). Warnings name items that could not be applied; they are
    never raised, because one unrecognised question must not cost a student their
    whole history, and never swallowed, because a silently ignored observation is
    exactly the "faked data" rules/00 forbids.
    """
    profile = {key: seed[key] for key in CARRIED_FIELDS if key in seed}
    profile.setdefault("id", seed.get("id", ""))
    mastery, schedule, warnings = {}, {}, []
    retention = profile.get("retention", {}) or {}

    for log in logs:
        log_day = date.fromisoformat(log["date"])
        # A rung is one review OUTCOME, not one item. Without this, a sitting with
        # six correct answers would walk a node straight up to the 11-day rung.
        # One sitting moves a node's schedule at most once.
        scheduled_this_log = set()
        for item in log.get("assessment", {}).get("items", []):
            node_id = item.get("node")
            question_id = item.get("question")
            facts = question_index.get((node_id, question_id))
            if facts is None:
                warnings.append(
                    f"{log.get('_file', log['date'])}: no question {question_id!r} "
                    f"on node {node_id!r}; item skipped"
                )
                continue

            correct = bool(item.get("correct"))
            record = mastery.setdefault(node_id, {
                "score": INITIAL_MASTERY, "evidence_count": 0,
                "last_seen": log["date"], "conceptual_ok": False,
                "misconceptions_active": [],
            })

            record["score"] = update_mastery(
                record["score"], correct, item_weight(facts["difficulty"], facts["skill"])
            )
            record["evidence_count"] += 1
            record["last_seen"] = log["date"]
            if correct and facts["skill"] in CONCEPTUAL_SKILLS:
                record["conceptual_ok"] = True

            active = record["misconceptions_active"]
            signalled = item.get("misconception_signalled")
            if not correct and signalled:
                existing = next((m for m in active if m["id"] == signalled), None)
                updated = observe_misconception(existing, signalled, log_day)
                if existing:
                    active[active.index(existing)] = updated
                else:
                    active.append(updated)
            elif correct:
                # A correct answer advances every misconception this item targets.
                for entry in list(active):
                    if entry["id"] in facts["targets"] and entry["repair_stage"] != "repaired":
                        active[active.index(entry)] = pass_retest(entry, log_day)

            # A node enters the review schedule the moment it is first MASTERED, and
            # stays scheduled thereafter. Reviews for it are logged like any other
            # item, so a later failure reaches this same path and resets the rung.
            is_mastered = (record["score"] >= MASTERY_THRESHOLD and record["conceptual_ok"])
            if (is_mastered or node_id in schedule) and node_id not in scheduled_this_log:
                scheduled_this_log.add(node_id)
                schedule[node_id] = schedule_review(
                    schedule.get(node_id), correct, log_day,
                    float(retention.get(strand_of.get(node_id, ""), 1.0)),
                )

    for record in mastery.values():
        record["score"] = round(record["score"], 4)

    profile["mastery"] = mastery
    profile["spaced_repetition"] = schedule
    profile["session_count"] = len(logs)
    profile["last_session"] = logs[-1]["date"] if logs else None
    profile.setdefault("strategy_stats", {})
    profile.setdefault("behavior", {})
    return profile, warnings


def reproject(student_id: str, kg, today: date, root: Path = ROOT):
    """Rebuild a student's profile from their ledger. -> (profile, warnings)."""
    seed_path = student_dir(student_id, root) / "profile.json"
    seed = read_json(seed_path) if seed_path.exists() else {}
    logs, warnings = read_sessions(student_id, root)
    strand_of = {node["id"]: node["strand"] for node in kg.nodes}
    profile, project_warnings = project(
        seed, logs, build_question_index(kg), strand_of, today
    )
    return profile, warnings + project_warnings


def save_profile(student_id: str, profile: dict, root: Path = ROOT) -> None:
    atomic_write_json(student_dir(student_id, root) / "profile.json", profile)
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python -m unittest tests.test_learner -v`
Expected: all PASS (45 total)

- [ ] **Step 5: Commit**

```bash
git add scripts/learner.py tests/test_learner.py
git commit -m "learner: project a profile from the session ledger

project() replays every logged assessment item through the rules/30 curve, the
rules/40 repair staging and the rules/10 ladder to produce profile.json. Pure:
same logs, same profile, always - which is what makes 'never fake data'
structural rather than a matter of discipline.

A correct answer only advances a misconception the item actually targets;
getting an unrelated question right proves nothing about a faulty idea it never
probed. An unrecognised question is warned about and skipped, never raised and
never silently dropped.

Intake and /reflect-owned fields (interests, goals, strategy_stats, retention)
are carried through untouched - they are not assessment observations."
```

---

### Task 7: The path engine

Pure graph + profile functions. No model, no I/O.

**Files:**
- Create: `scripts/path.py`
- Create: `tests/test_path.py`

**Interfaces:**
- Consumes: nothing from earlier tasks. Takes a `KG` (from `jev_brain`) and a profile dict.
- Produces:
  - `is_mastered(profile: dict, node_id: str) -> bool`
  - `mastered_set(profile: dict) -> set[str]`
  - `ready_nodes(kg, profile) -> list[dict]` each `{id, title, grade, strand, recommended_first: [{id, title, reason}]}`
  - `locked_nodes(kg, profile) -> list[dict]` each `{id, title, grade, strand, blocked_by: [{id, title, reason}]}`
  - `reviews_due(profile, today) -> list[dict]` each `{id, next_review, days_overdue, lapses}`, most overdue first
  - `review_debt(profile, today) -> int`
  - `gap_path(kg, profile, target_id) -> list[dict]` topologically ordered
  - `REVIEW_DEBT_LIMIT: int = 10`

- [ ] **Step 1: Write the failing test**

Create `tests/test_path.py`:

```python
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
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m unittest tests.test_path -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'path'`

Note: the module is deliberately named `path`, and `sys.path.insert` puts `scripts/` first, so this shadows nothing in stdlib (`os.path` is an attribute of `os`, not a top-level import).

- [ ] **Step 3: Write the implementation**

Create `scripts/path.py`:

```python
#!/usr/bin/env python3
"""Where a student stands on the graph: what is mastered, ready, locked, or due.

Pure functions over (graph, profile). No model calls and no file I/O, so the
gating rules that decide what a child is allowed to learn next can be unit-tested
offline and reviewed line by line. That matters more here than anywhere else in
the system: a bug in this file silently teaches on top of a gap.
"""
from datetime import date

# rules/30 and rules/40 §1 and the viewer overlay all use this one definition.
MASTERY_THRESHOLD = 0.8

# rules/40 §6: "Never let review debt exceed 10 nodes - if it does, the next
# session is a review session." Stated flatly, so it is policy, not a judgment.
REVIEW_DEBT_LIMIT = 10


def is_mastered(profile: dict, node_id: str) -> bool:
    """MASTERED = score >= 0.8 AND conceptual_ok. The only place this is defined.

    Both halves matter. A student can grind a procedure to 0.9 without understanding
    what it means, and rules/30 refuses to call that mastery, because the dependent
    concepts will need the understanding and not the procedure.
    """
    record = (profile.get("mastery") or {}).get(node_id)
    if not record:
        return False
    return record.get("score", 0) >= MASTERY_THRESHOLD and bool(record.get("conceptual_ok"))


def mastered_set(profile: dict) -> set:
    return {node_id for node_id in (profile.get("mastery") or {})
            if is_mastered(profile, node_id)}


def _split_prereqs(node: dict):
    """-> (hard, soft). A bare string edge counts as hard (rules/40 §1)."""
    hard, soft = [], []
    for prereq in node.get("prerequisites", []):
        if isinstance(prereq, str):
            hard.append({"id": prereq, "strength": "hard", "reason": ""})
        elif prereq.get("strength") == "soft":
            soft.append(prereq)
        else:
            hard.append(prereq)
    return hard, soft


def _describe(kg, prereq: dict) -> dict:
    node = kg.by_id.get(prereq["id"], {})
    return {
        "id": prereq["id"],
        "title": node.get("title", prereq["id"]),
        "grade": node.get("grade"),
        # The author's own words. rules/40 §1 is explicit that this is what gets
        # shown to a student: "we need place value first because you can't compare
        # decimals without it" beats "the graph says so".
        "reason": prereq.get("reason", ""),
    }


def ready_nodes(kg, profile: dict) -> list:
    """Not yet mastered, and every hard prerequisite is. The frontier."""
    mastered = mastered_set(profile)
    out = []
    for node in kg.nodes:
        if node["id"] in mastered:
            continue
        hard, soft = _split_prereqs(node)
        if any(prereq["id"] not in mastered for prereq in hard):
            continue
        out.append({
            "id": node["id"], "title": node["title"], "grade": node["grade"],
            "strand": node["strand"],
            # Soft edges never block. They are worth naming so a tutor can pick
            # them up opportunistically.
            "recommended_first": [_describe(kg, p) for p in soft
                                  if p["id"] not in mastered],
        })
    return out


def locked_nodes(kg, profile: dict) -> list:
    """Not mastered, and at least one hard prerequisite is missing. Names which."""
    mastered = mastered_set(profile)
    out = []
    for node in kg.nodes:
        if node["id"] in mastered:
            continue
        hard, _ = _split_prereqs(node)
        missing = [p for p in hard if p["id"] not in mastered]
        if not missing:
            continue
        out.append({
            "id": node["id"], "title": node["title"], "grade": node["grade"],
            "strand": node["strand"],
            "blocked_by": [_describe(kg, p) for p in missing],
        })
    return out


def reviews_due(profile: dict, today: date) -> list:
    """Scheduled reviews at or past their date, most overdue first."""
    out = []
    for node_id, entry in (profile.get("spaced_repetition") or {}).items():
        due = entry.get("next_review")
        if not due:
            continue
        overdue = (today - date.fromisoformat(due)).days
        if overdue >= 0:
            out.append({
                "id": node_id, "next_review": due, "days_overdue": overdue,
                "interval_days": entry.get("interval_days"),
                "lapses": entry.get("lapses", 0),
            })
    out.sort(key=lambda entry: -entry["days_overdue"])
    return out


def review_debt(profile: dict, today: date) -> int:
    return len(reviews_due(profile, today))


def gap_path(kg, profile: dict, target_id: str) -> list:
    """Unmastered hard ancestors of the target, plus the target, in teaching order.

    Depth-first post-order over hard edges gives a topological order: a node is
    emitted only after everything it depends on. Soft edges are excluded - they do
    not block, so they are not gaps on the critical path.

    Cycles would be a bug in the graph rather than a case to handle gracefully, but
    `seen` keeps this terminating regardless so a malformed edge cannot hang the
    server.
    """
    if target_id not in kg.by_id:
        return []
    mastered = mastered_set(profile)
    ordered, seen = [], set()

    def visit(node_id: str):
        if node_id in seen or node_id in mastered or node_id not in kg.by_id:
            return
        seen.add(node_id)
        node = kg.by_id[node_id]
        hard, _ = _split_prereqs(node)
        for prereq in hard:
            visit(prereq["id"])
        ordered.append({
            "id": node["id"], "title": node["title"], "grade": node["grade"],
            "strand": node["strand"],
            "description": node.get("description", ""),
        })

    visit(target_id)
    return ordered
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python -m unittest discover -s tests -t . -v`
Expected: all PASS (learner 45 + path 17 = 62 total)

- [ ] **Step 5: Commit**

```bash
git add scripts/path.py tests/test_path.py
git commit -m "path: where a student stands on the graph

mastered / ready / locked / reviews_due / gap_path as pure functions over
(graph, profile). No model calls and no I/O: a bug in this file silently
teaches on top of a gap, so it has to be testable offline and reviewable line
by line.

MASTERED = score >= 0.8 AND conceptual_ok is defined here once and nowhere
else. Hard edges gate, soft edges surface as recommended_first. Every locked
node names the specific prerequisite blocking it and carries the author's
written reason, which rules/40 §1 requires be shown to the student."
```

---

### Task 8: Candidate assembly and the "what next" decision

The first Jev judgment in this slice. Code assembles candidates, Jev chooses.

**Files:**
- Create: `scripts/jev_guide.py`

**Interfaces:**
- Consumes: `path.ready_nodes`, `path.locked_nodes`, `path.reviews_due`, `path.review_debt`, `path.REVIEW_DEBT_LIMIT`, `learner.display_stage`, `jev_client.JevClient/choice/noul/score/read_*`.
- Produces:
  - `assemble_candidates(kg, profile, today, limit=12) -> tuple[list[dict], bool]` returning `(candidates, debt_forced)`. Each candidate: `{id, title, grade, strand, kind, why}` where `kind ∈ {"due_review", "misconception_retest", "frontier"}`.
  - `decide_next(client, kg, profile, today) -> dict`

- [ ] **Step 1: Write the candidate assembly test**

Create `tests/test_guide.py`:

```python
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


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m unittest tests.test_guide -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'jev_guide'`

- [ ] **Step 3: Write the implementation**

Create `scripts/jev_guide.py`:

```python
#!/usr/bin/env python3
"""What the student should do next - the judgment, over candidates code assembled.

Same shape as route() in jev_brain.py, and for the same reason: a model cannot
choose an option it was never shown, so code narrows the graph to a shortlist and
Jev decides among them. Narrowing is retrieval; choosing is judgment.

One thing here is deliberately NOT Jev's: rules/40 §6 says review debt over ten
nodes makes the next session a review session. The rule is stated flatly, so the
code enforces it and the candidate list simply contains nothing else.
"""
from datetime import date

import path as pathmod
from jev_client import choice, noul, read_choice, read_noul, read_score, score
from learner import display_stage

SESSION_SHAPES = {
    "reviews_then_teach": "Clear the due reviews first, then teach the new concept. The "
                          "standard shape when a few things are fading but the student is "
                          "ready to move forward.",
    "review_only": "Spend the whole session rescuing what is fading. Nothing new.",
    "teach_only": "Go straight into the new concept - nothing is due, or what is due can "
                  "wait a day without being lost.",
    "repair_misconception": "Put the session into repairing one specific faulty idea, "
                            "because it keeps resurfacing and is blocking progress.",
}

RAMP_LEVELS = [
    "Ease off: recent evidence shows the student struggling, so the next session should "
    "revisit ground they have already partly covered before adding anything",
    "Hold steady: they are succeeding with visible effort, which is where learning "
    "happens - keep the difficulty roughly where it is",
    "Stretch: they are getting things right easily and quickly, and staying here would "
    "waste the session - push into harder material",
]


def assemble_candidates(kg, profile: dict, today: date, limit: int = 12):
    """Everything the student could sensibly do next. -> (candidates, debt_forced).

    Ordered by code before Jev sees it: overdue reviews first, then misconception
    retests, then the frontier nearest their level. The order is a prior, not a
    decision - Jev is free to pick anything on the list.
    """
    due = pathmod.reviews_due(profile, today)
    forced = len(due) > pathmod.REVIEW_DEBT_LIMIT

    candidates = []
    for review in due:
        node = kg.by_id.get(review["id"])
        if not node:
            continue
        candidates.append({
            "id": node["id"], "title": node["title"], "grade": node["grade"],
            "strand": node["strand"], "kind": "due_review",
            "why": (f"due for review {review['days_overdue']} day(s) ago"
                    + (f", lapsed {review['lapses']}x before" if review["lapses"] else "")),
        })

    if forced:
        # rules/40 §6. Not a judgment call, so Jev is not offered the alternative.
        return candidates[:limit], True

    for node_id, record in (profile.get("mastery") or {}).items():
        node = kg.by_id.get(node_id)
        if not node:
            continue
        for entry in record.get("misconceptions_active", []):
            if display_stage(entry, today) == "retest-due":
                candidates.append({
                    "id": node_id, "title": node["title"], "grade": node["grade"],
                    "strand": node["strand"], "kind": "misconception_retest",
                    "why": f"misconception {entry['id']} is due its repair retest",
                })

    frontier = pathmod.ready_nodes(kg, profile)
    frontier.sort(key=lambda n: n["grade"])
    for node in frontier:
        candidates.append({
            "id": node["id"], "title": node["title"], "grade": node["grade"],
            "strand": node["strand"], "kind": "frontier",
            "why": "ready to learn - every prerequisite is in place",
        })

    # De-duplicate by (id, kind): one node can legitimately appear as both a review
    # and a retest, and those are different things to do with it.
    seen, unique = set(), []
    for candidate in candidates:
        key = (candidate["id"], candidate["kind"])
        if key not in seen:
            seen.add(key)
            unique.append(candidate)
    return unique[:limit], False


def decide_next(client, kg, profile: dict, today: date) -> dict:
    """Four judgments in one request over the candidate list."""
    candidates, forced = assemble_candidates(kg, profile, today)
    if not candidates:
        return {"candidates": [], "debt_forced": False, "decision": None,
                "reason": "Nothing is ready and nothing is due. Every concept whose "
                          "prerequisites are met has been mastered."}

    options = {
        c["id"] + "|" + c["kind"]:
            f"Class {c['grade']} · {c['title']} — {c['why']}"
        for c in candidates
    }

    state = {
        "candidates": candidates,
        "student": {
            "school_class": profile.get("grade"),
            "goal": (profile.get("goals") or {}).get("target") or None,
            "interests": profile.get("interests", []),
            "motivation": (profile.get("motivation") or {}).get("drivers", []),
            "attention_span_min": (profile.get("behavior") or {}).get("attention_span_min"),
            "confidence_by_strand": (profile.get("affect") or {}).get("confidence_by_strand", {}),
            "reviews_due_count": len(pathmod.reviews_due(profile, today)),
            "sessions_so_far": profile.get("session_count", 0),
        },
        "recent_evidence": _recent_evidence(profile),
    }

    response = client.ask(state, {
        "next": choice(
            "Which single item from `candidates` should this student work on in their "
            "next session? Weigh what is fading, what is blocking progress, and what "
            "serves their stated goal - not merely what comes next in the curriculum.",
            options,
        ),
        "session_shape": choice("How should that session be structured?", SESSION_SHAPES),
        "ramp": score(
            "Judging by `recent_evidence`, how should the difficulty move next session? "
            "rules/40 targets a success rate of roughly 70-85%.",
            RAMP_LEVELS,
        ),
        "fits_attention": noul(
            "Is the chosen item a sensible size for this student's attention span?",
            true="It can be taught and tested within the minutes they can sustain",
            false="It is too big to finish well in one sitting for this student",
        ),
    })

    answers = response["answers"]
    picked, pick_conf, pick_probs = read_choice(answers["next"])
    shape, shape_conf, _ = read_choice(answers["session_shape"])
    ramp, ramp_conf, ramp_probs = read_score(answers["ramp"])
    fits = read_noul(answers["fits_attention"])

    chosen = next((c for c in candidates
                   if c["id"] + "|" + c["kind"] == picked), None)

    return {
        "candidates": candidates,
        "debt_forced": forced,
        "decision": {
            "pick": chosen,
            "confidence": round(pick_conf, 4),
            "probabilities": {k: round(v, 4) for k, v in
                              sorted(pick_probs.items(), key=lambda kv: -kv[1])
                              if v >= 0.005},
            "session_shape": {"value": shape, "confidence": round(shape_conf, 4)},
            "ramp": {"value": round(ramp, 3), "confidence": round(ramp_conf, 4),
                     "probabilities": {k: round(v, 4) for k, v in ramp_probs.items()}},
            "fits_attention": round(fits, 4),
        },
        "reason": _assemble_reason(kg, profile, chosen),
    }


def _recent_evidence(profile: dict, limit: int = 8) -> list:
    """The most recently seen nodes with how they went. Keeps the state small.

    The jaggedness notes warn that a large state padded with irrelevant detail makes
    answers worse, so this sends the last few nodes rather than the whole history.
    """
    records = [
        {"node": node_id, "score": record.get("score"),
         "conceptual_ok": record.get("conceptual_ok"),
         "last_seen": record.get("last_seen"),
         "active_misconceptions": [m["id"] for m in record.get("misconceptions_active", [])
                                   if m.get("repair_stage") != "repaired"]}
        for node_id, record in (profile.get("mastery") or {}).items()
    ]
    records.sort(key=lambda r: r.get("last_seen") or "", reverse=True)
    return records[:limit]


def _assemble_reason(kg, profile: dict, chosen) -> str:
    """Build the explanation from the graph's own words. Never generated prose.

    rules/00 keeps teaching copy human-authored, so this stitches together the
    author's edge reasons and real-world hooks rather than asking a model to write
    something persuasive.
    """
    if not chosen:
        return ""
    node = kg.by_id.get(chosen["id"])
    if not node:
        return chosen["why"]

    parts = [chosen["why"] + "."]

    if chosen["kind"] == "frontier":
        unlocks = [kg.by_id[dependent["id"]]["title"]
                   for dependent in getattr(kg, "unlocks", {}).get(chosen["id"], [])
                   if dependent["id"] in kg.by_id][:2]
        if unlocks:
            parts.append("It opens up " + " and ".join(unlocks) + ".")

    interests = [i.lower() for i in profile.get("interests", [])]
    hooks = (node.get("teaching") or {}).get("real_world_hooks", [])
    matched = [hook for hook in hooks
               if any(word.split()[0] in hook.lower() for word in interests if word)]
    if matched:
        parts.append("Hook that fits what they like: " + matched[0])

    return " ".join(parts)
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python -m unittest discover -s tests -t . -v`
Expected: all PASS (learner 45 + path 17 + guide 5 = 67 total)

- [ ] **Step 5: Verify the live decision against a real profile**

Run:

```bash
python -c "
import sys; sys.path.insert(0,'scripts')
from datetime import date
from jev_brain import KG
from jev_client import JevClient
import jev_guide, path as p
kg=KG(); prof={'grade':9,'interests':['cricket'],'goals':{'target':'Class 10 boards'},
 'mastery':{},'spaced_repetition':{},'session_count':0}
out=jev_guide.decide_next(JevClient(), kg, prof, date.today())
print('candidates:', [(c['id'],c['kind']) for c in out['candidates']])
print('picked   :', out['decision']['pick']['id'], out['decision']['confidence'])
print('shape    :', out['decision']['session_shape'])
print('reason   :', out['reason'])
"
```

Expected: a Class 1 frontier node is picked (nothing is mastered, so only roots are ready), `session_shape` is `teach_only` (nothing is due), and `reason` is non-empty. If the pick is not a root node, `ready_nodes` is wrong — stop and fix Task 7.

- [ ] **Step 6: Commit**

```bash
git add scripts/jev_guide.py tests/test_guide.py
git commit -m "guide: Jev decides what the student does next

Code assembles the candidate list - due reviews, misconception retests, the
frontier - and Jev chooses among them with the student's goal, interests,
attention span and recent evidence as state. Four judgments in one request.

rules/40 §6 stays in code: over ten due reviews and the candidate list contains
nothing but reviews, because the rule is stated flatly and is not Jev's to
overrule.

The reason shown to the student is assembled from the graph's own words - the
author's edge reasons and real-world hooks matched against the student's
interests - not generated. Jev picks; the curriculum supplies the wording."
```

---

### Task 9: Ranking the gaps toward a goal

**Files:**
- Modify: `scripts/jev_guide.py`

**Interfaces:**
- Consumes: `path.gap_path`.
- Produces: `rank_gaps(client, kg, profile, target_id, batch=10) -> dict` with `{"target": {...}, "gaps": [{id, title, grade, blocking, confidence, ...}], "total": int}` ordered by `blocking` descending.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_guide.py`, before the `if __name__` block:

```python
class TestGapBatching(unittest.TestCase):
    def test_gaps_are_chunked_for_batched_requests(self):
        self.assertEqual(jev_guide._chunk([1, 2, 3, 4, 5], 2), [[1, 2], [3, 4], [5]])

    def test_empty_input_gives_no_chunks(self):
        self.assertEqual(jev_guide._chunk([], 3), [])
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m unittest tests.test_guide -v`
Expected: FAIL with `AttributeError: module 'jev_guide' has no attribute '_chunk'`

- [ ] **Step 3: Write the implementation**

Append to `scripts/jev_guide.py`:

```python
# ------------------------------------------------------------- gaps toward a goal

BLOCKING_LEVELS = [
    "A detail they can pick up alongside the target - not knowing it would slow them "
    "down slightly but would not stop them",
    "A real dependency - they would be able to follow the target topic but would keep "
    "hitting steps they cannot do on their own",
    "A hard blocker - the target topic cannot be understood at all until this is in "
    "place, and attempting it first would only teach them to copy procedures",
]


def _chunk(items: list, size: int) -> list:
    return [items[i:i + size] for i in range(0, len(items), size)]


def rank_gaps(client, kg, profile: dict, target_id: str, batch: int = 10) -> dict:
    """Order the gap path by how much each gap actually holds the student back.

    gap_path returns a topological order, which says what depends on what but not
    what matters. Depth is not consequence: a Class 3 gap two hops back can matter
    far more than the Class 9 one immediately before the target.

    One Score per gap. Gaps over one state would be wrong here - each gap is judged
    against the same target, so they DO share a state, and batching them is the
    cheap path. Chunked because a very long path would otherwise build one enormous
    request, and the jaggedness notes warn that large states lose accuracy.
    """
    gaps = pathmod.gap_path(kg, profile, target_id)
    target = kg.by_id.get(target_id)
    if not gaps or not target:
        return {"target": target and {"id": target["id"], "title": target["title"]},
                "gaps": [], "total": 0}

    ranked = []
    for group in _chunk(gaps, batch):
        questions = {
            f"gap_{index}": score(
                f"How much does not yet knowing \"{item['title']}\" (Class {item['grade']}) "
                f"hold this student back from \"{target['title']}\"?",
                BLOCKING_LEVELS,
            )
            for index, item in enumerate(group)
        }
        response = client.ask(
            {
                "target": {"title": target["title"], "class": target["grade"],
                           "explained": target.get("description", "")[:400]},
                "missing_concepts": [
                    {"title": item["title"], "class": item["grade"],
                     "explained": (item.get("description") or "")[:200]}
                    for item in group
                ],
            },
            questions,
        )
        for index, item in enumerate(group):
            answer = response["answers"].get(f"gap_{index}")
            blocking, confidence, _ = read_score(answer) if answer else (0.0, 0.0, {})
            ranked.append(dict(item, blocking=round(blocking, 3),
                               confidence=round(confidence, 4)))

    # Teaching order still has to respect prerequisites, so keep the topological
    # index and expose the blocking score alongside rather than resorting outright.
    for position, item in enumerate(ranked):
        item["teach_order"] = position
    ranked_by_impact = sorted(ranked, key=lambda item: -item["blocking"])

    return {
        "target": {"id": target["id"], "title": target["title"], "grade": target["grade"]},
        "gaps": ranked,
        "by_impact": [item["id"] for item in ranked_by_impact],
        "total": len(ranked),
    }
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python -m unittest tests.test_guide -v`
Expected: all PASS (7 in this file)

- [ ] **Step 5: Verify against the real graph**

Run:

```bash
python -c "
import sys; sys.path.insert(0,'scripts')
from jev_brain import KG
from jev_client import JevClient
import jev_guide
kg=KG(); prof={'mastery':{},'spaced_repetition':{}}
out=jev_guide.rank_gaps(JevClient(), kg, prof, 'g10.tri.intro')
print('gaps to trigonometry:', out['total'])
for g in out['gaps'][:6]:
    print(f\"  teach#{g['teach_order']:<2} blocking={g['blocking']:<5} C{g['grade']} {g['title'][:52]}\")
print('most blocking first:', out['by_impact'][:4])
"
```

Expected: a non-empty topologically ordered path to trigonometry, every `blocking` between 0 and 2, and `teach_order` ascending. If any gap has `grade` greater than 10, `gap_path` is walking the wrong direction — stop and fix Task 7.

- [ ] **Step 6: Commit**

```bash
git add scripts/jev_guide.py tests/test_guide.py
git commit -m "guide: rank the gaps toward a goal by how much they actually block

gap_path gives a topological order, which says what depends on what but not
what matters - a Class 3 gap two hops back can matter more than the Class 9 one
immediately before the target. One Score per gap says how hard a blocker it is.

The gaps share one state (they are all judged against the same target) so they
batch into one request, chunked at 10 to keep any single state small."
```

---

### Task 10: Server endpoints

**Files:**
- Modify: `scripts/jev_serve.py`

**Interfaces:**
- Consumes: everything from Tasks 2–9.
- Produces: the six endpoints in the spec, plus `Console.today()` returning `date.today()`.

- [ ] **Step 1: Add the imports and a student index helper**

At the top of `scripts/jev_serve.py`, after the existing `from jev_brain import ...` line, add:

```python
from datetime import date

import jev_guide
import learner
import path as pathmod
```

And add this module-level function after `MAX_AUDIT_ROWS`:

```python
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
```

- [ ] **Step 2: Add the GET endpoints**

In `do_GET`, immediately before the `if path == "/api/stats":` line, add:

```python
            if path == "/api/students":
                return self._json({"students": list_students()})

            if path.startswith("/api/student/"):
                student_id = path[len("/api/student/"):]
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
```

- [ ] **Step 3: Add the POST endpoints**

In `do_POST`, immediately before `if path == "/api/audit/edges":`, add:

```python
            if path.startswith("/api/student/") and path.endswith("/session"):
                student_id = path[len("/api/student/"):-len("/session")]
                log = payload.get("log")
                if not isinstance(log, dict) or "date" not in log:
                    return self._json({"error": "log with a date is required"}, 400)
                before = learner.student_dir(student_id) / "profile.json"
                previous = learner.read_json(before) if before.is_file() else {}
                written = learner.append_session(student_id, log)
                profile, warnings = learner.reproject(student_id, self.kg, date.today())
                learner.save_profile(student_id, profile)
                return self._json({
                    "written": written.name, "warnings": warnings, "profile": profile,
                    "mastery_delta": _mastery_delta(previous, profile),
                })

            if path.startswith("/api/student/") and path.endswith("/next"):
                student_id = path[len("/api/student/"):-len("/next")]
                profile_path = learner.student_dir(student_id) / "profile.json"
                if not profile_path.is_file():
                    return self._json({"error": f"no student {student_id}"}, 404)
                return self._json(jev_guide.decide_next(
                    self.client, self.kg, learner.read_json(profile_path), date.today()
                ))

            if path.startswith("/api/student/") and path.endswith("/gaps"):
                student_id = path[len("/api/student/"):-len("/gaps")]
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
                profile, warnings = learner.reproject(student_id, self.kg, date.today())
                stored_path = learner.student_dir(student_id) / "profile.json"
                stored = learner.read_json(stored_path) if stored_path.is_file() else {}
                learner.save_profile(student_id, profile)
                return self._json({
                    "profile": profile, "warnings": warnings,
                    "mastery_delta": _mastery_delta(stored, profile),
                })
```

- [ ] **Step 4: Add the delta helper**

Add this module-level function next to `list_students`:

```python
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
```

- [ ] **Step 5: Add `append_session` to learner.py**

Append to `scripts/learner.py`:

```python
def append_session(student_id: str, log: dict, root: Path = ROOT) -> Path:
    """Add one session log to the ledger. Never overwrites an existing file.

    Names the file <date>-<nn>.json, picking the next free nn. Two sittings on the
    same day get -01 and -02 and replay in that order.
    """
    folder = student_dir(student_id, root) / "sessions"
    folder.mkdir(parents=True, exist_ok=True)
    day = log["date"]
    index = 1
    while (folder / f"{day}-{index:02d}.json").exists():
        index += 1
    target = folder / f"{day}-{index:02d}.json"
    payload = {key: value for key, value in log.items() if key != "_file"}
    payload.setdefault("$schema", "../../../harness/schemas/session-log.schema.json")
    atomic_write_json(target, payload)
    return target
```

- [ ] **Step 6: Restart the server and verify every endpoint**

```bash
python scripts/jev_serve.py --port 8770 &
sleep 4
curl -s http://localhost:8770/api/students | python -m json.tool | head -20
curl -s http://localhost:8770/api/student/S999 | python -c "import json,sys; d=json.load(sys.stdin); print('ready',len(d['ready']),'locked',len(d['locked']),'debt',d['review_debt'])"
curl -s -X POST http://localhost:8770/api/student/S999/next -H 'Content-Type: application/json' -d '{}' | python -c "import json,sys; d=json.load(sys.stdin); print('pick', d['decision']['pick']['id'] if d.get('decision') else None)"
curl -s -X POST http://localhost:8770/api/student/S999/gaps -H 'Content-Type: application/json' -d '{\"target\":\"g10.tri.intro\"}' | python -c "import json,sys; print('gaps', json.load(sys.stdin)['total'])"
```

Expected: `/api/students` lists S001, S999 and no `_template`; the S999 call reports non-zero `ready`; `next` returns a pick; `gaps` returns a positive total.

- [ ] **Step 7: Commit**

```bash
git add scripts/jev_serve.py scripts/learner.py
git commit -m "serve: student state, next-step and gap endpoints

Six endpoints over the learner and path modules. A session POST appends to the
ledger, reprojects, saves, and returns the mastery delta so the UI can show what
the sitting actually proved.

/reproject rebuilds a profile from its logs and reports the diff - always safe,
because the ledger is the source of truth and the profile is derived."
```

---

### Task 11: The Journey screen

**Files:**
- Modify: `web/index.html`
- Modify: `web/console.js`

**Interfaces:**
- Consumes: `GET /api/students`, `GET /api/student/<id>`, `POST /api/student/<id>/gaps`.
- Produces: `initJourney()` called from `boot()`; a `STUDENTS` module-level array.

- [ ] **Step 1: Add the nav button and the stage**

In `web/index.html`, add before the Quiz nav button:

```html
    <button class="mode" data-stage="journey">
      Journey
      <small>Where a student stands</small>
    </button>
```

And add this section before the `<!-- =========================================================== QUIZ -->` comment:

```html
  <!-- ======================================================== JOURNEY -->
  <section class="stage" id="stage-journey" hidden>
    <h2>Where a student stands</h2>
    <p class="lede">
      Everything on this screen is computed from the session ledger by
      <code>path.py</code> — no model call, so it works whether or not Jev is
      reachable. A locked concept names the exact prerequisite blocking it, in the
      words the curriculum author wrote.
    </p>

    <div class="row" style="margin-bottom:16px">
      <div class="field" style="margin:0;min-width:200px">
        <label class="micro" for="journeyStudent">student</label>
        <select id="journeyStudent"><option value="">— loading —</option></select>
      </div>
      <div class="field" style="margin:0;flex:1;min-width:240px">
        <label class="micro" for="journeyTarget">goal (optional)</label>
        <input type="text" id="journeyTarget" list="nodeList" spellcheck="false"
               placeholder="pick a concept to see the path to it…">
      </div>
      <button class="run" id="journeyGaps" style="align-self:end">Show the path</button>
    </div>

    <div id="journeyOut"></div>
  </section>
```

- [ ] **Step 2: Add the rendering**

In `web/console.js`, add before `/* ================================== AUDIT ================================== */`:

```javascript
/* ================================= JOURNEY ================================= */

let STUDENTS = [];

function journeyCard(data) {
  const profile = data.profile;
  const debtOver = data.review_debt > data.debt_limit;

  const overdue = data.reviews_due.slice(0, 10).map((review) => `<tr>
    <td>${escapeHtml(GRAPH.nodes.find((n) => n.id === review.id)?.title || review.id)}
      <span class="nid">${escapeHtml(review.id)}</span></td>
    <td class="num">${review.days_overdue}d</td>
    <td class="num">${review.lapses ? `${review.lapses} lapses` : ""}</td>
  </tr>`).join("");

  const blocked = data.locked.slice(0, 12).map((node) => `<tr>
    <td>${escapeHtml(node.title)}<span class="nid">Class ${node.grade} · ${escapeHtml(node.id)}</span></td>
    <td>${node.blocked_by.map((prereq) =>
      `<b>${escapeHtml(prereq.title)}</b>${prereq.reason
        ? `<span class="nid">${escapeHtml(prereq.reason)}</span>` : ""}`).join("<br>")}</td>
  </tr>`).join("");

  const misconceptions = data.misconceptions.map((entry) => `<tr>
    <td class="num"><span class="tag ${entry.stage === "retest-due" ? "bad" : ""}">${escapeHtml(entry.stage)}</span></td>
    <td>${escapeHtml(entry.node_title)}<span class="nid">${escapeHtml(entry.node)} · ${escapeHtml(entry.id)}</span></td>
    <td class="num">${escapeHtml(entry.first_seen || "")}</td>
    <td class="num">${entry.retests_passed ?? 0} / 2</td>
  </tr>`).join("");

  return `<div class="summary-bar">
      <div><span class="micro">mastered</span><b class="ok">${data.mastered.length}</b></div>
      <div><span class="micro">ready now</span><b>${data.ready.length}</b></div>
      <div><span class="micro">locked</span><b>${data.locked.length}</b></div>
      <div><span class="micro">reviews due</span><b class="${debtOver ? "bad" : ""}">${data.review_debt}</b></div>
      <div><span class="micro">sessions</span><b>${profile.session_count ?? 0}</b></div>
    </div>

    ${debtOver ? `<div class="error">Review debt is ${data.review_debt}, over the limit of
      ${data.debt_limit}. rules/40 §6: the next session is a review session — "your brain has
      ${data.review_debt} things about to fade, let's rescue them".</div>` : ""}

    ${data.ready.length ? `<div class="card">
      <span class="micro">ready to learn — every prerequisite in place</span>
      <div class="nodeline" style="margin-top:8px">${data.ready.slice(0, 14).map((node) =>
        `<span class="tag on">Class ${node.grade} · ${escapeHtml(node.title)}</span>`).join("")}</div>
    </div>` : '<div class="note">Nothing is ready yet — this student has no recorded evidence.</div>'}

    ${overdue ? `<div class="card"><span class="micro">fading — most overdue first</span>
      <table style="margin-top:8px"><thead><tr><th>concept</th><th>overdue</th><th></th></tr></thead>
      <tbody>${overdue}</tbody></table></div>` : ""}

    ${misconceptions ? `<div class="card flagged">
      <span class="micro">active misconceptions and how far repair has got</span>
      <table style="margin-top:8px"><thead><tr><th>stage</th><th>concept</th><th>first seen</th><th>retests</th></tr></thead>
      <tbody>${misconceptions}</tbody></table></div>` : ""}

    ${blocked ? `<div class="card"><span class="micro">locked, and by what</span>
      <table style="margin-top:8px"><thead><tr><th>concept</th><th>needs first</th></tr></thead>
      <tbody>${blocked}</tbody></table></div>` : ""}`;
}

function gapsCard(data) {
  if (!data.total) {
    return `<div class="note">Nothing missing — every hard prerequisite for
      ${escapeHtml(data.target?.title || "that concept")} is already mastered.</div>`;
  }
  const rows = data.gaps.map((gap) => `<tr>
    <td class="num">${gap.teach_order + 1}</td>
    <td>${escapeHtml(gap.title)}<span class="nid">Class ${gap.grade} · ${escapeHtml(gap.id)}</span></td>
    <td style="width:170px">${inlineStrip([
      { label: "blocks", value: Math.min(1, gap.blocking / 2), tone: "warn" },
      { label: "minor", value: Math.max(0, 1 - gap.blocking / 2) },
    ])}</td>
    <td class="num">${fixed(gap.blocking)}</td>
    <td class="num">${fixed(gap.confidence)}</td>
  </tr>`).join("");

  return `<div class="card">
    <h3>${data.total} concepts between here and ${escapeHtml(data.target.title)}</h3>
    <p class="lede" style="margin:6px 0 12px">Numbered in teaching order, which respects
    prerequisites. The bar is Jev's judgment of how much each one actually blocks the
    goal — depth in the graph is not the same as consequence.</p>
    <table><thead><tr><th>#</th><th>concept</th><th>how much it blocks</th><th>score</th><th>conf</th></tr></thead>
    <tbody>${rows}</tbody></table>
  </div>`;
}

async function loadJourney() {
  const studentId = $("#journeyStudent").value;
  const outlet = $("#journeyOut");
  if (!studentId) { outlet.innerHTML = '<div class="note">Pick a student.</div>'; return; }
  outlet.innerHTML = '<div class="working"><i></i></div>';
  try {
    outlet.innerHTML = journeyCard(await api(`/api/student/${encodeURIComponent(studentId)}`));
  } catch (error) {
    outlet.innerHTML = `<div class="error">${escapeHtml(error.message)}</div>`;
  }
}

async function refreshStudents() {
  try {
    const { students } = await api("/api/students");
    STUDENTS = students;
    const options = students.length
      ? students.map((s) => `<option value="${escapeHtml(s.id)}">${escapeHtml(s.id)} · Class ${s.grade ?? "?"} · ${s.mastered} mastered</option>`).join("")
      : '<option value="">— no students yet —</option>';
    ["#journeyStudent", "#quizStudent"].forEach((selector) => {
      const element = $(selector);
      if (element) element.innerHTML = `<option value="">— none —</option>${options}`;
    });
  } catch { /* the console still works without a student list */ }
}

function initJourney() {
  $("#journeyStudent").addEventListener("change", loadJourney);
  $("#journeyGaps").addEventListener("click", () =>
    run($("#journeyGaps"), $("#journeyOut"), async () => {
      const studentId = $("#journeyStudent").value;
      const target = nodeIdFromPicker($("#journeyTarget").value);
      if (!studentId) return '<div class="note">Pick a student first.</div>';
      if (!target) return '<div class="note">Pick a concept to aim at.</div>';
      return gapsCard(await api(`/api/student/${encodeURIComponent(studentId)}/gaps`,
                                { target }));
    }));
}
```

- [ ] **Step 3: Wire it into boot**

In `boot()`, add `initJourney();` after `initQuiz();`, and add `await refreshStudents();` immediately after the `GRAPH = await api("/api/graph");` line's block completes (inside the same `try`).

- [ ] **Step 4: Verify**

Run: `node --check web/console.js` — expected: no output (valid).

Restart the server, open `http://localhost:8770`, click **Journey**, pick S999. Expected: the summary bar shows non-zero counts, and at least one locked concept displays a prerequisite with the author's reason underneath it. Then type a Class 10 concept into the goal field and click **Show the path** — expected: a numbered list with probability strips.

- [ ] **Step 5: Commit**

```bash
git add web/index.html web/console.js
git commit -m "web: Journey screen - where a student stands

Mastered / ready / locked / fading counts, the review queue ordered by how
overdue each item is, active misconceptions with their repair stage and retest
progress, and every locked concept naming the prerequisite that blocks it in
the author's own words.

All of it comes from path.py, so the screen works with Jev unreachable. Only
the goal path calls the model."
```

---

### Task 12: Wire the Quiz to a student

The last step: a sitting changes what the system knows.

**Files:**
- Modify: `web/index.html`
- Modify: `web/console.js`

**Interfaces:**
- Consumes: `POST /api/student/<id>/session`, the existing quiz transcript.
- Produces: `buildSessionLog(nodeId, transcript, verdict) -> object` matching `session-log.schema.json`.

- [ ] **Step 1: Add the student selector to the Quiz setup**

In `web/index.html`, inside `<div class="row" id="quizSetup">`, add as the first child:

```html
      <div class="field" style="margin:0;min-width:170px">
        <label class="micro" for="quizStudent">student (optional)</label>
        <select id="quizStudent"><option value="">— none —</option></select>
      </div>
```

- [ ] **Step 2: Build the session log and post it**

In `web/console.js`, add before `/* ================================= JOURNEY ================================= */`:

```javascript
/** Shape a finished sitting as a session log the ledger will accept. */
function buildSessionLog(nodeId, transcript, verdict) {
  const today = new Date().toISOString().slice(0, 10);
  return {
    student: $("#quizStudent").value,
    date: today,
    goal: `${nodeId}: quiz`,
    nodes_touched: [nodeId],
    reviews_done: [],
    events: [],
    assessment: {
      items: transcript.map((item) => ({
        node: nodeId,
        question: item.question_id,
        correct: item.is_correct >= 0.5,
        answer_text: item.answer,
        misconception_signalled:
          item.misconception && !["no_error", "other_error"].includes(item.misconception)
            ? item.misconception : undefined,
        jev: {
          is_correct: item.is_correct,
          misconception: item.misconception,
          confident: item.confident,
          model: $("#modelTag").textContent,
        },
      })),
    },
    profile_updates: {},
    reflection: {
      goal_met: verdict ? verdict.mastery.value >= 1.5 : false,
      evidence: verdict
        ? `Jev read the sitting as "${verdict.mastery.label}" (${verdict.mastery.value}/2).`
        : "",
    },
  };
}

function deltaCard(result) {
  if (!result.mastery_delta.length) {
    return '<div class="note">Recorded. No mastery score moved.</div>';
  }
  const rows = result.mastery_delta.map((row) => `<tr>
    <td>${escapeHtml(GRAPH.nodes.find((n) => n.id === row.node)?.title || row.node)}
      <span class="nid">${escapeHtml(row.node)}</span></td>
    <td class="num">${row.from === null || row.from === undefined ? "—" : fixed(row.from)}</td>
    <td class="num">→ ${fixed(row.to)}</td>
    <td class="num">${row.newly_mastered ? '<span class="tag ok">now mastered</span>' : ""}</td>
  </tr>`).join("");

  return `<div class="card clean">
    <span class="micro">written to the ledger — ${escapeHtml(result.written)}</span>
    <table style="margin-top:8px"><thead><tr><th>concept</th><th>was</th><th>now</th><th></th></tr></thead>
    <tbody>${rows}</tbody></table>
    ${result.warnings.length
      ? `<div class="error" style="margin-top:10px">${result.warnings.map(escapeHtml).join("<br>")}</div>`
      : ""}
  </div>`;
}
```

- [ ] **Step 3: Record the question id in the transcript**

In `wireQuizButtons`, inside the `quiz.transcript.push({...})` call, add `question_id: question.id,` as the first property. Without it the session log cannot name which item was answered and the projection will skip it.

- [ ] **Step 4: Post the session after the verdict**

In `advanceQuiz`, replace the `.then((verdict) => {...})` callback with:

```javascript
    .then(async (verdict) => {
      outlet.innerHTML = quizHistory() + verdictCard(verdict);
      const studentId = $("#quizStudent").value;
      if (!studentId) return;
      // Only now, on an explicit finish, does the ledger gain a file. An abandoned
      // sitting leaves no record, which is what makes crash recovery a non-event.
      try {
        const saved = await api(`/api/student/${encodeURIComponent(studentId)}/session`,
                                { log: buildSessionLog(quiz.node.id, quiz.transcript, verdict) });
        outlet.insertAdjacentHTML("beforeend", deltaCard(saved));
        refreshStudents();
      } catch (error) {
        outlet.insertAdjacentHTML("beforeend",
          `<div class="error">The sitting was judged but not recorded: ${escapeHtml(error.message)}</div>`);
      }
    })
```

- [ ] **Step 5: Verify the whole loop end to end**

```bash
python -c "
import io,json,sys; sys.path.insert(0,'scripts')
from pathlib import Path
p=Path('students/S900'); (p/'sessions').mkdir(parents=True, exist_ok=True)
io.open(p/'profile.json','w',encoding='utf-8').write(json.dumps(
 {'id':'S900','created':'2026-09-21','grade':5,'mastery':{},'strategy_stats':{},
  'behavior':{},'spaced_repetition':{},'session_count':0,'last_session':None},indent=1))
print('test student S900 created')
"
```

Restart the server, open the console, go to **Quiz**, select **S900**, pick *adding fractions*, answer all three questions, and finish. Expected: after the verdict card, a delta card appears naming the written file and showing the mastery score moving from `—` to a number. Then open **Journey**, pick S900, and confirm the counts changed.

Verify the ledger is real and the projection is reproducible:

```bash
ls students/S900/sessions/
python -c "
import sys; sys.path.insert(0,'scripts')
from datetime import date
from jev_brain import KG
import learner, json
profile, warnings = learner.reproject('S900', KG(), date.today())
stored = learner.read_json(learner.student_dir('S900')/'profile.json')
print('warnings:', warnings)
print('reprojection matches stored profile:',
      json.dumps(profile,sort_keys=True)==json.dumps(stored,sort_keys=True))
"
```

Expected: one session file listed, no warnings, and `True`. If it prints `False`, the projection is not deterministic — stop and fix Task 6 before continuing.

Clean up: `rm -rf students/S900`

- [ ] **Step 6: Run the whole suite**

Run: `python -m unittest discover -s tests -t . -v`
Expected: all 67 tests PASS.

- [ ] **Step 7: Commit**

```bash
git add web/index.html web/console.js
git commit -m "web: a sitting now changes what the system knows

Finishing a quiz with a student selected appends a session log and reprojects
their profile, then shows which mastery scores moved and whether anything became
mastered. Without a student selected the console behaves exactly as before - the
test bench has to keep working without inventing a learner.

The ledger only gains a file on an explicit finish, so an abandoned sitting
leaves no trace and crash recovery is a non-event."
```

---

## Self-Review

**Spec coverage.** Every section of the design maps to a task: ledger + projection (2, 6), mastery curve (3), repair staging (4), review ladder (5), path engine (7), decide_next (8), rank_gaps (9), endpoints (10), Journey screen (11), Quiz wiring (12). The schema gap the spec missed is Task 1.

**Two spec items deliberately not implemented here**, both flagged rather than silently dropped:

- **The Today screen.** The spec describes Journey *and* Today. `decide_next` is built and exposed at `POST /api/student/<id>/next` (Task 8, Task 10) but has no dedicated screen. Task 11's Journey screen covers "where a student stands"; the "what to do today" surface is a thin renderer over an endpoint that already works and should be its own task once the loop above is proven. **Add it as Task 13 if you want it in this pass.**
- **Migration of S001 and S999.** The spec says both keep their profile as a seed with a `projection_from` marker. Task 1 adds the field and Task 6's `CARRIED_FIELDS` carries it, but no task *sets* it. That is correct for now: neither student has a ledger, so nothing will reproject over them. The marker should be written when their first real session is logged.

**Placeholder scan.** No TBDs. Every code step contains the actual code. Every test step contains the actual assertions.

**Type consistency.** `is_mastered(profile, node_id)` takes that argument order everywhere. `display_stage(entry, today)` likewise. `reproject` returns `(profile, warnings)` in Task 6 and is destructured that way in Task 10. `assemble_candidates` returns `(candidates, forced)` in Task 8 and is destructured that way in `decide_next` and in the tests. Candidate option keys are `f"{id}|{kind}"` when built and split the same way when read.

**One ordering constraint:** Task 12 Step 3 adds `question_id` to the quiz transcript. Task 6's projection skips items whose `(node, question)` pair is unknown, so without that step every logged item would be warned about and discarded. Do not reorder these.
