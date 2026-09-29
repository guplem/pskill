"""Harness adapters: what differs between Claude Code, Codex, and other harnesses (SPEC.md section 9).

An adapter holds wording and abilities only. Harness-specific files and hook formats live in their own
module (for example `claude_code.py`). The `generic` adapter works in any harness that can run a shell
command; every other adapter is optional.
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
    subagent_wording: str = ""


GENERIC = HarnessAdapter(
    name="generic",
    question_wording="Ask the user this in the chat, then end your turn and wait for the answer.",
    can_spawn_subagents=False,
)

CLAUDE_CODE = HarnessAdapter(
    name="claude-code",
    question_wording=(
        "Ask the user with the AskUserQuestion tool: use each choice id as an option label and its meaning as "
        "the option description. With more than 4 choices, or with no choices, ask in the chat instead."
    ),
    can_spawn_subagents=True,
    subagent_wording=(
        "Use the Agent tool with `subagent_type: general-purpose`: one Agent call per task, all in one message."
    ),
)

CODEX = HarnessAdapter(
    name="codex",
    # Codex offers its question tool only in Plan mode, so the agent asks in the chat.
    question_wording=GENERIC.question_wording,
    can_spawn_subagents=True,
    subagent_wording=(
        "Use the spawn_agent tool: one spawn_agent call per task, all at once, then wait_agent until every "
        "subagent has finished."
    ),
)

ADAPTERS: dict[str, HarnessAdapter] = {adapter.name: adapter for adapter in (GENERIC, CLAUDE_CODE, CODEX)}


def adapter_for(name: str) -> HarnessAdapter:
    if name not in ADAPTERS:
        raise AdapterError(f"unknown harness {name!r} (known harnesses: auto, {', '.join(sorted(ADAPTERS))})")
    return ADAPTERS[name]


def detect_harness(environment: Mapping[str, str]) -> str:
    """Guess the harness from its environment variables. Unknown environments use `generic`."""
    if environment.get("CLAUDECODE") == "1":
        return CLAUDE_CODE.name
    if environment.get("CODEX_THREAD_ID"):
        return CODEX.name
    return GENERIC.name


def detect_hook_harness(environment: Mapping[str, str], hook_input: Mapping[str, object]) -> str:
    """Guess the app that runs a hook from a shared hooks file, from the signs that each app documents.

    Codex sends a `turn_id` in the input of its turn hooks, such as Stop. Claude Code sets
    CLAUDE_PROJECT_DIR for every hook. The `turn_id` comes first: a Codex started from a Claude Code
    session may inherit CLAUDE_PROJECT_DIR.
    """
    if hook_input.get("turn_id"):
        return CODEX.name
    if environment.get("CLAUDE_PROJECT_DIR"):
        return CLAUDE_CODE.name
    return detect_harness(environment)
