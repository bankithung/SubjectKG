# Jev in SubjectKG

SubjectKG holds a lot of carefully written meaning — 570 misconceptions with detection
signals, 289 prerequisite edges each with a written justification, 494 diagnostic items
where every wrong option is supposed to detect something specific. Until now, reading
that meaning required a full Claude Code session. Finding a concept was a substring
grep, and a student who typed their answer instead of picking A/B/C/D could not be
diagnosed at all.

[Jev](https://docs.typesafe.ai) is TypeSafe's System One model. It does not generate
text. It answers **typed questions about state** and returns a probability, a chosen
option, or a position on a scale — values that drop straight into `profile.json` and
into `if` statements, with no parsing step in between.

```
python3 scripts/jev_serve.py      →  http://localhost:8770
```

---

## What Jev decides

The governing rule in this integration is that **Jev makes the judgments and code does
the fetching.** Where a decision needs semantic understanding, it is a Jev question —
never a threshold, a weight, or a formula in Python.

| Decision | Primitive | Previously |
|---|---|---|
| Which concept is this learner asking about? | Choice, adjudicated over a shortlist | substring grep |
| Is this even a maths question? | Noul | nothing |
| What does the learner want — teach, test, prerequisites? | Choice | inferred by a full LLM turn |
| Is this free-text answer correct? | Noul (the key is supplied) | **impossible** |
| Which documented misconception does the error reveal? | Choice, with two no-match outcomes | only if they picked a pre-tagged option |
| Slip, procedural gap, or conceptual gap? | Score over 3 described levels | a human judgment call |
| Did the student sound sure of themselves? | Noul | a human judgment call |
| What should the tutor do in the next two minutes? | Choice over 5 bounded actions | a full LLM turn |
| Is this prerequisite edge real, and is hard/soft right? | Noul + Choice | never checked |
| What should be done about this edge, and how badly? | Choice + Score | never checked |
| What is a student who picks *this* distractor thinking? | Choice per option | asserted by the author, never verified |
| Has this student mastered the concept, across a whole sitting? | Score + Choice + Noul | a human judgment call |

Deliberately **not** asked of Jev: whether an answer key is arithmetically correct, and
whether an item has exactly one right answer. Both require computation. See
[What Jev must not be asked](#what-jev-must-not-be-asked).

### Where code still decides, and why

Code narrows 162 concepts to a shortlist of 8 before Jev adjudicates. That is
**retrieval, not judgment** — a model cannot choose an option it was never shown, and
asking it to rank 162 full concept descriptions in one call would be both expensive and
worse. The beam search that produces the shortlist is mechanical and its score is
reported separately as `path_score`, so you can always see what retrieval thought and
what Jev decided instead.

Everything downstream of the shortlist is Jev's. An earlier version of `route()`
multiplied a hand-tuned `BAND_WEIGHT = 0.40` into the ranking to stop "what's the chance
of two heads in a row" matching Class 12 Bayes' theorem. That constant was a decision,
and it was in the wrong place. It is gone.

---

## The five workflows

### 1. Route — `POST /api/route`

Three tiers. Tier 1 is **one batched request** asking four independent things about the
utterance at once: is it maths, what does the learner want, which strand, which school
stage. They cannot see each other's answers, which is exactly why batching them is safe.

Tier 2 opens one request per surviving strand, in parallel — a beam, because as the
[hierarchical classification cookbook](https://docs.typesafe.ai/cookbooks/hierarchical_classification.md)
puts it, with greedy search "one early mistake cannot be recovered".

Tier 3 is the decision. Jev sees the finalists side by side **with their school levels**
and picks one. This matters: choosing between Class 10 and Class 12 probability is a
comparison, and a per-candidate score can never express one.

Measured on the shipped preset prompts:

| utterance | retrieval ranked | Jev decided |
|---|---|---|
| "whats the chance of getting two heads in a row" | Class 12 Bayes' theorem | **Class 10 classical probability** |
| "how do i share a chocolate bar equally between 3 friends" | Class 3 division | **Class 3 fractions** |
| "the shadow of a tower is 30m…" | Class 10 trigonometry applications | same, no adjudication needed |

The chocolate-bar case is the clearest: one bar shared three ways is a fraction, not a
whole-number division, and nothing in the wording says so.

### 2. Diagnose — `POST /api/diagnose`

**The capability the harness did not have.** Five judgments, one request, one copy of
the state:

```
is_correct     Noul    — judge the mathematics, not the spelling
misconception  Choice  — over this node's documented misconceptions, plus
                         "no_error" and "other_error" so the model is never
                         forced to invent a match
depth          Score   — slip / procedural / conceptual
confident      Noul    — did they sound sure?
next_move      Choice  — advance, consolidate, hint, reteach, drop to prerequisite
```

Two answers to the same question, same misconception, different action:

| student typed | misconception | sounded sure | tutor does |
|---|---|---|---|
| "yeah its a diameter, any line across a circle is one" | m2 (1.00) | 0.96 | **reteach the concept** |
| "hmm maybe? i think if its the longest one it counts" | m2 (0.99) | 0.06 | **one targeted hint** |

`harness/rules/` already says to treat those two students differently. Nothing enforced
it before, because nothing could tell them apart.

The `remedy` in the response is always the one a human wrote into the graph. Jev selects
which documented remedy applies; it never writes teaching advice.

### 3. Quiz — `POST /api/diagnose` per answer, then `POST /api/quiz/verdict`

Sit a concept's authored test. Answers are typed, not picked, and nothing is revealed
until the answer is committed — `harness/rules/` requires both, and neither was possible
before. Each answer is diagnosed as it comes in.

The end is the interesting part: **four judgments over the whole transcript at once**,
because a sitting is not the sum of its answers.

```
mastery      Score  — not yet / shaky / solid, against the node's learning_outcomes
persistent   Choice — is ONE faulty model behind all the errors, or were they one-offs?
guessing     Noul   — do the right answers show reasoning, or could they be luck?
next_step    Choice — advance / consolidate / reteach differently / drop to prerequisite
```

Three sittings on *Adding and Subtracting Fractions*:

| what the student typed | mastery | understood, not guessed | next |
|---|---|---|---|
| explained the reasoning each time | **2.00** solid | 0.93 | advance |
| right, but bare numbers with no working | **1.82** solid | 0.72 | advance |
| "you add the tops and the bottoms", three times | **0.00** not yet | 0.24 | reteach differently |

Two things a score out of three cannot do. It separates three bare correct answers from
three explained ones. And on the failing sitting it named **m1** as the thread running
through all three — even though the third answer, judged alone, came back
`other_error`. The persistent misconception is only visible across the sitting.

This is deliberately not computed from the per-answer results. "Two out of three" is
arithmetic; *which* two, and whether one idea caused both misses, is the assessment.

### 4. Audit — `POST /api/audit/edges`, `POST /api/audit/questions`

Turns Jev on the graph itself. Per edge, five judgments in one request; per question,
four plus **one per wrong option**.

The per-option judgment is the interesting one. Rule 30 says no option is ever random —
every distractor must detect a named misconception or slip. The graph *asserts* that.
This asks Jev, independently and without showing it the author's tag, what a student who
picks each option is thinking, then compares.

Real finding, Class 2: *"Rahul had 45 marbles. He won 28 more. How many now?"* Option D
is `17`. The author tagged it a generic slip. Jev says misconception **m2** — 45 − 28,
the student chose the wrong operation. That is a documented, nameable error, not
carelessness, and the graph already has an id for it.

Sorting is Jev's too: findings come back ordered by an urgency Score, not by a severity
formula.

#### What a full sweep of this graph actually found

**289 edges, 33 s, 1,445 judgments.** Jev said keep on 252, `relabel_soft` on 28 and
`rewrite_reason` on 9 — 12.8% wanting attention. The strongest was
*Coordinate Geometry (C10) → Introduction to 3-D Geometry (C11)*, declared hard,
`relabel_soft` at 0.74. Also flagged: *Squares and Square Roots → Cubes and Cube Roots*,
both Class 8 and declared hard, which reads as parallel rather than sequential.

**494 questions, 60 s, ~3,400 judgments.** Jev said keep on 444 and
`rewrite_distractors` on 50. Across 1,482 wrong options:

| | count | at ≥0.9 confidence |
|---|---|---|
| Author wrote a generic "slip"; Jev names a documented misconception | 264 | **50** |
| Jev contradicts an explicit misconception tag | 31 | **0** (all ≤0.60) |
| Jev says the option is filler — reveals nothing | 108 | 12 |

The asymmetry is the reassuring part. Jev almost never confidently overrides a human's
explicit tag; what it does is sharpen generic ones. Two at confidence 1.00:

- *"In ΔABC, AB=8, BC=5, CA=6 — which angle is largest?"*, option `∠A`. Tagged a slip.
  It is misconception **m4**: matching an angle to an adjacent side instead of the
  opposite one. (The answer is ∠C, opposite the longest side.)
- *"Which of these is prime?"*, option `15`. Tagged a slip. It is **m1**: "believes all
  odd numbers are prime — 9, 15 and 21 get called prime."

These are proposals for a human editor ranked by confidence, not automatic edits. The
50 high-confidence re-tags are a concrete afternoon's work that measurably improves what
the tutor learns when a child picks a wrong option.

### 5. Compare — `POST /api/compare`

Jev's routing against the keyword lookup it replaces. The baseline is a fair
implementation of what `/kg find` does today — weighted token overlap over titles and
descriptions — not a strawman. It is instant and free and stays the better tool when a
learner already knows the technical word.

On the eight-prompt hard set, keyword search returns nothing at all for "why is 1/2 + 1/3
not 2/5", and for "the shadow of a tower is 30m…" it confidently returns *Data Handling:
Tally Marks*.

---

## What Jev must not be asked

**Do not ask it to check arithmetic.** An early version of the question audit asked
whether the option marked correct really was correct. It flagged three items across the
494-item bank. All three were false alarms:

| item | key | the actual answer |
|---|---|---|
| ₹50 − (₹12.50 + ₹36.75) | ₹0.75 | 50 − 49.25 = **0.75** ✓ |
| P(A\|B) given P(A∩B)=0.2, P(B)=0.5 | 0.4 | 0.2/0.5 = **0.4** ✓ |
| median of 7, 2, 9, 4, 6 | 6 | 2,4,6,7,9 → **6** ✓ |

This is documented, not bad luck. The
[Jev 1.13 model card](https://docs.typesafe.ai/model-jaggedness/jev-1.13.md) says:
*"Jev is not a calculator. We strongly recommend implementing any mathematical logic in
code."* It also does not count reliably — it "recognizes the shape of an answer rather
than tallying". Those judgments have been removed. Answer-key verification belongs in
`validate_kg.py` or with a human.

**The rule that falls out of it:** ask Jev to judge an answer only when the truth is
supplied in the state. `diagnose()` works well precisely because the correct answer is
given to it, so the model is matching meaning — "five sixths" against "5/6" — rather
than computing. The audit had no key to compare against, so it had to calculate, and
that is the one thing it should not do.

Also worth avoiding, from the same page: date arithmetic, hex/RGB/binary values, reading
exact numbers out of a Score's interpolation, and large states padded with irrelevant
fields.

## Two things Jev got right that are worth knowing about

**It refuses badly-posed questions instead of guessing.** The first version of the
urgency Score described a reviewer's workflow — "worth tidying when someone is next
editing this part of the graph". Jev answered every single edge with
`urgency_confidence: 0.0`, which is a maximally spread distribution: *this question
cannot be answered from the state you gave me.* It was right. It knows nothing about
anyone's editing schedule. Re-posed as a consequence for a child — "a tutor following
this edge would sometimes make a child wait for a prerequisite they did not need" —
confidence went to 0.19–0.74 and the numbers became usable.

**A low confidence is often the correct answer.** "What's the chance of two heads in a
row" produces a bimodal band distribution — 0.60 middle-school, 0.33 senior — and
reports confidence 0.50. That is not the model failing. The topic genuinely is taught
twice, and a confident answer would have been the wrong one.

---

## Cost and speed

Batching is the whole economic argument. TypeSafe measured **12.2× cost and 10× speed**
from batching questions over one state, because the state dominates the tokens. Every
workflow here is written to exploit it:

| | requests | judgments | wall clock |
|---|---|---|---|
| Diagnose one answer | 1 | 5 | ~1.3 s |
| Route one utterance | 3 | 6 | ~1.4 s |
| Audit all 289 edges | 289 (12 in flight) | 1,445 | ~31 s |
| Audit all 494 questions | 494 (12 in flight) | ~3,400 | ~54 s |

Answers are cached to `.jev-cache/` keyed by a hash of the exact request, so re-running
an audit over an unchanged graph costs nothing. Delete the directory to force fresh
calls, or run the server with `--no-cache` when measuring real latency.

---

## Files

| Path | What |
|---|---|
| `scripts/jev_client.py` | Transport: auth, retry with backoff, disk cache, thread pool, question builders |
| `scripts/jev_brain.py` | The judgments — what gets asked, and how answers become decisions |
| `scripts/jev_serve.py` | Localhost server (stdlib only). Holds the API key; the browser never sees it |
| `web/` | The console |
| `.env` | `TYPESAFE_API_KEY=...` — gitignored |
| `.jev-cache/` | Answer cache — gitignored, safe to delete |

No pip installs, no npm, no build step. The repo's zero-dependency promise is intact.

## Security

The key is read server-side only and the server binds to `127.0.0.1`. Do not expose it
on a network — anything that can reach the port can spend your quota. Student data never
leaves the machine except as the specific question text sent to the API, and the
diagnose endpoint sends concept content and the typed answer, never a student id.
