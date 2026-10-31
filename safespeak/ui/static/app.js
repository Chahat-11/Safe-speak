/* SafeSpeak run monitor. Reads the server's event stream and draws three views of it:
   the run sheet (time), the case record (the blackboard) and the guardrail log.
   All message and LLM text is untrusted, so it only ever goes in through textContent. */

"use strict";

const ROWS = [
  { name: "input guardrail", label: "Entry check", role: "hides secrets", kind: "safety check", status: "The entry check is reading the message..." },
  { name: "coordinator", label: "Coordinator", role: "runs the team", kind: "fixed rules", status: "The Coordinator is opening a case..." },
  { name: "parser", label: "Reader", role: "pulls out the facts", kind: "AI model", status: "The Reader is pulling out the facts..." },
  { name: "router", label: "Router", role: "picks who looks", kind: "fixed rules", status: "The Router is choosing who should look..." },
  { name: "verifier", label: "Link checker", role: "looks up each website", kind: "AI + tools", status: "The Link checker is looking up each website..." },
  { name: "pattern", label: "Pattern finder", role: "known scam tricks", kind: "fixed rules", status: "The Pattern finder is comparing known scam tricks..." },
  { name: "retrieval", label: "Past cases", role: "similar old messages", kind: "not built yet", status: "Past cases: not built yet..." },
  { name: "correlation", label: "Scam waves", role: "related campaigns", kind: "not built yet", status: "Scam waves: not built yet..." },
  { name: "reasoner", label: "Reasoner", role: "decides", kind: "AI model", status: "The Reasoner is weighing the evidence..." },
  { name: "explainer", label: "Explainer", role: "writes the answer", kind: "AI model", status: "The Explainer is writing the answer..." },
  { name: "critic", label: "Critic", role: "checks the answer", kind: "AI model", status: "The Critic is checking the answer..." },
  { name: "output guardrail", label: "Exit check", role: "keeps the reply safe", kind: "safety check", status: "The exit check is making the reply safe..." },
];

const ARCHITECTURES = {
  hierarchical: { label: "Coordinated", hint: "The Coordinator chooses who looks, and can send work back." },
  sequential: { label: "In turn", hint: "Every helper takes a turn in a fixed order. Nothing is sent back." },
  parallel: { label: "All at once", hint: "The helpers all look at the same time. Nothing is sent back." },
};

const ANSWER_WORDS = { scam: "Scam", suspicious: "Suspicious", likely_safe: "Probably safe", uncertain: "Not sure" };
const SECRET_NAMES = { OTP: "an OTP", ACCOUNT: "an account number", CARD: "a card number", AADHAAR: "an Aadhaar number" };
const GUARD_WORDS = {
  skip_if_nothing_to_check: "nothing new to check",
  skip_useless_loop_back: "nothing new to find",
  cap_reasoner_loops: "limit on looking again reached",
  cap_critic_loops: "limit on rewrites reached",
};

const MAX_LOOPS = 2; // MAX_REASONER_LOOPS and MAX_CRITIC_LOOPS in schemas.py
const AXIS_STEPS = [10, 15, 20, 30, 45, 60, 90, 120, 180, 240, 300, 450, 600, 900, 1200, 1800, 3600];
const TICK_STEPS = [1, 2, 5, 10, 15, 30, 60, 120, 300, 600];
const NOTE_GAP = 5; // px between a mark and its note
const MARK_MIN_WIDTH = { skip: 10, tool: 6 }; // px; matches min-width in style.css, other marks are 3
const DESKTOP = "(min-width: 1100px) and (min-height: 640px)"; // the layout where each column scrolls alone

const $ = (id) => document.getElementById(id);

/* ---------- small helpers ---------- */

function make(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function formatMs(ms) {
  if (ms === undefined || ms === null) return "";
  if (ms < 1) return `${ms.toFixed(1)} ms`;
  if (ms < 1000) return `${Math.round(ms)} ms`;
  return `${(ms / 1000).toFixed(1)} s`;
}

function plural(count, word) {
  return `${count} ${word}${count === 1 ? "" : "s"}`;
}

function agentLabel(name) {
  const row = ROWS.find((item) => item.name === name);
  return row ? row.label : name;
}

/* "OTP, CARD" from a guardrail reason becomes "an OTP and a card number". */
function secretWords(reason) {
  const names = reason.split(": ").pop().split(", ").map((label) => SECRET_NAMES[label] || label);
  return names.length < 2 ? names.join("") : `${names.slice(0, -1).join(", ")} and ${names[names.length - 1]}`;
}

function setStatus(text) {
  if ($("status").textContent !== text) $("status").textContent = text;
}

/* ---------- run state ---------- */

let run = newRun();

function newRun() {
  return {
    spans: [], openAgents: {}, openModels: {}, openTools: {},
    firstT: null, lastT: 0, lastArrival: 0,
    live: false, tokens: 0, case: null, axisMax: AXIS_STEPS[0], selected: null, logged: 0,
  };
}

/* Bars use the event's own `t`, so a replay draws the recorded times even though
   its long waits are shortened. Between events the clock just keeps counting. */
function clock() {
  return run.live ? run.lastT + (performance.now() - run.lastArrival) / 1000 : run.lastT;
}

function noteTime(event) {
  if (event.t === undefined) { // `done` has no time of its own; do not present arrival jitter as a measurement
    if (event.event !== "done") run.lastT = clock();
    run.lastArrival = performance.now();
    return run.lastT;
  }
  if (run.firstT === null) run.firstT = event.t;
  run.lastT = (event.t - run.firstT) / 1000;
  run.lastArrival = performance.now();
  return run.lastT;
}

/* ---------- reading events ---------- */

function handleEvent(event) {
  const time = noteTime(event);
  if (event.case) updateCase(event.case, event);
  const handler = HANDLERS[event.event];
  if (handler) handler(event, time);
  render();
}

const HANDLERS = {
  agent_start(event, time) {
    if (run.openAgents[event.name]) closeAsFailed(event.name, time); // retry: no agent_end came
    run.openAgents[event.name] = addSpan("agent", event.name, time, event);
    if (event.name === "coordinator") addGuard("input guardrail", time, "Ran before the Coordinator started.", "input");
  },
  agent_end(event, time) {
    const span = run.openAgents[event.name];
    if (span) { closeSpan(span, time, event); span.wrote = event.wrote; delete run.openAgents[event.name]; }
    closeOpenChildren(event.name, time);
    if (event.name === "coordinator") {
      run.openAgents["output guardrail"] = addGuard("output guardrail", time, "Ran after the Coordinator ended. It has no timing events of its own, so no duration is shown.", "output");
    }
  },
  agent_skipped(event, time) {
    const span = run.openAgents[event.name];
    if (span) { closeSpan(span, time, event); span.skippedBy = event.guard; delete run.openAgents[event.name]; }
    closeOpenChildren(event.name, time);
    if (event.guard === "input_guardrail") {
      const guardSpan = run.spans.find((item) => item.row === "input guardrail");
      if (guardSpan) { guardSpan.kind = "skip"; guardSpan.blocked = true; guardSpan.guard = event.guard; styleSpan(guardSpan); }
      run.blocked = true;
      // A blocked message never opens a case, so the record cannot carry this entry.
      appendLogEntry({ stage: "input", action: "blocked", reason: "See the answer." });
      return;
    }
    addSkip(event.name, time, event);
  },
  model_start(event, time) {
    run.openModels[event.name] = addSpan("model", event.name, time, event);
  },
  model_end(event, time) {
    const span = run.openModels[event.name];
    if (span) { closeSpan(span, time, event); delete run.openModels[event.name]; }
    run.tokens += (event.prompt_tokens || 0) + (event.completion_tokens || 0);
  },
  model_skipped(event, time) {
    const span = run.openModels[event.name];
    if (span) { removeSpan(span); delete run.openModels[event.name]; }
    addSkip(event.name, time, event);
  },
  tool_start(event, time) {
    const span = addSpan("tool", event.name, time, event);
    span.tool = event.tool;
    span.lane = freeToolLane(event.name);
    run.openTools[`${event.name}/${event.tool}`] = span;
    styleSpan(span);
  },
  tool_end(event, time) {
    const key = `${event.name}/${event.tool}`;
    const span = run.openTools[key];
    if (!span) return;
    closeSpan(span, time, event);
    delete run.openTools[key];
    styleSpan(span);
  },
  done(event, time) {
    finishRun(time);
    if (event.total_tokens !== undefined) run.tokens = event.total_tokens;
    run.finished = true;
    showConclusion(event);
    revealConclusion();
    $("status").hidden = true;
    markRowsThatNeverRan();
  },
  error(event, time) {
    failRun(event.kind, event.message, time);
  },
};

function closeOpenChildren(agent, time) {
  const model = run.openModels[agent];
  if (model) { model.failed = true; closeSpan(model, time, null); styleSpan(model); delete run.openModels[agent]; }
  for (const key of Object.keys(run.openTools)) {
    if (key.startsWith(`${agent}/`)) {
      const tool = run.openTools[key];
      tool.failed = true;
      closeSpan(tool, time, null);
      styleSpan(tool);
      delete run.openTools[key];
    }
  }
}

function closeAsFailed(agent, time) {
  const span = run.openAgents[agent];
  span.failed = true;
  closeSpan(span, time, null);
  styleSpan(span);
  delete run.openAgents[agent];
  closeOpenChildren(agent, time);
}

/* Terminal: output guardrail closes normally; anything else still open did not finish. */
function finishRun(time) {
  const output = run.openAgents["output guardrail"];
  if (output) { closeSpan(output, time, null); delete run.openAgents["output guardrail"]; }
  Object.keys(run.openAgents).forEach((agent) => closeAsFailed(agent, time));
  run.live = false;
}

function failRun(kind, message, time) {
  finishRun(time === undefined ? clock() : time);
  $("status").hidden = true;
  showError(kind, message);
  setBusy(false);
  render();
}

/* ---------- spans: one positioned button per bar ---------- */

function addSpan(kind, rowName, time, event) {
  const span = { kind, row: rowName, start: time, end: null, startEvent: event, event, failed: false };
  span.node = make("button", "bar");
  span.node.type = "button";
  span.node.addEventListener("click", () => selectSpan(span));
  trackFor(rowName).append(span.node);
  run.spans.push(span);
  styleSpan(span);
  return span;
}

function addSkip(rowName, time, event) {
  const span = addSpan("skip", rowName, time, event);
  span.end = time;
  span.guard = event.guard;
  styleSpan(span);
}

/* Guardrail callbacks emit no timing events, so they are always a tick, never a bar. */
function addGuard(rowName, time, description, stage) {
  const span = addSpan("guard", rowName, time, {});
  span.description = description;
  span.stage = stage;
  span.end = time;
  styleSpan(span);
  return span;
}

function closeSpan(span, time, event) {
  span.end = time;
  if (event) span.event = event;
}

function removeSpan(span) {
  span.node.remove();
  run.spans.splice(run.spans.indexOf(span), 1);
}

function freeToolLane(agent) {
  const busy = Object.keys(run.openTools).filter((key) => key.startsWith(`${agent}/`)).length;
  return busy % 2;
}

function styleSpan(span) {
  const barKind = span.kind === "guard" ? "agent" : span.kind;
  const classes = ["bar", `bar-${barKind}`];
  if (span.kind === "tool") {
    classes.push(`lane-${span.lane || 0}`);
    const finding = span.event.finding;
    if (finding) classes.push(`result-${finding.result}`);
  }
  if (span.blocked) classes.push("blocked");
  if (span.failed) classes.push("failed");
  if (span === run.selected) classes.push("selected");
  span.node.className = classes.join(" ");
  span.node.setAttribute("aria-label", describeSpan(span));
  span.node.setAttribute("aria-pressed", span === run.selected ? "true" : "false");
  span.node.title = describeSpan(span);
}

function describeSpan(span) {
  const what = { agent: "run", guard: "callback", model: "model call", tool: span.tool, skip: `skipped by ${span.guard}` }[span.kind];
  const length = span.event && span.event.duration_ms !== undefined ? `, ${formatMs(span.event.duration_ms)}` : "";
  return `${span.row} ${what}${length}${span.failed ? ", failed" : ""}`;
}

function trackFor(rowName) {
  let row = ROW_NODES[rowName];
  if (!row) { // an agent we do not know about still gets drawn rather than lost
    addRow({ name: rowName, role: "", kind: "" });
    row = ROW_NODES[rowName];
  }
  return row.track;
}

/* ---------- drawing the sheet ---------- */

const ROW_NODES = {};

function addRow({ name, label: title, role, kind }) {
  const row = make("div", "row");
  const label = make("div", "row-label");
  const heading = make("span", "row-name", title || name);
  // The code name helps only where it differs from the plain name and is a real agent.
  if (title && title.toLowerCase() !== name && kind !== "safety check") heading.append(make("span", "row-code", name));
  label.title = role || "";
  label.append(heading, make("span", "row-role", role), make("span", "row-kind", kind));
  const track = make("div", "track");
  const note = make("span", "note");
  note.hidden = true;
  track.append(note);
  row.append(label, track);
  $("rows").append(row);
  ROW_NODES[name] = { row, track, note };
}

function chooseAxisMax(now) {
  if (run.finished && now >= 1) return now * 1.02; // a finished run fills the width
  return AXIS_STEPS.find((step) => step >= now * 1.04) || now * 1.2;
}

function drawAxis() {
  const max = run.axisMax;
  const tick = TICK_STEPS.find((step) => max / step <= 6) || max / 6;
  const axis = $("axis");
  axis.replaceChildren();
  for (let value = 0; value < max; value += tick) {
    const label = make("span", "", value === 0 ? "0 s" : String(value));
    label.style.left = `${(value / max) * 100}%`;
    axis.append(label);
  }
  $("sheet").style.setProperty("--tick", `${(tick / max) * 100}%`);
}

function positionSpan(span, now) {
  const end = span.end === null ? now : span.end;
  span.node.style.left = `${(span.start / run.axisMax) * 100}%`;
  span.node.style.width = `${((end - span.start) / run.axisMax) * 100}%`;
}

/* One short plain finding per row, taken from the case when that run ended. */
const FINDINGS = {
  parser(record) {
    const parsed = record.parsed;
    if (!parsed) return "";
    const links = parsed.urls.length;
    return [parsed.claimed_organisation && `claims to be ${parsed.claimed_organisation}`,
      links && `${links} link${links === 1 ? "" : "s"}`,
      parsed.asks_for_credentials && "asks for a secret"].filter(Boolean).join(", ") || "nothing unusual";
  },
  router: (record) => (record.routing ? `asked ${plural(record.routing.specialists.length, "helper")}` : ""),
  verifier(record) {
    const results = record.verifier_findings.map((finding) => finding.result);
    if (!results.length) return "no websites to check";
    const worrying = results.filter((result) => result === "suspicious" || result === "malicious").length;
    return worrying ? `${worrying} of ${plural(results.length, "check")} worrying` : `${plural(results.length, "check")}, nothing worrying`;
  },
  pattern(record) {
    const count = record.pattern_matches.length;
    return count ? plural(count, "scam pattern") : "no known pattern";
  },
  retrieval: () => "not built yet",
  correlation: () => "not built yet",
  reasoner: (record) => (record.verdict ? `${ANSWER_WORDS[record.verdict.label]}, ${Math.round(record.verdict.confidence * 100)}%` : ""),
  explainer: (record) => (record.explanation ? "answer written" : ""),
  critic: (record) => (record.critique ? (record.critique.approved ? "approved" : "asked for a rewrite") : ""),
};

function rowFinding(rowName, last) {
  const finding = FINDINGS[rowName];
  const record = last.event.case || run.case;
  return finding && record && last.end !== null && !last.failed ? finding(record) : "";
}

function drawRowNote(rowName, now) {
  const { note } = ROW_NODES[rowName];
  const spans = run.spans.filter((span) => span.row === rowName);
  const runs = spans.filter((span) => span.kind === "agent" || span.kind === "guard" || span.blocked);
  if (!runs.length) { note.hidden = true; return; }
  const last = runs[runs.length - 1];
  note.replaceChildren();
  note.className = "note";
  note.hidden = false;
  const end = last.end === null ? now : last.end;
  const milliseconds = last.event.duration_ms !== undefined ? last.event.duration_ms : (end - last.start) * 1000;
  const prefix = runs.length > 1 ? `ran ${runs.length} times: ` : "";
  const outcome = last.skippedBy ? `skipped, ${GUARD_WORDS[last.skippedBy] || "stopped by a safety check"}` : rowFinding(rowName, last) || formatMs(milliseconds);
  note.append(last.kind === "guard" || last.blocked ? guardOutcome(last) : `${prefix}${outcome}`);
  if (runs.some((span) => span.failed)) note.append(" ", make("span", "failed-word", "did not finish"));
  placeNote(note, spans, now);
}

function guardOutcome(span) {
  if (span.blocked || (span.stage === "output" && run.case && run.case.status === "blocked")) return "stopped the message";
  if (span.stage === "output") return run.live ? "working" : "passed";
  const hid = run.case && run.case.guardrail_events.find((item) => item.stage === "input" && item.action === "redacted");
  return hid ? `hid ${secretWords(hid.reason)}` : "passed";
}

/* Measured in pixels so a note always stays inside its track and off every mark:
   after the row's last mark, else before its first, else in the lower lane, clear of tool marks. */
function placeNote(note, spans, now) {
  const width = note.parentElement.clientWidth;
  const noteWidth = note.offsetWidth;
  const toPx = (seconds) => (seconds / run.axisMax) * width;
  const markEnd = (span) => Math.max(toPx(span.end === null ? now : span.end), toPx(span.start) + (MARK_MIN_WIDTH[span.kind] || 3));
  const lastEdge = Math.max(...spans.map(markEnd));
  const firstEdge = Math.min(...spans.map((span) => toPx(span.start)));
  const fitsAfter = lastEdge + NOTE_GAP + noteWidth <= width;
  const fitsBefore = firstEdge - NOTE_GAP - noteWidth >= 0;
  note.classList.toggle("under", !fitsAfter && !fitsBefore);
  if (fitsAfter) note.style.left = `${lastEdge + NOTE_GAP}px`;
  else if (fitsBefore) note.style.left = `${firstEdge - NOTE_GAP - noteWidth}px`;
  else {
    const tools = spans.filter((span) => span.kind === "tool").map((span) => toPx(span.start));
    const edge = tools.length ? Math.min(...tools) : lastEdge;
    note.style.left = `${Math.max(0, Math.min(edge - noteWidth, width - noteWidth))}px`;
  }
}

function currentAgent() {
  const open = Object.keys(run.openAgents);
  if (!open.length) return "";
  const inner = open.filter((name) => name !== "coordinator");
  return inner.length ? inner.join(" + ") : open[0];
}

function render() {
  const now = clock();
  const max = chooseAxisMax(now);
  if (max !== run.axisMax) { run.axisMax = max; easeRescale(); }
  drawAxis();
  run.spans.forEach((span) => positionSpan(span, now));
  Object.keys(ROW_NODES).forEach((rowName) => drawRowNote(rowName, now));

  const sheet = $("sheet");
  sheet.classList.toggle("running", run.live);
  sheet.style.setProperty("--now", `${(now / run.axisMax) * 100}%`);
  $("elapsed").textContent = run.finished ? `Finished in ${Math.round(now)} s` : `${now.toFixed(1)} s`;
  $("tokens").textContent = run.tokens ? `${run.tokens.toLocaleString("en-IN")} tokens` : "";
  drawLegend();
  if (run.live) {
    const agent = currentAgent();
    if (agent) setStatus(statusFor(agent));
    Object.entries(ROW_NODES).forEach(([name, nodes]) => {
      nodes.row.classList.toggle("current", agent.split(" + ").includes(name));
    });
  } else {
    Object.values(ROW_NODES).forEach((nodes) => nodes.row.classList.remove("current"));
  }
}

/* Bars slide when the axis changes scale; while growing they already move every frame. */
function easeRescale() {
  $("sheet").classList.add("rescaling");
  setTimeout(() => $("sheet").classList.remove("rescaling"), 350);
}

function statusFor(agent) {
  const row = ROWS.find((item) => item.name === agent);
  return row ? row.status : "Several agents are checking at once...";
}

/* The key names only what is on the chart right now. */
function drawLegend() {
  const used = new Set(run.spans.map((span) => (span.kind === "guard" ? "agent" : span.kind)));
  if (run.spans.some((span) => span.failed)) used.add("failed");
  document.querySelectorAll("#legend li").forEach((item) => { item.hidden = !used.has(item.dataset.kind); });
}

function tick() {
  if (!run.live) return;
  render();
  requestAnimationFrame(tick);
}

function markRowsThatNeverRan() {
  Object.entries(ROW_NODES).forEach(([name, nodes]) => {
    if (run.spans.some((span) => span.row === name)) return;
    nodes.row.classList.add("never");
    nodes.note.className = "note never";
    nodes.note.textContent = "did not run";
    nodes.note.hidden = false;
    nodes.note.style.left = "4px";
  });
}

/* ---------- inspector ---------- */

function selectSpan(span) {
  const previous = run.selected;
  run.selected = span;
  if (previous) styleSpan(previous);
  styleSpan(span);
  inspect(span);
  showInspector();
}

/* Details sit above the case file, so on desktop the chart never moves. */
function showInspector() {
  $("details").hidden = false;
  if (matchMedia(DESKTOP).matches) $("right").scrollTop = 0;
  else $("details").scrollIntoView({ block: "nearest" });
}

function closeDetails() {
  const previous = run.selected;
  run.selected = null;
  if (previous) { styleSpan(previous); previous.node.focus(); }
  $("details").hidden = true;
}

/* Bring the verdict into view when it arrives, unless the user has scrolled off elsewhere. */
function revealConclusion() {
  if (matchMedia(DESKTOP).matches) $("centre").scrollTop = 0;
  else if (window.scrollY === run.startScroll) $("conclusion").scrollIntoView({ block: "start" });
}

function codeBlock(title, value) {
  const block = make("div");
  block.append(make("h3", "", title), make("pre", "", typeof value === "string" ? value : JSON.stringify(value, null, 2)));
  return block;
}

function inspect(span) {
  const body = $("inspector-body");
  body.replaceChildren();
  const INSPECTORS = { agent: inspectAgent, model: inspectModel, tool: inspectTool, skip: inspectSkip, guard: inspectGuard };
  INSPECTORS[span.kind](span, body);
}

function inspectHeader(body, title, meta) {
  body.append(make("p", "inspect-title", title), make("p", "inspect-meta", meta));
}

function inspectAgent(span, body) {
  const event = span.event;
  const status = span.failed ? "failed, no agent_end" : span.end === null ? "still running" : formatMs(event.duration_ms);
  inspectHeader(body, `${agentLabel(span.row)}: one run`, `started at ${span.start.toFixed(2)} s, ${status}`);
  if (span.skippedBy) body.append(make("p", "", `Skipped by guardrail ${span.skippedBy}: the agent ended without running.`));
  if (span.end === null || span.failed || span.skippedBy) return;
  const wrote = span.wrote || [];
  if (!wrote.length) { body.append(make("p", "", "Wrote nothing to the case record.")); return; }
  if (span.row === "coordinator") { // the root agent's "changes" are the whole record, written by the others
    body.append(make("p", "", `Across its whole run the record changed in: ${wrote.join(", ")}.`));
    return;
  }
  body.append(make("p", "", `Wrote to the case record: ${wrote.join(", ")}.`));
  const written = {};
  wrote.forEach((section) => { written[section] = event.case ? event.case[section] : undefined; });
  body.append(codeBlock("Values after this run", written));
}

function inspectModel(span, body) {
  const event = span.event;
  if (span.end === null) { inspectHeader(body, `${agentLabel(span.row)}: AI model call`, "waiting for the model"); return; }
  if (span.failed) { inspectHeader(body, `${agentLabel(span.row)}: AI model call`, "failed, no reply"); return; }
  const tokens = `${event.prompt_tokens} prompt + ${event.completion_tokens} reply tokens`;
  inspectHeader(body, `${agentLabel(span.row)}: AI model call`, `started at ${span.start.toFixed(2)} s, ${formatMs(event.duration_ms)}, ${tokens}`);
  const columns = make("div", "inspect-columns two");
  columns.append(codeBlock("Prompt", event.prompt || ""), codeBlock("Reply", event.reply || ""));
  body.append(columns);
}

function inspectTool(span, body) {
  const event = span.event;
  const status = span.end === null ? "still running" : span.failed ? "failed" : formatMs(event.duration_ms);
  inspectHeader(body, `${agentLabel(span.row)}: tool ${span.tool}`, `started at ${span.start.toFixed(2)} s, ${status}, through the MCP server`);
  const columns = make("div", "inspect-columns two");
  columns.append(codeBlock("Arguments", span.startEvent.args || {}));
  if (span.end !== null) columns.append(codeBlock("Returned finding", event.finding || "No finding returned."));
  body.append(columns);
}

function inspectSkip(span, body) {
  const model = span.event.event === "model_skipped";
  inspectHeader(body, `${agentLabel(span.row)}: safety check ${span.guard}`, `at ${span.start.toFixed(2)} s`);
  body.append(make("p", "", model
    ? "This guardrail answered instead of the LLM, so no model call was made."
    : "This guardrail stopped the agent before it ran."));
}

function inspectGuard(span, body) {
  const blocked = span.blocked ? " It blocked the message." : "";
  inspectHeader(body, `${agentLabel(span.row)}`, `at ${span.start.toFixed(2)} s`);
  body.append(make("p", "", `${span.description}${blocked}`));
  const events = run.case ? run.case.guardrail_events.filter((item) => item.stage === span.stage) : [];
  if (events.length) body.append(codeBlock("Its entries in the safety checks", events));
}

/* ---------- case record ---------- */

function parsedLines(parsed) {
  if (!parsed) return [];
  return [
    parsed.claimed_organisation && `Claims to be from ${parsed.claimed_organisation}.`,
    parsed.urls.length && `Links: ${parsed.urls.join(", ")}`,
    parsed.phone_numbers.length && `Phone numbers: ${parsed.phone_numbers.join(", ")}`,
    parsed.emails.length && `Emails: ${parsed.emails.join(", ")}`,
    parsed.asks_for_credentials && "Asks for a password, OTP or similar secret.",
    parsed.urgency_cues.length && `Pressure: "${parsed.urgency_cues.join('", "')}"`,
  ].filter(Boolean);
}

/* Readable sections. `lines` returns sentences; no lines means the section stays hidden. */
const SECTIONS = [
  { label: "What the message says", keys: ["parsed"], lines: (c) => parsedLines(c.parsed) },
  { label: "Who was asked to look", keys: ["routing"], lines: (c) => (c.routing ? [c.routing.specialists.map(agentLabel).join(", ")] : []) },
  { label: "Website checks", keys: ["verifier_findings"], lines: (c) => c.verifier_findings.map((finding) => finding.detail) },
  { label: "Scam tricks recognised", keys: ["pattern_matches"], lines: (c) => c.pattern_matches.map((match) => match.pattern_name) },
  { label: "Similar past cases", keys: ["retrieved_evidence"], lines: (c) => (c.retrieved_evidence.length ? [plural(c.retrieved_evidence.length, "item")] : []) },
  { label: "The decision", keys: ["verdict"], lines: (c) => (c.verdict ? [`${ANSWER_WORDS[c.verdict.label]}, ${Math.round(c.verdict.confidence * 100)}% confident.`] : []) },
  { label: "The answer written", keys: ["explanation"], lines: (c) => (c.explanation ? [c.explanation.headline] : []) },
  { label: "The Critic's review", keys: ["critique"], lines: (c) => (c.critique ? (c.critique.approved ? ["Approved."] : ["Asked for a rewrite.", ...c.critique.issues]) : []) },
];

const TECHNICAL_KEYS = ["case_id", "status", "message_text", "routing", "correlation", "reasoner_loops", "critic_loops", "capped_loops", "guardrail_events"];

function buildCaseForm() {
  $("case-form").replaceChildren();
  $("case-technical").replaceChildren();
  $("case-empty").hidden = false;
  SECTIONS.forEach((section) => {
    section.last = null;
    section.field = null;
  });
}

function addField(section) {
  const field = make("div", "field");
  section.value = make("div");
  section.writer = make("p", "field-writer");
  field.append(make("h3", "field-name", section.label), section.value, section.writer);
  section.field = field;
  $("case-form").append(field);
}

/* Who gets the credit for a change we can see between two snapshots of the case. */
function writerOf(record, event) {
  if (event.event === "done") return agentLabel("output guardrail");
  return agentLabel(event.event === "agent_start" ? "coordinator" : event.name);
}

function updateCase(record, event) {
  run.case = record;
  $("subject").hidden = false;
  $("subject-message").textContent = record.message_text || "";
  SECTIONS.forEach((section) => {
    const snapshot = JSON.stringify(section.keys.map((key) => record[key]));
    if (snapshot === section.last) return;
    section.last = snapshot;
    const lines = section.lines(record);
    if (!lines.length) return;
    if (!section.field) addField(section);
    section.value.replaceChildren(...lines.map((line) => make("p", "field-line", line)));
    section.writer.textContent = `added by ${writerOf(record, event)}`;
    flash(section.field);
    $("case-empty").hidden = true;
  });
  drawTechnical(record);
  updateGuardLog(record);
}

function drawTechnical(record) {
  $("case-technical").replaceChildren(...TECHNICAL_KEYS.map((key) => {
    const field = make("div", "field");
    const value = typeof record[key] === "string" ? record[key] : JSON.stringify(record[key], null, 1);
    field.append(make("h3", "field-name", key), make("p", "field-line", value));
    return field;
  }));
}

function toggleTechnical() {
  const panel = $("case-technical");
  panel.hidden = !panel.hidden;
  $("technical-toggle").setAttribute("aria-expanded", String(!panel.hidden));
  $("technical-toggle").textContent = panel.hidden ? "Show technical fields" : "Hide technical fields";
}

function flash(node) {
  node.classList.remove("flash");
  void node.offsetWidth; // restart the CSS animation
  node.classList.add("flash");
}

/* ---------- guardrail log ---------- */

function updateGuardLog(record) {
  const events = record.guardrail_events || [];
  events.slice(run.logged).forEach(appendLogEntry);
  run.logged = events.length;
}

/* A guardrail entry in plain words. The raw text stays one click away. */
function safetySentence(item) {
  if (item.action === "allowed") return "The message passed the entry check.";
  if (item.action === "redacted") return `Hid ${secretWords(item.reason)} ${item.stage === "input" ? "before any agent read it" : "in the answer"}.`;
  if (item.action === "flagged") return "Noticed wording that tries to instruct the agents. Noted, not blocked.";
  if (item.action === "retried") return "A reply was in the wrong form, so it was asked again.";
  if (item.action === "failed") return "A reply was still in the wrong form.";
  if (item.action === "capped") return "Stopped a loop at its limit.";
  if (item.action === "blocked") return "Stopped the message before any agent read it.";
  if (item.reason.startsWith("Critic issues not confirmed")) return "Critic objection ignored: code found no real problem.";
  return item.reason;
}

function appendLogEntry(item) {
  $("guardlog-empty").hidden = true;
  const entry = make("li");
  const details = make("details");
  details.append(make("summary", `action-${item.action}`, safetySentence(item)), make("p", "log-raw", `${item.stage} / ${item.action}: ${item.reason}`));
  entry.append(details);
  $("guardlog").append(entry);
}

/* ---------- conclusion ---------- */

function bulletList(tag, title, items) {
  const block = make("div");
  const list = make(tag);
  items.forEach((item) => list.append(make("li", "", item)));
  block.append(make("h3", "", title), list);
  return block;
}

function showConclusion(event) {
  const body = $("conclusion-body");
  body.replaceChildren();
  $("conclusion").hidden = false;
  const record = event.case;
  if (!record || !record.verdict || !record.explanation || record.status === "blocked") {
    if (!record || record.status === "blocked") body.append(make("p", "error-title", "Not checked"));
    body.append(make("p", "verdict-plain", plainText(event.markdown) || "The run ended without a verdict."));
    return;
  }
  const { verdict, explanation } = record;
  const line = make("div", "verdict-line");
  line.append(
    make("p", `verdict-label label-${verdict.label}`, ANSWER_WORDS[verdict.label]),
    make("span", "verdict-confidence", `${Math.round(verdict.confidence * 100)}% confident`),
  );
  const columns = make("div", "verdict-columns");
  columns.append(bulletList("ul", "Why", explanation.why), bulletList("ol", "What to do", explanation.what_to_do));
  body.append(line, make("p", "verdict-headline", explanation.headline), columns);
}

/* The server's Markdown is for chat; here it is shown as plain text. */
function plainText(markdown) {
  return (markdown || "").replace(/^#+\s*/gm, "").replace(/\*\*/g, "").replace(/\p{Extended_Pictographic}\uFE0F?\s*/gu, "");
}

function showError(kind, message) {
  const body = $("conclusion-body");
  body.replaceChildren();
  $("conclusion").hidden = false;
  body.append(make("p", "error-title", "The check stopped, so there is no answer"), make("p", "verdict-headline", `${kind || "Error"}: ${message}`));
}

/* ---------- starting a run ---------- */

function resetPage() {
  run.spans.forEach((span) => span.node.remove());
  run = newRun();
  buildCaseForm();
  $("guardlog").replaceChildren();
  $("guardlog-empty").hidden = false;
  $("conclusion").hidden = true;
  $("conclusion-body").replaceChildren();
  $("details").hidden = true;
  $("status").hidden = false;
  $("subject").hidden = true;
  setStatus("Starting...");
  setNote("", false);
  $("subject-message").textContent = "";
  Object.values(ROW_NODES).forEach((nodes) => {
    nodes.row.classList.remove("never");
    nodes.note.hidden = true;
  });
  render();
}

function setNote(text, problem) {
  const note = $("sheet-note");
  note.textContent = text;
  if (text) $("subject").hidden = false;
  note.classList.toggle("problem", Boolean(problem));
}

let busy = false;
let health = null;

function setBusy(value) {
  busy = value;
  refreshButtons();
}

function refreshButtons() {
  const text = $("message").value.trim();
  const ollama = Boolean(health && health.ollama);
  $("run").disabled = busy || !text || !ollama;
  $("replay").disabled = busy || !(health && health.sample);
  const hint = $("run-hint");
  hint.classList.toggle("problem", Boolean(health) && !ollama);
  if (busy) hint.textContent = "A check is in progress.";
  else if (!health) hint.textContent = "Checking the server.";
  else if (!ollama) hint.textContent = health.sample ? "The local model (Ollama) is not running. Start it, or watch a recorded run." : "The local model (Ollama) is not running. Start it to check a message.";
  else if (!text) hint.textContent = "Paste a message to begin.";
  else hint.textContent = "Ready. The local model can take a minute or more.";
}

async function readStream(response) {
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let ended = false;
  for (;;) {
    const { value, done } = await reader.read();
    if (done) return ended;
    buffer += decoder.decode(value, { stream: true });
    const messages = buffer.split("\n\n");
    buffer = messages.pop();
    for (const message of messages) {
      if (!message.startsWith("data: ")) continue;
      const event = JSON.parse(message.slice(6));
      handleEvent(event);
      if (event.event === "done" || event.event === "error") ended = true;
    }
  }
}

async function startStream(request, note) {
  resetPage();
  setBusy(true);
  setNote(note);
  if (!matchMedia(DESKTOP).matches) $("status").scrollIntoView({ block: "start" }); // the button sits above the chart
  run.startScroll = window.scrollY;
  run.live = true;
  run.lastArrival = performance.now();
  tick();
  try {
    const response = await request();
    if (!response.ok) {
      const problem = await response.json().catch(() => ({}));
      failRun(`HTTP ${response.status}`, problem.error || "The server refused this run.");
      return;
    }
    const finished = await readStream(response);
    if (!finished) failRun("Connection", "The stream closed before the run finished.");
  } catch (err) {
    failRun("Connection", err.message);
    return;
  }
  setBusy(false);
  render();
}

function startRun() {
  const text = $("message").value;
  const architecture = document.querySelector('input[name="architecture"]:checked').value;
  startStream(
    () => fetch("/api/analyse", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text, architecture }) }),
    "Checking, secrets hidden:",
  );
}

function startReplay() {
  startStream(() => fetch("/api/replay"), "Recorded run, waits shortened, secrets hidden:");
}

/* ---------- page setup ---------- */

function buildArchitectureControl(names) {
  const holder = $("architectures");
  holder.replaceChildren();
  names.forEach((name, index) => {
    const label = make("label");
    const input = make("input");
    input.type = "radio";
    input.name = "architecture";
    input.value = name;
    input.checked = index === 0;
    input.addEventListener("change", () => showArchitectureHint(name));
    label.append(input, make("span", "", ARCHITECTURES[name] ? ARCHITECTURES[name].label : name));
    holder.append(label);
  });
  showArchitectureHint(names[0]);
}

function showArchitectureHint(name) {
  $("architecture-hint").textContent = ARCHITECTURES[name] ? ARCHITECTURES[name].hint : "";
}

async function checkHealth() {
  const line = $("health");
  try {
    health = await (await fetch("/api/health")).json();
    line.textContent = `Local model ${health.model.split("/").pop()}, ${health.ollama ? "ready" : "not running"}`;
    line.classList.toggle("down", !health.ollama);
    buildArchitectureControl(health.architectures.length ? health.architectures : Object.keys(ARCHITECTURES));
  } catch {
    health = null;
    line.textContent = "Server not reachable";
    line.classList.add("down");
  }
  refreshButtons();
}

function setup() {
  ROWS.forEach(addRow);
  buildCaseForm();
  buildArchitectureControl(Object.keys(ARCHITECTURES));
  $("message").addEventListener("input", refreshButtons);
  $("run").addEventListener("click", startRun);
  $("replay").addEventListener("click", startReplay);
  $("details-close").addEventListener("click", closeDetails);
  $("technical-toggle").addEventListener("click", toggleTechnical);
  window.addEventListener("resize", render); // note positions are in pixels
  render();
  checkHealth();
}

setup();
