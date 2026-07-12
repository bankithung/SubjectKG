---
name: plan
description: Create or revise a student's personal learning plan - a rolling multi-week horizon from where they are to where they're going, exam-aware, honestly revised as pace changes. Args: <student-id> [goal or horizon, e.g. "exam 2026-09-15" or "6 weeks"]. Output: students/<id>/plan.md
---

# /plan — The Personal Learning Plan

The session loop plans one step ahead; this plans the JOURNEY. The output is
`students/<id>/plan.md` — written for the student (and their parents) to read, and
embedded in their analytics page.

## Steps

1. **Load**: profile (mastery, retention, attention span, session cadence so far),
   `kg/math.json`, goals (arg 2 overrides profile `goals`).
2. **Compute the gap**: target nodes (from the goal — e.g. everything grade-N with
   exam weight, or the named topic's subtree) minus mastered nodes; order them
   topologically along prerequisite chains; include known-weak prerequisites first.
3. **Pace it honestly**: use THEIR observed velocity (nodes/week from session logs ×
   their typical session length), not an ideal one. Include slack (~20%) and the
   standing review load. If the goal doesn't fit the time, SAY SO in the plan and
   present the choice: more sessions/week, or a triaged target (highest-weight nodes
   first) — never a silent death-march schedule.
4. **Write `students/<id>/plan.md`** in this shape (student-readable, warm, zero jargon):
   - **Where you're headed** — the goal in one sentence, and why it's within reach.
   - **Where you are** — what's already conquered (by name — territory, not deficit).
   - **The path** — week by week: 2-4 topics per week with their class/strand, each with
     a one-line "why this next". Mark milestone weeks ("after this week, all of
     fractions is behind you").
   - **This week** — the immediate 2-3 topics, specific.
   - **Watch-outs** — active misconceptions/error-signature habits the plan routes around.
   - **Revision log** — dated one-liners whenever the plan changes ("2026-07-20: moved
     decimals back a week — we spent it beating the comparison trap; worth it").
5. **Keep it living**: /reflect updates it after every session (tick, re-date, log).
   A plan more than 2 sessions stale is a bug.
6. Regenerate the analytics page (`python3 scripts/build_student_page.py <id>`) so the
   embedded plan is current; commit per the usual session rules.

Rules: never pad the plan to look impressive; never hide slippage (re-dating with a
logged reason is honesty, silently stretched weeks are not); the plan bends to the
student, never the reverse (rules/40).
