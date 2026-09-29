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
from pskill_runner.skill_model import AnyBlock, DecisionBlock, EndBlock, Skill

FINISHED_STATUSES = ("succeeded", "failed", "cancelled")
FAILED_PAUSE_REASONS = ("block_failed", "runner_error")
EDGE_LABEL_LIMIT = 60
SCRIPT_FIELDS = ("argv", "exit_code", "stdout", "stderr", "duration_ms", "problem")
START_NODE = "start"
DOTTED_EDGE_KINDS = ("visit_cap", "call")


# --- the canvas: frames, nodes, and edges --------------------------------------------------------


@dataclass
class CanvasFrame:
    """One skill on the canvas: the root skill, or a child skill entered through a call block."""

    skill: Skill
    parent: int | None
    called_by: str | None


@dataclass
class CanvasEdge:
    id: str
    source: str
    target: str
    label: str | None
    kind: str
    frame: int
    from_block: str | None
    to_block: str
    when: str | None = None
    choice: str | None = None


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


def condition_label(condition: str | None) -> str | None:
    """A `when` shown as an edge label: without the braces, shortened, and safe for Mermaid."""
    if condition is None:
        return None
    text = condition.strip().removeprefix("{{").removesuffix("}}").strip()
    if len(text) > EDGE_LABEL_LIMIT:
        text = text[: EDGE_LABEL_LIMIT - 1] + "…"
    return mermaid_text(text)


def assign_frames(
    rows: list[dict[str, Any]], skills: dict[str, Skill], root: Skill
) -> tuple[list[CanvasFrame], list[int]]:
    """The canvas frames, and the frame index of each row.

    A row's `frame` is its call chain, like "parent>child". A child is a new frame per call block, so
    the same child skill called from two call blocks gets two frames.
    """
    frames = [CanvasFrame(root, parent=None, called_by=None)]
    active: dict[str, int] = {}
    last_call: dict[str, str] = {}
    previous_depth = 0
    row_frames = []
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
    chain: str, frames: list[CanvasFrame], active: dict[str, int], last_call: dict[str, str], skills: dict[str, Skill]
) -> int:
    if ">" not in chain:
        return 0
    parent_chain, skill_id = chain.rsplit(">", 1)
    parent = active.get(parent_chain, 0)
    called_by = last_call.get(parent_chain)
    for index, frame in enumerate(frames):
        if frame.parent == parent and frame.called_by == called_by and frame.skill.id == skill_id:
            return index
    if skill_id not in skills:
        return parent
    frames.append(CanvasFrame(skills[skill_id], parent=parent, called_by=called_by))
    return len(frames) - 1


def canvas_edges(frames: list[CanvasFrame]) -> list[CanvasEdge]:
    """Every edge of every frame, in the order the template declares them."""
    edges: list[CanvasEdge] = []
    pair_counts: dict[tuple[str, str], int] = {}

    def add(source: str, target: str, label: str | None, kind: str, frame: int, **match: Any) -> None:
        count = pair_counts.get((source, target), 0)
        pair_counts[(source, target)] = count + 1
        edge_id = f"L_{source}_{target}_{count}"
        edges.append(CanvasEdge(edge_id, source, target, label, kind, frame, to_block=match.pop("to_block"), **match))

    for edge in frames[0].skill.entry:
        target = node_id(0, edge.to)
        add(
            START_NODE,
            target,
            condition_label(edge.when),
            "entry",
            0,
            from_block=None,
            to_block=edge.to,
            when=edge.when,
        )
    for index, frame in enumerate(frames):
        for block in frame.skill.blocks.values():
            add_block_edges(add, index, block)
        if frame.parent is not None and frame.called_by is not None:
            for target_block in dict.fromkeys(edge.to for edge in frame.skill.entry):
                caller = node_id(frame.parent, frame.called_by)
                add(caller, node_id(index, target_block), None, "call", index, from_block=None, to_block=target_block)
    return edges


def add_block_edges(add: Any, index: int, block: AnyBlock) -> None:
    source = node_id(index, block.id)
    if isinstance(block, EndBlock):
        return
    if isinstance(block, DecisionBlock) and isinstance(block.next, dict):
        for choice, target in block.next.items():
            add(
                source,
                node_id(index, target),
                mermaid_text(choice),
                "choice",
                index,
                from_block=block.id,
                to_block=target,
                choice=choice,
            )
    else:
        for edge in block.next if isinstance(block.next, list) else []:
            label = condition_label(edge.when)
            add(
                source,
                node_id(index, edge.to),
                label,
                "next",
                index,
                from_block=block.id,
                to_block=edge.to,
                when=edge.when,
            )
    if block.on_max_visits is not None:
        target = block.on_max_visits
        add(source, node_id(index, target), "visit cap", "visit_cap", index, from_block=block.id, to_block=target)


def canvas_template(frames: list[CanvasFrame], edges: list[CanvasEdge]) -> str:
    lines = ["flowchart TD", f'  {START_NODE}(("start"))']
    for index, frame in enumerate(frames):
        indent = "  " if index == 0 else "    "
        if index > 0:
            lines.append(f'  subgraph f{index} ["{frame.skill.id} · called by {frame.called_by}"]')
        lines += [
            f'{indent}{node_id(index, block_id)}["{label_token(node_id(index, block_id))}"]'
            for block_id in frame.skill.blocks
        ]
        if index > 0:
            lines.append("  end")
    for edge in edges:
        arrow = "-.->" if edge.kind in DOTTED_EDGE_KINDS else "-->"
        label = f'|"{edge.label}"|' if edge.label is not None else ""
        lines.append(f"  {edge.source} {arrow}{label} {edge.target}")
    return "\n".join(lines) + "\n"


# --- the canvas: what each timeline row adds --------------------------------------------------


def arrival_edge(row: dict[str, Any], frame: int, edges: list[CanvasEdge]) -> CanvasEdge | None:
    """The edge that a row arrived by, matched from the logged `from` and `reason`."""
    candidates = [edge for edge in edges if edge.frame == frame and edge.to_block == row["block"]]
    from_block, reason = row["from"], str(row["reason"] or "")
    if from_block is None:
        wanted_kind = "entry" if frame == 0 else "call"
        matches = [edge for edge in candidates if edge.kind == wanted_kind]
        exact = [edge for edge in matches if edge.when == reason or (edge.when is None and reason == "always")]
        return next(iter(exact or matches), None)
    own = [edge for edge in candidates if edge.from_block == from_block]
    if reason.startswith("choice "):
        exact = [edge for edge in own if edge.choice == reason.removeprefix("choice ")]
    elif reason.startswith("visit cap of "):
        exact = [edge for edge in own if edge.kind == "visit_cap"]
    else:
        exact = [
            edge
            for edge in own
            if edge.kind == "next" and (edge.when == reason or (edge.when is None and reason == "always"))
        ]
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


def node_label(block_id: str, block_type: str, row: dict[str, Any] | None, rejected: int) -> str:
    details = [block_type]
    badges = []
    if row is not None:
        if row["duration_ms"] is not None:
            details.append(format_duration(int(row["duration_ms"])))
        outcome = row_outcome(row)
        if outcome is not None:
            details.append(mermaid_text(outcome))
        if int(row["visit"]) >= 2:
            badges.append(f"visit {row['visit']}")
    if rejected:
        badges.append(f"{rejected} rejected")
    label = f"<b>{block_id}</b><br/>{' · '.join(details)}"
    return label + (f"<br/>{' · '.join(badges)}" if badges else "")


def asks_human(block: AnyBlock | None) -> bool:
    return isinstance(block, DecisionBlock) and block.decider == "human"


def annotate_rows(
    rows: list[dict[str, Any]], row_frames: list[int], frames: list[CanvasFrame], edges: list[CanvasEdge]
) -> None:
    """Give each row its node, its arrival edge, its node label after the row, and its human mark."""
    rejected_per_node: dict[str, int] = {}
    for row, frame in zip(rows, row_frames, strict=True):
        node = node_id(frame, row["block"])
        block = frames[frame].skill.blocks.get(row["block"])
        rejected_per_node[node] = rejected_per_node.get(node, 0) + sum(
            1 for submission in row["submissions"] if not submission["accepted"]
        )
        edge = arrival_edge(row, frame, edges)
        row["node"] = node
        row["edge"] = edge.id if edge else None
        row["label"] = node_label(row["block"], row["block_type"], row, rejected_per_node[node])
        row["asks_human"] = asks_human(block)
    edges_by_id = {edge.id: edge for edge in edges}
    for index, row in enumerate(rows):
        row["left_by"] = None
        for later in rows[index + 1 :]:
            edge = edges_by_id.get(later["edge"] or "")
            if edge is not None and edge.source == row["node"]:
                row["left_by"] = {"to": later["block"], "label": edge.label}
                break


def current_step(info: RunInfo, rows: list[dict[str, Any]]) -> dict[str, str] | None:
    """The node that the run waits at, and how it waits. None for a finished run."""
    if info["status"] in FINISHED_STATUSES or not rows:
        return None
    last = rows[-1]
    if info["status"] == "paused" and info["pause_reason"] in FAILED_PAUSE_REASONS:
        state = "failed"
    elif last["asks_human"]:
        state = "waiting"
    else:
        state = "now"
    return {"node": last["node"], "state": state}


def load_run_skills(folder: Path) -> dict[str, Skill]:
    """Every skill copy that the run keeps in its own `skills/` folder."""
    skills = {}
    for skill_folder in sorted((folder / "skills").glob("*")):
        try:
            skills[skill_folder.name] = load_skill(skill_folder)
        except SkillLoadError:
            continue
    return skills


def run_canvas(folder: Path, info: RunInfo, rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    """The canvas of a run. It also adds `node`, `edge`, `label`, `asks_human`, and `left_by` to each row."""
    skills = load_run_skills(folder)
    root = skills.get(info["skill_id"])
    if root is None:
        return None
    frames, row_frames = assign_frames(rows, skills, root)
    edges = canvas_edges(frames)
    annotate_rows(rows, row_frames, frames, edges)
    nodes: list[dict[str, Any]] = [
        {
            "id": node_id(index, block.id),
            "frame": index,
            "skill_id": frame.skill.id,
            "block": block.id,
            "type": block_type_name(block),
            "asks_human": asks_human(block),
        }
        for index, frame in enumerate(frames)
        for block in frame.skill.blocks.values()
    ]
    return {
        "template": canvas_template(frames, edges),
        "labels": {node["id"]: node_label(node["block"], node["type"], None, 0) for node in nodes},
        "nodes": nodes,
        "edges": [
            {"id": edge.id, "source": edge.source, "target": edge.target, "label": edge.label, "kind": edge.kind}
            for edge in edges
        ],
        "current": current_step(info, rows),
    }


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
    rows = timeline_rows(read_events(folder))
    return {
        "info": info,
        "state": read_run_state(project, run_id),
        "canvas": run_canvas(folder, info, rows),
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
    return open_rows.get((frame, block, task)) or open_rows.get((frame, block, None))


def record_completion(row: dict[str, Any], event: dict[str, Any]) -> None:
    if event["decided_by"] != "runner":
        row["submissions"].append({"accepted": True, "errors": [], "raw": None})
    row["output"] = event["output"]
    row["decided_by"] = event["decided_by"]
    row["duration_ms"] = event["duration_ms"]
