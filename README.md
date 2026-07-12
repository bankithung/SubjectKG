# SubjectKG — a self-improving AI learning harness (Maths first)

SubjectKG turns a Claude Code CLI session into a **personalised maths tutor** that gets
smarter with every interaction — about each student, and about teaching itself.

```
cd SubjectKG
claude
> /tutor S001 fractions        # run a tutoring session
> /assess S001 entry           # place a new student on the graph
> /kg show S001                # visualise the graph with their mastery overlay
> /reflect S001                # post-session self-improvement pass
```

## How it works

```
                    ┌────────────────────────────────────────────┐
                    │  harness/rules/   (how to teach)           │
                    │  00 core loop · 10 pedagogy · 20 thinking  │
                    │  routines · 30 assessment · 40 personal-   │
                    │  ization · 50 self-improvement             │
                    └───────────────┬────────────────────────────┘
                                    │ read every session
   kg/math.json  ◄── build ──  kg/spine.json + kg/bands/*.json + kg/classes/*.json
   (162 concepts, Class 1-12,       │
    prerequisites, misconceptions,  ▼
    diagnostic question banks) ──► /tutor session ◄── students/<id>/profile.json
                                    │                  (mastery, behavior,
                                    ▼                   strategy stats, reviews)
                          students/<id>/sessions/*.json
                                    │
                                    ▼
                    /reflect: update profile + harness/insights.md
                              + improve the KG itself
```

**The knowledge graph** (`kg/`) covers Class 1–12 mathematics, structured on the NCERT
curriculum and aligned to Common Core (CCSS codes on every node): **162 concept nodes,
900 micro-skills (per-class in-depth graphs), 1,100+ diagnostic questions, 570 documented
misconceptions** — all machine-validated. Each concept node carries: prerequisites (the
graph edges), learning outcomes, **misconceptions with detection signals and remedies**,
teaching metadata (best modalities, thinking routines, real-world hooks), and a
**diagnostic question bank** where every wrong option is engineered to detect a specific
misconception or slip — no question is ever random. Each class additionally has its own
in-depth graph (`kg/classes/class-NN.json`) breaking every topic into 4–8 ordered,
individually-testable micro-skills.

**The student model** (`students/<id>/profile.json`) tracks per-node mastery with
evidence, active misconceptions and their repair stage, which teaching strategies
actually work for this student (a small bandit re-ranks them), behavioral signals
(attention span, hint appetite, frustration tells), affect, calibration, and
spaced-repetition schedules.

**Self-improvement** happens at two levels after every session: the profile update makes
the harness smarter about the *student*; the `/reflect` pass mines generalizable lessons
into `harness/insights.md` and feeds improvements back into the knowledge graph (new
misconceptions, better distractors, corrected prerequisite edges) and, with evidence,
into the harness rules themselves (auditable via `harness-learning:` commits).

**Teachers get a real dashboard.** `python3 scripts/build_student_page.py S001` generates
`students/S001/report.html` — a self-contained analytics page: mastery by strand and
topic, an actionable misconception tracker (faulty model → repair stage → the KG's
recommended remedy), the **complete question history** with every answer, what it
diagnosed, and confident-error flags, which teaching strategies actually work for this
student, behavior notes, the spaced-repetition schedule, and a session-by-session
timeline. Regenerated automatically by `/reflect` after every session.

**Students can see the map.** Open `viewer/index.html` — a self-contained interactive
viewer of the whole graph: search, filter by strand, click any topic to see what to
learn first and what it unlocks, and (after `/kg show <student-id>`) their personal
overlay: mastered ✓ / in progress ◐ / ready now ★ / locked 🔒.

## Repo layout

| Path | What |
|---|---|
| `CLAUDE.md` | Entry point for the Claude Code agent (loads the rules) |
| `.claude/skills/` | `/tutor` `/assess` `/kg` `/reflect` |
| `harness/rules/` | The teaching rulebook (living documents) |
| `harness/schemas/` | Contracts: KG node, student profile, session log |
| `harness/insights.md` | Cross-student teaching-insights ledger (append-only, evidenced) |
| `kg/spine.json` | Canonical node IDs, Class 1–12 (immutable) |
| `kg/bands/*.json` | Full macro node content by grade band |
| `kg/classes/class-NN.json` | Per-class in-depth graphs: each topic broken into ordered micro-skills |
| `kg/math.json` | Built combined graph (`python3 scripts/build_kg.py`) |
| `viewer/index.html` | Interactive graph viewer (works from `file://`) |
| `students/` | One folder per student: profile, session logs, generated artifacts |
| `scripts/` | build / validate / student overlay / NCERT PDF ingestion |

## Maintaining the graph

```bash
python3 scripts/build_kg.py        # rebuild kg/math.json + viewer data
python3 scripts/validate_kg.py    # must pass before committing KG changes
python3 scripts/export_student_overlay.py S001
```

To refine the graph against the actual NCERT textbooks (the authoring environment could
not reach ncert.nic.in), run from an unrestricted machine:

```bash
python3 scripts/ingest_ncert.py download   # all Class 1-12 maths PDFs -> data/raw/
python3 scripts/ingest_ncert.py extract    # -> data/text/*.txt (pip install pypdf)
# then let the agent reconcile each chapter with the graph (see script docstring)
```

## Roadmap

- [ ] Ingest NCERT texts and split coarse nodes into finer micro-skills
- [ ] Promote the best generated questions from session logs into the banks
- [ ] More subjects: the spine/band/viewer machinery is subject-agnostic (hence "SubjectKG")
- [ ] Optional web front-end; the data layer (JSON + schemas) is already API-shaped
