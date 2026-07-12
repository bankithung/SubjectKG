---
name: reflect
description: Post-session self-improvement pass - analyse what worked, update the insights ledger, refine the knowledge graph and harness rules. Args: <student-id> [session-file]. Run automatically at the end of every /tutor session; can also be run standalone to mine past sessions.
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
7. **Commit** all changes (profile, session log, insights, KG edits) with a message like
   `session: S001 2026-07-12 ratio-proportion (+kg: new misconception m5)`. Never include
   student names — ids only.

## Standalone mining mode

Run periodically (`/reflect all`): read ALL session logs across students, look for
patterns single sessions can't show (strategy success rates by strand, questions with
non-functioning distractors, nodes with unusually high lapse rates), and write the
findings to `harness/insights.md` + fix the KG accordingly. This is the closest thing to
a training run the harness has — treat it seriously.
