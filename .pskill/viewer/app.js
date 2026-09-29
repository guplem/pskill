// The pskill viewer. It only draws what the local server returns (pskill_runner/viewer_data.py and skill_view.py).
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
// One icon per block type, drawn for pskill: line paths on a 16 by 16 grid, in the color of the text.
const BLOCK_ICONS = {
  task: ["M3.5 2.5h9a1 1 0 0 1 1 1v9a1 1 0 0 1-1 1h-9a1 1 0 0 1-1-1v-9a1 1 0 0 1 1-1z", "M5.5 8.2l1.8 1.8 3.4-3.8"], // a checked box
  decision: ["M8 1.8l6.2 6.2L8 14.2 1.8 8z", "M8 8h.01"], // a diamond with a dot
  parallel: ["M2 8h4", "M6 8c2 0 2-4.5 4.5-4.5H14", "M6 8h8", "M6 8c2 0 2 4.5 4.5 4.5H14"], // one line that splits in three
  script: ["M2.5 3h11a1 1 0 0 1 1 1v8a1 1 0 0 1-1 1h-11a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1z", "M4.5 6.5l2 1.5-2 1.5", "M8.5 10h3"], // a terminal
  call: ["M9 2.5h3.5a1 1 0 0 1 1 1v9a1 1 0 0 1-1 1H9", "M2 8h8", "M7.5 5.5L10 8l-2.5 2.5"], // an arrow into a box
  end: ["M4 14V2.5", "M4 3h8l-2 2.75L12 8.5H4"], // a flag
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
const SKILL_START_HINT = "A run of this skill begins here.";
const INVOCATION_MEANING = {
  auto: "The agent can start it on its own, when the request matches the description.",
  manual: "Only the user starts it.",
  internal: "Only a call block of another skill starts it.",
};

const app = document.getElementById("app");
const view = {
  screen: null,
  skillId: null,
  editing: false,
  skills: [],
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

function blockIcon(type) {
  const namespace = "http://www.w3.org/2000/svg";
  const icon = document.createElementNS(namespace, "svg");
  icon.setAttribute("viewBox", "0 0 16 16");
  icon.setAttribute("class", "block-icon-svg");
  icon.setAttribute("aria-hidden", "true");
  for (const shape of BLOCK_ICONS[type] || []) {
    const path = document.createElementNS(namespace, "path");
    path.setAttribute("d", shape);
    icon.append(path);
  }
  return icon;
}

// The block type as the panel and the offline cards show it: its icon, then its name.
function blockType(type, text = type) {
  const line = element("span", null, "block-type");
  line.append(blockIcon(type), document.createTextNode(text));
  return line;
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
  const nav = element("nav", null, "nav");
  for (const [text, href, screens] of [
    ["Runs", "#/", ["runs", "run"]],
    ["Skills", "#/skills", ["skills", "skill"]],
  ]) {
    const link = element("a", text, "nav-link");
    link.href = href;
    if (screens.includes(view.screen)) link.setAttribute("aria-current", "page");
    nav.append(link);
  }
  bar.append(brand, nav);
  return bar;
}

function isSkillScreen() {
  return view.screen === "skill";
}

// --- the runs page ----------------------------------------------------------------------------

const RUN_FILTERS = {
  unfinished: { label: "Unfinished", keep: (run) => UNFINISHED.includes(run.status) },
  all: { label: "All", keep: () => true },
  failed: { label: "Failed", keep: (run) => run.status === "failed" },
};

async function showRuns() {
  const overview = await fetchJson("/api/runs");
  if (view.screen !== "runs") return; // the user moved on while it loaded
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

// --- the skills page ----------------------------------------------------------------------------

async function showSkills() {
  const overview = await fetchJson("/api/skills");
  if (view.screen !== "skills") return; // the user moved on while it loaded
  const text = JSON.stringify(overview);
  if (text === view.detailText) return;
  view.detailText = text;
  const page = element("main", null, "runs-page");
  const cards = element("div", null, "run-cards");
  for (const skill of overview.skills) {
    const card = element("a", null, skill.error ? "run-card skill-card has-error" : "run-card skill-card");
    card.href = `#/skill/${encodeURIComponent(skill.skill_id)}`;
    const head = element("div", null, "run-card-head");
    head.append(element("span", skill.skill_id));
    if (skill.error) head.append(element("span", "does not load", "pill state-failed"));
    else if (skill.invocation !== "auto") head.append(element("span", skill.invocation, "pill state-idle"));
    card.append(head);
    if (skill.error) {
      card.append(element("span", skill.error, "run-card-meta errors-text"));
    } else {
      card.append(
        element("span", skill.description, "skill-card-description"),
        element("span", `${skill.blocks} blocks · ${skill.runs} run${skill.runs === 1 ? "" : "s"}`, "run-card-meta"),
      );
    }
    cards.append(card);
  }
  page.append(
    element("h1", "Skills"),
    element("p", "Every skill in .pskill/skills/. Open one to see its steps and how they connect.", "note"),
    overview.skills.length ? cards : element("p", "This project has no skills yet.", "note"),
  );
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
  bar.append(picker, status, element("span", null, "spacer"), follow, ...zoomTools(zoomLabel));
  const { workspace, canvas, layer, note, panel } = buildWorkspace("The selected step");

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
  view.parts = { picker, status, follow, zoomLabel, canvas, layer, note, panel, progress, marks, slider, labels, play, workspace };
}

function zoomTools(zoomLabel) {
  return [button("Fit", fitCanvas), button("−", () => zoomBy(1 / 1.2)), zoomLabel, button("+", () => zoomBy(1.2))];
}

// The canvas, the panel, and the handle between them: the same on the run screen and the skill screen.
function buildWorkspace(panelLabel) {
  const canvas = element("div", null, "canvas");
  const layer = element("div", null, "layer");
  const note = element("p", null, "canvas-note");
  canvas.append(layer, note);
  attachPanAndZoom(canvas);
  const panel = element("aside", null, "panel");
  panel.setAttribute("aria-label", panelLabel);
  const workspace = element("div", null, "workspace");
  const handle = element("div", null, "panel-handle");
  handle.title = "Drag to make the panel wider or narrower";
  workspace.append(canvas, handle, panel);
  attachPanelResize(workspace, handle);
  return { workspace, canvas, layer, note, panel };
}

// --- the skill screen: layout -------------------------------------------------------------------

function buildSkillScreen() {
  const bar = topbar();
  const picker = element("select", null, "run-picker");
  picker.setAttribute("aria-label", "Skill");
  picker.addEventListener("change", () => {
    location.hash = `#/skill/${encodeURIComponent(picker.value)}`;
  });
  const status = element("span", null, "run-status");
  const zoomLabel = element("span", "100 %", "note");
  const addBar = buildAddBar();
  const editToggle = button("Edit", () => {
    view.editing = !view.editing;
    editToggle.setAttribute("aria-pressed", String(view.editing));
    addBar.hidden = !view.editing;
    drawPanel();
  });
  editToggle.setAttribute("aria-pressed", String(view.editing));
  editToggle.title = "Change the blocks and edges of this skill. Each save writes skill.yaml and keeps its comments.";
  addBar.hidden = !view.editing;
  bar.append(picker, status, element("span", null, "spacer"), addBar, editToggle, ...zoomTools(zoomLabel));
  const { workspace, canvas, layer, note, panel } = buildWorkspace("The selected block");
  layer.classList.add("is-skill");
  const screen = element("div", null, "run-screen skill-screen");
  screen.append(bar, workspace);
  app.className = "";
  app.replaceChildren(screen);
  view.parts = { picker, status, follow: null, zoomLabel, canvas, layer, note, panel, workspace };
}

// The editor's "add a block" controls: a type, a new block id, and the button.
function buildAddBar() {
  const bar = element("form", null, "add-bar");
  const type = element("select", null, "run-picker");
  type.setAttribute("aria-label", "Type of the new block");
  for (const name of Object.keys(BLOCK_ICONS)) {
    const option = element("option", name);
    option.value = name;
    type.append(option);
  }
  const id = element("input", null, "edit-input");
  id.placeholder = "new_block_id";
  id.setAttribute("aria-label", "Id of the new block");
  const add = element("button", "Add block", "tool");
  add.type = "submit";
  bar.append(type, id, add);
  bar.addEventListener("submit", async (event) => {
    event.preventDefault();
    const blockId = id.value.trim();
    if (await saveEdit({ action: "add", block: blockId, type: type.value }, null)) {
      id.value = "";
      selectNode(`f0_${blockId}`);
    }
  });
  return bar;
}

function drawSkillTopbar() {
  const { picker, status } = view.parts;
  const skillId = view.detail.skill.id;
  const options = view.skills.length ? view.skills.map((skill) => skill.skill_id) : [skillId];
  picker.replaceChildren(
    ...options.map((id) => {
      const option = element("option", id);
      option.value = id;
      option.selected = id === skillId;
      return option;
    }),
  );
  const parts = [];
  if (view.detail.skill.invocation) {
    const invocation = element("span", `invocation: ${view.detail.skill.invocation}`, "note");
    invocation.title = INVOCATION_MEANING[view.detail.skill.invocation] || "";
    parts.push(invocation);
  }
  const errors = view.detail.problems.filter((problem) => problem.level === "error").length;
  const warnings = view.detail.problems.length - errors;
  if (errors) parts.push(element("span", `${errors} error${errors === 1 ? "" : "s"}`, "pill state-failed"));
  if (warnings) parts.push(element("span", `${warnings} warning${warnings === 1 ? "" : "s"}`, "pill state-now"));
  if (!view.detail.error && !errors) {
    // The server builds the export (skill_export.py); the page only offers the download.
    const exportLink = element("a", "Export as Markdown", "tool");
    exportLink.href = `/api/skills/${encodeURIComponent(skillId)}/export`;
    exportLink.download = `${skillId}.zip`;
    exportLink.title =
      "Download this skill as a plain SKILL.md that any agent can follow without pskill, with its scripts, " +
      "its subagent roles, and its child skills. Nothing checks the order then: the agent follows the text.";
    parts.push(exportLink);
  }
  status.replaceChildren(...parts);
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
  const skillLink = element("a", "Skill graph", "tool");
  skillLink.href = `#/skill/${encodeURIComponent(info.skill_id)}`;
  skillLink.title = `See the skill ${info.skill_id} as it is now in .pskill/skills/, without this run.`;
  parts.push(skillLink);
  status.replaceChildren(...parts);
}

// --- the run screen: which state each node has at the replay step ------------------------------

function rows() {
  return view.detail.timeline || []; // the skill screen has no timeline
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
  return nodeInfo.parent === state.stepNode && state.stepNodeState === "now" ? "now" : "unvisited";
}

function nodeState(node, state) {
  if (isSkillScreen()) return "plain";
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
    if (isSkillScreen() && !view.detail.canvas) {
      drawLoadError();
    } else if (!window.mermaid || !view.detail.canvas) {
      if (isSkillScreen()) drawBlockList();
      else drawStepList();
    } else {
      await drawGraph();
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
    if (nodeInfo) group.querySelector(".block-icon")?.replaceChildren(blockIcon(nodeInfo.type));
    if (node === data.start) addHint(group, isSkillScreen() ? SKILL_START_HINT : START_HINT);
    else if (nodeInfo && isSkillScreen()) addHint(group, `${nodeInfo.hint}\n\nClick to see this block.`);
    else if (nodeInfo) addHint(group, `${nodeInfo.hint}\n\n${NODE_STATE_TEXT[stateName]}: ${NODE_STATE_MEANING[stateName]}\nClick to see this step.`);
  }
  for (const edge of data.edges) {
    const path = svgNode.querySelector(`[id="${renderId}-${edge.id}"]`);
    const label = svgNode.querySelector(`g.label[data-id="${edge.id}"]`);
    if (isSkillScreen()) {
      if (label) addHint(label, edge.hint);
      if (path) addHint(path, edge.hint);
      continue;
    }
    const taken = state.taken.has(edge.id) || (edge.kind === "tasks" && state.visited.has(edge.source));
    if (path) path.classList.toggle("is-taken", taken);
    const hint = `${edge.hint}\n${taken ? "The run took this edge." : "The run has not taken this edge."}\n${EDGE_STYLE_HINT}`;
    if (label) addHint(label, hint);
    if (path) addHint(path, hint);
  }
  for (const cluster of svgNode.querySelectorAll("g.cluster")) {
    addHint(cluster, cluster.id.endsWith("_TASKS") ? TASK_FRAME_HINT : CHILD_SKILL_HINT);
  }
  view.parts.note.textContent = `Drag to move · wheel to zoom · click a ${isSkillScreen() ? "block" : "step"} to see it`;
  if (!view.fitted) {
    // Open at a readable zoom: fit a small graph, and center a large one on the current step (or the start).
    view.fitted = true;
    fitCanvas();
    if (view.transform.scale < READABLE_SCALE) {
      if (isSkillScreen()) centerOnNode(data.start, READABLE_SCALE, { atTop: true });
      else centerOnStep(READABLE_SCALE);
    }
  } else if (view.followLive && !isSkillScreen()) {
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
      card.append(element("strong", row.block), blockType(row.block_type, row.summary));
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
  centerOnNode(stepState().stepNode, targetScale);
}

// Center the view on a node. With `atTop`, put the node near the top edge instead of the middle.
function centerOnNode(node, targetScale = view.transform.scale, { atTop = false } = {}) {
  const group = node && view.parts.layer.querySelector(`g.node[data-node="${node}"]`);
  if (!group) return applyTransform();
  const box = view.parts.canvas.getBoundingClientRect();
  const groupBox = group.getBoundingClientRect();
  const layerBox = view.parts.layer.getBoundingClientRect();
  const applied = view.appliedScale || 1;
  const centerX = (groupBox.left - layerBox.left + groupBox.width / 2) / applied;
  const centerY = (groupBox.top - layerBox.top + groupBox.height / 2) / applied;
  const scale = targetScale;
  const screenY = atTop ? 40 : box.height / 2;
  view.transform = { scale, x: box.width / 2 - centerX * scale, y: screenY - centerY * scale };
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
      if (view.followLive && view.parts.follow) view.parts.follow.click();
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
    if (!handle.hasPointerCapture(event.pointerId)) return;
    handle.releasePointerCapture(event.pointerId);
    savePanelWidth(setPanelWidth(workspace, workspace.getBoundingClientRect().right - event.clientX));
  });
  handle.addEventListener("lostpointercapture", () => handle.classList.remove("dragging")); // also a cancelled drag
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
  if (isSkillScreen()) {
    drawSkillPanel();
    return;
  }
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
  head.append(title, blockType(type, `${type}${skillText}`));
  if (nodeInfo) head.append(element("p", nodeInfo.hint, "note panel-hint"));
  const parts = [head];
  if (visits.length > 1) parts.push(visitPicker(visits, chosen));
  if (!chosen) {
    parts.push(element("p", "The run has not reached this step at this point of the replay.", "note"));
    parts.push(section("Where it can go", exitsOf(node)));
  } else {
    parts.push(...rowSections(chosen.row));
  }
  const stateDetails = element("details");
  stateDetails.append(element("summary", "Run state now (inputs, steps, history)"), jsonTree(view.detail.state, "state"));
  parts.push(stateDetails);
  panel.replaceChildren(...parts);
}

// --- the skill screen: the side panel --------------------------------------------------------------

function drawSkillPanel() {
  const details = view.detail.blocks[view.selectedNode ? blockOfNode(view.selectedNode) : ""];
  if (view.editing && details) {
    view.parts.panel.replaceChildren(editForm(details));
  } else if (details) {
    view.parts.panel.replaceChildren(...blockSections(details));
  } else {
    view.parts.panel.replaceChildren(...skillSections());
    if (view.editing && !view.detail.error) {
      view.parts.panel.append(element("p", "Click a block to edit it, or add a block in the top bar.", "note"));
    }
  }
}

// --- the skill screen: the editor ----------------------------------------------------------------

const EDIT_CHOICES = {
  decider: ["human", "agent"],
  parse: ["text", "json"],
  status: ["succeeded", "failed", "cancelled"],
};
const EDIT_LABELS = {
  description: "Description (a short label)",
  max_visits: "Visits at most",
  on_max_visits: "After the last visit, go to",
  retries: "Retries after a failure",
  timeout_s: "Timeout (seconds)",
  decider: "Decider",
  parse: "Parse the output as",
  status: "Status",
  skill: "Child skill",
  agent: "Agent (a file in .pskill/agents/)",
  for_each: "For each (a {{ }} list, or a JSON list)",
  run: "Command (one argument per line)",
  choices: "Choices",
  next: "Next (the first edge whose condition is true)",
};

function blockIds() {
  return Object.keys(view.detail.blocks);
}

// The form for one block. Save sends only the keys that changed, so the rest of skill.yaml stays as it is.
function editForm(details) {
  const block = blockOfNode(view.selectedNode);
  const { keys, values } = details.editable;
  const form = element("form", null, "edit-form");
  const head = element("div", null, "panel-head");
  head.append(element("h2", block), blockType(details.type));
  const errors = element("pre", null, "errors");
  errors.hidden = true;
  const readers = {};
  let choicesEditor = null;
  const fields = element("div", null, "edit-fields");
  for (const key of keys) {
    if (key === "instruction" || key === "report") continue; // drawn below, with its file
    if (key === "next") continue;
    const control = editControl(key, values[key]);
    if (key === "choices") choicesEditor = control;
    readers[key] = control.read;
    fields.append(editRow(EDIT_LABELS[key] || key, control.node));
  }
  const proseKey = keys.includes("report") ? "report" : keys.includes("instruction") ? "instruction" : null;
  if (proseKey) {
    const area = element("textarea", details.instruction ?? values[proseKey] ?? "", "edit-text");
    area.rows = 8;
    if (details.instruction_file) {
      readers.instruction_text = () => area.value;
      fields.append(editRow(`${proseKey === "report" ? "Report" : "Instruction"} (the file ${details.instruction_file})`, area));
    } else {
      readers[proseKey] = () => area.value || null;
      fields.append(editRow(proseKey === "report" ? "Report (what the agent tells the user)" : "Instruction", area));
    }
  }
  if (keys.includes("next")) {
    // A decision with choices has one edge list per choice; every other block has one edge list.
    const hasChoices = choicesEditor && (choicesEditor.read() || (values.next && typeof values.next === "object" && !Array.isArray(values.next)));
    const nextEditor = hasChoices ? choiceNextEditor(values.next, choicesEditor) : edgeListEditor(toEdges(values.next));
    readers.next = nextEditor.read;
    fields.append(editRow(EDIT_LABELS.next, nextEditor.node));
  }
  const save = element("button", "Save", "tool primary");
  save.type = "submit";
  const cancel = button("Cancel", () => drawPanel());
  const remove = button("Delete block", async () => {
    if (!window.confirm(`Delete the block ${block}? Blocks that lead to it must change first.`)) return;
    if (await saveEdit({ action: "delete", block }, errors)) selectNode(null);
  }, "tool danger");
  const actions = element("div", null, "edit-actions");
  actions.append(save, cancel, element("span", null, "spacer"), remove);
  form.append(head, element("p", "Changes go to skill.yaml when you save. Comments and the other blocks stay as they are.", "note"), fields, errors, actions);
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const changed = {};
    try {
      for (const [key, read] of Object.entries(readers)) {
        const value = key === "next" ? simpleNext(read()) : read();
        const before = key === "instruction_text" ? details.instruction : values[key];
        if (JSON.stringify(value ?? null) !== JSON.stringify(before ?? null)) changed[key] = value;
      }
    } catch (error) {
      errors.textContent = `Not saved: ${error.message}`;
      errors.hidden = false;
      return;
    }
    if (!Object.keys(changed).length) {
      drawPanel();
      return;
    }
    await saveEdit({ action: "update", block, values: changed }, errors);
  });
  return form;
}

function editRow(label, control) {
  const row = element("label", null, "edit-row");
  row.append(element("span", label, "edit-label"), control);
  return row;
}

// One control for a key: its element, and a function that reads its value (null removes the key).
function editControl(key, value) {
  if (EDIT_CHOICES[key]) return selectControl(EDIT_CHOICES[key], value ?? EDIT_CHOICES[key][0], false);
  if (key === "on_max_visits") return selectControl(blockIds(), value, true);
  if (key === "skill") return selectControl(view.skills.map((skill) => skill.skill_id), value, false);
  if (["max_visits", "retries", "timeout_s"].includes(key)) {
    const input = element("input", null, "edit-input");
    input.type = "number";
    input.min = key === "retries" ? "0" : "1";
    input.value = value ?? "";
    return { node: input, read: () => (input.value === "" ? null : Number(input.value)) };
  }
  if (key === "run") {
    const area = element("textarea", (value || []).join("\n"), "edit-text mono");
    area.rows = 4;
    return { node: area, read: () => area.value.split("\n").map((line) => line.trim()).filter(Boolean) };
  }
  if (key === "for_each") {
    const area = element("textarea", typeof value === "string" ? value : JSON.stringify(value ?? []), "edit-text mono");
    area.rows = 2;
    return { node: area, read: () => (area.value.trim().startsWith("[") ? JSON.parse(area.value) : area.value.trim()) };
  }
  if (key === "choices") return choicesControl(value || {});
  const input = element("input", null, "edit-input");
  input.value = value ?? "";
  return { node: input, read: () => input.value.trim() || null };
}

function selectControl(options, value, allowNone) {
  const select = element("select", null, "run-picker");
  const names = allowNone ? ["", ...options] : options;
  for (const name of names) {
    const option = element("option", name || "(none)");
    option.value = name;
    option.selected = name === (value ?? "");
    select.append(option);
  }
  return { node: select, read: () => select.value || null };
}

// The choices of a decision: one row per choice id and its meaning. The next editor follows its ids.
function choicesControl(choices) {
  const box = element("div", null, "edit-list");
  const listeners = [];
  const addRow = (id = "", meaning = "") => {
    const row = element("div", null, "edit-list-row");
    const idInput = element("input", null, "edit-input narrow");
    idInput.value = id;
    idInput.placeholder = "choice";
    const meaningInput = element("input", null, "edit-input");
    meaningInput.value = meaning;
    meaningInput.placeholder = "What the choice means";
    idInput.addEventListener("change", () => listeners.forEach((listener) => listener()));
    row.append(idInput, meaningInput, button("×", () => {
      row.remove();
      listeners.forEach((listener) => listener());
    }, "tool small"));
    box.insertBefore(row, addButton);
  };
  const addButton = button("Add a choice", () => addRow(), "tool small");
  box.append(addButton);
  for (const [id, meaning] of Object.entries(choices)) addRow(id, meaning);
  const read = () => {
    const result = {};
    for (const row of box.querySelectorAll(".edit-list-row")) {
      const [idInput, meaningInput] = row.querySelectorAll("input");
      if (idInput.value.trim()) result[idInput.value.trim()] = meaningInput.value.trim();
    }
    return Object.keys(result).length ? result : null;
  };
  return { node: box, read, onChange: (listener) => listeners.push(listener) };
}

// `next` in its shortest form, as the server writes it: one edge with no condition is just the block id.
function simpleNext(next) {
  if (Array.isArray(next)) return next.length === 1 && !next[0].when ? next[0].to : next;
  if (next && typeof next === "object") return Object.fromEntries(Object.entries(next).map(([id, edges]) => [id, simpleNext(edges)]));
  return next;
}

function toEdges(next) {
  if (typeof next === "string") return [{ when: "", to: next }];
  return (next || []).map((edge) => ({ when: edge.when || "", to: edge.to }));
}

// A list of edges: a condition (empty means always) and a target block per row, first match wins.
function edgeListEditor(edges) {
  const box = element("div", null, "edit-list");
  const addRow = (edge = { when: "", to: blockIds()[0] }) => {
    const row = element("div", null, "edit-list-row");
    const when = element("input", null, "edit-input mono");
    when.value = edge.when;
    when.placeholder = "always, or {{ condition }}";
    const target = selectControl(blockIds(), edge.to, false).node;
    row.append(when, element("span", "→", "note"), target, button("×", () => row.remove(), "tool small"));
    box.insertBefore(row, addButton);
  };
  const addButton = button("Add an edge", () => addRow(), "tool small");
  box.append(addButton);
  for (const edge of edges) addRow(edge);
  const read = () =>
    [...box.querySelectorAll(".edit-list-row")].map((row) => {
      const when = row.querySelector("input").value.trim();
      const to = row.querySelector("select").value;
      return when ? { when, to } : { to };
    });
  return { node: box, read };
}

// The next map of a decision with choices: one edge list per choice id of the choices editor.
function choiceNextEditor(next, choicesEditor) {
  const box = element("div", null, "edit-choice-next");
  const editors = {};
  const known = typeof next === "object" && next && !Array.isArray(next) ? next : {};
  const draw = () => {
    const ids = Object.keys(choicesEditor.read() || {});
    const kept = Object.fromEntries(ids.map((id) => [id, editors[id]?.read() ?? toEdges(known[id])]));
    box.replaceChildren();
    for (const id of ids) {
      editors[id] = edgeListEditor(kept[id].length ? toEdges(kept[id]) : [{ when: "", to: blockIds()[0] }]);
      const group = element("div", null, "edit-choice");
      group.append(element("code", id), editors[id].node);
      box.append(group);
    }
  };
  choicesEditor.onChange(draw);
  draw();
  const read = () => {
    const result = {};
    for (const id of Object.keys(choicesEditor.read() || {})) result[id] = editors[id].read();
    return result;
  };
  return { node: box, read };
}

// Send one change to the server. On success, draw the new skill; on a problem, show it and keep the form.
async function saveEdit(request, errorBox) {
  const response = await fetch(`/api/skills/${encodeURIComponent(view.skillId)}/edit`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  });
  const body = await response.json();
  if (!response.ok) {
    const text = Array.isArray(body.error) ? body.error.join("\n") : String(body.error);
    if (errorBox) {
      errorBox.textContent = `Not saved:\n${text}`;
      errorBox.hidden = false;
    } else {
      window.alert(`Not saved:\n${text}`);
    }
    return false;
  }
  view.detail = body;
  view.detailText = JSON.stringify(body);
  drawSkillTopbar();
  drawPanel();
  await drawCanvas();
  return true;
}

function blockOfNode(node) {
  return view.detail.canvas?.nodes.find((item) => item.id === node)?.block ?? "";
}

// Nothing selected: the skill itself, and what `pskill validate` says about it.
function skillSections() {
  const skill = view.detail.skill;
  const head = element("div", null, "panel-head");
  head.append(element("h2", skill.id));
  if (skill.description) head.append(element("p", skill.description, "note panel-hint"));
  const parts = [head];
  if (view.detail.error) {
    parts.push(section("The skill does not load", element("pre", view.detail.error.join("\n"), "errors")));
    return parts;
  }
  parts.push(section("Goal", element("p", skill.goal)));
  parts.push(problemsSection());
  if (skill.inputs.length) parts.push(section("Inputs", fieldList(skill.inputs)));
  if (skill.outputs.length) parts.push(section("Outputs", fieldList(skill.outputs)));
  parts.push(element("p", "Click a block on the canvas to see its instruction, its fields, and where it can go.", "note"));
  return parts;
}

function problemsSection() {
  const problems = view.detail.problems;
  if (!problems.length) return section("Checks", element("p", "pskill validate finds no problem in this skill.", "note"));
  const list = element("ul", null, "problems");
  for (const problem of problems) {
    const item = element("li", null, `problem is-${problem.level}`);
    item.append(element("strong", `${problem.level} `), document.createTextNode(`${problem.location}: ${problem.message}`));
    list.append(item);
  }
  return section(`Checks · ${problems.length}`, list);
}

function blockSections(details) {
  const block = blockOfNode(view.selectedNode);
  const head = element("div", null, "panel-head");
  const title = element("div", null, "panel-title");
  title.append(element("h2", block));
  head.append(title, blockType(details.type));
  head.append(element("p", details.hint, "note panel-hint"));
  const parts = [head];
  if (details.facts.length) {
    const facts = element("dl", null, "facts");
    for (const [name, value] of details.facts) facts.append(element("dt", name), element("dd", value));
    parts.push(facts);
  }
  if (details.child_skill) {
    const link = element("a", `Open the skill ${details.child_skill}`, "tool");
    link.href = `#/skill/${encodeURIComponent(details.child_skill)}`;
    parts.push(section("Child skill", element("p", "This block runs another skill and gets its outputs back.", "note"), link));
  }
  if (details.command) parts.push(section("Command", element("pre", details.command.join(" "), "command")));
  if (details.instruction !== null) {
    const title = details.type === "end" ? "Report" : "Instruction";
    const source = details.instruction_file ? `From ${details.instruction_file}. ` : "";
    parts.push(
      section(
        title,
        element("p", `${source}Values in {{ }} are filled in during a run.`, "note"),
        folded(markdown(details.instruction), `${block}:instruction`),
      ),
    );
  } else if (details.instruction_file) {
    parts.push(section("Instruction", element("p", `The file ${details.instruction_file} is missing.`, "errors")));
  }
  if (details.choices.length) {
    const list = element("dl", null, "facts");
    for (const choice of details.choices) list.append(element("dt", choice.choice), element("dd", choice.meaning));
    parts.push(section("Choices", list));
  }
  if (details.fields.length) parts.push(section("Output: what the answer must hold", fieldList(details.fields)));
  if (details.inputs.length) parts.push(section("Inputs to the child skill", valueList(details.inputs)));
  if (details.outputs.length) parts.push(section("Outputs of the skill", valueList(details.outputs)));
  if (details.exits.length) {
    const list = element("ul");
    for (const exit of details.exits) list.append(element("li", `→ ${exit.to}: ${exit.hint}`));
    parts.push(section("Where it can go", list));
  }
  return parts;
}

function fieldList(fields) {
  const list = element("ul", null, "fields");
  for (const field of fields) {
    const item = element("li");
    const type = `${field.type}${field.optional ? ", optional" : ""}${field.values ? `: ${field.values.join(" | ")}` : ""}`;
    item.append(element("code", field.name), element("span", ` (${type})`, "note"));
    if (field.description) item.append(document.createTextNode(` ${field.description}`));
    list.append(item);
  }
  return list;
}

function valueList(values) {
  const list = element("dl", null, "facts");
  for (const value of values) list.append(element("dt", value.name), element("dd", value.value, "mono"));
  return list;
}

// The skill screen without Mermaid (offline): one card per block, in the file order.
function drawBlockList() {
  const list = element("div", null, "step-list");
  list.append(element("p", "Graph unavailable offline (Mermaid did not load). The blocks:", "note"));
  for (const [block, details] of Object.entries(view.detail.blocks)) {
    const card = button(null, () => selectNode(details.node), "step-card");
    card.append(element("strong", block), blockType(details.type));
    list.append(card);
  }
  view.parts.layer.replaceChildren();
  view.parts.canvas.querySelector(".step-list")?.remove();
  view.parts.canvas.append(list);
  view.parts.note.textContent = "";
}

function drawLoadError() {
  const box = element("div", null, "step-list");
  box.append(
    element("p", "The skill does not load, so it has no graph. Fix these problems in skill.yaml:", "note"),
    element("pre", view.detail.error.join("\n"), "errors"),
  );
  view.parts.layer.replaceChildren();
  view.parts.canvas.querySelector(".step-list")?.remove();
  view.parts.canvas.append(box);
  view.parts.note.textContent = "";
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
  const listed = new Set(row.tasks.map((task) => task.task));
  const answers = row.submissions.filter((submission) => submission.task === null || !listed.has(submission.task));
  if (answers.length) parts.push(section(`Answers · ${answers.length}`, ...answers.map((item, index) => answerCard(item, index, row.seq))));
  if (row.output !== null) parts.push(section(row.output_title, folded(jsonTree(row.output, `${row.seq}:output`), `${row.seq}:output`)));
  return parts;
}

function scriptSections(row) {
  const parts = [];
  for (const [index, script] of row.script_runs.entries()) {
    const key = `${row.seq}:script${index}`;
    parts.push(section(row.input_title, element("pre", `$ ${script.argv.join(" ")}`, "command")));
    const result = [element("p", `Exit code ${script.exit_code ?? "-"} · ${formatDuration(script.duration_ms)}`, "note")];
    if (script.parsed !== null) {
      result.push(folded(jsonTree(script.parsed, `${key}:parsed`), `${key}:parsed`));
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
    const key = `${seq}:task${task.task}:output`;
    box.append(element("h4", `Output: the answer of task ${task.task}`), folded(jsonTree(task.output, key), key));
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
// A fold that fits needs no button, and no height limit, so a JSON node that opens later still shows whole.
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

// A JSON value as a tree: objects and arrays fold, the first level is open. `key` names the node, so an
// opened node stays open on redraws.
function jsonTree(value, key, depth = 0) {
  if (value === null || typeof value !== "object") return jsonLeaf(value);
  const isList = Array.isArray(value);
  const entries = isList ? value.map((item, index) => [index, item]) : Object.entries(value);
  const count = `${entries.length} ${isList ? "item" : "key"}${entries.length === 1 ? "" : "s"}`;
  const tree = element("details", null, depth === 0 ? "json json-root" : "json");
  tree.open = depth === 0 || view.openFolds.has(key);
  if (depth > 0) {
    tree.addEventListener("toggle", () => (tree.open ? view.openFolds.add(key) : view.openFolds.delete(key)));
  }
  tree.append(element("summary", isList ? `[ ${count} ]` : `{ ${count} }`, "json-summary"));
  const children = element("div", null, "json-children");
  for (const [name, item] of entries) {
    const line = element("div", null, "json-row");
    line.append(element("span", `${name}:`, "json-key"), jsonTree(item, `${key}/${name}`, depth + 1));
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
    const isHeredocEnd = heredocEnd(line);
    const heading = line.match(/^(#{1,6})\s+(.*)$/);
    const item = line.match(/^\s*(?:[-*]|(\d+)\.)\s+(.*)$/);
    if (fence) {
      flushParagraph();
      list = null;
      const code = [];
      for (index += 1; index < lines.length && !lines[index].trim().startsWith(fence[1]); index += 1) code.push(lines[index]);
      box.append(element("pre", code.join("\n")));
    } else if (isHeredocEnd) {
      flushParagraph();
      list = null;
      const code = [line];
      while (index + 1 < lines.length) {
        index += 1;
        code.push(lines[index]);
        if (isHeredocEnd(lines[index])) break;
      }
      box.append(element("pre", code.join("\n")));
    } else if (heading) {
      flushParagraph();
      list = null;
      box.append(inlineMarkdown(element(`h${Math.min(heading[1].length + 3, 6)}`), heading[2]));
    } else if (item) {
      flushParagraph();
      const tag = item[1] ? "OL" : "UL";
      if (!list || list.tagName !== tag) {
        box.append((list = element(tag.toLowerCase())));
        if (item[1]) list.start = Number(item[1]); // a list that a blank line cut goes on with its own number
      }
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

// The test for the last line of a heredoc (`<<'PSKILL'`) or a PowerShell here-string (`@'`) that this line
// opens, or null.
function heredocEnd(line) {
  const shell = line.match(/<<-?\s*['"]?(\w+)['"]?\s*$/);
  if (shell) return (next) => next.trim() === shell[1];
  if (/@['"]\s*$/.test(line)) return (next) => /^['"]@/.test(next.trim());
  return null;
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
  if (view.screen !== "run" || view.runId !== runId) return; // the user moved on while it loaded
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

// --- the skill screen: loading ---------------------------------------------------------------------

async function showSkill(skillId) {
  if (view.skillId !== skillId || !view.parts) {
    view.skillId = skillId;
    view.detail = null;
    view.detailText = null;
    view.fitted = false;
    view.selectedNode = null;
    view.openFolds.clear();
    buildSkillScreen();
  }
  const [detail, overview] = await Promise.all([
    fetchJson(`/api/skills/${encodeURIComponent(skillId)}`),
    fetchJson("/api/skills").catch(() => ({ skills: [] })),
  ]);
  if (view.screen !== "skill" || view.skillId !== skillId) return; // the user moved on while it loaded
  const text = JSON.stringify(detail);
  if (text === view.detailText) return;
  view.detailText = text;
  view.detail = detail;
  view.skills = overview.skills;
  drawSkillTopbar();
  drawPanel();
  await drawCanvas();
}

// --- routing ----------------------------------------------------------------------------------

async function render() {
  clearTimeout(view.pollTimer);
  const runMatch = location.hash.match(/^#\/run\/(.+)$/);
  const skillMatch = location.hash.match(/^#\/skill\/(.+)$/);
  const screen = runMatch ? "run" : skillMatch ? "skill" : location.hash === "#/skills" ? "skills" : "runs";
  if (screen !== view.screen) {
    view.parts = null; // another screen: build its layout again
    view.runId = null;
    view.skillId = null;
  }
  view.screen = screen;
  try {
    if (runMatch) {
      await showRun(decodeURIComponent(runMatch[1]));
    } else if (skillMatch) {
      await showSkill(decodeURIComponent(skillMatch[1]));
    } else if (screen === "skills") {
      await showSkills();
    } else {
      await showRuns();
    }
  } catch (error) {
    app.replaceChildren(topbar(), element("p", `The viewer could not load the data: ${error.message}`, "errors loading"));
  }
}

window.addEventListener("resize", () => {
  const workspace = view.parts?.workspace;
  // Fit the width that the user chose (not the current one) to the new window: it comes back when it grows.
  // Without site data (blocked storage), fit the current width instead.
  const chosen = savedPanelWidth() || parseFloat(workspace?.style.getPropertyValue("--panel-width") || "");
  if (workspace && chosen) setPanelWidth(workspace, chosen);
});
window.addEventListener("hashchange", () => {
  view.detailText = null;
  if (view.playTimer) clearInterval(view.playTimer);
  view.playTimer = null;
  render();
});
window.addEventListener("keydown", (event) => {
  if (view.screen !== "run" || !view.parts || ["INPUT", "SELECT", "TEXTAREA"].includes(event.target.tagName)) return;
  if (event.key === "ArrowRight") setStep(view.step + 1);
  else if (event.key === "ArrowLeft") setStep(view.step - 1);
});
render();
