# Plan: a script with `parse: json` keeps its whole output (#139)

## Goal

A `script` block with `parse: json` works when its script prints more than 64 KB. A cut text output says it was cut.

Acceptance:

- A `parse: json` script that prints a JSON value over 64 KiB succeeds, and `steps.<id>.json` holds the whole value.
- A text stdout or a stderr over the limit keeps its first 64 KiB plus a note that names the limit and the real size.
- An output within the limit is stored as it is, with no note.
- The failure message of a script that exits non-zero still shows the real end of its stderr.
- SPEC.md 6.4 and 10.3, AUTHORING.md, and CHANGELOG.md say so. Version 0.32.1.

## Decisions

- **Where the limit lives:** the executor returns the whole output. The engine applies the limit, because only it
  knows `parse`. `pskill test` (recorded results) then follows the same rule.
- **What `parse: json` keeps:** the whole stdout, in `steps.<id>.stdout`, `steps.<id>.json`, and the `script_ran`
  event. The viewer parses that event's stdout as JSON, so it must stay whole. Its stderr is still cut.
- **Order:** the engine checks the whole result (`script_problem`), then cuts what it logs and stores. So the stderr
  tail in the failure message is the real end of stderr, never the note.
- **The note:** appended on its own line: `[pskill cut this output: it keeps the first 65536 of 200000 characters.]`
- **Schema version:** no bump. The `script_ran` fields and their types stay the same; only the 10.3 wording changes.
- **Constant:** `OUTPUT_LIMIT_CHARACTERS` keeps its name and value, and moves to `engine.py` (its only user).

## Approach

- `pskill_runner/inline_executor.py`: `RealExecutor.run_script` returns `completed.stdout` and `completed.stderr`
  whole. Remove the constant.
- `pskill_runner/engine.py`: next to `script_problem`, add `OUTPUT_LIMIT_CHARACTERS`, a helper
  `limited_output(text) -> str` (cut plus note, copying the `TASK_NAME_LIMIT` style), and
  `stored_result(result, parse) -> ScriptResult` (`replace` with the cut stdout, unless `parse == "json"`, and the cut
  stderr). `Run.run_script` checks the whole result, then logs and stores the stored result.
- Docs: SPEC.md 6.4 (a bullet and a "Changed in 0.32.1 (#139)" sentence), SPEC.md 10.3 `script_ran` row,
  AUTHORING.md (one sentence), CHANGELOG.md 0.32.1, version in `__init__.py`, `pyproject.toml`, `uv.lock`.

## Steps

1. Red: an engine test where a `parse: json` script prints JSON over 64 KiB; it fails with "not valid JSON". Red: an
   executor test that a long output is kept whole. Green: the executor stops cutting; the engine stores the whole
   output for now.
2. Red: engine tests that a text stdout and a stderr over the limit keep the first 64 KiB plus the note (with sizes),
   and that the failure message of a non-zero exit shows the real stderr end. Green: `limited_output` and
   `stored_result` in `run_script`.
3. Docs, CHANGELOG, and version bump.

## Checks

- Tests: `tests/test_engine_blocks.py` (json over the limit, text over the limit, stderr over the limit with a
  non-zero exit, existing tests cover within the limit) and `tests/test_inline_executor.py` (long output kept whole).
- Local: `uv run ruff format --check . && uv run ruff check . && uv run mypy && uv run pytest --cov &&
  uv run pskill.py validate && uv run pskill.py test`.
- CI: the same checks on Windows, macOS, and Linux.

## Out of scope

- A per-block limit option (no new skill keyword).
- Shortening AUTHORING.md to its 150-line target.
