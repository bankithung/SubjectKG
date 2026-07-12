---
name: digest
description: Write the weekly parent digest for a student - one page, plain language, with one concrete 10-minute home activity. Args: <student-id>. Output: students/<id>/digests/YYYY-Www.md. Run weekly (auto-triggered from /reflect when the last digest is >6 days old).
---

# /digest — Weekly Parent Digest

The analytics page (`report.html`) is for teachers; this is for parents. One page,
warm, zero jargon, honest. A parent should finish it in two minutes knowing exactly
three things: how it's going, what changed this week, and one thing THEY can do.

## Steps

1. **Load** the profile and this week's session logs (last 7 days; if none, say so
   kindly and suggest a rhythm rather than guilt).
2. **Write `students/<id>/digests/YYYY-Www.md`** (ISO week), exactly these sections:
   - **This week in one line** — e.g. "Two sessions; decimals started, and the
     'longer number is bigger' trap is half-beaten."
   - **What clicked** — 2-3 specific wins in plain words, tied to what the student
     actually said/did ("she explained tenths using her own pizza-cuts idea").
   - **What we're working through** — the current misconception/struggle explained so
     a parent understands the THINKING ("right now 0.45 looks bigger than 0.5 to him
     because 45 > 5 — this is a completely normal stage, not a maths problem").
   - **Your 10 minutes this week** — ONE concrete home activity tied to the current
     node and the child's interests, doable at a kitchen table with household objects
     ("while serving dinner, cut one roti in halves and one in quarters and ask which
     piece is bigger — let her convince YOU"). Start from the current node's
     `parent_check` prompt in the KG when it has one; personalize it to this family.
   - When introducing a NEW strand, borrow its one-paragraph plain-language summary
     from `kg/spine.json` `strand_summaries` so parents know what this part of maths
     is FOR.
   - **Next up** — one sentence from the learning plan.
3. **Rules**: plain language (match the family's `language.explanation` register);
   never grades/percentages/peer comparison — describe growth in behaviors; never
   blame ("needs to focus more" is banned; describe what helps instead); keep the
   child's dignity — write as if they will read it, because they might. Anonymous id
   in the filename/file; the parent knows who their child is.
4. If `students/<id>/plan.md` shifted this week, one honest line about why.
5. Commit with the session per the usual rules.
