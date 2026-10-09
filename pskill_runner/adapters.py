"""Harness adapters: what differs between Claude Code, Codex, and other harnesses (SPEC.md section 9).

An adapter holds wording and abilities only. Harness-specific files and hook formats live in their own
module (for example `claude_code.py`). The `generic` adapter works in any harness that can run a shell
command; every other adapter is optional.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field


class AdapterError(Exception):
    """An unknown harness was named."""


@dataclass(frozen=True)
class HarnessAdapter:
    name: str
    question_wording: str
    can_spawn_subagents: bool
    subagent_wording: str = ""
    tier_wording: Mapping[str, str] = field(default_factory=dict)  # model tier -> how to spawn a task with it


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
        "Use the Agent tool with `subagent_type: general-purpose` and `run_in_background: false`: one Agent call "
        "per task, all in one message. The calls run in parallel, and your turn waits until every subagent has "
        "finished."
    ),
    # A per-invocation `model` overrides the subagent's own model: https://code.claude.com/docs/en/sub-agents
    tier_wording={
        "fast": "Pass `model: haiku` in this task's Agent call.",
        "standard": "Pass `model: sonnet` in this task's Agent call.",
        "deep": "Pass `model: opus` in this task's Agent call.",
    },
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
    # An explicit spawn request can set the reasoning effort; Codex picks the model itself. VERIFY.
    # https://learn.chatgpt.com/docs/agent-configuration/subagents
    tier_wording={
        "fast": "Spawn this task's subagent with the reasoning effort `low`.",
        "standard": "Spawn this task's subagent with the reasoning effort `medium`.",
        "deep": "Spawn this task's subagent with the reasoning effort `high`.",
    },
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


def detect_session_id(environment: Mapping[str, str]) -> str | None:
    """The id of the app session that runs this command, or None when the app is unknown.

    Claude Code sets CLAUDE_CODE_SESSION_ID for the commands of its Bash tool, with the same value as
    the `session_id` of its hook input: https://code.claude.com/docs/en/env-vars
    Codex sets CODEX_THREAD_ID for the commands of the agent (codex-rs/core/src/exec_env.rs), and its
    hook input has a `session_id` of the same thread id type (codex-rs/hooks/src/types.rs). VERIFY.
    """
    harness = detect_harness(environment)
    if harness == CLAUDE_CODE.name:
        return environment.get("CLAUDE_CODE_SESSION_ID") or None
    if harness == CODEX.name:
        return environment.get("CODEX_THREAD_ID") or None
    return None


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
