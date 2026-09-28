"""The data that the viewer shows (SPEC.md section 14). The browser only draws it.

Everything is built here, in Python, so the tests cover it: the Mermaid graph with its marks, the
timeline rows of a run, and the per-skill summaries.
"""

import statistics
from pathlib import Path
from typing import Any

from pskill_runner.engine import list_runs, read_run_info, read_run_state
from pskill_runner.project import Project
from pskill_runner.run_records import RunInfo
from pskill_runner.run_store import folder_hash, parse_timestamp, read_events, utc_now
from pskill_runner.skill_loader import SkillLoadError, load_skill
from pskill_runner.skill_model import DecisionBlock, EndBlock, Skill

FINISHED_STATUSES = ("succeeded", "failed", "cancelled")
FAILED_PAUSE_REASONS = ("block_failed", "runner_error")
EDGE_LABEL_LIMIT = 60
SCRIPT_FIELDS = ("argv", "exit_code", "stdout", "stderr", "duration_ms", "problem")
MERMAID_CLASSES = [
    "  classDef visited fill:#dbeafe,stroke:#2563eb",
    "  classDef current fill:#fef3c7,stroke:#d97706,stroke-width:3px",
    "  classDef failed fill:#fee2e2,stroke:#dc2626,stroke-width:3px",
]


# --- the graph ---------------------------------------------------------------------------------


def skill_mermaid(skill: Skill, visits: dict[str, int], current_block: str | None, failed: bool) -> str:
    """A Mermaid flowchart of the skill, with visit counts and marks for the visited and current blocks."""
    lines = ["flowchart TD"]
    lines += [edge_line('start(("start"))', edge.to, condition_label(edge.when)) for edge in skill.entry]
    for block in skill.blocks.values():
        block_type = type(block).__name__.removesuffix("Block").lower()
        lines.append(f'  {block.id}["{block.id}<br/>{block_type}{visit_text(visits.get(block.id, 0))}"]')
    for block in skill.blocks.values():
        lines += block_edge_lines(block)
    lines += MERMAID_CLASSES
    for block_id in skill.blocks:
        if block_id == current_block:
            lines.append(f"  class {block_id} {'failed' if failed else 'current'}")
        elif visits.get(block_id, 0) > 0:
            lines.append(f"  class {block_id} visited")
    return "\n".join(lines) + "\n"


def block_edge_lines(block: Any) -> list[str]:
    if isinstance(block, EndBlock):
        return []
    lines = []
    if isinstance(block, DecisionBlock) and isinstance(block.next, dict):
        lines += [edge_line(block.id, target, choice) for choice, target in block.next.items()]
    else:
        lines += [edge_line(block.id, edge.to, condition_label(edge.when)) for edge in block.next]
    if block.on_max_visits is not None:
        lines.append(f'  {block.id} -.->|"visit cap"| {block.on_max_visits}')
    return lines


def edge_line(source: str, target: str, label: str | None) -> str:
    if label is None:
        return f"  {source} --> {target}"
    return f'  {source} -->|"{label}"| {target}'


def condition_label(condition: str | None) -> str | None:
    """A `when` shown as an edge label: without the braces, shortened, and safe for Mermaid."""
    if condition is None:
        return None
    text = condition.strip().removeprefix("{{").removesuffix("}}").strip()
    if len(text) > EDGE_LABEL_LIMIT:
        text = text[: EDGE_LABEL_LIMIT - 1] + "…"
    return text.replace('"', "#quot;").replace("'", "#39;")


def visit_text(count: int) -> str:
    if count == 0:
        return ""
    return f" · {count} visit" if count == 1 else f" · {count} visits"


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
    events = read_events(folder)
    return {
        "info": info,
        "state": read_run_state(project, run_id),
        "timeline": timeline_rows(events),
        "graphs": run_graphs(folder, info, events),
        "skill_changed": skill_changed(project, info),
    }


def skill_changed(project: Project, info: RunInfo) -> bool:
    """Whether the project's copy of the skill differs from the copy that the run uses (D22)."""
    skill_folder = project.skills_folder / info["skill_id"]
    return not skill_folder.is_dir() or folder_hash(skill_folder) != info["skill_hash"]


def event_skill(event: dict[str, Any]) -> str:
    """The skill that an event belongs to: the last skill of its call chain."""
    return str(event["frame"]).split(">")[-1]


def is_block_entry(event: dict[str, Any]) -> bool:
    """A block_started event. A one-by-one parallel block logs one per task; count only the first."""
    return event["type"] == "block_started" and event.get("task") in (None, 0)


def run_graphs(folder: Path, info: RunInfo, events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One marked graph per skill that the run entered, in the order the run entered them."""
    skill_ids = list(dict.fromkeys(event_skill(event) for event in events if event["type"] == "block_started"))
    deepest_skill = skill_ids[-1] if skill_ids else info["skill_id"]
    unfinished = info["status"] not in FINISHED_STATUSES
    failed = info["status"] == "paused" and info["pause_reason"] in FAILED_PAUSE_REASONS
    graphs = []
    for skill_id in skill_ids or [info["skill_id"]]:
        try:
            skill = load_skill(folder / "skills" / skill_id)
        except SkillLoadError:
            continue
        visits: dict[str, int] = {}
        for event in events:
            if is_block_entry(event) and event_skill(event) == skill_id:
                visits[event["block"]] = visits.get(event["block"], 0) + 1
        current = info["current_block"] if unfinished and skill_id == deepest_skill else None
        graphs.append({"skill_id": skill_id, "mermaid": skill_mermaid(skill, visits, current, failed)})
    return graphs


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
