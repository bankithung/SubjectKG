#!/usr/bin/env python3
"""Generate a teacher-facing analytics page for one student.

Usage: python3 scripts/build_student_page.py S999
Output: students/<id>/report.html  (self-contained; open in any browser)

Compiles profile.json + every sessions/*.json + kg/math.json into one page:
overview, mastery by strand and node, misconception tracker, full question/answer
history with diagnoses, strategy effectiveness, behavior notes, spaced-repetition
state, and a session-by-session timeline. Same anonymity rules as everything else:
the page carries the student id, never a name.
"""
import html
import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def esc(x) -> str:
    return html.escape(str(x if x is not None else ""))


def bar(pct: float, color: str) -> str:
    pct = max(0, min(100, round(pct)))
    return (f'<div class="bar"><div style="width:{pct}%;background:{color}"></div>'
            f'<span>{pct}%</span></div>')


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 1
    sid = sys.argv[1]
    sdir = ROOT / "students" / sid
    profile = json.loads((sdir / "profile.json").read_text())
    graph = json.loads((ROOT / "kg" / "math.json").read_text())
    nodes = {n["id"]: n for n in graph["nodes"]}
    strands = graph["strands"]
    sessions = []
    for f in sorted((sdir / "sessions").glob("*.json")) if (sdir / "sessions").exists() else []:
        try:
            sessions.append(json.loads(f.read_text()))
        except json.JSONDecodeError:
            print(f"WARN: skipping unparseable {f.name}")
    today = date.today().isoformat()
    mastery = profile.get("mastery", {})

    def qbody(node_id: str, qid: str, log: dict):
        """Find the question body: node bank, micro bank, or session generated_items."""
        n = nodes.get(node_id)
        if n:
            for q in n.get("questions", []):
                if q["id"] == qid:
                    return q
            for m in n.get("micros", []):
                if m["id"] == qid and m.get("question"):
                    return m["question"]
        for g in (log.get("assessment", {}) or {}).get("generated_items", []) or []:
            if g.get("id") == qid:
                return g
        return None

    # ---- mastery by strand ----
    strand_rows = ""
    for code, name in strands.items():
        snodes = [n for n in graph["nodes"] if n["strand"] == code]
        seen = [n for n in snodes if n["id"] in mastery]
        mastered = [n for n in seen if mastery[n["id"]].get("score", 0) >= 0.8
                    and mastery[n["id"]].get("conceptual_ok")]
        avg = (sum(mastery[n["id"]].get("score", 0) for n in seen) / len(seen) * 100) if seen else 0
        strand_rows += (f'<tr><td><span class="dot" style="background:var(--s-{code})"></span>'
                        f'{esc(name)}</td><td>{len(mastered)}/{len(seen)} mastered '
                        f'<small>({len(snodes)} total in graph)</small></td>'
                        f'<td>{bar(avg, f"var(--s-{code})") if seen else "<small>no evidence yet</small>"}</td></tr>')

    # ---- mastery per node ----
    node_rows = ""
    for nid, m in sorted(mastery.items(), key=lambda kv: -kv[1].get("score", 0)):
        n = nodes.get(nid, {})
        status = ("mastered" if m.get("score", 0) >= 0.8 and m.get("conceptual_ok") else "in progress")
        color = "var(--ok)" if status == "mastered" else "var(--warn)"
        mis = ", ".join(f'{a["id"]} ({a.get("repair_stage","observed")})'
                        for a in m.get("misconceptions_active", [])) or "—"
        node_rows += (f'<tr><td>{esc(n.get("title", nid))}<br><small>{esc(nid)} · Class '
                      f'{esc(n.get("grade","?"))}</small></td><td>{bar(m.get("score",0)*100, color)}</td>'
                      f'<td>{"✓" if m.get("conceptual_ok") else "✗"}</td>'
                      f'<td>{m.get("evidence_count",0)}</td><td>{esc(m.get("last_seen",""))}</td>'
                      f'<td>{esc(mis)}</td></tr>')

    # ---- misconception tracker ----
    mis_rows = ""
    for nid, m in mastery.items():
        for a in m.get("misconceptions_active", []):
            n = nodes.get(nid, {})
            desc = next((x["description"] for x in n.get("misconceptions", [])
                         if x["id"] == a["id"]), "")
            remedy = next((x["remedy"] for x in n.get("misconceptions", [])
                           if x["id"] == a["id"]), "")
            mis_rows += (f'<tr><td>{esc(n.get("title", nid))}<br><small>{esc(a["id"])}</small></td>'
                         f'<td>{esc(desc)}</td><td><b>{esc(a.get("repair_stage","observed"))}</b>'
                         f'<br><small>first seen {esc(a.get("first_seen",""))}</small></td>'
                         f'<td>{esc(remedy)}</td></tr>')

    # ---- full question history ----
    q_rows, n_items, n_correct = "", 0, 0
    for log in sessions:
        for it in (log.get("assessment", {}) or {}).get("items", []) or []:
            n_items += 1
            n_correct += bool(it.get("correct"))
            q = qbody(it["node"], it["question"], log)
            prompt = q["prompt"] if q else f'(bank item {it["question"]})'
            key = next((o["text"] for o in q["options"] if o.get("correct")), "") if q else ""
            diag = ""
            if not it.get("correct"):
                tag = it.get("misconception_signalled", "")
                if q:
                    opt = next((o for o in q["options"]
                                if o.get("text") == it.get("option_chosen")), None)
                    diag = (opt or {}).get("diagnosis") or ""
                    if tag and not diag:
                        n = nodes.get(it["node"], {})
                        diag = next((x["description"] for x in n.get("misconceptions", [])
                                     if x["id"] == tag), tag)
                diag = f'{esc(tag)} — {esc(diag)}' if tag else esc(diag or "unclassified")
                if it.get("confirmed_as"):
                    diag += f' <small>(confirmed: {esc(it["confirmed_as"])})</small>'
            conf = it.get("confidence_stated")
            flag = ' <b class="hot">⚠ confident error</b>' if (conf or 0) >= 4 and not it.get("correct") else ""
            q_rows += (f'<tr class="{"good" if it.get("correct") else "bad"}">'
                       f'<td>{esc(log.get("date",""))}</td>'
                       f'<td>{esc(nodes.get(it["node"],{}).get("title", it["node"]))}</td>'
                       f'<td>{esc(prompt)}</td>'
                       f'<td>{esc(it.get("option_chosen",""))}{flag}</td>'
                       f'<td>{"✓" if it.get("correct") else "✗ (key: " + esc(key) + ")"}</td>'
                       f'<td>{diag or "—"}</td>'
                       f'<td>{esc(conf) if conf else "—"}</td></tr>')

    # ---- strategies ----
    st_rows = ""
    for name, s in sorted(profile.get("strategy_stats", {}).items(),
                          key=lambda kv: -(kv[1]["worked"] / kv[1]["tried"] if kv[1]["tried"] else 0)):
        rate = s["worked"] / s["tried"] * 100 if s["tried"] else 0
        st_rows += (f'<tr><td>{esc(name)}</td><td>{s["worked"]}/{s["tried"]}</td>'
                    f'<td>{bar(rate, "var(--acc)")}</td>'
                    f'<td>{esc(s.get("notes",""))}</td></tr>')

    # ---- spaced repetition ----
    sr_rows = ""
    for nid, r in sorted(profile.get("spaced_repetition", {}).items(),
                         key=lambda kv: kv[1]["next_review"]):
        overdue = r["next_review"] <= today
        sr_rows += (f'<tr class="{"bad" if overdue else ""}"><td>{esc(nodes.get(nid,{}).get("title",nid))}</td>'
                    f'<td>{esc(r["next_review"])}{" · <b>due</b>" if overdue else ""}</td>'
                    f'<td>{esc(r.get("interval_days",""))}d</td><td>{r.get("lapses",0)}</td></tr>')

    # ---- sessions timeline ----
    sess_rows = ""
    for log in reversed(sessions):
        r = log.get("reflection", {})
        items = (log.get("assessment", {}) or {}).get("items", []) or []
        ok = sum(1 for i in items if i.get("correct"))
        sess_rows += f"""<div class="card">
      <b>{esc(log.get('date',''))}</b> · {esc(log.get('goal',''))} ·
      {esc(log.get('duration_min','?'))} min · test {ok}/{len(items)} ·
      goal {'met ✓' if r.get('goal_met') else 'not met ✗'}
      <div class="cols">
        <div><small>WORKED</small><ul>{''.join(f'<li>{esc(x)}</li>' for x in r.get('what_worked', []))}</ul></div>
        <div><small>FAILED</small><ul>{''.join(f'<li>{esc(x)}</li>' for x in r.get('what_failed', []))}</ul></div>
        <div><small>NEXT TIME</small><p>{esc(r.get('next_time',''))}</p></div>
      </div></div>"""

    b = profile.get("behavior", {})
    beh = "".join(f'<tr><td>{esc(k.replace("_"," "))}</td><td>{esc(", ".join(v) if isinstance(v, list) else v)}</td></tr>'
                  for k, v in b.items() if v)
    cal = profile.get("calibration", {})
    acc = round(n_correct / n_items * 100) if n_items else 0

    page = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(sid)} — Student Analytics</title>
<style>
:root {{ --page:#f9f9f7; --card:#fcfcfb; --ink:#0b0b0b; --ink2:#52514e; --mut:#898781;
  --line:#e1e0d9; --ok:#0ca30c; --warn:#fab219; --hot:#d03b3b; --acc:#2a78d6;
  --s-num:#2a78d6; --s-alg:#1baf7a; --s-geo:#eda100; --s-mea:#008300;
  --s-dat:#4a3aa7; --s-tri:#e34948; --s-cal:#e87ba4; --s-vec:#eb6834; }}
@media (prefers-color-scheme: dark) {{
  :root {{ --page:#0d0d0d; --card:#1a1a19; --ink:#fff; --ink2:#c3c2b7; --line:#2c2c2a;
    --acc:#3987e5; --s-num:#3987e5; --s-alg:#199e70; --s-geo:#c98500;
    --s-dat:#9085e9; --s-tri:#e66767; --s-cal:#d55181; --s-vec:#d95926; }} }}
* {{ box-sizing:border-box; margin:0; }}
body {{ background:var(--page); color:var(--ink); max-width:1100px; margin:0 auto;
  padding:24px 16px 60px; font:14px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif; }}
h1 {{ font-size:22px; }} h2 {{ font-size:15px; margin:28px 0 10px; text-transform:uppercase;
  letter-spacing:.05em; color:var(--ink2); }}
.tiles {{ display:flex; gap:12px; flex-wrap:wrap; margin-top:14px; }}
.tile {{ background:var(--card); border:1px solid var(--line); border-radius:10px;
  padding:12px 16px; min-width:130px; }}
.tile b {{ font-size:22px; display:block; }}
.tile small {{ color:var(--mut); }}
table {{ width:100%; border-collapse:collapse; background:var(--card);
  border:1px solid var(--line); border-radius:10px; overflow:hidden; }}
th,td {{ text-align:left; padding:8px 10px; border-top:1px solid var(--line);
  vertical-align:top; font-size:13px; }}
th {{ font-size:11px; text-transform:uppercase; letter-spacing:.04em; color:var(--mut);
  border-top:none; }}
tr.good td:first-child {{ border-left:3px solid var(--ok); }}
tr.bad td:first-child {{ border-left:3px solid var(--hot); }}
.bar {{ position:relative; background:var(--line); border-radius:6px; height:16px;
  min-width:110px; }}
.bar div {{ height:100%; border-radius:6px; }}
.bar span {{ position:absolute; inset:0; font-size:11px; text-align:center;
  line-height:16px; color:var(--ink); }}
.dot {{ display:inline-block; width:10px; height:10px; border-radius:50%; margin-right:6px; }}
.hot {{ color:var(--hot); font-size:11px; }}
.card {{ background:var(--card); border:1px solid var(--line); border-radius:10px;
  padding:12px 16px; margin-bottom:12px; }}
.cols {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(220px,1fr));
  gap:12px; margin-top:8px; }}
.cols small {{ color:var(--mut); letter-spacing:.05em; }}
ul {{ padding-left:18px; }} p {{ color:var(--ink2); }}
.note {{ color:var(--mut); font-size:12px; margin-top:6px; }}
.scroll {{ overflow-x:auto; }}
</style></head><body>
<h1>Student {esc(sid)} — Analytics</h1>
<p class="note">Generated {today} · Class {esc(profile.get('grade'))} ·
goal: {esc(profile.get('goals',{}).get('target') or '—')} ·
anonymous id (names never stored — see harness/rules/40)</p>

<div class="tiles">
  <div class="tile"><b>{profile.get('session_count',0)}</b><small>sessions</small></div>
  <div class="tile"><b>{len([1 for m in mastery.values() if m.get('score',0)>=0.8 and m.get('conceptual_ok')])}</b><small>topics mastered</small></div>
  <div class="tile"><b>{len(mastery)}</b><small>topics with evidence</small></div>
  <div class="tile"><b>{acc}%</b><small>overall accuracy ({n_correct}/{n_items} items)</small></div>
  <div class="tile"><b>{sum(len(m.get('misconceptions_active',[])) for m in mastery.values())}</b><small>active misconceptions</small></div>
  <div class="tile"><b>{esc(cal.get('overconfidence','—'))}</b><small>calibration (＋ = overconfident)</small></div>
</div>

<h2>Mastery by strand</h2>
<div class="scroll"><table><tr><th>Strand</th><th>Progress</th><th>Avg score (seen topics)</th></tr>{strand_rows}</table></div>

<h2>Every topic with evidence</h2>
<div class="scroll"><table><tr><th>Topic</th><th>Mastery</th><th>Conceptual ✓</th><th>Items</th><th>Last seen</th><th>Active misconceptions</th></tr>{node_rows or '<tr><td colspan=6>none yet</td></tr>'}</table></div>

<h2>Misconception tracker (what to repair, and how)</h2>
<div class="scroll"><table><tr><th>Where</th><th>The faulty model</th><th>Repair stage</th><th>Recommended remedy (from the KG)</th></tr>{mis_rows or '<tr><td colspan=4>no active misconceptions 🎉</td></tr>'}</table></div>

<h2>Complete question history</h2>
<div class="scroll"><table><tr><th>Date</th><th>Topic</th><th>Question</th><th>Their answer</th><th>Result</th><th>What the answer revealed</th><th>Conf.</th></tr>{q_rows or '<tr><td colspan=7>no assessment items logged yet</td></tr>'}</table></div>
<p class="note">⚠ confident error = wrong with self-rated confidence ≥4/5 — a genuinely held misconception, not a guess. Address these first.</p>

<h2>What teaching actually works for this student</h2>
<div class="scroll"><table><tr><th>Strategy</th><th>Worked / tried</th><th>Success rate</th><th>Notes</th></tr>{st_rows or '<tr><td colspan=4>no strategy data yet</td></tr>'}</table></div>

<h2>Behavior profile</h2>
<div class="scroll"><table>{beh or '<tr><td>no behavior notes yet</td></tr>'}</table></div>

<h2>Review schedule (spaced repetition)</h2>
<div class="scroll"><table><tr><th>Topic</th><th>Next review</th><th>Interval</th><th>Lapses</th></tr>{sr_rows or '<tr><td colspan=4>nothing scheduled</td></tr>'}</table></div>

<h2>Session timeline (newest first)</h2>
{sess_rows or '<p class="note">no sessions logged yet</p>'}

<p class="note">Rebuild with: python3 scripts/build_student_page.py {esc(sid)} ·
Graph map with this student's overlay: /kg show {esc(sid)} then open viewer/index.html</p>
</body></html>"""

    out = sdir / "report.html"
    out.write_text(page)
    print(f"Wrote {out.relative_to(ROOT)} ({len(sessions)} sessions, {n_items} Q&A items, "
          f"{len(mastery)} topics with evidence)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
