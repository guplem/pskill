"""Tests for pskill_runner.adapters."""

import pytest

from pskill_runner.adapters import AdapterError, adapter_for, detect_harness, detect_hook_harness, detect_session_id
from pskill_runner.skill_model import MODEL_TIERS, TOOL_PROFILES


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
    wording = adapter_for("claude-code").tier_wording

    assert "`model: haiku`" in wording["fast"]
    assert "`model: sonnet`" in wording["standard"]
    assert "`model: opus`" in wording["deep"]


def test_codex_asks_for_the_reasoning_effort_of_each_tier() -> None:
    wording = adapter_for("codex").tier_wording

    assert "`low`" in wording["fast"]
    assert "`medium`" in wording["standard"]
    assert "`high`" in wording["deep"]


def test_every_adapter_with_subagents_words_every_tier_and_generic_words_none() -> None:
    assert set(adapter_for("claude-code").tier_wording) == set(MODEL_TIERS)
    assert set(adapter_for("codex").tier_wording) == set(MODEL_TIERS)
    assert adapter_for("generic").tier_wording == {}


def test_claude_code_asks_for_the_profile_agent_of_each_tool_profile() -> None:
    wording = adapter_for("claude-code").tools_wording

    assert "`subagent_type: pskill-read`" in wording["read"]
    assert "`subagent_type: pskill-web`" in wording["web"]


def test_the_profile_wording_falls_back_to_general_purpose_when_the_agent_is_unknown() -> None:
    for wording in adapter_for("claude-code").tools_wording.values():
        assert wording.endswith("If that agent type is unknown, use `general-purpose`.")


def test_only_claude_code_words_the_tool_profiles() -> None:
    assert set(adapter_for("claude-code").tools_wording) == set(TOOL_PROFILES)
    assert adapter_for("codex").tools_wording == {}
    assert adapter_for("generic").tools_wording == {}
