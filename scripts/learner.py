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
import copy
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
    """The folder for one student, containment-checked.

    The server allowlists student_id before it ever reaches here (see
    jev_serve.py), but that check lives at the edge and a future call site could
    forget it. This is the second, independent layer: whatever student_id turns
    out to be, the path handed back is verified to still be inside students/
    before anything downstream can read or write through it.
    """
    root = Path(root)
    students_root = (root / "students").resolve()
    try:
        folder = (students_root / student_id).resolve()
    except (OSError, ValueError) as exc:
        raise ValueError(f"invalid student id {student_id!r}: {exc}") from None
    if folder != students_root and students_root not in folder.parents:
        raise ValueError(f"invalid student id {student_id!r}: escapes students/")
    return folder


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
    "affect", "calibration", "projection_from", "seed",
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
    warnings = []
    retention = profile.get("retention", {}) or {}

    # A profile written before session logging existed cannot be reprojected faithfully -
    # the evidence was never recorded. Rather than fabricate a ledger to match, such a
    # profile carries `projection_from`: the date its ledger becomes authoritative. Its
    # stored model is the starting point, and only logs from that date onward replay on
    # top. Without the marker this is a pure replay, which is right for every student
    # enrolled after logging began.
    projection_from = seed.get("projection_from")
    # The pre-ledger snapshot lives in its own nested object, NOT in the profile's own
    # mastery/session_count. Those are the projection's OUTPUT: /session saves them back
    # over profile.json, so reading the starting state from them would mean every later
    # projection began from a profile that already contained the logs it was about to
    # replay - counting each session twice, compounding with every sitting. `seed` is
    # copied through verbatim by CARRIED_FIELDS and never recomputed, so what the next
    # projection starts from cannot drift.
    frozen = seed.get("seed") or {}
    if projection_from and frozen:
        # Deep-copied because project() must not mutate its arguments.
        mastery = copy.deepcopy(frozen.get("mastery") or {})
        schedule = copy.deepcopy(frozen.get("spaced_repetition") or {})
        prior_sessions = int(frozen.get("session_count") or 0)
        # Sessions before the marker are already baked into the seed; replaying them
        # would count the same evidence twice.
        logs = [log for log in logs if log["date"] >= projection_from]
    else:
        mastery, schedule = {}, {}
        prior_sessions = 0

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
            # A record reused verbatim from a seed (rather than freshly created above)
            # may be missing these two optional fields - the schema requires only
            # score/evidence_count/last_seen. Normalise here, at the point the record
            # is about to be read and mutated anyway, so an untouched seeded node (no
            # log this replay) is never touched and stays byte-identical to the seed.
            record.setdefault("conceptual_ok", False)
            record.setdefault("misconceptions_active", [])

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
    profile["session_count"] = prior_sessions + len(logs)
    profile["last_session"] = (logs[-1]["date"] if logs
                               else frozen.get("last_session") if projection_from else None)
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


MAX_SITTINGS_PER_DAY = 500


def append_session(student_id: str, log: dict, root: Path = ROOT) -> Path:
    """Add one session log to the ledger. Never overwrites an existing file.

    Names the file <date>-<nn>.json, picking the next free nn. Two sittings on the
    same day get -01 and -02 and replay in that order.

    `date` is validated before it ever touches a filename: it goes straight into
    one, so an unvalidated value (`../../evil`, say) is a path-traversal write
    primitive, not just a malformed log. Validated here rather than only at the
    server's edge, so the ledger's own naming invariant holds for every caller,
    present or future - nothing is created, not even the sessions/ folder, until
    the date has been confirmed safe.

    jev_serve.py is a ThreadingHTTPServer, so two /session posts for the same
    student can run this concurrently. Picking the next free index with an
    `.exists()` check and then writing separately (as this used to) has a race:
    both threads can see the same index free before either has written, and the
    second write then overwrites the first, silently destroying a log - the one
    thing the ledger's append-only design says can never happen. `os.O_CREAT |
    os.O_EXCL` makes "does this filename exist" and "claim it" a single atomic
    kernel operation, so a losing thread gets FileExistsError and retries the
    next index instead of clobbering the winner. Bounded so a pathological case
    (hundreds of sittings logged for one student on one day) raises instead of
    looping forever.
    """
    day = log["date"]
    try:
        date.fromisoformat(day)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"log date {day!r} is not a valid ISO date: {exc}") from None
    folder = student_dir(student_id, root) / "sessions"
    folder.mkdir(parents=True, exist_ok=True)
    payload = {key: value for key, value in log.items() if key != "_file"}
    payload.setdefault("$schema", "../../../harness/schemas/session-log.schema.json")
    encoded = json.dumps(payload, ensure_ascii=False, indent=1).encode("utf-8")

    for index in range(1, MAX_SITTINGS_PER_DAY + 1):
        target = folder / f"{day}-{index:02d}.json"
        try:
            fd = os.open(str(target), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            continue
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(encoded)
                stream.flush()
                os.fsync(stream.fileno())
        except BaseException:
            try:
                target.unlink()
            except OSError:
                pass
            raise
        return target

    raise RuntimeError(
        f"could not allocate a session log filename for {student_id!r} on "
        f"{day!r} after {MAX_SITTINGS_PER_DAY} attempts"
    )
