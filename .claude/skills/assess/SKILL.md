---
name: assess
description: Run a diagnostic assessment - entry placement for a new student, a topic test, or spaced-repetition review. Args: <student-id> [entry|topic <node-id>|review]. Example - /assess S001 topic g6.num.ratio-proportion
---

# /assess — Diagnostic Assessment

Read `harness/rules/30-assessment.md` and `harness/rules/40-personalization.md` first.
Load the student profile (`students/<id>/profile.json`) and `kg/math.json`.

## Modes

### `entry` (new or returning-after-long-gap student)
Adaptive placement, binary-search style:
1. Start at the key nodes of the student's nominal grade (pick 2-3 high-centrality nodes —
   ones many others depend on).
2. Correct → step UP the graph (dependents); wrong → step DOWN the prerequisite chain
   until items land correct.
3. 10-15 items TOTAL, max. Mix strands. Stop early if the frontier is clear.
4. Output: initial `mastery` entries for every node probed — FULL records per the profile
   schema: `score` (0.85 confident-correct on a conceptual item; 0.75 confident-correct on
   procedural-only; 0.5 shaky-correct; 0.2 wrong), `evidence_count` (items actually asked),
   `last_seen` (today), `conceptual_ok` (true only if a conceptual/application item was
   answered correctly — prefer probing with conceptual items so entry results can truly
   unlock dependents). Also create a `spaced_repetition` entry (next_review = +3 days,
   interval 3) for every node scored ≥ 0.75 so entry knowledge enters the review cycle.
   Then report the student's **frontier** (nodes ready to learn now) and any misconceptions
   already visible. Write all of it to the profile and a session log. Show the student
   their frontier on the graph — frame everything they already own as territory, not deficit.

### `topic <node-id>` (after-topic test — the default after any teaching)
1. Pull the node's question bank; select ≥3 items covering procedural + conceptual +
   application. Skip items answered correctly in the last 2 sessions; if the bank runs
   dry, GENERATE items following the distractor-engineering rules (write the three
   error-stories first; tag every distractor). Store generated items in the session log's
   `generated_items` so good ones can be promoted to the band file later.
2. One item at a time. Shuffle options (correct answer must not sit in a patterned
   position). Ask for confidence (1-5) on at least one item.
3. Wrong answer → read the distractor's tag → follow up "what makes you say that?" →
   record `confirmed_as` misconception/slip. Do NOT re-teach mid-test unless the student
   is distressed; finish the set, then repair the worst gap.
4. Update mastery per the scoring rule in 30-assessment.md, set `spaced_repetition`
   (first interval 1 day), log everything.

### `review` (spaced repetition)
1. Collect nodes with `next_review` ≤ today, order by (lapses desc, interval asc), cap at 6.
2. One retrieval item each (prefer an item format different from last exposure).
3. Correct → advance to the next step of the ladder in rules/10 (1→3→7→16→35→monthly);
   wrong → interval reset to 1 day, lapse++, mastery decremented per the rules/30 scoring
   formula (a failed review IS evidence), and a 2-minute repair using the node's
   misconception remedies.
4. Update profile; if review debt > 10 nodes, tell the student honestly and make the next
   session a rescue session (per 40-personalization).

## Always

- Every question from a bank or engineered per the rules — never random.
- Every distractor chosen is data: log `misconception_signalled` on every wrong answer.
- `latency_sec`: record only when actually measurable (e.g. timestamps available in the
  interface); otherwise omit the field — never estimate it (rules/00: never fake data).
- End on a success. Never end an assessment on a failure.
