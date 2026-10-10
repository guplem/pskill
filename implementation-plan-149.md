# Implementation plan: #149, a parallel block chooses the tool profile of its subagents

## 1. Goal

A `parallel` block gets an optional field `tools`: a profile name, or one `{{ }}` value per item, like `tier`.
A Claude Code subagent of a task with a profile starts as `subagent_type: pskill-<profile>`, an agent that
`pskill sync` writes with a short tool list and no prompt and no model. A block with no `tools` gets the same
packet as today.

Acceptance criteria (from the issue):
- A block with `tools: read` gets a Claude Code packet that asks for `subagent_type: pskill-read`, and that
  subagent has only the shell, read and search tools.
- A block with no `tools` gets the same packet as today (byte for byte).
- `pskill sync` writes `pskill-read` only when a skill uses `read`, and removes it when no skill does.
  `pskill sync --check` fails when it is stale.
- `pskill validate` rejects `tools: write`.
- SPEC.md, AUTHORING.md, and the 18.1 backlog row describe the field.

## 2. Decisions

- **Profiles.** `TOOL_PROFILES = ("read", "web")` in `skill_model.py`, next to `MODEL_TIERS`, with
  `tool_profile_choices()` ("read or web"). The harness tool names live in `claude_code.py`:
  - `read`: `Bash, Read, Grep, Glob, Write`
  - `web`: `Bash, Read, Grep, Glob, Write, WebFetch, WebSearch`
  `Write` is added to the issue's list on purpose: a subagent submits a long answer through a file
  (`submit --file`, D16), because the Bash tool on Windows breaks long heredocs; without `Write` a `read`
  subagent has no way to write that file. The profile is not a security boundary (the shell writes anyway).
- **Claude Code agent file** (https://code.claude.com/docs/en/sub-agents, read 2026-10-10):
  `.claude/agents/pskill-<profile>.md`, frontmatter `name`, `description` ("Only for pskill tasks. Never choose
  it on your own."), `tools` as a comma string; no `model`, so the Agent call's `model` (tier) still wins and
  otherwise the main model is used. A `tools` list drops MCP tools and the Agent tool. Body: the generated
  marker only (no prompt). A new `.claude/agents/` folder needs a session restart before Claude Code sees it:
  say so in AUTHORING.md and the README.
- **Codex ignores `tools`**, like generic. In the openai/codex source a custom agent file cannot set
  `sandbox_mode` or `mcp_servers` (the child keeps the parent's sandbox and MCP servers), and it needs a
  non-blank `developer_instructions`. A Codex profile agent would promise a limit it does not keep. Code
  comment in `adapters.py` with the source, SPEC 9.1 row says so. This answers the issue's Codex open question.
- **Role files** (`.pskill/agents/<role>.md`) do not get a default `tools`: one way to do each thing. Say so in
  the PR. The 18.1 row keeps the pskill-agent part as future.
- **Which apps:** sync writes Claude Code profile agents when `claude-code` is in `config.permissions` (the
  apps that pskill sets up, the anchor `permission_changes` already uses). Documented in SPEC 10.1.
- **Which profiles are used:** a written value counts as that profile; a `{{ }}` value counts as every profile
  (it is known only at run time). Every loaded skill counts, internal ones too.
- **Hand-written file with the same name:** sync stops with an error, like stubs (`StubError`); a hand-written
  file with another name is never touched. Delete only marked files that are no longer wanted.
- **Packets.** The block line (`general-purpose`) stays as it is. A task with a profile gets a per-task line
  under `#### Task <n>`: "Pass `subagent_type: pskill-read` in this task's Agent call, instead of
  `general-purpose`." Tier and profile wordings join with a space in the one `spawn_wording` line (profile
  first). No profile and no tier: no line, as today.
- **Validate** reports a stale profile agent like a stale stub, so CI (which runs `pskill validate`, not
  `sync --check`) catches it. Session start does not write profile agents (SPEC 9.2 "one job" stays).
- **Engine:** `task_tools` copies `task_tier`: empty computed value means none; unknown value raises
  `RunnerStop("The tools of 'x' must be read or web, not 'write'.")`. Stored in `ParallelTask["tools"]`, read
  back with `task.get("tools")` for old state files.
- **Example skills:** `implement-issue.research_code` gets `tools: read` (pattern-scout and adr-checker read
  only); `research_gaps` gets `tools: web` (it reads docs). Run `uv run pskill.py sync` and commit
  `.claude/agents/pskill-read.md` and `pskill-web.md`. Add a 13.3 row.
- **Release 0.35.0.**

## 3. Approach (files, and the code each change copies)

- `skill_model.py`: `TOOL_PROFILES`, `tool_profile_choices()`, `ParallelBlock.tools` (copy `MODEL_TIERS`, `tier`).
- `skill_schema.py`, `skill_loader.py`: `"tools": {"type": "string"}`, `tools=raw.get("tools")` (copy `tier`).
- `run_records.py`: `ParallelTask.tools`.
- `engine.py`: `task_tools`, set in `start_parallel`, wording in `task_prompt` (copy `task_tier`).
- `adapters.py`: `tools_wording: Mapping[str, str]` on the adapter; Claude Code fills it, Codex and generic
  leave it empty (copy `tier_wording`).
- `validator.py`: `tools_problems` + `string_values` (copy `tier_problems`).
- `claude_code.py`: `AGENTS_RELATIVE_FOLDER`, `PROFILE_TOOLS`, `profile_agent_text(profile)`, doc URL.
- New module `profile_agents.py`: `used_profiles(catalog)`, `sync_profile_agents(project, catalog, check_only)`
  returning `StubChange`s (copy `stubs.sync_stubs`, reuse `GENERATED_MARKER`, `is_generated`, `StubError`).
  Add it to the AGENTS.md module table.
- `sync.py`: call it in `sync_project`; `cli.py` validate: report stale profile agents.
- `viewer/field_help.js`: a `tools:` entry and the `for_each` entry mention.
- Docs: SPEC 6.3, 8, 9.1, 10.1, 11, 13.3, 18, 18.1; AUTHORING.md; README; CHANGELOG 0.35.0; version bump in
  `pskill_runner/__init__.py`, `pyproject.toml`, `uv.lock`.

## 4. Steps (each one red-green)

1. Model, schema, loader: `tools` loads, defaults to None.
2. Validator: a written unknown profile is an error; a computed one is not; references inside are checked.
3. Adapters: Claude Code has one wording per profile, Codex and generic none.
4. Engine and packets: per-task line for a written and a computed profile, combined with a tier, empty
   computed value means none, unknown computed value pauses with `runner_error`, generic ignores it, no
   `tools` gives the same packet as today.
5. Profile agents: the Claude Code agent text; `sync` creates, keeps, updates, deletes; `--check` writes
   nothing; hand-written same-name file stops; other files untouched; only when `claude-code` is in
   `permissions`; LF endings.
6. Validate reports a stale profile agent.
7. Viewer help entry.
8. Example skills use `read` and `web`; run sync; commit the agent files.
9. Docs and release 0.35.0.

## 5. Checks

- Tests: `test_skill_loader.py`, `test_validator.py`, `test_adapters.py`, `test_engine_blocks.py`,
  new `test_profile_agents.py`, `test_sync.py`, `test_cli.py` (validate), `test_viewer_files.py` (exists).
- Local: `uv run ruff format --check . && uv run ruff check . && uv run mypy && uv run pytest --cov &&
  uv run pskill.py validate && uv run pskill.py test`.
- CI: the same on Windows, macOS, and Linux.

## 6. Out of scope

- An OpenCode adapter; a Codex profile agent (Codex cannot enforce it today).
- A security boundary; a free tool list per block; a `tools` default in role files.
- Writing profile agents from the session-start hook.
