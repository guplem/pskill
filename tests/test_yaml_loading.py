"""Tests for pskill_runner.yaml_loading."""

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
