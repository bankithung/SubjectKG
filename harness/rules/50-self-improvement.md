# 50 — Self-Improvement: The Harness Learns Too

The harness improves at two levels after EVERY session: it learns about the **student**
(profile updates — see 40) and it learns about **teaching itself** (this file). The second
level is what makes the harness self-improving rather than merely adaptive.

## The reflection pass (`/reflect`, mandatory after each session)

Answer in writing, in the session log's `reflection` block:
1. What was the session goal, and was it met (evidence, not vibes: test scores, mastery deltas)?
2. Which teaching moves worked? (student engaged, answered the follow-up correctly)
3. Which moves failed, and what's the best hypothesis why?
4. What surprised me about this student? (surprises = model errors = the profile was wrong
   somewhere — fix the profile.)
5. What will I try differently next session? (concrete, testable: "open with the cricket
   run-rate hook before touching notation")

## The insights ledger (`harness/insights.md`)

When a reflection produces a lesson that generalizes beyond one student, append it to
`harness/insights.md` as a dated entry:

    ## 2026-07-12 · fractions-add-sub · modality
    Area-model-first beat rule-first for both students who held m2 ("add tops and bottoms").
    Evidence: S001 session 14, S003 session 6 — both passed transfer item after area model,
    both had failed it after rule-first in earlier sessions.
    Action: prefer visual/manipulative before procedural for g5.num.fractions-add-sub when m2 active.

Rules for the ledger:
- Every entry needs **evidence** (which student, which session, what changed).
- Entries may **contradict earlier entries** — newer evidence wins; note the supersession.
- At session start, the agent reads recent insights for the nodes it plans to teach.

## Improving the knowledge graph itself

The KG is data, so the harness can and must refine it:
- Student reveals a misconception not in the node → add it (with signal/remedy) to the
  band file and re-run `scripts/validate_kg.py`.
- A question's distractor is never chosen across many exposures → it isn't diagnostic;
  redesign it. A question everyone gets right teaches nothing; raise it a difficulty or replace.
- A prerequisite edge proves wrong (students succeed without it, or fail despite it) →
  fix the edge; note the evidence in the commit message.
- New source material ingested (`scripts/ingest_ncert.py`) → propose node splits/additions
  as a diff for human review; never silently restructure spine IDs (they are referenced by
  every student profile).

## Improving the harness rules

When an insight is about the harness itself ("entry diagnostics longer than 12 items crater
first-session return rate"), amend the relevant rule file in `harness/rules/` directly —
these files are living documents. Every amendment must:
1. cite the evidence line from `harness/insights.md`,
2. be committed with a message starting `harness-learning:` so the evolution is auditable.

## Guardrails on self-modification

- Never weaken the Hard Rules in 00-core.md or the privacy rules in 40-personalization.md.
- Never change scoring/mastery math retroactively for existing students without migrating
  their profiles (write the migration in `scripts/`).
- Prefer additive learning (new insight entries) over destructive edits; keep history.
- All spine ID changes require a deprecation alias in `kg/spine.json`, never deletion.
