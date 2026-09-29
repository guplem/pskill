// The pskill viewer. It only draws what the local server returns (pskill_runner/viewer_data.py).
// Every text from a run goes into the page through textContent, never as HTML.

const UNFINISHED = ["active", "waiting_for_human", "paused"];
const POLL_MS = 1000;
const PLAY_MS = 700;
const FOLD_LINE_LIMIT = 3;
const PANEL_WIDTH_KEY = "pskill.panelWidth";
const PANEL_MIN_WIDTH = 320;
const CANVAS_MIN_WIDTH = 240;
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
const STATUS_MEANING = {
  active: "The runner waits for the agent's answer.",
  waiting_for_human: "A decision waits for your answer.",
  paused: "The run stopped for now. It can resume.",
  succeeded: "The run finished and the skill reached its goal.",
  failed: "The run finished without the skill reaching its goal.",
  cancelled: "Someone stopped the run before its end.",
};
const NODE_STATE_TEXT = { done: "Done", now: "Now", waiting: "Waiting for you", failed: "Failed", unvisited: "Not visited" };
const NODE_STATE_MEANING = {
  done: "The run went through this step.",
  now: "The run is at this step at this point of the replay.",
  waiting: "This step waits for your answer.",
  failed: "This step failed.",
  unvisited: "The run has not reached this step at this point of the replay.",
};
const MODE_MEANING = {
  interactive: "Interactive mode: human decisions ask you.",
  autonomous: "Autonomous mode: the agent makes every decision, human decisions included.",
};
const START_HINT = "The run begins here.";
const CHILD_SKILL_HINT = "A child skill. The call block at the end of the dotted edge runs it, and gets its outputs back.";
const TASK_FRAME_HINT = "The tasks of the parallel block at the end of the dotted edge. Each node is one task that one subagent does.";
const TASK_STATE_TEXT = { done: "Done", rejected: "Answer rejected", open: "Open" };
const TASK_STATE_MEANING = {
  done: "The task has an accepted answer.",
  rejected: "The runner rejected every answer of this task so far.",
  open: "The task has no answer yet.",
};
const EDGE_STYLE_HINT = "Solid blue: the run took this edge. Dashed grey: the run did not take it.";

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
  selectedTask: null,
  openFolds: new Set(),
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
  if (STATUS_MEANING[status]) pill.title = STATUS_MEANING[status];
  return pill;
}

// A hover tooltip on a Mermaid group: an SVG <title> for the shapes, and an HTML title for the label.
function addHint(group, text) {
  const title = document.createElementNS("http://www.w3.org/2000/svg", "title");
  title.textContent = text;
  group.prepend(title);
  for (const label of group.querySelectorAll("foreignObject > div")) label.title = text;
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
  const handle = element("div", null, "panel-handle");
  handle.title = "Drag to make the panel wider or narrower";
  workspace.append(canvas, handle, panel);
  attachPanelResize(workspace, handle);

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
  slider.addEventListener("pointermove", hintStepUnderPointer);
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
  const harnessAndMode = element("span", `${info.harness} · ${info.mode}`, "note");
  harnessAndMode.title = `Harness: ${info.harness}, the agent tool that runs the skill.\n${MODE_MEANING[info.mode] || ""}`;
  const parts = [statusPill(info.status), harnessAndMode];
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
  const taskStates = {};
  for (const row of upToStep) {
    if (row.node) labels[row.node] = row.label;
    for (const task of row.tasks) {
      if (!task.node) continue;
      labels[task.node] = task.label;
      taskStates[task.node] = task.state;
    }
  }
  const atEnd = view.step === rows().length - 1;
  const current = view.detail.canvas && view.detail.canvas.current;
  const stepNode = upToStep.length ? upToStep[upToStep.length - 1].node : null;
  const stepNodeState = atEnd ? (current ? current.state : "done") : "now";
  return { visited, taken, labels, taskStates, stepNode, stepNodeState };
}

// A task node: blue when done, red after a rejected answer, orange while open at the step, else grey.
function taskNodeState(nodeInfo, state) {
  const taskState = state.taskStates[nodeInfo.id] || "open";
  if (taskState === "done") return "done";
  if (taskState === "rejected") return "failed";
  return nodeInfo.parent === state.stepNode && state.stepNodeState !== "done" ? "now" : "unvisited";
}

function nodeState(node, state) {
  const nodeInfo = view.detail.canvas?.nodes.find((item) => item.id === node);
  if (nodeInfo && nodeInfo.kind === "task") return taskNodeState(nodeInfo, state);
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
    const stateName = nodeState(node, state);
    group.dataset.node = node;
    group.classList.add(`is-${stateName}`);
    if (node === view.selectedNode) group.classList.add("is-selected");
    const nodeInfo = data.nodes.find((item) => item.id === node);
    if (nodeInfo && nodeInfo.kind === "task") {
      group.classList.add("is-task");
      group.addEventListener("click", () => view.dragEnded || selectNode(nodeInfo.parent, null, nodeInfo.task));
      const taskState = state.taskStates[node] || "open";
      addHint(group, `${nodeInfo.hint}\n\n${TASK_STATE_TEXT[taskState]}: ${TASK_STATE_MEANING[taskState]}\nClick to see this task.`);
      continue;
    }
    if (node !== data.start) group.addEventListener("click", () => view.dragEnded || selectNode(node));
    if (node === data.start) addHint(group, START_HINT);
    else if (nodeInfo) addHint(group, `${nodeInfo.hint}\n\n${NODE_STATE_TEXT[stateName]}: ${NODE_STATE_MEANING[stateName]}\nClick to see this step.`);
  }
  for (const edge of data.edges) {
    const taken = state.taken.has(edge.id) || (edge.kind === "tasks" && state.visited.has(edge.source));
    const path = svgNode.querySelector(`[id="${renderId}-${edge.id}"]`);
    if (path) path.classList.toggle("is-taken", taken);
    const hint = `${edge.hint}\n${taken ? "The run took this edge." : "The run has not taken this edge."}\n${EDGE_STYLE_HINT}`;
    const label = svgNode.querySelector(`g.label[data-id="${edge.id}"]`);
    if (label) addHint(label, hint);
    if (path) addHint(path, hint);
  }
  for (const cluster of svgNode.querySelectorAll("g.cluster")) {
    addHint(cluster, cluster.id.endsWith("_tasks") ? TASK_FRAME_HINT : CHILD_SKILL_HINT);
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

function savedPanelWidth() {
  try {
    return Number(localStorage.getItem(PANEL_WIDTH_KEY)) || null;
  } catch {
    return null; // the browser blocks site data
  }
}

function savePanelWidth(width) {
  try {
    localStorage.setItem(PANEL_WIDTH_KEY, String(width));
  } catch {
    // the browser blocks site data: the width lasts until the reload
  }
}

function setPanelWidth(workspace, width) {
  const widest = Math.max(PANEL_MIN_WIDTH, workspace.getBoundingClientRect().width - CANVAS_MIN_WIDTH);
  const clamped = Math.round(Math.min(Math.max(width, PANEL_MIN_WIDTH), widest));
  workspace.style.setProperty("--panel-width", `${clamped}px`);
  return clamped;
}

function attachPanelResize(workspace, handle) {
  const saved = savedPanelWidth();
  if (saved) {
    workspace.style.setProperty("--panel-width", `${saved}px`);
    requestAnimationFrame(() => setPanelWidth(workspace, saved)); // fit it to this window once the page has a size
  }
  handle.addEventListener("pointerdown", (event) => {
    event.preventDefault();
    handle.setPointerCapture(event.pointerId);
    handle.classList.add("dragging");
  });
  handle.addEventListener("pointermove", (event) => {
    if (!handle.hasPointerCapture(event.pointerId)) return;
    setPanelWidth(workspace, workspace.getBoundingClientRect().right - event.clientX);
  });
  handle.addEventListener("pointerup", (event) => {
    handle.releasePointerCapture(event.pointerId);
    handle.classList.remove("dragging");
    savePanelWidth(setPanelWidth(workspace, workspace.getBoundingClientRect().right - event.clientX));
  });
}

function selectNode(node, rowIndex = null, task = null) {
  view.selectedNode = node;
  view.selectedRow = rowIndex;
  view.selectedTask = task;
  for (const group of view.parts.layer.querySelectorAll("g.node")) {
    group.classList.toggle("is-selected", group.dataset.node === node);
  }
  drawPanel();
}

function selectTask(task) {
  view.selectedTask = task;
  drawPanel();
}

function drawPanel() {
  const panel = view.parts.panel;
  const state = stepState();
  const node = view.selectedNode || (view.selectedRow === null ? state.stepNode : null);
  if (!node) {
    // A step with no node on the canvas (no canvas, or a child without its skill copy): show the row itself.
    const row = rows()[view.selectedRow ?? view.step];
    if (row) {
      const title = element("div", null, "panel-title");
      title.append(element("h2", row.block), element("span", row.block_type, "pill state-idle"));
      panel.replaceChildren(title, ...rowSections(row));
      return;
    }
  }
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
  if (nodeInfo) parts.push(element("p", nodeInfo.hint, "note panel-hint"));
  if (visits.length > 1) parts.push(visitPicker(visits, chosen));
  if (!chosen) {
    parts.push(element("p", "The run has not reached this step at this point of the replay.", "note"));
    parts.push(section("Where it can go", exitsOf(node)));
  } else {
    parts.push(...rowSections(chosen.row));
  }
  const stateDetails = element("details");
  stateDetails.append(element("summary", "Run state now (inputs, steps, history)"), jsonTree(view.detail.state));
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
  for (const edge of view.detail.canvas.edges.filter((item) => item.source === node && item.kind !== "tasks")) {
    const target = view.detail.canvas.nodes.find((item) => item.id === edge.target);
    list.append(element("li", `→ ${target ? target.block : edge.target}: ${edge.hint}`));
  }
  return list;
}

function rowSections(row) {
  const facts = element("dl", null, "facts");
  const addFact = (name, value, hint) => {
    const term = element("dt", name);
    term.title = hint;
    facts.append(term, element("dd", value));
  };
  addFact("Arrived from", row.arrival, "The step before this one, and the edge condition that led here.");
  addFact("Started", formatTime(row.ts), "When the run entered this step.");
  addFact("Duration", row.duration_ms === null ? "not finished" : formatDuration(row.duration_ms), "From the start of this step to its accepted answer.");
  if (row.decided_by) addFact("Decided by", row.decided_by, "Who gave the accepted answer: the agent, a human, or the runner itself.");
  if (row.left_by) addFact("Went next to", `${row.left_by.to}${row.left_by.label ? ` (${row.left_by.label})` : ""}`, "The step after this one, and the edge condition that led there.");
  const parts = [facts];
  if (row.block_type === "script") return [...parts, ...scriptSections(row)];
  if (row.packet) parts.push(section(row.input_title, folded(markdown(row.packet), `${row.seq}:input`)));
  if (row.tasks.length) parts.push(tasksSection(row));
  // The answers of a parallel block's tasks show with their task; the rest shows here.
  const answers = row.tasks.length ? row.submissions.filter((submission) => submission.task === null) : row.submissions;
  if (answers.length) parts.push(section(`Answers · ${answers.length}`, ...answers.map((item, index) => answerCard(item, index, row.seq))));
  if (row.output !== null) parts.push(section(row.output_title, folded(jsonTree(row.output), `${row.seq}:output`)));
  return parts;
}

function scriptSections(row) {
  const parts = [];
  for (const [index, script] of row.script_runs.entries()) {
    const key = `${row.seq}:script${index}`;
    parts.push(section(row.input_title, element("pre", `$ ${script.argv.join(" ")}`, "command")));
    const result = [element("p", `Exit code ${script.exit_code ?? "-"} · ${formatDuration(script.duration_ms)}`, "note")];
    if (script.parsed !== null) {
      result.push(folded(jsonTree(script.parsed), `${key}:parsed`));
      const raw = element("details");
      raw.append(element("summary", "The raw stdout"), element("pre", script.stdout));
      result.push(raw);
    } else if (script.stdout) {
      result.push(folded(element("pre", script.stdout), `${key}:stdout`));
    }
    if (script.stderr) result.push(element("h4", "stderr"), folded(element("pre", script.stderr), `${key}:stderr`));
    if (script.problem) result.push(element("pre", `The runner said: ${script.problem}`, "errors"));
    parts.push(section(row.output_title, ...result));
  }
  return parts;
}

function tasksSection(row) {
  const counts = { done: 0, rejected: 0, open: 0 };
  for (const task of row.tasks) counts[task.state] += 1;
  const summary = Object.entries(counts)
    .filter(([, count]) => count)
    .map(([name, count]) => `${count} ${TASK_STATE_TEXT[name].toLowerCase()}`)
    .join(" · ");
  const chips = element("div", null, "visits");
  const selected = view.selectedTask ?? row.task;
  for (const task of row.tasks) {
    const chip = button(task.label, () => selectTask(task.task), `tool task-chip is-${task.state}`);
    chip.title = `${TASK_STATE_TEXT[task.state]}: ${TASK_STATE_MEANING[task.state]}`;
    chip.setAttribute("aria-pressed", String(task.task === selected));
    chips.append(chip);
  }
  const chosen = row.tasks.find((task) => task.task === selected);
  const detail = chosen ? taskDetail(chosen, row.seq) : element("p", "Click a task to see its prompt, its answers, and its output.", "note");
  return section(`Tasks · ${row.tasks.length}`, element("p", summary, "note"), chips, detail);
}

function taskDetail(task, seq) {
  const box = element("div", null, "task-detail");
  box.append(element("h4", `Task ${task.task} · ${TASK_STATE_TEXT[task.state]}`));
  if (task.packet) box.append(element("h4", "Input: the prompt that the subagent got"), folded(markdown(task.packet), `${seq}:task${task.task}:input`));
  if (task.submissions.length) {
    box.append(element("h4", `Answers · ${task.submissions.length}`), ...task.submissions.map((item, index) => answerCard(item, index, `${seq}:task${task.task}`)));
  }
  if (task.output !== null) {
    box.append(element("h4", `Output: the answer of task ${task.task}`), folded(jsonTree(task.output), `${seq}:task${task.task}:output`));
  }
  return box;
}

function answerCard(submission, index, keyPrefix) {
  const card = element("div", null, submission.accepted ? "answer" : "answer rejected");
  const head = element("div", null, "answer-head");
  const taskText = submission.task !== null && submission.task !== undefined ? ` · task ${submission.task}` : "";
  head.append(element("span", null, "dot"), document.createTextNode(`Answer ${index + 1}${taskText} · ${submission.accepted ? "accepted" : "rejected"}`));
  card.append(head);
  if (submission.raw) card.append(folded(element("pre", submission.raw), `${keyPrefix}:answer${index}`));
  if (submission.errors.length) {
    card.append(folded(element("pre", `The runner said:\n${submission.errors.join("\n")}`, "errors"), `${keyPrefix}:errors${index}`));
  }
  return card;
}

// --- the run screen: JSON trees, Markdown, and folded blocks ---------------------------------------

// Long content shows its first lines, with a button to show all of it. The open ones stay open on redraws.
function folded(content, key) {
  const box = element("div", null, "fold");
  box.style.setProperty("--fold-lines", String(FOLD_LINE_LIMIT));
  const body = element("div", null, "fold-body");
  body.append(content);
  const isOpen = view.openFolds.has(key);
  box.classList.toggle("is-open", isOpen);
  const toggle = button(isOpen ? "Show less" : "Show all", () => {
    const open = box.classList.toggle("is-open");
    if (open) view.openFolds.add(key);
    else view.openFolds.delete(key);
    toggle.textContent = open ? "Show less" : "Show all";
  }, "fold-toggle");
  box.append(body, toggle);
  requestAnimationFrame(() => box.classList.toggle("fits", !isOpen && body.scrollHeight <= body.clientHeight + 1));
  return box;
}

// A JSON value as a tree: objects and arrays fold, the first level is open.
function jsonTree(value, depth = 0) {
  if (value === null || typeof value !== "object") return jsonLeaf(value);
  const isList = Array.isArray(value);
  const entries = isList ? value.map((item, index) => [index, item]) : Object.entries(value);
  const count = `${entries.length} ${isList ? "item" : "key"}${entries.length === 1 ? "" : "s"}`;
  const tree = element("details", null, depth === 0 ? "json json-root" : "json");
  tree.open = depth === 0;
  tree.append(element("summary", isList ? `[ ${count} ]` : `{ ${count} }`, "json-summary"));
  const children = element("div", null, "json-children");
  for (const [key, item] of entries) {
    const line = element("div", null, "json-row");
    line.append(element("span", `${key}:`, "json-key"), jsonTree(item, depth + 1));
    children.append(line);
  }
  tree.append(children);
  return tree;
}

function jsonLeaf(value) {
  if (typeof value === "string") return element("span", value, "json-string");
  return element("span", String(value), value === null ? "json-null" : "json-literal");
}

// A small Markdown renderer: headings, fenced code, lists, paragraphs, inline code, and bold.
// It builds elements and text nodes only, so the run text never goes into the page as HTML.
function markdown(text) {
  const box = element("div", null, "markdown");
  const lines = text.split("\n");
  let paragraph = [];
  let list = null;
  const flushParagraph = () => {
    if (paragraph.length) box.append(inlineMarkdown(element("p"), paragraph.join("\n")));
    paragraph = [];
  };
  for (let index = 0; index < lines.length; index += 1) {
    const line = lines[index];
    const fence = line.match(/^\s*(```|~~~)/);
    const heading = line.match(/^(#{1,6})\s+(.*)$/);
    const item = line.match(/^\s*(?:[-*]|(\d+)\.)\s+(.*)$/);
    if (fence) {
      flushParagraph();
      list = null;
      const code = [];
      for (index += 1; index < lines.length && !lines[index].trim().startsWith(fence[1]); index += 1) code.push(lines[index]);
      box.append(element("pre", code.join("\n")));
    } else if (heading) {
      flushParagraph();
      list = null;
      box.append(inlineMarkdown(element(`h${Math.min(heading[1].length + 3, 6)}`), heading[2]));
    } else if (item) {
      flushParagraph();
      const tag = item[1] ? "OL" : "UL";
      if (!list || list.tagName !== tag) box.append((list = element(tag.toLowerCase())));
      list.append(inlineMarkdown(element("li"), item[2]));
    } else if (!line.trim()) {
      flushParagraph();
      list = null;
    } else if (list && /^\s+/.test(line)) {
      inlineMarkdown(list.lastChild, ` ${line.trim()}`); // a list item that goes on over several lines
    } else {
      list = null;
      paragraph.push(line);
    }
  }
  flushParagraph();
  return box;
}

function inlineMarkdown(parent, text) {
  for (const part of text.split(/(`[^`]+`|\*\*[^*]+\*\*)/)) {
    if (/^`[^`]+`$/.test(part)) parent.append(element("code", part.slice(1, -1)));
    else if (/^\*\*[^*]+\*\*$/.test(part)) parent.append(element("strong", part.slice(2, -2)));
    else if (part) parent.append(document.createTextNode(part));
  }
  return parent;
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

// The tooltip of the replay bar names the step under the pointer. The slider covers the marks.
function hintStepUnderPointer(event) {
  const { slider } = view.parts;
  const all = rows();
  if (!all.length) return;
  const box = slider.getBoundingClientRect();
  const ratio = Math.min(Math.max((event.clientX - box.left) / box.width, 0), 1);
  const index = Math.round(ratio * (all.length - 1));
  const row = all[index];
  let meaning = "Blue mark: a step of the run.";
  if (row.submissions.some((submission) => !submission.accepted)) meaning = "Red mark: the runner rejected an answer at this step.";
  else if (row.asks_human) meaning = "Purple mark: a person decides this step.";
  slider.title = `Step ${index + 1} of ${all.length} · ${row.block} · ${row.summary}\n${meaning}\nClick or drag to see the run at this step.`;
}

function setStep(step) {
  const last = Math.max(rows().length - 1, 0);
  view.step = Math.min(Math.max(step, 0), last);
  view.stepAtEnd = view.step === last;
  view.selectedNode = null;
  view.selectedRow = null;
  view.selectedTask = null;
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
    view.openFolds.clear();
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
