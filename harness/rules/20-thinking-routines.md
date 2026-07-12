# 20 — Thinking Routines

Thinking routines (largely from Harvard Project Zero's Visible Thinking) are structured
conversation patterns that make student thinking visible — to them and to us. Each KG node
lists routines that fit it (`teaching.thinking_routines`). The agent must know them all and
run them properly, not as slogans.

Every routine produces **observable thinking** — always log what the student's responses
reveal (vocabulary, misconceptions, connections) to the session log.

## The routines

### `see-think-wonder`
Show a mathematical object (graph, pattern, geometric figure, data table).
1. **See** — "What do you notice? Only observations, no interpretations yet."
2. **Think** — "What do you think is going on? Why?"
3. **Wonder** — "What does this make you wonder?"
Use for: introducing new objects (first graph of a parabola, first histogram, a tiling).
The Wonder step generates the questions the lesson then answers — instant motivation.

### `notice-wonder`
Lighter-weight see-think-wonder for problem setups: "What do you notice? What do you
wonder?" before ANY problem is posed. Turns word-problem dread into curiosity. Use freely
at all grades.

### `think-pair-share` (adapted for 1:1)
Student thinks silently/writes first, THEN discusses with the tutor (the tutor plays the
"pair"). The discipline is the pause: never let the student answer instantly without
committed thought. Ask them to write their answer before you respond.

### `what-makes-you-say-that`
The universal follow-up. After ANY claim (right or wrong): "What makes you say that?"
Reveals reasoning, catches lucky guesses, dignifies wrong answers. Use several times per
session. Especially after CORRECT answers — right answer, wrong reason is the most
dangerous state and only this routine finds it.

### `claim-support-question`
For conjectures and properties: state a **claim**, find **support** (examples, reasoning),
raise a **question** that remains. Use for: divisibility rules, angle properties,
"is it always true that...?" Perfect bridge toward proof (grades 6+).

### `always-sometimes-never`
Present statements to classify as always/sometimes/never true ("a square is a rectangle",
"multiplying makes bigger", "x² > x"). The single best routine for flushing out
misconceptions — most "sometimes" answers expose the exact boundary of understanding.

### `convince-me`
Three levels: convince yourself → convince a friend → convince a skeptic. The tutor plays
an increasingly skeptical audience. Use for: any rule the student uses but hasn't justified.
This is proof, disguised as conversation.

### `three-whys`
Ask "why?" three times in a row, going deeper each time. "Why do we flip and multiply?" →
"why does dividing by ½ give more?" → "why is division the inverse of multiplication?"
Use sparingly (it's intense) on procedures the student executes mechanically.

### `connect-extend-challenge`
After learning something new: what does this **connect** to (KG prerequisites make this
concrete — show the graph!), how does it **extend** what you knew, what still
**challenges** you? Ideal session-closer; the Challenge answers seed the next session.

### `headlines`
"Write a newspaper headline capturing the most important thing about today's topic."
Forces synthesis and reveals what the student thinks the main point was (often not what
you thought you taught). Great quick closer for younger students.

### `step-inside`
Perspective-taking for maths: "You are the denominator — what's your job? What do you
complain about?" Sounds silly, works brilliantly for grades 1-7 to anthropomorphize
structure (place value positions, equation sides staying balanced, the equals sign's job).

### `i-used-to-think-now-i-think`
After repairing a misconception or completing a topic: "I used to think ___, now I think
___." Makes conceptual change explicit and self-acknowledged — repaired misconceptions
relapse less when the student has narrated the change. Log the exact wording in the
session record; it's the best evidence of conceptual change we can capture.

## Selection rules

- New object or topic → `see-think-wonder` / `notice-wonder`
- After any answer → `what-makes-you-say-that` (liberally)
- Suspected misconception → `always-sometimes-never`, then `i-used-to-think-now-i-think` after repair
- Procedure without understanding → `three-whys` or `convince-me`
- Session close → `connect-extend-challenge` or `headlines`
- Young/disengaged student → `step-inside`, `notice-wonder`
- Track per-student routine effectiveness in `strategy_stats` like any other strategy.
