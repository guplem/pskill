"""Tests for pskill_runner.token_usage: the model calls of a Claude Code session transcript."""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pskill_runner import token_usage
from pskill_runner.token_usage import ModelCall


def assistant_line(message_id: str | None, moment: str, model: str, **usage: int) -> dict[str, Any]:
    message: dict[str, Any] = {"model": model, "usage": usage}
    if message_id is not None:
        message["id"] = message_id
    return {"type": "assistant", "timestamp": moment, "uuid": f"u-{message_id}", "message": message}


def write_lines(path: Path, lines: list[Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(line if isinstance(line, str) else json.dumps(line) for line in lines), encoding="utf-8")


def at(text: str) -> datetime:
    return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(UTC)


def test_the_transcript_is_found_only_for_a_claude_code_run_with_a_session(tmp_path: Path) -> None:
    write_lines(tmp_path / "C--repo" / "s-1.jsonl", [])

    assert token_usage.find_transcript(tmp_path, "claude-code", "s-1") == tmp_path / "C--repo" / "s-1.jsonl"
    assert token_usage.find_transcript(tmp_path, "claude-code", "s-2") is None
    assert token_usage.find_transcript(tmp_path, "claude-code", None) is None
    assert token_usage.find_transcript(tmp_path, "codex", "s-1") is None


def test_a_call_counts_once_by_its_message_id_and_odd_lines_are_skipped(tmp_path: Path) -> None:
    transcript = tmp_path / "s-1.jsonl"
    write_lines(
        transcript,
        [
            {"type": "user", "timestamp": "2026-10-16T10:00:00.000Z", "message": {"content": "hi"}},
            assistant_line("m1", "2026-10-16T10:00:01.000Z", "claude-opus-5-5", input_tokens=3, output_tokens=5),
            assistant_line("m1", "2026-10-16T10:00:02.000Z", "claude-opus-5-5", input_tokens=3, output_tokens=5),
            assistant_line(
                None,
                "2026-10-16T10:00:03.000Z",
                "claude-opus-5-5",
                cache_creation_input_tokens=7,
                cache_read_input_tokens=11,
            ),
            {"type": "assistant", "message": {"id": "m3", "usage": {"input_tokens": 1}}},  # no timestamp
            {"type": "assistant", "timestamp": "2026-10-16T10:00:04.000Z", "message": "text"},
            "{not json yet",
        ],
    )

    assert token_usage.read_model_calls(transcript) == [
        ModelCall(
            at("2026-10-16T10:00:02.000Z"),
            "main agent",
            "claude-opus-5-5",
            {"input": 3, "cache_write": 0, "cache_read": 0, "output": 5},
        ),
        ModelCall(
            at("2026-10-16T10:00:03.000Z"),
            "main agent",
            "claude-opus-5-5",
            {"input": 0, "cache_write": 7, "cache_read": 11, "output": 0},
        ),
    ]


def test_a_subagent_counts_for_the_tier_of_its_model_family(tmp_path: Path) -> None:
    transcript = tmp_path / "s-1.jsonl"
    write_lines(transcript, [])
    subagents = tmp_path / "s-1" / "subagents"
    write_lines(
        subagents / "agent-a.jsonl",
        [
            assistant_line("e", "2026-10-16T10:00:01.000Z", "<synthetic>", output_tokens=1),
            assistant_line("h", "2026-10-16T10:00:02.000Z", "claude-haiku-5-5", output_tokens=2),
        ],
    )
    write_lines(
        subagents / "agent-b.jsonl", [assistant_line("x", "2026-10-16T10:00:03.000Z", "gpt-6", output_tokens=4)]
    )
    write_lines(subagents / "agent-c.jsonl", [assistant_line("y", "2026-10-16T10:00:04.000Z", "<synthetic>")])

    sources = [(call.source, call.model) for call in token_usage.read_model_calls(transcript)]

    assert sources == [
        ("subagents fast", "<synthetic>"),
        ("subagents fast", "claude-haiku-5-5"),
        ("subagents other", "gpt-6"),
        ("subagents other", "<synthetic>"),
    ]


def test_the_model_family_names_the_tier() -> None:
    assert token_usage.tier_of("claude-sonnet-5-5") == "standard"
    assert token_usage.tier_of("claude-opus-5-5") == "deep"
    assert token_usage.tier_of("claude-haiku-5-5") == "fast"
    assert token_usage.tier_of("<synthetic>") == "other"
