"""The typed model of a loaded skill (SPEC.md sections 5 and 6)."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pskill_runner.field_types import FieldMap


@dataclass(frozen=True)
class Edge:
    """A link to the next block. With no `when`, the edge always applies."""

    to: str
    when: str | None = None


# A decision with choices uses a choice map: choice id -> its edges. `approve: done` in YAML is one edge
# with no `when`; an edge list lets one choice lead to different blocks by condition. Every other block
# uses edges.
ChoiceMap = dict[str, list[Edge]]


@dataclass(frozen=True, kw_only=True)
class Block:
    """Fields that every block type has."""

    id: str
    description: str | None = None
    max_visits: int | None = None
    on_max_visits: str | None = None
    ask_on_max_visits: bool = True  # at the cap, ask "more rounds, or move on?" (SPEC.md section 5.5)
    autonomous_max_visits: int | None = None  # the hidden ceiling for the agent; None: the config.yaml value


@dataclass(frozen=True, kw_only=True)
class RetryableBlock(Block):
    """A block that can fail and try again. `retries` overrides the global value in `config.yaml`."""

    retries: int | None = None


@dataclass(frozen=True, kw_only=True)
class TaskBlock(RetryableBlock):
    instruction: str
    output: FieldMap
    next: list[Edge]


@dataclass(frozen=True, kw_only=True)
class DecisionBlock(RetryableBlock):
    decider: str
    instruction: str
    choices: dict[str, str] | None = None
    output: FieldMap = field(default_factory=dict)
    next: list[Edge] | ChoiceMap = field(default_factory=list)


@dataclass(frozen=True, kw_only=True)
class EndBlock(Block):
    status: str
    outputs: dict[str, Any] = field(default_factory=dict)
    report: str | None = None


@dataclass(frozen=True, kw_only=True)
class ParallelBlock(RetryableBlock):
    """One subagent task per item of `for_each`, joined into one list of results."""

    for_each: list[Any] | str
    agent: str | None = None
    task_name: str | None = None  # a {{ }} value per item: the task's name in the packet and the viewer
    instruction: str
    output: FieldMap
    next: list[Edge]


@dataclass(frozen=True, kw_only=True)
class ScriptBlock(RetryableBlock):
    """A command that the runner executes itself, with no shell and no LLM.

    `input` is what the script reads on stdin: a text as it is, any other value as JSON.
    `timeout_s` overrides the global `script_timeout_s` in `config.yaml`.
    """

    run: list[Any]
    input: Any = None
    parse: str = "text"
    timeout_s: int | None = None
    next: list[Edge]


@dataclass(frozen=True, kw_only=True)
class CallBlock(Block):
    """Run another skill as a function: inputs in, outputs out."""

    skill: str
    inputs: dict[str, Any] = field(default_factory=dict)
    next: list[Edge]


AnyBlock = TaskBlock | DecisionBlock | ParallelBlock | ScriptBlock | CallBlock | EndBlock
AgentBlock = TaskBlock | DecisionBlock | ParallelBlock


def block_edges(block: AnyBlock) -> list[Edge]:
    """The edges of a block, with a choice map turned into one edge per choice."""
    if isinstance(block, EndBlock):
        return []
    if isinstance(block.next, dict):
        return [edge for choice_edges in block.next.values() for edge in choice_edges]
    return list(block.next)


def next_targets(block: AnyBlock) -> list[str]:
    """Every block that this block can lead to, including its `on_max_visits` target."""
    targets = [edge.to for edge in block_edges(block)]
    if block.on_max_visits is not None:
        targets.append(block.on_max_visits)
    return targets


@dataclass(frozen=True)
class Skill:
    id: str
    description: str
    goal: str
    invocation: str
    inputs: FieldMap
    outputs: FieldMap
    entry: list[Edge]
    blocks: dict[str, AnyBlock]
    folder: Path

    def instruction_text(self, value: str) -> str:
        """An `instruction` or `report` is a path that ends in `.md`, or the text itself."""
        if value.endswith(".md"):
            return (self.folder / value).read_text(encoding="utf-8")
        return value


@dataclass(frozen=True)
class SkillCatalog:
    """Every skill and pskill agent of a project, for the checks that look across skills."""

    skills: dict[str, Skill]
    agent_names: set[str]
