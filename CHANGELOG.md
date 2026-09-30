# Changelog

## 0.8.2 (2026-09-30)

A generated hooks source keeps its hooks.

- **A generated hooks source keeps its hooks:** when `hook_files` lists a project's own hooks source, and the project's generator copies it into `.claude/settings.json` and `.codex/hooks.json`, `sync` now leaves the shared hooks in those two files. Before, `sync` removed them, and `sync --check` always reported both files as out of date.

## 0.8.1 (2026-09-30)

A warning about `history` in a loop that can run again.

- **The scope of `history`:** AUTHORING.md and SPEC.md now say that `history` holds every output of the skill's run, not one pass through a loop. A per-item loop that counts answers with `history.<block> | length` reads past its list when an earlier block leads back into it. The fix: put such a loop in its own `internal` skill, and run it with a `call` block. Each call starts with an empty `history`.

## 0.8.0 (2026-09-30)

A name for each parallel task.

- **A name for each parallel task:** a `parallel` block can set `task_name`, a `{{ }}` value per item, for example `task_name: "{{ item.name }}"`. The packet heads each task with its name, and the viewer shows it on the task's node and chip instead of "task 0". When the name is missing or empty, the task keeps its number. The proof skills name their tasks: `implement-issue` by agent, and `review-pr` by review focus.

## 0.7.1 (2026-09-30)

A label on every block of the proof skills.

- **A label on every proof-skill block:** each block of `create-issue`, `implement-issue`, and `review-pr` now has a short `description`. The viewer shows it in the block's hover hint, and "Export as Markdown" shows it under each step.

## 0.7.0 (2026-09-29)

A help button for every field on the skill screen.

- **Help for every field:** on the skill screen, each field of a block has a "?" button, in the side panel and in the editor. Hover it to see what the field is. Click it to open a dialog with the details and YAML examples. The goal, the inputs, and the outputs of the skill have one too.

## 0.6.1 (2026-09-29)

A fix for the arrow tips in dark mode.

- **Arrow tips in dark mode:** the arrow tips on the canvas were black, so the dark theme hid them. They now take the color of their line: blue on a taken edge, grey on the others.

## 0.6.0 (2026-09-29)

A Skills screen that shows, exports, and edits each skill, and more ways to route and retry.

- **Edit a skill in the viewer:** on the skill screen, "Edit" lets you change a block (its instruction, edges, choices, visit cap, retries, and more), add a block, or delete one. A save writes `skill.yaml`: only the changed block's lines change, and its comments stay. A change that would break the file's structure is refused. The runner now needs one more package, `ruamel.yaml`; `uv` installs it on the next run.
- **Export a skill as Markdown:** the skill screen has an "Export as Markdown" button. It downloads a zip with a plain `SKILL.md` that any agent can follow without pskill: every block is a numbered step, every edge a "go to step N" line, and every `{{ }}` value a plain name. The skill's scripts, its subagent roles, and its child skills come with it.
- **A Skills screen in the viewer:** it lists every skill, also a skill that never ran. Open one to see its graph without a run. Click a block to see its instruction, its fields, its choices, and where it can go. A call block links to its child skill. The screen also shows what `pskill validate` finds. A run links to its skill's graph.
- **A small start dot:** the graph starts at a small dot instead of a large circle.
- **A choice can lead to different blocks:** in a decision with choices, a choice can take an edge list instead of one block. The runner follows the choice, then the first matching edge. A per-item loop can now keep the question buttons; `AUTHORING.md` shows the pattern.
- **A hint for `?` in test cases:** when a case file fails to parse at a `?` inside `{ }`, `pskill test` now says to put the value in quotes, with the fixed line as an example.
- **Retries and a timeout per block:** a `task`, `decision`, `parallel`, or `script` block can set its own `retries`, and a `script` block its own `timeout_s`. Each one overrides the global value in `.pskill/config.yaml` for that block. The canvas hint names them.
- **Parallel answers on Windows:** when two subagents submitted at the same moment, one could fail with "Permission denied" on the run's lock file. The runner now waits for the lock instead.

## 0.5.0 (2026-09-29)

Block icons, and a tidier side panel.

- **An icon per block type:** task, decision, parallel, script, call, and end each have their own icon, on the canvas and in the side panel, in the color of the step's state.
- **A tidier side panel:** the block's explanation sits right under its type and no longer repeats the type. A selected chip is blue, not black.

## 0.4.0 (2026-09-29)

A run viewer that a person who did not write the skill can follow.

- **Tooltips on the canvas:** hover a step to see what its block type does and who decides. Hover an edge to see when the run takes it, with its whole condition.
- **Subagents on the canvas:** a parallel block shows one node per task, colored by its state: done, rejected answer, or open. Click a task to see its prompt, its answers, and its output.
- **A readable side panel:** each step names its input and its output. Packets show as formatted Markdown, JSON shows as a tree that folds, and a script shows its command, its exit code, and its parsed result. Long content shows 3 lines until you ask for all of it.
- **A wider panel:** drag the panel's left edge. The viewer keeps the width.

## 0.3.0 (2026-09-29)

Choose where the hooks go, and `harnesses` becomes `permissions` (rename it in `.pskill/config.yaml`).

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
