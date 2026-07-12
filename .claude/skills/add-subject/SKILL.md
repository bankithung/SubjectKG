---
name: add-subject
description: Extend the harness to a new subject by building a full knowledge graph (spine, band content, misconceptions, diagnostic banks, per-class micro graphs) to the same standard as maths. Args: <subject> [grade-range]. Example - /add-subject science 1-10
---

# /add-subject — Build a New Subject's Knowledge Graph

Follow `harness/prompts/add-subject.md` END TO END — it is the complete playbook,
encoding the methodology and quality bars from the maths build (including the audit
findings that shaped them). Do not improvise a lighter process.

Key commitments the playbook enforces:
1. Strand design and spine FIRST, with your deepest reasoning — ids are immutable.
2. Band authoring with real documented misconceptions and engineered distractors
   (write error-stories first, then options; every wrong option tagged).
3. Per-class micro graphs (4–8 ordered micro-skills per topic).
4. Adversarial audits in FRESH passes (answer keys, edges, consistency) — never audit
   your own output in the context that wrote it. Fan out subagents if available.
5. `python3 scripts/validate_kg.py` at 0 errors, viewer rendered and screenshotted,
   one pilot session end-to-end before declaring done.

Use the maths graph (`kg/spine.json`, `kg/bands/`, `kg/classes/`) as the reference
implementation for shape, tone, and depth throughout.
