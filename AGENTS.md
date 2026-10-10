# pskill: agent guide

pskill runs agent skills written as YAML graphs of typed blocks, one block at a time. `SPEC.md` is the design: read sections 0 to 3 before any change. Do not re-open a decision in section 3. Do not add back anything in section 18.

## Map

| Path | What it is |
|---|---|
| `pskill.py` | Entry script. Holds the PEP 723 dependency block, then calls `pskill_runner.cli.main`. |
| `pskill_runner/` | The runner package. One module per concern (table below). |
| `viewer/` | The viewer page: plain HTML, CSS, and JavaScript, no build step. It only draws what `viewer_data.py` returns. `hosted.js` is the hosted viewer's engine: picked folders, their copy, and Pyodide. |
| `docs/` | Images for the README, such as the viewer screenshot. |
| `tests/` | The pytest suite. One test file per module. |
| `SPEC.md` | The implementation specification. |
| `README.md`, `AUTHORING.md`, `CHANGELOG.md` | For users; for agents that write skills (`pskill authoring` prints it); the release notes. |
| `.pskill/skills/`, `.pskill/agents/` | The example skills and their pskill agents (`SPEC.md` section 13). They run on this repository's own issues and pull requests (the test bed). Their scripts have tests in `tests/test_skill_<skill>.py`. |

## Runner modules

| Module | Concern |
|---|---|
| `cli.py` | Commands, arguments, exit codes. No logic beyond calling the engine. |
| `engine.py` | Runs a skill block by block: edges, answers, visit caps, retries, pause and resume. |
| `run_records.py` | The typed shape of `run.json` and `state.json`. |
| `run_store.py` | Run files on disk: atomic JSON, the event trace, skill copies. |
| `packets.py` | The text that the agent sees for each block. |
| `skill_loader.py`, `skill_schema.py`, `skill_model.py` | Read `skill.yaml`, check its structure, build typed objects. |
| `validator.py` | Static checks of a loaded skill (`pskill validate`). |
| `field_types.py` | Field maps, and checking answers and outputs against them. |
| `computed_values.py` | Everything inside `{{ }}`. |
| `yaml_loading.py` | YAML 1.2 booleans for skills; plain text for answers. |
| `shells.py`, `answer_input.py` | The stdin forms of `submit`, reading stdin with a timeout, and reading an answer file (`submit --file`). |
| `adapters.py` | Harness-specific wording and abilities. |
| `inline_executor.py` | Runs `script` commands and child skills; `pskill test` swaps in recorded results. |
| `skill_tests.py` | `pskill test`: replays a case file's answers against a skill. |
| `project.py` | Finding `.pskill/` and reading `config.yaml`. |
| `stubs.py`, `sync.py` | The generated `SKILL.md` stubs, and `pskill sync` (stubs plus harness settings). |
| `hook_settings.py` | The JSON hook merge that Claude Code and Codex share. |
| `claude_code.py` | Claude Code's `.claude/settings.json` entries (hooks, permission rule) and hook output. |
| `codex.py` | Codex's `.codex/hooks.json` hooks, `.codex/rules/pskill.rules`, and hook output. |
| `hooks.py` | The Stop and session-start hook logic, for every harness. |
| `install.py` | `pskill init` and `pskill update`: the pinned entry script, the user's runner cache, and the few project files. |
| `release.py` | The release archive `pskill.zip`, and unpacking an archive given to `init` or `update`. |
| `release_plan.py` | On a merge to `main`: the tag to create for the version, and its release notes from `CHANGELOG.md`. |
| `viewer_data.py` | Everything the viewer shows: the run canvas (one Mermaid template, child skills included), timeline rows with their node and edges, summaries. |
| `skill_view.py` | The skill screen of the viewer: the skills list, and one skill's canvas and block details, with no run. |
| `agent_view.py` | The agent screens of the viewer: the agents list, one agent's text and users, and saving its text. |
| `skill_export.py` | A skill as plain Markdown skills (`SKILL.md`) in a zip, for projects without pskill. |
| `skill_editor.py` | The viewer's skill editor: change, add, or delete one block of `skill.yaml`, keeping every other line. |
| `viewer_server.py` | `pskill view`: the local server on 127.0.0.1 (the static files, and the API through `viewer_api.py`). |
| `viewer_api.py` | The viewer's API as plain functions, for the local server and for the hosted viewer (Pyodide). |
| `hosted_site.py` | Builds the hosted viewer for GitHub Pages: `viewer/` plus `pskill_runner.zip`. |

## Commands

| Task | Command |
|---|---|
| Install the dev environment | `uv sync` |
| Run the tests | `uv run pytest` (add `--cov` for the coverage report and its 100% gate) |
| Lint and format | `uv run ruff check .` and `uv run ruff format .` |
| Type check | `uv run mypy` |
| Run the runner | `uv run pskill.py <command>` |
| Run every CI check, as CI does | `uv run ruff format --check . && uv run ruff check . && uv run mypy && uv run pytest --cov && uv run pskill.py validate && uv run pskill.py test` |

CI (`.github/workflows/pull-request-checks.yml`) runs those checks on Windows, macOS, and Linux with Python 3.11. The ruleset on `main` requires the jobs `checks (ubuntu-latest)`, `checks (windows-latest)`, and `checks (macos-latest)`.

## Rules

- **Full coverage.** `uv run pytest --cov` fails below 100% of lines and branches. Test every new line. Mark a line that no input can reach with `# pragma: no cover` (or `no branch`) and its reason; never to skip a hard case.
- **Red-green, always.** Write the failing test first, run it, and see it fail for the expected reason. Then write the least code that passes. Commit the test with its code.
- **Simplicity first.** Code must be easy to read for a junior developer: small functions, descriptive names, explicit types, no clever tricks.
- **`.pskill/pskill.py` runs this checkout** (the dev pin), so the test bed always uses the current code. After a change to the root `pskill.py`, run `uv run pskill.py update --from .`; a test fails until the copy matches. Never edit `.pskill/pskill.py` by hand.
- **Dependencies live in two places.** Keep the PEP 723 block in `pskill.py` equal to `[project].dependencies` in `pyproject.toml`. A test checks this.
- **Example skills reach GitHub only through REST**, because the Claude Code cloud GitHub proxy refuses GraphQL, the search API, and `--paginate`. It is the proxy's restriction, not a pskill rule: drop it when the proxy allows them. SPEC 13.2 holds the rule and its one exception; `tests/test_skills_github_calls.py` checks it.
- **Branch and pull request.** Branch from `main`, open one pull request per issue, and close the issue from it. CI must be green on Windows, macOS, and Linux before a merge.

## Releasing

1. Raise `__version__` in `pskill_runner/__init__.py` and `version` in `pyproject.toml` (a test checks that they are equal).
2. Add the version's section to `CHANGELOG.md` (a test checks that the current version has one), and merge the pull request.
3. Do nothing more. On the merge, `.github/workflows/release.yml` tags `v<version>`, tests, builds `pskill.zip`, and publishes the GitHub release with the section as its notes.

A merge that keeps the version releases nothing. A version below the newest tag fails the workflow. Never push a release tag by hand: the workflow then finds the tag and publishes no release.

The first-install command `uv run https://raw.githubusercontent.com/guplem/pskill/main/pskill.py init` downloads `releases/latest/download/pskill.zip`, so a release must exist before it works.

## Picking the next issue

"Implement the next issue" means: the open issue with the label `mvp` that no open issue blocks, with the lowest milestone number (M0, M1, ...). Check "Blocked by" with `gh api repos/guplem/pskill/issues/<n>/dependencies/blocked_by`. Never pick a `future` issue unless the user names it.
