"""Export a skill as plain Markdown skills (`SKILL.md`) that any agent can follow without pskill.

No runner checks the agent in an exported skill, so the export can only describe the graph clearly:
each block becomes a numbered step in graph order, each edge a "go to step N" line, each output field a
"write down" line, and each `{{ }}` value a plain name (`create_plan.plan`). The skill's scripts and
pskill agents come with it, and each child skill of a call block is exported next to it.
"""

import io
import json
import re
import zipfile
from typing import Any

from pskill_runner.field_types import FieldMap, FieldSpec
from pskill_runner.project import Project
from pskill_runner.skill_loader import SKILL_FILE_NAME, SkillLoadError, load_skill
from pskill_runner.skill_model import (
    AnyBlock,
    CallBlock,
    DecisionBlock,
    Edge,
    EndBlock,
    ParallelBlock,
    ScriptBlock,
    Skill,
    TaskBlock,
    next_targets,
)
from pskill_runner.skill_schema import is_skill_id

EXPORTED_FILE_NAME = "SKILL.md"
SKILL_FOLDER_TEXT = "<this skill's folder>"
SCRIPTS_FOLDER = "scripts"
SUBAGENTS_FOLDER = "subagents"  # not `agents/`: Codex reads `agents/openai.yaml` in a skill folder
VALUE = re.compile(r"\{\{-?(.*?)-?\}\}", re.S)
STATEMENT = re.compile(r"\{%-?(.*?)-?%\}", re.S)
COMMENT = re.compile(r"\{#.*?#\}", re.S)
FIELD_TYPE_WORDS = {
    "string": "text",
    "integer": "whole number",
    "number": "number",
    "boolean": "true or false",
    "array": "list",
    "object": "object",
}

HOW_TO_FOLLOW = """\
## How to follow this skill

- Do one step at a time. After each step, go to the step that its **Next** part names. Never skip a step.
- Write down what each step asks for, under the step's name. Later steps read these values by name:
  `create_plan.plan` is the `plan` value of the step `create_plan`, and `inputs.topic` is the input `topic`.
  `<step>.all_visits` is the list of every answer of a step, oldest first.
- A value in backticks such as `(review.findings | length) > 0` is an expression over these values:
  `a | length` is the number of items in `a`, and `a | default(b)` is `a`, or `b` when `a` has no value yet.
- Run every command from the project root. `<this skill's folder>` is the folder that holds this file.
  In a command, `<name>` stands for the value `name`: put it in quotes when it has spaces or several lines.
- When the user asked you to work without questions, take each "Ask the user" step yourself: decide as the
  user would, and say why.
"""


class ExportError(Exception):
    """The skill cannot be exported: it does not exist, or it does not load."""


def export_zip(project: Project, skill_id: str) -> bytes:
    """The export as one zip file: a folder per skill, ready to copy into a skills folder."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for path, content in sorted(export_skill(project, skill_id).items()):
            archive.writestr(path, content)
    return buffer.getvalue()


def export_skill(project: Project, skill_id: str) -> dict[str, bytes]:
    """Every file of the export, by its path in the export: `<skill>/SKILL.md`, its scripts, its agents."""
    files: dict[str, bytes] = {}
    add_skill(project, skill_id, files)
    return files


def add_skill(project: Project, skill_id: str, files: dict[str, bytes]) -> None:
    skill = load_exported_skill(project, skill_id)
    files[f"{skill.id}/{EXPORTED_FILE_NAME}"] = skill_markdown(skill, project.config.retries).encode("utf-8")
    scripts_folder = skill.folder / SCRIPTS_FOLDER
    if scripts_folder.is_dir():
        for path in sorted(scripts_folder.rglob("*")):
            if path.is_file() and "__pycache__" not in path.parts:
                files[f"{skill.id}/{SCRIPTS_FOLDER}/{path.relative_to(scripts_folder).as_posix()}"] = path.read_bytes()
    for name in sorted(agent_names(skill)):
        agent_file = project.agents_folder / f"{name}.md"
        if agent_file.is_file():
            files[f"{skill.id}/{SUBAGENTS_FOLDER}/{name}.md"] = agent_file.read_bytes()
    for block in skill.blocks.values():
        if isinstance(block, CallBlock) and f"{block.skill}/{EXPORTED_FILE_NAME}" not in files:
            add_skill(project, block.skill, files)


def load_exported_skill(project: Project, skill_id: str) -> Skill:
    folder = project.skills_folder / skill_id
    if not is_skill_id(skill_id) or not (folder / SKILL_FILE_NAME).is_file():
        raise ExportError(f"There is no skill {skill_id!r} in {project.skills_folder}.")
    try:
        return load_skill(folder)
    except SkillLoadError as error:
        raise ExportError(f"The skill {skill_id!r} does not load: {'; '.join(error.problems)}") from error


def prose(skill: Skill, value: str) -> str:
    """An instruction or report text. A missing `.md` file stops the export (the loader accepts it)."""
    if value.endswith(".md") and not (skill.folder / value).is_file():
        raise ExportError(f"The skill {skill.id!r} names the file {value}, which is missing.")
    return skill.instruction_text(value)


def agent_names(skill: Skill) -> set[str]:
    """The pskill agents that the parallel blocks name, also through `{{ item.agent }}` over a YAML list."""
    names: set[str] = set()
    for block in skill.blocks.values():
        if not isinstance(block, ParallelBlock) or block.agent is None:
            continue
        if "{{" not in block.agent:
            names.add(block.agent)
        elif isinstance(block.for_each, list):
            names.update(str(item["agent"]) for item in block.for_each if isinstance(item, dict) and "agent" in item)
    return names


# --- the Markdown ---------------------------------------------------------------------------------


def skill_markdown(skill: Skill, default_retries: int) -> str:
    order = graph_order(skill)
    numbers = {block_id: index + 1 for index, block_id in enumerate(order)}
    frontmatter = [f"name: {skill.id}", f"description: {json.dumps(' '.join(skill.description.split()))}"]
    if skill.invocation in ("manual", "internal"):
        frontmatter.append("disable-model-invocation: true")
    parts = [
        "---\n" + "\n".join(frontmatter) + "\n---",
        f"# {skill.id}",
        f"**Goal:** {skill.goal}",
        HOW_TO_FOLLOW.rstrip(),
        "## Inputs\n\n" + (field_lines(skill.inputs) if skill.inputs else "This skill has no inputs."),
    ]
    if skill.outputs:
        parts.append(
            "## Outputs\n\nThe end step gives these values to whoever started the skill:\n\n"
            + field_lines(skill.outputs)
        )
    parts.append("## Start\n\n" + edge_lines(skill.entry, numbers, skill))
    parts += [step_markdown(skill, skill.blocks[block_id], numbers, default_retries) for block_id in order]
    return "\n\n".join(parts) + "\n"


def graph_order(skill: Skill) -> list[str]:
    """The blocks in the order that a run meets them first (breadth first from the entry)."""
    order: list[str] = []
    queue = [edge.to for edge in skill.entry]
    while queue:
        block_id = queue.pop(0)
        if block_id in order or block_id not in skill.blocks:
            continue
        order.append(block_id)
        queue += next_targets(skill.blocks[block_id])
    return order + [block_id for block_id in skill.blocks if block_id not in order]


def step_markdown(skill: Skill, block: AnyBlock, numbers: dict[str, int], default_retries: int) -> str:
    lines = [f"## Step {numbers[block.id]}: `{block.id}`"]
    if block.description:
        lines.append(f"_{block.description}_")
    lines += block_body(skill, block, default_retries)
    if not isinstance(block, EndBlock):
        lines.append("**Next:**\n\n" + next_lines(skill, block, numbers))
    if block.max_visits is not None:
        lines.append(visit_cap_line(block, numbers))
    return "\n\n".join(lines)


def block_body(skill: Skill, block: AnyBlock, default_retries: int) -> list[str]:
    if isinstance(block, TaskBlock):
        return ["Do this:", plain_text(prose(skill, block.instruction)), write_down(block.id, block.output)]
    if isinstance(block, DecisionBlock):
        return decision_body(skill, block)
    if isinstance(block, ParallelBlock):
        return parallel_body(skill, block)
    if isinstance(block, ScriptBlock):
        return script_body(block, default_retries)
    if isinstance(block, CallBlock):
        return call_body(block)
    return end_body(skill, block)


def decision_body(skill: Skill, block: DecisionBlock) -> list[str]:
    if block.decider == "human":
        opening = "Ask the user one question, and wait for the answer. Prepare the question like this:"
    else:
        opening = "Decide this yourself:"
    lines = [opening, plain_text(prose(skill, block.instruction))]
    if block.choices:
        lines.append(
            "The choices:\n\n" + "\n".join(f"- `{choice}`: {meaning}" for choice, meaning in block.choices.items())
        )
        fixed = [
            "- `choice`: the choice that was picked.",
            "- `rationale`: why this choice. For a choice of the user, their own words.",
        ]
        hint = "When the reply matches no choice exactly, pick the closest choice. When no choice fits, ask again."
        lines.append(write_down(block.id, block.output, fixed) + ("\n\n" + hint if block.decider == "human" else ""))
    else:
        lines.append(write_down(block.id, block.output, ["- `answer`: the user's answer."]))
    return lines


def parallel_body(skill: Skill, block: ParallelBlock) -> list[str]:
    items = f"`{condition_text(block.for_each)}`" if isinstance(block.for_each, str) else "this list"
    lines = [
        f"For each item of {items}, do the task below. Use one subagent per item when you can: give each "
        "subagent only its own item and the task, so no subagent sees the others. When you cannot start "
        "subagents, do the items one by one yourself. In the task, `item` is the current item."
    ]
    if isinstance(block.for_each, list):
        lines.append("\n".join(f"- `{json.dumps(item)}`" for item in block.for_each))
    if block.agent is not None and "{{" not in block.agent:
        lines.append(f"Give each subagent the role in `{SUBAGENTS_FOLDER}/{block.agent}.md` first.")
    elif block.agent is not None:
        lines.append(
            f"Give each subagent a role first: the file `{SUBAGENTS_FOLDER}/<name>.md`, where the name is "
            f"`{condition_text(block.agent)}`."
        )
    if block.task_name is not None:
        lines.append(f"Name each task: {plain_text(block.task_name)}.")
    lines += ["The task:", plain_text(prose(skill, block.instruction))]
    lines.append(
        f"**Write down:** `{block.id}.results`, the list of the answers of every item, in item order. "
        "Each answer holds:\n\n" + field_lines(block.output)
    )
    return lines


def script_body(block: ScriptBlock, default_retries: int) -> list[str]:
    lines = ["Run this command:", f"`{command_text(block.run)}`"]
    produced = [f"- `{block.id}.stdout`: what the command printed.", f"- `{block.id}.exit_code`: its exit code."]
    if isinstance(block.input, dict):
        values = "\n".join(f"- `{name}`: {plain_value(value)}" for name, value in block.input.items())
        lines.append("Send it this JSON object on its standard input:\n\n" + values)
    elif block.input is not None:
        lines.append(f"Send it this text on its standard input: {plain_value(block.input)}")
    if block.parse == "json":
        lines.append(f"The command prints JSON: write it down as `{block.id}.json`.")
    retries = block.retries if block.retries is not None else default_retries
    if retries == 0:
        lines.append("If the command fails, stop and tell the user why.")
    else:
        lines.append(
            f"If the command fails, run it again, up to {retries} more times. Then stop and tell the user why."
        )
    lines.append("**Write down:**\n\n" + "\n".join(produced))
    return lines


def call_body(block: CallBlock) -> list[str]:
    inputs = "\n".join(f"- `{name}`: {plain_value(value)}" for name, value in block.inputs.items())
    return [
        f"Follow the skill `{block.skill}` in the folder `{block.skill}/` next to this skill's folder, "
        "from its start to its end, with these inputs:",
        inputs or "(no inputs)",
        f"When it ends, come back here. **Write down:** `{block.id}.status` (succeeded, failed, or cancelled) "
        f"and `{block.id}.outputs` (the outputs of its end step).",
    ]


def end_body(skill: Skill, block: EndBlock) -> list[str]:
    lines = [f"The skill ends here with the status **{block.status}**."]
    if block.outputs:
        outputs = "\n".join(f"- `{name}`: {plain_value(value)}" for name, value in block.outputs.items())
        lines.append("Its outputs:\n\n" + outputs)
    if block.report is not None:
        lines.append(f"Tell the user: {plain_text(prose(skill, block.report))}")
    return lines


def next_lines(skill: Skill, block: AnyBlock, numbers: dict[str, int]) -> str:
    if isinstance(block, DecisionBlock) and isinstance(block.next, dict):
        return "\n".join(choice_lines(choice, edges, numbers) for choice, edges in block.next.items())
    edges = block.next if not isinstance(block, EndBlock) and isinstance(block.next, list) else []
    return edge_lines(edges, numbers, skill)


def edge_lines(edges: list[Edge], numbers: dict[str, int], skill: Skill) -> str:
    if len(edges) == 1 and edges[0].when is None:
        return f"- Go to {step_link(edges[0].to, numbers)}."
    lines = []
    for edge in edges:
        if edge.when is None:
            lines.append(f"- Otherwise: go to {step_link(edge.to, numbers)}.")
        else:
            lines.append(f"- When `{condition_text(edge.when)}`: go to {step_link(edge.to, numbers)}.")
    return "\n".join(lines)


def choice_lines(choice: str, edges: list[Edge], numbers: dict[str, int]) -> str:
    if len(edges) == 1 and edges[0].when is None:
        return f"- If the choice is `{choice}`: go to {step_link(edges[0].to, numbers)}."
    lines = []
    for edge in edges:
        if edge.when is None:
            lines.append(
                f"- If the choice is `{choice}`, and no condition above matches: go to {step_link(edge.to, numbers)}."
            )
        else:
            lines.append(
                f"- If the choice is `{choice}` and `{condition_text(edge.when)}`: go to {step_link(edge.to, numbers)}."
            )
    return "\n".join(lines)


def visit_cap_line(block: AnyBlock, numbers: dict[str, int]) -> str:
    cap = block.max_visits or 0
    limit = f"Do this step at most {cap} time{'s' if cap != 1 else ''}. The {ordinal(cap + 1)} time,"
    if block.on_max_visits is None:
        return f"{limit} stop instead, and tell the user that this step reached its limit."
    return f"{limit} go to {step_link(block.on_max_visits, numbers)} instead."


def step_link(block_id: str, numbers: dict[str, int]) -> str:
    return f"step {numbers[block_id]} (`{block_id}`)"


def ordinal(number: int) -> str:
    if 10 <= number % 100 <= 20:
        return f"{number}th"
    return f"{number}{ {1: 'st', 2: 'nd', 3: 'rd'}.get(number % 10, 'th') }"


# --- fields and values ----------------------------------------------------------------------------


def write_down(block_id: str, fields: FieldMap, fixed: list[str] | None = None) -> str:
    lines = [*(fixed or []), *field_lines(fields).splitlines()] if fields else list(fixed or [])
    if not lines:
        return "**Write down:** that this step is done."
    return f"**Write down,** under `{block_id}`:\n\n" + "\n".join(lines)


def field_lines(fields: FieldMap) -> str:
    return "\n".join(
        f"- `{name}` ({field_type_words(spec)}): {spec.description or ''}".rstrip(": ") for name, spec in fields.items()
    )


def field_type_words(spec: FieldSpec) -> str:
    words = FIELD_TYPE_WORDS[spec.type]
    if spec.type == "array" and spec.items is not None:
        words = f"list of {field_type_words(spec.items)}"
    elif spec.type == "object" and spec.properties:
        words = f"object with {', '.join(f'`{name}`' for name in spec.properties)}"
    if spec.optional:
        words += ", optional"
    if spec.enum is not None:
        words += ", one of: " + ", ".join(f"`{value}`" for value in spec.enum)
    return words


def plain_value(value: Any) -> str:
    """An input or output value: text with its `{{ }}` values as plain names, or compact JSON."""
    return plain_text(value) if isinstance(value, str) else f"`{json.dumps(value)}`"


def plain_text(text: str) -> str:
    """Prose with every `{{ value }}` as a plain name in backticks, and every `{% %}` tag in words."""
    text = COMMENT.sub("", text)
    text = STATEMENT.sub(lambda match: statement_words(match[1].strip()), text)
    return VALUE.sub(lambda match: value_in_place(text, match), text).strip()


def value_in_place(text: str, match: re.Match[str]) -> str:
    """A value in backticks, or a bare name inside the author's own code span or fenced code block."""
    before = text[: match.start()]
    line_before = before.rsplit("\n", 1)[-1]
    in_fence = before.count("```") % 2 == 1
    in_code_span = line_before.replace("```", "").count("`") % 2 == 1
    words = value_words(match[1].strip())
    return words.strip("`") if in_fence or in_code_span else words


def value_words(expression: str) -> str:
    return f"`{plain_expression(expression)}`"


def statement_words(statement: str) -> str:
    keyword, _, rest = statement.partition(" ")
    if keyword == "for":
        name, _, source = rest.partition(" in ")
        return f"(for each `{name.strip()}` in `{plain_expression(source)}`:) "
    if keyword == "if":
        return f"(only when `{plain_expression(rest)}`:) "
    if keyword == "elif":
        return f"(else, when `{plain_expression(rest)}`:) "
    return {"endfor": "(end of the list) ", "else": "(otherwise:) ", "endif": "(end) "}.get(
        keyword, f"(`{plain_expression(statement)}`) "
    )


def condition_text(when: str) -> str:
    return plain_expression(when.strip().removeprefix("{{").removesuffix("}}"))


def plain_expression(expression: str) -> str:
    """A `{{ }}` expression with the names of the export: `steps.x.y` is `x.y`, `history.x` is `x.all_visits`."""
    expression = re.sub(r"\bsteps\.([a-z0-9_]+)", r"\1", expression.strip())
    expression = re.sub(r"\bhistory\.([a-z0-9_]+)", r"\1.all_visits", expression)
    return expression.replace("skill.dir", SKILL_FOLDER_TEXT).replace("run.dir", "<a scratch folder>")


def command_text(run: list[Any]) -> str:
    return " ".join(command_part(str(part)) for part in run)


def command_part(part: str) -> str:
    if "{{" in part:
        return VALUE.sub(lambda match: f"<{value_words(match[1].strip()).strip('`').strip('<>')}>", part)
    return f'"{part}"' if " " in part or not part else part
