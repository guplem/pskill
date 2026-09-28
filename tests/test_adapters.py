"""Tests for pskill_runner.adapters."""

import pytest

from pskill_runner.adapters import AdapterError, adapter_for, detect_harness


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
