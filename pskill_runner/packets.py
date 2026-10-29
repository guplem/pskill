"""Packets: the text that the runner prints for the agent (SPEC.md section 8).

A packet holds only the current block. It never shows future blocks.
"""

from collections.abc import Sequence
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
    answers_folder: str  # for example ".pskill/runs/<run>/answers", where a long answer goes
    task_index: int | None = None  # set for one task of a parallel block
    subagent_wording: str = ""  # how this harness spawns subagents, for parallel packets
    work_folder: str = ""  # the project root, where every subagent of a parallel block works
    can_wait: bool = False  # the harness wakes the agent after a background command, so `pskill wait` works
    in_worktree: bool = False  # the run works in its own git worktree, so the header names the work folder
    # The stub gives the goal and the rules once. A packet repeats them only where the agent never saw them.
    show_goal: bool = False  # the first packet of a child skill, and `current` and `resume`
    show_rules: bool = False  # `current` and `resume`: a new session may not have read the stub

    @property
    def asks_the_human(self) -> bool:
        return self.decider == "human" and self.mode == "interactive"


def render_agent_packet(packet: AgentPacket) -> str:
    sections = [header(packet)]
    if packet.show_goal:
        sections.append(f"### Goal\n{packet.goal.strip()}")
    sections.append(f"### Instruction\n{packet.instruction.strip()}")
    if packet.errors:
        listed = "\n".join(f"- {error}" for error in packet.errors)
        sections.append(f"### Errors\nYour last answer was rejected. Fix these problems and submit again:\n{listed}")
    if packet.decider is not None:
        sections.append(decision_section(packet))
    sections.append(return_section(packet))
    if packet.show_rules:
        sections.append(rules_section(packet))
    return "\n\n".join(sections) + "\n"


def header(packet: AgentPacket) -> str:
    chain = " > ".join(packet.chain)
    lines = [f"## pskill · {chain} · {packet.block_id} (visit {packet.visit})", f"Run {packet.run_id} · {packet.mode}"]
    if packet.in_worktree:
        lines.append(worktree_line(packet.work_folder))
    return "\n".join(lines)


def worktree_line(work_folder: str) -> str:
    """The commands of a worktree run stay relative (the permission rule matches only that form): name the folder."""
    return (
        f"This run works in the folder `{work_folder}`. "
        "Run every command and make every file change of this run in that folder."
    )


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


RETURN_HELP = (
    "When the work is done, run this one command. Replace the example values.\n"
    "Write text with several lines as `field: |` followed by indented lines."
)


def submit_command(packet: AgentPacket, fields: FieldMap, task_index: int | None, asks_the_human: bool) -> str:
    """The one command that sends the answer, with an annotated example answer on stdin."""
    body_lines = example_lines(fields, indent="")
    if asks_the_human:
        body_lines.append("$answered_by: human")
    return stdin_command(packet.shell, plain_submit_command(packet, task_index), "\n".join(body_lines))


def plain_submit_command(packet: AgentPacket, task_index: int | None) -> str:
    """`<runner> submit <run>`, with `--task <n>` for one task of a parallel block."""
    task_option = f" --task {task_index}" if task_index is not None else ""
    return f"{packet.runner_command} submit {packet.run_id}{task_option}"


def answer_file_line(packet: AgentPacket, task_index: int | None) -> str:
    """The `--file` form of the submit command, for a long answer (SPEC.md section 7.3).

    A long heredoc fails in Claude Code's Bash tool on Windows. Each task gets its own file, so parallel
    subagents never write the same one. A worktree run's path is absolute, and may hold a space: it is quoted.
    """
    task_suffix = f"-task-{task_index}" if task_index is not None else ""
    path = f"{packet.answers_folder}/{packet.block_id}{task_suffix}.yaml"
    file_argument = f'"{path}"' if packet.in_worktree else path
    command = f"{plain_submit_command(packet, task_index)} --file {file_argument}"
    return f"For an answer over about 5 KB, write it to the file `{path}` instead, then run: `{command}`"


def return_section(packet: AgentPacket) -> str:
    command = submit_command(packet, packet.return_fields, packet.task_index, packet.asks_the_human)
    return f"### Return\n{RETURN_HELP}\n{command}\n{answer_file_line(packet, packet.task_index)}"


@dataclass(frozen=True)
class TaskPrompt:
    """One task of a parallel block, as a full prompt for one subagent."""

    index: int
    agent_text: str | None  # the pskill agent's role, or None
    instruction: str
    return_fields: FieldMap
    name: str | None = None  # from the block's `task_name`
    spawn_wording: str = ""  # how to spawn this task's subagent with its tool profile and model tier, in this harness


def render_parallel_packet(packet: AgentPacket, open_tasks: list[TaskPrompt], total_tasks: int) -> str:
    """The packet of a parallel block when the harness can spawn subagents: a one-line prompt per open task.

    The subagent reads its full prompt with `pskill task`, so the main agent copies one short line per task.
    The same line restarts a task whose subagent stalled.
    """
    lines = [
        header(packet),
        "",
        "### Parallel tasks",
        "Spawn one subagent per task below, all at once, each with a fresh context (none of this conversation).",
        "Give each subagent exactly the one-line prompt of its task.",
        *([packet.subagent_wording] if packet.subagent_wording else []),
        f"{len(open_tasks)} of {total_tasks} tasks are still open.",
        f"When every subagent has finished, run: {packet.runner_command} current {packet.run_id}",
        *([background_subagent_line(packet)] if packet.can_wait else []),
    ]
    for task in open_tasks:
        name = f" · {task.name}" if task.name else ""
        lines += ["", f"#### Task {task.index}{name}", *([task.spawn_wording] if task.spawn_wording else [])]
        lines.append(task_line(packet, task.index))
    return "\n".join(lines) + "\n"


def background_subagent_line(packet: AgentPacket) -> str:
    """A subagent that goes on in the background is still at work: wait for its submit, never spawn it twice."""
    wait = f'{packet.runner_command} wait {packet.run_id} --reason "the subagents of {packet.block_id}"'
    return (
        "If a subagent call returns before its subagent submitted its task (it went on in the background), do not "
        f"spawn that task again and do not go on: run `{wait}` in the background, then end your turn. Each "
        "submitted task ends the wait."
    )


def task_line(packet: AgentPacket, index: int) -> str:
    """The one-line prompt of a subagent: read the full prompt of its task, then do it."""
    command = f"{packet.runner_command} task {packet.run_id} {index}"
    return (
        f"You are a subagent of pskill run {packet.run_id}. In the folder `{packet.work_folder}`, run "
        f"`{command}`, and do what it prints."
    )


def task_prompt_text(packet: AgentPacket, task: TaskPrompt) -> str:
    """The full prompt of one task, which `pskill task` prints for its subagent."""
    parts = [
        "You are a subagent of a pskill run. Do only this task, then submit its answer.",
        f"Work in the folder `{packet.work_folder}`.",
    ]
    if task.agent_text:
        parts.append(task.agent_text.strip())
    parts.append(f"Goal: {packet.goal.strip()}")
    parts.append(f"Your task:\n{task.instruction.strip()}")
    parts.append(RETURN_HELP)
    parts.append(submit_command(packet, task.return_fields, task.index, asks_the_human=False))
    parts.append(answer_file_line(packet, task.index))
    parts.append("If you cannot do it, submit only the line `$cannot_complete: <reason>`.")
    return "\n\n".join(parts)


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


STATUS_ICONS = {"succeeded": "✅", "failed": "❌", "cancelled": "⏹️", "paused": "⏸️"}
NOT_DECLARED = "⚠️ Not declared by the skill"
NOTHING_LEFT = "Nothing left to do"
MAX_OUTPUT_CHARS = 200


@dataclass(frozen=True)
class SummaryCard:
    """The card that closes a run, or a turn at a pause: what happened and what is left (SPEC.md section 8).

    `label` is the id of the end block in capitals, `result` its description. `pending` is None when the skill
    declares no `pending`, and empty when it declares that nothing is left.
    """

    run_id: str
    skill_id: str
    status: str
    label: str
    result: str
    mode: str
    duration_ms: int
    outputs: dict[str, Any]
    pending: str | None


def render_summary_card(card: SummaryCard) -> str:
    """The card: one Markdown table with the same rows for every skill, so the user always knows it at a glance."""
    rows = [
        f"| {STATUS_ICONS[card.status]} {card.label} | {card.skill_id} · {card.status} |",
        "|---|---|",
        f"| Result | {table_cell(card.result)} |",
        f"| Run | `{card.run_id}` · {card.mode} · {duration_text(card.duration_ms)} |",
        f"| Outputs | {outputs_cell(card.outputs)} |",
        f"| Pending | {pending_cell(card.pending)} |",
    ]
    return (
        "\n".join(
            [
                "### Summary card",
                "Put this card at the top of your next message to the user, word for word. If you are a subagent, put "
                "it at the top of your answer to the agent that started you, word for word.",
                "",
                *rows,
            ]
        )
        + "\n"
    )


def duration_text(duration_ms: int) -> str:
    minutes = duration_ms // 60_000
    if minutes < 1:
        return "under 1 min"
    if minutes < 60:
        return f"{minutes} min"
    return f"{minutes // 60} h {minutes % 60} min"


def outputs_cell(outputs: dict[str, Any]) -> str:
    """Each output that has a value, as `name: value`. A long value is cut: `run.json` keeps it whole."""
    parts = []
    for name, value in outputs.items():
        text = table_cell(plain_card_value(value))
        if not text:
            continue
        if len(text) > MAX_OUTPUT_CHARS - len(name) - 2:
            text = text[: MAX_OUTPUT_CHARS - len(name) - 3] + "…"
        parts.append(f"{name}: {text}")
    return " · ".join(parts) or "None"


def pending_cell(pending: str | None) -> str:
    if pending is None:
        return NOT_DECLARED
    return table_cell(pending) or NOTHING_LEFT


def plain_card_value(value: Any) -> str:
    """An output value in plain words: a list joined with `; `, a group as `name: value` pairs."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, list):
        return "; ".join(plain_card_value(item) for item in value)
    if isinstance(value, dict):
        return ", ".join(f"{name}: {plain_card_value(item)}" for name, item in value.items())
    return str(value)


def table_cell(text: str) -> str:
    """Text on one line, with each `|` escaped, so that it never breaks the table."""
    return " ".join(text.split()).replace("|", "\\|")


def render_final_packet(card: SummaryCard, report: str | None, worktree: str | None = None) -> str:
    """The final packet: the summary card, then the skill's report. A worktree run names its worktree."""
    lines = [
        f"## pskill · {card.skill_id} · finished",
        f"Run {card.run_id} finished with status {card.status}.",
        "",
        render_summary_card(card),
    ]
    if report:
        lines += ["### Report to the user", report.strip(), ""]
    if worktree:
        lines.append(worktree_removal_line(worktree))
    lines.append("The run is finished. No more pskill commands are needed.")
    return "\n".join(lines) + "\n"


def worktree_removal_line(worktree: str) -> str:
    """The line of an ended worktree run: the runner never removes the worktree, since the run lives there.

    The worktree is detached, so a commit made there on no branch is lost with it. On Windows a folder that is the
    shell's working folder cannot be removed: the agent removes it from the checkout.
    """
    return (
        f"The run worked in the worktree `{worktree}`. Before you remove it, push every commit that you want to "
        "keep: a commit on no branch is lost with the worktree. Then, from the checkout and not from inside the "
        f'worktree, run: `git worktree remove "{worktree}"`.'
    )


@dataclass(frozen=True)
class PauseSteps:
    """A skill's `on_pause` text, rendered, for the pause packet."""

    skill_id: str
    text: str


def render_pause_packet(
    run_id: str,
    skill_id: str,
    block_id: str,
    reason: str,
    error: str | None,
    runner_command: str,
    pause_steps: Sequence[PauseSteps] = (),
    steps_shown_before: bool = False,
    work_folder: str | None = None,
    card: SummaryCard | None = None,
) -> str:
    """The pause packet. The pause steps of each skill on the call stack sit between the error and the commands.

    With `steps_shown_before`, an earlier packet of this pause gave them: this one names them, so they run once.
    A worktree run gives its `work_folder`. The summary `card` sits right after the header.
    """
    lines = [f"## pskill · {skill_id} · paused", f"Run {run_id} is paused at block {block_id} ({reason})."]
    if work_folder:
        lines.append(worktree_line(work_folder))
    if card:
        lines += ["", render_summary_card(card).rstrip("\n")]
    if error:
        lines += ["", "### Error", error.strip()]
    for steps in pause_steps:
        lines += ["", f"### Pause steps of {steps.skill_id}", steps.text.strip()]
    if steps_shown_before:
        lines += ["", "### Pause steps", "The first packet of this pause gave them. Do not do them again."]
    first_step = "Do the pause steps above. Then tell the user" if pause_steps else "Tell the user"
    lines += [
        "",
        "### Next",
        f"{first_step} why the run paused. Then, when the user decides:",
        f"- To try the block again: {runner_command} resume {run_id}",
        f"- To stop the run: {runner_command} cancel {run_id}",
        f"- To see the current block: {runner_command} current {run_id}",
    ]
    return "\n".join(lines) + "\n"


VISIT_CAP_CHOICES = {
    "more": "Run the block more times. Give the number in `rounds`.",
    "move_on": "Stop this loop, and go on with the skill.",
}
VISIT_CAP_ROUNDS = FieldSpec(type="integer", description="For `more`: how many more times.", optional=True)


def visit_cap_instruction(block_id: str, visits: int, asks_the_human: bool) -> str:
    """The question at a visit cap. It never names the ceiling or the block after the cap (SPEC.md section 5.5)."""
    rounds_line = (
        "For `more`, ask the user how many more runs, and give that number in `rounds`."
        if asks_the_human
        else "For `more`, choose the smallest number of rounds that can do it."
    )
    return (
        f"The block `{block_id}` reached its visit limit: it ran {visits} times. Decide whether it runs again.\n\n"
        "The user wants few extra runs. Choose `more` only when more runs can finish work that matters. " + rounds_line
    )
