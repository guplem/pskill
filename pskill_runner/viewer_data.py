"""The data that the viewer shows (SPEC.md section 14). The browser only draws it.

Everything is built here, in Python, so the tests cover it: the canvas (one Mermaid template for the
whole run, child skills included), the timeline rows with their node, arrival edge, and label, and the
per-skill summaries. The page only adds up the rows up to the replay step.
"""

import json
import math
import re
import statistics
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pskill_runner.engine import list_runs, read_run_info, read_run_state
from pskill_runner.project import Project
from pskill_runner.run_records import RunInfo, RunState
from pskill_runner.run_store import folder_hash, parse_timestamp, read_events, utc_now
from pskill_runner.skill_loader import SkillLoadError, load_skill
from pskill_runner.skill_model import AnyBlock, CallBlock, DecisionBlock, EndBlock, RetryableBlock, ScriptBlock, Skill

FINISHED_STATUSES = ("succeeded", "failed", "cancelled")
FAILED_PAUSE_REASONS = ("block_failed", "runner_error")
EDGE_LABEL_LIMIT = 60
SCRIPT_FIELDS = ("argv", "input", "exit_code", "stdout", "stderr", "duration_ms", "problem")
START_NODE = "start"
DOTTED_EDGE_KINDS = ("visit_cap", "call")
BLOCK_TYPE_MEANINGS = {
    "task": "The agent does a piece of work and returns a typed answer.",
    "decision": "One choice is picked from a list, or a question gets an answer.",
    "parallel": "Subagents do one task per list item at the same time, and the results join into one list.",
    "script": "The runner runs a command. No AI model takes part.",
    "call": "The runner runs another skill and gets its outputs.",
    "end": "The skill finishes here with a status and outputs.",
}
# The first line of a block node label: the page draws the block type's icon in it. A line of its own,
# because Mermaid sizes a node by its lines of text.
ICON_LINE = "<span class='block-icon'>\u00a0</span><br/>"
INPUT_TITLES = {
    "task": "Input: the instruction the agent got",
    "decision": "Input: the question to decide",
    "parallel": "Input: the tasks that the subagents got",
    "script": "Input: the command the runner ran",
    "call": "Input: what the child skill got",
    "end": "Input: the report the agent got",
    "visit_cap": "Input: the question at the visit cap",
}
OUTPUT_TITLES = {
    "task": "Output: the agent's answer",
    "decision": "Output: the decision",
    "parallel": "Output: the results of every task, joined",
    "script": "Output: the command's result",
    "call": "Output: the child skill's outputs",
    "end": "Output: the skill's outputs",
    "visit_cap": "Output: more rounds, or move on",
}
# A packet before schema version 4 holds each task's full prompt; a later one holds a one-line prompt.
TASK_HEADING = re.compile(
    r"^#### Task (\d+)(?: · [^\n]*)?\n(?=You are a subagent of (?:a pskill run\.|pskill run ))", re.MULTILINE
)
TASK_TOTAL = re.compile(r"^\d+ of (\d+) tasks are still open\.$", re.MULTILINE)
TASKS_PER_ROW = 4
TASK_NODE_HINT = "One task of this parallel block. One subagent (or the agent) does it and answers on its own."
TASKS_EDGE_HINT = "The tasks of this parallel block, one node per task."


# --- the canvas: frames, nodes, and edges --------------------------------------------------------


@dataclass
class CanvasFrame:
    """One skill on the canvas: the root skill, or a child skill entered through a call block."""

    skill: Skill
    parent: int | None
    called_by: str | None


@dataclass
class CanvasEdge:
    """One edge of the template. `text` is the plain label; `label` is the same text, safe for Mermaid.

    `hint` says in plain words when the run takes the edge, with the whole condition.
    """

    source: str
    target: str
    text: str | None
    kind: str
    frame: int
    from_block: str | None
    to_block: str
    hint: str
    when: str | None = None
    choice: str | None = None
    fallback: bool = False  # the edge with no condition after others: the run takes it when none matches
    id: str = ""

    @property
    def label(self) -> str | None:
        return None if self.text is None else mermaid_text(self.text)


def node_id(frame_index: int, block_id: str) -> str:
    return f"f{frame_index}_{block_id}"


def task_node_id(parent: str, task: int) -> str:
    return f"{parent}_T{task}"


def task_frame_id(parent: str) -> str:
    return f"{parent}_TASKS"


def label_token(node: str) -> str:
    """The placeholder that the page swaps for the node label of the replay step."""
    return f"@@{node}@@"


def block_type_name(block: AnyBlock) -> str:
    return type(block).__name__.removesuffix("Block").lower()


def block_type_text(block: AnyBlock) -> str:
    """The type line of a node: the type, and for a call block the child skill that it runs."""
    return f"call: {block.skill}" if isinstance(block, CallBlock) else block_type_name(block)


def mermaid_text(text: str) -> str:
    """Text that is safe inside a quoted Mermaid label."""
    for character, entity in (('"', "#quot;"), ("'", "#39;"), ("<", "#lt;"), (">", "#gt;")):
        text = text.replace(character, entity)
    return text


def whole_condition_text(condition: str) -> str:
    """A `when` as plain text, without the braces."""
    return condition.strip().removeprefix("{{").removesuffix("}}").strip()


def condition_text(condition: str) -> str:
    """A `when` as plain text: without the braces, and shortened."""
    text = whole_condition_text(condition)
    return text if len(text) <= EDGE_LABEL_LIMIT else text[: EDGE_LABEL_LIMIT - 1] + "…"


def node_hint(block: AnyBlock) -> str:
    """The block in plain words: its description, what its type does, and who decides or what it runs."""
    lines = [block.description] if block.description else []
    lines.append(BLOCK_TYPE_MEANINGS[block_type_name(block)])
    notes = node_notes(block)
    return "\n".join([*lines, notes] if notes else lines)


def node_notes(block: AnyBlock) -> str:
    """The lines of the hint after the type meaning: who decides, what it runs, and its limits."""
    lines: list[str] = []
    if isinstance(block, DecisionBlock):
        human = block.decider == "human"
        lines.append(
            "The user decides in an interactive run. The agent decides in an autonomous run."
            if human
            else "The agent decides."
        )
    if isinstance(block, CallBlock):
        lines.append(f"Skill: {block.skill}.")
    if isinstance(block, EndBlock):
        lines.append(f"Status: {block.status}.")
    if block.max_visits is not None:
        lines.append(visit_cap_note(block))
    if isinstance(block, RetryableBlock) and block.retries is not None:
        lines.append(
            "It does not try again when it fails."
            if block.retries == 0
            else f"It tries again up to {block.retries} times when it fails."
        )
    if isinstance(block, ScriptBlock) and block.timeout_s is not None:
        lines.append(f"The command stops after {block.timeout_s} s.")
    return "\n".join(lines)


def condition_hint(when: str | None, has_other_edges: bool) -> str:
    """The end of a hint sentence: when the run takes one edge of an edge list (the first match wins).

    Empty for the only edge of a list, which the run always takes.
    """
    if when is not None:
        return f" when {whole_condition_text(when)}."
    return " when no condition above matches." if has_other_edges else ""


def choice_hint(choice: str, meaning: str | None, when: str | None, has_other_edges: bool) -> str:
    """When the run takes one edge of a choice: the choice alone, or the choice and its condition."""
    picks = f'Taken when the decider picks "{choice}"'
    if when is None and not has_other_edges:
        return picks + (f": {meaning}" if meaning else ".")
    return picks + " and" + condition_hint(when, has_other_edges).removeprefix(" when")


def split_choice_reason(reason: str) -> tuple[str, str | None]:
    """The engine logs "choice fix", or "choice fix: {{ ... }}" when a condition of the choice matched."""
    # Split at ": {{", not ": ": a choice id may hold ": ", and a logged condition always starts with "{{".
    choice, separator, when = reason.removeprefix("choice ").partition(": {{")
    return choice, "{{" + when if separator else None


def assign_frames(
    rows: list[dict[str, Any]], skills: dict[str, Skill], root: Skill
) -> tuple[list[CanvasFrame], list[int | None]]:
    """The canvas frames, and the frame index of each row (None for a child whose skill copy is missing).

    A row's `frame` is its call chain, like "parent>child". A child is a new frame per call block, so
    the same child skill called from two call blocks gets two frames.
    """
    frames = [CanvasFrame(root, parent=None, called_by=None)]
    active: dict[str, int | None] = {}
    last_call: dict[str, str] = {}
    previous_depth = 0
    row_frames: list[int | None] = []
    for row in rows:
        chain = str(row["frame"])
        depth = chain.count(">")
        if chain not in active or depth > previous_depth:
            active[chain] = frame_for_chain(chain, frames, active, last_call, skills)
        if row["block_type"] == "call":
            last_call[chain] = row["block"]
        previous_depth = depth
        row_frames.append(active[chain])
    return frames, row_frames


def frame_for_chain(
    chain: str,
    frames: list[CanvasFrame],
    active: dict[str, int | None],
    last_call: dict[str, str],
    skills: dict[str, Skill],
) -> int | None:
    if ">" not in chain:
        return 0
    parent_chain, skill_id = chain.rsplit(">", 1)
    parent = active.get(parent_chain, 0)
    called_by = last_call.get(parent_chain)
    if parent is None or skill_id not in skills:
        return None
    for index, frame in enumerate(frames):
        if frame.parent == parent and frame.called_by == called_by and frame.skill.id == skill_id:
            return index
    frames.append(CanvasFrame(skills[skill_id], parent=parent, called_by=called_by))
    return len(frames) - 1


def block_edges(index: int, block: AnyBlock) -> list[CanvasEdge]:
    """The edges out of one block: its choices or its next edges, plus its visit-cap edge."""
    if isinstance(block, EndBlock):
        return []
    source = node_id(index, block.id)
    edges = []
    if isinstance(block, DecisionBlock) and isinstance(block.next, dict):
        choices = block.choices or {}
        for choice, choice_edges in block.next.items():
            for edge in choice_edges:
                label = choice if edge.when is None else f"{choice}: {condition_text(edge.when)}"
                edges.append(
                    CanvasEdge(
                        source,
                        node_id(index, edge.to),
                        label,
                        "choice",
                        index,
                        block.id,
                        edge.to,
                        choice_hint(choice, choices.get(choice), edge.when, len(choice_edges) > 1),
                        when=edge.when,
                        choice=choice,
                        fallback=edge.when is None and len(choice_edges) > 1,
                    )
                )
    else:
        next_edges = block.next if isinstance(block.next, list) else []
        for edge in next_edges:
            text = condition_text(edge.when) if edge.when is not None else None
            ending = condition_hint(edge.when, len(next_edges) > 1)
            hint = f"Taken{ending}" if ending else "Always taken."
            fallback = edge.when is None and len(next_edges) > 1
            edges.append(
                CanvasEdge(
                    source,
                    node_id(index, edge.to),
                    text,
                    "next",
                    index,
                    block.id,
                    edge.to,
                    hint,
                    when=edge.when,
                    fallback=fallback,
                )
            )
    if block.on_max_visits is not None:
        target = block.on_max_visits
        hint = (
            f"Taken when the run tries to enter {block.id} after its {block.max_visits} visits and the question at "
            "the cap says to move on (the visit cap)."
            if block.ask_on_max_visits
            else f"Taken instead when the run tries to enter {block.id} after its {block.max_visits} visits "
            "(the visit cap)."
        )
        edges.append(
            CanvasEdge(source, node_id(index, target), "visit cap", "visit_cap", index, block.id, target, hint)
        )
    return edges


def frame_edges(index: int, frame: CanvasFrame) -> list[CanvasEdge]:
    """The entry edges (from the start, or from the call block), then every block's edges."""
    edges = []
    if frame.parent is None:
        for edge in frame.skill.entry:
            text = condition_text(edge.when) if edge.when is not None else None
            hint = "The run starts here" + (condition_hint(edge.when, len(frame.skill.entry) > 1) or ".")
            edges.append(
                CanvasEdge(
                    START_NODE,
                    node_id(0, edge.to),
                    text,
                    "entry",
                    0,
                    None,
                    edge.to,
                    hint,
                    when=edge.when,
                    fallback=edge.when is None and len(frame.skill.entry) > 1,
                )
            )
    elif frame.called_by is not None:  # pragma: no branch - a child frame always has its call block
        caller = node_id(frame.parent, frame.called_by)
        hint = f"The call block {frame.called_by} runs the skill {frame.skill.id}, which starts here."
        for target in dict.fromkeys(edge.to for edge in frame.skill.entry):
            edges.append(CanvasEdge(caller, node_id(index, target), None, "call", index, None, target, hint))
    for block in frame.skill.blocks.values():
        edges += block_edges(index, block)
    return edges


def next_targets(block: AnyBlock) -> list[str]:
    """The blocks that a block's next edges or choices lead to, in file order, without its visit-cap edge."""
    if isinstance(block, EndBlock):
        return []
    next_edges = block.next
    if isinstance(next_edges, dict):
        next_edges = [edge for choice_edges in next_edges.values() for edge in choice_edges]
    return list(dict.fromkeys(edge.to for edge in next_edges))


def main_line(skill: Skill) -> list[str]:
    """The blocks of the skill's usual way to a succeeded end, in order: the layout draws them in a straight line.

    It is the longest way from the entry to a succeeded end that never goes back to an earlier block, without
    each block that the way can skip (its previous block also leads straight to its next one). So a loop, a
    retry, or an optional question stays off the line. A skill with no way to a succeeded end has no line.
    """
    successors = {
        block_id: [target for target in next_targets(block) if target in skill.blocks]
        for block_id, block in skill.blocks.items()
    }
    entry = [target for target in dict.fromkeys(edge.to for edge in skill.entry) if target in skill.blocks]
    forward: dict[str, list[str]] = {block_id: [] for block_id in skill.blocks}
    on_way: dict[str, bool] = {}  # True while the depth-first walk is inside the block

    def walk(block_id: str) -> None:
        on_way[block_id] = True
        for target in successors[block_id]:
            if on_way.get(target):
                continue  # a loop back to an earlier block
            forward[block_id].append(target)
            if target not in on_way:
                walk(target)
        on_way[block_id] = False

    for start in entry:
        if start not in on_way:
            walk(start)
    longest: dict[str, list[str] | None] = {}

    def longest_from(block_id: str) -> list[str] | None:
        if block_id not in longest:
            block = skill.blocks[block_id]
            if isinstance(block, EndBlock):
                longest[block_id] = [block_id] if block.status == "succeeded" else None
            else:
                ways = [way for target in forward[block_id] if (way := longest_from(target)) is not None]
                longest[block_id] = [block_id, *max(ways, key=len)] if ways else None
        return longest[block_id]

    ways = [way for start in entry if (way := longest_from(start)) is not None]
    line = max(ways, key=len) if ways else []
    skipped = True
    while skipped:
        skipped = False
        for index in range(len(line) - 1):
            before = successors[line[index - 1]] if index > 0 else entry
            if line[index + 1] in before:
                del line[index]
                skipped = True
                break
    return line


def main_line_edges(frames: list[CanvasFrame], edges: list[CanvasEdge]) -> list[str]:
    """The ids of the edges along each frame's main line: the entry edge to its first block, then block to block."""
    steps: dict[str, int] = {}
    for index, frame in enumerate(frames):
        for step, block_id in enumerate(main_line(frame.skill)):
            steps[node_id(index, block_id)] = step
    return [
        edge.id
        for edge in edges
        if edge.target in steps
        and (
            steps[edge.target] == 0
            if edge.kind == "entry"
            else edge.kind in ("next", "choice") and steps.get(edge.source, -2) + 1 == steps[edge.target]
        )
    ]


def number_edges(edges: list[CanvasEdge], drawn_as: dict[str, str] | None = None) -> list[CanvasEdge]:
    """Give each edge the DOM id that Mermaid gives it: `L_<source>_<target>_<n>`.

    Mermaid 12 numbers the first edge of a source and target pair 0, and each later one of that pair
    one more than the count of edges before it: 0, 2, 3, ... `drawn_as` names the nodes that the template
    draws as something else (the skill screen draws a call block as the frame of its child skill).
    """
    drawn = drawn_as or {}
    counts: dict[tuple[str, str], int] = {}
    for edge in edges:
        pair = (drawn.get(edge.source, edge.source), drawn.get(edge.target, edge.target))
        count = counts.get(pair, 0)
        counts[pair] = count + 1
        edge.id = f"L_{pair[0]}_{pair[1]}_{0 if count == 0 else count + 1}"
    return edges


def task_frame_lines(parent: str, block_id: str, count: int, indent: str) -> list[str]:
    """The frame of a parallel block's tasks: one small node per task, in rows of TASKS_PER_ROW.

    Mermaid ignores `direction LR` in a frame that an edge links, so invisible links (`~~~`) make the rows.
    """
    lines = [f'{indent}subgraph {task_frame_id(parent)} ["{block_id} · {count} task{"" if count == 1 else "s"}"]']
    lines.append(f"{indent}  direction LR")
    for task in range(count):
        lines.append(f'{indent}  {task_node_id(parent, task)}["{label_token(task_node_id(parent, task))}"]')
    first = 0
    for size in task_row_sizes(count):
        if size > 1:
            lines.append(f"{indent}  {' ~~~ '.join(task_node_id(parent, task) for task in range(first, first + size))}")
        first += size
    return [*lines, f"{indent}end"]


def task_row_sizes(count: int) -> list[int]:
    """Rows of at most TASKS_PER_ROW tasks, balanced. Mermaid puts a task without links first, not last."""
    rows = max(1, math.ceil(count / TASKS_PER_ROW))
    base, extra = divmod(count, rows)
    return [base + 1] * extra + [base] * (rows - extra)


def canvas_template(frames: list[CanvasFrame], edges: list[CanvasEdge], task_counts: dict[tuple[int, str], int]) -> str:
    """The Mermaid template: each child skill is a frame inside the frame of the skill that called it."""

    def frame_lines(index: int, indent: str) -> list[str]:
        lines = []
        for block_id in frames[index].skill.blocks:
            lines.append(f'{indent}{node_id(index, block_id)}["{label_token(node_id(index, block_id))}"]')
        for (frame_index, block_id), count in task_counts.items():
            if frame_index == index:
                lines += task_frame_lines(node_id(index, block_id), block_id, count, indent)
        for child, frame in enumerate(frames):
            if frame.parent == index:
                lines.append(f'{indent}subgraph f{child} ["{frame.skill.id} · called by {frame.called_by}"]')
                lines += frame_lines(child, indent + "  ")
                lines.append(f"{indent}end")
        return lines

    # A small start dot: Mermaid 12 gives a labeled circle a fixed radius of about 90 px.
    lines = ["flowchart TD", f"  {START_NODE}@{{ shape: sm-circ }}", *frame_lines(0, "  ")]
    for edge in edges:
        arrow = "-.-" if edge.kind == "tasks" else "-.->" if edge.kind in DOTTED_EDGE_KINDS else "-->"
        label = f'|"{edge.label}"|' if edge.label is not None else ""
        lines.append(f"  {edge.source} {arrow}{label} {edge.target}")
    return "\n".join(lines) + "\n"


# --- the canvas: what each timeline row adds --------------------------------------------------


def matches_reason(edge: CanvasEdge, reason: str) -> bool:
    """Whether the engine's logged reason names this edge's condition."""
    return edge.when == reason or (edge.when is None and reason == "always")


def arrival_edge(row: dict[str, Any], frame: int, edges: list[CanvasEdge]) -> CanvasEdge | None:
    """The edge that a row arrived by, matched from the logged `from` and `reason`."""
    candidates = [edge for edge in edges if edge.frame == frame and edge.to_block == row["block"]]
    from_block, reason = row["from"], str(row["reason"] or "")
    if from_block is None:
        wanted_kind = "entry" if frame == 0 else "call"
        matches = [edge for edge in candidates if edge.kind == wanted_kind]
        return next(iter([edge for edge in matches if matches_reason(edge, reason)] or matches), None)
    own = [edge for edge in candidates if edge.from_block == from_block]
    if reason.startswith("choice "):
        choice, when = split_choice_reason(reason)
        exact = [edge for edge in own if edge.choice == choice and edge.when == when]
    elif reason.startswith("visit cap of "):
        exact = [edge for edge in own if edge.kind == "visit_cap"]
    else:
        exact = [edge for edge in own if edge.kind == "next" and matches_reason(edge, reason)]
    return next(iter(exact or own), None)


def format_duration(milliseconds: int) -> str:
    if milliseconds < 1000:
        return f"{milliseconds} ms"
    seconds = round(milliseconds / 1000)
    return f"{seconds} s" if seconds < 60 else f"{seconds // 60} min {seconds % 60:02d} s"


def row_outcome(row: dict[str, Any]) -> str | None:
    """The short result shown on the node: a choice, a child status, an exit code, or a task count."""
    output = row["output"] if isinstance(row["output"], dict) else {}
    if row["block_type"] == "decision" and "choice" in output:
        return str(output["choice"])
    if row["block_type"] == "call" and "status" in output:
        return str(output["status"])
    if row["block_type"] == "script" and row["script_runs"]:
        return f"exit {row['script_runs'][-1]['exit_code']}"
    if row["block_type"] == "parallel" and isinstance(output.get("results"), list):
        return f"{len(output['results'])} tasks"
    return None


def row_details(row: dict[str, Any], rejected: int, type_text: str) -> tuple[list[str], list[str]]:
    """The plain details of a node after a row (type, duration, outcome) and its badges (visit, rejected)."""
    details = [type_text]
    if row["duration_ms"] is not None:
        details.append(format_duration(int(row["duration_ms"])))
    outcome = row_outcome(row)
    if outcome is not None:
        details.append(outcome)
    badges: list[str] = []
    if int(row["visit"]) >= 2:
        badges.append(f"visit {row['visit']}")
    if rejected:
        badges.append(f"{rejected} rejected")
    return details, badges


def node_label(block_id: str, details: list[str], badges: list[str]) -> str:
    label = f"{ICON_LINE}<b>{block_id}</b><br/>{mermaid_text(' · '.join(details))}"
    return label + (f"<br/>{' · '.join(badges)}" if badges else "")


def arrival_text(row: dict[str, Any], called_by: str | None) -> str:
    """Where a row came from and why, in plain words."""
    reason = str(row["reason"] or "")
    if row["from"] is None:
        chain = str(row["frame"]).split(">")
        if len(chain) == 1:
            return "the start"
        return f"{called_by or chain[-2]} (call)"
    if reason == "always":
        return str(row["from"])
    if reason.startswith("choice "):
        choice, when = split_choice_reason(reason)
        return f"{row['from']} (choice {choice}" + (f", {condition_text(when)})" if when else ")")
    if reason.startswith("visit cap of "):
        return f"{row['from']} ({reason})"
    return f"{row['from']} ({condition_text(reason)})"


def visit_cap_note(block: AnyBlock) -> str:
    """What happens at a block's visit cap (SPEC.md section 5.5)."""
    then = "then asks whether to run more" if block.ask_on_max_visits else "then moves on"
    note = f"It runs at most {block.max_visits} times, {then}."
    if block.autonomous_max_visits is not None:
        note += f" In autonomous mode, at most {block.autonomous_max_visits} times."
    return note


def asks_human(block: AnyBlock | None, mode: str) -> bool:
    """A human decision asks the user only in an interactive run; in autonomous mode the agent decides."""
    return isinstance(block, DecisionBlock) and block.decider == "human" and mode == "interactive"


def next_step_in_frame(rows: list[dict[str, Any]], index: int, row_frames: list[int | None]) -> dict[str, Any] | None:
    """The next row of the same frame, skipping the other tasks of the same parallel block."""
    row = rows[index]
    if row["block_type"] == "end":
        return None
    for later, frame in zip(rows[index + 1 :], row_frames[index + 1 :], strict=True):
        if frame != row_frames[index]:
            continue
        other_task = later["block"] == row["block"] and later["visit"] == row["visit"] and later["task"] is not None
        if other_task:
            continue
        return None if later["from"] is None else later
    return None


def left_by(
    row: dict[str, Any], later: dict[str, Any] | None, edges_by_id: dict[str, CanvasEdge]
) -> dict[str, Any] | None:
    if later is None:
        return None
    reason = str(later["reason"] or "")
    if reason.startswith("visit cap of "):
        return {"to": later["block"], "label": f"visit cap of {later['from']}"}
    edge = edges_by_id.get(later["edge"] or "")
    return {"to": later["block"], "label": edge.text if edge is not None and edge.source == row["node"] else None}


def annotate_rows(
    rows: list[dict[str, Any]],
    row_frames: list[int | None],
    frames: list[CanvasFrame],
    edges: list[CanvasEdge],
    mode: str,
) -> list[dict[str, Any]]:
    """New rows, each with its node, arrival edge, labels, texts, human mark, and the edge it left by."""
    rejected_per_block: dict[tuple[int | None, str], int] = {}
    annotated: list[dict[str, Any]] = []
    for row, frame in zip(rows, row_frames, strict=True):
        key = (frame, str(row["block"]))
        rejected_per_block[key] = rejected_per_block.get(key, 0) + sum(
            1 for submission in row["submissions"] if not submission["accepted"]
        )
        block = frames[frame].skill.blocks.get(row["block"]) if frame is not None else None
        details, badges = row_details(
            row, rejected_per_block[key], block_type_text(block) if block else str(row["block_type"])
        )
        edge = arrival_edge(row, frame, edges) if frame is not None else None
        called_by = frames[frame].called_by if frame is not None else None
        node = node_id(frame, row["block"]) if frame is not None else None
        annotated.append(
            {
                **row,
                "node": node,
                "tasks": [
                    {**task, "node": task_node_id(node, task["task"]) if node else None} for task in row["tasks"]
                ],
                "input_title": INPUT_TITLES[str(row["block_type"])],
                "output_title": OUTPUT_TITLES[str(row["block_type"])],
                "edge": edge.id if edge is not None else None,
                "label": node_label(row["block"], details, badges),
                "summary": " · ".join(details + badges),
                "arrival": arrival_text(row, called_by),
                "asks_human": asks_human(block, mode) or (row["block_type"] == "visit_cap" and mode == "interactive"),
            }
        )
    edges_by_id = {edge.id: edge for edge in edges}
    for index, row in enumerate(annotated):
        row["left_by"] = left_by(row, next_step_in_frame(annotated, index, row_frames), edges_by_id)
    return annotated


def current_step(info: RunInfo, rows: list[dict[str, Any]]) -> dict[str, str] | None:
    """The node that the run waits at, and how it waits. None for a finished run."""
    if info["status"] in FINISHED_STATUSES or not rows or rows[-1]["node"] is None:
        return None
    if info["status"] == "paused" and info["pause_reason"] in FAILED_PAUSE_REASONS:
        state = "failed"
    elif info["status"] == "waiting_for_human":
        state = "waiting"
    else:
        state = "now"
    return {"node": rows[-1]["node"], "state": state}


def load_run_skills(folder: Path) -> dict[str, Skill]:
    """Every skill copy that the run keeps in its own `skills/` folder."""
    skills: dict[str, Skill] = {}
    for skill_folder in sorted((folder / "skills").glob("*")):
        try:
            skills[skill_folder.name] = load_skill(skill_folder)
        except SkillLoadError:
            continue
    return skills


def parallel_task_counts(rows: list[dict[str, Any]], row_frames: list[int | None]) -> dict[tuple[int, str], int]:
    """The most tasks that each parallel block had in one visit, per canvas frame and block."""
    counts: dict[tuple[int, str], int] = {}
    for row, frame in zip(rows, row_frames, strict=True):
        if frame is not None and row["tasks"]:
            key = (frame, str(row["block"]))
            counts[key] = max(counts.get(key, 0), len(row["tasks"]))
    return counts


def parallel_task_names(rows: list[dict[str, Any]], row_frames: list[int | None]) -> dict[tuple[str, int], str]:
    """The latest name of each named task, by task node and task number."""
    names: dict[tuple[str, int], str] = {}
    for row, frame in zip(rows, row_frames, strict=True):
        if frame is None:
            continue
        parent = node_id(frame, str(row["block"]))
        for task in row["tasks"]:
            if task["name"]:
                names[(task_node_id(parent, task["task"]), task["task"])] = task["name"]
    return names


def task_frame_edges(task_counts: dict[tuple[int, str], int]) -> list[CanvasEdge]:
    """One dotted edge from each parallel block to the frame of its tasks."""
    edges = []
    for index, block_id in task_counts:
        parent = node_id(index, block_id)
        edges.append(CanvasEdge(parent, task_frame_id(parent), None, "tasks", index, block_id, "", TASKS_EDGE_HINT))
    return edges


def frame_of_node(node: str) -> int:
    """The frame index in a node id: 2 for `f2_check` and for its task node `f2_check_T0`."""
    return int(node.split("_", 1)[0].removeprefix("f"))


def frame_call_node(frame: CanvasFrame) -> str | None:
    """The node of the call block that entered a child frame. None for the run's own skill."""
    if frame.parent is None or frame.called_by is None:
        return None
    return node_id(frame.parent, frame.called_by)


def call_block_on_top(frames: list[CanvasFrame], node: str) -> str:
    """The node of the run's own skill that holds a node: the node, or the call block of its outermost frame."""
    frame = frames[frame_of_node(node)]
    while (call_node := frame_call_node(frame)) is not None:
        node = call_node
        frame = frames[frame_of_node(call_node)]
    return node


def collapsed_run_canvas(
    canvas: dict[str, Any], frames: list[CanvasFrame], edges: list[CanvasEdge], task_counts: dict[tuple[int, str], int]
) -> dict[str, Any]:
    """The run canvas with each child skill drawn as its call block's node: only the run's own skill.

    Its edges keep the ids of the full canvas, so the timeline rows fit both canvases. A step in a child skill
    shows on the call block at the top of it.
    """
    own_edges = [edge for edge in edges if edge.frame == 0]
    own_nodes = [node for node in canvas["nodes"] if node["frame"] == 0]
    current = canvas["current"]
    return {
        "template": canvas_template(
            frames[:1], own_edges, {key: count for key, count in task_counts.items() if key[0] == 0}
        ),
        "start": START_NODE,
        "labels": {node["id"]: canvas["labels"][node["id"]] for node in own_nodes},
        "nodes": own_nodes,
        "edges": canvas_edge_rows(own_edges),
        "current": None if current is None else {**current, "node": call_block_on_top(frames, current["node"])},
        "main_edges": main_line_edges(frames[:1], own_edges),
    }


def run_canvas(
    folder: Path, info: RunInfo, rows: list[dict[str, Any]]
) -> tuple[dict[str, Any] | None, dict[str, Any] | None, list[dict[str, Any]]]:
    """The canvas of a run and its collapsed canvas (None when its skill copy does not load), and the rows
    with their canvas fields."""
    skills = load_run_skills(folder)
    root = skills.get(info["skill_id"])
    if root is None:
        return None, None, annotate_rows(rows, [None] * len(rows), [], [], info["mode"])
    frames, row_frames = assign_frames(rows, skills, root)
    task_counts = parallel_task_counts(rows, row_frames)
    task_names = parallel_task_names(rows, row_frames)
    edges = [edge for index, frame in enumerate(frames) for edge in frame_edges(index, frame)]
    edges = number_edges(edges + task_frame_edges(task_counts))
    annotated = annotate_rows(rows, row_frames, frames, edges, info["mode"])
    nodes = block_nodes(frames)
    labels = {node["id"]: node_label(node["block"], [node["type_text"]], []) for node in nodes}
    for (index, block_id), count in task_counts.items():
        parent = node_id(index, block_id)
        for task in range(count):
            task_node = task_node_id(parent, task)
            labels[task_node] = task_names.get((task_node, task)) or f"task {task}"
            nodes.append(
                {
                    "id": task_node,
                    "token": label_token(task_node),
                    "frame": index,
                    "skill_id": frames[index].skill.id,
                    "block": block_id,
                    "type": "parallel",
                    "hint": TASK_NODE_HINT,
                    "kind": "task",
                    "parent": parent,
                    "task": task,
                }
            )
    canvas = {
        "template": canvas_template(frames, edges, task_counts),
        "start": START_NODE,
        "labels": labels,
        "nodes": nodes,
        "edges": canvas_edge_rows(edges),
        "current": current_step(info, annotated),
        "main_edges": main_line_edges(frames, edges),
        # Each child frame and the call block that entered it: the page puts a hidden child's step on its call block.
        "child_frames": [
            {"id": f"f{index}", "node": call_node}
            for index, frame in enumerate(frames)
            if (call_node := frame_call_node(frame)) is not None
        ],
    }
    return canvas, collapsed_run_canvas(canvas, frames, edges, task_counts), annotated


def block_nodes(frames: list[CanvasFrame]) -> list[dict[str, Any]]:
    """One node per block of every frame, with what the page needs to draw and explain it."""
    return [
        {
            "id": node_id(index, block.id),
            "token": label_token(node_id(index, block.id)),
            "frame": index,
            "skill_id": frame.skill.id,
            "block": block.id,
            "type": block_type_name(block),
            "type_text": block_type_text(block),
            "hint": node_hint(block),
            "description": block.description,
            "type_meaning": BLOCK_TYPE_MEANINGS[block_type_name(block)],
            "notes": node_notes(block),
            "kind": "block",
        }
        for index, frame in enumerate(frames)
        for block in frame.skill.blocks.values()
    ]


def canvas_edge_rows(edges: list[CanvasEdge]) -> list[dict[str, Any]]:
    return [
        {
            "id": edge.id,
            "source": edge.source,
            "target": edge.target,
            "to_block": edge.to_block,
            "label": edge.text,
            "kind": edge.kind,
            "hint": edge.hint,
            "when": whole_condition_text(edge.when) if edge.when is not None else None,
            "choice": edge.choice,
            "fallback": edge.fallback,
        }
        for edge in edges
    ]


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
        "updated_at": info["updated_at"],
        "current_block": info["current_block"],
        "duration_ms": run_duration_ms(info),
    }


def runs_overview(project: Project) -> dict[str, Any]:
    """Every run as a table row, plus one summary row per skill."""
    rows = [run_row(info) for info in list_runs(project)]
    return {"runs": rows, "summaries": skill_summaries(rows)}


def locations_runs_overview(projects: dict[str, Project]) -> dict[str, Any]:
    """The runs of several projects as one overview: each row names its location, newest first.

    The hosted viewer shows every folder that the user picked at once (`viewer/hosted.js`).
    """
    rows = [{**run_row(info), "location": name} for name, project in projects.items() for info in list_runs(project)]
    rows.sort(key=lambda row: row["updated_at"], reverse=True)
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


# --- the tasks of parallel blocks ---------------------------------------------------------------


def task_packets(packet: str | None) -> dict[int, str]:
    """The prompt of each task in a packet for subagents: the text after each `#### Task <n>` heading.

    The packet's line "<open> of <total> tasks are still open." bounds the task numbers, so a heading
    inside an instruction adds no task.
    """
    text = packet or ""
    total = TASK_TOTAL.search(text)
    if total is None:
        return {}
    headings = [match for match in TASK_HEADING.finditer(text) if int(match[1]) < int(total[1])]
    if not headings:
        return {}
    ends = [match.start() for match in headings[1:]] + [len(text)]
    return {int(match[1]): text[match.end() : end].strip() for match, end in zip(headings, ends, strict=True)}


def live_tasks(state: RunState) -> tuple[str, str, int] | None:
    """The frame chain, the block, and the task count of the parallel block that the run is in, if any."""
    frames = state["frames"]
    top = frames[-1] if frames else None
    if top is None or top["tasks"] is None or top["current_block"] is None:
        return None
    return ">".join(frame["skill_id"] for frame in frames), top["current_block"], len(top["tasks"])


def task_view(entry: dict[str, Any] | None, task: int, packet: str | None, name: str | None) -> dict[str, Any]:
    """One task as the page shows it: done (an accepted answer), rejected (only rejected answers), or open.

    A task without a name (no `task_name`, or one that gave nothing) shows as "task <n>".
    """
    submissions = entry["submissions"] if entry is not None else []
    output = entry["output"] if entry is not None else None
    rejected = sum(1 for submission in submissions if not submission["accepted"])
    state = "done" if output is not None else "rejected" if rejected else "open"
    return {
        "task": task,
        "name": name,
        "state": state,
        "label": (name or f"task {task}") + (f" · {rejected} rejected" if rejected else ""),
        "submissions": submissions,
        "output": output,
        "duration_ms": entry["duration_ms"] if entry is not None else None,
        "packet": packet,
    }


def parallel_visits(rows: list[dict[str, Any]]) -> dict[tuple[str, int, str, int], list[dict[str, Any]]]:
    """The rows of each visit of a parallel block, by frame chain, call of that frame, block, and visit.

    A child skill counts its visits from 1 again on each call, so the call number keeps two calls apart.
    """
    calls: dict[str, int] = {}
    groups: dict[tuple[str, int, str, int], list[dict[str, Any]]] = {}
    previous_chain = None
    for row in rows:
        chain = str(row["frame"])
        if row["from"] is None and chain != previous_chain:
            calls[chain] = calls.get(chain, 0) + 1  # the run enters this frame: a new call
        previous_chain = chain
        if row["block_type"] == "parallel":
            key = (chain, calls.get(chain, 1), str(row["block"]), int(row["visit"]))
            groups.setdefault(key, []).append(row)
    return groups


def add_task_lists(rows: list[dict[str, Any]], state: RunState) -> None:
    """Give each row of a parallel block every task of its visit, as known up to that row.

    With subagents, one row holds every task. One by one (the generic adapter), each task has its own row.
    """
    groups = parallel_visits(rows)
    live = live_tasks(state)
    last_key = list(groups)[-1] if groups else None
    for key, group in groups.items():
        packets: dict[int, str] = {}
        names: list[str | None] = next((row["task_names"] for row in reversed(group) if row["task_names"]), [])
        for row in group:
            if row["task"] is None and row["task_prompts"]:
                packets.update(enumerate(row["task_prompts"]))  # with subagents: the full prompt of each task
            elif row["task"] is None:
                packets.update(task_packets(row["packet"]))  # a run before schema version 4: the packet holds them
            elif row["packet"]:  # pragma: no branch - a one-by-one task row always has its packet
                packets[row["task"]] = row["packet"]  # one by one: the row's packet is its task's prompt
        live_count = live[2] if live is not None and key == last_key and live[:2] == (key[0], key[2]) else 0
        # A rejected answer can name a task that does not exist, so only accepted answers and task rows count.
        accepted = [entry["task"] + 1 for row in group for entry in row["tasks"] if entry["output"] is not None]
        own_rows = [row["task"] + 1 for row in group if row["task"] is not None]
        count = max([live_count, *accepted, *own_rows, *(task + 1 for task in packets)], default=0)
        known: dict[int, dict[str, Any]] = {}
        for row in group:
            known.update({entry["task"]: entry for entry in row["tasks"]})
            row["tasks"] = [
                task_view(known.get(task), task, packets.get(task), names[task] if task < len(names) else None)
                for task in range(count)
            ]


# --- one run ------------------------------------------------------------------------------------


def run_detail(project: Project, run_id: str) -> dict[str, Any] | None:
    """Everything the run screen shows, or None for an unknown run."""
    folder = project.runs_folder / run_id
    if not (folder / "run.json").is_file():
        return None
    info = read_run_info(project, run_id)
    state = read_run_state(project, run_id)
    rows = timeline_rows(read_events(folder))
    add_task_lists(rows, state)
    canvas, collapsed_canvas, rows = run_canvas(folder, info, rows)
    return {
        "info": info,
        "state": state,
        "canvas": canvas,
        "collapsed_canvas": collapsed_canvas,  # the switch that collapses the child skills
        "timeline": rows,
        "skill_changed": skill_changed(project, info),
    }


def skill_changed(project: Project, info: RunInfo) -> bool:
    """Whether the project's copy of the skill differs from the copy that the run uses (D22)."""
    skill_folder = project.skills_folder / info["skill_id"]
    return not skill_folder.is_dir() or folder_hash(skill_folder) != info["skill_hash"]


def timeline_rows(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One row per block entry, with its packet, every submission, its output, and its script runs."""
    rows: list[dict[str, Any]] = []
    open_rows: dict[tuple[str, str, int | None], dict[str, Any]] = {}
    for event in events:
        if event["type"] == "block_started":
            row = new_timeline_row(event)
            close_old_rows(open_rows, row, rows[-1] if rows else None)
            rows.append(row)
            open_rows[(event["frame"], event["block"], event.get("task"))] = row
            continue
        row_for_event = find_open_row(open_rows, event)
        if row_for_event is None:
            continue
        if event["type"] == "submission_rejected":
            task = event.get("task")
            rejected = {"accepted": False, "errors": event["errors"], "raw": event["raw"], "task": task}
            row_for_event["submissions"].append(rejected)
            if task is not None:
                task_entry(row_for_event, task)["submissions"].append(rejected)
        elif event["type"] == "script_ran":
            script_run = {key: event.get(key) for key in SCRIPT_FIELDS}
            script_run["parsed"] = parsed_json(event.get("stdout"))
            row_for_event["script_runs"].append(script_run)
        elif event["type"] == "block_completed":  # pragma: no branch - the last event type that has a block
            record_completion(row_for_event, event)
    return rows


def close_old_rows(
    open_rows: dict[tuple[str, str, int | None], dict[str, Any]], row: dict[str, Any], previous: dict[str, Any] | None
) -> None:
    """Forget the rows that a new row ends: a new call of its frame ends every row of that frame, and a new
    visit of its block ends the rows of the block's earlier visits."""
    new_call = row["from"] is None and (previous is None or previous["frame"] != row["frame"])
    for key, old in list(open_rows.items()):
        same_frame = key[0] == row["frame"]
        if same_frame and (new_call or (key[1] == row["block"] and old["visit"] != row["visit"])):
            del open_rows[key]


def parsed_json(text: str | None) -> Any:
    """The text as a JSON object or array, or None when it is not one."""
    try:
        value = json.loads(text or "")
    except ValueError:
        return None
    return value if isinstance(value, dict | list) else None


def task_entry(row: dict[str, Any], task: int) -> dict[str, Any]:
    """The entry of one task of a parallel row, created on first use."""
    entries: list[dict[str, Any]] = row["tasks"]
    for entry in entries:
        if entry["task"] == task:
            return entry
    entry = {"task": task, "submissions": [], "output": None, "duration_ms": None, "packet": None}
    entries.append(entry)
    return entry


def new_timeline_row(event: dict[str, Any]) -> dict[str, Any]:
    return {
        "seq": event["seq"],
        "ts": event["ts"],
        "frame": event["frame"],
        "block": event["block"],
        "block_type": event["block_type"],
        "visit": event["visit"],
        "task": event.get("task"),
        "task_names": event.get("task_names"),
        "task_prompts": event.get("task_prompts"),
        "skipped_tasks": event.get("skipped_tasks") or [],
        "from": event.get("from"),
        "reason": event.get("reason"),
        "packet": event.get("packet"),
        "submissions": [],
        "script_runs": [],
        "output": None,
        "decided_by": None,
        "duration_ms": None,
        "tasks": [],
    }


def find_open_row(
    open_rows: dict[tuple[str, str, int | None], dict[str, Any]], event: dict[str, Any]
) -> dict[str, Any] | None:
    """The row that an event belongs to. In subagent mode, task answers belong to the block's one row."""
    frame, block = str(event["frame"]), str(event.get("block", ""))
    task: int | None = event.get("task")
    if task is not None and (frame, block, task) in open_rows:
        return open_rows[(frame, block, task)]
    if task is not None and (frame, block, None) in open_rows:
        return open_rows[(frame, block, None)]
    # Else the newest row of the block: for a one-by-one parallel block, the task that the packet shows.
    same_block = [row for key, row in open_rows.items() if key[:2] == (frame, block)]
    return max(same_block, key=lambda row: int(row["seq"])) if same_block else None


def record_completion(row: dict[str, Any], event: dict[str, Any]) -> None:
    """A task's answer, or the end of the block. The join of a parallel block's tasks is not an answer."""
    task: int | None = event.get("task")
    if task is not None:
        accepted = {"accepted": True, "errors": [], "raw": None, "task": task}
        row["submissions"].append(accepted)
        entry = task_entry(row, task)
        entry["submissions"].append(accepted)
        entry["output"] = event["output"]
        entry["duration_ms"] = event["duration_ms"]
        if row["task"] is None:
            return  # With subagents, every task shares the block's row: only the join sets the row's output.
    elif event["decided_by"] != "runner" and row["block_type"] != "parallel":
        row["submissions"].append({"accepted": True, "errors": [], "raw": None, "task": None})
    row["output"] = event["output"]
    row["decided_by"] = event["decided_by"]
    row["duration_ms"] = event["duration_ms"]
