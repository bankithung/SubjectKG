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
