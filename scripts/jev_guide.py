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
