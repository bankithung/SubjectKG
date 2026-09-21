/* Jev console.
 *
 * Everything the server returns is a distribution, so almost everything here funnels
 * through one renderer: strip(). Keeping a single reading surface means a Noul, a
 * Choice over 3 options and a Choice over 52 concepts are all read the same way, and
 * the eye learns the shape once.
 */

const $ = (selector, scope = document) => scope.querySelector(selector);
const $$ = (selector, scope = document) => [...scope.querySelectorAll(selector)];

const escapeHtml = (value) => String(value ?? "").replace(
  /[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]),
);
const pct = (value) => `${(value * 100).toFixed(0)}%`;
const fixed = (value, places = 2) => Number(value ?? 0).toFixed(places);

let GRAPH = { nodes: [], strands: {} };

/* ------------------------------------------------------------------ transport */

async function api(path, body) {
  const response = await fetch(path, body
    ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }
    : undefined);
  const payload = await response.json().catch(() => ({ error: `${response.status} ${response.statusText}` }));
  if (!response.ok) throw new Error(payload.error || `request failed (${response.status})`);
  return payload;
}

async function refreshStats() {
  try {
    const stats = await api("/api/stats");
    $("#sCalls").textContent = stats.calls;
    $("#sCached").textContent = stats.cache_hits;
    $("#sIn").textContent = stats.input_tokens.toLocaleString();
    $("#sOut").textContent = stats.output_tokens.toLocaleString();
    $("#modelTag").textContent = stats.model;
  } catch { /* the readout is informational; never block work on it */ }
}

/* Wraps a run: disables the button, shows the sweep, surfaces failures in place
 * rather than only in the console, and always restores the button. */
async function run(button, outlet, work) {
  button.disabled = true;
  outlet.innerHTML = '<div class="working"><i></i></div>';
  try {
    outlet.innerHTML = await work();
  } catch (error) {
    outlet.innerHTML = `<div class="error">${escapeHtml(error.message)}</div>`;
  } finally {
    button.disabled = false;
    refreshStats();
  }
}

/* ========================= THE SIGNATURE ELEMENT ========================= */

/**
 * Draw a probability distribution as a measured bar on a 0..1 scale.
 *
 * Segments are ordered by mass and dimmed by rank, so the pick reads first while the
 * runners-up stay visible — the fragments ARE the uncertainty, and hiding them would
 * defeat the point of using a calibrated model. Anything below `floor` is swept into
 * one hatched remainder rather than becoming slivers too thin to label.
 *
 * @param {object}  options
 * @param {string}  options.name     short mono label for the judgment
 * @param {string}  options.verdict  the right-aligned plain-language conclusion (HTML)
 * @param {Array}   options.entries  [{label, value, tone}] — tone: undefined|'warn'|'good'
 * @param {number}  options.floor    mass below this collapses into the remainder
 */
function strip({ name, verdict = "", entries, floor = 0.02 }) {
  const ranked = [...entries].filter((e) => e.value > 0).sort((a, b) => b.value - a.value);
  const shown = ranked.filter((e) => e.value >= floor);
  const remainder = ranked.filter((e) => e.value < floor).reduce((sum, e) => sum + e.value, 0);

  const segments = shown.map((entry, index) => {
    const width = Math.max(entry.value * 100, 0.6);
    const label = entry.value >= 0.11 ? `${escapeHtml(entry.label)} ${pct(entry.value)}` : "";
    return `<div class="seg ${entry.tone || ""}" data-rank="${Math.min(index, 4)}"
      style="--w:${width}%;animation-delay:${index * 28}ms"
      title="${escapeHtml(entry.label)} — ${pct(entry.value)}"><span>${label}</span></div>`;
  }).join("");

  const rest = remainder > 0.001
    ? `<div class="seg rest" style="--w:${remainder * 100}%" title="${shown.length ? "everything else" : ""} — ${pct(remainder)}"></div>`
    : "";

  // Only label the legend when the bar itself could not carry the names.
  const legend = shown.length > 1 && shown.some((e) => e.value < 0.11)
    ? `<div class="legend">${shown.map((e) =>
        `<div><i style="opacity:${e.value >= 0.11 ? 1 : 0.45}"></i>${escapeHtml(e.label)} <b>${fixed(e.value)}</b></div>`,
      ).join("")}</div>`
    : "";

  return `<div class="readout">
    <div class="readout-head"><span class="name">${escapeHtml(name)}</span>
      <span class="verdict">${verdict}</span></div>
    <div class="strip">${segments}${rest}</div>
    <div class="scale"><span>0</span><span>.25</span><span>.5</span><span>.75</span><span>1</span></div>
    ${legend}
  </div>`;
}

/** A Noul is a distribution over two outcomes; drawing it as one keeps the reading consistent. */
function noulStrip(name, probability, yes, no, tone) {
  return strip({
    name,
    verdict: `<b>${fixed(probability)}</b>`,
    entries: [
      { label: yes, value: probability, tone },
      { label: no, value: 1 - probability },
    ],
    floor: 0,
  });
}

/* ================================== ROUTE ================================== */

const PRESETS = {
  plain: [
    "i dont get fractions",
    "teach me long division",
    "what is a prime number",
    "explain pythagoras theorem",
  ],
  wordy: [
    "how do i share a chocolate bar equally between 3 friends",
    "the shadow of a tower is 30m and i need to find how tall it is",
    "if i flip a coin twice whats the chance i get heads both times",
    "my recipe is for 4 people but 6 are coming, how much flour",
    "why does my calculator say 0.1 + 0.2 isnt 0.3",
  ],
  edge: [
    "what do i need to know before trigonometry",
    "why is 1/2 + 1/3 not 2/5",
    "give me 5 practice questions on percentages",
    "whats after quadratic equations",
    "who was ramanujan",
    "i'm bored",
  ],
  cmp: [
    "how do i share a chocolate bar equally between 3 friends",
    "the shadow of a tower is 30m and i need to find how tall it is",
    "why is 1/2 + 1/3 not 2/5",
    "my recipe is for 4 people but 6 are coming, how much flour",
    "if i flip a coin twice whats the chance i get heads both times",
    "i dont get fractions",
    "whats the area of a circle",
    "how do i know if a shape will tile a floor with no gaps",
  ],
};

function routeCard(result) {
  if (result.error) {
    return `<div class="card flagged"><h3>${escapeHtml(result.utterance)}</h3>
      <div class="error">${escapeHtml(result.error)}</div></div>`;
  }

  const top = result.top;
  // The guardrail comes first: if it isn't maths, the routing below is noise.
  const offTopic = result.is_maths < 0.5;

  const head = `<h3>${escapeHtml(result.utterance)}</h3>
    <div class="nodeline">
      <span class="tag ${offTopic ? "bad" : "ok"}">maths ${fixed(result.is_maths)}</span>
      <span class="tag">intent · ${escapeHtml(result.intent.value)} ${fixed(result.intent.confidence)}</span>
      <span class="tag">level · ${escapeHtml(result.band.value)} ${fixed(result.band.confidence)}</span>
      <span class="tag">${result.requests} requests</span>
      <span class="tag">${result.wall_ms} ms</span>
    </div>`;

  if (offTopic) {
    return `<div class="card flagged">${head}
      <p class="lede" style="margin:0">Jev does not read this as a maths request, so the
      tutor should answer it as conversation rather than route it to a concept.</p></div>`;
  }

  if (!top) {
    return `<div class="card flagged">${head}
      <p class="lede" style="margin:0">No concept in the graph matched. Either the topic
      is genuinely absent, or the utterance is too vague to place.</p></div>`;
  }

  const beam = strip({
    name: "strand",
    verdict: `<b>${escapeHtml(result.beam[0]?.name || "—")}</b>`,
    entries: result.beam.map((b) => ({ label: b.name, value: b.probability })),
    floor: 0,
  });

  // The shortlist is what retrieval put in front of Jev — mechanical, and shown as
  // such. The decision below it is Jev's.
  const shortlist = strip({
    name: "shortlist · retrieval",
    verdict: `ranked <b>${escapeHtml(result.retrieval_top?.title || "—")}</b> first`,
    entries: result.candidates.map((c) => ({ label: c.title, value: c.path_score })),
    floor: 0.015,
  });

  const decision = result.decision ? strip({
    name: "decision · jev",
    verdict: `<b>${escapeHtml(top.title)}</b>`,
    entries: Object.entries(result.decision.probabilities).map(([id, value]) => ({
      label: (result.candidates.find((c) => c.id === id)?.title) || id,
      value,
      tone: id === result.decision.id ? "good" : undefined,
    })),
    floor: 0.01,
  }) : "";

  // The headline signal: Jev chose something other than the top retrieval hit.
  const overruled = result.decision?.overruled_ranking
    ? `<div class="remedy" style="border-left:2px solid var(--signal)">
        <span class="micro">jev overruled the ranking</span>
        Retrieval put <b>${escapeHtml(result.retrieval_top.title)}</b>
        (Class ${result.retrieval_top.grade}) first. Jev chose
        <b>${escapeHtml(top.title)}</b> (Class ${top.grade}) instead,
        at ${fixed(result.decision.confidence)} confidence.
      </div>` : "";

  const runners = result.candidates.slice(0, 5).map((candidate) => {
    const chosen = candidate.id === top.id;
    return `<tr>
      <td>${chosen ? "<b>→ </b>" : ""}${escapeHtml(candidate.title)}
        <span class="nid">${escapeHtml(candidate.id)} · Class ${candidate.grade}</span></td>
      <td class="num">${fixed(candidate.path_score)}</td>
      <td class="num">${fixed(result.decision?.probabilities[candidate.id] ?? (chosen ? 1 : 0))}</td>
    </tr>`;
  }).join("");

  return `<div class="card">${head}
    <div class="nodeline" style="margin-top:2px">
      <span class="tag on">Class ${top.grade}</span>
      <span class="tag">${escapeHtml(top.strand_name)}</span>
      <span class="tag ${result.decision?.overruled_ranking ? "bad" : "ok"}">decided by ${escapeHtml(top.decided_by)}</span>
    </div>
    <h3 style="font-size:19px">${escapeHtml(top.title)}</h3>
    <span class="nid">${escapeHtml(top.id)}</span>
    <p style="color:var(--ink-2);margin:9px 0 0">${escapeHtml(top.description)}</p>
    ${beam}${shortlist}${decision}${overruled}
    <table><thead><tr><th>candidate</th><th>retrieval</th><th>jev</th></tr></thead>
      <tbody>${runners}</tbody></table>
  </div>`;
}

/** A bare strip for table cells: the bar alone, no heading and no scale rule. */
function inlineStrip(entries) {
  return strip({ name: "", verdict: "", entries, floor: 0.02 })
    .replace('<div class="readout">', '<div class="readout" style="margin:0;gap:0">')
    .replace(/<div class="readout-head">[\s\S]*?<\/div>\s*<\/div>/, "")
    .replace(/<div class="readout-head">[\s\S]*?<\/div>/, "")
    .replace(/<div class="scale">[\s\S]*?<\/div>/, "");
}

function batchTable(results) {
  const rows = results.map((result) => {
    const top = result.top;
    const overruled = result.decision?.overruled_ranking;
    // Show Jev's decision distribution where it adjudicated; otherwise the
    // retrieval shortlist, so the column always means "what was it weighing".
    const entries = result.decision
      ? Object.entries(result.decision.probabilities).map(([id, value]) => ({
          label: result.candidates.find((c) => c.id === id)?.title || id, value,
        }))
      : result.candidates.map((c) => ({ label: c.title, value: c.path_score }));

    return `<tr class="${overruled ? "diverged" : ""}">
      <td>${escapeHtml(result.utterance)}</td>
      <td>${top ? `${escapeHtml(top.title)}<span class="nid">${escapeHtml(top.id)}</span>`
                : '<span class="miss">no match</span>'}</td>
      <td class="num">${top ? `C${top.grade}` : "—"}</td>
      <td style="width:170px">${entries.length ? inlineStrip(entries) : ""}</td>
      <td class="num">${top?.decision_confidence != null ? fixed(top.decision_confidence) : "—"}</td>
      <td class="num">${overruled ? '<span class="tag bad">overruled</span>' : ""}</td>
      <td class="num">${escapeHtml(result.intent?.value || "—")}</td>
      <td class="num">${result.wall_ms ?? 0}</td>
    </tr>`;
  }).join("");

  const overruledCount = results.filter((r) => r.decision?.overruled_ranking).length;

  return `<div class="summary-bar">
      <div><span class="micro">prompts</span><b>${results.length}</b></div>
      <div><span class="micro">routed</span><b class="ok">${results.filter((r) => r.top).length}</b></div>
      <div><span class="micro">unplaced</span><b class="${results.some((r) => !r.top) ? "bad" : ""}">${results.filter((r) => !r.top).length}</b></div>
      <div><span class="micro">jev overruled retrieval</span><b>${overruledCount}</b></div>
      <div><span class="micro">requests</span><b>${results.reduce((sum, r) => sum + (r.requests || 0), 0)}</b></div>
      <div><span class="micro">slowest</span><b>${Math.max(0, ...results.map((r) => r.wall_ms || 0))} ms</b></div>
    </div>
    <p class="lede">Highlighted rows are where Jev chose something other than the
    concept the retrieval maths ranked first. Those are the rows worth reading.</p>
    <table><thead><tr>
      <th>utterance</th><th>jev's choice</th><th>level</th><th>what it weighed</th>
      <th>conf</th><th></th><th>intent</th><th>ms</th>
    </tr></thead><tbody>${rows}</tbody></table>`;
}

function initRoute() {
  const input = $("#routeInput");
  const output = $("#routeOut");
  input.value = PRESETS.wordy.join("\n");

  $$("[data-preset]").forEach((chip) => chip.addEventListener("click", () => {
    const preset = PRESETS[chip.dataset.preset];
    if (!preset) return;
    (chip.dataset.preset === "cmp" ? $("#cmpInput") : input).value = preset.join("\n");
  }));

  $("#routeRun").addEventListener("click", () => run($("#routeRun"), output, async () => {
    const prompts = input.value.split("\n").map((line) => line.trim()).filter(Boolean);
    if (!prompts.length) return '<div class="note">Type at least one thing a learner might say.</div>';

    // One prompt deserves the full readout; many deserve a scannable table.
    if (prompts.length === 1) {
      return routeCard(await api("/api/route", { utterance: prompts[0] }));
    }
    const { results } = await api("/api/route/batch", { utterances: prompts });
    return batchTable(results);
  }));
}

/* =============================== DIAGNOSE ================================== */

const SAMPLE_ANSWERS = {
  confident: "yeah obviously, you just add the top numbers and the bottom numbers",
  hedged: "umm i think maybe you add them straight across? not sure though",
  right: "no you have to make the bottoms the same first, then add just the tops",
};

function nodeIdFromPicker(value) {
  return (value || "").trim().split(/\s+/)[0];
}

async function loadNodeQuestions(nodeId) {
  const select = $("#qPick");
  const node = GRAPH.nodes.find((n) => n.id === nodeId);
  if (!node) {
    select.innerHTML = '<option value="">— concept not found —</option>';
    return;
  }
  const detail = await api(`/api/node/${encodeURIComponent(nodeId)}`);
  select.innerHTML = '<option value="">— write my own question —</option>'
    + detail.questions.map((question, index) =>
        `<option value="${index}">${escapeHtml(question.prompt.slice(0, 90))}</option>`).join("");
  select.dataset.node = nodeId;
  select._questions = detail.questions;

  if (detail.questions.length) {
    select.value = "0";
    select.dispatchEvent(new Event("change"));
  }
}

function diagnosisCard(result) {
  const wrong = result.is_correct < 0.5;
  const misconception = result.misconception;
  const named = misconception.id !== "no_error" && misconception.id !== "other_error";

  const misconceptionStrip = strip({
    name: "misconception",
    verdict: `<b>${escapeHtml(misconception.id)}</b>`,
    entries: Object.entries(misconception.probabilities).map(([id, value]) => ({
      label: id, value, tone: id === "no_error" ? "good" : (id === misconception.id ? "warn" : undefined),
    })),
    floor: 0.01,
  });

  const depthStrip = strip({
    name: "depth of gap",
    verdict: `<b>${escapeHtml(result.depth.label)}</b> &nbsp;${fixed(result.depth.value)} / 2`,
    entries: [
      { label: "slip", value: result.depth.probabilities["0"] || 0 },
      { label: "procedural", value: result.depth.probabilities["1"] || 0, tone: "warn" },
      { label: "conceptual", value: result.depth.probabilities["2"] || 0, tone: "warn" },
    ],
    floor: 0,
  });

  // The pattern the harness cares about most: sure of themselves, and wrong.
  const flag = result.confident_error > 0.6
    ? `<span class="tag bad">confident error ${fixed(result.confident_error)}</span>` : "";

  return `<div class="card ${wrong ? "flagged" : "clean"}">
    <div class="nodeline">
      <span class="tag ${wrong ? "bad" : "ok"}">${wrong ? "incorrect" : "correct"}</span>
      ${flag}
      <span class="tag on">${escapeHtml(result.next_move.value.replace(/_/g, " "))}</span>
      <span class="tag">${result.meta.ms} ms</span>
      <span class="tag">${result.usage.input_tokens}→${result.usage.output_tokens} tok</span>
      <span class="tag">5 judgments · 1 request</span>
    </div>

    <div class="quote">${escapeHtml(result.student_answer)}</div>

    ${noulStrip("is correct", result.is_correct, "correct", "wrong", wrong ? "warn" : "good")}
    ${misconceptionStrip}
    ${named ? `<p style="margin:0 0 4px"><b>${escapeHtml(misconception.description)}</b></p>
      ${misconception.signal ? `<p style="color:var(--ink-2);margin:0 0 10px;font-size:13px">
        <span class="micro">how it shows up</span> ${escapeHtml(misconception.signal)}</p>` : ""}` : ""}
    ${depthStrip}
    ${noulStrip("sounded sure", result.confident, "confident", "hesitant",
                result.confident_error > 0.6 ? "warn" : undefined)}

    <div class="remedy">
      <span class="micro">what the tutor does next</span>
      <b>${escapeHtml(result.next_move.value.replace(/_/g, " "))}</b> —
      ${escapeHtml(result.next_move.description)}
      ${misconception.remedy ? `<div style="margin-top:10px;padding-top:10px;border-top:1px solid var(--rule)">
        <span class="micro">remedy authored in the graph</span>
        ${escapeHtml(misconception.remedy)}</div>` : ""}
    </div>

    <details class="raw"><summary>raw response</summary><pre>${escapeHtml(JSON.stringify(result, null, 2))}</pre></details>
  </div>`;
}

function initDiagnose() {
  const picker = $("#nodePick");
  const select = $("#qPick");

  picker.addEventListener("change", () => {
    const nodeId = nodeIdFromPicker(picker.value);
    if (nodeId) loadNodeQuestions(nodeId).catch(() => {});
  });

  select.addEventListener("change", () => {
    const question = (select._questions || [])[Number(select.value)];
    if (!question) return;
    $("#qPrompt").value = question.prompt;
    const key = (question.options || []).find((option) => option.correct);
    $("#qCorrect").value = key ? key.text : "";
  });

  $$("[data-answer]").forEach((chip) => chip.addEventListener("click", () => {
    $("#qAnswer").value = SAMPLE_ANSWERS[chip.dataset.answer];
  }));

  $("#diagRun").addEventListener("click", () => run($("#diagRun"), $("#diagOut"), async () => {
    const nodeId = nodeIdFromPicker(picker.value);
    if (!nodeId) return '<div class="note">Pick a concept first.</div>';
    if (!$("#qAnswer").value.trim()) return '<div class="note">Write what the student said.</div>';
    return diagnosisCard(await api("/api/diagnose", {
      node_id: nodeId,
      prompt: $("#qPrompt").value,
      correct: $("#qCorrect").value,
      answer: $("#qAnswer").value,
    }));
  }));
}

/* =================================== QUIZ ================================== */

/* One sitting, held in memory. Deliberately not persisted: this is a test bench,
 * and a half-finished quiz surviving a reload would be a bug, not a feature. */
const quiz = { node: null, questions: [], index: 0, transcript: [], answered: false };

function quizProgress() {
  return `<div class="nodeline">
    <span class="tag on">Class ${quiz.node.grade}</span>
    <span class="tag">${escapeHtml(quiz.node.title)}</span>
    <span class="tag">question ${Math.min(quiz.index + 1, quiz.questions.length)}
      of ${quiz.questions.length}</span>
  </div>`;
}

function renderQuestion() {
  const question = quiz.questions[quiz.index];
  // The options are shown as hints of the SHAPE of an answer, not as buttons to
  // click. The whole point of this screen is that free text gets diagnosed, and
  // offering a multiple choice would quietly turn it back into the old lookup.
  const shapes = (question.options || []).map((option) =>
    `<span class="tag">${escapeHtml(option.text)}</span>`).join("");

  return `<div class="card">
    ${quizProgress()}
    <h3 style="font-size:19px;margin-bottom:14px">${escapeHtml(question.prompt)}</h3>
    <div class="field">
      <label class="micro" for="quizAnswer">your answer, in your own words</label>
      <textarea id="quizAnswer" rows="3" spellcheck="false"
        placeholder="explain it however you'd say it out loud"></textarea>
    </div>
    <div class="row">
      <button class="run" id="quizSubmit">Answer</button>
      <button class="chip" id="quizSkip">Skip</button>
      <span class="micro">roughly, the answer looks like one of</span> ${shapes}
    </div>
  </div>`;
}

function answerCard(diagnosis, question) {
  const wrong = diagnosis.is_correct < 0.5;
  const misconception = diagnosis.misconception;
  const named = !["no_error", "other_error"].includes(misconception.id);

  return `<div class="card ${wrong ? "flagged" : "clean"}">
    <div class="nodeline">
      <span class="tag ${wrong ? "bad" : "ok"}">${wrong ? "not right" : "correct"}</span>
      ${diagnosis.confident_error > 0.6
        ? `<span class="tag bad">confident error ${fixed(diagnosis.confident_error)}</span>` : ""}
      <span class="tag">${diagnosis.meta.ms} ms</span>
    </div>
    <p style="margin:0 0 4px;font-size:13px;color:var(--ink-2)">${escapeHtml(question.prompt)}</p>
    <div class="quote">${escapeHtml(diagnosis.student_answer)}</div>
    ${noulStrip("is correct", diagnosis.is_correct, "correct", "wrong", wrong ? "warn" : "good")}
    ${named ? `<p style="margin:2px 0 0"><b>${escapeHtml(misconception.description)}</b></p>` : ""}
    ${wrong ? `<div class="remedy">
        <span class="micro">the answer</span> ${escapeHtml(question.options.find((o) => o.correct)?.text || "—")}
        ${question.explanation ? `<div style="margin-top:8px">${escapeHtml(question.explanation)}</div>` : ""}
        ${misconception.remedy ? `<div style="margin-top:10px;padding-top:10px;border-top:1px solid var(--rule)">
          <span class="micro">how to fix the thinking</span> ${escapeHtml(misconception.remedy)}</div>` : ""}
      </div>` : ""}
    <div class="row" style="margin-top:14px">
      <button class="run" id="quizNext">${quiz.index + 1 < quiz.questions.length
        ? "Next question" : "Finish and see the verdict"}</button>
    </div>
  </div>`;
}

function verdictCard(verdict) {
  const persistent = verdict.persistent_misconception;
  const hasPersistent = persistent.id !== "none_persistent";
  const rightCount = quiz.transcript.filter((t) => t.is_correct >= 0.5).length;

  return `<div class="card">
    <div class="nodeline">
      <span class="tag on">Class ${verdict.node.grade}</span>
      <span class="tag">${escapeHtml(verdict.node.title)}</span>
      <span class="tag">${rightCount} of ${verdict.answered} right</span>
      <span class="tag">${verdict.meta.ms} ms · 4 judgments · 1 request</span>
    </div>
    <h3 style="font-size:21px">${escapeHtml(verdict.mastery.label)}</h3>

    ${strip({
      name: "mastery · jev",
      verdict: `<b>${fixed(verdict.mastery.value)}</b> / 2`,
      entries: [
        { label: "not yet", value: verdict.mastery.probabilities["0"] || 0, tone: "warn" },
        { label: "shaky", value: verdict.mastery.probabilities["1"] || 0 },
        { label: "solid", value: verdict.mastery.probabilities["2"] || 0, tone: "good" },
      ],
      floor: 0,
    })}
    ${noulStrip("understood, not guessed", verdict.understood_not_guessed,
                "reasoning shown", "could be luck",
                verdict.understood_not_guessed < 0.4 ? "warn" : "good")}

    ${hasPersistent ? `<div class="remedy" style="border-left:2px solid var(--warn)">
        <span class="micro">one faulty idea ran through the sitting</span>
        <b>${escapeHtml(persistent.description)}</b>
        ${persistent.remedy ? `<div style="margin-top:10px;padding-top:10px;border-top:1px solid var(--rule)">
          <span class="micro">remedy authored in the graph</span>
          ${escapeHtml(persistent.remedy)}</div>` : ""}
      </div>` : ""}

    <div class="remedy">
      <span class="micro">what happens next</span>
      <b>${escapeHtml(verdict.next_step.value.replace(/_/g, " "))}</b> —
      ${escapeHtml(verdict.next_step.description)}
    </div>

    <p class="lede" style="margin:14px 0 0">This is a judgment over the whole sitting,
    not a score. ${rightCount} of ${verdict.answered} is arithmetic; which ones went
    wrong, and whether one idea caused them, is the thing worth knowing.</p>

    <div class="row" style="margin-top:14px">
      <button class="run" id="quizAgain">Take another</button>
    </div>
    <details class="raw"><summary>raw response</summary><pre>${escapeHtml(JSON.stringify(verdict, null, 2))}</pre></details>
  </div>`;
}

function quizHistory() {
  if (!quiz.transcript.length) return "";
  return `<span class="micro">answered so far</span>
    <table style="margin:7px 0 18px"><tbody>${quiz.transcript.map((item) => `<tr>
      <td class="num">${item.is_correct >= 0.5 ? '<span class="tag ok">✓</span>'
                                               : '<span class="tag bad">✕</span>'}</td>
      <td>${escapeHtml(item.prompt)}<span class="nid">${escapeHtml(item.answer)}</span></td>
      <td class="num">${item.misconception && !["no_error", "other_error"].includes(item.misconception)
        ? escapeHtml(item.misconception) : ""}</td>
    </tr>`).join("")}</tbody></table>`;
}

function paintQuiz(extra = "") {
  $("#quizOut").innerHTML = quizHistory() + extra;
  wireQuizButtons();
}

function wireQuizButtons() {
  const submit = $("#quizSubmit");
  if (submit) {
    const send = () => {
      const answer = $("#quizAnswer").value.trim();
      if (!answer) { $("#quizAnswer").focus(); return; }
      const question = quiz.questions[quiz.index];
      const correct = (question.options || []).find((o) => o.correct)?.text || "";
      run(submit, $("#quizOut"), async () => {
        const diagnosis = await api("/api/diagnose", {
          node_id: quiz.node.id, prompt: question.prompt, correct, answer,
        });
        quiz.transcript.push({
          question_id: question.id,
          prompt: question.prompt, correct, answer,
          is_correct: diagnosis.is_correct,
          misconception: diagnosis.misconception.id,
          confident: diagnosis.confident,
        });
        return quizHistory() + answerCard(diagnosis, question);
      }).then(wireQuizButtons);
    };
    submit.addEventListener("click", send);
    // Enter submits, shift+enter makes a new line — this is a short answer box.
    $("#quizAnswer").addEventListener("keydown", (event) => {
      if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); send(); }
    });
    $("#quizAnswer").focus();
  }

  const skip = $("#quizSkip");
  if (skip) skip.addEventListener("click", () => { quiz.index += 1; advanceQuiz(); });

  const next = $("#quizNext");
  if (next) next.addEventListener("click", () => { quiz.index += 1; advanceQuiz(); });

  const again = $("#quizAgain");
  if (again) again.addEventListener("click", () => {
    Object.assign(quiz, { node: null, questions: [], index: 0, transcript: [], answered: false });
    $("#quizOut").innerHTML = "";
    $("#quizSetup").hidden = false;
    $("#quizNode").focus();
  });
}

function advanceQuiz() {
  if (quiz.index < quiz.questions.length) {
    paintQuiz(renderQuestion());
    return;
  }
  if (!quiz.transcript.length) {
    paintQuiz('<div class="note">Nothing was answered, so there is nothing to judge.</div>');
    return;
  }
  // Every question done: one request, four judgments over the whole transcript.
  const outlet = $("#quizOut");
  outlet.innerHTML = quizHistory() + '<div class="working"><i></i></div>';
  api("/api/quiz/verdict", { node_id: quiz.node.id, transcript: quiz.transcript })
    .then(async (verdict) => {
      outlet.innerHTML = quizHistory() + verdictCard(verdict);
      const studentId = $("#quizStudent").value;
      if (!studentId) return;
      // Only now, on an explicit finish, does the ledger gain a file. An abandoned
      // sitting leaves no record, which is what makes crash recovery a non-event.
      try {
        const saved = await api(`/api/student/${encodeURIComponent(studentId)}/session`,
                                { log: buildSessionLog(quiz.node.id, quiz.transcript, verdict) });
        outlet.insertAdjacentHTML("beforeend", deltaCard(saved));
        refreshStudents();
      } catch (error) {
        outlet.insertAdjacentHTML("beforeend",
          `<div class="error">The sitting was judged but not recorded: ${escapeHtml(error.message)}</div>`);
      }
    })
    .catch((error) => {
      outlet.innerHTML = quizHistory() + `<div class="error">${escapeHtml(error.message)}</div>`;
    })
    .finally(() => { wireQuizButtons(); refreshStats(); });
}

async function startQuiz(nodeId) {
  const detail = await api(`/api/node/${encodeURIComponent(nodeId)}`);
  if (!detail.questions?.length) {
    $("#quizOut").innerHTML = `<div class="note">${escapeHtml(detail.title)} has no
      diagnostic questions authored yet. Try another concept.</div>`;
    return;
  }
  Object.assign(quiz, {
    node: detail, questions: detail.questions, index: 0, transcript: [], answered: false,
  });
  $("#quizSetup").hidden = true;
  paintQuiz(renderQuestion());
}

function initQuiz() {
  // Not routed through run(): startQuiz paints the stage itself and wires its own
  // buttons, so handing it back a string to inject would fight that.
  const begin = async () => {
    const nodeId = nodeIdFromPicker($("#quizNode").value);
    if (!nodeId) { $("#quizNode").focus(); return; }
    $("#quizStart").disabled = true;
    $("#quizOut").innerHTML = '<div class="working"><i></i></div>';
    try {
      await startQuiz(nodeId);
    } catch (error) {
      $("#quizOut").innerHTML = `<div class="error">${escapeHtml(error.message)}</div>`;
    } finally {
      $("#quizStart").disabled = false;
    }
  };
  $("#quizStart").addEventListener("click", begin);
  $$("[data-quiz]").forEach((chip) => chip.addEventListener("click", () => {
    const node = GRAPH.nodes.find((n) => n.id === chip.dataset.quiz);
    $("#quizNode").value = node ? `${node.id}  ${node.title}` : chip.dataset.quiz;
    begin();
  }));
}

/** Shape a finished sitting as a session log the ledger will accept. */
function buildSessionLog(nodeId, transcript, verdict) {
  const today = new Date().toISOString().slice(0, 10);
  return {
    student: $("#quizStudent").value,
    date: today,
    goal: `${nodeId}: quiz`,
    nodes_touched: [nodeId],
    reviews_done: [],
    events: [],
    assessment: {
      items: transcript.map((item) => ({
        node: nodeId,
        question: item.question_id,
        correct: item.is_correct >= 0.5,
        answer_text: item.answer,
        misconception_signalled:
          item.misconception && !["no_error", "other_error"].includes(item.misconception)
            ? item.misconception : undefined,
        jev: {
          is_correct: item.is_correct,
          misconception: item.misconception,
          confident: item.confident,
          model: $("#modelTag").textContent,
        },
      })),
    },
    profile_updates: {},
    reflection: {
      goal_met: verdict ? verdict.mastery.value >= 1.5 : false,
      evidence: verdict
        ? `Jev read the sitting as "${verdict.mastery.label}" (${verdict.mastery.value}/2).`
        : "",
    },
  };
}

function deltaCard(result) {
  if (!result.mastery_delta.length) {
    return '<div class="note">Recorded. No mastery score moved.</div>';
  }
  const rows = result.mastery_delta.map((row) => `<tr>
    <td>${escapeHtml(GRAPH.nodes.find((n) => n.id === row.node)?.title || row.node)}
      <span class="nid">${escapeHtml(row.node)}</span></td>
    <td class="num">${row.from === null || row.from === undefined ? "—" : fixed(row.from)}</td>
    <td class="num">→ ${fixed(row.to)}</td>
    <td class="num">${row.newly_mastered ? '<span class="tag ok">now mastered</span>' : ""}</td>
  </tr>`).join("");

  return `<div class="card clean">
    <span class="micro">written to the ledger — ${escapeHtml(result.written)}</span>
    <table style="margin-top:8px"><thead><tr><th>concept</th><th>was</th><th>now</th><th></th></tr></thead>
    <tbody>${rows}</tbody></table>
    ${result.warnings.length
      ? `<div class="error" style="margin-top:10px">${result.warnings.map(escapeHtml).join("<br>")}</div>`
      : ""}
  </div>`;
}

/* ================================= JOURNEY ================================= */

let STUDENTS = [];

function journeyCard(data) {
  const profile = data.profile;
  const debtOver = data.review_debt > data.debt_limit;

  const overdue = data.reviews_due.slice(0, 10).map((review) => `<tr>
    <td>${escapeHtml(GRAPH.nodes.find((n) => n.id === review.id)?.title || review.id)}
      <span class="nid">${escapeHtml(review.id)}</span></td>
    <td class="num">${review.days_overdue}d</td>
    <td class="num">${review.lapses ? `${review.lapses} lapses` : ""}</td>
  </tr>`).join("");

  const blocked = data.locked.slice(0, 12).map((node) => `<tr>
    <td>${escapeHtml(node.title)}<span class="nid">Class ${node.grade} · ${escapeHtml(node.id)}</span></td>
    <td>${node.blocked_by.map((prereq) =>
      `<b>${escapeHtml(prereq.title)}</b>${prereq.reason
        ? `<span class="nid">${escapeHtml(prereq.reason)}</span>` : ""}`).join("<br>")}</td>
  </tr>`).join("");

  const misconceptions = data.misconceptions.map((entry) => `<tr>
    <td class="num"><span class="tag ${entry.stage === "retest-due" ? "bad" : ""}">${escapeHtml(entry.stage)}</span></td>
    <td>${escapeHtml(entry.node_title)}<span class="nid">${escapeHtml(entry.node)} · ${escapeHtml(entry.id)}</span></td>
    <td class="num">${escapeHtml(entry.first_seen || "")}</td>
    <td class="num">${entry.retests_passed ?? 0} / 2</td>
  </tr>`).join("");

  return `<div class="summary-bar">
      <div><span class="micro">mastered</span><b class="ok">${data.mastered.length}</b></div>
      <div><span class="micro">ready now</span><b>${data.ready.length}</b></div>
      <div><span class="micro">locked</span><b>${data.locked.length}</b></div>
      <div><span class="micro">reviews due</span><b class="${debtOver ? "bad" : ""}">${data.review_debt}</b></div>
      <div><span class="micro">sessions</span><b>${profile.session_count ?? 0}</b></div>
    </div>

    ${debtOver ? `<div class="error">Review debt is ${data.review_debt}, over the limit of
      ${data.debt_limit}. rules/40 §6: the next session is a review session — "your brain has
      ${data.review_debt} things about to fade, let's rescue them".</div>` : ""}

    ${data.ready.length ? `<div class="card">
      <span class="micro">ready to learn — every prerequisite in place</span>
      <div class="nodeline" style="margin-top:8px">${data.ready.slice(0, 14).map((node) =>
        `<span class="tag on">Class ${node.grade} · ${escapeHtml(node.title)}</span>`).join("")}</div>
    </div>` : '<div class="note">Nothing is ready yet — this student has no recorded evidence.</div>'}

    ${overdue ? `<div class="card"><span class="micro">fading — most overdue first</span>
      <table style="margin-top:8px"><thead><tr><th>concept</th><th>overdue</th><th></th></tr></thead>
      <tbody>${overdue}</tbody></table></div>` : ""}

    ${misconceptions ? `<div class="card flagged">
      <span class="micro">active misconceptions and how far repair has got</span>
      <table style="margin-top:8px"><thead><tr><th>stage</th><th>concept</th><th>first seen</th><th>retests</th></tr></thead>
      <tbody>${misconceptions}</tbody></table></div>` : ""}

    ${blocked ? `<div class="card"><span class="micro">locked, and by what</span>
      <table style="margin-top:8px"><thead><tr><th>concept</th><th>needs first</th></tr></thead>
      <tbody>${blocked}</tbody></table></div>` : ""}`;
}

function gapsCard(data) {
  if (!data.total) {
    return `<div class="note">Nothing missing — every hard prerequisite for
      ${escapeHtml(data.target?.title || "that concept")} is already mastered.</div>`;
  }
  const rows = data.gaps.map((gap) => `<tr>
    <td class="num">${gap.teach_order + 1}</td>
    <td>${escapeHtml(gap.title)}<span class="nid">Class ${gap.grade} · ${escapeHtml(gap.id)}</span></td>
    <td style="width:170px">${inlineStrip([
      { label: "blocks", value: Math.min(1, gap.blocking / 2), tone: "warn" },
      { label: "minor", value: Math.max(0, 1 - gap.blocking / 2) },
    ])}</td>
    <td class="num">${fixed(gap.blocking)}</td>
    <td class="num">${fixed(gap.confidence)}</td>
  </tr>`).join("");

  return `<div class="card">
    <h3>${data.total} concepts between here and ${escapeHtml(data.target.title)}</h3>
    <p class="lede" style="margin:6px 0 12px">Numbered in teaching order, which respects
    prerequisites. The bar is Jev's judgment of how much each one actually blocks the
    goal — depth in the graph is not the same as consequence.</p>
    <table><thead><tr><th>#</th><th>concept</th><th>how much it blocks</th><th>score</th><th>conf</th></tr></thead>
    <tbody>${rows}</tbody></table>
  </div>`;
}

async function loadJourney() {
  const studentId = $("#journeyStudent").value;
  const outlet = $("#journeyOut");
  if (!studentId) { outlet.innerHTML = '<div class="note">Pick a student.</div>'; return; }
  outlet.innerHTML = '<div class="working"><i></i></div>';
  try {
    outlet.innerHTML = journeyCard(await api(`/api/student/${encodeURIComponent(studentId)}`));
  } catch (error) {
    outlet.innerHTML = `<div class="error">${escapeHtml(error.message)}</div>`;
  }
}

async function refreshStudents() {
  try {
    const { students } = await api("/api/students");
    STUDENTS = students;
    const options = students.length
      ? students.map((s) => `<option value="${escapeHtml(s.id)}">${escapeHtml(s.id)} · Class ${s.grade ?? "?"} · ${s.mastered} mastered</option>`).join("")
      : '<option value="">— no students yet —</option>';
    ["#journeyStudent", "#quizStudent"].forEach((selector) => {
      const element = $(selector);
      if (element) element.innerHTML = `<option value="">— none —</option>${options}`;
    });
  } catch { /* the console still works without a student list */ }
}

function initJourney() {
  $("#journeyStudent").addEventListener("change", loadJourney);
  $("#journeyGaps").addEventListener("click", () =>
    run($("#journeyGaps"), $("#journeyOut"), async () => {
      const studentId = $("#journeyStudent").value;
      const target = nodeIdFromPicker($("#journeyTarget").value);
      if (!studentId) return '<div class="note">Pick a student first.</div>';
      if (!target) return '<div class="note">Pick a concept to aim at.</div>';
      return gapsCard(await api(`/api/student/${encodeURIComponent(studentId)}/gaps`,
                                { target }));
    }));
}

/* ================================== AUDIT ================================== */

function edgeFinding(finding) {
  if (finding.error) {
    return `<div class="card flagged"><div class="error">${escapeHtml(finding.error)}</div></div>`;
  }
  const needsWork = finding.action_needed;
  return `<div class="card ${needsWork ? "flagged" : "clean"}">
    <div class="nodeline">
      <span class="tag ${finding.declared === "hard" ? "on" : ""}">declared ${escapeHtml(finding.declared)}</span>
      <span class="tag ${finding.model_strength !== finding.declared ? "bad" : "ok"}">Jev reads ${escapeHtml(finding.model_strength)}</span>
      <span class="tag ${needsWork ? "bad" : "ok"}">${escapeHtml(finding.verdict.replace(/_/g, " "))}
        ${fixed(finding.verdict_confidence)}</span>
      <span class="tag">urgency ${fixed(finding.urgency, 1)}/2</span>
    </div>
    <h3>${escapeHtml(finding.from.title)} &nbsp;→&nbsp; ${escapeHtml(finding.to.title)}</h3>
    <span class="nid">Class ${finding.from.grade} ${escapeHtml(finding.from.id)} → Class ${finding.to.grade} ${escapeHtml(finding.to.id)}</span>
    <div class="quote">${escapeHtml(finding.reason) || "<em>no reason written</em>"}</div>

    ${strip({
      name: "verdict · jev",
      verdict: `<b>${escapeHtml(finding.verdict.replace(/_/g, " "))}</b>`,
      entries: Object.entries(finding.verdict_probabilities).map(([id, value]) => ({
        label: id.replace(/_/g, " "), value, tone: id === "keep" ? "good" : "warn",
      })),
      floor: 0.01,
    })}
    ${strip({
      name: "urgency",
      verdict: `<b>${fixed(finding.urgency)}</b> / 2`,
      entries: [
        { label: "nothing to do", value: Math.max(0, 1 - finding.urgency), tone: "good" },
        { label: "fix before the graph gates a child", value: Math.min(1, finding.urgency / 2), tone: "warn" },
      ],
      floor: 0,
    })}
    ${noulStrip("must be learned first", finding.required, "required", "not required")}
  </div>`;
}

const OPTION_KIND_LABEL = {
  careless_slip: "a slip, not a faulty model",
  not_diagnostic: "filler — reveals nothing",
  actually_correct: "this option is also correct",
};

function questionFinding(finding) {
  if (finding.error) {
    return `<div class="card flagged"><div class="error">${escapeHtml(finding.error)}</div></div>`;
  }
  const needsWork = finding.action_needed;
  const correct = (finding.options || []).find((option) => option.correct);

  // Every wrong option, with what the author tagged it against what Jev says a
  // student picking it is actually thinking. This is the graph's "no option is
  // random" rule, checked rather than asserted.
  const optionRows = (finding.options_judged || []).map((option) => {
    const label = OPTION_KIND_LABEL[option.jev] || escapeHtml(option.jev);
    return `<tr>
      <td class="num">${escapeHtml(option.label)}</td>
      <td>${escapeHtml(option.text)}</td>
      <td class="num">${option.authored ? escapeHtml(option.authored) : '<span class="miss">untagged</span>'}</td>
      <td>${label}${option.jev_description
        ? `<span class="nid">${escapeHtml(option.jev_description)}</span>` : ""}</td>
      <td class="num">${fixed(option.confidence)}</td>
      <td class="num">${option.agrees ? '<span class="tag ok">same</span>'
        : option.jev === "not_diagnostic" ? '<span class="tag bad">filler</span>'
        : '<span class="tag bad">differs</span>'}</td>
    </tr>`;
  }).join("");

  const counts = [
    finding.option_disagreements ? `${finding.option_disagreements} re-tagged` : "",
    finding.option_untagged_but_diagnostic
      ? `${finding.option_untagged_but_diagnostic} called a slip but maps to a real misconception` : "",
    finding.option_filler ? `${finding.option_filler} filler` : "",
  ].filter(Boolean).join(" · ");

  return `<div class="card ${needsWork ? "flagged" : "clean"}">
    <div class="nodeline">
      <span class="tag">Class ${finding.node.grade}</span>
      <span class="tag">${escapeHtml(finding.node.id)} · ${escapeHtml(finding.question_id)}</span>
      <span class="tag ${needsWork ? "bad" : "ok"}">${escapeHtml(finding.verdict.replace(/_/g, " "))}
        ${fixed(finding.verdict_confidence)}</span>
      <span class="tag">urgency ${fixed(finding.urgency, 1)}/2</span>
    </div>
    <h3>${escapeHtml(finding.prompt)}</h3>
    ${correct ? `<p style="margin:4px 0 12px;color:var(--ink-2);font-size:13px">
      <span class="micro">answer</span> ${escapeHtml(correct.text)}</p>` : ""}

    <span class="micro">what each wrong option detects${counts ? ` — ${escapeHtml(counts)}` : ""}</span>
    <table style="margin:7px 0 4px"><thead><tr>
      <th></th><th>option</th><th>author says</th><th>jev says</th><th>conf</th><th></th>
    </tr></thead><tbody>${optionRows}</tbody></table>

    ${strip({
      name: "verdict · jev",
      verdict: `<b>${escapeHtml(finding.verdict.replace(/_/g, " "))}</b>`,
      entries: Object.entries(finding.verdict_probabilities).map(([id, value]) => ({
        label: id.replace(/_/g, " "), value, tone: id === "keep" ? "good" : "warn",
      })),
      floor: 0.01,
    })}
    ${strip({
      name: "distractors diagnose",
      verdict: `<b>${fixed(finding.distractor_quality)}</b> / 2`,
      entries: [
        { label: "filler", value: Math.max(0, 1 - finding.distractor_quality), tone: "warn" },
        { label: "each reveals a specific error", value: Math.min(1, finding.distractor_quality / 2) },
      ],
      floor: 0,
    })}
    ${noulStrip("readable at this class level", finding.age_appropriate, "suits Class " + finding.node.grade,
                "off-level", finding.age_appropriate < 0.4 ? "warn" : undefined)}
  </div>`;
}

function initAudit() {
  $("#auditRun").addEventListener("click", () => run($("#auditRun"), $("#auditOut"), async () => {
    const target = $("#auditTarget").value;
    const result = await api(`/api/audit/${target}`, {
      limit: Number($("#auditLimit").value) || 20,
      offset: Number($("#auditOffset").value) || 0,
    });
    const needing = result.findings.filter((f) => f.action_needed).length;
    const total = result.total_edges ?? result.total_questions;
    const retagged = result.findings.reduce((sum, f) =>
      sum + (f.option_disagreements || 0) + (f.option_untagged_but_diagnostic || 0), 0);

    const summary = `<div class="summary-bar">
      <div><span class="micro">checked</span><b>${result.audited}</b></div>
      <div><span class="micro">of</span><b>${total}</b></div>
      <div><span class="micro">jev says act</span><b class="${needing ? "bad" : "ok"}">${needing}</b></div>
      <div><span class="micro">jev says keep</span><b class="ok">${result.audited - needing}</b></div>
      ${target === "questions" ? `<div><span class="micro">options re-diagnosed</span><b class="${retagged ? "bad" : "ok"}">${retagged}</b></div>` : ""}
    </div>
    <p class="lede">Ordered by the urgency Jev assigned, worst first. Nothing in this
    list came from a threshold in the code — the verdict and the ordering are both
    the model's.</p>`;

    const render = target === "edges" ? edgeFinding : questionFinding;
    return summary + result.findings.map(render).join("");
  }));
}

/* ================================= COMPARE ================================= */

function initCompare() {
  $("#cmpInput").value = PRESETS.cmp.join("\n");

  $("#cmpRun").addEventListener("click", () => run($("#cmpRun"), $("#cmpOut"), async () => {
    const prompts = $("#cmpInput").value.split("\n").map((l) => l.trim()).filter(Boolean);
    if (!prompts.length) return '<div class="note">Add some prompts to compare.</div>';
    const { rows, summary } = await api("/api/compare", { utterances: prompts });

    const body = rows.map((row) => `<tr class="${row.agree ? "" : "diverged"}">
      <td>${escapeHtml(row.utterance)}</td>
      <td>${row.jev ? `${escapeHtml(row.jev.title)}<span class="nid">Class ${row.jev.grade}${
          row.jev.confidence != null ? ` · decided at ${fixed(row.jev.confidence)}` : ""}</span>`
                    : '<span class="miss">no match</span>'}</td>
      <td>${row.keyword ? `${escapeHtml(row.keyword.title)}<span class="nid">Class ${row.keyword.grade} · ${fixed(row.keyword.score)}</span>`
                        : '<span class="miss">nothing found</span>'}</td>
      <td class="num">${row.agree ? "same" : "differs"}</td>
    </tr>`).join("");

    return `<div class="summary-bar">
        <div><span class="micro">prompts</span><b>${summary.prompts}</b></div>
        <div><span class="micro">same answer</span><b>${summary.agreed}</b></div>
        <div><span class="micro">differed</span><b class="bad">${summary.diverged}</b></div>
        <div><span class="micro">keyword found nothing</span><b class="bad">${summary.keyword_found_nothing}</b></div>
      </div>
      <p class="lede">Rows are highlighted where the two disagree. Read them yourself —
      divergence is not automatically a win for either side, and that judgement is the
      point of the screen.</p>
      <table><thead><tr><th>utterance</th><th>Jev · beam search</th><th>keyword · today</th><th></th></tr></thead>
      <tbody>${body}</tbody></table>`;
  }));
}

/* ================================== shell ================================== */

function initShell() {
  $$(".mode").forEach((button) => button.addEventListener("click", () => {
    $$(".mode").forEach((other) => other.setAttribute("aria-current", String(other === button)));
    $$(".stage").forEach((stage) => { stage.hidden = stage.id !== `stage-${button.dataset.stage}`; });
  }));

  const root = document.documentElement;
  const stored = localStorage.getItem("jev-theme");
  if (stored) root.dataset.theme = stored;
  else root.removeAttribute("data-theme");  // fall back to the OS preference

  $("#themeBtn").addEventListener("click", () => {
    const next = root.dataset.theme === "dark" ? "light" : "dark";
    root.dataset.theme = next;
    try { localStorage.setItem("jev-theme", next); } catch { /* private mode */ }
  });
}

async function boot() {
  initShell();
  initRoute();
  initQuiz();
  initJourney();
  initDiagnose();
  initAudit();
  initCompare();

  try {
    GRAPH = await api("/api/graph");
    $("#cNodes").textContent = GRAPH.counts.nodes;
    $("#cEdges").textContent = GRAPH.counts.edges;
    $("#cQuestions").textContent = GRAPH.counts.questions;
    $("#cMis").textContent = GRAPH.counts.misconceptions;

    $("#nodeList").innerHTML = GRAPH.nodes.map((node) =>
      `<option value="${escapeHtml(node.id)}  ${escapeHtml(node.title)}">Class ${node.grade} · ${node.questions} questions</option>`).join("");

    await refreshStudents();

    // Open on a concept that has both authored questions and misconceptions, so the
    // diagnose screen is useful without hunting for a good example first.
    const seed = GRAPH.nodes.find((n) => n.id === "g5.num.fractions-add-sub")
      || GRAPH.nodes.find((n) => n.questions > 0 && n.misconceptions > 1);
    if (seed) {
      $("#nodePick").value = `${seed.id}  ${seed.title}`;
      await loadNodeQuestions(seed.id);
      $("#qAnswer").value = SAMPLE_ANSWERS.confident;
    }
  } catch (error) {
    document.body.insertAdjacentHTML("afterbegin",
      `<div class="error" style="margin:14px">Could not load the graph: ${escapeHtml(error.message)}</div>`);
  }
  refreshStats();
}

boot();
