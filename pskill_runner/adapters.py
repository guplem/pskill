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
class TierRow:
    """What a model tier means in one harness. None keeps the session's model, or the model's default effort."""

    model: str | None = None
    effort: str | None = None


@dataclass(frozen=True)
class HarnessAdapter:
    name: str
    question_wording: str
    can_spawn_subagents: bool
    subagent_wording: str = ""
    tier_rows: Mapping[str, TierRow] = field(default_factory=dict)  # model tier -> its default model and effort
    spawn_call: str = ""  # the tool call that spawns one subagent
    effort_parameter: str = ""  # the parameter of that call that sets the effort


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
    # A per-invocation `model` and `effort` override the subagent's own: https://code.claude.com/docs/en/sub-agents
    # The aliases haiku, sonnet, and opus follow the newest model of each family, so they never expire.
    tier_rows={
        "fast": TierRow(model="haiku"),
        "standard": TierRow(model="sonnet"),
        "deep": TierRow(model="opus"),
    },
    spawn_call="Agent",
    effort_parameter="effort",
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
    # spawn_agent takes `model` and `reasoning_effort`, and Codex has no model aliases (sources in codex.py).
    # Versioned names expire, so the defaults set the effort only, and a project names a model in config.yaml.
    tier_rows={
        "fast": TierRow(effort="low"),
        "standard": TierRow(effort="medium"),
        "deep": TierRow(effort="high"),
    },
    spawn_call="spawn_agent",
    effort_parameter="reasoning_effort",
)

ADAPTERS: dict[str, HarnessAdapter] = {adapter.name: adapter for adapter in (GENERIC, CLAUDE_CODE, CODEX)}
# The harnesses that spawn subagents, so the ones whose tier rows a project can change in config.yaml.
SPAWNING_HARNESSES = tuple(adapter.name for adapter in ADAPTERS.values() if adapter.can_spawn_subagents)
TIER_ROW_KEYS = ("effort", "model")


def adapter_for(name: str) -> HarnessAdapter:
    if name not in ADAPTERS:
        raise AdapterError(f"unknown harness {name!r} (known harnesses: auto, {', '.join(sorted(ADAPTERS))})")
    return ADAPTERS[name]


def tier_wording(adapter: HarnessAdapter, project_tiers: Mapping[str, Mapping[str, TierRow]], tier: str) -> str:
    """How to spawn a task's subagent with its model tier, in one line. Empty when the row asks for nothing.

    `project_tiers` holds the project's rows from config.yaml, per harness: a project row replaces the default row.
    """
    project_rows = project_tiers.get(adapter.name, {})
    row = project_rows[tier] if tier in project_rows else adapter.tier_rows.get(tier, TierRow())
    settings = []
    if row.model:
        settings.append(f"`model: {row.model}`")
    if row.effort:
        settings.append(f"`{adapter.effort_parameter}: {row.effort}`")
    if not settings:
        return ""
    return f"Pass {' and '.join(settings)} in this task's {adapter.spawn_call} call."


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
