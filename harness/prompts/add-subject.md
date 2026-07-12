# Add-a-Subject Playbook

A complete, model-agnostic prompt for extending SubjectKG to a new subject. Any capable
AI model (Claude, or others) can follow this to produce a knowledge graph of the same
standard as the maths graph. It encodes the exact methodology that built maths —
including the quality bars and the failure modes we found and fixed along the way.

Give the model this file plus repo access, filling in the two parameters:

> Build the {SUBJECT} knowledge graph for SubjectKG, covering {GRADE_RANGE}, following
> harness/prompts/add-subject.md end to end. Use the maths graph (kg/) as the reference
> implementation throughout.

---

## Operating principles (read first)

1. **Work at your full capacity.** Use your deepest reasoning for structure decisions
   (strand design, prerequisite edges) — these are load-bearing and expensive to change
   later. If your harness supports parallel subagents, fan out authoring by grade band
   and audit in parallel, exactly as the maths build did. If not, work band by band and
   run the adversarial audits yourself in separate, fresh passes (an audit in the same
   pass that authored the content will rubber-stamp it).
2. **The spine is sacred.** Canonical node ids are immutable once students reference
   them. Get the spine right before authoring any content; never rename, only add.
3. **Nothing random.** Every assessment option must be engineered to detect a named
   error. This is the product's soul; it is non-negotiable in every subject.
4. **Validate mechanically, audit adversarially.** `validate_kg.py` catches structure;
   only an independent re-derivation pass catches a wrong answer key, and a wrong key
   is the worst bug the system can have.
5. **Evidence over authority.** Map to the actual curriculum documents (NCERT chapters,
   CCSS, or the subject's equivalent) and record the mapping per node, so the graph can
   be audited against sources later.

## Step 0 — Source survey

Identify the subject's curriculum backbone: the Indian national curriculum (NCERT
textbooks/chapters) and one international standard (like CCSS for maths — e.g. NGSS for
science, CEFR for languages). Add download entries to `kg/sources/manifest.json`. If
sources are unreachable from your environment, say so explicitly in the manifest and
build from curriculum-structure knowledge — honestly labeled — with the ingestion
scripts ready for later refinement.

## Step 1 — Strand design (think hardest here)

Choose 5–9 strands that partition the subject across ALL grades (maths used: num, alg,
geo, mea, dat, tri, cal, vec). Good strands: stable across grades, roughly balanced,
match how the curriculum itself thinks. Codes: 3 lowercase letters. These become id
segments and viewer colors (define one `--s-<code>` CSS variable per strand in
`viewer/index.html`, reusing the 8 validated palette colors in slot order).

## Step 2 — The spine

Author `kg/spine.json` for the subject (same shape as maths): every teachable concept
node for the full grade range, `g{grade}.{strand}.{slug}` ids, ~10–16 nodes per grade.
Granularity test: one node ≈ one textbook chapter or coherent half-chapter ≈ 30–90
minutes to first mastery. The spine is a human-reviewable curriculum map — write titles
a parent can understand.

## Step 3 — Band content (the big authoring pass)

Split the grade range into 4–6 bands at natural stage boundaries. For each band, author
full nodes per `harness/schemas/kg-node.schema.json`. Per node:

- **description** (student-readable why-it-matters), **learning_outcomes** (observable
  can-dos), **curriculum mapping** (chapter names + standard codes; empty array when no
  honest match — never force one).
- **misconceptions (2–4)**: REAL, documented, subject-specific faulty mental models with
  a behavioral `signal` and a specific `remedy`. Non-maths examples of the same species:
  science — "heavier objects fall faster", "current gets used up around a circuit";
  language — overgeneralized rules ("goed", "more better"); history — presentism,
  single-cause explanations; geography — "seasons come from distance to the sun".
- **questions (3+)**: easy→medium→hard, recall/procedural→conceptual→application.
  Exactly 4 options, exactly 1 correct. Write the three error-stories FIRST, derive
  what each error produces, then write the options. Every distractor tagged with a
  misconception id or a specific diagnosis. If two errors give the same option, change
  the stem until all four are distinct. Verify every keyed answer independently —
  for facts, check against sources; for computations, recompute.
- **teaching metadata**: modalities genuinely suited to the concept, thinking routines
  from `harness/rules/20-thinking-routines.md`, real-world hooks (Indian-context
  friendly AND universal), a `video_search` query (never hardcoded URLs).

Prerequisite edges: only true conceptual prerequisites; cross-band edges are expected
and are where different authors' seams show — see Step 5.

## Step 4 — Per-class micro graphs

For each class, expand every macro node into 4–8 ordered micro-skills per
`harness/schemas/kg-micro.schema.json` → `kg/classes/class-NN.json` (for a non-maths
subject: `kg/<subject>/classes/`). One micro = one teachable chunk (5–30 min). Micros
carry their own prereqs (earlier micros or other-grade macros), outcomes, and a
diagnostic question on at least a third of them (prioritize misconception-bearing ones).

## Step 5 — Adversarial audits (do NOT skip; fresh context per audit)

The maths build ran these as independent passes and found 65 real issues despite
careful authoring. Budget for the same:

1. **Answer-key audit** (per band): independently re-derive every keyed answer; check no
   distractor is also defensible; check all 4 option values are distinct; check each
   distractor's tag actually produces its value ("the stated error path must generate
   the stated option" — the most common defect class in maths was exactly this).
2. **Edge audit** (whole graph): compute degrees/roots/leaves; walk band boundaries
   (different authors!) for missing edges; hunt "unlocked without its real
   prerequisite" chains — maths' one critical bug was quadratics reachable without
   ever solving a linear equation. Spot-check the longest chains for pedagogical order.
3. **Consistency audit** (harness): every file path, field, threshold, and formula
   mentioned anywhere must agree with the schemas and scripts.

Fix everything; re-run `python3 scripts/validate_kg.py` until 0 errors.

## Step 6 — Wire it in

- Scripts: derive strand ids from the spine (already done — validate_kg.py reads them).
  For a second subject, place files under `kg/<subject>/` and copy/point the scripts'
  ROOT paths accordingly; keep one spine per subject.
- Viewer: add the `--s-<code>` color variables; everything else is data-driven.
- Skills: `/tutor`, `/assess`, `/kg`, `/reflect` are subject-agnostic by design — they
  read whatever graph the profile references. Extend student profiles with the new
  subject's node ids (same mastery semantics).

## Step 7 — Prove it

Definition of done (all machine-checkable ones enforced by validate_kg.py):
- [ ] spine covers the full grade range; every spine node has full band content (0 stubs)
- [ ] 0 validation errors; prerequisite graph is a DAG; no dangling refs
- [ ] every wrong option tagged; every keyed answer independently verified in a fresh pass
- [ ] every node mapped to curriculum sources (or explicitly marked unmapped)
- [ ] per-class micro graphs for every grade; viewer renders map + drill-down
      (screenshot it — the maths build caught a real crash only by rendering)
- [ ] a pilot session run against a test student profile end-to-end (/assess entry →
      /tutor → /reflect) without a rule contradiction

## Anti-patterns (each one was found in real output and had to be fixed)

- Filler distractors ("none of the above", random near-numbers) — forbidden.
- Two options with the same value in different clothes (1/2 vs 2/4).
- A diagnosis that cannot mathematically/factually produce its option's value.
- Explanations that assert a false derivation even when the key is right.
- Forced standard-code mappings where the standard doesn't actually cover the node.
- Prerequisite chains that skip the adjacent grade's node for a distant ancestor.
- Auditing your own fresh output in the same context that wrote it.
