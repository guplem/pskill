"""Tests for pskill_runner.computed_values."""

from pathlib import Path
from typing import Any

import pytest

from pskill_runner.computed_values import (
    ComputedValueError,
    compute,
    find_references,
    is_single_expression,
    is_true,
    render_text,
    syntax_errors,
)

CONTEXT: dict[str, Any] = {
    "inputs": {"issue": "42", "count": 5},
    "steps": {"plan": {"status": "question", "items": ["a", "b"]}},
    "history": {"plan": [{"status": "question"}], "ask_user": []},
}


def test_plain_values_stay_as_they_are() -> None:
    assert compute("implemented", CONTEXT) == "implemented"
    assert compute(False, CONTEXT) is False
    assert compute(3, CONTEXT) == 3


def test_exactly_one_expression_keeps_the_type_of_its_result() -> None:
    assert compute("{{ inputs.count + 1 }}", CONTEXT) == 6
    assert compute("{{ steps.plan.items }}", CONTEXT) == ["a", "b"]
    assert compute(" {{ steps.plan.status == 'question' }} ", CONTEXT) is True


def test_text_with_expressions_renders_to_text() -> None:
    assert compute("Issue {{ inputs.issue }} has {{ inputs.count }} parts", CONTEXT) == "Issue 42 has 5 parts"


def test_lists_and_mappings_are_computed_item_by_item() -> None:
    value = compute({"pr": "{{ inputs.count }}", "tags": ["{{ inputs.issue }}", "plain"]}, CONTEXT)

    assert value == {"pr": 5, "tags": ["42", "plain"]}


def test_a_missing_value_can_be_chained_and_replaced_with_default() -> None:
    assert compute("{{ steps.create_issue.outputs.number | default(inputs.issue) }}", CONTEXT) == "42"


def test_a_comparison_with_a_missing_value_is_false() -> None:
    assert compute("{{ steps.create_issue.status == 'succeeded' }}", CONTEXT) is False


def test_printing_a_missing_value_fails() -> None:
    with pytest.raises(ComputedValueError, match="missing"):
        compute("Comment: {{ steps.confirm.comment }}", CONTEXT)


def test_a_single_expression_that_gives_a_missing_value_fails() -> None:
    with pytest.raises(ComputedValueError, match="missing"):
        compute("{{ steps.confirm.comment }}", CONTEXT)


def test_iterating_over_a_missing_value_fails() -> None:
    with pytest.raises(ComputedValueError, match="missing"):
        render_text("{% for item in steps.nothing.list %}{{ item }}{% endfor %}", CONTEXT)


def test_iterating_over_an_empty_history_gives_no_items() -> None:
    assert render_text("[{% for qa in history.ask_user %}{{ qa }}{% endfor %}]", CONTEXT) == "[]"


def test_is_true_reads_a_condition() -> None:
    assert is_true("{{ steps.plan.status == 'question' }}", CONTEXT) is True
    assert is_true("{{ (inputs.issue | int(0)) > 100 }}", CONTEXT) is False


def test_is_single_expression_recognizes_the_typed_form() -> None:
    assert is_single_expression("{{ a.b }}")
    assert not is_single_expression("x {{ a.b }}")
    assert not is_single_expression("{{ a }} {{ b }}")
    assert not is_single_expression("plain")


def test_syntax_errors_reports_a_broken_expression() -> None:
    assert syntax_errors("{{ steps.plan.status == }}") != []
    assert syntax_errors("Issue {{ inputs.issue }}") == []


def test_find_references_lists_the_names_used_per_namespace() -> None:
    text = "{% for qa in history.ask_user %}{{ qa }}{% endfor %} {{ steps.plan.status }} {{ inputs.issue | int }}"

    assert find_references(text) == {("history", "ask_user"), ("steps", "plan"), ("inputs", "issue")}


def test_to_file_writes_the_text_and_returns_its_path(tmp_path: Path) -> None:
    context = {**CONTEXT, "run": {"dir": str(tmp_path)}}

    path = compute("{{ 'long body' | to_file }}", context)

    assert Path(path).read_text(encoding="utf-8") == "long body"
    assert Path(path).parent == tmp_path / "files"
