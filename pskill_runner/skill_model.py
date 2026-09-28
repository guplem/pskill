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


# A decision with choices uses a choice map (choice id -> target block). Every other block uses edges.
ChoiceMap = dict[str, str]


@dataclass(frozen=True, kw_only=True)
class Block:
    """Fields that every block type has."""

    id: str
    description: str | None = None
    max_visits: int | None = None
    on_max_visits: str | None = None


@dataclass(frozen=True, kw_only=True)
class TaskBlock(Block):
    instruction: str
    output: FieldMap
    next: list[Edge]


@dataclass(frozen=True, kw_only=True)
class DecisionBlock(Block):
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


AnyBlock = TaskBlock | DecisionBlock | EndBlock
AGENT_BLOCK_TYPES = (TaskBlock, DecisionBlock)


def block_edges(block: AnyBlock) -> list[Edge]:
    """The edges of a block, with a choice map turned into one edge per choice."""
    if isinstance(block, EndBlock):
        return []
    if isinstance(block.next, dict):
        return [Edge(to=target) for target in block.next.values()]
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
