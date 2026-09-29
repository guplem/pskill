// The pskill viewer. It only draws what the local server returns (pskill_runner/viewer_data.py).
// Every text from a run goes into the page through textContent, never as HTML.

const UNFINISHED = ["active", "waiting_for_human", "paused"];
const POLL_MS = 1000;
const PLAY_MS = 700;
const EXCERPT_LINES = 14;
const READABLE_SCALE = 0.9;
const STATUS_TEXT = {
  active: "running",
  waiting_for_human: "waiting for you",
  paused: "paused",
  succeeded: "succeeded",
  failed: "failed",
  cancelled: "cancelled",
};
const STATUS_STATE = {
  active: "now",
  waiting_for_human: "waiting",
  paused: "now",
  succeeded: "done",
  failed: "failed",
  cancelled: "idle",
};
const NODE_STATE_TEXT = { done: "Done", now: "Now", waiting: "Waiting for you", failed: "Failed", unvisited: "Not visited" };

const app = document.getElementById("app");
const view = {
  runId: null,
  detail: null,
  detailText: null,
  runs: [],
  step: 0,
  stepAtEnd: true,
  followLive: true,
  selectedNode: null,
  selectedRow: null,
  transform: { x: 0, y: 0, scale: 1 },
  appliedScale: 1,
  fitted: false,
  renderCount: 0,
  rendering: false,
  renderAgain: false,
  runsFilter: "unfinished",
  pollTimer: null,
  dragEnded: false,
  playTimer: null,
  parts: null,
};

// --- small helpers ----------------------------------------------------------------------------

function element(tag, text, className) {
  const node = document.createElement(tag);
  if (text !== undefined && text !== null) node.textContent = String(text);
  if (className) node.className = className;
  return node;
}

function button(text, onClick, className = "tool") {
  const node = element("button", text, className);
  node.type = "button";
  node.addEventListener("click", onClick);
  return node;
}

function formatDuration(milliseconds) {
  if (milliseconds === null || milliseconds === undefined) return "-";
  if (milliseconds < 1000) return `${milliseconds} ms`;
  const seconds = Math.round(milliseconds / 1000);
  return seconds < 60 ? `${seconds} s` : `${Math.floor(seconds / 60)} min ${String(seconds % 60).padStart(2, "0")} s`;
}

function formatTime(timestamp) {
  return new Date(timestamp).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

function statusPill(status) {
  const pill = element("span", null, `pill state-${STATUS_STATE[status] || "idle"}`);
  pill.append(element("span", null, "dot"), document.createTextNode(STATUS_TEXT[status] || status));
  return pill;
}

async function fetchJson(path) {
  const response = await fetch(path, { cache: "no-store" });
  if (!response.ok) throw new Error((await response.json()).error || response.statusText);
  return response.json();
}

function topbar() {
  const bar = element("header", null, "topbar");
  const brand = element("a", "pskill", "brand");
  brand.href = "#/";
  bar.append(brand);
  return bar;
}

// --- the runs page ----------------------------------------------------------------------------

const RUN_FILTERS = {
  unfinished: { label: "Unfinished", keep: (run) => UNFINISHED.includes(run.status) },
  all: { label: "All", keep: () => true },
  failed: { label: "Failed", keep: (run) => run.status === "failed" },
};

async function showRuns() {
  const overview = await fetchJson("/api/runs");
  const text = JSON.stringify(overview) + view.runsFilter;
  if (text !== view.detailText) {
    view.detailText = text;
    drawRuns(overview);
  }
  if (overview.runs.some((run) => UNFINISHED.includes(run.status))) view.pollTimer = setTimeout(render, POLL_MS * 2);
}

function drawRuns(overview) {
  const page = element("main", null, "runs-page");
  const filters = element("div", null, "filters");
  for (const [key, filter] of Object.entries(RUN_FILTERS)) {
    const count = overview.runs.filter(filter.keep).length;
    const chip = button(`${filter.label} · ${count}`, () => {
      view.runsFilter = key;
      view.detailText = null;
      render();
    });
    chip.setAttribute("aria-pressed", String(view.runsFilter === key));
    filters.append(chip);
  }
  const summaries = element("div", null, "summaries");
  for (const summary of overview.summaries) {
    const card = element("div", null, "summary");
    const rate = summary.success_rate === null ? "no finished run" : `${Math.round(summary.success_rate * 100)} % succeeded`;
    card.append(
      element("strong", summary.skill_id),
      element("span", `${summary.runs} runs · ${rate} · median ${formatDuration(summary.median_duration_ms)}`),
    );
    summaries.append(card);
  }
  const cards = element("div", null, "run-cards");
  const runs = overview.runs.filter(RUN_FILTERS[view.runsFilter].keep);
  for (const run of runs) {
    const card = element("a", null, "run-card");
    card.href = `#/run/${run.run_id}`;
    const head = element("div", null, "run-card-head");
    head.append(element("span", run.skill_id), statusPill(run.status));
    card.append(
      head,
      element("span", `at ${run.current_block || "-"} · ${formatDuration(run.duration_ms)}`, "run-card-meta"),
      element("span", `${formatTime(run.created_at)} · ${run.harness} · ${run.mode} · ${run.run_id}`, "run-card-meta mono"),
    );
    cards.append(card);
  }
  page.append(element("h1", "Runs"), filters);
  if (overview.summaries.length) page.append(summaries);
  page.append(runs.length ? cards : element("p", "No runs here yet.", "note"));
  app.className = "";
  app.replaceChildren(topbar(), page);
}

// --- the run screen: layout -------------------------------------------------------------------

function buildRunScreen() {
  const bar = topbar();
  const picker = element("select", null, "run-picker");
  picker.setAttribute("aria-label", "Run");
  picker.addEventListener("change", () => {
    location.hash = `#/run/${picker.value}`;
  });
  const status = element("span", null, "run-status");
  const follow = button("Follow live", () => {
    view.followLive = !view.followLive;
    follow.setAttribute("aria-pressed", String(view.followLive));
    if (view.followLive) centerOnStep();
  });
  follow.setAttribute("aria-pressed", String(view.followLive));
  const zoomLabel = element("span", "100 %", "note");
  bar.append(
    picker,
    status,
    element("span", null, "spacer"),
    follow,
    button("Fit", fitCanvas),
    button("−", () => zoomBy(1 / 1.2)),
    zoomLabel,
    button("+", () => zoomBy(1.2)),
  );

  const canvas = element("div", null, "canvas");
  const layer = element("div", null, "layer");
  const note = element("p", null, "canvas-note");
  canvas.append(layer, note);
  attachPanAndZoom(canvas);
  const panel = element("aside", null, "panel");
  panel.setAttribute("aria-label", "The selected step");
  const workspace = element("div", null, "workspace");
  workspace.append(canvas, panel);

  const replay = element("footer", null, "replay");
  const play = button("▶", togglePlay, "play");
  play.setAttribute("aria-label", "Play the run from here");
  const track = element("div", null, "replay-track");
  const progress = element("div", null, "replay-progress");
  const marks = element("div");
  const slider = element("input");
  slider.type = "range";
  slider.min = "0";
  slider.setAttribute("aria-label", "Replay step");
  slider.addEventListener("input", () => setStep(Number(slider.value)));
  track.append(element("div", null, "replay-line"), progress, marks, slider);
  const labels = element("div", null, "replay-labels");
  const body = element("div", null, "replay-body");
  body.append(track, labels);
  replay.append(play, body);

  const screen = element("div", null, "run-screen");
  screen.append(bar, workspace, replay);
  app.className = "";
  app.replaceChildren(screen);
  view.parts = { picker, status, follow, zoomLabel, canvas, layer, note, panel, progress, marks, slider, labels, play };
}

function drawTopbar() {
  const { picker, status } = view.parts;
  const info = view.detail.info;
  const options = view.runs.length ? view.runs : [{ run_id: info.run_id, skill_id: info.skill_id, status: info.status }];
  picker.replaceChildren(
    ...options.map((run) => {
      const option = element("option", `${run.skill_id} · ${STATUS_TEXT[run.status] || run.status} · ${run.run_id}`);
      option.value = run.run_id;
      option.selected = run.run_id === info.run_id;
      return option;
    }),
  );
  const parts = [statusPill(info.status), element("span", `${info.harness} · ${info.mode}`, "note")];
  if (info.pause_reason) parts.push(element("span", `paused: ${info.pause_reason}`, "note"));
  if (view.detail.skill_changed) parts.push(element("span", "The skill changed after this run started.", "note"));
  status.replaceChildren(...parts);
}

// --- the run screen: which state each node has at the replay step ------------------------------

function rows() {
  return view.detail.timeline;
}

function stepState() {
  const upToStep = rows().slice(0, view.step + 1);
  const visited = new Set(upToStep.map((row) => row.node).filter(Boolean));
  const taken = new Set(upToStep.map((row) => row.edge).filter(Boolean));
  const labels = {};
  for (const row of upToStep) if (row.node) labels[row.node] = row.label;
  const atEnd = view.step === rows().length - 1;
  const current = view.detail.canvas && view.detail.canvas.current;
  const stepNode = upToStep.length ? upToStep[upToStep.length - 1].node : null;
  const stepNodeState = atEnd ? (current ? current.state : "done") : "now";
  return { visited, taken, labels, stepNode, stepNodeState };
}

function nodeState(node, state) {
  if (node === state.stepNode) return state.stepNodeState;
  return state.visited.has(node) || node === view.detail.canvas?.start ? "done" : "unvisited";
}

// --- the run screen: the canvas ---------------------------------------------------------------

async function drawCanvas() {
  if (view.rendering) {
    view.renderAgain = true;
    return;
  }
  view.rendering = true;
  try {
    if (!window.mermaid) {
      drawStepList();
    } else if (view.detail.canvas) {
      await drawGraph();
    } else {
      drawStepList();
    }
  } finally {
    view.rendering = false;
  }
  if (view.renderAgain) {
    view.renderAgain = false;
    await drawCanvas();
  }
}

async function drawGraph() {
  const { canvas: data } = view.detail;
  const state = stepState();
  let source = data.template;
  for (const node of data.nodes) source = source.replace(node.token, () => state.labels[node.id] || data.labels[node.id]);
  await document.fonts.ready; // Mermaid measures the labels, so the fonts must be there first
  const renderId = `canvas-${++view.renderCount}`;
  window.mermaid.initialize({
    startOnLoad: false,
    securityLevel: "strict",
    theme: "base",
    themeVariables: { fontFamily: "Manrope, system-ui, sans-serif", fontSize: "13px" },
    flowchart: { htmlLabels: true, curve: "basis", nodeSpacing: 34, rankSpacing: 46, padding: 14 },
  });
  try {
    const { svg } = await window.mermaid.render(renderId, source);
    view.parts.layer.innerHTML = svg; // Mermaid's own output, rendered in strict security mode
  } catch (error) {
    view.parts.layer.replaceChildren(element("pre", `The graph could not be drawn: ${error}\n\n${source}`, "errors"));
    return;
  }
  const svgNode = view.parts.layer.querySelector("svg");
  const viewBox = svgNode.viewBox.baseVal;
  svgNode.style.maxWidth = "none";
  svgNode.style.width = `${viewBox.width}px`;
  svgNode.style.height = `${viewBox.height}px`;
  for (const group of svgNode.querySelectorAll("g.node")) {
    const match = group.id.match(/-flowchart-(.+)-\d+$/);
    if (!match) continue;
    const node = match[1];
    group.dataset.node = node;
    group.classList.add(`is-${nodeState(node, state)}`);
    if (node === view.selectedNode) group.classList.add("is-selected");
    if (node !== data.start) group.addEventListener("click", () => view.dragEnded || selectNode(node));
  }
  for (const edge of data.edges) {
    const path = svgNode.querySelector(`[id="${renderId}-${edge.id}"]`);
    if (path) path.classList.toggle("is-taken", state.taken.has(edge.id));
  }
  view.parts.note.textContent = "Drag to move · wheel to zoom · click a step to see it";
  if (!view.fitted) {
    // Open at a readable zoom: fit a small graph, and center a large one on the current step.
    view.fitted = true;
    fitCanvas();
    if (view.transform.scale < READABLE_SCALE) centerOnStep(READABLE_SCALE);
  } else if (view.followLive) {
    centerOnStep();
  } else {
    applyTransform();
  }
}

function drawStepList() {
  const state = stepState();
  const list = element("div", null, "step-list");
  list.append(element("p", "Graph unavailable offline (Mermaid did not load). The steps so far:", "note"));
  rows()
    .slice(0, view.step + 1)
    .forEach((row, index) => {
      const card = button(null, () => selectNode(row.node, index), "step-card");
      const stateName = index === view.step ? state.stepNodeState : "done";
      card.classList.add(`is-${stateName}`);
      card.append(element("strong", row.block), element("small", row.summary));
      list.append(card);
    });
  view.parts.layer.replaceChildren();
  view.parts.canvas.querySelector(".step-list")?.remove();
  view.parts.canvas.append(list);
  view.parts.note.textContent = "";
}

function applyTransform() {
  const { x, y, scale } = view.transform;
  view.appliedScale = scale;
  view.parts.layer.style.transform = `translate(${x}px, ${y}px) scale(${scale})`;
  view.parts.zoomLabel.textContent = `${Math.round(scale * 100)} %`;
}

function graphSize() {
  const svgNode = view.parts.layer.querySelector("svg");
  if (!svgNode) return null;
  return { width: svgNode.viewBox.baseVal.width, height: svgNode.viewBox.baseVal.height };
}

function fitCanvas() {
  const size = graphSize();
  if (!size) return;
  const box = view.parts.canvas.getBoundingClientRect();
  const scale = Math.min(box.width / size.width, box.height / size.height, 1.3) * 0.92;
  view.transform = {
    scale,
    x: (box.width - size.width * scale) / 2,
    y: Math.max(16, (box.height - size.height * scale) / 2),
  };
  applyTransform();
}

function zoomBy(factor, centerX, centerY) {
  const box = view.parts.canvas.getBoundingClientRect();
  const pointX = centerX ?? box.width / 2;
  const pointY = centerY ?? box.height / 2;
  const { x, y, scale } = view.transform;
  const nextScale = Math.min(Math.max(scale * factor, 0.15), 3);
  view.transform = {
    scale: nextScale,
    x: pointX - ((pointX - x) * nextScale) / scale,
    y: pointY - ((pointY - y) * nextScale) / scale,
  };
  applyTransform();
}

function centerOnStep(targetScale = view.transform.scale) {
  const node = stepState().stepNode;
  const group = node && view.parts.layer.querySelector(`g.node[data-node="${node}"]`);
  if (!group) return applyTransform();
  const box = view.parts.canvas.getBoundingClientRect();
  const groupBox = group.getBoundingClientRect();
  const layerBox = view.parts.layer.getBoundingClientRect();
  const applied = view.appliedScale || 1;
  const centerX = (groupBox.left - layerBox.left + groupBox.width / 2) / applied;
  const centerY = (groupBox.top - layerBox.top + groupBox.height / 2) / applied;
  const scale = targetScale;
  view.transform = { scale, x: box.width / 2 - centerX * scale, y: box.height / 2 - centerY * scale };
  applyTransform();
}

function attachPanAndZoom(canvas) {
  let drag = null;
  canvas.addEventListener("pointerdown", (event) => {
    if (event.button !== 0 || event.target.closest(".step-list")) return;
    drag = { startX: event.clientX, startY: event.clientY, x: view.transform.x, y: view.transform.y, moved: false };
  });
  window.addEventListener("pointermove", (event) => {
    if (!drag) return;
    const dx = event.clientX - drag.startX;
    const dy = event.clientY - drag.startY;
    if (!drag.moved && Math.hypot(dx, dy) < 4) return;
    drag.moved = true;
    canvas.classList.add("dragging");
    view.transform = { ...view.transform, x: drag.x + dx, y: drag.y + dy };
    applyTransform();
  });
  window.addEventListener("pointerup", () => {
    if (drag && drag.moved) {
      // A drag is not a click on the node under the pointer.
      view.dragEnded = true;
      setTimeout(() => (view.dragEnded = false), 0);
      if (view.followLive) view.parts.follow.click();
    }
    drag = null;
    canvas.classList.remove("dragging");
  });
  canvas.addEventListener(
    "wheel",
    (event) => {
      event.preventDefault();
      const box = canvas.getBoundingClientRect();
      zoomBy(event.deltaY < 0 ? 1.12 : 1 / 1.12, event.clientX - box.left, event.clientY - box.top);
    },
    { passive: false },
  );
}

// --- the run screen: the side panel -------------------------------------------------------------

function selectNode(node, rowIndex = null) {
  view.selectedNode = node;
  view.selectedRow = rowIndex;
  for (const group of view.parts.layer.querySelectorAll("g.node")) {
    group.classList.toggle("is-selected", group.dataset.node === node);
  }
  drawPanel();
}

function drawPanel() {
  const panel = view.parts.panel;
  const state = stepState();
  const node = view.selectedNode || state.stepNode;
  const nodeInfo = view.detail.canvas && node ? view.detail.canvas.nodes.find((item) => item.id === node) : null;
  const visits = rows()
    .map((row, index) => ({ row, index }))
    .filter((item) => item.row.node === node && item.index <= view.step);
  if (!node || (!nodeInfo && !visits.length)) {
    panel.replaceChildren(element("p", "Click a step on the canvas to see it here.", "note"));
    return;
  }
  const chosen = visits.find((item) => item.index === view.selectedRow) || visits[visits.length - 1];
  const nodeStateName = nodeState(node, state);
  const head = element("div", null, "panel-head");
  const title = element("div", null, "panel-title");
  const stateClass = nodeStateName === "unvisited" ? "idle" : nodeStateName;
  title.append(element("h2", nodeInfo ? nodeInfo.block : chosen.row.block), element("span", NODE_STATE_TEXT[nodeStateName], `pill state-${stateClass}`));
  const type = nodeInfo ? nodeInfo.type : chosen.row.block_type;
  const skillText = nodeInfo && nodeInfo.frame > 0 ? ` · in ${nodeInfo.skill_id}` : "";
  head.append(title, element("span", `${type}${skillText}`, "note"));
  const parts = [head];
  if (visits.length > 1) parts.push(visitPicker(visits, chosen));
  if (!chosen) {
    parts.push(element("p", "The run has not reached this step at this point of the replay.", "note"));
    parts.push(section("Where it can go", exitsOf(node)));
  } else {
    parts.push(...rowSections(chosen.row));
  }
  const stateDetails = element("details");
  stateDetails.append(element("summary", "Run state now (inputs, steps, history)"), element("pre", JSON.stringify(view.detail.state, null, 2)));
  parts.push(stateDetails);
  panel.replaceChildren(...parts);
}

function section(title, ...content) {
  const node = element("section");
  node.append(element("h3", title), ...content);
  return node;
}

function visitPicker(visits, chosen) {
  const picker = element("div", null, "visits");
  visits.forEach((item, position) => {
    const label = item.row.task !== null && item.row.task !== undefined ? `Task ${item.row.task}` : `Visit ${position + 1}`;
    const chip = button(label, () => selectNode(item.row.node, item.index));
    chip.setAttribute("aria-pressed", String(item === chosen));
    picker.append(chip);
  });
  return section("Visits", picker);
}

function exitsOf(node) {
  const list = element("ul");
  for (const edge of view.detail.canvas.edges.filter((item) => item.source === node)) {
    const target = view.detail.canvas.nodes.find((item) => item.id === edge.target);
    list.append(element("li", `→ ${target ? target.block : edge.target}${edge.label ? ` (${edge.label})` : ""}`));
  }
  return list;
}

function rowSections(row) {
  const facts = element("dl", null, "facts");
  const addFact = (name, value) => facts.append(element("dt", name), element("dd", value));
  addFact("Arrived from", row.arrival);
  addFact("Started", formatTime(row.ts));
  addFact("Duration", row.duration_ms === null ? "not finished" : formatDuration(row.duration_ms));
  if (row.decided_by) addFact("Decided by", row.decided_by);
  if (row.left_by) addFact("Went next to", `${row.left_by.to}${row.left_by.label ? ` (${row.left_by.label})` : ""}`);
  const parts = [facts];
  if (row.packet) {
    const lines = row.packet.split("\n");
    const excerpt = element("pre", lines.slice(0, EXCERPT_LINES).join("\n") + (lines.length > EXCERPT_LINES ? "\n…" : ""));
    const whole = element("details");
    whole.append(element("summary", "The whole packet"), element("pre", row.packet));
    parts.push(section("What the agent got", excerpt, whole));
  }
  if (row.submissions.length) {
    parts.push(section(`Answers · ${row.submissions.length}`, ...row.submissions.map(answerCard)));
  }
  if (row.output !== null) parts.push(section("Output", element("pre", JSON.stringify(row.output, null, 2))));
  if (row.script_runs.length) parts.push(section("Script runs", ...row.script_runs.map(scriptCard)));
  return parts;
}

function answerCard(submission, index) {
  const card = element("div", null, submission.accepted ? "answer" : "answer rejected");
  const head = element("div", null, "answer-head");
  head.append(element("span", null, "dot"), document.createTextNode(`Answer ${index + 1} · ${submission.accepted ? "accepted" : "rejected"}`));
  card.append(head);
  if (submission.raw) card.append(element("pre", submission.raw));
  if (submission.errors.length) card.append(element("pre", `The runner said:\n${submission.errors.join("\n")}`, "errors"));
  return card;
}

function scriptCard(script) {
  const lines = [`$ ${script.argv.join(" ")}`, `exit code ${script.exit_code ?? "-"} · ${formatDuration(script.duration_ms)}`];
  if (script.stdout) lines.push("", script.stdout);
  if (script.stderr) lines.push("", "[stderr]", script.stderr);
  if (script.problem) lines.push("", `[problem] ${script.problem}`);
  return element("pre", lines.join("\n"));
}

// --- the run screen: the replay bar ---------------------------------------------------------------

function drawReplay() {
  const { progress, marks, slider, labels, play } = view.parts;
  const all = rows();
  const last = Math.max(all.length - 1, 0);
  slider.max = String(last);
  slider.value = String(view.step);
  const percent = (index) => (last === 0 ? 0 : (index / last) * 100);
  progress.style.width = `${percent(view.step)}%`;
  const markNodes = all.map((row, index) => {
    const mark = element("span", null, "mark");
    if (row.submissions.some((submission) => !submission.accepted)) mark.classList.add("rejected");
    else if (row.asks_human) mark.classList.add("human");
    if (index > view.step) mark.classList.add("future");
    if (index === view.step) mark.classList.add("at");
    mark.style.left = `${percent(index)}%`;
    return mark;
  });
  marks.replaceChildren(...markNodes);
  const current = all[view.step];
  const where = current ? `Step ${view.step + 1} of ${all.length} · ${current.block}` : "No steps yet";
  const end = view.step === last ? (UNFINISHED.includes(view.detail.info.status) ? "live" : "end") : "drag to the end to follow live";
  labels.replaceChildren(
    element("span", all.length ? formatTime(all[0].ts) : ""),
    element("span", where),
    element("span", end),
  );
  play.textContent = view.playTimer ? "❚❚" : "▶";
  play.setAttribute("aria-label", view.playTimer ? "Pause the replay" : "Play the run from here");
}

function setStep(step) {
  const last = Math.max(rows().length - 1, 0);
  view.step = Math.min(Math.max(step, 0), last);
  view.stepAtEnd = view.step === last;
  view.selectedNode = null;
  view.selectedRow = null;
  drawReplay();
  drawPanel();
  drawCanvas();
}

function togglePlay() {
  if (view.playTimer) {
    clearInterval(view.playTimer);
    view.playTimer = null;
    drawReplay();
    return;
  }
  if (view.step >= rows().length - 1) setStep(0);
  view.playTimer = setInterval(() => {
    if (view.step >= rows().length - 1) {
      clearInterval(view.playTimer);
      view.playTimer = null;
      drawReplay();
      return;
    }
    setStep(view.step + 1);
  }, PLAY_MS);
  drawReplay();
}

// --- the run screen: loading and live updates -----------------------------------------------------

async function showRun(runId) {
  if (view.runId !== runId || !view.parts) {
    view.runId = runId;
    view.detail = null;
    view.detailText = null;
    view.fitted = false;
    view.stepAtEnd = true;
    view.selectedNode = null;
    buildRunScreen();
  }
  const [detail, overview] = await Promise.all([
    fetchJson(`/api/runs/${encodeURIComponent(runId)}`),
    fetchJson("/api/runs").catch(() => ({ runs: [] })),
  ]);
  const text = JSON.stringify(detail);
  if (text !== view.detailText) {
    view.detailText = text;
    view.detail = detail;
    view.runs = overview.runs;
    if (view.stepAtEnd) view.step = Math.max(detail.timeline.length - 1, 0);
    drawTopbar();
    drawReplay();
    drawPanel();
    await drawCanvas();
  }
  if (UNFINISHED.includes(detail.info.status)) view.pollTimer = setTimeout(render, POLL_MS);
}

// --- routing ----------------------------------------------------------------------------------

async function render() {
  clearTimeout(view.pollTimer);
  const match = location.hash.match(/^#\/run\/(.+)$/);
  try {
    if (match) {
      await showRun(decodeURIComponent(match[1]));
    } else {
      view.runId = null;
      view.parts = null;
      await showRuns();
    }
  } catch (error) {
    app.replaceChildren(topbar(), element("p", `The viewer could not load the data: ${error.message}`, "errors loading"));
  }
}

window.addEventListener("hashchange", () => {
  view.detailText = null;
  if (view.playTimer) clearInterval(view.playTimer);
  view.playTimer = null;
  render();
});
window.addEventListener("keydown", (event) => {
  if (!view.parts || ["INPUT", "SELECT", "TEXTAREA"].includes(event.target.tagName)) return;
  if (event.key === "ArrowRight") setStep(view.step + 1);
  else if (event.key === "ArrowLeft") setStep(view.step - 1);
});
render();
