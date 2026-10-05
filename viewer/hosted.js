// The hosted viewer (GitHub Pages) has no server. It reads the folders that the user picks, through the File
// System Access API, and answers the viewer's API in the browser: Pyodide runs pskill's own Python
// (viewer_api.py) on a copy of each project's .pskill files (SPEC.md section 14.3). app.js loads this module
// only when no local server answers.

const RUAMEL = "ruamel.yaml==0.19.1"; // the version in uv.lock: Pyodide has no build of it, so micropip installs it
const DATABASE = "pskill-viewer";
const STORE = "sources";
const FINISHED = new Set(["succeeded", "failed", "cancelled"]);
const SYNC_MS = 1000; // the shortest time between two copies of the same project
const SCAN_DEPTH = 3; // how deep a scan looks for projects in a folder that is not a git checkout
const SKIPPED_FOLDERS = new Set(["node_modules", "__pycache__", "venv", "dist", "build", "target"]);
// Where worktrees live inside a checkout: Claude Code's own place, and two common ones.
const WORKTREE_HOMES = [[".claude", "worktrees"], [".worktrees"], ["worktrees"]];

// Python, run once after the start: it reads each project from its copy at `root`.
const GLUE = `
import json
import sys

sys.path.insert(0, "/pskill")
from pathlib import Path

from pskill_runner import __version__
from pskill_runner.project import Config, Project, ProjectError, load_config
from pskill_runner.viewer_api import answer_get, answer_post
from pskill_runner.viewer_data import locations_runs_overview


def hosted_project(root):
    try:
        config = load_config(Path(root) / ".pskill" / "config.yaml")
    except ProjectError:
        config = Config()  # the viewer needs no setting: a bad config.yaml must not hide the runs
    return Project(root=Path(root), config=config)


def hosted_answer(answer):
    return None if answer is None else [answer.status, answer.content_type, answer.body, answer.download_name]


def hosted_get(root, path):
    return hosted_answer(answer_get(hosted_project(root), path))


def hosted_post(root, path, body):
    return hosted_answer(answer_post(hosted_project(root), path, body.encode("utf-8")))


def hosted_runs(roots):
    projects = {name: hosted_project(root) for name, root in json.loads(roots).items()}
    return json.dumps(locations_runs_overview(projects))
`;

let sources = []; // the folders that the user picked: { id, name, handle, pattern, granted, patternError }
let places = new Map(); // every project found in them, by id
let placeCount = 0;
let python = null; // the started Pyodide, as a promise

export function supported() {
  return "showDirectoryPicker" in window;
}

// --- the folders that the user picked, kept in IndexedDB (a handle survives a reload) -------------------

function database() {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(DATABASE, 1);
    request.onupgradeneeded = () => request.result.createObjectStore(STORE, { keyPath: "id" });
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}

async function storeRequest(mode, act) {
  const db = await database();
  return new Promise((resolve, reject) => {
    const request = act(db.transaction(STORE, mode).objectStore(STORE));
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}

function saveSource(source) {
  const { id, name, handle, pattern } = source;
  return storeRequest("readwrite", (store) => store.put({ id, name, handle, pattern }));
}

// Load the saved folders, and look for projects in each folder that the browser still lets the page read.
export async function load() {
  const saved = await storeRequest("readonly", (store) => store.getAll()).catch(() => []);
  sources = saved.map((source) => ({ ...source, granted: false, patternError: null }));
  for (const source of sources) source.granted = (await source.handle.queryPermission({ mode: "readwrite" })) === "granted";
  await rescan();
}

export function sourceList() {
  return sources.map((source) => ({
    id: source.id,
    name: source.name,
    pattern: source.pattern,
    granted: source.granted,
    patternError: source.patternError,
    places: placeList().filter((place) => place.source === source.id),
  }));
}

// Every project in every folder, by label. A place is one folder that holds a .pskill folder.
export function placeList() {
  return [...places.values()]
    .map(({ id, label, kind, branch, source }) => ({ id, label, kind, branch, source }))
    .sort((a, b) => a.label.localeCompare(b.label));
}

export function needsAccess() {
  return sources.some((source) => !source.granted);
}

// Ask the user to pick a folder: one project, or a folder of clones and worktrees.
export async function addSource() {
  const handle = await window.showDirectoryPicker({ id: "pskill", mode: "readwrite" });
  const source = { id: crypto.randomUUID(), name: handle.name, handle, pattern: "", granted: true, patternError: null };
  sources.push(source);
  await saveSource(source);
  await rescan();
}

export async function removeSource(id) {
  sources = sources.filter((source) => source.id !== id);
  await storeRequest("readwrite", (store) => store.delete(id));
  await rescan();
}

export async function setPattern(id, pattern) {
  const source = sources.find((item) => item.id === id);
  source.pattern = pattern;
  await saveSource(source);
  await rescan();
}

// Ask again for the folders that the browser no longer lets the page read. It needs a click of the user.
export async function allowAccess() {
  for (const source of sources) {
    if (!source.granted) source.granted = (await source.handle.requestPermission({ mode: "readwrite" })) === "granted";
  }
  await rescan();
}

// --- finding the projects in a folder ---------------------------------------------------------------------

async function entriesOf(folder) {
  const entries = [];
  for await (const entry of folder.values()) entries.push(entry);
  return entries;
}

async function childOf(folder, names, kind) {
  let handle = folder;
  try {
    for (const [index, name] of names.entries()) {
      handle = index === names.length - 1 && kind === "file" ? await handle.getFileHandle(name) : await handle.getDirectoryHandle(name);
    }
    return handle;
  } catch {
    return null; // it is not there
  }
}

async function textOf(folder, names) {
  const handle = await childOf(folder, names, "file");
  return handle ? (await handle.getFile()).text() : null;
}

function joinPath(...parts) {
  return parts.filter(Boolean).join("/");
}

// Every folder with a .pskill folder: the picked folder, its subfolders up to SCAN_DEPTH, and the worktrees of
// each git checkout. The scan does not go inside a checkout, which can hold thousands of folders.
async function projectsIn(source) {
  const found = [];
  const walk = async (folder, path, depth) => {
    const entries = await entriesOf(folder);
    const git = entries.find((entry) => entry.name === ".git");
    if (entries.some((entry) => entry.name === ".pskill" && entry.kind === "directory")) {
      found.push({ path, handle: folder, kind: git ? (git.kind === "directory" ? "clone" : "worktree") : "folder" });
    }
    if (git) {
      for (const home of WORKTREE_HOMES) {
        const holder = await childOf(folder, home, "directory");
        if (!holder) continue;
        for (const entry of await entriesOf(holder)) {
          if (entry.kind === "directory") await walk(entry, joinPath(path, ...home, entry.name), depth + 1);
        }
      }
      return;
    }
    if (depth >= SCAN_DEPTH) return;
    for (const entry of entries) {
      if (entry.kind === "directory" && !entry.name.startsWith(".") && !SKIPPED_FOLDERS.has(entry.name)) {
        await walk(entry, joinPath(path, entry.name), depth + 1);
      }
    }
  };
  await walk(source.handle, "", 0);
  return found;
}

// The branch of a checkout: .git/HEAD of a clone. A worktree's HEAD sits in its clone's .git/worktrees/<name>.
async function branchOf(project, projects) {
  let head = null;
  if (project.kind === "clone") head = await textOf(project.handle, [".git", "HEAD"]);
  if (project.kind === "worktree") {
    const gitFile = (await textOf(project.handle, [".git"])) || "";
    const name = gitFile.trim().split(/[\\/]/).pop();
    const clone = projects.find((item) => item.kind === "clone" && project.path.startsWith(`${item.path}/`));
    if (clone && name) head = await textOf(clone.handle, [".git", "worktrees", name, "HEAD"]);
  }
  if (!head) return null;
  const ref = head.trim().match(/^ref: refs\/heads\/(.+)$/);
  return ref ? ref[1] : head.trim().slice(0, 7);
}

// Look for projects again in every folder that the page may read. A place that stays keeps its copy.
export async function rescan() {
  const next = new Map();
  for (const source of sources.filter((item) => item.granted)) {
    let pattern = null;
    source.patternError = null;
    try {
      pattern = source.pattern ? new RegExp(source.pattern) : null;
    } catch (error) {
      source.patternError = error.message;
    }
    const projects = await projectsIn(source).catch(() => []);
    for (const project of projects) {
      const label = joinPath(source.name, project.path);
      if (pattern && !pattern.test(label)) continue;
      let id = label;
      for (let copy = 2; next.has(id); copy += 1) id = `${label} (${copy})`;
      const place = places.get(id) ?? newPlace(id);
      Object.assign(place, { label, source: source.id, handle: project.handle, kind: project.kind });
      place.branch = await branchOf(project, projects).catch(() => null);
      next.set(id, place);
    }
  }
  places = next;
}

function newPlace(id) {
  placeCount += 1;
  return { id, root: `/places/${placeCount}`, files: new Map(), finishedRuns: new Set(), syncs: new Map() };
}

// --- Python in the browser ---------------------------------------------------------------------------------

export function startPython() {
  python ??= (async () => {
    const { loadPyodide } = await import("pyodide"); // index.html maps it to the pinned files
    const pyodide = await loadPyodide();
    await pyodide.loadPackage(["jinja2", "pyyaml", "jsonschema", "micropip"]);
    await pyodide.pyimport("micropip").install(RUAMEL);
    const archive = await fetch("pskill_runner.zip");
    if (!archive.ok) throw new Error("The site has no pskill_runner.zip: the build step did not run.");
    pyodide.unpackArchive(await archive.arrayBuffer(), "zip", { extractDir: "/pskill" });
    pyodide.runPython(GLUE);
    return pyodide;
  })();
  return python;
}

function callPython(pyodide, name, ...args) {
  const result = pyodide.globals.get(name)(...args);
  if (result === undefined || typeof result === "string") return result;
  const value = result.toJs();
  result.destroy();
  return value;
}

// --- the copy of each project's .pskill files ----------------------------------------------------------------

function fingerprint(bytes) {
  let hash = 2166136261; // FNV-1a: enough to see that Python changed a file
  for (const byte of bytes) hash = Math.imul(hash ^ byte, 16777619);
  return `${bytes.length}:${hash >>> 0}`;
}

function parentOf(path) {
  return path.slice(0, path.lastIndexOf("/"));
}

async function copyFile(pyodide, place, handle, path) {
  const file = await handle.getFile();
  const known = place.files.get(path);
  if (known && known.lastModified === file.lastModified && known.size === file.size) return;
  const bytes = new Uint8Array(await file.arrayBuffer());
  pyodide.FS.mkdirTree(parentOf(path));
  pyodide.FS.writeFile(path, bytes);
  place.files.set(path, { lastModified: file.lastModified, size: file.size, fingerprint: fingerprint(bytes) });
}

// Copy a folder with every file in it: folder_hash() counts every file, so nothing may be left out.
async function copyFolder(pyodide, place, folder, path, seen) {
  for (const entry of await entriesOf(folder)) {
    const entryPath = `${path}/${entry.name}`;
    if (entry.kind === "directory") {
      await copyFolder(pyodide, place, entry, entryPath, seen);
    } else {
      await copyFile(pyodide, place, entry, entryPath);
      seen.add(entryPath);
    }
  }
}

// Remove from the copy each file under `path` that the folder no longer has.
function dropMissing(pyodide, place, path, seen) {
  for (const known of [...place.files.keys()]) {
    if (!known.startsWith(`${path}/`) || seen.has(known)) continue;
    try {
      pyodide.FS.unlink(known);
    } catch {
      // already gone
    }
    place.files.delete(known);
  }
}

async function copyTree(pyodide, place, names) {
  const path = joinPath(place.root, ".pskill", ...names);
  const folder = await childOf(place.handle, [".pskill", ...names], "directory");
  const seen = new Set();
  if (folder) await copyFolder(pyodide, place, folder, path, seen);
  dropMissing(pyodide, place, path, seen);
}

// The skills, the agents, and config.yaml.
async function copyContent(pyodide, place) {
  const config = await childOf(place.handle, [".pskill", "config.yaml"], "file");
  if (config) await copyFile(pyodide, place, config, `${place.root}/.pskill/config.yaml`);
  await copyTree(pyodide, place, ["skills"]);
  await copyTree(pyodide, place, ["agents"]);
}

// The runs: run.json of each run for the list, or the whole folder of one run. A finished run never changes.
async function copyRuns(pyodide, place, wholeRun = null) {
  const runsPath = `${place.root}/.pskill/runs`;
  pyodide.FS.mkdirTree(runsPath);
  const folder = await childOf(place.handle, [".pskill", "runs"], "directory");
  const runIds = new Set();
  for (const entry of folder ? await entriesOf(folder) : []) {
    if (entry.kind !== "directory") continue;
    runIds.add(entry.name);
    const runPath = `${runsPath}/${entry.name}`;
    if (entry.name === wholeRun && !place.finishedRuns.has(`${entry.name}:whole`)) {
      const seen = new Set();
      await copyFolder(pyodide, place, entry, runPath, seen);
      dropMissing(pyodide, place, runPath, seen);
    } else if (!place.finishedRuns.has(entry.name)) {
      const info = await childOf(entry, ["run.json"], "file");
      if (info) await copyFile(pyodide, place, info, `${runPath}/run.json`);
    }
    noteFinished(pyodide, place, entry.name, entry.name === wholeRun);
  }
  for (const runId of pyodide.FS.readdir(runsPath).filter((name) => !name.startsWith("."))) {
    if (!runIds.has(runId)) removeRun(pyodide, place, `${runsPath}/${runId}`, runId);
  }
}

function noteFinished(pyodide, place, runId, whole) {
  const infoPath = `${place.root}/.pskill/runs/${runId}/run.json`;
  try {
    const info = JSON.parse(pyodide.FS.readFile(infoPath, { encoding: "utf8" }));
    if (!FINISHED.has(info.status)) return;
    place.finishedRuns.add(runId);
    if (whole) place.finishedRuns.add(`${runId}:whole`);
  } catch {
    // run.json is being written: the next copy reads it again
  }
}

function removeRun(pyodide, place, path, runId) {
  dropMissing(pyodide, place, path, new Set());
  place.finishedRuns.delete(runId);
  place.finishedRuns.delete(`${runId}:whole`);
  try {
    pyodide.FS.rmdir(path);
  } catch {
    // a folder that still holds subfolders stays: Python sees no run.json in it
  }
}

// Copy what one request reads, at most once per SYNC_MS for the same part of a project.
function sync(pyodide, place, part, copy) {
  const last = place.syncs.get(part);
  if (last && Date.now() - last.at < SYNC_MS) return last.promise;
  const promise = copy().catch((error) => {
    place.syncs.delete(part);
    throw error;
  });
  place.syncs.set(part, { at: Date.now(), promise });
  return promise;
}

// --- writing the editor's changes back to the folder ------------------------------------------------------

function filesInCopy(pyodide, path) {
  const files = [];
  const walk = (folder) => {
    let names = [];
    try {
      names = pyodide.FS.readdir(folder).filter((name) => name !== "." && name !== "..");
    } catch {
      return; // the folder is not there
    }
    for (const name of names) {
      const child = `${folder}/${name}`;
      if (pyodide.FS.isDir(pyodide.FS.stat(child).mode)) walk(child);
      else files.push(child);
    }
  };
  walk(path);
  return files;
}

async function folderFor(place, path, create) {
  const names = path.slice(place.root.length + 1).split("/");
  let folder = place.handle;
  for (const name of names.slice(0, -1)) folder = await folder.getDirectoryHandle(name, { create });
  return { folder, name: names[names.length - 1] };
}

// After a write, put each file that Python changed in the real folder, and remove each file that it deleted:
// in the skills, the agents, and the folder of the run that was cancelled or deleted.
async function writeBack(pyodide, place, runId) {
  const parts = runId ? ["skills", "agents", `runs/${runId}`] : ["skills", "agents"];
  for (const part of parts) {
    const path = `${place.root}/.pskill/${part}`;
    if (runId && part.startsWith("runs/") && !pyodide.FS.analyzePath(path).exists) {
      await removeRunFolder(place, runId, path);
      continue;
    }
    const inCopy = new Set(filesInCopy(pyodide, path));
    for (const file of inCopy) {
      const bytes = pyodide.FS.readFile(file);
      if (place.files.get(file)?.fingerprint === fingerprint(bytes)) continue;
      const { folder, name } = await folderFor(place, file, true);
      const handle = await folder.getFileHandle(name, { create: true });
      const writable = await handle.createWritable();
      await writable.write(bytes);
      await writable.close();
      const written = await handle.getFile();
      place.files.set(file, { lastModified: written.lastModified, size: written.size, fingerprint: fingerprint(bytes) });
    }
    for (const known of [...place.files.keys()]) {
      if (!known.startsWith(`${path}/`) || inCopy.has(known)) continue;
      const { folder, name } = await folderFor(place, known, false);
      await folder.removeEntry(name);
      place.files.delete(known);
    }
  }
}

// Python deleted the run: delete its folder in the real project too.
async function removeRunFolder(place, runId, path) {
  const runs = await childOf(place.handle, [".pskill", "runs"], "directory");
  if (runs) await runs.removeEntry(runId, { recursive: true });
  for (const known of [...place.files.keys()]) if (known.startsWith(`${path}/`)) place.files.delete(known);
  place.finishedRuns.delete(runId);
  place.finishedRuns.delete(`${runId}:whole`);
}

// --- the API ----------------------------------------------------------------------------------------------

function jsonAnswer(status, data) {
  return { status, contentType: "application/json", body: new TextEncoder().encode(JSON.stringify(data)) };
}

// Answer one API request as the local server would. The place "*" with /api/runs is every project at once.
export async function request(placeId, method, path, body = "") {
  const pyodide = await startPython();
  if (path === "/api/version") return jsonAnswer(200, { version: pyodide.globals.get("__version__") });
  if (placeId === "*" && path === "/api/runs") {
    const roots = {};
    for (const place of places.values()) {
      await sync(pyodide, place, "runs", () => copyRuns(pyodide, place));
      roots[place.id] = place.root;
    }
    const overview = JSON.parse(callPython(pyodide, "hosted_runs", JSON.stringify(roots)));
    for (const run of overview.runs) {
      run.place = run.location; // Python names each run's project by its id
      run.location = places.get(run.place).label;
    }
    return jsonAnswer(200, overview);
  }
  const place = places.get(placeId);
  if (!place) return jsonAnswer(404, { error: "This folder is not in the list. Add it on the Folders screen." });
  const runMatch = path.match(/^\/api\/runs\/([^/]+)/);
  const runId = runMatch ? decodeURIComponent(runMatch[1]) : null;
  await sync(pyodide, place, "content", () => copyContent(pyodide, place));
  if (method === "POST" && runId) {
    await copyRuns(pyodide, place, runId); // a cancel changes the run: start from its newest files
  } else if (path.startsWith("/api/runs") || path.startsWith("/api/skills")) {
    await sync(pyodide, place, `runs:${runId}`, () => copyRuns(pyodide, place, runId));
  }
  const answer = callPython(pyodide, method === "POST" ? "hosted_post" : "hosted_get", place.root, path, ...(method === "POST" ? [body] : []));
  if (!answer) return jsonAnswer(404, { error: "Not found" });
  const [status, contentType, bytes, downloadName] = answer;
  if (method === "POST" && status === 200) {
    try {
      await writeBack(pyodide, place, runId);
    } catch (error) {
      place.files.clear(); // the copy holds a change that the folder does not: read it all again
      place.syncs.clear();
      return jsonAnswer(403, { error: [`Not saved in the folder: ${error.message}. Allow the folder again on the Folders screen.`] });
    }
  }
  return { status, contentType, body: bytes, downloadName };
}
