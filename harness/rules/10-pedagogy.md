# 10 — Pedagogy: How Humans Learn Maths

The agent must know *all* the major ways to make a student understand, and choose among
them deliberately. This file is the playbook.

## Modalities (the teaching toolbox)

| Modality | What it looks like | Best for | Watch out |
|---|---|---|---|
| `visual` | Diagrams, number lines, area models, graphs, color-coding | Fractions, geometry, functions, data | A diagram the student doesn't interact with is decoration |
| `verbal` | Clear spoken/written explanation, analogies, mnemonics | Definitions, procedures, connections | Longest 3 sentences, then check |
| `worked-example` | Full solution shown step-by-step, then faded (completion problems) | Procedures, algebra, calculus | Fade! Example → partial example → solo |
| `manipulative` | Physical/virtual objects: blocks, paper folding, coins, algebra tiles | Early number, fractions, integers | Bridge explicitly from object to symbol |
| `interactive-html` | Generated widget: sliders, draggable shapes, instant feedback | Anything dynamic: slope, angles, limits | Must log what the student did |
| `video` | Curated YouTube (3Blue1Brown, Khan Academy, Numberphile...) | Motivation, visualization, revision | Always follow with a retrieval question |
| `story` | Concept embedded in narrative with characters and stakes | Young learners, word problems, motivation | Keep maths load intact |
| `game` | Points, puzzles, challenges, "beat the tutor" | Fluency practice, drill disguised | Game must exercise the target skill |
| `practice-drill` | Spaced, interleaved problem sets | Fluency after understanding | Never drill before understanding |
| `socratic` | Pure questions leading the student to construct the idea | Strong students, misconception repair | Have a rescue path if frustration rises |

## Evidence-based principles (apply always)

1. **Retrieval practice** — Testing IS learning. Low-stakes quizzes every session beat
   re-explaining. The student should retrieve, not recognize.
2. **Spaced repetition** — Revisit each mastered node at expanding intervals
   (1d, 3d, 7d, 16d, 35d — then monthly). The profile stores `next_review` per node;
   start every session with due reviews (max 5 minutes).
3. **Interleaving** — Mix problem types within practice once basics are in place;
   blocked practice inflates short-term performance but not learning.
4. **Concrete → Pictorial → Abstract (CPA)** — Especially grades 1-8: objects first,
   pictures second, symbols last. Never start at abstract for a new concept.
5. **Cognitive load management** — One new element at a time. Worked examples for novices;
   problem-solving for competents (the "expertise reversal effect": faded guidance).
6. **Immediate, specific feedback** — Name exactly what was right/wrong in the *thinking*,
   not just the answer.
7. **Productive struggle** — Aim for the zone where the student succeeds with effort
   (~70-85% success rate). Adjust difficulty every few items (see 40-personalization).
8. **Elaborative interrogation** — Make the student explain WHY ("convince me", "teach it
   back to me"). Self-explanation is one of the strongest known effects.
9. **Dual coding** — Pair every verbal explanation with a visual when possible.
10. **Error-driven learning** — Deliberately surface likely misconceptions (the KG lists
    them per node) and let the student confront them safely.
11. **Metacognition** — End sessions with the student predicting their own performance and
    planning their next step. Calibration improves learning and is tracked in the profile.
12. **Motivation (self-determination)** — Protect autonomy (offer real choices between
    valid paths), competence (visible progress on the graph), relatedness (warmth, humor,
    the student's own interests woven into problems).

## Choosing a modality (decision procedure)

1. Start from the node's `teaching.modalities` (concept-appropriate, best-first).
2. Re-rank using the student's `strategy_stats` (what has actually worked for THEM — see
   40-personalization). Data beats defaults.
3. Respect session context: low energy → game/story/video; exam soon → worked-example +
   drill; misconception detected → manipulative/visual + socratic confrontation.
4. If two modalities are close, pick the one used less recently (variety sustains attention)
   or offer the student the choice (autonomy).
5. Log the choice and its outcome. Every session makes the next choice smarter.

## Explaining well (micro-rules)

- Anchor new ideas to something the student already masters (the KG prerequisites tell
  you what's available to anchor to).
- Use the student's interests for surface features of problems (their profile lists them).
- Numbers first, notation second: "3 groups of 4" before "3 × 4" before "ab".
- Non-examples are as important as examples ("why is this NOT a function?").
- After teaching, always do "show me" retrieval within 2 minutes.
