"""Tests for pskill_runner.adapters."""

from dataclasses import replace

import pytest

from pskill_runner.adapters import (
    AdapterError,
    TierRow,
    adapter_for,
    detect_harness,
    detect_hook_harness,
    detect_session_id,
    tier_wording,
)
from pskill_runner.skill_model import MODEL_TIERS


def test_the_generic_adapter_asks_in_the_chat_and_has_no_subagents() -> None:
    adapter = adapter_for("generic")

    assert adapter.name == "generic"
    assert "chat" in adapter.question_wording
    assert adapter.can_spawn_subagents is False


def test_an_unknown_environment_falls_back_to_generic() -> None:
    assert detect_harness({}) == "generic"


def test_an_unknown_harness_name_is_an_error() -> None:
    with pytest.raises(AdapterError, match="unknown harness 'vim'"):
        adapter_for("vim")


def test_a_hook_input_with_a_turn_id_comes_from_codex() -> None:
    assert detect_hook_harness({"CLAUDE_PROJECT_DIR": "/project"}, {"turn_id": "turn-1"}) == "codex"


def test_a_hook_with_the_claude_project_folder_comes_from_claude_code() -> None:
    assert detect_hook_harness({"CLAUDE_PROJECT_DIR": "/project"}, {"session_id": "s"}) == "claude-code"


def test_a_hook_without_a_known_sign_uses_the_normal_detection() -> None:
    assert detect_hook_harness({}, {}) == "generic"
    assert detect_hook_harness({"CODEX_THREAD_ID": "t"}, {}) == "codex"


def test_the_session_id_comes_from_the_variable_of_the_detected_app() -> None:
    assert detect_session_id({"CLAUDECODE": "1", "CLAUDE_CODE_SESSION_ID": "s1"}) == "s1"
    assert detect_session_id({"CODEX_THREAD_ID": "019a-thread"}) == "019a-thread"


def test_there_is_no_session_id_without_a_known_app() -> None:
    assert detect_session_id({}) is None
    assert detect_session_id({"CLAUDE_CODE_SESSION_ID": "s1"}) is None  # CLAUDECODE is missing
    assert detect_session_id({"CLAUDECODE": "1", "CLAUDE_CODE_SESSION_ID": ""}) is None


def test_claude_code_runs_parallel_subagents_in_the_foreground_so_the_turn_waits_for_them() -> None:
    wording = adapter_for("claude-code").subagent_wording

    assert "`run_in_background: false`" in wording
    assert "all in one message" in wording


def test_claude_code_asks_for_the_model_of_each_tier_on_the_agent_call() -> None:
    claude_code = adapter_for("claude-code")

    assert tier_wording(claude_code, {}, "fast") == "Pass `model: haiku` in this task's Agent call."
    assert tier_wording(claude_code, {}, "standard") == "Pass `model: sonnet` in this task's Agent call."
    assert tier_wording(claude_code, {}, "deep") == "Pass `model: opus` in this task's Agent call."


def test_codex_asks_for_the_reasoning_effort_of_each_tier_on_the_spawn_agent_call() -> None:
    codex = adapter_for("codex")

    assert tier_wording(codex, {}, "fast") == "Pass `reasoning_effort: low` in this task's spawn_agent call."
    assert tier_wording(codex, {}, "standard") == "Pass `reasoning_effort: medium` in this task's spawn_agent call."
    assert tier_wording(codex, {}, "deep") == "Pass `reasoning_effort: high` in this task's spawn_agent call."


def test_a_row_with_a_model_and_an_effort_names_both() -> None:
    claude_code = replace(adapter_for("claude-code"), tier_rows={"deep": TierRow(model="opus", effort="max")})

    assert tier_wording(claude_code, {}, "deep") == "Pass `model: opus` and `effort: max` in this task's Agent call."


def test_a_row_with_neither_a_model_nor_an_effort_asks_for_nothing() -> None:
    codex = replace(adapter_for("codex"), tier_rows={"fast": TierRow()})

    assert tier_wording(codex, {}, "fast") == ""


def test_every_adapter_with_subagents_has_a_row_for_every_tier_and_generic_has_none() -> None:
    assert set(adapter_for("claude-code").tier_rows) == set(MODEL_TIERS)
    assert set(adapter_for("codex").tier_rows) == set(MODEL_TIERS)
    assert adapter_for("generic").tier_rows == {}
    assert tier_wording(adapter_for("generic"), {}, "deep") == ""


def test_a_project_row_replaces_the_default_row_of_its_tier_only() -> None:
    codex = adapter_for("codex")
    project_tiers = {"codex": {"fast": TierRow(model="gpt-6-luna", effort="low")}}

    assert tier_wording(codex, project_tiers, "fast") == (
        "Pass `model: gpt-6-luna` and `reasoning_effort: low` in this task's spawn_agent call."
    )
    assert (
        tier_wording(codex, project_tiers, "deep") == "Pass `reasoning_effort: high` in this task's spawn_agent call."
    )


def test_a_project_row_of_another_harness_changes_nothing() -> None:
    project_tiers = {"codex": {"fast": TierRow(model="gpt-6-luna")}}

    assert tier_wording(adapter_for("claude-code"), project_tiers, "fast") == (
        "Pass `model: haiku` in this task's Agent call."
    )


def test_an_empty_project_row_asks_for_nothing() -> None:
    project_tiers = {"claude-code": {"deep": TierRow()}}

    assert tier_wording(adapter_for("claude-code"), project_tiers, "deep") == ""
