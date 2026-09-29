# Changelog

## Unreleased

- **Choose where the hooks go:** the new `hook_files` setting in `.pskill/config.yaml` lists the files that get the two hooks. The default is each app's own file, as before. A project that generates its app settings from its own source lists that source instead.
- **`harnesses` is now `permissions`:** it only decides which apps get the rule to run pskill without asking. Rename the setting in `.pskill/config.yaml`; the old name stops with an error that says so.
- **One update is enough:** `pskill update` now runs its `sync` in a new process, with the runner that it just installed. Before, the `sync` ran the old code, so new hook commands or stubs arrived only with a second `pskill sync`.

## 0.2.1 (2026-09-29)

A fix for projects that have the hooks but not the runner.

- **Hooks without the runner:** the hook commands now do nothing when `.pskill/pskill.py` is missing. Before, `uv` failed with exit code 2, which Claude Code and Codex read as "do not stop", so the agent was pushed on at every stop. The new commands also work in bash, PowerShell, and cmd. Run `pskill update` (or `pskill sync`) to get them.

## 0.2.0 (2026-09-29)

A new run viewer.

- **New run viewer:** each run is a flow canvas. The skill graph fills the screen, with the path the run took, and child skills in a frame next to their call block. Click a step to see its packet, answers, and output, and drag the replay bar to see the run as it was at any step. The viewer now loads two fonts from Google Fonts; offline it uses the system fonts.
- **Parallel blocks in the viewer:** a block that runs its tasks one by one now shows its final result on its last task, once, also when the block runs again.

## 0.1.2 (2026-09-29)

Fixes from the real Codex runs.

- **Harness switch:** `current` now records a new harness, like `submit` and `resume`. Before, a run continued with `current` in another agent app kept the old app's name, so that app's Stop hook ignored the run until the first answer.
- **Parallel tasks:** the last subagent now gets only "all tasks are done", not the next block. The main agent reads the next block with `current`.
- **Codex needs Full access:** the README and `SPEC.md` (L7) now say so. In the Codex sandbox, the runner cannot send answers.

## 0.1.1 (2026-09-29)

Fixes from the first runs in a real Claude Code session.

- **Parallel blocks:** `submit` now takes `--task <n>`. Before, the command rejected the option that the packets tell the agent to use, so no parallel block could finish.
- **Git ignore:** `init` now also ignores `.pskill/__pycache__/` folders. In a project from 0.1.0, add `__pycache__/` to `.pskill/.gitignore` by hand.

## 0.1.0 (2026-09-28)

The first release.

- **Skills as graphs:** `skill.yaml` with six block types (`task`, `decision`, `parallel`, `script`, `call`, `end`), typed inputs and outputs, `{{ }}` computed values, visit caps, and nested skill calls.
- **The runner:** one packet per block, one `submit` command per answer (YAML on stdin), typed answer checks with plain-word errors, retries, pause and resume across sessions and harnesses, and an interactive or autonomous mode.
- **Harnesses:** Claude Code and Codex adapters (stubs, Stop and SessionStart hooks, a permission rule, parallel subagents), plus a `generic` adapter for any other harness.
- **Tools:** `validate`, `test` (a scripted fake agent), `sync`, `init`, `update`, and a read-only `view`er with a step-through timeline.
- **Proof skills:** `implement-issue`, `review-pr`, and `create-issue`, with 13 test cases.
