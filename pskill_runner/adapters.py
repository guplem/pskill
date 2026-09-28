"""Harness adapters: what differs between Claude Code, Codex, and other harnesses (SPEC.md section 9).

M1 has only the `generic` adapter, which works in any harness that can run a shell command.
"""

from collections.abc import Mapping
from dataclasses import dataclass


class AdapterError(Exception):
    """An unknown harness was named."""


@dataclass(frozen=True)
class HarnessAdapter:
    name: str
    question_wording: str
    can_spawn_subagents: bool


GENERIC = HarnessAdapter(
    name="generic",
    question_wording="Ask the user this in the chat, then end your turn and wait for the answer.",
    can_spawn_subagents=False,
)

ADAPTERS: dict[str, HarnessAdapter] = {GENERIC.name: GENERIC}


def adapter_for(name: str) -> HarnessAdapter:
    if name not in ADAPTERS:
        raise AdapterError(f"unknown harness {name!r} (known harnesses: auto, {', '.join(sorted(ADAPTERS))})")
    return ADAPTERS[name]


def detect_harness(environment: Mapping[str, str]) -> str:
    """Guess the harness from its environment variables. Unknown environments use `generic`."""
    return GENERIC.name
