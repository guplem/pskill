"""The model calls of a Claude Code session, read from its transcripts (SPEC.md section 10.4, token use).

Claude Code writes one JSON line per content block of a model call in `~/.claude/projects/*/<session id>.jsonl`,
and each line repeats the usage of the whole call. A subagent writes its own transcript in
`<session id>/subagents/` beside it. Codex writes no such transcript, so a Codex run has no token use.
"""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import NamedTuple

# Our name of each count -> the name in the `usage` of a transcript line.
USAGE_FIELDS = {
    "input": "input_tokens",
    "cache_write": "cache_creation_input_tokens",
    "cache_read": "cache_read_input_tokens",
    "output": "output_tokens",
}
# The model family of a subagent names its tier: the default Claude Code tier rows of the runner.
TIERS_BY_FAMILY = {"haiku": "fast", "sonnet": "standard", "opus": "deep"}
# Claude Code writes this model for a turn that it made up itself, such as an error message.
SYNTHETIC_MODEL = "<synthetic>"
MAIN_AGENT = "main agent"

Usage = dict[str, int]


class ModelCall(NamedTuple):
    moment: datetime
    source: str  # "main agent", or "subagents <tier>"
    model: str
    usage: Usage


def default_projects_folder() -> Path:
    return Path.home() / ".claude" / "projects"


def find_transcript(projects_folder: Path, harness: str, session_id: str | None) -> Path | None:
    """The main transcript of a Claude Code session, or None (another harness, or no session id)."""
    if harness != "claude-code" or not session_id:
        return None
    matches = sorted(projects_folder.glob(f"*/{session_id}.jsonl"))
    return matches[0] if matches else None


def zero_usage() -> Usage:
    return dict.fromkeys(USAGE_FIELDS, 0)


def tier_of(model: str) -> str:
    return next((tier for family, tier in TIERS_BY_FAMILY.items() if family in model), "other")


def read_model_calls(transcript: Path) -> list[ModelCall]:
    """Every model call of the main agent and of its subagents."""
    calls = read_file_calls(transcript, MAIN_AGENT)
    for path in sorted((transcript.parent / transcript.stem / "subagents").glob("*.jsonl")):
        subagent_calls = read_file_calls(path, "")
        model = next((call.model for call in subagent_calls if call.model != SYNTHETIC_MODEL), SYNTHETIC_MODEL)
        calls += [call._replace(source=f"subagents {tier_of(model)}") for call in subagent_calls]
    return calls


def read_file_calls(path: Path, source: str) -> list[ModelCall]:
    """The calls of one transcript, once each by message id. A line that is not JSON yet is still being written."""
    calls: dict[str, ModelCall] = {}
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines()):
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        message = entry.get("message")
        if entry.get("type") != "assistant" or not isinstance(message, dict) or "usage" not in message:
            continue
        if not entry.get("timestamp"):
            continue
        usage = {name: int(message["usage"].get(field) or 0) for name, field in USAGE_FIELDS.items()}
        moment = datetime.fromisoformat(str(entry["timestamp"]).replace("Z", "+00:00")).astimezone(UTC)
        key = message.get("id") or entry.get("uuid") or f"line {number}"
        calls[key] = ModelCall(moment, source, str(message.get("model")), usage)
    return list(calls.values())
