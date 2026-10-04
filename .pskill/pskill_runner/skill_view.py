"""The skill screen of the viewer (SPEC.md section 14): every skill, and one skill's graph without a run.

It reads the skills in `.pskill/skills/`, never a run's copy. The canvas is the run canvas with no run parts
(no status, no current step, and no timeline), with one change: each call block is drawn as the frame of its
child skill, in the call block's place, and a child's own call blocks are frames inside that frame. A second,
collapsed canvas has only the skill's own blocks, with each call block as one node, for a quick look at the flow.
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
from pskill_runner.validator import agent_names_used, validate_skill
from pskill_runner.viewer_data import (
    BLOCK_TYPE_MEANINGS,
    DOTTED_EDGE_KINDS,
    START_NODE,
    CanvasEdge,
    CanvasFrame,
    block_edges,
    block_nodes,
    block_type_name,
    canvas_edge_rows,
    frame_edges,
    label_token,
    main_line_edges,
    mermaid_text,
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
        return {
            "skill": {"id": skill_id},
            "canvas": None,
            "collapsed_canvas": None,
            "blocks": {},
            "child_blocks": {},
            "problems": [],
            "error": error.problems,
        }
    catalog = load_catalog(project.skills_folder, project.agents_folder)
    raw_blocks = load_skill_yaml((folder / SKILL_FILE_NAME).read_text(encoding="utf-8"))["blocks"]
    problems = [
        {"level": problem.level, "location": problem.location, "message": problem.message}
        for problem in validate_skill(skill, catalog)
    ]
    frames = skill_frames(skill, catalog.skills)
    return {
        "skill": skill_facts(skill),
        "canvas": skill_canvas(frames),
        "collapsed_canvas": skill_canvas(frames[:1]),  # the toggle that collapses the child skills: no frames
        "blocks": {
            block.id: {
                **block_details(skill, block, catalog.agent_names),
                "editable": editable_values(raw_blocks, block),
            }
            for block in skill.blocks.values()
        },
        "child_blocks": child_block_details(frames, catalog.agent_names),
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


def skill_frames(skill: Skill, skills: dict[str, Skill]) -> list[CanvasFrame]:
    """The skill, then one frame per call block of each frame: its child skill, and that child's own children.

    A child that does not load (it is not in `skills`) gets no frame. A call back into a skill of its own chain
    gets none either, so a call cycle (which `pskill validate` reports) cannot loop forever.
    """
    frames = [CanvasFrame(skill, parent=None, called_by=None)]

    def add_children(parent: int, chain: frozenset[str]) -> None:
        for block in frames[parent].skill.blocks.values():
            if isinstance(block, CallBlock) and block.skill in skills and block.skill not in chain:
                frames.append(CanvasFrame(skills[block.skill], parent=parent, called_by=block.id))
                add_children(len(frames) - 1, chain | {block.skill})

    add_children(0, frozenset({skill.id}))
    return frames


def frame_id(index: int) -> str:
    return f"f{index}"


def call_frames(frames: list[CanvasFrame]) -> dict[str, int]:
    """The call node that each child frame takes the place of, with the frame's index."""
    return {
        node_id(frame.parent, frame.called_by): index
        for index, frame in enumerate(frames)
        if frame.parent is not None and frame.called_by is not None
    }


def skill_canvas(frames: list[CanvasFrame]) -> dict[str, Any]:
    """Every block and every edge, and nothing that a run adds. A call block is the frame of its child skill.

    The edges keep the call block's node as their end, so the panel lists its exits; only the template and
    the edge ids use the frame. The call edge (from the call block to its child's entry) goes, because the
    frame holds the child.
    """
    calls = call_frames(frames)
    drawn_as = {node: frame_id(index) for node, index in calls.items()}
    edges = [edge for index, frame in enumerate(frames) for edge in frame_edges(index, frame) if edge.kind != "call"]
    number_edges(edges, drawn_as)
    nodes = block_nodes(frames)
    labels = {node["id"]: node_label(node["block"], [node["type"]], []) for node in nodes}
    for index in calls.values():
        frame = frames[index]
        labels[frame_id(index)] = f"<b>{frame.called_by}</b><br/>call: {mermaid_text(frame.skill.id)}"
    return {
        "template": skill_template(frames, edges, calls, drawn_as),
        "start": START_NODE,
        "labels": labels,
        "nodes": nodes,
        "frames": [
            {"id": frame_id(index), "node": node, "token": label_token(frame_id(index))}
            for node, index in calls.items()
        ],
        "edges": canvas_edge_rows(edges),
        "main_edges": main_line_edges(frames, edges),
    }


def skill_template(
    frames: list[CanvasFrame], edges: list[CanvasEdge], calls: dict[str, int], drawn_as: dict[str, str]
) -> str:
    """The Mermaid template: the skill's blocks, with each call block replaced by its child's frame."""

    def frame_lines(index: int, indent: str) -> list[str]:
        lines = []
        for block_id in frames[index].skill.blocks:
            node = node_id(index, block_id)
            child = calls.get(node)
            if child is None:
                lines.append(f'{indent}{node}["{label_token(node)}"]')
            else:
                lines.append(f'{indent}subgraph {frame_id(child)} ["{label_token(frame_id(child))}"]')
                lines += frame_lines(child, indent + "  ")
                lines.append(f"{indent}end")
        return lines

    # A small start dot: Mermaid 12 gives a labeled circle a fixed radius of about 90 px.
    lines = ["flowchart TD", f"  {START_NODE}@{{ shape: sm-circ }}", *frame_lines(0, "  ")]
    for edge in edges:
        arrow = "-.->" if edge.kind in DOTTED_EDGE_KINDS else "-->"
        label = f'|"{edge.label}"|' if edge.label is not None else ""
        source, target = drawn_as.get(edge.source, edge.source), drawn_as.get(edge.target, edge.target)
        lines.append(f"  {source} {arrow}{label} {target}")
    return "\n".join(lines) + "\n"


# --- the side panel: one block's details ---------------------------------------------------------


def child_block_details(frames: list[CanvasFrame], agent_names: set[str]) -> dict[str, dict[str, Any]]:
    """The details of each block of a child frame, by node id: a child block can share a name with a parent block."""
    return {
        node_id(index, block.id): {
            **block_details(frame.skill, block, agent_names, index),
            "skill_id": frame.skill.id,
            "called_by": frame.called_by,
        }
        for index, frame in enumerate(frames)
        if index > 0
        for block in frame.skill.blocks.values()
    }


def block_details(skill: Skill, block: AnyBlock, agent_names: set[str], frame: int = 0) -> dict[str, Any]:
    """What the side panel shows for one block: its facts, its prose, its fields, and its exits.

    `agents` names each agent file that the block uses and that exists, so the panel can link to it. `frame`
    is the canvas frame of the block: 0 for the skill itself, more for a child skill.
    """
    instruction_value = block.report if isinstance(block, EndBlock) else getattr(block, "instruction", None)
    details: dict[str, Any] = {
        "node": node_id(frame, block.id),
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
        "agents": [],
        "for_each_items": [],
        "exits": [{"to": edge.to_block, "label": edge.text, "hint": edge.hint} for edge in block_edges(frame, block)],
    }
    if isinstance(block, DecisionBlock) and block.choices:
        details["choices"] = [{"choice": choice, "meaning": meaning} for choice, meaning in block.choices.items()]
    if isinstance(block, ParallelBlock):
        details["agents"] = [name for name in dict.fromkeys(agent_names_used(block)) if name in agent_names]
        details["for_each_items"] = for_each_items(block.for_each)
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
        facts.append(["for each", for_each_summary(block.for_each)])
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


def for_each_summary(for_each: Any) -> str:
    """A computed list as its expression, a fixed list as its size: the panel shows its items one by one."""
    if not isinstance(for_each, list):
        return value_text(for_each)
    summary = f"a fixed list of {len(for_each)} item{'' if len(for_each) == 1 else 's'}"
    conditional = sum(1 for item in for_each if isinstance(item, dict) and "when" in item)
    return f"{summary}, {conditional} with a when" if conditional else summary


def for_each_items(for_each: Any) -> list[dict[str, Any]]:
    """One card per item of a fixed list: its fields as text, and its `when` apart. A computed list has none."""
    if not isinstance(for_each, list):
        return []
    return [for_each_item(item) for item in for_each]


def for_each_item(item: Any) -> dict[str, Any]:
    if not isinstance(item, dict):
        return {"fields": [["item", value_text(item)]], "when": None}
    fields = [[str(key), value_text(value)] for key, value in item.items() if key != "when"]
    when = item.get("when")
    return {"fields": fields, "when": None if when is None else value_text(when)}


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
