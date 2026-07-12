# Marble (withmarble.com) taxonomy vs SubjectKG — competitive analysis

Date: 2026-07-12. Sources: github.com/withmarbleapp/os-taxonomy (README, schema/topics.schema.json,
data/topics.json, dependencies.json, clusters.json, curriculum-standards.json, manifest.json — all
fetched and analyzed directly); withmarble.com/curriculum was 403 behind the proxy, reconstructed
from search coverage and the founder's announcement. Local: kg/spine.json, harness/schemas/kg-node
+ kg-micro, kg/bands/g6-8.json (full ratio-proportion node), kg/classes/class-09.json, README.md.

## What Marble's taxonomy is

- Single-level graph of **1,590 "micro-topics"** ("a single teachable idea") across **8 subjects**
  (Science 547, Mathematics 503, English 286, History 90, Personal & Social Dev 88, Life Skills 37,
  Computing 21, Learning to Learn 18). No macro/unit hierarchy in the data — hierarchy is only
  subject → domain (a string label, e.g. Mathematics → "Fractions", 12 math domains).
- **3,221 prerequisite edges** in a validated DAG. Each edge = `{topicId, prerequisiteId,
  strength: "hard"|"soft", reason}` — 2,025 hard / 1,196 soft; every edge carries a one-line
  pedagogical rationale ("Must understand vibrations make sound before finding volume patterns").
  985 edges are math→math; **66 edges cross subject boundaries** involving math.
- **Topic fields** (schema/topics.schema.json, `additionalProperties:false`): `id` (`mt_` + opaque
  nanoid), `type` ∈ {CONCEPTUAL, PROCEDURAL, REPRESENTATIONAL, LANGUAGE, META} (math: 263 P / 129 C /
  56 META / 35 R / 20 L), `subject`, `domain`, `name`, `description`, `ageRangeStart/End` (ages,
  not grades; math tops out at 15, bulk is 4–13 → primary/lower-secondary only), `centrality`
  (precomputed graph-position score), `evidence[]` (observable mastery criteria),
  `assessmentPrompt` (a single parent-administerable check with a `{{name}}` placeholder),
  `standards[]` (`"<curriculum-slug>:<code>"`).
- **Standards**: 7 frameworks, 3,261 standards, 1,859 topic↔standard links (uk-nc-2013 895,
  ccss-ela 528, ccss-math 223, ngss-k5/ms 143, ib-pyp-pspe 70, c3). curriculum-standards.json ships
  the **verbatim standard text** (where licensing allows; 4 sources codes-only), with PROVENANCE.md.
  Note: 772/1,590 topics have **no** standards link.
- **clusters.json**: 183 parent-friendly `{subject, domain, ageRangeStart, summary}` narratives
  ("Your child is learning the building blocks of writing — …").
- **manifest.json**: versioning, per-file sha256, counts; explicitly *excludes* "embeddings, child
  mastery beliefs (PII), teaching research, visualizations" — i.e. the personalization layer is NOT
  open-sourced.
- **License**: database structure ODbL 1.0 (attribution + share-alike on derivative databases);
  authored content (descriptions, evidence, edge reasons) CC BY-SA 4.0; standards keep upstream
  licenses.
- **Curriculum page** (reconstructed): "Everything a child learns" — one connected map of 460+
  skills shown to parents; ZPD/"growing edge" framing ("next skill they're ready for once its
  foundations are secure"); tagline "every link says what must come first, and why". Product is
  ages 6–12.

## Comparable scale

| | Marble (math) | SubjectKG |
|---|---|---|
| Nodes | 503 micro-topics, ages 4–15 | 162 macro + 900 micros, Class 1–12 (incl. trig/calculus/vectors) |
| Edges | 985 math→math (+66 cross-subject), hard/soft + reason | 289 macro + 1,196 micro prereq edges, untyped, no rationale |
| Assessment | 1 open prompt/topic, no items | 494 macro + 615 micro MCQs, every distractor tagged |
| Misconceptions | none | 570 with signal + remedy, wired to distractors |
| Standards | 7 frameworks incl. verbatim text | CCSS codes (147/162 nodes) + NCERT chapters |

## A. What Marble has that we LACK

1. **Typed, justified prerequisite edges.** Our `prerequisites` is a bare string array. Marble's
   hard/soft distinction + written reason is genuinely better for gating (a soft prereq shouldn't
   block a session; rule 2 currently treats all prereqs as gates) and for explaining "why first"
   to students/parents in the viewer.
2. **Node type classification** (CONCEPTUAL/PROCEDURAL/REPRESENTATIONAL/LANGUAGE/META). We encode
   this only at the *question* level (`skill` enum). Knowing a micro is representational vs
   procedural should drive modality choice and what "mastery" looks like.
3. **Centrality score** per node — precomputed graph importance. Useful for entry-assessment item
   ordering (probe high-centrality nodes first) and for prioritizing which gaps to repair.
4. **Age *ranges* rather than a single grade** — encodes that readiness is a band, not a class.
5. **Parent-administerable `assessmentPrompt`** ("If {{name}} says…, can they tell you…") — a
   no-materials home check per topic. We have nothing per-node that a parent can run.
6. **Parent-friendly domain summaries** (clusters.json) — a narrative layer per domain × age band,
   decoupled from node granularity.
7. **Cross-subject breadth + cross-subject edges** (8 subjects, 66 math-crossing edges). Matters
   when `/add-subject science` runs: our node-id pattern (`^g\d+\.(num|alg|...)`) hard-codes math
   strands, so cross-subject prereq references can't currently be expressed.
8. **Multi-framework standards with verbatim text + provenance/licensing discipline.** We store
   CCSS codes only and NCERT chapter *names*; they ship the standard text and a PROVENANCE trail,
   plus per-file checksums and a manifest.
9. **Presentation idea**: the map itself is the marketing/learner artifact — edge tooltips that say
   *why* a link exists, and an explicit "growing edge" (ZPD frontier) framing. Our viewer has
   ready-now ★ but doesn't surface edge rationale (because we don't store any).

## B. What WE have that Marble lacks (do not cargo-cult away)

1. **Misconception engineering** — 570 faulty models with detection `signal` and specific `remedy`,
   cross-referenced by question distractors. Marble has zero misconception data. This is our core
   diagnostic advantage.
2. **Real question banks** — 1,100+ items, exactly-4-options, exactly-1-correct, every wrong option
   tagged with the misconception or slip it detects, plus full worked `explanation`. Marble's
   entire assessment layer is one open-ended prompt per topic.
3. **Teaching metadata** — per-node modalities (best-first), thinking-routine bindings,
   real-world hooks, video search query. Marble open-sourced none of its "teaching research".
4. **Two-level hierarchy with teaching order** — macro concepts + 4–8 ordered micros per topic;
   array order = recommended sequence. Marble is flat; sequence must be derived from the DAG.
5. **Upper-secondary coverage** — Classes 9–12: trigonometry, calculus, vectors. Marble's math
   ends around age 13–15 (primary product is ages 6–12).
6. **`difficulty` and `est_minutes`** on every node/micro — session planning inputs Marble lacks.
7. **The whole learner-model loop** — profiles with mastery evidence, misconception repair stages,
   strategy bandit, spaced repetition, session logs, insights ledger, self-amending rules. Marble
   deliberately withheld this layer ("child mastery beliefs (PII)" excluded).
8. **Human-readable stable IDs** (`g6.num.ratio-proportion`) vs opaque `mt_g3W0mdADVu` — matters
   for agent legibility, diffs, and hand-editing.
9. **NCERT alignment** — their 7 frameworks are US/UK/IB; nothing for our primary curriculum.
10. **Edge quality note**: their density is higher (2.0 edges/node vs our ~1.4) but 772/1,590 of
    their topics have no standards link, and evidence criteria are roughly our
    `learning_outcomes` — not deeper.

## C. Adoption recommendations (ranked)

1. **Typed + justified prereq edges** — *medium effort, highest value.*
   Schema: in kg-node + kg-micro, let each prerequisite be either a string (back-compat) or
   `{id, strength: "hard"|"soft", reason}`. Update build_kg.py/validate_kg.py to normalize;
   update rule "gate on prerequisites" so only **hard** edges gate and soft edges become
   "recommended warm-up". Viewer: tooltip shows `reason` on edges. Backfill via one agent pass
   over 289 macro edges first (micros later, lazily). Directly improves gating correctness and
   parent-facing explanations.
2. **Compute centrality in build_kg.py** — *small effort.* Store per-node
   centrality in built math.json only (not hand-authored files). Use it in `/assess entry` to
   pick maximally-informative probe nodes and in `/plan` to prioritize gap repair.
3. **Micro-skill `type` field** — *small schema change, medium backfill.* Add
   `type: conceptual|procedural|representational|language|meta` to kg-micro (optional at first).
   Tutor uses it to pick modality (representational → visual/manipulative; procedural → worked
   example + drill) and the right mastery evidence. Backfill the 900 micros in one scripted agent
   pass; validate enum in validate_kg.py.
4. **Per-node parent check prompt** — *small.* Optional `parent_check` string on macro nodes
   ("Ask your child: …", no materials, <2 min). Feeds `/digest`'s weekly 10-minute home activity
   directly instead of the digest inventing one. Backfill opportunistically during `/reflect`.
5. **Cross-subject-ready ID pattern** — *small, do before /add-subject.* Relax schema patterns to
   `^[a-z]+\d*\.` subject-prefixed ids (keep math ids unchanged; e.g. future `sci.g6.*`), and allow
   prereq references across subjects. Cheap now, painful later.
6. **Strand × band parent summaries in the viewer** — *small-medium.* A `kg/summaries.json`
   (strand, grade-band, 2-sentence plain-language "what your child is learning") rendered in
   viewer/index.html and reused by `/digest`. Cosmetic-adjacent but directly serves parents.
7. **Skip**: switching grades → age ranges (our mastery-based gating already handles off-grade
   learners; NCERT class anchoring is a feature here); opaque IDs; multi-framework standards text
   (only if a non-NCERT user base appears — and note the licensing burden they carry for it);
   manifest/checksums (nice-to-have, not learning-relevant).

## D. Import vs build (licensing)

License: structure ODbL 1.0 (share-alike on **derivative databases**), content CC BY-SA 4.0.
Systematically importing their edges/descriptions makes `kg/` a derivative database → we'd have to
license `kg/` under ODbL with attribution and share improvements back. That's acceptable for the
KG (it contains no student data — students/ stays untouched), but it's a real obligation; decide
consciously before bulk import.

- **Legitimately usable now, low obligation**: use their 985 math→math edges + reasons as an
  *audit checklist* — script a fuzzy title/description match of their ages 4–14 math topics to our
  g1–g8 nodes, flag prerequisite edges they have that we lack, then have the agent independently
  evaluate and author each edge in our own words (facts about pedagogy aren't copyrightable;
  wholesale extraction of their reason strings is).
- **Importable with attribution + share-alike if we accept ODbL/CC BY-SA on kg/**: hard/soft
  strength labels and reason text; parent-friendly cluster summaries (as a starting corpus for
  rec #6); Science/English topic lists as scaffolding when `/add-subject` runs (their Science 547
  topics are the largest ready-made prerequisite-wired science graph we've seen).
- **Must build ourselves (they don't have it, or it's withheld)**: misconceptions + signals +
  remedies; tagged-distractor question banks; teaching metadata; NCERT mapping; Class 9–12
  content; anything from their personalization layer (never released).
- **Careful**: curriculum-standards.json carries *upstream* licenses per framework (4 sources
  are codes-only for that reason) — don't copy standard text from it without checking PROVENANCE.md.
