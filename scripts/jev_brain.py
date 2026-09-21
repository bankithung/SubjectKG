#!/usr/bin/env python3
"""The judgment layer: what SubjectKG asks Jev, and how the answers become decisions.

Design rule, taken from TypeSafe's building guide: **code owns the workflow, the
model supplies the semantic step.** Traversing prerequisites, scoring a beam,
writing to profile.json and enforcing the "never teach on top of a gap" rule are
all plain Python here. Jev is asked only the questions that genuinely need to
understand meaning:

  route()          "which of 162 concepts is this child actually asking about?"
  diagnose()       "this free-text answer is wrong - which of the 570 documented
                    misconceptions does it reveal, how deep is it, and what next?"
  audit_edges()    "is this prerequisite edge real, and is hard/soft the right label?"
  audit_questions() "is every distractor in this item actually diagnostic?"

Two of those the harness does badly today (routing is a substring grep); two it
cannot do at all (free-text diagnosis, and auditing itself at scale).

Each workflow batches every judgment it needs over one copy of the state, because
the state is what costs tokens. diagnose() asks five questions in a single round
trip for roughly the price of one.
"""
import io
import json
import math
import re
from pathlib import Path

from jev_client import JevClient, choice, noul, read_choice, read_noul, read_score, score

ROOT = Path(__file__).resolve().parent.parent

# How many strands the beam keeps alive into the node-level decision. K=1 is greedy
# and, as the hierarchical-classification cookbook puts it, "one early mistake cannot
# be recovered" - a question about "sharing a pizza between 3 friends" can read as
# Numbers or as Measurement, and we would rather pay one extra parallel call than
# route a child to the wrong strand.
BEAM_WIDTH = 2

# Cap the per-option judgments in one request. Items have 4 options in this graph;
# the cap only guards against a malformed item ballooning a batch.
MAX_OPTIONS_JUDGED = 6


def clip(text: str, limit: int) -> str:
    """Trim to a sentence-ish boundary. Criteria must stay readable but not bloat state."""
    text = " ".join((text or "").split())
    if len(text) <= limit:
        return text
    cut = text[:limit]
    stop = max(cut.rfind(". "), cut.rfind("; "))
    return (cut[: stop + 1] if stop > limit * 0.5 else cut.rstrip() + "...")


# ------------------------------------------------------------------ the graph


class KG:
    """kg/math.json + kg/spine.json, indexed for lookup. Read once at startup."""

    def __init__(self, root: Path = ROOT):
        self.data = json.loads(io.open(root / "kg" / "math.json", encoding="utf-8").read())
        spine = json.loads(io.open(root / "kg" / "spine.json", encoding="utf-8").read())
        self.strands = self.data["strands"]
        self.strand_summaries = spine.get("strand_summaries", {})
        self.nodes = self.data["nodes"]
        self.by_id = {n["id"]: n for n in self.nodes}

        self.by_strand = {}
        for node in self.nodes:
            self.by_strand.setdefault(node["strand"], []).append(node)

        # Reverse edges: the graph stores prerequisites, but "what does this unlock?"
        # is the question students actually ask, so precompute it.
        self.unlocks = {n["id"]: [] for n in self.nodes}
        for node in self.nodes:
            for prereq in node.get("prerequisites", []):
                if prereq["id"] in self.unlocks:
                    self.unlocks[prereq["id"]].append(
                        {"id": node["id"], "strength": prereq.get("strength", "hard")}
                    )

    def summary(self, node: dict) -> dict:
        """The slim shape the browser needs - the full graph is 2.6 MB and stays server-side."""
        return {
            "id": node["id"],
            "title": node["title"],
            "grade": node["grade"],
            "strand": node["strand"],
            "strand_name": self.strands.get(node["strand"], node["strand"]),
            "description": node.get("description", ""),
            "difficulty": node.get("difficulty"),
            "est_minutes": node.get("est_minutes"),
            "centrality": node.get("centrality"),
            "prerequisites": node.get("prerequisites", []),
            "unlocks": self.unlocks.get(node["id"], []),
            "misconceptions": node.get("misconceptions", []),
            "questions": node.get("questions", []),
            "learning_outcomes": node.get("learning_outcomes", []),
            "micros": [
                {"id": m["id"], "title": m["title"], "description": m.get("description", "")}
                for m in node.get("micros", [])
            ],
        }

    def edges(self):
        """Every prerequisite edge as (parent_node, child_node, declared_strength, reason)."""
        out = []
        for node in self.nodes:
            for prereq in node.get("prerequisites", []):
                parent = self.by_id.get(prereq["id"])
                if parent:
                    out.append((parent, node, prereq.get("strength", "hard"), prereq.get("reason", "")))
        return out

    def all_questions(self):
        """Every diagnostic item as (node, question)."""
        return [(n, q) for n in self.nodes for q in n.get("questions", [])]


# ------------------------------------------------------------ 1. semantic routing


INTENTS = {
    "learn_concept": "Wants to learn or understand a topic - 'teach me X', 'I don't get X', 'what is X'",
    "diagnose_error": "Is reporting a specific wrong answer or a mistake they made, and wants to know why it is wrong",
    "prerequisites": "Wants to know what must be learned BEFORE a topic - 'what do I need before X', 'am I ready for X'",
    "whats_next": "Wants to know what a topic leads to, or what to study next after finishing something",
    "practice": "Wants questions, exercises or a test rather than an explanation",
    "unclear": "The request does not fit any of the above, or is too vague to act on",
}

BANDS = {
    "g1-3": "Early primary, roughly ages 6-8: counting, place value to 999, addition and subtraction, basic shapes",
    "g4-5": "Upper primary, roughly ages 9-10: multiplication and division, fractions, decimals, area and perimeter",
    "g6-8": "Middle school, roughly ages 11-13: integers, ratio, percentages, introductory algebra, linear equations",
    "g9-10": "Secondary, roughly ages 14-15: polynomials, coordinate geometry, trigonometry, circles, statistics",
    "g11-12": "Senior secondary, roughly ages 16-17: sets and functions, calculus, vectors, 3D geometry, probability",
}

BAND_ORDER = ["g1-3", "g4-5", "g6-8", "g9-10", "g11-12"]
BAND_OF_GRADE = {g: b for b, grades in {
    "g1-3": (1, 2, 3), "g4-5": (4, 5), "g6-8": (6, 7, 8),
    "g9-10": (9, 10), "g11-12": (11, 12),
}.items() for g in grades}

# Probability mass bleeds into neighbouring bands at this rate per step, because
# "two heads in a row" is a fair question at Class 8 and at Class 11.
BAND_DECAY = 0.5


def band_affinity(grade: int, band_probabilities: dict) -> float:
    """How well a node's school level matches where the learner's question sits.

    Reported for inspection only - it is NOT blended into a ranking. An earlier
    version multiplied it into the score with a hand-tuned weight, which meant a
    constant in this file was quietly deciding between Class 10 and Class 12
    probability. That decision now belongs to Jev, which sees the finalists and
    their levels together and picks; this number just shows what the level
    judgment implied, so the two can be compared.
    """
    node_band = BAND_OF_GRADE.get(grade)
    if node_band not in BAND_ORDER:
        return 1.0
    node_index = BAND_ORDER.index(node_band)
    return sum(
        probability * (BAND_DECAY ** abs(BAND_ORDER.index(band) - node_index))
        for band, probability in band_probabilities.items()
        if band in BAND_ORDER
    )


def route(client: JevClient, kg: KG, utterance: str, beam_width: int = BEAM_WIDTH) -> dict:
    """Map a free-text learner utterance onto the graph, by beam search over strand -> node.

    Tier 1 is a single batched request that asks four independent things about the
    same utterance at once: is this even maths (a guardrail), what does the learner
    want (so the caller knows whether to teach, test, or walk prerequisites), which
    strand, and which grade band. They cannot see each other's answers, which is
    exactly why they are safe to batch.

    Tier 2 opens one request per surviving strand, in parallel, choosing among that
    strand's nodes. Candidates are ranked by the geometric mean of the edge
    probabilities along their path, so a shallow confident path and a deep confident
    path stay comparable.
    """
    strand_options = {
        key: clip(kg.strand_summaries.get(key, name), 260)
        for key, name in kg.strands.items()
    }

    tier1 = client.ask(
        {"learner_says": utterance},
        {
            "is_maths": noul(
                "Is `learner_says` a request about school mathematics that a maths tutor should handle?",
                true="It is about mathematics, a maths topic, a maths problem, or the learner's own maths work",
                false="It is off-topic, a greeting with no maths content, or about a different subject entirely",
            ),
            "intent": choice("What does the learner want to happen next?", INTENTS),
            "strand": choice(
                "Which branch of school mathematics is `learner_says` about?", strand_options
            ),
            "band": choice(
                "Judging only by the mathematical content mentioned, which school stage does "
                "`learner_says` sit at?",
                BANDS,
            ),
        },
    )
    answers = tier1["answers"]
    is_maths = read_noul(answers["is_maths"])
    intent, intent_conf, intent_probs = read_choice(answers["intent"])
    _, _, strand_probs = read_choice(answers["strand"])
    band, band_conf, band_probs = read_choice(answers["band"])

    requests_made = 1
    tier1_ms = tier1["_meta"]["ms"]

    # Keep the strands worth exploring: the top K by probability, dropping anything
    # the model effectively ruled out - but never drop the leader, so a diffuse
    # distribution still produces a route instead of an empty result.
    ranked = sorted(strand_probs.items(), key=lambda kv: -kv[1])[:beam_width]
    beam = [(s, p) for s, p in ranked if p > 0.01] or ranked[:1]

    jobs, job_strands = [], []
    for strand_key, _ in beam:
        nodes = kg.by_strand.get(strand_key, [])
        if not nodes:
            continue
        options = {
            n["id"]: f"Class {n['grade']} - {n['title']}: {clip(n.get('description', ''), 200)}"
            for n in nodes
        }
        options["none_of_these"] = (
            "None of the listed concepts matches what the learner is asking about."
        )
        jobs.append((
            {"learner_says": utterance},
            {
                "node": choice(
                    "Which single concept from this list is the learner asking about? "
                    "Match on the mathematical content, not on shared words.",
                    options,
                )
            },
        ))
        job_strands.append(strand_key)

    candidates = []
    tier2_ms = 0
    if jobs:
        for strand_key, (_, strand_prob), outcome in zip(
            job_strands, beam, client.ask_many(jobs)
        ):
            if not outcome["ok"]:
                continue
            requests_made += 1
            # Tier 2 calls go out together, so the tier contributes its slowest call
            # to wall-clock time, not their sum.
            tier2_ms = max(tier2_ms, outcome["result"]["_meta"]["ms"])
            node_answer = outcome["result"]["answers"]["node"]
            _, node_conf, node_probs = read_choice(node_answer)
            for node_id, node_prob in node_probs.items():
                if node_id == "none_of_these" or node_prob < 0.01:
                    continue
                node = kg.by_id.get(node_id)
                if not node:
                    continue
                # Geometric mean over the two decisions on this path, so paths of
                # equal length compare fairly and one weak hop is not hidden by
                # one strong hop. This is a RETRIEVAL score: its only job is to
                # decide which handful of concepts are worth putting in front of
                # Jev for the actual decision. It does not pick the winner.
                path_score = math.sqrt(strand_prob * node_prob)
                candidates.append({
                    "id": node_id,
                    "title": node["title"],
                    "grade": node["grade"],
                    "strand": node["strand"],
                    "strand_name": kg.strands.get(node["strand"], node["strand"]),
                    "description": clip(node.get("description", ""), 240),
                    "path_score": round(path_score, 4),
                    "level_fit": round(band_affinity(node["grade"], band_probs), 4),
                    "p_strand": round(strand_prob, 4),
                    "p_node": round(node_prob, 4),
                })

    candidates.sort(key=lambda c: -c["path_score"])

    shortlist = candidates[:8]

    # ---- Tier 3: Jev decides -------------------------------------------------
    # The beam produced a shortlist. Which one the tutor actually opens is a
    # judgment, not arithmetic, so Jev makes it rather than a weighting formula.
    # Crucially it now sees all finalists side by side WITH their school levels,
    # which is what a per-candidate score can never show: the choice between
    # Class 10 and Class 12 probability is a comparison, and comparisons need
    # the alternatives in view.
    decision, adjudication_ms = None, 0
    if len(shortlist) > 1:
        options = {
            c["id"]: f"Class {c['grade']} · {c['title']} — {clip(c['description'], 190)}"
            for c in shortlist
        }
        options["none_of_these"] = (
            "None of these concepts is what the learner is asking about."
        )
        verdict = client.ask(
            {
                "learner_says": utterance,
                "reading": {"intent": intent, "apparent_school_stage": band},
            },
            {
                "best": choice(
                    "Which one of these concepts should the tutor open for this learner? "
                    "Weigh both what they are asking about and the school level the "
                    "question is pitched at: prefer the level where this idea is actually "
                    "taught first, not the most advanced concept that mentions it.",
                    options,
                ),
            },
        )
        adjudication_ms = verdict["_meta"]["ms"]
        requests_made += 1
        picked, pick_conf, pick_probs = read_choice(verdict["answers"]["best"])
        chosen = next((c for c in shortlist if c["id"] == picked), None)
        decision = {
            "id": picked,
            "confidence": round(pick_conf, 4),
            "probabilities": {k: round(v, 4) for k, v in
                              sorted(pick_probs.items(), key=lambda kv: -kv[1]) if v >= 0.005},
            # Did Jev's judgment differ from what the retrieval maths ranked first?
            # This is the interesting column: it is where the model earns its place.
            "overruled_ranking": bool(chosen and shortlist and chosen["id"] != shortlist[0]["id"]),
        }
        if chosen:
            chosen = dict(chosen, decided_by="jev", decision_confidence=round(pick_conf, 4))
    else:
        chosen = shortlist[0] if shortlist else None
        if chosen:
            chosen = dict(chosen, decided_by="only_candidate", decision_confidence=None)

    return {
        "utterance": utterance,
        "is_maths": round(is_maths, 4),
        "intent": {"value": intent, "confidence": round(intent_conf, 4),
                   "probabilities": {k: round(v, 4) for k, v in intent_probs.items()}},
        "band": {"value": band, "confidence": round(band_conf, 4),
                 "probabilities": {k: round(v, 4) for k, v in band_probs.items()}},
        "beam": [{"strand": s, "name": kg.strands.get(s, s), "probability": round(p, 4)} for s, p in beam],
        "candidates": shortlist,
        "retrieval_top": shortlist[0] if shortlist else None,
        "decision": decision,
        "top": chosen,
        "requests": requests_made,
        "wall_ms": tier1_ms + tier2_ms + adjudication_ms,
    }


def keyword_route(kg: KG, utterance: str, top_n: int = 5) -> list:
    """The baseline: what `/kg find` does today - token overlap against title and description.

    This is a fair implementation of the current approach, not a strawman: it
    stems crudely, weights title matches above description matches, and ignores
    stopwords. It still cannot know that "sharing a chocolate bar equally" means
    fractions, because those words appear nowhere in the fractions node.
    """
    stop = {
        "a", "an", "the", "i", "me", "my", "is", "are", "do", "dont", "don't", "to", "of",
        "in", "on", "for", "and", "or", "what", "how", "why", "can", "you", "it", "this",
        "that", "with", "get", "got", "not", "be", "have", "need", "want", "know", "understand",
    }
    terms = [t for t in re.findall(r"[a-z0-9]+", utterance.lower()) if t not in stop and len(t) > 2]
    if not terms:
        return []

    scored = []
    for node in kg.nodes:
        title = node["title"].lower()
        body = (node.get("description", "") + " " + " ".join(node.get("learning_outcomes", []))).lower()
        hits = 0.0
        for term in terms:
            stem = term[:-1] if term.endswith("s") and len(term) > 4 else term
            if stem in title:
                hits += 3.0
            elif stem in body:
                hits += 1.0
        if hits:
            scored.append({
                "id": node["id"], "title": node["title"], "grade": node["grade"],
                "strand": node["strand"], "score": round(hits / (len(terms) * 3.0), 4),
            })
    scored.sort(key=lambda s: -s["score"])
    return scored[:top_n]


# --------------------------------------------------- 2. free-text error diagnosis


NEXT_MOVES = {
    "advance": "The answer is right and well reasoned - move on to the next concept",
    "consolidate": "Right, but shaky or lucky - give one or two more items on the same skill before moving on",
    "targeted_hint": "Nearly there; one specific hint about the step they slipped on will fix it",
    "reteach_concept": "The underlying idea is not there - go back and reteach this concept in a different modality",
    "drop_to_prerequisite": "The gap is below this concept - stop and teach a prerequisite first",
}

DEPTH_LEVELS = [
    "A careless slip: the method is right and the student clearly understands the idea, "
    "they just mis-copied, mis-calculated or rushed",
    "A procedural gap: the student understands what the objects are but is applying the "
    "wrong rule or step to them",
    "A conceptual gap: the student does not understand what the objects themselves mean, "
    "so no amount of rule-practice will fix it",
]


def diagnose(client: JevClient, kg: KG, node_id: str, prompt: str,
             correct_answer: str, student_answer: str) -> dict:
    """Diagnose one student answer - including free text - against this node's misconceptions.

    This is the capability the harness does not currently have. Today a wrong answer
    can only be diagnosed if the student picked a pre-authored multiple-choice
    distractor that someone already tagged. A child who types "you just add the tops
    and bottoms" gets no diagnosis at all.

    Five judgments go out in one request over one copy of the state:

      is_correct      did they actually get it right (free text needs judging, not matching)
      misconception   which documented faulty model this reveals - with two escape
                      hatches, because forcing a match onto a list that does not
                      contain the real answer is how a tutor mis-teaches
      depth           slip vs procedural vs conceptual - decides whether to hint or reteach
      confident       did they sound sure? a confident error is far more damaging than a
                      hesitant one, and the profile already tracks this flag
      next_move       the bounded action the tutor should take

    The answers map straight onto fields the student profile already defines:
    `mastery`, `error_signature`, and the confident-error flags in report.html.
    """
    node = kg.by_id.get(node_id)
    if not node:
        raise ValueError(f"unknown node {node_id}")

    misconceptions = node.get("misconceptions", [])
    options = {
        m["id"]: f"{m['description']} (how it shows up: {clip(m.get('signal', ''), 160)})"
        for m in misconceptions
    }
    # Always give the model somewhere honest to put an answer that does not fit.
    options["no_error"] = "The student's answer is correct; there is no misconception to report."
    options["other_error"] = (
        "The answer is wrong, but the reason is NOT any of the listed misconceptions - it is "
        "an arithmetic slip, a misread question, or a faulty model nobody has documented yet."
    )

    state = {
        "concept": node["title"],
        "concept_explained": clip(node.get("description", ""), 400),
        "school_class": node["grade"],
        "question_asked": prompt,
        "correct_answer": correct_answer,
        "student_answer": student_answer,
    }

    response = client.ask(state, {
        "is_correct": noul(
            "Judging the mathematics rather than the wording, is `student_answer` a correct "
            "answer to `question_asked`?",
            true="Mathematically correct, even if phrased loosely, abbreviated or misspelt",
            false="Mathematically wrong, or it does not answer the question that was asked",
        ),
        "misconception": choice(
            "The student gave `student_answer`. Which faulty mental model does that reveal? "
            "Choose the documented misconception whose description matches the student's actual "
            "reasoning - not merely one about the same topic.",
            options,
        ),
        "depth": score(
            "How deep is the problem behind `student_answer`?", DEPTH_LEVELS,
        ),
        "confident": noul(
            "Does the student sound sure of themselves in `student_answer`?",
            true="Stated flatly or assertively, with no hedging - they believe they are right",
            false="Hedged, guessed, questioned themselves, or said they did not know",
        ),
        "next_move": choice(
            "Given `student_answer`, what should the tutor do in the next two minutes?",
            NEXT_MOVES,
        ),
    })

    answers = response["answers"]
    is_correct = read_noul(answers["is_correct"])
    picked, pick_conf, pick_probs = read_choice(answers["misconception"])
    depth_value, depth_conf, depth_probs = read_score(answers["depth"])
    confident = read_noul(answers["confident"])
    move, move_conf, _ = read_choice(answers["next_move"])

    matched = next((m for m in misconceptions if m["id"] == picked), None)

    return {
        "node": {"id": node["id"], "title": node["title"], "grade": node["grade"]},
        "student_answer": student_answer,
        "is_correct": round(is_correct, 4),
        "misconception": {
            "id": picked,
            "confidence": round(pick_conf, 4),
            "description": matched["description"] if matched else options.get(picked, ""),
            "signal": matched.get("signal") if matched else None,
            # The remedy is authored by a human and stored in the graph. Jev selects
            # which one applies; it never writes teaching advice itself.
            "remedy": matched.get("remedy") if matched else None,
            "probabilities": {k: round(v, 4) for k, v in sorted(
                pick_probs.items(), key=lambda kv: -kv[1]) if v >= 0.005},
        },
        "depth": {
            "value": round(depth_value, 3),
            "confidence": round(depth_conf, 4),
            "label": DEPTH_LEVELS[min(int(round(depth_value)), len(DEPTH_LEVELS) - 1)].split(":")[0],
            "probabilities": {k: round(v, 4) for k, v in depth_probs.items()},
        },
        "confident": round(confident, 4),
        # The pattern the harness cares about most: sure of themselves, and wrong.
        "confident_error": round(confident * (1 - is_correct), 4),
        "next_move": {"value": move, "confidence": round(move_conf, 4),
                      "description": NEXT_MOVES.get(move, "")},
        "usage": response.get("usage", {}),
        "meta": response["_meta"],
    }


# --------------------------------------------------------- 3. auditing the graph


EDGE_VERDICTS = {
    "keep": "The edge is correct as it stands - right dependency, right hard/soft label, "
            "and the written reason explains it well",
    "relabel_soft": "The dependency is real but not blocking, so it should be marked soft "
                    "rather than hard",
    "relabel_hard": "The dependency is a genuine blocker and should be marked hard rather "
                    "than soft",
    "rewrite_reason": "The dependency and its label are right, but the written justification "
                      "is too vague or circular to be useful to a teacher",
    "remove": "There is no real dependency here; the edge should be deleted from the graph",
}

# These levels describe what happens to a CHILD if the edge is used as written.
# An earlier version described a reviewer's editing schedule instead - which Jev
# cannot know anything about - and it answered with confidence 0.0 on every edge,
# correctly reporting that the question was unanswerable from the state given.
EDGE_URGENCY = [
    "Harmless as written: a tutor following this edge would teach these two concepts in "
    "a sensible order, and no student is affected by the way it is labelled",
    "Occasionally harmful: a tutor following this edge would sometimes make a child wait "
    "for a prerequisite they did not need, or skip one that would have helped",
    "Actively harmful: a tutor following this edge would routinely teach these concepts in "
    "the wrong order, or block a child who was ready to move on",
]

# NOTE: there is deliberately no "the answer key is wrong" verdict here.
#
# An earlier version asked Jev to check whether the option marked correct really was
# correct. It flagged three items across the bank, and all three were false alarms -
# the keys for 50 - (12.50 + 36.75), for P(A|B) = 0.2/0.5, and for the median of
# 7,2,9,4,6 were all right. That is documented behaviour, not a fluke: the Jev 1.13
# model card says plainly, "Jev is not a calculator. We strongly recommend
# implementing any mathematical logic in code."
#
# Note the contrast with diagnose(), where `is_correct` works well - there the
# correct answer is supplied in the state, so the model is matching meaning
# ("five sixths" against "5/6") rather than computing. The rule that falls out:
# ask Jev to judge an answer only when the truth is given to it.
#
# Verifying answer keys belongs in scripts/validate_kg.py or with a human.
QUESTION_VERDICTS = {
    "keep": "The item works as a diagnostic: the wrong options each reveal a specific way "
            "of misunderstanding the concept",
    "rewrite_distractors": "Some wrong options are filler - they tell a teacher nothing "
                           "about how the student was thinking",
    "rewrite_prompt": "The question itself is unclear, ambiguous, or pitched at the wrong "
                      "level for this class",
    "retire": "The item is beyond repair and should be removed from the bank",
}

# Again phrased as the consequence for a real teacher reading a real answer, not as
# a position in someone's backlog.
QUESTION_URGENCY = [
    "Safe to use: a teacher who sees which option a student picked would draw the right "
    "conclusion about that student's thinking",
    "Sometimes misleading: for some students the option they pick would point a teacher "
    "at the wrong misunderstanding, or at none at all",
    "Reliably misleading: a teacher using this item would regularly conclude the wrong "
    "thing about what the student knows, or mark a correct answer wrong",
]


def audit_edges(client: JevClient, kg: KG, limit: int = 40, offset: int = 0, workers: int = 8):
    """Check prerequisite edges against the reasons their authors wrote down.

    289 edges were hand-authored with a written justification each. Nobody has ever
    re-read them all. Three judgments per edge, batched, one request per edge, all
    edges in flight at once - so 40 edges cost about as long as one.
    """
    edges = kg.edges()[offset: offset + limit]
    jobs = []
    for parent, child, strength, reason in edges:
        jobs.append((
            {
                "earlier_concept": {
                    "title": parent["title"], "class": parent["grade"],
                    "explained": clip(parent.get("description", ""), 300),
                },
                "later_concept": {
                    "title": child["title"], "class": child["grade"],
                    "explained": clip(child.get("description", ""), 300),
                },
                "author_says_dependency_is": strength,
                "author_reason": reason,
            },
            {
                "is_required": noul(
                    "Must a student understand `earlier_concept` before they can learn "
                    "`later_concept`?",
                    true="Yes - without the earlier concept the later one cannot be understood "
                         "or is reduced to memorising steps",
                    false="No - the later concept can be taught first, or the two are independent",
                ),
                "strength": choice(
                    "How strong is the dependency between `earlier_concept` and `later_concept`?",
                    {
                        "hard": "A true blocker: teaching the later concept without the earlier "
                                "one would leave the student memorising procedures they cannot reason about",
                        "soft": "Helpful but not blocking: the earlier concept makes the later one "
                                "easier or richer, and a motivated student could manage without it",
                        "none": "There is no real dependency between these two concepts",
                    },
                ),
                "reason_quality": score(
                    "How well does `author_reason` explain why this dependency exists?",
                    [
                        "Empty, circular, or it just restates the two titles without giving a reason",
                        "States a real reason but vaguely - a teacher could not act on it",
                        "Names the specific skill or idea that transfers, so a teacher knows exactly "
                        "what to check for",
                    ],
                ),
                # The verdict and the urgency are the decisions. They used to be a
                # formula over the three judgments above, with thresholds picked by
                # hand; now Jev states what should happen to the edge and how much
                # it matters, and the code only sorts by what it says.
                "verdict": choice(
                    "A curriculum editor is reviewing this prerequisite edge. What should "
                    "they do with it?",
                    EDGE_VERDICTS,
                ),
                "urgency": score(
                    "How urgently does this edge need a human editor's attention, given that "
                    "the graph is used to decide what a child is allowed to learn next?",
                    EDGE_URGENCY,
                ),
            },
        ))

    findings = []
    for (parent, child, strength, reason), outcome in zip(edges, client.ask_many(jobs, workers)):
        row = {
            "from": {"id": parent["id"], "title": parent["title"], "grade": parent["grade"]},
            "to": {"id": child["id"], "title": child["title"], "grade": child["grade"]},
            "declared": strength,
            "reason": reason,
        }
        if not outcome["ok"]:
            row.update({"error": outcome["error"]})
            findings.append(row)
            continue
        answers = outcome["result"]["answers"]
        required = read_noul(answers["is_required"])
        agreed, agree_conf, _ = read_choice(answers["strength"])
        quality, quality_conf, _ = read_score(answers["reason_quality"])
        verdict, verdict_conf, verdict_probs = read_choice(answers["verdict"])
        urgency, urgency_conf, _ = read_score(answers["urgency"])

        row.update({
            "required": round(required, 4),
            "model_strength": agreed,
            "strength_confidence": round(agree_conf, 4),
            "reason_quality": round(quality, 3),
            "reason_quality_confidence": round(quality_conf, 4),
            # Jev's decision about what to do, and how much it matters. No threshold
            # in this file turns a probability into a verdict any more.
            "verdict": verdict,
            "verdict_confidence": round(verdict_conf, 4),
            "verdict_probabilities": {k: round(v, 4) for k, v in
                                      sorted(verdict_probs.items(), key=lambda kv: -kv[1])
                                      if v >= 0.005},
            "urgency": round(urgency, 3),
            "urgency_confidence": round(urgency_conf, 4),
            "action_needed": verdict != "keep",
            "decided_by": "jev",
        })
        findings.append(row)

    # Sorted by Jev's own urgency, worst first - the ordering is its judgment too.
    findings.sort(key=lambda f: -f.get("urgency", 0))
    return {"total_edges": len(kg.edges()), "audited": len(findings), "offset": offset,
            "findings": findings}


def audit_questions(client: JevClient, kg: KG, limit: int = 30, offset: int = 0, workers: int = 8):
    """Check diagnostic items: exactly one right answer, and every distractor earning its place.

    The harness's rule 30 says no question may be random - every wrong option must
    detect a named misconception or slip. This is that rule, enforced mechanically
    across all 494 items instead of trusted.
    """
    items = kg.all_questions()[offset: offset + limit]
    jobs = []
    for node, question in items:
        options = []
        for index, option in enumerate(question.get("options", [])):
            options.append({
                "label": chr(65 + index),
                "text": option.get("text", ""),
                "marked_correct": bool(option.get("correct")),
                "meant_to_detect": option.get("misconception") or option.get("diagnosis") or None,
            })

        # One judgment per wrong option: what is a student who picks THIS thinking?
        # The graph's rule is that no option is filler - every distractor detects a
        # named misconception. Until now that was an assertion. These questions ask
        # Jev to assign each distractor independently, so the authored tag can be
        # checked against a judgment that never saw it.
        #
        # They ride along in the same request as the whole-item questions below.
        # The state - concept, prompt, every option - is transmitted once and
        # answered six or seven times, which is the entire economic argument for
        # batching: the document dominates the cost, not the questions.
        option_questions = {}
        misconception_options = {
            m["id"]: f"{m['description']} (how it shows up: {clip(m.get('signal', ''), 140)})"
            for m in node.get("misconceptions", [])
        }
        for index, option in enumerate(options):
            if option["marked_correct"] or index >= MAX_OPTIONS_JUDGED:
                continue
            option_questions[f"option_{index}"] = choice(
                f"Option {option['label']} says: \"{option['text']}\". A student who picks "
                f"option {option['label']} instead of the correct answer is thinking what? "
                f"Choose the misunderstanding that would actually lead someone to this "
                f"specific answer - not merely one that exists for this topic.",
                dict(misconception_options, **{
                    "careless_slip": "No faulty model - this is what you get from a "
                                     "miscalculation, a misread, or a moment's carelessness by "
                                     "a student who understands the concept",
                    "not_diagnostic": "Nothing in particular - the option is obviously wrong or "
                                      "arbitrary, so almost nobody would pick it and picking it "
                                      "reveals nothing about the student's thinking",
                    "actually_correct": "Nothing is wrong with it - this option is also a "
                                        "correct answer to the question",
                }),
            )

        jobs.append((
            {
                "concept": node["title"],
                "school_class": node["grade"],
                "question": question.get("prompt", ""),
                "options": options,
            },
            {
                **option_questions,
                # No "is the key correct" or "is there exactly one right answer" here:
                # both require computing each option, which is the documented weak
                # spot. See the note above QUESTION_VERDICTS.
                "distractor_quality": score(
                    "How well do the wrong options work as diagnostic distractors - that is, would "
                    "a student who holds a specific misunderstanding be pulled to a specific one?",
                    [
                        "Wrong options are obviously wrong or random, so choosing one tells the "
                        "teacher nothing about how the student was thinking",
                        "Some wrong options are tempting and informative, others are filler",
                        "Every wrong option corresponds to a specific plausible way of thinking, so "
                        "the option a student picks identifies exactly what they misunderstand",
                    ],
                ),
                "age_appropriate": noul(
                    "Is `question` readable and answerable by a typical student in `school_class`?",
                    true="The vocabulary, context and mathematical demand suit that class",
                    false="Too hard, too easy, or written in language that class would not follow",
                ),
                "verdict": choice(
                    "An editor is reviewing this diagnostic item. What should they do with it?",
                    QUESTION_VERDICTS,
                ),
                "urgency": score(
                    "How urgently does this item need fixing, given that a teacher reads the "
                    "option a student picks as evidence of what that student misunderstands?",
                    QUESTION_URGENCY,
                ),
            },
        ))

    findings = []
    for (node, question), outcome in zip(items, client.ask_many(jobs, workers)):
        row = {
            "node": {"id": node["id"], "title": node["title"], "grade": node["grade"]},
            "question_id": question.get("id"),
            "prompt": question.get("prompt", ""),
            "options": question.get("options", []),
        }
        if not outcome["ok"]:
            row["error"] = outcome["error"]
            findings.append(row)
            continue
        answers = outcome["result"]["answers"]
        quality, _, _ = read_score(answers["distractor_quality"])
        age_ok = read_noul(answers["age_appropriate"])
        verdict, verdict_conf, verdict_probs = read_choice(answers["verdict"])
        urgency, urgency_conf, _ = read_score(answers["urgency"])

        # Per-option verdicts: what Jev says each distractor detects, next to what
        # the author tagged it with. Disagreement is the useful output - it means
        # either the tag is wrong or the option does not do the job it was written
        # for, and both are things a question bank wants to know.
        option_rows, disagreements, untagged_but_useful, filler = [], 0, 0, 0
        for index, option in enumerate(question.get("options", [])):
            if option.get("correct"):
                continue
            answer = answers.get(f"option_{index}")
            if not answer:
                continue
            picked, picked_conf, _ = read_choice(answer)
            authored = option.get("misconception")
            authored_kind = ("misconception" if authored
                             else "slip" if option.get("diagnosis") else None)
            jev_kind = ("misconception" if picked in
                        {m["id"] for m in node.get("misconceptions", [])}
                        else picked)

            # Agreement means both name the same specific misconception, or both
            # call it a slip. An untagged option can never "agree".
            agrees = (authored is not None and picked == authored) or (
                authored is None and authored_kind == "slip" and picked == "careless_slip")

            if picked == "not_diagnostic":
                filler += 1
            elif authored is None and jev_kind == "misconception":
                untagged_but_useful += 1
            elif not agrees and authored_kind is not None:
                disagreements += 1

            detected = next((m for m in node.get("misconceptions", []) if m["id"] == picked), None)
            option_rows.append({
                "label": chr(65 + index),
                "text": option.get("text", ""),
                "authored": authored or authored_kind,
                "jev": picked,
                "jev_description": detected["description"] if detected else None,
                "confidence": round(picked_conf, 4),
                "agrees": agrees,
                "kind": jev_kind,
            })

        row.update({
            "options_judged": option_rows,
            "option_disagreements": disagreements,
            "option_untagged_but_diagnostic": untagged_but_useful,
            "option_filler": filler,
            "distractor_quality": round(quality, 3),
            "age_appropriate": round(age_ok, 4),
            "verdict": verdict,
            "verdict_confidence": round(verdict_conf, 4),
            "verdict_probabilities": {k: round(v, 4) for k, v in
                                      sorted(verdict_probs.items(), key=lambda kv: -kv[1])
                                      if v >= 0.005},
            "urgency": round(urgency, 3),
            "urgency_confidence": round(urgency_conf, 4),
            "action_needed": verdict != "keep",
            "decided_by": "jev",
        })
        findings.append(row)

    findings.sort(key=lambda f: -f.get("urgency", 0))
    return {"total_questions": len(kg.all_questions()), "audited": len(findings),
            "offset": offset, "findings": findings}


# ------------------------------------------------------------- 4. batch + compare


def route_batch(client: JevClient, kg: KG, utterances: list, workers: int = 6) -> list:
    """Route many utterances at once. Each one is its own beam search, run in parallel.

    Routing cannot be collapsed into a single batched request the way diagnose() can,
    because every utterance is a *different state* - and batching only saves money
    when questions share one state. What it can do is overlap the round trips, so
    twenty prompts cost about the wall-clock of the slowest one rather than twenty
    in a row.
    """
    import concurrent.futures

    results = [None] * len(utterances)
    if not utterances:
        return results
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(workers, len(utterances))) as pool:
        futures = {pool.submit(route, client, kg, text): i for i, text in enumerate(utterances)}
        for future in concurrent.futures.as_completed(futures):
            index = futures[future]
            try:
                results[index] = future.result()
            except Exception as exc:  # noqa: BLE001 - one bad prompt must not sink the run
                results[index] = {"utterance": utterances[index], "error": str(exc),
                                  "candidates": [], "top": None}
    return results


def compare(client: JevClient, kg: KG, utterances: list, workers: int = 6) -> dict:
    """Jev's semantic routing against the graph's current keyword lookup, same prompts.

    The baseline is the real mechanism `/kg find` uses today - token overlap against
    node titles and descriptions - not a strawman. The comparison is about *reach*,
    not speed: keyword search is instant and free, and will stay the right tool when
    the learner already knows the technical term. It fails the moment a child
    describes a problem in their own words, which is most of the time.
    """
    routed = route_batch(client, kg, utterances, workers)
    rows, agreements, keyword_misses = [], 0, 0

    for utterance, result in zip(utterances, routed):
        jev_top = result.get("top")
        keyword_hits = keyword_route(kg, utterance)
        keyword_top = keyword_hits[0] if keyword_hits else None

        if not keyword_top:
            keyword_misses += 1
        agreed = bool(jev_top and keyword_top and jev_top["id"] == keyword_top["id"])
        if agreed:
            agreements += 1

        rows.append({
            "utterance": utterance,
            "jev": None if not jev_top else {
                "id": jev_top["id"], "title": jev_top["title"],
                "grade": jev_top["grade"],
                # Jev's own certainty in the pick, not a computed ranking number.
                "confidence": jev_top.get("decision_confidence"),
                "retrieval_score": jev_top.get("path_score"),
            },
            "keyword": None if not keyword_top else {
                "id": keyword_top["id"], "title": keyword_top["title"],
                "grade": keyword_top["grade"], "score": keyword_top["score"],
            },
            "agree": agreed,
            "intent": result.get("intent", {}).get("value"),
            "is_maths": result.get("is_maths"),
            "requests": result.get("requests", 0),
            "wall_ms": result.get("wall_ms", 0),
            # True when Jev's adjudication picked something other than whatever the
            # retrieval maths ranked first - the clearest single signal of the model
            # contributing judgment rather than ratifying a lookup.
            "overruled_ranking": bool((result.get("decision") or {}).get("overruled_ranking")),
        })

    total = len(utterances) or 1
    return {
        "rows": rows,
        "summary": {
            "prompts": len(utterances),
            "agreed": agreements,
            "diverged": len(utterances) - agreements,
            "keyword_found_nothing": keyword_misses,
            "agreement_rate": round(agreements / total, 3),
        },
    }


# ------------------------------------------------------- 5. end-of-quiz verdict


MASTERY_LEVELS = [
    "Not yet: the student got the core idea wrong, or was right only where the question "
    "did not really test the concept",
    "Shaky: some answers were right, but the reasoning shown was uneven, guessed, or "
    "leaned on a rule they could not justify",
    "Solid: consistently right, with reasoning that shows the idea is understood rather "
    "than the procedure memorised, and any error was a passing slip",
]

QUIZ_NEXT = {
    "advance": "They have this. Move on to a concept that builds on it",
    "consolidate": "Basically there, but give a few more items on this same concept before "
                   "moving on",
    "reteach_differently": "The idea has not landed. Teach this same concept again in a "
                           "different way - a manipulative, a drawing, a story",
    "drop_to_prerequisite": "The gap is below this concept. Stop here and go back to "
                            "something this one depends on",
}


def quiz_verdict(client: JevClient, kg: KG, node_id: str, transcript: list) -> dict:
    """Judge a whole sitting: did this student understand the concept, and what now?

    The per-answer diagnoses already happened one at a time. This is the judgment
    that needs the whole transcript at once - a student who gets two right and the
    third wrong for the same underlying reason is in a different place from one who
    slipped once on arithmetic, and you cannot see that one answer at a time.

    Four judgments over one state, in a single request. Deliberately NOT computed
    from the individual results: "three out of four" is a number, not an assessment,
    and the graph's whole premise is that which ones you got wrong matters more than
    how many.
    """
    node = kg.by_id.get(node_id)
    if not node:
        raise ValueError(f"unknown node {node_id}")

    misconceptions = node.get("misconceptions", [])
    persistent_options = {
        m["id"]: f"{m['description']} kept showing up across their answers"
        for m in misconceptions
    }
    persistent_options["none_persistent"] = (
        "No single faulty model runs through their answers - any errors were unrelated "
        "one-offs, or there were no errors."
    )

    state = {
        "concept": node["title"],
        "concept_explained": clip(node.get("description", ""), 400),
        "school_class": node["grade"],
        "what_mastery_looks_like": node.get("learning_outcomes", []),
        "the_sitting": [
            {
                "question": item.get("prompt", ""),
                "correct_answer": item.get("correct", ""),
                "student_answered": item.get("answer", ""),
                "was_right": item.get("is_correct"),
                "error_showed": item.get("misconception"),
                "sounded_sure": item.get("confident"),
            }
            for item in transcript
        ],
    }

    response = client.ask(state, {
        "mastery": score(
            "Judging `the_sitting` as a whole against `what_mastery_looks_like`, where is "
            "this student on this concept?",
            MASTERY_LEVELS,
        ),
        "persistent": choice(
            "Looking across every answer in `the_sitting` rather than at any one of them, "
            "is there a single faulty mental model behind this student's errors?",
            persistent_options,
        ),
        "next_step": choice(
            "What should the tutor do at the end of this sitting?", QUIZ_NEXT,
        ),
        "guessing": noul(
            "Do the right answers in `the_sitting` look like understanding rather than "
            "lucky guesses?",
            true="The reasoning or wording shows they knew why, not just what",
            false="The right answers could as easily have been guesses - short, unexplained, "
                  "or inconsistent with the wrong ones",
        ),
    })

    answers = response["answers"]
    mastery, mastery_conf, mastery_probs = read_score(answers["mastery"])
    persistent, persistent_conf, _ = read_choice(answers["persistent"])
    step, step_conf, _ = read_choice(answers["next_step"])
    understood = read_noul(answers["guessing"])

    matched = next((m for m in misconceptions if m["id"] == persistent), None)

    return {
        "node": {"id": node["id"], "title": node["title"], "grade": node["grade"]},
        "answered": len(transcript),
        "mastery": {
            "value": round(mastery, 3),
            "confidence": round(mastery_conf, 4),
            "label": MASTERY_LEVELS[min(int(round(mastery)), len(MASTERY_LEVELS) - 1)].split(":")[0],
            "probabilities": {k: round(v, 4) for k, v in mastery_probs.items()},
        },
        "persistent_misconception": {
            "id": persistent,
            "confidence": round(persistent_conf, 4),
            "description": matched["description"] if matched else None,
            "remedy": matched.get("remedy") if matched else None,
        },
        "next_step": {"value": step, "confidence": round(step_conf, 4),
                      "description": QUIZ_NEXT.get(step, "")},
        "understood_not_guessed": round(understood, 4),
        "usage": response.get("usage", {}),
        "meta": response["_meta"],
    }
