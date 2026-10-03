"""Static checks of a loaded skill (SPEC.md section 11).

The loader already checked the structure of `skill.yaml`. The validator checks what the structure
cannot express: the graph, the references inside `{{ }}`, the files, and the descriptions.
"""

from dataclasses import dataclass

from pskill_runner.computed_values import (
    ComputedValueError,
    compute,
    find_references,
    is_single_expression,
    syntax_errors,
)
from pskill_runner.field_types import FieldMap
from pskill_runner.skill_model import (
    AnyBlock,
    CallBlock,
    DecisionBlock,
    Edge,
    EndBlock,
    ParallelBlock,
    ScriptBlock,
    Skill,
    SkillCatalog,
    block_edges,
    next_targets,
)

DESCRIPTION_LIMIT = 1024


@dataclass(frozen=True)
class Problem:
    level: str  # "error" or "warning"
    location: str
    message: str


def validate_skill(skill: Skill, catalog: SkillCatalog | None = None) -> list[Problem]:
    """Check one skill. With a catalog, also check its calls and its agents against the project."""
    problems: list[Problem] = []
    problems += description_problems(skill)
    problems += field_description_problems("inputs", "the field", skill.inputs)
    problems += field_description_problems("outputs", "the field", skill.outputs)
    problems += target_problems(skill)
    problems += reachability_problems(skill)
    for block in skill.blocks.values():
        problems += block_problems(skill, block)
        if catalog is not None:
            problems += catalog_problems(skill, block, catalog)
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
        problems += edge_problems(skill, location, block)
    if isinstance(block, ParallelBlock):
        problems += item_when_problems(location, block)
    output = block_output(block)
    if output is not None:
        problems += field_description_problems(location, "the output field", output)
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
    problems = [
        error(location, "a when must be exactly one {{ ... }}")
        for edge in block_edges(block)
        if edge.when is not None and not is_single_expression(edge.when)
    ]
    for owner, edges in edge_lists(block):
        if edges and edges[-1].when is not None:
            problems.append(warning(location, f"{owner}the last edge has a when, so no edge may match"))
    return problems


def item_when_problems(location: str, block: ParallelBlock) -> list[Problem]:
    """Each `when` of a fixed `for_each` list follows the same rule as an edge's `when`."""
    if not isinstance(block.for_each, list):
        return []
    return [
        error(location, "a when must be exactly one {{ ... }}")
        for item in block.for_each
        if isinstance(item, dict) and "when" in item
        if not (isinstance(item["when"], str) and is_single_expression(item["when"]))
    ]


def edge_lists(block: AnyBlock) -> list[tuple[str, list[Edge]]]:
    """Each list in which the first matching edge wins, with a prefix that names its choice."""
    if isinstance(block, EndBlock):  # pragma: no cover - edge_problems skips end blocks; this narrows the type
        return []
    if isinstance(block.next, dict):
        return [(f"the choice {choice!r}: ", edges) for choice, edges in block.next.items()]
    return [("", block.next)]


def block_output(block: AnyBlock) -> FieldMap | None:
    """The output fields that the agent returns for this block, if any."""
    if isinstance(block, EndBlock | ScriptBlock | CallBlock):
        return None
    return block.output


def prose_value(block: AnyBlock) -> str | None:
    """The `instruction` (or the `report` of an end block): a `.md` path or the text itself."""
    if isinstance(block, EndBlock):
        return block.report
    if isinstance(block, ScriptBlock | CallBlock):
        return None
    return block.instruction


def string_values(values: list[object]) -> list[str]:
    return [value for value in values if isinstance(value, str)]


def nested_strings(value: object) -> list[str]:
    """Every string inside a value, at any depth: a fixed `for_each` list holds them in its items."""
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [text for item in value for text in nested_strings(item)]
    if isinstance(value, dict):
        return [text for item in value.values() for text in nested_strings(item)]
    return []


def block_texts(skill: Skill, block: AnyBlock, location: str, problems: list[Problem]) -> list[str]:
    """Every text of a block that may contain {{ }}. A missing instruction file is reported in problems."""
    texts = [edge.when for edge in block_edges(block) if edge.when is not None]
    if isinstance(block, EndBlock):
        texts += string_values(list(block.outputs.values()))
    if isinstance(block, ScriptBlock):
        texts += string_values(block.run)
    if isinstance(block, CallBlock):
        texts += string_values(list(block.inputs.values()))
    if isinstance(block, ParallelBlock):
        texts += nested_strings(block.for_each) + string_values([block.agent, block.task_name])
    prose = prose_value(block)
    if prose is not None:
        if prose.endswith(".md") and not (skill.folder / prose).is_file():
            problems.append(error(location, f"the file {prose!r} does not exist"))
        else:
            texts.append(skill.instruction_text(prose))
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
    used = {prose_value(block) for block in skill.blocks.values()}
    instruction_folder = skill.folder / "instructions"
    if not instruction_folder.is_dir():
        return []
    problems = []
    for path in sorted(instruction_folder.rglob("*.md")):
        relative_path = path.relative_to(skill.folder).as_posix()
        if relative_path not in used:
            problems.append(warning(relative_path, "no block uses this instruction file"))
    return problems


def catalog_problems(skill: Skill, block: AnyBlock, catalog: SkillCatalog) -> list[Problem]:
    location = f"blocks.{block.id}"
    if isinstance(block, CallBlock):
        return call_problems(skill, block, catalog, location)
    if isinstance(block, ParallelBlock):
        return [
            error(location, f"there is no agent file '{name}.md' in .pskill/agents/")
            for name in agent_names_used(block)
            if name not in catalog.agent_names
        ]
    return []


def call_problems(skill: Skill, block: CallBlock, catalog: SkillCatalog, location: str) -> list[Problem]:
    callee = catalog.skills.get(block.skill)
    if callee is None:
        return [error(location, f"there is no skill {block.skill!r}")]
    problems = [
        error(location, f"{name!r} is not an input of the skill {callee.id!r}")
        for name in block.inputs
        if name not in callee.inputs
    ]
    problems += [
        error(location, f"the required input {name!r} of the skill {callee.id!r} is missing")
        for name, spec in callee.inputs.items()
        if not spec.optional and spec.default is None and name not in block.inputs
    ]
    cycle = call_path(catalog, start=callee.id, goal=skill.id, visited=set())
    if cycle is not None:
        chain = " > ".join([skill.id, *cycle])
        problems.append(error(location, f"the call to {callee.id!r} makes a cycle ({chain})"))
    return problems


def call_path(catalog: SkillCatalog, start: str, goal: str, visited: set[str]) -> list[str] | None:
    """A chain of calls from `start` to `goal` (both included), or None when there is none."""
    if start == goal:
        return [start]
    if start in visited or start not in catalog.skills:
        return None
    visited.add(start)
    for block in catalog.skills[start].blocks.values():
        if isinstance(block, CallBlock):
            rest = call_path(catalog, block.skill, goal, visited)
            if rest is not None:
                return [start, *rest]
    return None


def agent_names_used(block: ParallelBlock) -> list[str]:
    """The agent names that the validator can know: a plain name, or one per item of a fixed list."""
    if block.agent is None:
        return []
    if "{{" not in block.agent:
        return [block.agent]
    if not isinstance(block.for_each, list):
        return []  # A list computed during the run: the agent names are checked at run time.
    names = []
    for item in block.for_each:
        try:
            names.append(str(compute(block.agent, {"item": item})))
        except ComputedValueError:
            continue
    return names
