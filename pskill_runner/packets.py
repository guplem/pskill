"""Packets: the text that the runner prints for the agent (SPEC.md section 8).

A packet holds only the current block. It never shows future blocks.
"""

from dataclasses import dataclass
from typing import Any

from pskill_runner.field_types import FieldMap, FieldSpec
from pskill_runner.shells import stdin_command

TYPE_LABELS = {
    "string": "text",
    "integer": "integer",
    "number": "number",
    "boolean": "true | false",
    "array": "list",
    "object": "group",
}


@dataclass(frozen=True)
class AgentPacket:
    """Everything that an agent block's packet shows."""

    run_id: str
    chain: list[str]  # skill ids from the root skill to the current one
    block_id: str
    visit: int
    mode: str
    goal: str
    instruction: str
    return_fields: FieldMap
    choices: dict[str, str] | None
    decider: str | None  # "agent" or "human" for decisions, None for tasks
    errors: list[str]
    runner_command: str  # for example "uv run .pskill/pskill.py"
    shell: str
    question_wording: str

    @property
    def asks_the_human(self) -> bool:
        return self.decider == "human" and self.mode == "interactive"


def render_agent_packet(packet: AgentPacket) -> str:
    sections = [
        header(packet),
        f"### Goal\n{packet.goal.strip()}",
        f"### Instruction\n{packet.instruction.strip()}",
    ]
    if packet.errors:
        listed = "\n".join(f"- {error}" for error in packet.errors)
        sections.append(f"### Errors\nYour last answer was rejected. Fix these problems and submit again:\n{listed}")
    if packet.decider is not None:
        sections.append(decision_section(packet))
    sections.append(return_section(packet))
    sections.append(rules_section(packet))
    return "\n\n".join(sections) + "\n"


def header(packet: AgentPacket) -> str:
    chain = " > ".join(packet.chain)
    return f"## pskill · {chain} · {packet.block_id} (visit {packet.visit})\nRun {packet.run_id} · {packet.mode}"


def decision_section(packet: AgentPacket) -> str:
    lines = ["### Decision"]
    if packet.choices:
        lines.append("The choices:")
        lines += [f"- {choice}: {meaning}" for choice, meaning in packet.choices.items()]
    if packet.asks_the_human:
        lines.append(packet.question_wording)
        lines.append("Submit the user's answer with `$answered_by: human`. Do not decide for the user.")
        if packet.choices:
            lines.append(
                "If the reply matches no choice exactly, pick the closest choice and copy the user's words into "
                "`rationale`. When no choice fits, ask again."
            )
    elif packet.decider == "human":
        lines.append(
            "This run is autonomous. Decide as the user would, from the goal, this session, and the project. "
            "Explain why in `rationale`."
        )
    return "\n".join(lines)


def return_section(packet: AgentPacket) -> str:
    body_lines = example_lines(packet.return_fields, indent="")
    if packet.asks_the_human:
        body_lines.append("$answered_by: human")
    command = stdin_command(packet.shell, f"{packet.runner_command} submit {packet.run_id}", "\n".join(body_lines))
    return (
        "### Return\nWhen the work is done, run this one command. Replace the example values.\n"
        "Write text with several lines as `field: |` followed by indented lines.\n"
        f"{command}"
    )


def rules_section(packet: AgentPacket) -> str:
    return (
        "### Rules\n"
        "- Do only this block. The runner gives you the next one.\n"
        "- If you cannot do it, submit only the line `$cannot_complete: <reason>`.\n"
        f"- If the user asks to stop, run: {packet.runner_command} pause {packet.run_id}"
    )


def example_lines(fields: FieldMap, indent: str) -> list[str]:
    """An annotated YAML example of a field map, one field per line."""
    lines = []
    for name, spec in fields.items():
        comment = field_comment(spec) if indent == "" else ""
        if spec.type == "array":
            lines.append(f"{indent}{name}:{comment}")
            lines += list_item_lines(spec.items or FieldSpec(type="string"), indent + "  ")
        elif spec.type == "object":
            lines.append(f"{indent}{name}:{comment}")
            lines += example_lines(spec.properties, indent + "  ")
        else:
            lines.append(f"{indent}{name}: {example_value(spec)}{comment}")
    return lines


def list_item_lines(item_spec: FieldSpec, indent: str) -> list[str]:
    if item_spec.type == "object":
        nested = example_lines(item_spec.properties, indent + "  ")
        if not nested:
            return [f"{indent}- {{}}"]
        return [f"{indent}- {nested[0].strip()}", *nested[1:]]
    return [f"{indent}- {example_value(item_spec)}"]


def example_value(spec: FieldSpec) -> str:
    if spec.enum:
        return str(spec.enum[0])
    return {"integer": "0", "number": "0", "boolean": "false"}.get(spec.type, "...")


def field_comment(spec: FieldSpec) -> str:
    presence = "optional" if spec.optional else "required"
    kind = " | ".join(str(option) for option in spec.enum) if spec.enum else TYPE_LABELS[spec.type]
    description = f": {spec.description.strip()}" if spec.description else ""
    return f"  # {presence}, {kind}{description}"


def render_final_packet(run_id: str, skill_id: str, status: str, report: str | None, outputs: dict[str, Any]) -> str:
    lines = [f"## pskill · {skill_id} · finished", f"Run {run_id} finished with status {status}.", ""]
    if report:
        lines += ["### Report to the user", report.strip(), ""]
    if outputs:
        lines += ["### Outputs", *(f"{name}: {value}" for name, value in outputs.items()), ""]
    lines.append("The run is finished. No more pskill commands are needed.")
    return "\n".join(lines) + "\n"


def render_pause_packet(
    run_id: str, skill_id: str, block_id: str, reason: str, error: str | None, runner_command: str
) -> str:
    lines = [f"## pskill · {skill_id} · paused", f"Run {run_id} is paused at block {block_id} ({reason})."]
    if error:
        lines += ["", "### Error", error.strip()]
    lines += [
        "",
        "### Next",
        "Tell the user why the run paused. Then, when the user decides:",
        f"- To try the block again: {runner_command} resume {run_id}",
        f"- To stop the run: {runner_command} cancel {run_id}",
        f"- To see the current block: {runner_command} current {run_id}",
    ]
    return "\n".join(lines) + "\n"
