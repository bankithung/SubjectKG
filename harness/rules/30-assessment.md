# 30 — Assessment & Diagnostic Question Engineering

Assessment in this harness is never a grade — it is **measurement of a mental model**.
Every question is an instrument; every option is a sensor.

## When to test

- **Entry diagnostic** (new student): locate them on the graph. Start at their claimed
  grade's key nodes; adaptively step down prerequisite chains on failure, up on success
  (binary-search style). 10-15 items max per sitting; it must not feel like an exam.
- **After every topic** (mandatory): minimum 3 items on the node just taught —
  one procedural, one conceptual, one application/transfer.
- **Spaced reviews**: due-node items at session start (see 10-pedagogy).
- **Micro-checks**: 1-item pulse checks mid-teaching after each chunk.

## The distractor engineering rules (the heart of this file)

A 4-option MCQ has 3 wrong options. In this harness, **all three must be diagnostic**:

1. Every wrong option is derived from a **specific, named error**:
   - a misconception listed on the KG node (`misconception: "m2"`), or
   - a predictable procedural slip (`diagnosis: "subtracted exponents instead of dividing"`).
2. **No filler distractors.** If you cannot name what choosing an option would reveal,
   the option is not allowed. Replace it or use a different item format.
3. The correct answer must not be identifiable by test-taking tricks: options are
   length-balanced, plausible, in a neutral order (numeric options sorted). Position of
   the correct answer varies (never a pattern).
4. **Selection is interpretation**: when a student picks a distractor, the agent reads its
   tag and immediately knows the *probable* fault. Confirm with one follow-up
   (`what-makes-you-say-that`) before recording the misconception as observed — a slip and
   a misconception need different responses.
5. Generated questions (beyond the node's bank) MUST follow the same rules: write the
   three error-stories first, then compute what each error produces, THEN write the options.
   If two errors give the same value, adjust the numbers in the stem until all four options
   are distinct.
6. Numbers are chosen so that errors are **detectable**: e.g. for (a+b)² use a,b where
   a²+b² ≠ (a+b)² obviously; for fraction addition pick denominators where
   "add tops and bottoms" ≠ correct answer.

## Item formats beyond MCQ

MCQ is the workhorse (fast, diagnostic), but rotate in:
- **Open response with rubric** — for "convince me" and proofs; agent grades against the
  node's learning outcomes.
- **Error-spotting** — "Here is Riya's solution. Find and fix her mistake." (Directly
  exercises a misconception without the student owning the error. Very low threat.)
- **Estimate first** — demand an estimate before computing; calibrates number sense.
- **Sort/classify** — always-sometimes-never sets, card sorts (via interactive HTML).
- **Teach-back** — student explains to a "younger student" (the agent role-plays).

## Scoring & mastery model

Per node, maintain in the student profile:
- `mastery` ∈ [0,1] — updated per item via a simple Bayesian-flavoured rule:
  correct: m ← m + 0.3·(1−m) · w   |   incorrect: m ← m − 0.35·m · w
  where w = item difficulty weight (0.8 easy, 1.0 medium, 1.2 hard); conceptual/application
  items count 1.2× vs procedural. Clamp [0.05, 0.99].
- Mastery threshold to unlock dependents: **0.8** with at least one conceptual item correct.
- `misconceptions_active`: list of misconception ids observed and not yet repaired;
  a repair is only confirmed by a later correct answer on an item targeting that same
  misconception (never by the student saying "oh I get it").
- Response latency and confidence (ask "how sure are you, 1-5?" on key items) are logged;
  high-confidence errors are gold — address them first next session.

## Test session etiquette

- Frame as "let's see what your brain kept" — never punitive.
- After each item: feedback on the *reasoning*, then the worked explanation from the bank.
- End every assessment with one item the student will almost surely get right
  (exit on success — it protects motivation and tomorrow's willingness to return).
