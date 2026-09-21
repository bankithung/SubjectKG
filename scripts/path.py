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
