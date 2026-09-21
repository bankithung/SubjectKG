# Learning journey: persistent state and the path engine

**Date:** 2026-09-21
**Status:** approved design, not yet implemented
**Scope:** slice A (state loop) + slice B (path engine)

## Purpose

The harness specifies a complete learning-journey engine in `harness/rules/` and
`harness/schemas/`, and none of it is implemented. `students/S001/profile.json` has
`mastery: {}` and `session_count: 0` after an enrolment session. The Jev console added in
`docs/JEV.md` is entirely stateless: it can judge one answer beautifully and then throws
the judgment away.

This design makes the harness remember, and then makes it guide. After it:

- A sitting durably changes what the system knows about a student.
- The system can say what is mastered, what is ready to learn, what is locked and by
  which specific prerequisite, what is due for review, and what is missing between here
  and a stated goal.
- Jev decides what the student should actually do next, and says why.

### Out of scope

Deferred to their own specs, in this order:

- **C — Placement.** An adaptive entry diagnostic that binary-searches prerequisite
  chains to seed a new student's mastery map in one sitting. Until it exists, a new
  student's map fills in session by session.
- **D — Journey view.** The map with progress over time and a teacher rollup.
  `viewer/index.html` and `students/<id>/report.html` already cover part of this.

Also out of scope: authentication, multi-tenancy, deployment. The server stays bound to
`127.0.0.1`.

## Architecture: ledger and projection

Session logs are append-only truth. `profile.json` is a **projection** derived from them
by replaying every recorded observation through the scoring rules.

```
students/<id>/sessions/2026-09-21-01.json   ─┐
students/<id>/sessions/2026-09-22-01.json    ├─ the ledger (append-only, never edited)
students/<id>/sessions/...                  ─┘
                    │
                    │  project()   deterministic, pure
                    ▼
students/<id>/profile.json                     the projection (derived, rebuildable)
```

This is not a new idea imposed on the repo — it is what the repo already intends.
`harness/schemas/session-log.schema.json` requires `assessment.items` (every question,
whether it was correct, which misconception the answer signalled) and a
`profile_updates` block. Sessions are already records and the profile is already
described as the rolled-up state. What is missing is the roll-up.

Four problems this dissolves rather than solves:

| Problem | Why it goes away |
|---|---|
| Two writers (`/tutor` CLI and the console) | Both only ever append their own new file. No shared mutable state, so no race. |
| A crash mid-session | An incomplete log is discarded by the projection. The profile is never half-written. |
| "Never fake data" (rules/00) | Every number in the profile traces to a logged observation. Enforced by construction, not by discipline. |
| Profile drift | `project(seed, logs) == profile.json` is a checkable invariant. `seed` is empty for students whose ledger goes back to their first session, and the pre-existing profile for the two migrated students (see Migration). |

**Non-goal: purity for its own sake.** The projection is cheap (tens of logs, a few KB
each) so it is recomputed in full on every write. No incremental fast path until
profiling says one is needed.

### Write protocol

1. Append `students/<id>/sessions/<date>-<nn>.json`, written to a temp file in the same
   directory and `os.replace`d into place (atomic on POSIX and on Windows).
2. Recompute the projection from all logs for that student.
3. Write `profile.json` the same atomic way.

If step 2 or 3 fails, the ledger is still correct and the next run repairs the profile.
The reverse can never happen, because the profile is never a source of truth.

## The projection

`project(student_id, logs) -> profile` is pure: same logs, same profile, always. It
carries forward the fields the ledger does not own (`goals`, `interests`, `language`,
`motivation.drivers`, `behavior` preferences set at intake) from the existing profile,
and derives everything else.

### Mastery, per node

From `harness/rules/30-assessment.md`, applied per assessment item in chronological
order:

```
correct:    m ← m + 0.30 · (1 − m) · w
incorrect:  m ← m − 0.35 · m · w
clamp to [0.05, 0.99]
```

A node with no prior evidence starts at `m = 0.05`, the floor of the clamp. Five
consecutive correct medium items take a node from 0.05 to 0.84, which is the intended
shape: mastery is earned over a handful of items, not claimed in one.

**Interpreting `w`.** rules/30 gives `w = 0.8 easy, 1.0 medium, 1.2 hard`, but questions
in the graph carry `difficulty` on a 1–5 scale. Linear interpolation honouring both
stated endpoints:

```
w = (0.7 + 0.1 · difficulty) · (1.2 if skill in {conceptual, application} else 1.0)
```

giving 0.8 at difficulty 1 and 1.2 at difficulty 5, then the stated 1.2× for
conceptual and application items over procedural. `recall` is treated as 1.0 alongside
`procedural`; rules/30 does not mention it and inventing a discount for it would be
going beyond the spec. **This mapping is an inference and is flagged as such in the
code, so a curriculum author can correct it.**

`conceptual_ok` becomes true the first time a `conceptual` or `application` item for
that node is answered correctly. All 162 nodes have at least one such item, so the flag
is always reachable.

`MASTERED(n) ≡ score ≥ 0.8 AND conceptual_ok` — the single definition used by rules/30,
rules/40 and the viewer overlay. It lives in exactly one function.

### Misconceptions

`mastery[node].misconceptions_active[]` with `repair_stage ∈ {observed, confronted,
retest-due, repaired}`:

- An item whose answer signals misconception `m` adds it at `observed` if absent.
- Teaching that addresses it moves it to `confronted` and sets `retest_after = +2 days`.
- A **correct** answer on a later item that targets that same misconception advances the
  stage: first such pass sets `retest_after = +7 days`, the second marks `repaired`.
  rules/30 is explicit that nothing else confirms a repair — never the student saying
  they understand.
- A wrong answer signalling it again resets to `observed`.

Whether an answer "targets that misconception" is known from the graph: the item's
options carry `misconception` tags. Whether a free-text answer *reveals* it is Jev's
existing `diagnose()` judgment.

### Spaced repetition

Ladder from rules/10: `1, 3, 7, 16, 35` days, then 30-day steps. Per rules/40 §7 the
interval is scaled by the strand's personal multiplier:

```
interval = ladder[rung] × retention.get(strand, 1.0)
next_review = last_seen + interval
```

A node enters the schedule when it first becomes MASTERED, at rung 0. A passed review
advances one rung. A failed review resets to rung 0 and increments `lapses`.

`retention` tuning stays where rules/40 puts it — in `/reflect`, on ≥5 observations,
in 0.1 steps, clamped [0.6, 1.5]. **This design does not tune it**; it only reads it.

### What the projection does not compute

`strategy_stats`, `error_signature`, `calibration`, `behavior.attention_span_min` and
the `affect` fields are cross-session inferences that rules/50 assigns to `/reflect`.
The projection carries them through untouched. Slice A+B does not write them; mining
them is a later slice.

## The path engine

Pure functions over `(graph, profile)`. No model calls, no I/O, fully testable offline.

```
mastered(profile)        -> {node_id}
ready(graph, profile)    -> [node]        every hard prereq mastered, node not mastered
locked(graph, profile)   -> [{node, blocked_by: [{node, reason}]}]
reviews_due(profile, today)  -> [node], soonest first
review_debt(profile, today)  -> int
gap_path(graph, profile, target) -> [node]   unmastered hard ancestors, topologically ordered
```

`blocked_by` carries the author's written `reason` from the edge. rules/40 §1 is
explicit that this is what gets shown to a student — *"we need place value first because
you can't compare decimals without it"* beats *"the graph says so"*. The reason is
already in the data and has never been surfaced.

Soft edges never block. They appear as `recommended_first` on a ready node.

### The one policy rule that stays in code

rules/40 §6: **review debt > 10 forces a review session.** The rule is stated flatly, so
it is not Jev's to overrule. When it fires, the candidate list handed to Jev contains
only due reviews, and the UI says why in the rule's own words.

Below 10, what to do is a judgment, and Jev makes it.

## What Jev decides

Code assembles candidates; Jev chooses among them. Exactly the shortlist/adjudicate
split that `route()` already uses, and for the same reason: a model cannot choose an
option it was never shown, but choosing between shown options is judgment.

### 1. What should this student do next?

One request, four judgments over one state.

**State:** the candidate list (each with id, title, class, why it is a candidate —
`due_review` / `frontier` / `misconception_retest`), plus the student's `goals`,
`interests`, `language`, `motivation.drivers`, `behavior.attention_span_min`,
`affect.confidence_by_strand`, review debt, and a digest of the last two sessions.

| key | primitive | decides |
|---|---|---|
| `next` | Choice over candidate ids | the topic to open |
| `session_shape` | Choice: `reviews_then_teach` / `review_only` / `teach_only` / `repair_misconception` | how the session runs |
| `stretch_or_consolidate` | Score, 3 described levels | the difficulty ramp, serving rules/40 §2's 70–85% target |
| `energy_fit` | Noul | whether the pick suits the attention span on record |

The reason shown to the student is **not generated text**. It is assembled by code from
the chosen candidate's own data: its edge `reason`, its `real_world_hooks` matched
against `interests`, its place in `gap_path(goal)`. Jev picks; the graph supplies the
words. This keeps the harness's rule that the model never writes teaching copy.

### 2. Toward a goal, which gaps matter?

For a stated target (`goals.target`, e.g. *"Class 10 boards"*), `gap_path` returns the
unmastered hard ancestors. That list is often long and uniformly ordered by depth, which
is not the same as by consequence.

One batched request, one Score per gap (capped at 12 per request, the rest in parallel
requests):

> *How much does not knowing this hold the student back from the target?* over three
> described levels, from "a detail they can pick up alongside" to "nothing downstream
> works until this is in place".

Code orders the path by Jev's score. This is the **"which one is lacking / which to
consider"** the request asked for.

When `goals.target` is empty — true for every student today — there is no gap path to
rank, and the screen says so rather than inventing a target. The Journey screen offers
the obvious substitute: pick any node as a provisional target and see the path to it.
Nothing guesses what a child is working towards.

### 3. Is a misconception repaired?

At the `retest-due` stage, `diagnose()` already returns the misconception distribution
for a targeted item. The projection reads it; no new judgment needed.

### 4. Was the sitting understanding or luck?

`quiz_verdict()`, already built. Its `mastery` Score and `understood_not_guessed` Noul
are **recorded in the session log and displayed**, but per the approved hybrid they do
**not** set `profile.mastery.score` — the rules/30 accumulation owns that number.

Where Jev's per-sitting verdict and the running score disagree (Jev says *solid*, the
accumulated score says 0.55), the UI shows both and names the disagreement. That is
information, not a bug: it usually means either a genuinely good sitting on a node with
a bad history, or a lucky one. Neither should be silently resolved.

### Explicitly not asked of Jev

Every formula above — the mastery update, the ladder, the 0.8 gate, debt counting,
topological ordering. All arithmetic. `docs/JEV.md` records what happened the last time
this line was crossed: asked to verify answer keys, Jev flagged three items and all
three keys were correct, because the model card says plainly it is not a calculator.

## Modules

New files, each with one job. `jev_brain.py` is already ~1,100 lines and does not grow.

| File | Responsibility | Depends on |
|---|---|---|
| `scripts/learner.py` | Load/append session logs, atomic writes, the `project()` function, the mastery/ladder/repair arithmetic | stdlib, the schemas |
| `scripts/path.py` | `mastered`/`ready`/`locked`/`reviews_due`/`gap_path` — pure graph+profile functions | `jev_brain.KG` |
| `scripts/jev_guide.py` | The Jev judgments above: candidate assembly, `decide_next()`, `rank_gaps()` | `jev_client`, `path`, `learner` |
| `scripts/jev_serve.py` | New endpoints only | the three above |
| `web/` | Two new screens | — |

`learner.py` and `path.py` make **no model calls at all**. That is deliberate: the
state and the graph logic must be testable, and reviewable, without a network or an API
key.

## HTTP API

```
GET  /api/students                      -> [{id, grade, session_count, last_session}]
GET  /api/student/<id>                  -> profile + derived {mastered, ready, locked,
                                           reviews_due, review_debt}
POST /api/student/<id>/session          -> append a session log, reproject, return the
                                           new profile and what changed
POST /api/student/<id>/next             -> Jev's decision + the assembled reason
POST /api/student/<id>/gaps {target}    -> gap path ranked by Jev
POST /api/student/<id>/reproject        -> rebuild the profile from logs; returns a diff
                                           against the stored one
```

The existing quiz flow gains an optional `student_id`. With it, finishing a sitting
posts a session log and the profile updates. Without it, the console behaves exactly as
it does today — the test bench must keep working without inventing a learner.

## UI

Two screens, in the established style: probability strips for every Jev judgment, the
graph's own words for every explanation.

**Journey** — pick a student. Shows where they are: counts of mastered / ready / locked,
the review queue with what is overdue and by how long, active misconceptions with their
repair stage, and the gap path toward their stated goal ranked by Jev's consequence
score. Each locked node names the specific prerequisite blocking it **and quotes the
author's reason.**

**Today** — the decision. The candidate list code assembled, Jev's Choice distribution
over it drawn as a strip, the picked topic, the session shape, and the assembled reason.
When review debt forces the session, that is stated in rules/40's own words rather than
presented as a choice Jev made.

The Quiz screen gains a student selector; on finish it writes the session and shows the
mastery delta alongside Jev's sitting verdict.

## Failure handling

- **Unparseable session log** — skipped, named loudly in the reprojection result, never
  silently dropped. One bad file must not erase a student's history.
- **Incomplete session** (browser closed mid-quiz) — no log was written, so nothing
  happened. The ledger only gains a file on an explicit finish.
- **Profile disagrees with the ledger** — `/reproject` shows the diff and rewrites.
  Since the ledger is truth, this is always safe.
- **Schema violation** — validated against `student-profile.schema.json` before the
  write. A projection that would produce an invalid profile fails loudly and leaves the
  old file in place.
- **Jev unavailable** — the Journey screen is unaffected, because everything on it is
  computed by `path.py`. Only the Today decision and gap ranking degrade, and they say
  so rather than falling back to a silent heuristic.

## Testing

`learner.py` and `path.py` are pure, so they get real unit tests with no network:

- The mastery curve: five correct medium items take a node from 0.05 past 0.8; a wrong
  answer moves it the specified amount; the clamp holds at both ends.
- `conceptual_ok` requires a correct conceptual or application item specifically.
- Repair staging: `observed → confronted → retest-due → repaired` needs two targeted
  correct answers, and a fresh wrong answer resets to `observed`.
- The ladder advances on a pass, resets and counts a lapse on a fail, and scales by the
  strand multiplier.
- **Projection determinism:** `project(seed, logs)` is stable across runs, and for a
  student with no seed, replaying the logs in a fresh directory reproduces the committed
  profile exactly. Seeded students are checked for the weaker property that reprojection
  is idempotent.
- Gating: a node with an unmastered hard prereq is locked and names that prereq; a node
  with only an unmastered soft prereq is ready and lists it as recommended.
- `gap_path` is topologically ordered and contains no mastered node.

Fixtures: `students/S999` already exists as a synthetic profile with a session log, and
is the natural test subject. A second fixture student with a deliberately broken log
covers the failure paths.

The Jev-dependent parts are verified against the live API the way the existing workflows
were: a small set of hand-checked cases where the right answer is known.

## Migration

`students/S001` has an enrolment session recorded in git history but an empty profile
and no session log. `students/S999` has both a profile and one log, but the profile
describes six sessions and only the sixth is logged.

Neither can be reprojected faithfully, because the evidence was never written down.
Rather than fabricate a ledger to match — which would violate "never fake data" for the
sake of tidiness — both keep their current profile as a **seed**: the projection starts
from the stored profile and applies logged sessions from this point on. A
`"projection_from"` marker records the date the ledger becomes authoritative. New
students are pure projections from their first session.

## Open interpretations

Flagged because a curriculum author may want to rule differently, and each is a one-line
change:

1. **Difficulty → `w` mapping.** rules/30 names three weights; the data has five levels.
   Linear interpolation between the stated endpoints.
2. **`recall` weight.** Treated as 1.0 with `procedural`. Arguably recall is weaker
   evidence and deserves less, but rules/30 does not say so.
3. **Starting mastery 0.05.** The clamp floor. Not stated explicitly.
4. **Ladder beyond 35 days.** rules/10 says "then monthly"; implemented as repeating
   30-day steps.
