# Plan: packets call the runner through `.pskill/pskill.py` (#130)

## Goal

Every command in every packet starts with `uv run .pskill/pskill.py`. This holds in a pinned project and in this repository (dev pin).

Acceptance criteria:

- A pinned project prints `uv run .pskill/pskill.py` in start, task, submit, current, pause, resume, and cancel commands.
- This repository prints the same prefix.
- An autonomous Claude Code run needs only the `Bash(uv run .pskill/pskill.py *)` rule.
- A test calls the real `runner_command`, with the package outside the project.

## Decisions

- **Source of the path:** `project.pskill_folder / ENTRY_SCRIPT_NAME`, relative to `project.root`, with `.as_posix()`. Agreed in the issue.
- **Fallback branch:** remove the `try/except ValueError`. The launcher is always inside the project root.
- **`import pskill_runner`:** keep it. `engine.py` still reads `pskill_runner.__version__`.
- **Version:** raise 0.30.0 to 0.30.1, with a `CHANGELOG.md` section. The repository releases each fix.

## Approach

- `pskill_runner/engine.py` `runner_command`: copy the launcher path from `sync.py` (`project.pskill_folder / "pskill.py"`).
- `tests/test_engine.py`: new tests with `make_project` and `start_run`.
- `pskill_runner/__init__.py`, `pyproject.toml`, `CHANGELOG.md`: the release.

## Steps

1. Red: a test that `runner_command(project)` is `uv run .pskill/pskill.py`, and that a started run's packet holds `uv run .pskill/pskill.py submit <run id>`. Green: change `runner_command`.
2. Raise the version to 0.30.1 and add the changelog section.

## Checks

- Local: `uv run pytest tests/test_engine.py`, then the full CI command from `AGENTS.md`.
- CI: the checks on Windows, macOS, and Linux.

## Out of scope

- The empty pin of the cache copy of `pskill.py`.
- The short `pskill task` form in `SPEC.md` section 8.
