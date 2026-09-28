// The pskill viewer. It only draws what the local server returns (pskill_runner/viewer_data.py).
// Every text from a run goes into the page through textContent, never as HTML.

const UNFINISHED = ["active", "waiting_for_human", "paused"];
const POLL_MS = 1000;
const app = document.getElementById("app");
let pollTimer = null;
let selectedRow = 0;
let lastDrawnRun = null;

// --- small helpers ----------------------------------------------------------------------------

function element(tag, text, className) {
  const node = document.createElement(tag);
  if (text !== undefined && text !== null) node.textContent = String(text);
  if (className) node.className = className;
  return node;
}

function formatDuration(milliseconds) {
  if (milliseconds === null || milliseconds === undefined) return "-";
  if (milliseconds < 1000) return `${milliseconds} ms`;
  const seconds = Math.round(milliseconds / 1000);
  return seconds < 60 ? `${seconds} s` : `${Math.floor(seconds / 60)} min ${seconds % 60} s`;
}

function table(headers, rows) {
  const tableNode = element("table");
  const headRow = element("tr");
  headers.forEach((header) => headRow.append(element("th", header)));
  tableNode.append(headRow);
  rows.forEach((cells) => {
    const row = element("tr");
    cells.forEach((cell) => {
      const cellNode = element("td");
      cellNode.append(cell instanceof Node ? cell : document.createTextNode(String(cell)));
      row.append(cellNode);
    });
    tableNode.append(row);
  });
  return tableNode;
}

async function fetchJson(path) {
  const response = await fetch(path, { cache: "no-store" });
  if (!response.ok) throw new Error((await response.json()).error || response.statusText);
  return response.json();
}

// --- the runs screen ----------------------------------------------------------------------------

async function showRuns() {
  const overview = await fetchJson("/api/runs");
  const summaryRows = overview.summaries.map((summary) => [
    summary.skill_id,
    summary.runs,
    summary.success_rate === null ? "-" : `${Math.round(summary.success_rate * 100)} %`,
    formatDuration(summary.median_duration_ms),
  ]);
  const runRows = overview.runs.map((run) => {
    const link = element("a", run.run_id);
    link.href = `#/run/${run.run_id}`;
    return [link, run.skill_id, run.status, run.current_block || "-", run.harness, run.mode, run.created_at, formatDuration(run.duration_ms)];
  });
  app.replaceChildren(
    element("h2", "Skills"),
    table(["skill", "runs", "success rate", "median duration"], summaryRows),
    element("h2", "Runs"),
    overview.runs.length ? table(["run", "skill", "status", "block", "harness", "mode", "started", "duration"], runRows) : element("p", "No runs yet."),
  );
}

// --- the run screen -----------------------------------------------------------------------------

async function drawGraph(container, graph, index) {
  if (!window.mermaid) {
    container.append(
      element("p", "Graph unavailable offline (Mermaid did not load). Its source:", "note"),
      element("pre", graph.mermaid),
    );
    return;
  }
  try {
    window.mermaid.initialize({ startOnLoad: false, securityLevel: "strict" });
    const { svg } = await window.mermaid.render(`graph-${index}`, graph.mermaid);
    const holder = element("div", null, "graph");
    holder.innerHTML = svg; // Mermaid's own output, rendered in strict security mode
    container.append(holder);
  } catch (error) {
    container.append(element("p", `The graph could not be drawn: ${error}`, "note"), element("pre", graph.mermaid));
  }
}

function rowDetail(row) {
  const detail = element("div", null, "detail");
  detail.append(element("h3", `${row.block}${row.task !== null ? ` (task ${row.task})` : ""} · visit ${row.visit}`));
  detail.append(element("p", `Arrived from ${row.from || "the entry"} (${row.reason || "-"}). Decided by: ${row.decided_by || "-"}. Duration: ${formatDuration(row.duration_ms)}.`));
  if (row.packet) {
    detail.append(element("h4", "Packet given to the agent"), element("pre", row.packet));
  }
  row.submissions.forEach((submission, index) => {
    const title = submission.accepted ? `Submission ${index + 1}: accepted` : `Submission ${index + 1}: rejected`;
    detail.append(element("h4", title));
    if (submission.raw) detail.append(element("pre", submission.raw));
    if (submission.errors.length) detail.append(element("pre", submission.errors.join("\n"), "errors"));
  });
  row.script_runs.forEach((script, index) => {
    detail.append(element("h4", `Script run ${index + 1}: exit code ${script.exit_code ?? "-"}`));
    detail.append(element("pre", `$ ${script.argv.join(" ")}\n${script.stdout || ""}${script.stderr ? `\n[stderr]\n${script.stderr}` : ""}${script.problem ? `\n[problem] ${script.problem}` : ""}`));
  });
  if (row.output !== null) {
    detail.append(element("h4", "Output"), element("pre", JSON.stringify(row.output, null, 2)));
  }
  return detail;
}

function drawTimeline(rows) {
  const wrapper = element("div", null, "timeline");
  const list = element("ol");
  const detailHolder = element("div");
  selectedRow = Math.min(selectedRow, Math.max(rows.length - 1, 0));
  rows.forEach((row, index) => {
    const item = element("li", null, index === selectedRow ? "selected" : "");
    const button = element("button", `${row.block}${row.task !== null ? ` #${row.task}` : ""} (${row.block_type})`);
    button.addEventListener("click", () => {
      selectedRow = index;
      render();
    });
    item.append(button);
    list.append(item);
  });
  if (rows.length) detailHolder.append(rowDetail(rows[selectedRow]));
  wrapper.append(list, detailHolder);
  return wrapper;
}

async function showRun(runId) {
  const detail = await fetchJson(`/api/runs/${encodeURIComponent(runId)}`);
  const info = detail.info;
  // Redraw only when something changed, so polling never resets the scroll position or the graph.
  const detailText = JSON.stringify(detail) + selectedRow;
  if (detailText === lastDrawnRun) {
    if (UNFINISHED.includes(info.status)) pollTimer = setTimeout(render, POLL_MS);
    return;
  }
  lastDrawnRun = detailText;
  const header = element("section", null, "run-header");
  header.append(element("h2", `${info.skill_id} · ${info.run_id}`));
  header.append(element("p", `Status: ${info.status}${info.pause_reason ? ` (${info.pause_reason})` : ""} · harness: ${info.harness} · mode: ${info.mode}`));
  if (info.pause_error) header.append(element("pre", info.pause_error, "errors"));
  if (detail.skill_changed) header.append(element("p", "The skill changed after this run started: the run uses its own copy.", "note"));
  const graphs = element("section");
  graphs.append(element("h2", "Graph"));
  const timeline = element("section");
  timeline.append(element("h2", "Timeline (use the left and right arrow keys)"), drawTimeline(detail.timeline));
  const state = element("details");
  state.append(element("summary", "State (inputs, steps, history)"), element("pre", JSON.stringify(detail.state, null, 2)));
  app.replaceChildren(header, graphs, timeline, state);
  for (const [index, graph] of detail.graphs.entries()) {
    graphs.append(element("h3", graph.skill_id));
    await drawGraph(graphs, graph, index);
  }
  if (UNFINISHED.includes(info.status)) pollTimer = setTimeout(render, POLL_MS);
}

// --- routing ------------------------------------------------------------------------------------

async function render() {
  clearTimeout(pollTimer);
  const match = location.hash.match(/^#\/run\/(.+)$/);
  try {
    if (match) await showRun(decodeURIComponent(match[1]));
    else await showRuns();
  } catch (error) {
    app.replaceChildren(element("p", `The viewer could not load the data: ${error.message}`, "errors"));
  }
}

window.addEventListener("hashchange", () => {
  selectedRow = 0;
  lastDrawnRun = null;
  render();
});
window.addEventListener("keydown", (event) => {
  if (!location.hash.startsWith("#/run/")) return;
  if (event.key === "ArrowRight") selectedRow += 1;
  else if (event.key === "ArrowLeft") selectedRow = Math.max(selectedRow - 1, 0);
  else return;
  render();
});
render();
