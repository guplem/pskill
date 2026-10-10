# Plan: a tier maps to a model and an effort per harness (#151)

## 1. Goal

Each harness turns a parallel task's `tier` (`fast`, `standard`, `deep`) into a model and an effort, through a default table that a project can change row by row in `.pskill/config.yaml` under `tiers`.

Acceptance criteria (from the issue):

- A project row `codex.fast: {model: gpt-6-luna, effort: low}` gives a Codex packet that passes both values to `spawn_agent`. That a real run logs the subagent on that model and effort is a **manual** check (the issue has the `manual` label, and this container has no Codex).
- A Claude Code row with `effort` gives a packet that passes it to the Agent call.
- A project row changes the packet for that tier only.
- Config loading (so `pskill validate` and every other command) rejects an unknown harness, tier, or key. `pskill validate` warns on a Codex model that is missing from the catalog or has an `upgrade`.
- SPEC.md §6.3 and AUTHORING.md describe the table, with no VERIFY left on the Codex tier.

## 2. Decisions

- **Row:** `TierRow(model: str | None, effort: str | None)`. A missing model keeps the session's model, and a missing effort keeps the model's default. A row with neither key gives no packet line.
- **Defaults** (no versioned names): claude-code `fast/standard/deep` → `model: haiku/sonnet/opus`; codex → `effort: low/medium/high`.
- **Override:** a project row replaces the default row for that harness and tier entirely. Other rows keep their defaults.
- **Harness keys:** the adapters that spawn subagents (`claude-code`, `codex`), taken from `ADAPTERS`, not from `PERMISSION_APPS`. Generic has no row and still ignores the tier.
- **Config errors:** `ProjectError` at load, prefixed with the path and naming the known values. The cases: `tiers` is not a mapping, an unknown harness, a harness value that is not a mapping, an unknown tier, a row that is not a mapping, an unknown key (known: `effort`, `model`), or a value that is not a non-empty string.
- **Wording:**
  - Claude Code: "Pass `model: X` and `effort: Y` in this task's Agent call." The Agent tool's `effort` parameter is the one Claude Code documents for subagents.
  - Codex: "Pass `model: X` and `reasoning_effort: Y` in this task's spawn_agent call." The source is Codex CLI 0.158.0, from the evidence in #151.
  - With only one key, only that one is named.
- **Codex catalog** (answer to the gap): `$CODEX_HOME/models_cache.json`, else `~/.codex/models_cache.json`; an empty `CODEX_HOME` counts as unset. Its models sit under `models[]`: `slug` is the name, and `upgrade` is `null` or `{model, retirement_at?}`. Read only `slug` and `upgrade.model`.
  - The check is skipped when the file is missing, or cannot be read or parsed (it is a cache that Codex rewrites).
  - It warns for each project Codex row whose model is not a slug.
  - It warns for each such model with an upgrade, and names `upgrade.model`.
  - Warnings do not change the exit code.

## 3. Approach

- `pskill_runner/adapters.py`:
  - Add the `TierRow` dataclass.
  - Replace `tier_wording: Mapping[str, str]` with:
    - `tier_rows: Mapping[str, TierRow]`, the defaults;
    - `spawn_call: str`, which is `Agent` or `spawn_agent`;
    - `effort_parameter: str`, which is `effort` or `reasoning_effort`.
  - Add `SPAWNING_HARNESSES`.
  - Add the pure function `tier_wording(adapter, project_tiers, tier) -> str`, which merges a project row over the default and builds the sentence.
  - Doc-URL comments. Drop the VERIFY.
- `pskill_runner/project.py`: `Config.tiers: Mapping[str, Mapping[str, TierRow]]`, with an empty default. `load_config` checks the raw mapping with small helpers (copying the `permissions` check), then builds `TierRow`s.
- `pskill_runner/engine.py` `task_prompt`: `spawn_wording=tier_wording(self.adapter, self.project.config.tiers, task tier)`. This copies the engine's existing `self.project.config.retries` reads.
- `pskill_runner/codex.py`, each with its source in the module docstring:
  - `codex_home(environment)`, copying `install.cache_root`;
  - `read_model_catalog(path) -> dict[str, str | None] | None`, which maps a slug to its upgrade model and copies `hook_settings.read_json_settings`;
  - `tier_model_problems(tiers, environment) -> list[Problem]`.
- `pskill_runner/cli.py` `validate_command`: when every skill is checked, add the catalog warnings as `warning (config)  tiers.codex.<tier>: ...` lines. This copies the `(stubs)` lines.
- Docs:
  - SPEC §6.3 tier paragraph ("Changed in 0.35.0 (#151)"), §9.1 Model tier row, §10.1 list and example, §11 warnings;
  - AUTHORING.md tier bullet;
  - `viewer/field_help.js` tier help;
  - a commented `tiers` example in `install.py` DEFAULT_CONFIG only if it fits its style.
- Release: 0.35.0 in `pskill_runner/__init__.py` and `pyproject.toml`, plus a CHANGELOG `## 0.35.0` section.

## 4. Steps (one red-green cycle each)

1. Adapters: `TierRow`, the default rows, and `tier_wording` with no project rows. The tests in `tests/test_adapters.py` are rewritten.
2. Adapters: a project row replaces its default row only, and a row with model + effort names both (Codex `reasoning_effort`, Claude Code `effort`). An empty row gives "".
3. Project: `tiers` loads into `TierRow`s, and each invalid shape raises `ProjectError` (one test per branch).
4. Engine: the packet uses the project row (the Codex row `gpt-6-luna`/`low` reaches the spawn_agent line, and the other tiers are unchanged). The loose `test_engine_blocks.py` checks are rewritten.
5. Codex catalog: the path from `CODEX_HOME` or home, reading the catalog (missing, broken, or valid), and the warnings for a missing model and for an upgrade.
6. CLI: `pskill validate` prints the catalog warning lines and counts them, with exit code 0. The tests set `CODEX_HOME` to a temp folder.
7. Docs, viewer help, CHANGELOG, and the version bump.

## 5. Checks

- New and changed tests in `tests/test_adapters.py`, `tests/test_project.py`, `tests/test_engine_blocks.py`, `tests/test_codex.py`, and `tests/test_cli.py`.
- Local: `uv run ruff format --check . && uv run ruff check . && uv run mypy && uv run pytest --cov && uv run pskill.py validate && uv run pskill.py test`.
- CI: the same on Linux, macOS, and Windows (paths and `CODEX_HOME` on Windows).

## 6. Out of scope

- Tool limits per subagent (§18.1; PR #153).
- An OpenCode adapter.
- Model or effort keys in `skill.yaml`.
- The real Codex run (manual).
