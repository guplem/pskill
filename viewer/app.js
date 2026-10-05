// The pskill viewer. It only draws what the local server returns (pskill_runner/viewer_data.py and skill_view.py).
// Every text from a run goes into the page through textContent, never as HTML.

import { FACT_FIELDS, FIELD_HELP } from "./field_help.js";

const UNFINISHED = ["active", "waiting_for_human", "paused"];
const POLL_MS = 1000;
const PLAY_MS = 700;
const FOLD_LINE_LIMIT = 3;
const PANEL_WIDTH_KEY = "pskill.panelWidth";
const REPOSITORY_URL = "https://github.com/guplem/pskill"; // the logo and the version note lead there
const PLACE_KEY = "pskill.place"; // the project that the Content tab opens
// How often the page reads its data again on its own. Each read is cheap: local files, no network.
const REFRESH_CHOICES = [
  { id: "off", label: "Auto: off", seconds: 0 },
  { id: "10s", label: "Auto: 10 s", seconds: 10 },
  { id: "30s", label: "Auto: 30 s", seconds: 30 },
  { id: "1m", label: "Auto: 1 min", seconds: 60 },
  { id: "5m", label: "Auto: 5 min", seconds: 300 },
];
const DEFAULT_REFRESH = "30s";
const REFRESH_KEY = "pskill.refresh";
// How often the page updates the live status and checks whether a refresh is due. It is not the refresh
// interval: it is short, so the time since the last read counts up each second.
const REFRESH_TICK_MS = 1000;
// The shortest time the refresh button stays down after a press, so a fast read still shows that it happened.
const REFRESH_REST_MS = 1000;
const EXPANDED_KEY = "pskill.expandChildSkills"; // only a choice to expand is kept: collapsed is the default
// The run screen opens with the child skills expanded, so a live run shows its exact step: only a choice to collapse is kept.
const RUN_COLLAPSED_KEY = "pskill.collapseRunChildSkills";
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
// A value that reads the output of a block: steps.<block> (its latest output) or history.<block> (every output).
const BLOCK_REFERENCE = /\b(steps|history)\.([a-z0-9_]+)(?:\.\w+)*/g;

const app = document.getElementById("app");
const view = {
  version: null, // the pskill version that serves this viewer
  projectName: null, // the folder name of the local server's project
  place: null, // the project of the open screen: "local", or a folder that the hosted viewer found
  lastPlace: savedPlace(), // the project that the Content tab opens
  runsPlace: "all", // the runs page shows the runs of every project, or of one
  pythonReady: false,
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
  pollWaiting: false, // a live run's poll that waits for the hidden page to come back
  refreshChoice: savedRefresh(),
  refreshedAt: null, // when the last read finished, in milliseconds
  refreshing: false,
  live: false, // a live run that the page polls every second or two
  pollAsked: false, // the screen of this render asked to poll again
  dragEnded: false,
  playTimer: null,
  collapsed: savedCollapsed(), // the skill screen draws each child skill as its call block's node, not a frame
  runCollapsed: savedRunCollapsed(), // the same choice on the run screen, kept apart: expanded by default
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

// A "?" button for one field of skill.yaml: a hover tooltip, and a dialog with details and examples on a click.
function helpButton(field) {
  const help = FIELD_HELP[field];
  const node = button("?", (event) => {
    event.preventDefault();
    event.stopPropagation();
    showFieldHelp(field);
  }, "help-button");
  node.title = help.short;
  node.setAttribute("aria-label", `About ${help.title}`);
  return node;
}

// An on and off switch: a track with a knob, then its label. The role tells a screen reader what it is.
function switchControl(text, on, onClick) {
  const control = button(null, onClick, "switch");
  control.setAttribute("role", "switch");
  control.setAttribute("aria-checked", String(on));
  control.append(element("span", null, "switch-track"), document.createTextNode(text));
  return control;
}

// A heading or a label with its "?" button after the text.
function withHelp(tag, text, field, className) {
  const node = element(tag, null, className ? `${className} with-help` : "with-help");
  node.append(document.createTextNode(text), helpButton(field));
  return node;
}

function showFieldHelp(field) {
  const help = FIELD_HELP[field];
  const dialog = element("dialog", null, "help-dialog");
  const body = element("div", null, "help-body");
  const head = element("div", null, "help-head");
  head.append(element("h2", help.title, "mono"), button("Close", () => dialog.close(), "tool small"));
  body.append(head, element("p", help.short, "help-lead"));
  for (const paragraph of help.details) body.append(inlineMarkdown(element("p"), paragraph));
  if (help.examples.length) body.append(element("h3", help.examples.length === 1 ? "Example" : "Examples"));
  for (const example of help.examples) body.append(element("p", example.caption, "note"), element("pre", example.code));
  body.append(element("p", "AUTHORING.md in .pskill/ has the full guide to writing skills.", "note"));
  dialog.append(body);
  dialog.addEventListener("click", (event) => {
    if (event.target === dialog) dialog.close(); // a click on the backdrop
  });
  dialog.addEventListener("close", () => dialog.remove());
  for (const old of document.querySelectorAll(".help-dialog")) old.remove(); // in case a close event never came
  document.body.append(dialog);
  dialog.showModal();
}

// The block type and what it means, with its "?" button, for the head of the side panel on the skill screen.
function typeLine(type, meaning) {
  const line = element("span", null, "with-help");
  line.append(blockType(type, `${type}: ${meaning}`), helpButton("type"));
  return line;
}

// The block's own description in the ink color, then the notes on who decides and on its limits.
function appendBlockIntro(head, block) {
  if (block.description) head.append(element("p", block.description, "panel-description"));
  if (block.notes) head.append(element("p", block.notes, "note panel-hint"));
}

// --- where the data comes from ---------------------------------------------------------------
// `pskill view` serves one project, the place "local". On GitHub Pages no server answers: hosted.js reads the
// folders that the user picked and answers in the browser, and each project in those folders is one place.

const LOCAL_PLACE = "local";
const ALL_PLACES = "*";
const PYTHON_LOADING = "Starting Python in your browser. The first visit downloads about 15 MB.";
const UNSUPPORTED =
  "This page reads your project folders through the File System Access API, which only Chrome and Edge have. " +
  "Open it in one of them, or run `uv run .pskill/pskill.py view` in your project.";
const FOLDERS_INTRO =
  "Pick each project folder (the one that holds .pskill), or a folder of clones and worktrees. The viewer finds " +
  "the projects in it: its subfolders up to 3 levels down, and the worktrees of each git checkout. " +
  "Your files stay on this computer: the page reads them in the browser.";
let hosted = null; // the hosted.js module on GitHub Pages, else null

// One API request, as { ok, data } with the parsed JSON body.
async function apiRequest(path, { place = view.place, method = "GET", body = null } = {}) {
  if (hosted) {
    const answer = await hosted.request(place, method, path, body ?? "");
    return { ok: answer.status < 300, data: JSON.parse(new TextDecoder().decode(answer.body)) };
  }
  const options = method === "GET" ? { cache: "no-store" } : { method, headers: { "Content-Type": "application/json" }, body };
  const response = await fetch(path, options);
  return { ok: response.ok, data: await response.json() };
}

async function apiJson(path, place = view.place) {
  const { ok, data } = await apiRequest(path, { place });
  if (!ok) throw new Error(data.error || "The request failed.");
  return data;
}

// A download on the hosted viewer: Python builds the file, and the page saves it.
async function downloadHosted(path) {
  const answer = await hosted.request(view.place, "GET", path);
  if (answer.status !== 200) {
    window.alert(JSON.parse(new TextDecoder().decode(answer.body)).error);
    return;
  }
  const link = element("a");
  link.href = URL.createObjectURL(new Blob([answer.body], { type: answer.contentType }));
  link.download = answer.downloadName;
  link.click();
  setTimeout(() => URL.revokeObjectURL(link.href), 1000);
}

function placeList() {
  return hosted ? hosted.placeList() : [{ id: LOCAL_PLACE, label: view.projectName || "This project", kind: null, branch: null }];
}

function placeInfo(id) {
  return placeList().find((place) => place.id === id);
}

// A project in plain words: its path, then its kind and its branch when it is a git checkout.
function placeText(place) {
  if (!place) return "a folder that is no longer in the list";
  return [place.label, place.kind === "folder" ? null : place.kind, place.branch].filter(Boolean).join(" · ");
}

// A list of projects, optionally with "All folders" first.
function placePicker(value, withAll, onChange) {
  const picker = element("select", null, "run-picker");
  picker.setAttribute("aria-label", "Folder");
  const options = withAll ? [{ id: "all", label: "All folders" }, ...placeList()] : placeList();
  for (const place of options) {
    const option = element("option", place.id === "all" ? place.label : placeText(place));
    option.value = place.id;
    option.selected = place.id === value;
    picker.append(option);
  }
  picker.addEventListener("change", () => onChange(picker.value));
  return picker;
}

function savedPlace() {
  try {
    return localStorage.getItem(PLACE_KEY);
  } catch {
    return null; // the browser blocks site data
  }
}

function rememberPlace(place) {
  view.lastPlace = place;
  try {
    localStorage.setItem(PLACE_KEY, place);
  } catch {
    // the browser blocks site data: the choice lasts until the reload
  }
}

// The run, skill, and agent screens: each shows one thing, and its logo leads back to the list.
function isDetailScreen() {
  return ["run", "skill", "agent"].includes(view.screen);
}

// The bar at the top of every screen, in one row: the logo, then the tabs on the list screens (Runs, Content,
// Folders) or the screen's own parts on a detail screen, then the refresh control with the live status.
function topbar(...parts) {
  const bar = element("header", null, "topbar");
  const brand = brandLink();
  brand.className = "brand";
  const access = hosted?.needsAccess() ? [button("Allow the folders again", allowFolders, "tool primary")] : [];
  if (isDetailScreen()) {
    bar.append(brand, ...access, ...parts, refreshControl());
    return bar;
  }
  const nav = element("nav", null, "nav");
  const tabs = [
    ["Runs", "#/", ["runs"]],
    ["Content", contentHref(view.lastPlace), ["content"]],
  ];
  if (hosted) tabs.push(["Folders", "#/folders", ["folders"]]);
  for (const [text, href, screens] of tabs) {
    const link = element("a", text, "nav-link");
    link.href = href;
    if (screens.includes(view.screen)) link.setAttribute("aria-current", "page");
    nav.append(link);
  }
  bar.append(brand, nav, ...access, refreshControl());
  return bar;
}

// The logo. On a detail screen, it leads back to the list that the screen belongs to: the runs, or the content
// of the project that the screen shows. On the Runs, Content, and Folders screens, it opens pskill on GitHub.
function brandLink() {
  const back = {
    run: ["#/", "Back to the runs"],
    skill: [contentHref(view.place), "Back to the skills and agents of this project"],
    agent: [contentHref(view.place), "Back to the skills and agents of this project"],
  }[view.screen];
  if (!back) return externalLink("pskill", REPOSITORY_URL, "pskill on GitHub: the code, the docs, and the releases");
  const link = element("a");
  const arrow = element("span", "‹", "brand-back");
  arrow.setAttribute("aria-hidden", "true");
  link.append(arrow, "pskill");
  [link.href, link.title] = back;
  link.setAttribute("aria-label", back[1]);
  return link;
}

// --- refreshing: read the data again, on a schedule or on a press ---------------------------------------

function savedRefresh() {
  try {
    const choice = localStorage.getItem(REFRESH_KEY);
    return REFRESH_CHOICES.some((item) => item.id === choice) ? choice : DEFAULT_REFRESH;
  } catch {
    return DEFAULT_REFRESH; // the browser blocks site data
  }
}

function saveRefresh(choice) {
  try {
    localStorage.setItem(REFRESH_KEY, choice);
  } catch {
    // the browser blocks site data: the choice lasts until the reload
  }
}

// An open editor or dialog. A refresh draws the screen again, so it would lose what is in them.
function editorOpen() {
  return Boolean(app.querySelector(".edit-form") || document.querySelector("dialog[open]"));
}

// Whether a refresh now would get in the way: an open editor, an open Details card, or a text field in use.
function refreshWouldInterrupt() {
  if (editorOpen() || document.querySelector(":popover-open")) return true;
  return Boolean(document.activeElement?.matches("textarea, input:not([type]), input[type=text]"));
}

function refreshDue() {
  const seconds = REFRESH_CHOICES.find((item) => item.id === view.refreshChoice)?.seconds ?? 0;
  if (!seconds || document.visibilityState === "hidden" || view.refreshing || refreshWouldInterrupt()) return false;
  if (view.refreshedAt === null) return true;
  const waited = Date.now() - view.refreshedAt;
  return waited < 0 || waited >= seconds * 1000; // a clock that went back must not stop the refresh
}

function tickRefresh() {
  drawRefreshButtons();
  if (refreshDue()) refreshNow();
}

// Read everything again. On the hosted viewer, look for new clones and worktrees first. The screen draws
// again only where its data changed (each screen compares it with view.detailText).
async function refreshNow() {
  if (view.refreshing || editorOpen()) return;
  view.refreshing = true;
  drawRefreshButtons();
  const rest = new Promise((resolve) => setTimeout(resolve, REFRESH_REST_MS));
  try {
    if (hosted?.supported()) await hosted.rescan();
    await render();
  } finally {
    await rest;
    view.refreshing = false;
    drawRefreshButtons();
  }
}

function refreshTip() {
  if (view.refreshing) return "Refreshing…";
  if (editorOpen()) return "Save or close the edit first: a refresh would lose it.";
  return "Refresh now";
}

// The time since the last read, in whole seconds or minutes: the live status changes once a second.
function updatedText() {
  if (view.refreshedAt === null) return "Not updated yet";
  const seconds = Math.floor(Math.max(0, Date.now() - view.refreshedAt) / 1000);
  if (seconds < 5) return "Updated just now";
  return seconds < 60 ? `Updated ${seconds} s ago` : `Updated ${Math.floor(seconds / 60)} min ago`;
}

const LIVE_MODE_TEXT = {
  live: "Live: the page reads the open run every second while it runs.",
  auto: "The page reads the runs and the files again on its own, at the time that you chose.",
  off: "The page reads the data only when you open a screen or press the refresh button.",
};

// The refresh button and the live status of each top bar. The button is down and turning while a refresh
// runs. The status dot pulses while a live run updates, is solid while the page refreshes on its own,
// and is hollow when the automatic refresh is off.
function drawRefreshButtons() {
  for (const press of document.querySelectorAll(".refresh-now")) {
    press.disabled = view.refreshing;
    if (view.refreshing) press.setAttribute("aria-busy", "true");
    else press.removeAttribute("aria-busy");
  }
  const mode = view.live ? "live" : view.refreshChoice === "off" ? "off" : "auto";
  for (const status of document.querySelectorAll(".refresh-status")) {
    status.dataset.mode = mode;
    status.title = LIVE_MODE_TEXT[mode];
    const since = updatedText();
    status.querySelector(".refresh-since").textContent = mode === "live" ? `Live · ${since.toLowerCase()}` : since;
  }
}

function refreshControl() {
  const control = element("div", null, "refresh-control");
  const status = element("span", null, "refresh-status note");
  status.append(element("span", null, "refresh-dot"), element("span", null, "refresh-since"));
  const choice = element("select", null, "run-picker refresh-choice");
  choice.setAttribute("aria-label", "Refresh on its own");
  choice.title = "How often the page reads the runs and the files again. It waits while the tab is hidden or while you edit.";
  for (const item of REFRESH_CHOICES) {
    const option = element("option", item.label);
    option.value = item.id;
    option.selected = item.id === view.refreshChoice;
    choice.append(option);
  }
  choice.addEventListener("change", () => {
    view.refreshChoice = choice.value;
    saveRefresh(choice.value);
    drawRefreshButtons();
  });
  const press = button("", refreshNow, "tool refresh-now");
  press.setAttribute("aria-label", "Refresh now");
  press.append(refreshIcon());
  // The tip says how long ago the page read its data, at the moment the pointer or the focus arrives.
  const showTip = () => (press.title = refreshTip());
  press.addEventListener("pointerenter", showTip);
  press.addEventListener("focus", showTip);
  control.append(status, choice, press);
  // The parts take their state when drawRefreshButtons runs next: at the end of render, or on the next tick.
  return control;
}

// Two strokes: a circle with a gap, and the arrow head at its end.
function refreshIcon() {
  const namespace = "http://www.w3.org/2000/svg";
  const icon = document.createElementNS(namespace, "svg");
  icon.setAttribute("viewBox", "0 0 24 24");
  icon.setAttribute("aria-hidden", "true");
  for (const shape of ["M21 12a9 9 0 1 1-2.64-6.36", "M21 3v6h-6"]) {
    const path = document.createElementNS(namespace, "path");
    path.setAttribute("d", shape);
    icon.append(path);
  }
  return icon;
}

// Ask a live run again soon, while the page is visible. A hidden page asks when it comes back.
function pollAgain(milliseconds) {
  view.pollAsked = true;
  if (document.visibilityState === "visible") view.pollTimer = setTimeout(render, milliseconds);
  else view.pollWaiting = true;
}

// A screen with the top bar and one message: Python starts, the browser cannot run the viewer, or an error.
// index.html starts #app with the "loading" class. Its padding goes, so the top bar spans the page.
function showMessage(text, className) {
  app.className = "";
  app.replaceChildren(topbar(), element("p", text, `${className} loading`));
}

// A name that leads to another skill or agent: a link with an arrow, so it reads as "go there".
function entityLink(text, href) {
  const link = element("a", text, "entity-link");
  link.href = href;
  return link;
}

function encodedPath(...parts) {
  return parts.map((part) => encodeURIComponent(part)).join("/");
}

function runHref(place, runId) {
  return `#/run/${encodedPath(place, runId)}`;
}

function skillHref(skillId, place = view.place) {
  return `#/skill/${encodedPath(place, skillId)}`;
}

function agentHref(name, place = view.place) {
  return `#/agent/${encodedPath(place, name)}`;
}

function contentHref(place) {
  return place ? `#/content/${encodedPath(place)}` : "#/content";
}

function isSkillScreen() {
  return view.screen === "skill";
}

// Whether the screen draws each child skill as its call block's node: the skill screen and the run screen
// each keep their own choice.
function childSkillsCollapsed() {
  return isSkillScreen() ? view.collapsed : view.runCollapsed;
}

// The canvas that the screen draws: with the child skills expanded or collapsed.
function canvasData() {
  return childSkillsCollapsed() ? view.detail?.collapsed_canvas : view.detail?.canvas;
}

// The node on the drawn canvas that shows a node: the node, or, when the child skills are collapsed, the call
// block at the top of its child frames. The side panel still shows the node itself.
function nodeOnCanvas(node) {
  return node && childSkillsCollapsed() ? callBlockOnTop(node) : node;
}

// --- the runs page ----------------------------------------------------------------------------

const RUN_FILTERS = {
  unfinished: { label: "Unfinished", keep: (run) => UNFINISHED.includes(run.status) },
  all: { label: "All", keep: () => true },
  failed: { label: "Failed", keep: (run) => run.status === "failed" },
};

async function showRuns() {
  const overview = await apiJson("/api/runs", hosted ? ALL_PLACES : LOCAL_PLACE);
  if (view.screen !== "runs") return; // the user moved on while it loaded
  for (const run of overview.runs) run.place ??= LOCAL_PLACE;
  const text = JSON.stringify(overview) + view.runsFilter + view.runsPlace;
  if (text !== view.detailText) {
    view.detailText = text;
    drawRuns(overview);
  }
  if (overview.runs.some((run) => UNFINISHED.includes(run.status))) pollAgain(POLL_MS * 2);
}

function drawRuns(overview) {
  const page = element("main", null, "runs-page");
  const filters = element("div", null, "filters");
  const placeRuns = overview.runs.filter((run) => view.runsPlace === "all" || run.place === view.runsPlace);
  for (const [key, filter] of Object.entries(RUN_FILTERS)) {
    const count = placeRuns.filter(filter.keep).length;
    const chip = button(`${filter.label} · ${count}`, () => {
      view.runsFilter = key;
      view.detailText = null;
      render();
    });
    chip.setAttribute("aria-pressed", String(view.runsFilter === key));
    filters.append(chip);
  }
  if (placeList().length > 1) {
    filters.append(
      placePicker(view.runsPlace, true, (place) => {
        view.runsPlace = place;
        view.detailText = null;
        render();
      }),
    );
  }
  const cards = element("div", null, "run-cards");
  const runs = placeRuns.filter(RUN_FILTERS[view.runsFilter].keep);
  const finished = runs.filter((run) => !UNFINISHED.includes(run.status));
  if (finished.length) {
    const cleanup = button(`Delete the ${finished.length} finished run${finished.length === 1 ? "" : "s"} shown`, () => deleteRuns(finished), "tool danger");
    cleanup.title = "Remove their folders from .pskill/runs/, for cleanup. The unfinished runs stay.";
    filters.append(cleanup);
  }
  for (const run of runs) {
    const card = element("a", null, "run-card");
    card.href = runHref(run.place, run.run_id);
    const head = element("div", null, "run-card-head");
    head.append(element("span", run.skill_id), statusPill(run.status));
    card.append(
      head,
      element("span", `at ${run.current_block || "-"} · ${formatDuration(run.duration_ms)}`, "run-card-meta"),
      element("span", `${formatTime(run.created_at)} · ${run.harness} · ${run.mode} · ${run.run_id}`, "run-card-meta mono"),
    );
    if (hosted) card.append(element("span", placeText(placeInfo(run.place)), "run-card-place"));
    cards.append(card);
  }
  page.append(element("h1", "Runs"), filters);
  page.append(runs.length ? cards : element("p", hosted && !placeList().length ? "No folder yet: add one on the Folders tab." : "No runs here yet.", "note"));
  if (overview.summaries.length) page.append(...skillTotals(overview.summaries));
  app.className = "";
  app.replaceChildren(topbar(), page, ...versionNote());
}

// The numbers of each skill, under the run cards. They count every run, whatever the filters, so they get
// their own heading and a table: they must not read as one more run.
function skillTotals(summaries) {
  const table = element("table", null, "skill-totals");
  const head = element("tr");
  for (const name of ["Skill", "Runs", "Succeeded", "Median time"]) head.append(element("th", name));
  const body = element("tbody");
  for (const summary of summaries) {
    const succeeded =
      summary.success_rate === null ? "no finished run" : `${Math.round(summary.success_rate * 100)} % of ${summary.finished}`;
    const row = element("tr");
    row.append(
      element("td", summary.skill_id, "mono"),
      element("td", String(summary.runs)),
      element("td", succeeded),
      element("td", formatDuration(summary.median_duration_ms)),
    );
    body.append(row);
  }
  const thead = element("thead");
  thead.append(head);
  table.append(thead, body);
  const where = hosted ? "in every folder" : "in this project";
  return [element("h2", "By skill"), element("p", `Every run of each skill ${where}, whatever the filters above.`, "note"), table];
}

// --- the content page: the skills and the agents of one project ----------------------------------

async function showContent(place) {
  if (!place || !placeInfo(place)) {
    // No project in the address, or one that is gone: the last one, or the first one.
    const fallback = placeInfo(view.lastPlace) ?? placeList()[0];
    if (fallback) location.replace(contentHref(fallback.id));
    else drawEmptyContent();
    return;
  }
  view.place = place;
  rememberPlace(place);
  const [skills, agents] = await Promise.all([apiJson("/api/skills", place), apiJson("/api/agents", place)]);
  if (view.screen !== "content" || view.place !== place) return; // the user moved on while it loaded
  const text = JSON.stringify([skills, agents]) + JSON.stringify(placeList());
  if (text === view.detailText) return;
  view.detailText = text;
  const page = element("main", null, "runs-page");
  const where = element("div", null, "filters");
  if (placeList().length > 1) where.append(placePicker(place, false, (next) => (location.hash = contentHref(next))));
  else where.append(element("span", placeText(placeInfo(place)), "note mono"));
  const internalSkills = skills.skills.filter((skill) => skill.invocation === "internal");
  const mainSkills = skills.skills.filter((skill) => skill.invocation !== "internal");
  page.append(
    element("h1", "Content"),
    where,
    element("h2", "Skills"),
    element("p", "Every skill in .pskill/skills/. Open one to see its steps and how they connect.", "note"),
    skills.skills.length ? skillCards(mainSkills) : element("p", "This project has no skills yet.", "note"),
  );
  if (internalSkills.length) {
    page.append(
      element("h3", "Internal skills"),
      element("p", "Only a call block of another skill starts these. Several skills can call the same one.", "note"),
      skillCards(internalSkills),
    );
  }
  page.append(
    element("h2", "Agents"),
    element("p", "Every agent in .pskill/agents/. A parallel block gives its text to each subagent, before the task.", "note"),
    agents.agents.length ? agentCards(agents.agents) : element("p", "This project has no agents yet.", "note"),
  );
  app.className = "";
  app.replaceChildren(topbar(), page, ...versionNote());
}

function drawEmptyContent() {
  const page = element("main", null, "runs-page");
  page.append(element("h1", "Content"), element("p", "No folder yet: add one on the Folders tab.", "note"));
  app.className = "";
  app.replaceChildren(topbar(), page);
}

// The pskill version at the foot of the list screens (runs, skills, agents), or nothing when it is unknown.
function versionNote() {
  if (!view.version) return [];
  const note = element("p", null, "version-note");
  note.append(externalLink(`pskill ${view.version}`, `${REPOSITORY_URL}/releases/tag/v${view.version}`, "What changed in this version"));
  return [note];
}

// A link that opens another site in a new tab, so the viewer stays open.
function externalLink(text, href, hint) {
  const link = element("a", text);
  link.href = href;
  link.target = "_blank";
  link.rel = "noopener";
  link.title = hint;
  return link;
}

function skillCards(skills) {
  const cards = element("div", null, "run-cards");
  for (const skill of skills) {
    const card = element("a", null, skill.error ? "run-card skill-card has-error" : "run-card skill-card");
    card.href = skillHref(skill.skill_id);
    const head = element("div", null, "run-card-head");
    head.append(element("span", skill.skill_id));
    if (skill.error) head.append(element("span", "does not load", "pill state-failed"));
    else if (skill.invocation === "manual") head.append(element("span", skill.invocation, "pill state-idle"));
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
  return cards;
}

// --- the agents and the agent screen --------------------------------------------------------------

function agentCards(agents) {
  const cards = element("div", null, "run-cards");
  for (const agent of agents) {
    const card = element("a", null, "run-card skill-card");
    card.href = agentHref(agent.name);
    const head = element("div", null, "run-card-head");
    head.append(element("span", agent.name));
    const users = agent.used_by.length ? `used by ${agent.used_by.join(", ")}` : "no fixed use in a skill";
    card.append(head, element("span", agent.summary, "skill-card-description"), element("span", users, "run-card-meta"));
    cards.append(card);
  }
  return cards;
}

async function showAgent(place, name) {
  view.place = place;
  const agent = await apiJson(`/api/agents/${encodeURIComponent(name)}`, place);
  if (view.screen !== "agent") return; // the user moved on while it loaded
  const text = JSON.stringify(agent) + place;
  if (text === view.detailText) return; // a refresh with no change keeps the scroll position
  view.detailText = text;
  drawAgent(agent, false);
}

function drawAgent(agent, editing) {
  const page = element("main", null, "runs-page agent-page");
  const users = element("div", null, "entity-links");
  for (const user of agent.used_by) {
    const item = element("span", null, "entity-user");
    item.append(entityLink(user.skill, skillHref(user.skill)), element("span", `block ${user.blocks.join(", ")}`, "note"));
    users.append(item);
  }
  const usedBy = agent.used_by.length
    ? users
    : element("p", "No skill names this agent where pskill validate can see it. A skill can still pick it from a list that a script returns.", "note");
  const file = hosted ? `The file ${agent.file} in ${placeText(placeInfo(view.place))}.` : `The file ${agent.file}.`;
  page.append(element("h1", agent.name), element("p", file, "note"), section("Used by", usedBy));
  page.append(editing ? agentEditor(agent) : agentText(agent));
  app.className = "";
  app.replaceChildren(topbar(), page);
}

function agentText(agent) {
  const head = element("div", null, "agent-text-head");
  head.append(element("h3", "Text"), button("Edit", () => drawAgent(agent, true)));
  return section(head, agent.text.trim() ? markdown(agent.text) : element("p", "The file is empty.", "note"));
}

function agentEditor(agent) {
  const form = element("form", null, "edit-form");
  const area = element("textarea", agent.text, "edit-text mono agent-editor");
  area.rows = 24;
  area.setAttribute("aria-label", `The text of ${agent.name}`);
  const errors = element("pre", null, "errors");
  errors.hidden = true;
  const save = element("button", "Save", "tool primary");
  save.type = "submit";
  const actions = element("div", null, "edit-actions");
  actions.append(save, button("Cancel", () => drawAgent(agent, false)));
  form.append(element("p", `Markdown. Changes go to ${agent.file} when you save.`, "note"), area, errors, actions);
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (area.value === agent.text) {
      drawAgent(agent, false);
      return;
    }
    const saved = await saveAgent(agent.name, area.value, errors);
    if (saved) drawAgent(saved, false);
  });
  return form;
}

async function saveAgent(name, text, errorBox) {
  const { ok, data: body } = await apiRequest(`/api/agents/${encodeURIComponent(name)}/edit`, {
    method: "POST",
    body: JSON.stringify({ text }),
  });
  if (!ok) {
    errorBox.textContent = `Not saved:\n${Array.isArray(body.error) ? body.error.join("\n") : String(body.error)}`;
    errorBox.hidden = false;
    return null;
  }
  return body;
}

// --- the run screen: layout -------------------------------------------------------------------

function buildRunScreen() {
  const picker = element("select", null, "run-picker");
  picker.setAttribute("aria-label", "Run");
  picker.addEventListener("change", () => {
    location.hash = picker.value; // each option is the link to its run
  });
  const status = element("span", null, "run-status");
  const follow = button("Follow live", () => {
    view.followLive = !view.followLive;
    follow.setAttribute("aria-pressed", String(view.followLive));
    if (view.followLive) centerOnStep();
  });
  follow.setAttribute("aria-pressed", String(view.followLive));
  const zoomLabel = element("span", "100 %", "note");
  const collapseToggle = switchControl("Collapse sub-skills", view.runCollapsed, toggleChildSkills);
  collapseToggle.title = "Draw each child skill as its call block's node. A step inside a child skill shows on its call block.";
  const bar = topbar(picker, status);
  const { workspace, canvas, layer, note, panel } = buildWorkspace("The selected step", [follow, ...zoomTools(zoomLabel)]);

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
  view.parts = { picker, status, follow, zoomLabel, canvas, layer, note, panel, progress, marks, slider, labels, play, workspace, collapseToggle };
}

function zoomTools(zoomLabel) {
  return [button("Fit", fitCanvas), button("−", () => zoomBy(1 / 1.2)), zoomLabel, button("+", () => zoomBy(1.2))];
}

// The canvas, the panel, and the handle between them: the same on the run screen and the skill screen.
// The canvas tools (the zoom, and Follow live on the run screen) float in the canvas's top right corner.
function buildWorkspace(panelLabel, tools) {
  const canvas = element("div", null, "canvas");
  const layer = element("div", null, "layer");
  const note = element("p", null, "canvas-note");
  const canvasTools = element("div", null, "canvas-tools");
  canvasTools.append(...tools);
  canvas.append(layer, note, canvasTools);
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
  const picker = element("select", null, "run-picker");
  picker.setAttribute("aria-label", "Skill");
  picker.addEventListener("change", () => {
    location.hash = skillHref(picker.value);
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
  const collapseToggle = switchControl("Collapse sub-skills", view.collapsed, toggleChildSkills);
  collapseToggle.title = "Draw each child skill as one node, to see the main flow of a skill with many child skills.";
  const bar = topbar(picker, status, element("span", null, "spacer"), addBar, editToggle, collapseToggle);
  const { workspace, canvas, layer, note, panel } = buildWorkspace("The selected block", zoomTools(zoomLabel));
  layer.classList.add("is-skill");
  const screen = element("div", null, "run-screen skill-screen");
  screen.append(bar, workspace);
  app.className = "";
  app.replaceChildren(screen);
  view.parts = { picker, status, follow: null, zoomLabel, canvas, layer, note, panel, workspace, collapseToggle };
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
  const facts = [];
  if (view.detail.skill.invocation) {
    const invocation = view.detail.skill.invocation;
    facts.push(["Invocation", `${invocation}: ${INVOCATION_MEANING[invocation] || ""}`]);
  }
  if (hosted) facts.push(["Project", placeText(placeInfo(view.place))]);
  const parts = facts.length ? [detailsButton(facts)] : [];
  const errors = view.detail.problems.filter((problem) => problem.level === "error").length;
  const warnings = view.detail.problems.length - errors;
  if (errors) parts.push(element("span", `${errors} error${errors === 1 ? "" : "s"}`, "pill state-failed"));
  if (warnings) parts.push(element("span", `${warnings} warning${warnings === 1 ? "" : "s"}`, "pill state-now"));
  if (!view.detail.error && !errors) {
    // The server builds the export (skill_export.py); the page only offers the download.
    const exportLink = element("a", "Export", "tool");
    const exportPath = `/api/skills/${encodeURIComponent(skillId)}/export`;
    exportLink.href = hosted ? "#" : exportPath;
    exportLink.download = `${skillId}.zip`;
    if (hosted) {
      exportLink.addEventListener("click", (event) => {
        event.preventDefault();
        downloadHosted(exportPath);
      });
    }
    exportLink.title =
      "Download this skill as a plain SKILL.md that any agent can follow without pskill, with its scripts, " +
      "its subagent roles, and its child skills. Nothing checks the order then: the agent follows the text.";
    parts.push(exportLink);
  }
  status.replaceChildren(...parts);
  view.parts.collapseToggle.hidden = !view.detail.canvas?.frames.length; // a skill with no child skill has nothing to collapse
}

function drawTopbar() {
  const { picker, status } = view.parts;
  const info = view.detail.info;
  const current = { run_id: info.run_id, skill_id: info.skill_id, status: info.status, place: view.place };
  const options = view.runs.length ? view.runs : [current];
  // One group per status, the unfinished runs first: the status pill names the shown run's own status.
  const groups = new Map();
  for (const run of [...options].sort((a, b) => UNFINISHED.includes(b.status) - UNFINISHED.includes(a.status))) {
    const label = STATUS_TEXT[run.status] || run.status;
    if (!groups.has(label)) groups.set(label, element("optgroup"));
    groups.get(label).label = label[0].toUpperCase() + label.slice(1);
    const option = element("option", `${run.skill_id} · ${run.run_id}`);
    option.value = runHref(run.place, run.run_id);
    option.selected = run.run_id === info.run_id && run.place === view.place;
    groups.get(label).append(option);
  }
  picker.replaceChildren(...groups.values());
  const facts = [
    ["Harness", `${info.harness}: the agent tool that runs the skill.`],
    ["Mode", MODE_MEANING[info.mode] || info.mode],
  ];
  if (hosted) facts.push(["Project", placeText(placeInfo(view.place))]);
  if (info.pause_reason) facts.push(["Paused", info.pause_reason]);
  const parts = [statusPill(info.status), detailsButton(facts)];
  if (view.detail.skill_changed) {
    const changed = element("span", "skill changed", "pill state-now");
    changed.title = "The skill changed after this run started. The graph shows the skill as the run saw it.";
    parts.push(changed);
  }
  parts.push(element("span", null, "spacer"));
  // A run that entered no child skill has nothing to collapse.
  if (view.detail.canvas?.child_frames.length) parts.push(view.parts.collapseToggle);
  const skillLink = element("a", "Skill graph", "tool");
  skillLink.href = skillHref(info.skill_id);
  skillLink.title = `See the skill ${info.skill_id} as it is now in .pskill/skills/, without this run.`;
  parts.push(skillLink);
  if (UNFINISHED.includes(info.status)) parts.push(button("Cancel run", cancelOpenRun, "tool danger"));
  else parts.push(button("Delete run", deleteOpenRun, "tool danger"));
  status.replaceChildren(...parts);
}

// The facts of the shown run or skill, behind one small button: they matter now and then, not all the time.
// A click opens a card under the button. It closes on a click outside or on Escape (a native popover).
function detailsButton(facts) {
  const wrap = element("span", null, "details");
  const press = element("button", "i", "tool details-button");
  press.type = "button";
  press.setAttribute("aria-label", "Details");
  press.title = "Details";
  const card = element("dl", null, "details-card");
  card.popover = "auto";
  for (const [name, value] of facts) card.append(element("dt", name), element("dd", value));
  press.addEventListener("click", () => {
    const box = press.getBoundingClientRect();
    card.style.top = `${box.bottom + 6}px`;
    card.style.left = `${Math.max(8, Math.min(box.left, innerWidth - 360))}px`;
    card.togglePopover();
  });
  wrap.append(press, card);
  return wrap;
}

// --- cancelling and deleting runs ------------------------------------------------------------------

// Cancel or delete one run. It returns the reason when the runner refuses, else null.
async function runAction(place, runId, action) {
  const { ok, data } = await apiRequest(`/api/runs/${encodeURIComponent(runId)}/${action}`, { place, method: "POST", body: "{}" });
  return ok ? null : [].concat(data.error).join("\n");
}

async function cancelOpenRun() {
  const runId = view.detail.info.run_id;
  const question = `Cancel the run ${runId}? It cannot go on afterwards. The agent learns it at its next pskill command.`;
  if (!window.confirm(question)) return;
  const refusal = await runAction(view.place, runId, "cancel");
  if (refusal) window.alert(`Not cancelled:\n${refusal}`);
  view.detailText = null;
  render();
}

async function deleteOpenRun() {
  const runId = view.detail.info.run_id;
  if (!window.confirm(`Delete the run ${runId}? Its folder .pskill/runs/${runId} goes for good.`)) return;
  const refusal = await runAction(view.place, runId, "delete");
  if (refusal) window.alert(`Not deleted:\n${refusal}`);
  else location.hash = "#/";
}

// Delete finished runs, one by one, for cleanup. The page lists the runs that the runner refused.
async function deleteRuns(runs) {
  const question = `Delete these ${runs.length} finished runs? Their folders in .pskill/runs/ go for good. The unfinished runs stay.`;
  if (!window.confirm(question)) return;
  const refusals = [];
  for (const run of runs) {
    const refusal = await runAction(run.place, run.run_id, "delete");
    if (refusal) refusals.push(`${run.run_id}: ${refusal}`);
  }
  if (refusals.length) window.alert(`Not deleted:\n${refusals.join("\n")}`);
  view.detailText = null;
  render();
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
  const current = canvasData()?.current;
  const stepNode = upToStep.length ? upToStep[upToStep.length - 1].node : null;
  const stepNodeState = atEnd ? (current ? current.state : "done") : "now";
  // A step in a collapsed child skill shows on its call block.
  return { visited, taken, labels, taskStates, stepNode, canvasStepNode: nodeOnCanvas(stepNode), stepNodeState };
}

// A task node: blue when done, red after a rejected answer, orange while open at the step, else grey.
function taskNodeState(nodeInfo, state) {
  const taskState = state.taskStates[nodeInfo.id] || "open";
  if (taskState === "done") return "done";
  if (taskState === "rejected") return "failed";
  return nodeInfo.parent === state.stepNode && state.stepNodeState === "now" ? "now" : "unvisited";
}

// The state of a node: on the canvas, or in the side panel (which can show a block of a collapsed child skill).
function nodeState(node, state) {
  if (isSkillScreen()) return "plain";
  const nodeInfo = view.detail.canvas?.nodes.find((item) => item.id === node);
  if (nodeInfo && nodeInfo.kind === "task") return taskNodeState(nodeInfo, state);
  if (node === state.stepNode || node === state.canvasStepNode) return state.stepNodeState;
  return state.visited.has(node) || node === canvasData()?.start ? "done" : "unvisited";
}

// --- the run screen: the canvas ---------------------------------------------------------------

async function drawCanvas() {
  if (view.rendering) {
    view.renderAgain = true;
    return;
  }
  view.rendering = true;
  try {
    if (isSkillScreen() && !canvasData()) {
      drawLoadError();
    } else if (!window.mermaid || !canvasData()) {
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
  const data = canvasData();
  const state = stepState();
  let source = data.template;
  for (const node of data.nodes) source = source.replace(node.token, () => state.labels[node.id] || data.labels[node.id]);
  for (const frame of data.frames || []) source = source.replace(frame.token, () => data.labels[frame.id]);
  const mainEdges = new Set(data.main_edges);
  const layout = await loadElkLayout();
  straightEdges = mainEdges;
  await document.fonts.ready; // Mermaid measures the labels, so the fonts must be there first
  const renderId = `canvas-${++view.renderCount}`;
  window.mermaid.initialize({
    startOnLoad: false,
    securityLevel: "strict",
    layout,
    elk: { nodePlacementStrategy: "NETWORK_SIMPLEX" }, // the placement that reads each edge's straightness
    theme: "base",
    themeVariables: { fontFamily: "Manrope, system-ui, sans-serif", fontSize: "13px" },
    flowchart: { htmlLabels: true, curve: "basis", nodeSpacing: 34, rankSpacing: 46, padding: 14, wrappingWidth: 320 },
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
    addSelectionRing(group);
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
    if (path) path.dataset.edge = edge.id; // for the exit cards of the panel
    path?.classList.toggle("is-main", mainEdges.has(edge.id));
    label?.classList.toggle("is-side", !mainEdges.has(edge.id));
    const references = referencedNodes(edge.when, edge.source); // the blocks that the edge's condition reads
    for (const part of references.length ? [label, path] : []) {
      part?.addEventListener("mouseenter", () => highlightReferences(references, true));
      part?.addEventListener("mouseleave", () => highlightReferences(references, false));
    }
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
  markSelection();
  for (const cluster of svgNode.querySelectorAll("g.cluster")) {
    const frame = (data.frames || []).find((item) => cluster.id.endsWith(`-${item.id}`));
    if (frame) wireCallFrame(cluster, frame);
    else addHint(cluster, cluster.id.endsWith("_TASKS") ? TASK_FRAME_HINT : CHILD_SKILL_HINT);
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

// ELK (index.html maps "mermaid-layout-elk" to its pinned files) lays the graph out top to bottom. Each
// main-line edge asks it to stay straight, so the usual way to a succeeded end is one straight column.
// It resolves to the layout name for Mermaid: Mermaid's own "dagre" when ELK does not load (offline).
const STRAIGHT_EDGE = { "elk.layered.priority.straightness": 100, "elk.layered.priority.direction": 100 };
let straightEdges = new Set(); // the main-line edges of the graph that Mermaid lays out next
let elkLayout = null;

function loadElkLayout() {
  elkLayout ??= import("mermaid-layout-elk").then(
    (module) => {
      const elk = module.default.find((layout) => layout.name === "elk");
      // Mermaid's ELK adapter copies each edge's fields into ELK, layoutOptions included.
      const loader = async () => {
        const engine = await elk.loader();
        const render = (data, ...rest) => {
          for (const edge of data.edges) if (straightEdges.has(edge.id)) edge.layoutOptions = STRAIGHT_EDGE;
          return engine.render(data, ...rest);
        };
        return { ...engine, render };
      };
      window.mermaid.registerLayoutLoaders([{ name: "elk-main-line", loader, algorithm: "elk.layered" }]);
      return "elk-main-line";
    },
    () => "dagre",
  );
  return elkLayout;
}

// On the skill screen, a call block is the frame of its child skill: the frame stands for the call block.
// Its title moves to the top left, and a click on the title or on the frame's empty area selects the call block.
function wireCallFrame(cluster, frame) {
  cluster.dataset.node = frame.node;
  cluster.classList.add("is-call-frame");
  const nodeInfo = canvasData().nodes.find((item) => item.id === frame.node);
  addHint(cluster, `${nodeInfo.hint}\n\nThe frame holds the child skill. Click the frame to see the call block.`);
  cluster.addEventListener("click", () => view.dragEnded || selectNode(frame.node));
  const rect = cluster.querySelector(":scope > rect");
  const label = cluster.querySelector(":scope > .cluster-label");
  if (!rect || !label) return;
  label.setAttribute("transform", `translate(${rect.x.baseVal.value + 14}, ${rect.y.baseVal.value + 10})`);
  // Mermaid sized the title box for a centered title: give it the frame's width, so the skill name is not cut.
  const box = label.querySelector("foreignObject");
  if (box) box.setAttribute("width", String(Math.max(box.width.baseVal.value, rect.width.baseVal.value - 28)));
}

function drawStepList() {
  const state = stepState();
  const list = element("div", null, "step-list");
  list.append(element("p", "Graph unavailable offline (Mermaid did not load). The steps so far:", "note"));
  rows()
    .slice(0, view.step + 1)
    .forEach((row, index) => {
      const card = button(null, () => selectNode(row.node, index), "step-card");
      card.dataset.node = row.node;
      const stateName = index === view.step ? state.stepNodeState : "done";
      card.classList.add(`is-${stateName}`);
      card.append(element("strong", row.block), blockType(row.block_type, row.summary));
      list.append(card);
    });
  view.parts.layer.replaceChildren();
  view.parts.canvas.querySelector(".step-list")?.remove();
  view.parts.canvas.append(list);
  view.parts.note.textContent = "";
  markSelection();
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
  centerOnNode(stepState().canvasStepNode, targetScale);
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
    if (event.button !== 0 || event.target.closest(".step-list, .canvas-tools")) return;
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

function savedCollapsed() {
  try {
    return localStorage.getItem(EXPANDED_KEY) !== "true";
  } catch {
    return true; // the browser blocks site data
  }
}

function saveCollapsed(collapsed) {
  try {
    localStorage.setItem(EXPANDED_KEY, String(!collapsed));
  } catch {
    // the browser blocks site data: the choice lasts until the reload
  }
}

function savedRunCollapsed() {
  try {
    return localStorage.getItem(RUN_COLLAPSED_KEY) === "true";
  } catch {
    return false; // the browser blocks site data
  }
}

function saveRunCollapsed(collapsed) {
  try {
    localStorage.setItem(RUN_COLLAPSED_KEY, String(collapsed));
  } catch {
    // the browser blocks site data: the choice lasts until the reload
  }
}

// Collapse or expand the child skills. On the skill screen, a block of a child skill that the panel shows gives
// way to the call block that holds it, because a collapsed canvas has no node for it. The run screen's panel
// keeps the block, and the canvas rings its call block.
function toggleChildSkills() {
  if (isSkillScreen()) {
    view.collapsed = !view.collapsed;
    saveCollapsed(view.collapsed);
    if (view.collapsed && view.selectedNode) view.selectedNode = callBlockOnTop(view.selectedNode);
  } else {
    view.runCollapsed = !view.runCollapsed;
    saveRunCollapsed(view.runCollapsed);
  }
  view.parts.collapseToggle.setAttribute("aria-checked", String(childSkillsCollapsed()));
  view.fitted = false;
  drawPanel();
  drawCanvas();
}

// The block of the skill itself that holds a node: the node, or the call block at the top of its child frames.
// The skill canvas lists its child frames as `frames`, the run canvas as `child_frames`.
function callBlockOnTop(node) {
  const frames = view.detail.canvas?.frames ?? view.detail.canvas?.child_frames ?? [];
  let frame;
  while ((frame = frames.find((item) => node.startsWith(`${item.id}_`)))) node = frame.node;
  return node;
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
  markSelection();
  drawPanel();
}

function selectTask(task) {
  view.selectedTask = task;
  markSelection();
  drawPanel();
}

// The node that the side panel shows: the clicked node or, on the run screen, the current step.
function shownNode() {
  if (view.selectedNode || isSkillScreen()) return view.selectedNode;
  return view.selectedRow === null ? stepState().stepNode : null;
}

// The ring of the node that the side panel shows (style.css shows it on .is-selected): a rounded rectangle
// around the node's box, RING_GAP away from its border line. Its corners follow the box's corners, so the ring
// has one width everywhere.
const RING_GAP = 4;

function addSelectionRing(group) {
  const box = group.querySelector(":scope > rect");
  if (!box) return; // the start dot: it is never selected
  const x = box.x.baseVal.value - RING_GAP;
  const y = box.y.baseVal.value - RING_GAP;
  const width = box.width.baseVal.value + 2 * RING_GAP;
  const height = box.height.baseVal.value + 2 * RING_GAP;
  const r = Math.min((parseFloat(getComputedStyle(box).rx) || 0) + RING_GAP, width / 2, height / 2);
  const ring = document.createElementNS("http://www.w3.org/2000/svg", "path");
  ring.setAttribute("class", "selection-ring");
  ring.setAttribute(
    "d",
    `M${x + r},${y}H${x + width - r}A${r},${r} 0 0 1 ${x + width},${y + r}V${y + height - r}` +
      `A${r},${r} 0 0 1 ${x + width - r},${y + height}H${x + r}A${r},${r} 0 0 1 ${x},${y + height - r}` +
      `V${y + r}A${r},${r} 0 0 1 ${x + r},${y}Z`,
  );
  box.before(ring);
}

// Ring the shown node, and the task node of the shown task, on the canvas and in the offline card list.
function markSelection() {
  const node = nodeOnCanvas(shownNode());
  const taskNode = canvasData()?.nodes.find(
    (item) => item.kind === "task" && item.parent === node && item.task === view.selectedTask,
  )?.id;
  for (const item of view.parts.canvas.querySelectorAll("g.node, g.cluster, .step-card")) {
    item.classList.toggle("is-selected", Boolean(node) && [node, taskNode].includes(item.dataset.node));
  }
}

function drawPanel() {
  // A redraw removes the card or the reference under the pointer before its mouseleave, so clear its highlight here.
  for (const item of view.parts.canvas.querySelectorAll(".is-hovered, .is-exit-target, .is-referenced")) {
    item.classList.remove("is-hovered", "is-exit-target", "is-referenced");
  }
  if (isSkillScreen()) drawSkillPanel();
  else drawRunPanel();
  linkReferences(view.parts.panel, shownNode());
  addCloseButton();
}

// The close button at the top right of the panel, while the user has a block or a step selected.
// It clears the selection: the skill screen then shows the skill, and the run screen the current step.
function addCloseButton() {
  if (view.selectedNode === null && (isSkillScreen() || view.selectedRow === null)) return;
  const close = button("×", () => selectNode(null), "panel-close");
  close.title = isSkillScreen() ? "Close this block (Esc)" : "Close, and show the current step again (Esc)";
  close.setAttribute("aria-label", close.title);
  view.parts.panel.prepend(close);
}

function drawRunPanel() {
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
  // The full canvas: the panel can show a block of a collapsed child skill.
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
  const meaningText = nodeInfo ? `: ${nodeInfo.type_meaning}` : "";
  head.append(title, blockType(type, `${type}${skillText}${meaningText}`));
  if (nodeInfo) appendBlockIntro(head, nodeInfo);
  const parts = [head];
  if (nodeOnCanvas(node) !== node) parts.push(collapsedChildNote(nodeInfo, nodeOnCanvas(node)));
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

// A block of a child skill that the collapsed canvas draws inside its call block.
function collapsedChildNote(nodeInfo, callNode) {
  const note = element("p", `A block of the child skill ${nodeInfo?.skill_id ?? ""}. The canvas shows it inside the call block `, "note");
  const callBlock = view.detail.canvas.nodes.find((item) => item.id === callNode)?.block ?? callNode;
  note.append(blockRef(callBlock, callNode, `The call block ${callBlock}.`), ". ");
  note.append(button("Expand sub-skills", toggleChildSkills, "tool"));
  return note;
}

// --- the skill screen: the side panel --------------------------------------------------------------

function drawSkillPanel() {
  const node = view.selectedNode;
  // A block of a child skill has its details by node: its name can be the name of a block of this skill.
  const child = node ? view.detail.child_blocks?.[node] : undefined;
  const details = child ?? view.detail.blocks[node ? blockOfNode(node) : ""];
  if (child) {
    view.parts.panel.replaceChildren(childSkillNote(child), ...blockSections(child));
  } else if (view.editing && details) {
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

// A block of a child skill shows here read-only. Its own skill screen can edit it.
function childSkillNote(details) {
  const note = element("p", `A block of the child skill ${details.skill_id}, which the call block `, "note");
  const callNode = canvasData().frames.find((frame) => details.node.startsWith(`${frame.id}_`))?.node;
  note.append(callNode ? blockRef(details.called_by, callNode, `The call block ${details.called_by}.`) : details.called_by, " runs. ");
  note.append(entityLink(`Open ${details.skill_id}`, skillHref(details.skill_id)));
  return note;
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
  task_name: "Task name (a {{ }} value per item)",
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
  head.append(element("h2", block), typeLine(details.type));
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
    fields.append(editRow(EDIT_LABELS[key] || key, control.node, key));
  }
  const proseKey = keys.includes("report") ? "report" : keys.includes("instruction") ? "instruction" : null;
  if (proseKey) {
    const area = element("textarea", details.instruction ?? values[proseKey] ?? "", "edit-text");
    area.rows = 8;
    if (details.instruction_file) {
      readers.instruction_text = () => area.value;
      fields.append(editRow(`${proseKey === "report" ? "Report" : "Instruction"} (the file ${details.instruction_file})`, area, proseKey));
    } else {
      readers[proseKey] = () => area.value || null;
      fields.append(editRow(proseKey === "report" ? "Report (what the agent tells the user)" : "Instruction", area, proseKey));
    }
  }
  if (keys.includes("next")) {
    // A decision with choices has one edge list per choice; every other block has one edge list.
    const hasChoices = choicesEditor && (choicesEditor.read() || (values.next && typeof values.next === "object" && !Array.isArray(values.next)));
    const nextEditor = hasChoices ? choiceNextEditor(values.next, choicesEditor) : edgeListEditor(toEdges(values.next));
    readers.next = nextEditor.read;
    fields.append(editRow(EDIT_LABELS.next, nextEditor.node, "next"));
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

// A div, not a label: a label passes a click on its text to the first button in it, the "?" button.
function editRow(label, control, field) {
  const row = element("div", null, "edit-row");
  row.append(FIELD_HELP[field] ? withHelp("span", label, field, "edit-label") : element("span", label, "edit-label"), control);
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
  const { ok, data: body } = await apiRequest(`/api/skills/${encodeURIComponent(view.skillId)}/edit`, {
    method: "POST",
    body: JSON.stringify(request),
  });
  if (!ok) {
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
  return canvasData()?.nodes.find((item) => item.id === node)?.block ?? "";
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
  parts.push(section(withHelp("h3", "Goal", "goal"), element("p", skill.goal)));
  parts.push(problemsSection());
  if (skill.inputs.length) parts.push(section(withHelp("h3", "Inputs", "skill_inputs"), fieldList(skill.inputs)));
  if (skill.outputs.length) parts.push(section(withHelp("h3", "Outputs", "skill_outputs"), fieldList(skill.outputs)));
  parts.push(element("p", "Click a block on the canvas to see its instruction, its fields, and where it can go.", "note"));
  return parts;
}

function problemsSection() {
  const problems = view.detail.problems;
  if (!problems.length) return section("Checks", element("p", "pskill validate finds no problem in this skill.", "note"));
  const list = element("ul", null, "problems");
  for (const problem of problems) {
    const item = element("li", null, `problem is-${problem.level}`);
    const block = problem.location.match(/^blocks\.([a-z0-9_]+)/)?.[1];
    const node = block ? nodeInFrameOf(null, block) : null;
    const location = node ? blockRef(problem.location, node, `The block ${block}.`) : problem.location;
    item.append(element("strong", `${problem.level} `), location, `: ${problem.message}`);
    list.append(item);
  }
  return section(`Checks · ${problems.length}`, list);
}

function blockSections(details) {
  const block = blockOfNode(view.selectedNode);
  const head = element("div", null, "panel-head");
  const title = element("div", null, "panel-title");
  title.append(element("h2", block));
  head.append(title, typeLine(details.type, details.type_meaning));
  appendBlockIntro(head, details);
  const parts = [head];
  if (details.facts.length) {
    const facts = element("dl", null, "facts");
    for (const [name, value] of details.facts) {
      const term = FACT_FIELDS[name] ? withHelp("dt", name, FACT_FIELDS[name]) : element("dt", name);
      const definition = element("dd");
      if (name === "skill" && details.child_skill) definition.append(entityLink(value, skillHref(details.child_skill)));
      else if (name === "agent" && details.agents.includes(value)) definition.append(entityLink(value, agentHref(value)));
      else definition.textContent = value;
      facts.append(term, definition);
    }
    parts.push(facts);
  }
  // An agent name from a fixed list ("{{ item.agent }}"): one link per agent that the list names.
  const listedAgents = details.agents.filter((name) => !details.facts.some(([fact, value]) => fact === "agent" && value === name));
  if (listedAgents.length) {
    const links = element("div", null, "entity-links");
    links.append(...listedAgents.map((name) => entityLink(name, agentHref(name))));
    parts.push(section(withHelp("h3", "Agents", "agent"), links));
  }
  if (details.for_each_items.length) parts.push(forEachItems(details));
  if (details.command) parts.push(section(withHelp("h3", "Command", "run"), element("pre", details.command.join(" "))));
  if (details.input != null) parts.push(section(withHelp("h3", "Input (stdin)", "input"), element("pre", details.input)));
  for (const file of details.script_files) {
    const note = element("p", `The command runs ${file.path}. Change it in your code editor.`, "note");
    parts.push(section("Script file", note, folded(element("pre", file.text), `${block}:script:${file.path}`)));
  }
  if (details.instruction !== null) {
    const title = details.type === "end" ? "Report" : "Instruction";
    const source = details.instruction_file ? `From ${details.instruction_file}. ` : "";
    parts.push(
      section(
        withHelp("h3", title, details.type === "end" ? "report" : "instruction"),
        element("p", `${source}Values in {{ }} are filled in during a run.`, "note"),
        folded(markdown(details.instruction), `${block}:instruction`),
      ),
    );
  } else if (details.instruction_file) {
    const field = details.type === "end" ? "report" : "instruction";
    const heading = withHelp("h3", field === "report" ? "Report" : "Instruction", field);
    parts.push(section(heading, element("p", `The file ${details.instruction_file} is missing.`, "errors")));
  }
  if (details.choices.length) {
    const list = element("dl", null, "facts");
    for (const choice of details.choices) list.append(element("dt", choice.choice), element("dd", choice.meaning));
    parts.push(section(withHelp("h3", "Choices", "choices"), list));
  }
  if (details.fields.length) parts.push(section(withHelp("h3", "Output: what the answer must hold", "output"), fieldList(details.fields)));
  if (details.inputs.length) parts.push(section(withHelp("h3", "Inputs to the child skill", "inputs"), valueList(details.inputs)));
  if (details.outputs.length) parts.push(section(withHelp("h3", "Outputs of the skill", "outputs"), valueList(details.outputs)));
  if (details.exits.length) parts.push(section(withHelp("h3", "Where it can go", "next"), exitsOf(details.node)));
  return parts;
}

// One card per item of a fixed for_each list: its name as the title, its other fields, then its when apart.
function forEachItems(details) {
  const list = element("ul", null, "fields");
  details.for_each_items.forEach((item, index) => {
    const card = element("li", null, "field");
    const name = item.fields.find(([key]) => key === "name");
    const head = element("div", null, "field-head");
    head.append(element("code", name ? name[1] : `item ${index}`, "field-name"));
    if (item.when) head.append(element("span", "only when needed", "chip"));
    card.append(head);
    const rest = item.fields.filter(([key]) => key !== "name");
    if (rest.length) {
      const facts = element("dl", null, "facts");
      for (const [key, value] of rest) {
        const definition = element("dd");
        if (key === "agent" && details.agents.includes(value)) definition.append(entityLink(value, agentHref(value)));
        else definition.textContent = value;
        facts.append(element("dt", key), definition);
      }
      card.append(facts);
    }
    if (item.when) {
      const when = element("div", null, "item-when");
      when.append(element("span", "Runs only when", "note"), element("code", item.when));
      card.append(when);
    }
    list.append(card);
  });
  const note = element("p", "Each item starts one task. An item with a when starts it only when its when is true.", "note");
  return section(withHelp("h3", `Items · ${details.for_each_items.length}`, "for_each"), note, list);
}

// One card per field: the name and its chips on the first line, the description below, then the nested fields.
function fieldList(fields) {
  const list = element("ul", null, "fields");
  for (const field of fields) {
    const item = element("li", null, "field");
    const head = element("div", null, "field-head");
    // With the nested fields listed below, "object with a, b" says nothing more than "object".
    const type = field.children.length ? field.type.replace(/ with .*$/, "") : field.type;
    head.append(element("code", field.name, "field-name"), element("span", type, "chip"));
    if (field.optional) head.append(element("span", "optional", "chip"));
    if (field.default !== null) head.append(element("span", `default ${JSON.stringify(field.default)}`, "chip"));
    item.append(head);
    if (field.description) item.append(element("p", field.description, "field-description"));
    if (field.values) {
      const values = element("div", null, "field-values");
      values.append(element("span", "One of", "note"), ...field.values.map((value) => element("code", String(value), "chip is-value")));
      item.append(values);
    }
    if (field.children.length) item.append(fieldList(field.children));
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
    card.dataset.node = details.node;
    card.append(element("strong", block), blockType(details.type));
    list.append(card);
  }
  view.parts.layer.replaceChildren();
  view.parts.canvas.querySelector(".step-list")?.remove();
  view.parts.canvas.append(list);
  view.parts.note.textContent = "";
  markSelection();
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

// The title is text, or a heading node (for example one with a "?" button).
function section(title, ...content) {
  const node = element("section");
  node.append(typeof title === "string" ? element("h3", title) : title, ...content);
  return node;
}

function visitPicker(visits, chosen) {
  const picker = element("div", null, "visits");
  visits.forEach((item, position) => {
    const name = item.row.tasks.find((task) => task.task === item.row.task)?.name;
    const taskLabel = name ? `Task ${item.row.task} · ${name}` : `Task ${item.row.task}`;
    const label = item.row.task !== null && item.row.task !== undefined ? taskLabel : `Visit ${position + 1}`;
    const chip = button(label, () => selectNode(item.row.node, item.index));
    chip.setAttribute("aria-pressed", String(item === chosen));
    picker.append(chip);
  });
  return section("Visits", picker);
}

// One card per edge out of a node: the target, a tag for when the run takes it, and the condition.
// A hover lights up the edge and its target on the canvas, and a click opens the target.
function exitsOf(node) {
  const list = element("div", null, "exits");
  for (const edge of canvasData().edges.filter((item) => item.source === node && item.kind !== "tasks")) {
    const card = button(null, () => {
      highlightExit(edge, false);
      selectNode(edge.target);
    }, "exit");
    card.title = edge.hint;
    const [tag, tagKind] = exitTag(edge);
    const head = element("span", null, "exit-head");
    head.append(element("span", "→", "exit-arrow"), element("strong", edge.to_block), element("span", tag, `chip is-${tagKind}`));
    card.append(head);
    if (edge.when) card.append(element("code", edge.when, "exit-condition"));
    else if (edge.kind !== "next" || edge.fallback) card.append(element("span", edge.hint, "exit-text"));
    card.addEventListener("mouseenter", () => highlightExit(edge, true));
    card.addEventListener("mouseleave", () => highlightExit(edge, false));
    list.append(card);
  }
  return list;
}

// The tag of an exit card, and its color class: when the run takes the edge, in one or two words.
function exitTag(edge) {
  if (edge.kind === "visit_cap") return ["visit cap", "visit-cap"];
  if (edge.choice !== null) return [`choice "${edge.choice}"`, "choice"];
  if (edge.when) return ["if", "if"];
  if (edge.fallback) return ["otherwise", "otherwise"];
  return ["always", "always"];
}

function highlightExit(edge, on) {
  const { layer } = view.parts;
  layer.querySelector(`path[data-edge="${CSS.escape(edge.id)}"]`)?.classList.toggle("is-hovered", on);
  layer.querySelector(`g.label[data-id="${CSS.escape(edge.id)}"]`)?.classList.toggle("is-hovered", on);
  const target = CSS.escape(edge.target);
  layer.querySelector(`g.node[data-node="${target}"], g.cluster[data-node="${target}"]`)?.classList.toggle("is-exit-target", on);
}

// --- references: a text that names a block lights up that block on the canvas ----------------------

// The node of a block in the canvas frame of `fromNode` (f<frame>_<block>), or null when the canvas has none.
// With no `fromNode`, the frame is the skill itself.
function nodeInFrameOf(fromNode, block) {
  const node = `${fromNode?.match(/^f\d+_/)?.[0] ?? "f0_"}${block}`;
  return canvasData()?.nodes.some((item) => item.id === node) ? node : null;
}

// The nodes that a value reads through steps.<block> or history.<block>.
function referencedNodes(text, fromNode) {
  return [...(text || "").matchAll(BLOCK_REFERENCE)].map((match) => nodeInFrameOf(fromNode, match[2])).filter(Boolean);
}

// Light up the nodes, or the call frames, on the canvas and in the offline card list.
function highlightReferences(nodes, on) {
  for (const node of nodes) {
    for (const item of view.parts.canvas.querySelectorAll(`[data-node="${CSS.escape(node)}"]`)) {
      item.classList.toggle("is-referenced", on);
    }
  }
}

// A block name in the panel: a hover lights up its node, and a click shows it.
function blockRef(text, node, hint) {
  const ref = element("span", text, "block-ref");
  ref.title = `${hint}\nClick to see this ${isSkillScreen() ? "block" : "step"}.`;
  ref.addEventListener("mouseenter", () => highlightReferences([node], true));
  ref.addEventListener("mouseleave", () => highlightReferences([node], false));
  ref.addEventListener("click", (event) => {
    event.preventDefault();
    event.stopPropagation(); // inside an exit card, the click is for the named block, not for the exit
    highlightReferences([node], false);
    selectNode(node);
  });
  return ref;
}

// Turn each steps.<block> and history.<block> in the text of `root` into a block reference of the same frame.
function linkReferences(root, fromNode) {
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  const texts = [];
  while (walker.nextNode()) texts.push(walker.currentNode);
  for (const text of texts) {
    if (text.parentElement.closest(".block-ref, textarea, select")) continue;
    const parts = [];
    let end = 0;
    for (const match of text.data.matchAll(BLOCK_REFERENCE)) {
      const node = nodeInFrameOf(fromNode, match[2]);
      if (!node) continue;
      const hint = match[1] === "steps" ? `The latest output of ${match[2]}.` : `Every output of ${match[2]}, oldest first.`;
      parts.push(text.data.slice(end, match.index), blockRef(match[0], node, hint));
      end = match.index + match[0].length;
    }
    if (parts.length) text.replaceWith(...parts, text.data.slice(end));
  }
}

function rowSections(row) {
  const facts = element("dl", null, "facts");
  // A fact that starts with a block name of the same frame: the name lights up that block on the canvas.
  const addFact = (name, value, hint, block = null) => {
    const term = element("dt", name);
    term.title = hint;
    const definition = element("dd", value);
    const node = block && row.node && value.startsWith(block) ? nodeInFrameOf(row.node, block) : null;
    if (node) definition.replaceChildren(blockRef(block, node, `The step ${block}.`), value.slice(block.length));
    facts.append(term, definition);
  };
  addFact("Arrived from", row.arrival, "The step before this one, and the edge condition that led here.", row.from);
  addFact("Started", formatTime(row.ts), "When the run entered this step.");
  addFact("Duration", row.duration_ms === null ? "not finished" : formatDuration(row.duration_ms), "From the start of this step to its accepted answer.");
  if (row.decided_by) addFact("Decided by", row.decided_by, "Who gave the accepted answer: the agent, a human, or the runner itself.");
  if (row.left_by) addFact("Went next to", `${row.left_by.to}${row.left_by.label ? ` (${row.left_by.label})` : ""}`, "The step after this one, and the edge condition that led there.", row.left_by.to);
  const parts = [facts];
  if (row.block_type === "script") return [...parts, ...scriptSections(row)];
  if (row.packet) parts.push(section(row.input_title, folded(markdown(row.packet), `${row.seq}:input`)));
  if (row.tasks.length) parts.push(tasksSection(row));
  if (row.skipped_tasks.length) parts.push(skippedSection(row));
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
    parts.push(section(row.input_title, element("pre", `$ ${script.argv.join(" ")}`)));
    if (script.input != null) {
      const sent = typeof script.input === "string" ? element("pre", script.input) : folded(jsonTree(script.input, `${key}:input`), `${key}:input`);
      parts.push(section("Stdin", sent));
    }
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

function skippedSection(row) {
  const list = element("ul");
  for (const skipped of row.skipped_tasks) {
    const item = element("li");
    item.append(element("strong", skipped.name ?? "An unnamed item"), " was skipped: ", element("code", skipped.when), " was false.");
    list.append(item);
  }
  const note = element("p", "These items of the for_each list started no task, because their when was false.", "note");
  return section(`Skipped · ${row.skipped_tasks.length}`, note, list);
}

function taskDetail(task, seq) {
  const box = element("div", null, "task-detail");
  const name = task.name ? ` · ${task.name}` : "";
  box.append(element("h4", `Task ${task.task}${name} · ${TASK_STATE_TEXT[task.state]}`));
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

async function showRun(place, runId) {
  const key = `${place}/${runId}`;
  view.place = place;
  if (view.runId !== key || !view.parts) {
    view.runId = key;
    view.detail = null;
    view.detailText = null;
    view.fitted = false;
    view.stepAtEnd = true;
    view.selectedNode = null;
    view.openFolds.clear();
    buildRunScreen();
  }
  const [detail, overview] = await Promise.all([
    apiJson(`/api/runs/${encodeURIComponent(runId)}`, place),
    apiJson("/api/runs", hosted ? ALL_PLACES : LOCAL_PLACE).catch(() => ({ runs: [] })),
  ]);
  if (view.screen !== "run" || view.runId !== key) return; // the user moved on while it loaded
  for (const run of overview.runs) run.place ??= LOCAL_PLACE;
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
  if (UNFINISHED.includes(detail.info.status)) pollAgain(POLL_MS);
}

// --- the skill screen: loading ---------------------------------------------------------------------

async function showSkill(place, skillId) {
  const changedPlace = view.place !== place;
  view.place = place;
  if (view.skillId !== skillId || changedPlace || !view.parts) {
    view.skillId = skillId;
    view.detail = null;
    view.detailText = null;
    view.fitted = false;
    view.selectedNode = null;
    view.openFolds.clear();
    buildSkillScreen();
  }
  const [detail, overview] = await Promise.all([
    apiJson(`/api/skills/${encodeURIComponent(skillId)}`, place),
    apiJson("/api/skills", place).catch(() => ({ skills: [] })),
  ]);
  if (view.screen !== "skill" || view.skillId !== skillId || view.place !== place) return; // the user moved on
  const text = JSON.stringify(detail);
  if (text === view.detailText) return;
  view.detailText = text;
  view.detail = detail;
  view.skills = overview.skills;
  drawSkillTopbar();
  drawPanel();
  await drawCanvas();
}

// --- the folders screen (hosted viewer only) --------------------------------------------------------

function showFolders() {
  const page = element("main", null, "runs-page");
  const actions = element("div", null, "filters");
  actions.append(button("Add a folder", addFolder, "tool primary"), button("Look again", lookAgain));
  page.append(element("h1", "Folders"), element("p", FOLDERS_INTRO, "note"), actions);
  const sources = hosted.sourceList();
  if (!sources.length) page.append(element("p", "No folder yet.", "note"));
  for (const source of sources) page.append(folderCard(source));
  app.className = "";
  app.replaceChildren(topbar(), page, ...versionNote());
}

// One picked folder: its pattern, and the projects found in it.
function folderCard(source) {
  const card = element("section", null, "folder-card");
  const head = element("div", null, "run-card-head");
  head.append(element("strong", source.name));
  if (!source.granted) head.append(element("span", "needs your permission again", "pill state-waiting"));
  head.append(
    button(
      "Remove",
      async () => {
        await hosted.removeSource(source.id);
        showFolders();
      },
      "tool small danger",
    ),
  );
  const pattern = element("input", null, "edit-input mono");
  pattern.value = source.pattern;
  pattern.placeholder = "Every project (or a pattern, such as monorepo-clone-\\d+)";
  pattern.setAttribute("aria-label", `Pattern for ${source.name}`);
  pattern.addEventListener("change", async () => {
    await hosted.setPattern(source.id, pattern.value.trim());
    showFolders();
  });
  const patternRow = element("div", null, "edit-row");
  patternRow.append(element("span", "Only the projects whose path matches this regular expression", "edit-label"), pattern);
  card.append(head, patternRow);
  if (source.patternError) card.append(element("p", `The pattern is not valid, so every project shows: ${source.patternError}`, "errors-text"));
  const list = element("ul", null, "folder-places");
  for (const place of source.places) {
    const item = element("li");
    item.append(entityLink(placeText(place), contentHref(place.id)));
    list.append(item);
  }
  const count = source.places.length;
  card.append(element("p", count ? `${count} project${count === 1 ? "" : "s"} with .pskill:` : "No project with .pskill in this folder.", "note"));
  if (count) card.append(list);
  return card;
}

async function addFolder() {
  try {
    await hosted.addSource();
  } catch (error) {
    if (error.name !== "AbortError") window.alert(`The folder could not be added: ${error.message}`);
  }
  view.detailText = null;
  showFolders();
}

async function lookAgain() {
  await hosted.rescan();
  showFolders();
}

async function allowFolders() {
  await hosted.allowAccess();
  view.detailText = null;
  render();
}

// --- routing ----------------------------------------------------------------------------------

const SCREENS = { "": "runs", run: "run", content: "content", skill: "skill", agent: "agent", folders: "folders" };

function route() {
  try {
    const [name = "", ...rest] = location.hash.replace(/^#\/?/, "").split("/").map(decodeURIComponent);
    return { screen: SCREENS[name] ?? "runs", rest };
  } catch {
    return { screen: "runs", rest: [] }; // a broken address
  }
}

async function render() {
  clearTimeout(view.pollTimer);
  view.pollWaiting = false;
  view.pollAsked = false; // the screen calls pollAgain again while its run is live
  const { screen, rest } = route();
  if (screen !== view.screen) {
    view.parts = null; // another screen: build its layout again
    view.runId = null;
    view.skillId = null;
  }
  view.screen = screen;
  try {
    if (hosted && !(await hostedReady(screen))) return;
    if (screen === "run") await showRun(rest[0], rest[1]);
    else if (screen === "skill") await showSkill(rest[0], rest[1]);
    else if (screen === "agent") await showAgent(rest[0], rest[1]);
    else if (screen === "content") await showContent(rest[0]);
    else if (screen === "folders") showFolders();
    else await showRuns();
  } catch (error) {
    showMessage(`The viewer could not load the data: ${error.message}`, "errors");
  }
  view.refreshedAt = Date.now();
  view.live = view.pollAsked; // set at the end, so the live dot does not blink while a read runs
  drawRefreshButtons();
}

// On the hosted viewer, a screen with data needs a folder and Python first. False when the screen cannot show.
async function hostedReady(screen) {
  if (!hosted.supported()) {
    showMessage(UNSUPPORTED, "note");
    return false;
  }
  if (screen === "folders") return true;
  if (!hosted.sourceList().length) {
    location.replace("#/folders");
    return false;
  }
  if (!view.pythonReady) {
    showMessage(PYTHON_LOADING, "note");
    await hosted.startPython();
    view.pythonReady = true;
    view.version = (await apiJson("/api/version", ALL_PLACES)).version;
  }
  return true;
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
  if (!view.parts || ["INPUT", "SELECT", "TEXTAREA"].includes(event.target.tagName)) return;
  // Escape does what the panel's close button does. An open help dialog or Details card takes Escape for itself.
  if (event.key === "Escape" && !document.querySelector("dialog[open], :popover-open")) view.parts.panel.querySelector(".panel-close")?.click();
  if (view.screen !== "run") return;
  if (event.key === "ArrowRight") setStep(view.step + 1);
  else if (event.key === "ArrowLeft") setStep(view.step - 1);
});
// The local server answers /api/version. Without it (GitHub Pages), the page is the hosted viewer.
async function start() {
  try {
    const response = await fetch("/api/version", { cache: "no-store" });
    if (!response.ok) throw new Error(response.statusText);
    const info = await response.json();
    view.version = info.version;
    view.projectName = info.project;
  } catch {
    hosted = await import("./hosted.js");
    if (hosted.supported()) await hosted.load();
  }
  render();
  setInterval(tickRefresh, REFRESH_TICK_MS);
}

// A page that comes back into view: a live run asks again at once, and a due refresh runs.
document.addEventListener("visibilitychange", () => {
  if (document.visibilityState !== "visible") return;
  if (view.pollWaiting) render();
  else tickRefresh();
});

start();
