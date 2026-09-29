"""The data that the viewer shows (SPEC.md section 14). The browser only draws it.

Everything is built here, in Python, so the tests cover it: the canvas (one Mermaid template for the
whole run, child skills included), the timeline rows with their node, arrival edge, and label, and the
per-skill summaries. The page only adds up the rows up to the replay step.
"""

import statistics
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pskill_runner.engine import list_runs, read_run_info, read_run_state
from pskill_runner.project import Project
from pskill_runner.run_records import RunInfo
from pskill_runner.run_store import folder_hash, parse_timestamp, read_events, utc_now
from pskill_runner.skill_loader import SkillLoadError, load_skill
from pskill_runner.skill_model import AnyBlock, CallBlock, DecisionBlock, EndBlock, Skill

FINISHED_STATUSES = ("succeeded", "failed", "cancelled")
FAILED_PAUSE_REASONS = ("block_failed", "runner_error")
EDGE_LABEL_LIMIT = 60
SCRIPT_FIELDS = ("argv", "exit_code", "stdout", "stderr", "duration_ms", "problem")
START_NODE = "start"
DOTTED_EDGE_KINDS = ("visit_cap", "call")
BLOCK_TYPE_MEANINGS = {
    "task": "the agent does a piece of work and returns a typed answer.",
    "decision": "one choice is picked from a list, or a question gets an answer.",
    "parallel": "subagents do one task per list item at the same time, and the results join into one list.",
    "script": "the runner runs a command. No AI model takes part.",
    "call": "the runner runs another skill and gets its outputs.",
    "end": "the skill finishes here with a status and outputs.",
}


# --- the canvas: frames, nodes, and edges --------------------------------------------------------


@dataclass
class CanvasFrame:
    """One skill on the canvas: the root skill, or a child skill entered through a call block."""

    skill: Skill
    parent: int | None
    called_by: str | None


@dataclass
class CanvasEdge:
    """One edge of the template. `text` is the plain label; `label` is the same text, safe for Mermaid.

    `hint` says in plain words when the run takes the edge, with the whole condition.
    """

    source: str
    target: str
    text: str | None
    kind: str
    frame: int
    from_block: str | None
    to_block: str
    hint: str
    when: str | None = None
    choice: str | None = None
    id: str = ""

    @property
    def label(self) -> str | None:
        return None if self.text is None else mermaid_text(self.text)


def node_id(frame_index: int, block_id: str) -> str:
    return f"f{frame_index}_{block_id}"


def label_token(node: str) -> str:
    """The placeholder that the page swaps for the node label of the replay step."""
    return f"@@{node}@@"


def block_type_name(block: AnyBlock) -> str:
    return type(block).__name__.removesuffix("Block").lower()


def mermaid_text(text: str) -> str:
    """Text that is safe inside a quoted Mermaid label."""
    for character, entity in (('"', "#quot;"), ("'", "#39;"), ("<", "#lt;"), (">", "#gt;")):
        text = text.replace(character, entity)
    return text


def whole_condition_text(condition: str) -> str:
    """A `when` as plain text, without the braces."""
    return condition.strip().removeprefix("{{").removesuffix("}}").strip()


def condition_text(condition: str) -> str:
    """A `when` as plain text: without the braces, and shortened."""
    text = whole_condition_text(condition)
    return text if len(text) <= EDGE_LABEL_LIMIT else text[: EDGE_LABEL_LIMIT - 1] + "…"


def node_hint(block: AnyBlock) -> str:
    """The block in plain words: its description, what its type does, and who decides or what it runs."""
    type_name = block_type_name(block)
    lines = [block.description] if block.description else []
    lines.append(f"{type_name} block: {BLOCK_TYPE_MEANINGS[type_name]}")
    if isinstance(block, DecisionBlock):
        human = block.decider == "human"
        lines.append(
            "The user decides in an interactive run. The agent decides in an autonomous run."
            if human
            else "The agent decides."
        )
    if isinstance(block, CallBlock):
        lines.append(f"Skill: {block.skill}.")
    if isinstance(block, EndBlock):
        lines.append(f"Status: {block.status}.")
    if block.max_visits is not None:
        lines.append(f"It runs at most {block.max_visits} times.")
    return "\n".join(lines)


def condition_hint(when: str | None, has_other_edges: bool) -> str:
    """The end of a hint sentence: when the run takes one edge of an edge list (the first match wins).

    Empty for the only edge of a list, which the run always takes.
    """
    if when is not None:
        return f" when {whole_condition_text(when)}."
    return " when no condition above matches." if has_other_edges else ""


def assign_frames(
    rows: list[dict[str, Any]], skills: dict[str, Skill], root: Skill
) -> tuple[list[CanvasFrame], list[int | None]]:
    """The canvas frames, and the frame index of each row (None for a child whose skill copy is missing).

    A row's `frame` is its call chain, like "parent>child". A child is a new frame per call block, so
    the same child skill called from two call blocks gets two frames.
    """
    frames = [CanvasFrame(root, parent=None, called_by=None)]
    active: dict[str, int | None] = {}
    last_call: dict[str, str] = {}
    previous_depth = 0
    row_frames: list[int | None] = []
    for row in rows:
        chain = str(row["frame"])
        depth = chain.count(">")
        if chain not in active or depth > previous_depth:
            active[chain] = frame_for_chain(chain, frames, active, last_call, skills)
        if row["block_type"] == "call":
            last_call[chain] = row["block"]
        previous_depth = depth
        row_frames.append(active[chain])
    return frames, row_frames


def frame_for_chain(
    chain: str,
    frames: list[CanvasFrame],
    active: dict[str, int | None],
    last_call: dict[str, str],
    skills: dict[str, Skill],
) -> int | None:
    if ">" not in chain:
        return 0
    parent_chain, skill_id = chain.rsplit(">", 1)
    parent = active.get(parent_chain, 0)
    called_by = last_call.get(parent_chain)
    if parent is None or skill_id not in skills:
        return None
    for index, frame in enumerate(frames):
        if frame.parent == parent and frame.called_by == called_by and frame.skill.id == skill_id:
            return index
    frames.append(CanvasFrame(skills[skill_id], parent=parent, called_by=called_by))
    return len(frames) - 1


def block_edges(index: int, block: AnyBlock) -> list[CanvasEdge]:
    """The edges out of one block: its choices or its next edges, plus its visit-cap edge."""
    if isinstance(block, EndBlock):
        return []
    source = node_id(index, block.id)
    edges = []
    if isinstance(block, DecisionBlock) and isinstance(block.next, dict):
        choices = block.choices or {}
        for choice, target in block.next.items():
            hint = f'Taken when the decider picks "{choice}"' + (f": {choices[choice]}" if choices.get(choice) else ".")
            edges.append(
                CanvasEdge(
                    source, node_id(index, target), choice, "choice", index, block.id, target, hint, choice=choice
                )
            )
    else:
        next_edges = block.next if isinstance(block.next, list) else []
        for edge in next_edges:
            text = condition_text(edge.when) if edge.when is not None else None
            ending = condition_hint(edge.when, len(next_edges) > 1)
            hint = f"Taken{ending}" if ending else "Always taken."
            edges.append(
                CanvasEdge(
                    source, node_id(index, edge.to), text, "next", index, block.id, edge.to, hint, when=edge.when
                )
            )
    if block.on_max_visits is not None:
        target = block.on_max_visits
        hint = (
            f"Taken instead when the run tries to enter {block.id} after its {block.max_visits} visits (the visit cap)."
        )
        edges.append(
            CanvasEdge(source, node_id(index, target), "visit cap", "visit_cap", index, block.id, target, hint)
        )
    return edges


def frame_edges(index: int, frame: CanvasFrame) -> list[CanvasEdge]:
    """The entry edges (from the start, or from the call block), then every block's edges."""
    edges = []
    if frame.parent is None:
        for edge in frame.skill.entry:
            text = condition_text(edge.when) if edge.when is not None else None
            hint = "The run starts here" + (condition_hint(edge.when, len(frame.skill.entry) > 1) or ".")
            edges.append(
                CanvasEdge(START_NODE, node_id(0, edge.to), text, "entry", 0, None, edge.to, hint, when=edge.when)
            )
    elif frame.called_by is not None:
        caller = node_id(frame.parent, frame.called_by)
        hint = f"The call block {frame.called_by} runs the skill {frame.skill.id}, which starts here."
        for target in dict.fromkeys(edge.to for edge in frame.skill.entry):
            edges.append(CanvasEdge(caller, node_id(index, target), None, "call", index, None, target, hint))
    for block in frame.skill.blocks.values():
        edges += block_edges(index, block)
    return edges


def number_edges(edges: list[CanvasEdge]) -> list[CanvasEdge]:
    """Give each edge the DOM id that Mermaid gives it: `L_<source>_<target>_<n>`.

    Mermaid 12 numbers the first edge of a source and target pair 0, and each later one of that pair
    one more than the count of edges before it: 0, 2, 3, ...
    """
    counts: dict[tuple[str, str], int] = {}
    for edge in edges:
        count = counts.get((edge.source, edge.target), 0)
        counts[(edge.source, edge.target)] = count + 1
        edge.id = f"L_{edge.source}_{edge.target}_{0 if count == 0 else count + 1}"
    return edges


def canvas_template(frames: list[CanvasFrame], edges: list[CanvasEdge]) -> str:
    lines = ["flowchart TD", f'  {START_NODE}(("start"))']
    for index, frame in enumerate(frames):
        indent = "  " if index == 0 else "    "
        if index > 0:
            lines.append(f'  subgraph f{index} ["{frame.skill.id} · called by {frame.called_by}"]')
        for block_id in frame.skill.blocks:
            lines.append(f'{indent}{node_id(index, block_id)}["{label_token(node_id(index, block_id))}"]')
        if index > 0:
            lines.append("  end")
    for edge in edges:
        arrow = "-.->" if edge.kind in DOTTED_EDGE_KINDS else "-->"
        label = f'|"{edge.label}"|' if edge.label is not None else ""
        lines.append(f"  {edge.source} {arrow}{label} {edge.target}")
    return "\n".join(lines) + "\n"


# --- the canvas: what each timeline row adds --------------------------------------------------


def matches_reason(edge: CanvasEdge, reason: str) -> bool:
    """Whether the engine's logged reason names this edge's condition."""
    return edge.when == reason or (edge.when is None and reason == "always")


def arrival_edge(row: dict[str, Any], frame: int, edges: list[CanvasEdge]) -> CanvasEdge | None:
    """The edge that a row arrived by, matched from the logged `from` and `reason`."""
    candidates = [edge for edge in edges if edge.frame == frame and edge.to_block == row["block"]]
    from_block, reason = row["from"], str(row["reason"] or "")
    if from_block is None:
        wanted_kind = "entry" if frame == 0 else "call"
        matches = [edge for edge in candidates if edge.kind == wanted_kind]
        return next(iter([edge for edge in matches if matches_reason(edge, reason)] or matches), None)
    own = [edge for edge in candidates if edge.from_block == from_block]
    if reason.startswith("choice "):
        exact = [edge for edge in own if edge.choice == reason.removeprefix("choice ")]
    elif reason.startswith("visit cap of "):
        exact = [edge for edge in own if edge.kind == "visit_cap"]
    else:
        exact = [edge for edge in own if edge.kind == "next" and matches_reason(edge, reason)]
    return next(iter(exact or own), None)


def format_duration(milliseconds: int) -> str:
    if milliseconds < 1000:
        return f"{milliseconds} ms"
    seconds = round(milliseconds / 1000)
    return f"{seconds} s" if seconds < 60 else f"{seconds // 60} min {seconds % 60:02d} s"


def row_outcome(row: dict[str, Any]) -> str | None:
    """The short result shown on the node: a choice, a child status, an exit code, or a task count."""
    output = row["output"] if isinstance(row["output"], dict) else {}
    if row["block_type"] == "decision" and "choice" in output:
        return str(output["choice"])
    if row["block_type"] == "call" and "status" in output:
        return str(output["status"])
    if row["block_type"] == "script" and row["script_runs"]:
        return f"exit {row['script_runs'][-1]['exit_code']}"
    if row["block_type"] == "parallel" and isinstance(output.get("results"), list):
        return f"{len(output['results'])} tasks"
    return None


def row_details(row: dict[str, Any], rejected: int) -> tuple[list[str], list[str]]:
    """The plain details of a node after a row (type, duration, outcome) and its badges (visit, rejected)."""
    details = [str(row["block_type"])]
    if row["duration_ms"] is not None:
        details.append(format_duration(int(row["duration_ms"])))
    outcome = row_outcome(row)
    if outcome is not None:
        details.append(outcome)
    badges: list[str] = []
    if int(row["visit"]) >= 2:
        badges.append(f"visit {row['visit']}")
    if rejected:
        badges.append(f"{rejected} rejected")
    return details, badges


def node_label(block_id: str, details: list[str], badges: list[str]) -> str:
    label = f"<b>{block_id}</b><br/>{mermaid_text(' · '.join(details))}"
    return label + (f"<br/>{' · '.join(badges)}" if badges else "")


def arrival_text(row: dict[str, Any], called_by: str | None) -> str:
    """Where a row came from and why, in plain words."""
    reason = str(row["reason"] or "")
    if row["from"] is None:
        chain = str(row["frame"]).split(">")
        if len(chain) == 1:
            return "the start"
        return f"{called_by or chain[-2]} (call)"
    if reason == "always":
        return str(row["from"])
    if reason.startswith(("choice ", "visit cap of ")):
        return f"{row['from']} ({reason})"
    return f"{row['from']} ({condition_text(reason)})"


def asks_human(block: AnyBlock | None, mode: str) -> bool:
    """A human decision asks the user only in an interactive run; in autonomous mode the agent decides."""
    return isinstance(block, DecisionBlock) and block.decider == "human" and mode == "interactive"


def next_step_in_frame(rows: list[dict[str, Any]], index: int, row_frames: list[int | None]) -> dict[str, Any] | None:
    """The next row of the same frame, skipping the other tasks of the same parallel block."""
    row = rows[index]
    if row["block_type"] == "end":
        return None
    for later, frame in zip(rows[index + 1 :], row_frames[index + 1 :], strict=True):
        if frame != row_frames[index]:
            continue
        other_task = later["block"] == row["block"] and later["visit"] == row["visit"] and later["task"] is not None
        if other_task:
            continue
        return None if later["from"] is None else later
    return None


def left_by(
    row: dict[str, Any], later: dict[str, Any] | None, edges_by_id: dict[str, CanvasEdge]
) -> dict[str, Any] | None:
    if later is None:
        return None
    reason = str(later["reason"] or "")
    if reason.startswith("visit cap of "):
        return {"to": later["block"], "label": f"visit cap of {later['from']}"}
    edge = edges_by_id.get(later["edge"] or "")
    return {"to": later["block"], "label": edge.text if edge is not None and edge.source == row["node"] else None}


def annotate_rows(
    rows: list[dict[str, Any]],
    row_frames: list[int | None],
    frames: list[CanvasFrame],
    edges: list[CanvasEdge],
    mode: str,
) -> list[dict[str, Any]]:
    """New rows, each with its node, arrival edge, labels, texts, human mark, and the edge it left by."""
    rejected_per_block: dict[tuple[int | None, str], int] = {}
    annotated: list[dict[str, Any]] = []
    for row, frame in zip(rows, row_frames, strict=True):
        key = (frame, str(row["block"]))
        rejected_per_block[key] = rejected_per_block.get(key, 0) + sum(
            1 for submission in row["submissions"] if not submission["accepted"]
        )
        details, badges = row_details(row, rejected_per_block[key])
        block = frames[frame].skill.blocks.get(row["block"]) if frame is not None else None
        edge = arrival_edge(row, frame, edges) if frame is not None else None
        called_by = frames[frame].called_by if frame is not None else None
        annotated.append(
            {
                **row,
                "node": node_id(frame, row["block"]) if frame is not None else None,
                "edge": edge.id if edge is not None else None,
                "label": node_label(row["block"], details, badges),
                "summary": " · ".join(details + badges),
                "arrival": arrival_text(row, called_by),
                "asks_human": asks_human(block, mode),
            }
        )
    edges_by_id = {edge.id: edge for edge in edges}
    for index, row in enumerate(annotated):
        row["left_by"] = left_by(row, next_step_in_frame(annotated, index, row_frames), edges_by_id)
    return annotated


def current_step(info: RunInfo, rows: list[dict[str, Any]]) -> dict[str, str] | None:
    """The node that the run waits at, and how it waits. None for a finished run."""
    if info["status"] in FINISHED_STATUSES or not rows or rows[-1]["node"] is None:
        return None
    if info["status"] == "paused" and info["pause_reason"] in FAILED_PAUSE_REASONS:
        state = "failed"
    elif info["status"] == "waiting_for_human":
        state = "waiting"
    else:
        state = "now"
    return {"node": rows[-1]["node"], "state": state}


def load_run_skills(folder: Path) -> dict[str, Skill]:
    """Every skill copy that the run keeps in its own `skills/` folder."""
    skills: dict[str, Skill] = {}
    for skill_folder in sorted((folder / "skills").glob("*")):
        try:
            skills[skill_folder.name] = load_skill(skill_folder)
        except SkillLoadError:
            continue
    return skills


def run_canvas(
    folder: Path, info: RunInfo, rows: list[dict[str, Any]]
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    """The canvas of a run (None when its skill copy does not load), and the rows with their canvas fields."""
    skills = load_run_skills(folder)
    root = skills.get(info["skill_id"])
    if root is None:
        return None, annotate_rows(rows, [None] * len(rows), [], [], info["mode"])
    frames, row_frames = assign_frames(rows, skills, root)
    edges = number_edges([edge for index, frame in enumerate(frames) for edge in frame_edges(index, frame)])
    annotated = annotate_rows(rows, row_frames, frames, edges, info["mode"])
    nodes: list[dict[str, Any]] = [
        {
            "id": node_id(index, block.id),
            "token": label_token(node_id(index, block.id)),
            "frame": index,
            "skill_id": frame.skill.id,
            "block": block.id,
            "type": block_type_name(block),
            "hint": node_hint(block),
        }
        for index, frame in enumerate(frames)
        for block in frame.skill.blocks.values()
    ]
    canvas = {
        "template": canvas_template(frames, edges),
        "start": START_NODE,
        "labels": {node["id"]: node_label(node["block"], [node["type"]], []) for node in nodes},
        "nodes": nodes,
        "edges": [
            {
                "id": edge.id,
                "source": edge.source,
                "target": edge.target,
                "label": edge.text,
                "kind": edge.kind,
                "hint": edge.hint,
            }
            for edge in edges
        ],
        "current": current_step(info, annotated),
    }
    return canvas, annotated


# --- the runs overview ------------------------------------------------------------------------


def run_duration_ms(info: RunInfo) -> int:
    end = parse_timestamp(info["ended_at"]) if info["ended_at"] else utc_now()
    return int((end - parse_timestamp(info["created_at"])).total_seconds() * 1000)


def run_row(info: RunInfo) -> dict[str, Any]:
    return {
        "run_id": info["run_id"],
        "skill_id": info["skill_id"],
        "status": info["status"],
        "harness": info["harness"],
        "mode": info["mode"],
        "created_at": info["created_at"],
        "current_block": info["current_block"],
        "duration_ms": run_duration_ms(info),
    }


def runs_overview(project: Project) -> dict[str, Any]:
    """Every run as a table row, plus one summary row per skill."""
    rows = [run_row(info) for info in list_runs(project)]
    return {"runs": rows, "summaries": skill_summaries(rows)}


def skill_summaries(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    summaries = []
    for skill_id in sorted({row["skill_id"] for row in rows}):
        skill_rows = [row for row in rows if row["skill_id"] == skill_id]
        finished = [row for row in skill_rows if row["status"] in FINISHED_STATUSES]
        succeeded = [row for row in finished if row["status"] == "succeeded"]
        summaries.append(
            {
                "skill_id": skill_id,
                "runs": len(skill_rows),
                "finished": len(finished),
                "succeeded": len(succeeded),
                "success_rate": len(succeeded) / len(finished) if finished else None,
                "median_duration_ms": int(statistics.median(row["duration_ms"] for row in finished))
                if finished
                else None,
            }
        )
    return summaries


# --- one run ------------------------------------------------------------------------------------


def run_detail(project: Project, run_id: str) -> dict[str, Any] | None:
    """Everything the run screen shows, or None for an unknown run."""
    folder = project.runs_folder / run_id
    if not (folder / "run.json").is_file():
        return None
    info = read_run_info(project, run_id)
    canvas, rows = run_canvas(folder, info, timeline_rows(read_events(folder)))
    return {
        "info": info,
        "state": read_run_state(project, run_id),
        "canvas": canvas,
        "timeline": rows,
        "skill_changed": skill_changed(project, info),
    }


def skill_changed(project: Project, info: RunInfo) -> bool:
    """Whether the project's copy of the skill differs from the copy that the run uses (D22)."""
    skill_folder = project.skills_folder / info["skill_id"]
    return not skill_folder.is_dir() or folder_hash(skill_folder) != info["skill_hash"]


def timeline_rows(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One row per block entry, with its packet, every submission, its output, and its script runs."""
    rows: list[dict[str, Any]] = []
    open_rows: dict[tuple[str, str, int | None], dict[str, Any]] = {}
    for event in events:
        if event["type"] == "block_started":
            row = new_timeline_row(event)
            rows.append(row)
            open_rows[(event["frame"], event["block"], event.get("task"))] = row
            continue
        row_for_event = find_open_row(open_rows, event)
        if row_for_event is None:
            continue
        if event["type"] == "submission_rejected":
            row_for_event["submissions"].append({"accepted": False, "errors": event["errors"], "raw": event["raw"]})
        elif event["type"] == "script_ran":
            row_for_event["script_runs"].append({key: event.get(key) for key in SCRIPT_FIELDS})
        elif event["type"] == "block_completed":
            record_completion(row_for_event, event)
    return rows


def new_timeline_row(event: dict[str, Any]) -> dict[str, Any]:
    return {
        "seq": event["seq"],
        "ts": event["ts"],
        "frame": event["frame"],
        "block": event["block"],
        "block_type": event["block_type"],
        "visit": event["visit"],
        "task": event.get("task"),
        "from": event.get("from"),
        "reason": event.get("reason"),
        "packet": event.get("packet"),
        "submissions": [],
        "script_runs": [],
        "output": None,
        "decided_by": None,
        "duration_ms": None,
    }


def find_open_row(
    open_rows: dict[tuple[str, str, int | None], dict[str, Any]], event: dict[str, Any]
) -> dict[str, Any] | None:
    """The row that an event belongs to. In subagent mode, task answers belong to the block's one row."""
    frame, block = str(event["frame"]), str(event.get("block", ""))
    task: int | None = event.get("task")
    if task is not None:
        return open_rows.get((frame, block, task)) or open_rows.get((frame, block, None))
    # Without a task: the newest row of the block. For a one-by-one parallel block, that is the last task.
    same_block = [row for key, row in open_rows.items() if key[:2] == (frame, block)]
    return max(same_block, key=lambda row: int(row["seq"])) if same_block else None


def record_completion(row: dict[str, Any], event: dict[str, Any]) -> None:
    joins_tasks = row["task"] is not None and event.get("task") is None
    if event["decided_by"] != "runner" and not joins_tasks:
        row["submissions"].append({"accepted": True, "errors": [], "raw": None})
    row["output"] = event["output"]
    row["decided_by"] = event["decided_by"]
    row["duration_ms"] = event["duration_ms"]
