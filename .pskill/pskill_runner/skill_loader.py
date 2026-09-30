"""Load a skill folder: read `skill.yaml`, check its structure, and build the typed model."""

from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator

from pskill_runner.field_types import parse_field_map
from pskill_runner.skill_model import (
    AnyBlock,
    CallBlock,
    ChoiceMap,
    DecisionBlock,
    Edge,
    EndBlock,
    ParallelBlock,
    ScriptBlock,
    Skill,
    SkillCatalog,
    TaskBlock,
)
from pskill_runner.skill_schema import BLOCK_SCHEMAS, TOP_LEVEL_SCHEMA
from pskill_runner.yaml_loading import load_skill_yaml

SKILL_FILE_NAME = "skill.yaml"


class SkillLoadError(Exception):
    """A skill folder could not be loaded. `problems` lists every reason in plain words."""

    def __init__(self, problems: list[str]) -> None:
        super().__init__("; ".join(problems))
        self.problems = problems


def load_skill(folder: Path) -> Skill:
    raw = read_skill_file(folder / SKILL_FILE_NAME)
    problems = structure_problems(raw, folder.name)
    if problems:
        raise SkillLoadError(problems)
    return build_skill(raw, folder)


def read_skill_file(path: Path) -> dict[str, Any]:
    try:
        raw = load_skill_yaml(path.read_text(encoding="utf-8"))
    except OSError as error:
        raise SkillLoadError([f"{path.name} cannot be read: {error}"]) from error
    except yaml.YAMLError as error:
        raise SkillLoadError([f"{path.name} is not valid YAML: {error}"]) from error
    if not isinstance(raw, dict):
        raise SkillLoadError([f"{path.name} must be a mapping of keys, such as 'id: my-skill'"])
    return raw


def structure_problems(raw: dict[str, Any], folder_name: str) -> list[str]:
    """Check the top level, then each block against the schema of its type."""
    problems = schema_problems(raw, TOP_LEVEL_SCHEMA, location="")
    if problems:
        return problems
    if raw["id"] != folder_name:
        problems.append(f"id: {raw['id']!r} does not match the folder name {folder_name!r}")
    for block_id, raw_block in raw["blocks"].items():
        location = f"blocks.{block_id}"
        block_type = raw_block["type"]
        if block_type not in BLOCK_SCHEMAS:
            known_types = ", ".join(sorted(BLOCK_SCHEMAS))
            problems.append(f"{location}: unknown block type {block_type!r} (known types: {known_types})")
            continue
        problems.extend(schema_problems(raw_block, BLOCK_SCHEMAS[block_type], location))
    return problems


def schema_problems(value: Any, schema: dict[str, Any], location: str) -> list[str]:
    problems = []
    for error in sorted(Draft202012Validator(schema).iter_errors(value), key=lambda item: list(item.path)):
        path = ".".join([location, *(str(part) for part in error.path)]).strip(".") or "skill.yaml"
        problems.append(f"{path}: {error.message}")
    return problems


def build_skill(raw: dict[str, Any], folder: Path) -> Skill:
    return Skill(
        id=raw["id"],
        description=raw["description"],
        goal=raw["goal"],
        invocation=raw.get("invocation", "auto"),
        inputs=parse_field_map(raw.get("inputs", {})),
        outputs=parse_field_map(raw.get("outputs", {})),
        entry=parse_edges(raw["entry"]),
        blocks={block_id: build_block(block_id, raw_block) for block_id, raw_block in raw["blocks"].items()},
        folder=folder,
    )


def parse_edges(raw: str | list[dict[str, str]]) -> list[Edge]:
    if isinstance(raw, str):
        return [Edge(to=raw)]
    return [Edge(to=item["to"], when=item.get("when")) for item in raw]


def build_block(block_id: str, raw: dict[str, Any]) -> AnyBlock:
    common: dict[str, Any] = {
        "id": block_id,
        "description": raw.get("description"),
        "max_visits": raw.get("max_visits"),
        "on_max_visits": raw.get("on_max_visits"),
    }
    block_type = raw["type"]
    retryable: dict[str, Any] = {**common, "retries": raw.get("retries")}
    if block_type == "task":
        return TaskBlock(
            **retryable,
            instruction=raw["instruction"],
            output=parse_field_map(raw["output"]),
            next=parse_edges(raw["next"]),
        )
    if block_type == "decision":
        raw_next = raw["next"]
        next_blocks: list[Edge] | ChoiceMap = (
            {choice: parse_edges(edges) for choice, edges in raw_next.items()}
            if isinstance(raw_next, dict)
            else parse_edges(raw_next)
        )
        return DecisionBlock(
            **retryable,
            decider=raw["decider"],
            instruction=raw["instruction"],
            choices=raw.get("choices"),
            output=parse_field_map(raw.get("output", {})),
            next=next_blocks,
        )
    if block_type == "parallel":
        return ParallelBlock(
            **retryable,
            for_each=raw["for_each"],
            agent=raw.get("agent"),
            task_name=raw.get("task_name"),
            instruction=raw["instruction"],
            output=parse_field_map(raw["output"]),
            next=parse_edges(raw["next"]),
        )
    if block_type == "script":
        return ScriptBlock(
            **retryable,
            run=raw["run"],
            parse=raw.get("parse", "text"),
            timeout_s=raw.get("timeout_s"),
            next=parse_edges(raw["next"]),
        )
    if block_type == "call":
        return CallBlock(**common, skill=raw["skill"], inputs=raw.get("inputs", {}), next=parse_edges(raw["next"]))
    if block_type == "end":
        return EndBlock(**common, status=raw["status"], outputs=raw.get("outputs", {}), report=raw.get("report"))
    raise ValueError(f"Unknown block type: {block_type}")


def load_catalog(skills_folder: Path, agents_folder: Path) -> SkillCatalog:
    """Load every valid skill and list every agent file. Invalid skills are left out."""
    skills: dict[str, Skill] = {}
    if skills_folder.is_dir():
        for folder in sorted(skills_folder.iterdir()):
            if not (folder / SKILL_FILE_NAME).is_file():
                continue
            try:
                skills[folder.name] = load_skill(folder)
            except SkillLoadError:
                continue
    agent_names = {path.stem for path in agents_folder.glob("*.md")} if agents_folder.is_dir() else set()
    return SkillCatalog(skills=skills, agent_names=agent_names)
