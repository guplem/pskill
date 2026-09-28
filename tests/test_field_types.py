"""Tests for pskill_runner.field_types."""

from typing import Any

from pskill_runner.field_types import FieldSpec, check_answer, parse_field_map

PLAN_FIELDS = parse_field_map(
    {
        "status": {"type": "string", "enum": ["finished", "question"], "description": "Plan state."},
        "plan": {"type": "string", "description": "The plan."},
        "question": {"type": "string", "optional": True, "description": "The open question."},
    }
)


def test_parse_field_map_reads_every_attribute() -> None:
    fields = parse_field_map(
        {
            "tags": {"type": "array", "items": {"type": "string"}, "description": "Labels."},
            "count": {"type": "integer", "optional": True, "default": 1, "description": "How many."},
        }
    )

    assert fields["tags"] == FieldSpec(type="array", description="Labels.", items=FieldSpec(type="string"))
    assert fields["count"] == FieldSpec(type="integer", description="How many.", optional=True, default=1)


def test_check_answer_converts_text_to_the_declared_types() -> None:
    fields = parse_field_map(
        {
            "number": {"type": "integer", "description": "d"},
            "ratio": {"type": "number", "description": "d"},
            "done": {"type": "boolean", "description": "d"},
            "name": {"type": "string", "description": "d"},
            "items": {"type": "array", "items": {"type": "integer"}, "description": "d"},
            "place": {
                "type": "object",
                "properties": {"file": {"type": "string"}, "line": {"type": "integer"}},
                "description": "d",
            },
        }
    )
    raw_answer: dict[str, Any] = {
        "number": "42",
        "ratio": "0.5",
        "done": "true",
        "name": "1.10",
        "items": ["1", "2"],
        "place": {"file": "a.py", "line": "7"},
    }

    value, errors = check_answer(raw_answer, fields)

    assert errors == []
    assert value == {
        "number": 42,
        "ratio": 0.5,
        "done": True,
        "name": "1.10",
        "items": [1, 2],
        "place": {"file": "a.py", "line": 7},
    }


def test_check_answer_keeps_the_text_no_for_a_string_field() -> None:
    fields = parse_field_map({"choice": {"type": "string", "enum": ["yes", "no"], "description": "d"}})

    value, errors = check_answer({"choice": "no"}, fields)

    assert errors == []
    assert value == {"choice": "no"}


def test_check_answer_names_the_field_that_does_not_convert() -> None:
    fields = parse_field_map(
        {"number": {"type": "integer", "description": "d"}, "done": {"type": "boolean", "description": "d"}}
    )

    _, errors = check_answer({"number": "many", "done": "yes"}, fields)

    assert errors == ["number: 'many' is not an integer", "done: 'yes' is not true or false"]


def test_check_answer_reports_missing_unknown_and_enum_errors() -> None:
    _, errors = check_answer({"status": "maybe", "extra": "x"}, PLAN_FIELDS)

    assert "'plan' is a required field" in errors
    assert "extra: this field is not part of the return format" in errors
    assert "status: 'maybe' is not one of: finished, question" in errors


def test_check_answer_rejects_an_answer_that_is_not_a_mapping() -> None:
    _, errors = check_answer("just text", PLAN_FIELDS)

    assert errors == ["The answer must be a list of 'field: value' lines, not plain text."]
