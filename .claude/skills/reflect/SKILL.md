---
name: reflect
description: Post-session self-improvement pass - analyse what worked, update the insights ledger, refine the knowledge graph and harness rules. Args: <student-id> [session-file], or "all" for cross-student mining mode. Run automatically at the end of every /tutor session; run "/reflect all" periodically to mine patterns across all students.
---

# /reflect — Self-Improvement Pass

Read `harness/rules/50-self-improvement.md` first. This skill is how the harness gets
smarter about TEACHING (the profile update in /tutor is how it gets smarter about the
STUDENT). Both must happen every session.

## Steps

1. **Load** the session log (arg 2, or the latest in `students/<id>/sessions/`), the
   student profile, and `harness/insights.md` (create it with a header if missing).
2. **Answer the five reflection questions** from 50-self-improvement.md in the session
   log's `reflection` block (if not already written):
   goal met with evidence · what worked · what failed + hypothesis · surprises ·
   concrete next-time plan.
3. **Update strategy_stats** in the profile: each strategy used this session gets
   tried+1, and worked+1 only if its follow-up check landed.
4. **Mine for generalizable insights.** If a lesson holds beyond this student (or this
   session confirms/contradicts an existing insight), append a dated, evidenced entry to
   `harness/insights.md`. No evidence, no entry.
5. **Propose KG improvements** when the session surfaced them:
   - new misconception observed → add to the node in its band file (with signal/remedy)
   - distractor never chosen / question too easy → flag or fix in the band file
   - prerequisite edge contradicted by evidence → fix, citing the session
   - good generated question → promote from the session log into the band file
   Then run `python3 scripts/validate_kg.py` and `python3 scripts/build_kg.py`.
6. **Amend harness rules** only for insights about the harness itself, per the guardrails
   in 50-self-improvement.md (cite evidence; commit message prefix `harness-learning:`).
7. **Tune the personal forgetting curve** (rules/40 #7): recompute per-strand lapse
   rates from `spaced_repetition`; where a strand has ≥5 reviews, nudge its `retention`
   multiplier ±0.1 per the thresholds. Never tune on thin evidence.
8. **Update the error signature** when today's wrong answers rhyme with older ones
   ACROSS topics (same slip type in different nodes ≥3 times → add/strengthen an
   `error_signature` entry with a coaching ritual; a signature dodged twice in a row →
   `improving`, five times → `beaten`).
9. **Update streaks & records** in `motivation.streaks` (session streak, review streak,
   any new personal record worth naming next session).
10. **Refresh the learning plan** — if `students/<id>/plan.md` exists (see `/plan`),
    update it against today's reality: tick completed steps, move dates honestly if
    pace changed, note the change in its revision log. Never let the plan silently rot.
11. **Weekly parent digest** — if the latest digest in `students/<id>/digests/` is >6
    days old (or missing), run the `/digest` skill's steps for this student.
12. **Regenerate the student's analytics page** — `python3 scripts/build_student_page.py <id>`
    — so `students/<id>/report.html` always reflects the latest session (it is the page a
    teacher/parent reads: mastery, misconception tracker, full Q&A history, what works).
13. **Commit** all changes (profile, session log, report, plan, digest, insights, KG edits) with a message like
   `session: S001 2026-07-12 ratio-proportion (+kg: new misconception m5)`. Never include
   student names — ids only.

## Standalone mining mode

Run periodically (`/reflect all`): read ALL session logs across students, look for
patterns single sessions can't show (strategy success rates by strand, questions with
non-functioning distractors, nodes with unusually high lapse rates, cross-topic
`error_signature` habits per student, and which remedies actually repaired each
misconception across students), and write the findings to `harness/insights.md` +
fix the KG accordingly. This is the closest thing to
a training run the harness has — treat it seriously.
