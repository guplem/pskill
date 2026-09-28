"""Static checks of a loaded skill (SPEC.md section 11).

The loader already checked the structure of `skill.yaml`. The validator checks what the structure
cannot express: the graph, the references inside `{{ }}`, the files, and the descriptions.
"""

from dataclasses import dataclass

from pskill_runner.computed_values import find_references, is_single_expression, syntax_errors
from pskill_runner.field_types import FieldMap
from pskill_runner.skill_model import AnyBlock, DecisionBlock, EndBlock, Skill, block_edges, next_targets

DESCRIPTION_LIMIT = 1024


@dataclass(frozen=True)
class Problem:
    level: str  # "error" or "warning"
    location: str
    message: str


def validate_skill(skill: Skill) -> list[Problem]:
    problems: list[Problem] = []
    problems += description_problems(skill)
    problems += field_description_problems("inputs", "the field", skill.inputs)
    problems += field_description_problems("outputs", "the field", skill.outputs)
    problems += target_problems(skill)
    problems += reachability_problems(skill)
    for block in skill.blocks.values():
        problems += block_problems(skill, block)
    problems += loop_warnings(skill)
    problems += unused_instruction_file_warnings(skill)
    return problems


def error(location: str, message: str) -> Problem:
    return Problem(level="error", location=location, message=message)


def warning(location: str, message: str) -> Problem:
    return Problem(level="warning", location=location, message=message)


def description_problems(skill: Skill) -> list[Problem]:
    length = len(skill.description)
    if length > DESCRIPTION_LIMIT:
        return [
            error("description", f"the skill description has {length} characters (the limit is {DESCRIPTION_LIMIT})")
        ]
    return []


def field_description_problems(location: str, field_label: str, fields: FieldMap) -> list[Problem]:
    return [
        error(location, f"{field_label} {name!r} needs a description")
        for name, spec in fields.items()
        if not spec.description
    ]


def target_problems(skill: Skill) -> list[Problem]:
    problems = [
        error("entry", f"the target {edge.to!r} is not a block") for edge in skill.entry if edge.to not in skill.blocks
    ]
    for block in skill.blocks.values():
        for target in next_targets(block):
            if target not in skill.blocks:
                problems.append(error(f"blocks.{block.id}", f"the target {target!r} is not a block"))
    return problems


def reachable_blocks(skill: Skill, start_ids: list[str]) -> set[str]:
    reached: set[str] = set()
    to_visit = [block_id for block_id in start_ids if block_id in skill.blocks]
    while to_visit:
        block_id = to_visit.pop()
        if block_id in reached:
            continue
        reached.add(block_id)
        to_visit += [target for target in next_targets(skill.blocks[block_id]) if target in skill.blocks]
    return reached


def reachability_problems(skill: Skill) -> list[Problem]:
    reached = reachable_blocks(skill, [edge.to for edge in skill.entry])
    return [
        error(f"blocks.{block_id}", "no path from the entry reaches this block")
        for block_id in skill.blocks
        if block_id not in reached
    ]


def block_problems(skill: Skill, block: AnyBlock) -> list[Problem]:
    location = f"blocks.{block.id}"
    problems: list[Problem] = []
    if isinstance(block, DecisionBlock):
        problems += decision_problems(location, block)
    if isinstance(block, EndBlock):
        problems += end_problems(skill, location, block)
    else:
        problems += field_description_problems(location, "the output field", block.output)
        problems += edge_problems(skill, location, block)
    for text in block_texts(skill, block, location, problems):
        problems += text_problems(skill, location, text)
    return problems


def decision_problems(location: str, block: DecisionBlock) -> list[Problem]:
    if block.choices is None:
        problems = []
        if block.decider == "agent":
            problems.append(error(location, "an agent decision needs choices (use a task block for free-form work)"))
        if isinstance(block.next, dict):
            problems.append(error(location, "a choice map in next needs choices"))
        return problems
    if not isinstance(block.next, dict):
        return [error(location, "a decision with choices needs a choice map in next")]
    problems = [
        error(location, f"the choice {choice!r} has no entry in next")
        for choice in block.choices
        if choice not in block.next
    ]
    problems += [
        error(location, f"next has {choice!r}, which is not a choice")
        for choice in block.next
        if choice not in block.choices
    ]
    return problems


def end_problems(skill: Skill, location: str, block: EndBlock) -> list[Problem]:
    problems = [
        error(location, f"{name!r} is not a declared skill output")
        for name in block.outputs
        if name not in skill.outputs
    ]
    if block.status == "succeeded":
        problems += [
            error(location, f"a succeeded end must give the required output {name!r}")
            for name, spec in skill.outputs.items()
            if not spec.optional and name not in block.outputs
        ]
    return problems


def edge_problems(skill: Skill, location: str, block: AnyBlock) -> list[Problem]:
    edges = block_edges(block)
    problems = [
        error(location, "a when must be exactly one {{ ... }}")
        for edge in edges
        if edge.when is not None and not is_single_expression(edge.when)
    ]
    # Choice maps become edges without a when, so this only fires for a real condition list.
    if edges and edges[-1].when is not None:
        problems.append(warning(location, "the last edge has a when, so no edge may match"))
    return problems


def block_texts(skill: Skill, block: AnyBlock, location: str, problems: list[Problem]) -> list[str]:
    """Every text of a block that may contain {{ }}. A missing instruction file is reported in problems."""
    texts = [edge.when for edge in block_edges(block) if edge.when is not None]
    prose_values: list[str] = []
    if isinstance(block, EndBlock):
        texts += [value for value in block.outputs.values() if isinstance(value, str)]
        if block.report is not None:
            prose_values.append(block.report)
    else:
        prose_values.append(block.instruction)
    for value in prose_values:
        if value.endswith(".md") and not (skill.folder / value).is_file():
            problems.append(error(location, f"the file {value!r} does not exist"))
        else:
            texts.append(skill.instruction_text(value))
    return texts


def text_problems(skill: Skill, location: str, text: str) -> list[Problem]:
    compile_errors = syntax_errors(text)
    if compile_errors:
        return [error(location, f"the {{{{ }}}} does not compile: {compile_errors[0]}")]
    problems = []
    for namespace, name in sorted(find_references(text)):
        if namespace == "inputs" and name not in skill.inputs:
            problems.append(error(location, f"'inputs.{name}' is not a declared input"))
        if namespace in ("steps", "history") and name not in skill.blocks:
            problems.append(error(location, f"'{namespace}.{name}' is not a block"))
    return problems


def loop_warnings(skill: Skill) -> list[Problem]:
    """Warn once per loop in which no block has max_visits (SPEC.md D11)."""
    reach = {block_id: reachable_blocks(skill, next_targets(block)) for block_id, block in skill.blocks.items()}
    problems = []
    seen_loops: set[frozenset[str]] = set()
    for block_id in sorted(skill.blocks):
        if block_id not in reach[block_id]:
            continue
        members = frozenset(other for other in reach[block_id] if block_id in reach[other]) | {block_id}
        if members in seen_loops:
            continue
        seen_loops.add(members)
        if all(skill.blocks[member].max_visits is None for member in members):
            listed = ", ".join(sorted(members))
            problems.append(warning(f"blocks.{block_id}", f"this loop ({listed}) has no block with max_visits"))
    return problems


def unused_instruction_file_warnings(skill: Skill) -> list[Problem]:
    used = set()
    for block in skill.blocks.values():
        used.add(block.report if isinstance(block, EndBlock) else block.instruction)
    instruction_folder = skill.folder / "instructions"
    if not instruction_folder.is_dir():
        return []
    problems = []
    for path in sorted(instruction_folder.rglob("*.md")):
        relative_path = path.relative_to(skill.folder).as_posix()
        if relative_path not in used:
            problems.append(warning(relative_path, "no block uses this instruction file"))
    return problems
