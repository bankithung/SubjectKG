---
name: kg
description: Explore, visualise, validate, or edit the maths knowledge graph. Args: [path <node-id>|show <student-id>|validate|find <text>]. Example - /kg path g10.tri.intro
---

# /kg — Knowledge Graph Operations

The graph lives at `kg/math.json` (built from `kg/spine.json` + `kg/bands/*.json` +
`kg/classes/class-NN.json` by `scripts/build_kg.py`). Band files carry macro concept
nodes; class files carry each class's in-depth micro-skill graph (attached to macro
nodes as `micros`, schema `harness/schemas/kg-micro.schema.json`). The interactive
viewer is `viewer/index.html` — full 1-12 map, plus click a CLASS label to open that
class's in-depth graph.

## Subcommands

### `find <text>`
Search node titles/descriptions in `kg/math.json`; print matching ids with grade, strand,
and one-line description. Use this to map a student's informal topic ("fractions",
"trig") to node ids.

### `path <node-id>`
Print the full prerequisite tree for the node (topologically ordered, deduplicated),
formatted as a learning path with grades. If a student id is also given, annotate each
node with their mastery and highlight the actual gaps — the personalised path is just
the unmastered prefix.

### `show [student-id]`
Regenerate viewer data and tell the user to open the viewer:
1. Run `python3 scripts/build_kg.py` (rebuilds `kg/math.json` and `viewer/kg-data.js`).
2. If a student id is given, also run `python3 scripts/export_student_overlay.py <id>` to
   write `viewer/student-data.js` (mastery overlay: green mastered / amber in-progress /
   grey locked / blue frontier).
3. Tell the user to open `viewer/index.html` in a browser (it is fully self-contained).

### `validate`
Run `python3 scripts/validate_kg.py`. Fix any reported errors (dangling prerequisite ids,
cycles, schema violations, duplicate question ids, multiple/zero correct options). The
graph must always validate before commit.

## Editing rules

- Spine ids are immutable (student profiles reference them). Additions go through
  `kg/spine.json` + the right band file, then `validate`.
- Misconceptions and questions discovered during tutoring should be promoted into band
  files — that is how the graph gets smarter (see `harness/rules/50-self-improvement.md`).
- Every edit: run validate, then rebuild via `show`.
