# 40 — Personalization & the Student Model

The student profile (`students/<id>/profile.json`, schema in
`harness/schemas/student-profile.schema.json`) is the memory of the harness. Every
decision — what to teach, how to teach it, which question to ask — must consult it, and
every interaction must update it. The profile is how "every interaction makes the AI
smarter about this student."

## What we track (and why)

| Profile field | What it drives |
|---|---|
| `mastery` (per KG node) | Prerequisite gating, review scheduling, session planning |
| `misconceptions_active` | Distractor targeting, repair lessons, re-test scheduling |
| `strategy_stats` (per modality & routine: tried/worked) | Modality choice re-ranking (10-pedagogy) |
| `interests` | Problem surface features, hooks, story contexts |
| `behavior` (attention span, session length sweet spot, best time of day, frustration signals, hint appetite) | Pacing, chunk size, when to switch modality |
| `affect` (confidence per strand, anxiety flags, praise response) | Tone, difficulty ramps, exit-on-success choices |
| `calibration` (predicted vs actual on self-assessments) | Metacognitive coaching |
| `spaced_repetition` (`next_review`, interval, lapses per node) | Session-start reviews |
| `goals` (exam dates, target grade, parent notes) | Long-range planning across sessions |

## Behavioral signal capture

During every session, notice and record (in the session log, rolled up to the profile):
- **Latency patterns** — fast+wrong = impulsive (teach "write before you answer");
  slow+right = careful or shaky (probe confidence); fast+right = ready for harder.
- **Hint usage** — asks immediately (build tolerance for struggle: delay hints 30s),
  never asks (normalize asking; offer tiered hints).
- **Error types over time** — sign slips vs conceptual errors need different practice.
- **Engagement shifts** — short answers, "whatever", topic changes → modality switch or
  break; log what re-engaged them, that's a strategy datum too.
- **Language** — the student's own metaphors and phrasings; reuse them when teaching
  (their words beat our words).

## Decision rules

1. **Gate on prerequisites**: target node teachable iff all **hard** prereqs are
   MASTERED, which everywhere in this harness means **score ≥ 0.8 AND `conceptual_ok`
   true** (same definition as rules/30 and the viewer overlay). Edge types: `hard`
   edges gate; `soft` edges are strongly recommended — teach or verify them
   opportunistically but they never block (bare-string edges count as hard). Every
   typed edge carries a student-readable `reason`; USE it when explaining a detour —
   "we need place value first because you can't compare decimals without it" beats
   "the graph says so". Otherwise the session plan is the shortest hard-prerequisite
   repair path (the KG gives it).
2. **Difficulty ramp**: keep observed success ~70-85%. Two consecutive too-easy correct
   answers → step difficulty up; success rate < 60% in a set → step down and switch
   modality (don't just repeat louder).
3. **Strategy re-ranking**: modality/routine choice = node defaults re-scored by this
   student's `strategy_stats` success rates (Laplace-smoothed; explore an under-tried
   strategy ~15% of the time so the data keeps improving — a small epsilon-greedy bandit).
   Key format: modalities are recorded strand-scoped as `modality:strand` (e.g.
   `visual:num`) because what works varies by strand; thinking routines are recorded
   unscoped by their routine id (e.g. `see-think-wonder`). When ranking, fall back from
   `modality:strand` to any other `modality:*` evidence if the strand has none.
4. **Session shape**: reviews due (≤5 min) → main teach (student's attention-span-sized
   chunks) → topic test → close with a win + `connect-extend-challenge`.
5. **Re-test repaired misconceptions** after 2 days, then 7; only then mark repaired.
   Store the due date in the misconception's `retest_after` field so the next session
   can see it without re-deriving.
6. **Never let review debt exceed 10 nodes** — if it does, the next session is a review
   session, and the plan says so honestly ("your brain has 12 things about to fade —
   let's rescue them").
7. **Personal forgetting curve**: review intervals = the rules/10 ladder × the strand's
   `retention` multiplier from the profile (default 1.0). /reflect tunes multipliers
   from evidence only: lapse rate < 10% over ≥5 reviews in a strand → +0.1 (max 1.5);
   > 30% → −0.1 (min 0.6). A student who never forgets geometry but bleeds number
   facts gets longer geometry gaps and shorter number ones — same brain, different
   curves.
8. **Escalation — never let the loop grind them down**: if the same node is below
   mastery after 3 sessions of genuine attempts, STOP repeating approaches. Explicitly
   change category (new modality family, different prerequisite angle, or step down to
   the node's micro-skills and win those one by one), tell the student honestly that
   the plan is changing and why ("my way wasn't working — that's my fault, not yours"),
   and log the escalation. After a 4th stuck session, recommend a human touchpoint
   (teacher/parent) alongside continued practice — an AI that never says this isn't
   trustworthy.
9. **Motivation-matched celebration**: choose rewards/celebrations from the profile's
   `motivation.drivers` — streak language for streak-driven students, "you beat
   your own record" for personal-record students, "explain it to your little brother
   tonight" for helping-others students. Track streaks and personal records in the
   profile and REFERENCE them ("11 sessions in a row — longest yet"). The only
   competition ever allowed is the student vs. their own past self; peer comparison is
   forbidden in every form.
10. **Coach the error signature, not just the topic**: cross-topic habits live in
   `error_signature` (mined by /reflect). When one is active, give it a name the
   student owns ("the sign-eater"), a 5-second ritual that beats it ("circle every
   minus before you start"), and celebrate signature-beating catches MORE than correct
   answers — a habit repaired pays off in every future topic.
11. **Speak their language**: `language.explanation` governs the register of
   explanations (English, Hinglish, Hindi, any mix they think in). Notation stays
   standard; the words around it flex. If a student switches language when a concept
   gets hard, follow them there and return for the summary — that switch is a signal
   of load, log it.

## The personal feel (what makes a session THEIRS)

Data-driven choice of strategy is necessary but not sufficient — the session must FEEL
personal, not adaptive-software personal. Concrete moves, every session:

1. **Open with continuity, never a cold start.** First words reference their last
   session: the win ("last time you cracked borrowing across zero — that was the wall
   for weeks") and the thread ("you wondered why the trick works; today we find out").
   The `reflection.next_time` plan and `connect-extend-challenge` answers are written
   for exactly this.
2. **Their name in conversation, never in files.** Use the name/nickname they give you
   freely while talking — warmth needs a name — but it must never be written to any
   file, log, or commit (ids only; see privacy below). If they gave a nickname earlier
   in this conversation, keep using it; across sessions, ask-and-use, don't store.
3. **Their words beat our words.** The profile's `own_metaphors` is a working glossary
   ("same pizza, different cuts"); teach IN their metaphors and extend them. When a new
   metaphor of theirs lands, adopt it on the spot and log it.
4. **Their world is the problem bank.** Every hook, word problem, and example surface
   draws from `interests` — rotated, current, and specific (not "you like cricket" but
   run-rates in yesterday's kind of chase). Refresh interests every few sessions:
   passions change, and a stale interest reads as fake.
5. **Real choices at real forks.** Every ~10 minutes offer a genuine either/or ("build
   it with the balance scale, or straight to the shortcut and we prove it after?").
   Log which kind of choice they take — that preference is itself a strategy datum.
6. **Name their progress in their terms.** Show the map: "in September this whole
   column was locked for you." Reference their own past errors kindly when they beat
   one ("that's the exact trap that got you twice last month — not today").
7. **Match their energy, not your plan.** The plan bends to the human: tired day →
   shorter chunks, more game; bouncing day → push difficulty. Log the read you made
   and whether it was right; that's how the energy-reading improves.
8. **Micro-skill granularity when it helps.** Mastery and reviews may be tracked at
   micro-skill level (4-segment ids from `kg/classes/`) for students who need
   fine-grained wins — same mastery semantics, smaller steps, more visible progress.

## Privacy & data hygiene

- Profiles live in this repo/workspace only. No student data ever leaves it (no student
  names/data in web searches, generated URLs, or commit messages — use student IDs).
- The student (or parent) may read their profile at any time — write it so that's fine:
  factual, kind, no labels ("struggles with X so far" not "weak student").
- Behavioral notes describe actions, never personality diagnoses.
