"""The skill screen of the viewer (SPEC.md section 14): every skill, and one skill's graph without a run.

It reads the skills in `.pskill/skills/`, never a run's copy. The canvas is the run canvas of one frame,
with no run parts: no status, no current step, and no timeline.
"""

import json
import re
from pathlib import Path
from typing import Any

from pskill_runner.engine import list_runs
from pskill_runner.field_types import FieldMap, FieldSpec
from pskill_runner.project import Project
from pskill_runner.skill_editor import COMMON_KEYS, EDITABLE_KEYS
from pskill_runner.skill_loader import SKILL_FILE_NAME, SkillLoadError, load_catalog, load_skill
from pskill_runner.skill_model import (
    AnyBlock,
    CallBlock,
    DecisionBlock,
    EndBlock,
    ParallelBlock,
    RetryableBlock,
    ScriptBlock,
    Skill,
    TaskBlock,
)
from pskill_runner.skill_schema import is_skill_id
from pskill_runner.validator import validate_skill
from pskill_runner.viewer_data import (
    BLOCK_TYPE_MEANINGS,
    START_NODE,
    CanvasFrame,
    block_edges,
    block_nodes,
    block_type_name,
    canvas_edge_rows,
    canvas_template,
    frame_edges,
    node_hint,
    node_id,
    node_label,
    node_notes,
    number_edges,
)
from pskill_runner.yaml_loading import load_skill_yaml


def skill_folders(project: Project) -> list[Path]:
    """Every folder in `.pskill/skills/` with a `skill.yaml`, in name order."""
    if not project.skills_folder.is_dir():
        return []
    return sorted(folder for folder in project.skills_folder.iterdir() if (folder / SKILL_FILE_NAME).is_file())


def skills_overview(project: Project) -> dict[str, Any]:
    """One row per skill, also for a skill with no runs or one that fails to load."""
    run_counts: dict[str, int] = {}
    for info in list_runs(project):
        run_counts[info["skill_id"]] = run_counts.get(info["skill_id"], 0) + 1
    return {"skills": [skill_row(folder, run_counts.get(folder.name, 0)) for folder in skill_folders(project)]}


def skill_row(folder: Path, runs: int) -> dict[str, Any]:
    row: dict[str, Any] = {"skill_id": folder.name, "description": None, "invocation": None, "blocks": 0}
    try:
        skill = load_skill(folder)
    except SkillLoadError as error:
        return {**row, "runs": runs, "error": "; ".join(error.problems)}
    return {
        **row,
        "description": skill.description,
        "invocation": skill.invocation,
        "blocks": len(skill.blocks),
        "runs": runs,
        "error": None,
    }


def skill_detail(project: Project, skill_id: str) -> dict[str, Any] | None:
    """Everything the skill screen shows, or None for an unknown skill."""
    folder = project.skills_folder / skill_id
    if not is_skill_id(skill_id) or not (folder / SKILL_FILE_NAME).is_file():
        return None
    try:
        skill = load_skill(folder)
    except SkillLoadError as error:
        return {"skill": {"id": skill_id}, "canvas": None, "blocks": {}, "problems": [], "error": error.problems}
    catalog = load_catalog(project.skills_folder, project.agents_folder)
    raw_blocks = load_skill_yaml((folder / SKILL_FILE_NAME).read_text(encoding="utf-8"))["blocks"]
    problems = [
        {"level": problem.level, "location": problem.location, "message": problem.message}
        for problem in validate_skill(skill, catalog)
    ]
    return {
        "skill": skill_facts(skill),
        "canvas": skill_canvas(skill),
        "blocks": {
            block.id: {**block_details(skill, block), "editable": editable_values(raw_blocks, block)}
            for block in skill.blocks.values()
        },
        "problems": problems,
        "error": None,
    }


def skill_facts(skill: Skill) -> dict[str, Any]:
    return {
        "id": skill.id,
        "description": skill.description,
        "goal": skill.goal,
        "invocation": skill.invocation,
        "inputs": field_rows(skill.inputs),
        "outputs": field_rows(skill.outputs),
    }


def skill_canvas(skill: Skill) -> dict[str, Any]:
    """The run canvas of one frame: every block and every edge, and nothing that a run adds."""
    frames = [CanvasFrame(skill, parent=None, called_by=None)]
    edges = number_edges(frame_edges(0, frames[0]))
    nodes = block_nodes(frames)
    return {
        "template": canvas_template(frames, edges, {}),
        "start": START_NODE,
        "labels": {node["id"]: node_label(node["block"], [node["type"]], []) for node in nodes},
        "nodes": nodes,
        "edges": canvas_edge_rows(edges),
    }


# --- the side panel: one block's details ---------------------------------------------------------


def block_details(skill: Skill, block: AnyBlock) -> dict[str, Any]:
    """What the side panel shows for one block: its facts, its prose, its fields, and its exits."""
    instruction_value = block.report if isinstance(block, EndBlock) else getattr(block, "instruction", None)
    details: dict[str, Any] = {
        "node": node_id(0, block.id),
        "type": block_type_name(block),
        "description": block.description,
        "hint": node_hint(block),
        "type_meaning": BLOCK_TYPE_MEANINGS[block_type_name(block)],
        "notes": node_notes(block),
        "facts": block_facts(block),
        "instruction": prose_text(skill, instruction_value),
        "instruction_file": instruction_value if instruction_value and instruction_value.endswith(".md") else None,
        "fields": field_rows(block.output) if isinstance(block, TaskBlock | DecisionBlock | ParallelBlock) else [],
        "choices": [],
        "command": None,
        "script_files": [],
        "inputs": [],
        "outputs": [],
        "child_skill": None,
        "exits": [{"to": edge.to_block, "label": edge.text, "hint": edge.hint} for edge in block_edges(0, block)],
    }
    if isinstance(block, DecisionBlock) and block.choices:
        details["choices"] = [{"choice": choice, "meaning": meaning} for choice, meaning in block.choices.items()]
    if isinstance(block, ScriptBlock):
        details["command"] = [str(part) for part in block.run]
        details["script_files"] = script_files(skill, block)
    if isinstance(block, CallBlock):
        details["child_skill"] = block.skill
        details["inputs"] = value_rows(block.inputs)
    if isinstance(block, EndBlock):
        details["outputs"] = value_rows(block.outputs)
    return details


def prose_text(skill: Skill, value: str | None) -> str | None:
    """The instruction or report text, or None when there is none or its `.md` file is missing.

    The loader accepts a missing file; `pskill validate` reports it, and the panel shows that problem.
    """
    if value is None or (value.endswith(".md") and not (skill.folder / value).is_file()):
        return None
    return skill.instruction_text(value)


def editable_values(raw_blocks: dict[str, Any], block: AnyBlock) -> dict[str, Any]:
    """The keys that the skill editor can change for this block, and their values as `skill.yaml` has them."""
    keys = [*COMMON_KEYS, *EDITABLE_KEYS[block_type_name(block)]]
    raw_block = raw_blocks[block.id]
    return {"keys": keys, "values": {key: raw_block[key] for key in keys if key in raw_block}}


def block_facts(block: AnyBlock) -> list[list[str]]:
    """Name and value pairs: who decides, what runs, and the limits that the block sets."""
    facts: list[list[str]] = []
    if isinstance(block, DecisionBlock):
        facts.append(["decider", block.decider])
    if isinstance(block, ParallelBlock):
        facts.append(["for each", value_text(block.for_each)])
        if block.agent is not None:
            facts.append(["agent", block.agent])
        if block.task_name is not None:
            facts.append(["task name", block.task_name])
    if isinstance(block, ScriptBlock):
        facts.append(["parse", block.parse])
        if block.timeout_s is not None:
            facts.append(["timeout", f"{block.timeout_s} s"])
    if isinstance(block, CallBlock):
        facts.append(["skill", block.skill])
    if isinstance(block, EndBlock):
        facts.append(["status", block.status])
    if block.max_visits is not None:
        facts.append(["visits at most", str(block.max_visits)])
    if isinstance(block, RetryableBlock) and block.retries is not None:
        facts.append(["retries", str(block.retries)])
    return facts


def field_rows(fields: FieldMap) -> list[dict[str, Any]]:
    """One row per field, with the rows of its nested fields: an object's properties, or an array's item properties."""
    return [
        {
            "name": name,
            "type": field_type_text(spec),
            "description": spec.description,
            "optional": spec.optional,
            "default": spec.default,
            "values": list(spec.enum) if spec.enum is not None else None,
            "children": field_rows(spec.items.properties if spec.items is not None else spec.properties),
        }
        for name, spec in fields.items()
    ]


SKILL_FILE_PART = re.compile(r"^\{\{\s*skill\.dir\s*\}\}/(.+)$")


def script_files(skill: Skill, block: ScriptBlock) -> list[dict[str, str]]:
    """The files inside the skill folder that the command runs, with their text: they say what the command does."""
    folder = skill.folder.resolve()
    files = []
    for part in block.run:
        match = SKILL_FILE_PART.match(str(part).strip())
        path = (folder / match.group(1)).resolve() if match else None
        if path is None or not path.is_relative_to(folder) or not path.is_file():
            continue
        files.append(
            {"path": path.relative_to(folder).as_posix(), "text": path.read_text(encoding="utf-8", errors="replace")}
        )
    return files


def field_type_text(spec: FieldSpec) -> str:
    """The type in plain words: `string`, `array of integer`, `object with a, b`."""
    if spec.type == "array" and spec.items is not None:
        return f"array of {field_type_text(spec.items)}"
    if spec.type == "object" and spec.properties:
        return f"object with {', '.join(spec.properties)}"
    return spec.type


def value_rows(values: dict[str, Any]) -> list[dict[str, str]]:
    return [{"name": name, "value": value_text(value)} for name, value in values.items()]


def value_text(value: Any) -> str:
    """A YAML value as the author wrote it: text stays text, anything else is compact JSON."""
    return value if isinstance(value, str) else json.dumps(value)
