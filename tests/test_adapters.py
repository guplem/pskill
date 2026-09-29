"""Tests for pskill_runner.adapters."""

import pytest

from pskill_runner.adapters import AdapterError, adapter_for, detect_harness, detect_hook_harness


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
