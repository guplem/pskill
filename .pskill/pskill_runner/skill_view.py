"""The skill screen of the viewer (SPEC.md section 14): every skill, and one skill's graph without a run.

It reads the skills in `.pskill/skills/`, never a run's copy. The canvas is the run canvas of one frame,
with no run parts: no status, no current step, and no timeline.
"""

import json
from pathlib import Path
from typing import Any

from pskill_runner.engine import list_runs
from pskill_runner.field_types import FieldMap, FieldSpec
from pskill_runner.project import Project
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
from pskill_runner.validator import validate_skill
from pskill_runner.viewer_data import (
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
    number_edges,
)


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
    if not (folder / SKILL_FILE_NAME).is_file():
        return None
    try:
        skill = load_skill(folder)
    except SkillLoadError as error:
        return {"skill": {"id": skill_id}, "canvas": None, "blocks": {}, "problems": [], "error": error.problems}
    catalog = load_catalog(project.skills_folder, project.agents_folder)
    problems = [
        {"level": problem.level, "location": problem.location, "message": problem.message}
        for problem in validate_skill(skill, catalog)
    ]
    return {
        "skill": skill_facts(skill),
        "canvas": skill_canvas(skill),
        "blocks": {block.id: block_details(skill, block) for block in skill.blocks.values()},
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
        "facts": block_facts(block),
        "instruction": skill.instruction_text(instruction_value) if instruction_value is not None else None,
        "instruction_file": instruction_value if instruction_value and instruction_value.endswith(".md") else None,
        "fields": field_rows(block.output) if isinstance(block, TaskBlock | DecisionBlock | ParallelBlock) else [],
        "choices": [],
        "command": None,
        "inputs": [],
        "outputs": [],
        "child_skill": None,
        "exits": [{"to": edge.to_block, "label": edge.text, "hint": edge.hint} for edge in block_edges(0, block)],
    }
    if isinstance(block, DecisionBlock) and block.choices:
        details["choices"] = [{"choice": choice, "meaning": meaning} for choice, meaning in block.choices.items()]
    if isinstance(block, ScriptBlock):
        details["command"] = [str(part) for part in block.run]
    if isinstance(block, CallBlock):
        details["child_skill"] = block.skill
        details["inputs"] = value_rows(block.inputs)
    if isinstance(block, EndBlock):
        details["outputs"] = value_rows(block.outputs)
    return details


def block_facts(block: AnyBlock) -> list[list[str]]:
    """Name and value pairs: who decides, what runs, and the limits that the block sets."""
    facts: list[list[str]] = []
    if isinstance(block, DecisionBlock):
        facts.append(["decider", block.decider])
    if isinstance(block, ParallelBlock):
        facts.append(["for each", value_text(block.for_each)])
        if block.agent is not None:
            facts.append(["agent", block.agent])
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
    return [
        {
            "name": name,
            "type": field_type_text(spec),
            "description": spec.description,
            "optional": spec.optional,
            "values": list(spec.enum) if spec.enum is not None else None,
        }
        for name, spec in fields.items()
    ]


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
