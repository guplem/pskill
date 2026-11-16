# Plan: issue 201, read run.json under the run lock in the key check

## Goal
`check_run_key` reads `run.json` under `run_lock`, so it never races an `os.replace` on Windows. A refused command writes nothing and logs no event. A test covers the locked read.

## Decisions
- Lock inside `check_run_key` only, not inside `read_run_info` (others hold the lock; it is not re-entrant).
- `with run_lock(run_folder(project, run_id)):` keeps the "There is no run" error for an unknown run.
- Raise the refusal after the `with`. Let RunLockTimeout propagate. No CHANGELOG/version change.

## Approach
`pskill_runner/engine.py` `check_run_key`: copy `run_waits.read_when_free` and the engine's `with run_lock(run_folder(...))` blocks.

## Steps
1. Red: test in `tests/test_engine.py` next to the key tests: wrap `engine.read_run_info`, record whether the lock file exists during the read; assert it did and is gone after.
2. Green: take the lock around the read in `check_run_key`, with a short Windows comment.
3. Refused check test: run folder files unchanged (no event, run.json same), lock gone.

## Lists
- New cases: read under lock (step 1 test); refused check writes nothing (step 3 test).
- Stale texts: none expected; check `git grep "check_run_key"` and the docstring.
- Reused code: `run_lock`, `run_folder`, pattern of `run_waits.read_when_free`.

## Checks
`uv run dev.py fast`, then `uv run dev.py check`; CI on three OS.

## Out of scope
Other unlocked readers (`list_runs`, viewer).
