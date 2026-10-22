"""Tests for pskill_runner.yaml_loading."""

import pytest
import yaml

from pskill_runner.yaml_loading import load_answer_yaml, load_skill_yaml


def test_skill_yaml_keeps_yes_and_no_as_text() -> None:
    loaded = load_skill_yaml("choices:\n  yes: Go on.\n  no: Stop.\nflag: on\n")

    assert loaded == {"choices": {"yes": "Go on.", "no": "Stop."}, "flag": "on"}


def test_skill_yaml_reads_true_false_and_numbers_as_typed_values() -> None:
    loaded = load_skill_yaml("post_verdict: false\nstrict: true\nmax_visits: 3\n")

    assert loaded == {"post_verdict": False, "strict": True, "max_visits": 3}


def test_answer_yaml_reads_every_value_as_text() -> None:
    loaded = load_answer_yaml("choice: no\ncount: 3\nversion: 1.10\ndone: true\n")

    assert loaded == {"choice": "no", "count": "3", "version": "1.10", "done": "true"}


def test_answer_yaml_keeps_multi_line_text() -> None:
    loaded = load_answer_yaml("plan: |\n  1. Add the column.\n  2. Backfill it.\n")

    assert loaded == {"plan": "1. Add the column.\n2. Backfill it.\n"}


def test_answer_yaml_accepts_json() -> None:
    loaded = load_answer_yaml('{"choice": "approve", "items": ["a", "b"]}')

    assert loaded == {"choice": "approve", "items": ["a", "b"]}


def test_answer_yaml_keeps_a_plain_value_with_a_colon_as_text() -> None:
    loaded = load_answer_yaml("summary: api/src/a.ts:12: unused import\ndone: false\n")

    assert loaded == {"summary": "api/src/a.ts:12: unused import", "done": "false"}


def test_answer_yaml_keeps_a_colon_in_a_list_item_field_as_text() -> None:
    loaded = load_answer_yaml("findings:\n  - file: api/src/a.ts\n    text: line 12: unused import\n  - text: a: b\n")

    assert loaded == {"findings": [{"file": "api/src/a.ts", "text": "line 12: unused import"}, {"text": "a: b"}]}


def test_answer_yaml_keeps_quotes_inside_a_plain_value_with_a_colon() -> None:
    loaded = load_answer_yaml('$cannot_complete: the step says "push": it was refused  # note\n')

    assert loaded == {"$cannot_complete": 'the step says "push": it was refused'}


def test_answer_yaml_still_rejects_a_colon_that_no_plain_value_explains() -> None:
    with pytest.raises(yaml.MarkedYAMLError, match="mapping values are not allowed here") as raised:
        load_answer_yaml('plan: first line\n  second: "line"\n')

    assert raised.value.problem_mark is not None and raised.value.problem_mark.line == 1


def test_answer_yaml_still_rejects_other_broken_yaml() -> None:
    with pytest.raises(yaml.YAMLError):
        load_answer_yaml("items: [a, b\n")
