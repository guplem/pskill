# Plan: a recorded call can check the inputs that the call block sends (#135)

## Goal

In `pskill test`, a recorded call entry can state `inputs:`. The case fails when the call block sends other values.

Acceptance criteria:
- A recorded call can state the inputs that its visit must send. A difference fails the case, and the message names the block, the visit, the input, and the expected and actual values.
- A recorded call without `inputs` passes as today.
- `SPEC.md` section 12 and `AUTHORING.md` describe the new key.

## Decisions

- **Key:** `inputs`, inside each recorded call entry: `{status, outputs, inputs}`. No change to `CASE_KEYS`.
- **Partial match:** check only the inputs that the entry names. A named input that the block does not send is a mismatch (actual value `None`).
- **Comparison:** plain equality of the case's YAML values and the computed values. No text conversion.
- **Message:** `the call block 'review' sent the input 'reported' = [] on visit 1, but the case expects ['a']`.
- **Visit:** a 1-based counter per call block in `RecordedExecutor`.
- **Release:** 0.32.0, because Galtea-AI/monorepo#5858 waits for it.

## Approach

- `pskill_runner/skill_tests.py`: `RecordedExecutor` gets `call_visits: dict[str, int]`. `call_result` counts the visit and calls a small helper `check_call_inputs(block_id, visit, expected, actual) -> None`, which raises `SkillTestError`. It copies the partial match of `expectation_problem`.
- `tests/test_skill_tests.py`: tests in the style of `test_calls_use_the_recorded_child_results`.
- `.pskill/skills/implement-issue/tests/review-loop-converges.yaml`: `inputs:` on both `review` entries.
- `SPEC.md` section 12, `AUTHORING.md` edit loop step 1, the module docstring.
- `pskill_runner/__init__.py`, `pyproject.toml`, `CHANGELOG.md`: version 0.32.0.

## Steps

1. Red: a matching `inputs: {name: Ada}` passes; `{name: Bob}` fails with the exact message. Green: the check.
2. Red: a named input the block does not send fails with actual `None`; a direct second `call_result` names visit 2. Green if needed.
3. Example case: add `inputs:` to `review-loop-converges.yaml` (see it fail with a wrong value first).
4. Docs: `SPEC.md`, `AUTHORING.md`.
5. Release: version 0.32.0 and the CHANGELOG section.

## Checks

Local: `uv run pytest --cov`, `uv run ruff format --check .`, `uv run ruff check .`, `uv run mypy`, `uv run pskill.py validate`, `uv run pskill.py test`. CI runs the same on Windows, macOS, and Linux.

## Out of scope

- The stdin of script blocks.
- The engine and the `InlineExecutor` protocol.
