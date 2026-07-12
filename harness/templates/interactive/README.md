# Interactive HTML Teaching Widgets

When a concept is visual or dynamic, the tutor generates a small self-contained HTML page
into `students/<id>/artifacts/<date>-<node>.html` and asks the student to open it.
These are teaching moves, not decorations (rule 00-core): every widget must make the
student DO something, and the session log must record what they did and what it showed.

## Conventions (follow all of them)

1. **Self-contained**: one file, inline CSS/JS, no CDNs, no external requests. It must
   work offline from a file:// URL.
2. **One concept per widget**, matched to exactly one KG node; put the node id in a
   HTML comment at the top.
3. **Interaction first**: sliders, draggables, clickable regions — the maths responds
   instantly. A static diagram belongs in the chat, not here.
4. **Built-in check**: end with 1-2 questions inside the widget (same distractor rules
   as everywhere — `harness/rules/30-assessment.md`). Show diagnosis-aware feedback and
   a "tell your tutor this code" line: e.g. `RESULT: q1=B q2=A` the student pastes back,
   so the outcome enters the session log even though the page can't phone home.
5. **Grade-appropriate**: font size, language, and colours for the student's age.
   Big touch targets for young students.
6. **Answer keys stay out of sight**: obfuscate correct-answer handling minimally
   (students WILL view source; that's fine — curiosity about the code is a win — but
   don't paste the answer in plain sight next to the question text).

## Starter patterns that work well

- number line with a draggable point (integers, fractions, decimals)
- area-model builder for fractions/multiplication/(a+b)²
- balance scale for equations (drag terms, both sides react)
- unit-circle/triangle with draggable angle for trigonometry
- secant→tangent slider for derivatives; Riemann-rectangles slider for integrals
- dice/spinner simulators for probability (with running frequency chart)
- graph plotter where the student predicts, THEN reveals

Keep each widget under ~400 lines. If it needs more, the concept probably needs two
widgets (one idea at a time — cognitive load rule).
