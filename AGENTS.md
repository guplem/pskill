# pskill: agent guide

pskill runs agent skills written as YAML graphs of typed blocks, one block at a time. `SPEC.md` is the design: read sections 0 to 3 before any change. Do not re-open a decision in section 3. Do not add back anything in section 18.

## Map

| Path | What it is |
|---|---|
| `pskill.py` | Entry script. Holds the PEP 723 dependency block, then calls `pskill_runner.cli.main`. |
| `pskill_runner/` | The runner package. One module per concern (see `SPEC.md` section 4). |
| `tests/` | The pytest suite. One test file per module. |
| `SPEC.md` | The implementation specification. |

## Commands

| Task | Command |
|---|---|
| Install the dev environment | `uv sync` |
| Run the tests | `uv run pytest` |
| Lint and format | `uv run ruff check .` and `uv run ruff format .` |
| Type check | `uv run mypy` |
| Run the runner | `uv run pskill.py <command>` |
| Run every CI check, as CI does | `uv run ruff format --check . && uv run ruff check . && uv run mypy && uv run pytest` |

CI (`.github/workflows/pull-request-checks.yml`) runs those four checks on Windows, macOS, and Linux with Python 3.11. The ruleset on `main` requires the jobs `checks (ubuntu-latest)`, `checks (windows-latest)`, and `checks (macos-latest)`.

## Rules

- **Red-green, always.** Write the failing test first, run it, and see it fail for the expected reason. Then write the least code that passes. Commit the test with its code.
- **Simplicity first.** Code must be easy to read for a junior developer: small functions, descriptive names, explicit types, no clever tricks.
- **Dependencies live in two places.** Keep the PEP 723 block in `pskill.py` equal to `[project].dependencies` in `pyproject.toml`. A test checks this.
- **Branch and pull request.** Branch from `main`, open one pull request per issue, and close the issue from it. CI must be green on Windows, macOS, and Linux before a merge.

## Picking the next issue

"Implement the next issue" means: the open issue with the label `mvp` that no open issue blocks, with the lowest milestone number (M0, M1, ...). Check "Blocked by" with `gh api repos/guplem/pskill/issues/<n>/dependencies/blocked_by`. Never pick a `future` issue unless the user names it.
