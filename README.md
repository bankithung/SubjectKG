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

## How to use it — complete walkthrough

### 0. Setup (once)

```bash
git clone <this-repo> && cd SubjectKG
python3 scripts/build_kg.py        # build the graph (plain python3, no dependencies)
python3 scripts/validate_kg.py    # should end: 0 errors
claude                             # start Claude Code in the repo - the agent reads
                                   # CLAUDE.md and becomes the tutor automatically
```

Requirements: the [Claude Code CLI](https://claude.com/claude-code) and Python 3.10+.
Nothing else — no packages, no database, no server. Everything lives in this folder,
so back it up like you'd back up marksheets.

### 1. Enrol a student (first session, ~15 min)

```
> /tutor S001
```

No profile exists yet, so the tutor runs the **intake**: a 5-minute friendly interview
(interests, motivation, language preference, goals — never a form), then a short
adaptive **entry diagnostic** (10-15 questions, binary-searching down prerequisite
chains to find their true level, which is usually NOT their school grade). It ends by
showing them their **frontier** — everything they're ready to learn right now — framed
as territory owned, not deficit. Pick any anonymous id (S001, S002...); the real name
never enters a file. Write it in `students/S001/private-notes.md` if you need a
reminder — that file is gitignored.

### 2. Daily: run sessions

```
> /tutor S001                      # continue from the plan / last session
> /tutor S001 fractions            # or steer to a topic
```

One session ≈ their attention span (the profile learns it). The tutor opens with due
reviews (≤5 min), teaches the frontier node in the modality that works for THIS student,
tests with ≥3 diagnostic questions, diagnoses every wrong answer (each distractor maps
to a specific misconception), and closes with a win. Everything is logged and the
profile, analytics page, and plan update automatically via the end-of-session /reflect.

Useful variants:
```
> /assess S001 review              # just clear due reviews (10 min on a busy day)
> /assess S001 topic g6.num.ratio-proportion   # re-test one topic
> /kg path g10.tri.intro           # "what do I need before trigonometry?" with reasons
> /kg find decimals                # map informal topic names to graph nodes
```

### 3. Weekly rhythm

```
> /plan S001 exam 2026-09-15       # create/revise the rolling learning plan
> /digest S001                     # parent digest (auto-triggered weekly by /reflect)
> /reflect all                     # cross-student mining: what teaching works, which
                                   # questions underperform, KG fixes (run fortnightly)
```

### 4. What to open in a browser

| Page | For | How |
|---|---|---|
| `viewer/index.html` | Student/parent: the full 1-12 map, what unlocks what, why | `> /kg show S001` first (adds their green/amber/star/lock overlay), then open the file |
| Class drill-down | The in-depth per-class graph, micro-skill by micro-skill | click any CLASS label inside the viewer |
| `students/S001/report.html` | Teacher: full analytics - mastery, misconception tracker, every Q&A, what works | regenerated every session, or `python3 scripts/build_student_page.py S001` |
| `students/S001/plan.md` | The student's own journey plan | any editor; embedded in report.html too |
| `students/S001/digests/` | Weekly parent digests | any editor |

### 5. Maintenance & growth

```bash
python3 scripts/validate_kg.py            # after ANY graph edit; must be 0 errors
python3 scripts/build_kg.py               # rebuild math.json + viewer data
python3 scripts/ingest_ncert.py download  # (network-unrestricted machine) pull all
                                          # NCERT PDFs, then let the agent refine the
                                          # graph against the real texts
```

```
> /add-subject science 1-10        # extend to a new subject at the same quality bar
                                   # (full playbook: harness/prompts/add-subject.md)
```

The harness improves itself as it runs: `harness/insights.md` accumulates evidenced
teaching lessons, question banks grow from good generated items, prerequisite edges are
corrected by observation, and rule changes are auditable as `harness-learning:` commits.

### If something looks wrong

- **"Node not ready" but you disagree** → `> /kg path <node-id> S001` shows exactly which
  hard prerequisite is unmet and why it matters; override consciously by teaching the
  prerequisite first (recommended) or record the evidence and fix the edge (rules/50).
- **Validation errors after an edit** → the message names the node/question; fix and re-run.
- **Student data feels stale** → profiles only update through sessions; there is no sync
  to fix. If a session ended abruptly, run `/reflect S001` to complete the logging.

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
