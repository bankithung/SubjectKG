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
from datetime import date, timedelta
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


class ProfileInvalid(ValueError):
    """A projection produced something the profile schema would reject."""


# Mirrors the `required` arrays in harness/schemas/student-profile.schema.json.
# Deliberately NOT a general JSON Schema engine: this repo is stdlib-only, so
# `jsonschema` is unavailable, and validate_kg.py has only ever checked the
# knowledge graph. A targeted invariant check over the fields the schema marks
# required honours the design's "fails loudly" promise at the right size.
_PROFILE_REQUIRED = ("id", "created", "grade", "mastery", "strategy_stats",
                     "behavior", "spaced_repetition")
_MASTERY_REQUIRED = ("score", "evidence_count", "last_seen")
_REVIEW_REQUIRED = ("next_review", "interval_days")


def validate_profile(profile: dict) -> list:
    """-> a list of problems, empty when the profile is valid.

    Returns rather than raises so a caller can report every problem at once; a
    student's profile failing on six counts should say so in one message rather
    than six runs.
    """
    problems = []
    for key in _PROFILE_REQUIRED:
        if key not in profile:
            problems.append(f"missing required key {key!r}")

    for node_id, record in (profile.get("mastery") or {}).items():
        for key in _MASTERY_REQUIRED:
            if key not in record:
                problems.append(f"mastery[{node_id}] missing {key!r}")
        score = record.get("score")
        if score is not None and not 0 <= score <= 1:
            problems.append(f"mastery[{node_id}] score {score} outside [0, 1]")

    for node_id, entry in (profile.get("spaced_repetition") or {}).items():
        for key in _REVIEW_REQUIRED:
            if key not in entry:
                problems.append(f"spaced_repetition[{node_id}] missing {key!r}")

    return problems


def save_profile(student_id: str, profile: dict, root: Path = ROOT) -> None:
    """Write a profile, refusing to persist one the schema would reject.

    The ledger is the source of truth, so a refused write costs nothing: the
    projection can be rerun once the cause is fixed. Writing a malformed profile
    over a good one would cost the student their model.
    """
    problems = validate_profile(profile)
    if problems:
        raise ProfileInvalid(
            f"refusing to write an invalid profile for {student_id}: "
            + "; ".join(problems)
        )
    atomic_write_json(student_dir(student_id, root) / "profile.json", profile)
