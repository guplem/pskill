# Plan: one task block runs one or many agent jobs (#170)

## 1. Goal

pskill 1.0.0 has one agent-work block, `task`. A task runs one job, or one job per item of `for_each`. Each job sets its `tier`, `tools`, `agent`, and `context` (`main` by default, or `fresh`). `type: parallel` is removed.

Acceptance criteria (from the issue):
- `task` takes `for_each` (optional, with the per-item `when` and `task_name` of today's `parallel`), `tier`, `tools`, `agent`, and `context: main | fresh`. Each is a fixed value or a `{{ }}` value per item.
- Outputs: without `for_each`, `steps.<id>.<field>` as today. With `for_each`, `steps.<id>.results` in item order.
- `context: fresh`: the main agent spawns a subagent that gets only the goal, its rendered instruction, and its return format (D8, D17).
- `context: main`: the main agent does the job in its own conversation. With `for_each`, it does the `main` jobs one by one, after it spawns the `fresh` ones.
- `pskill validate` gives an error, naming the block, for `tier`, `tools`, or `agent` on a job with `context: main`.
- The `generic` adapter runs every job in the main context and ignores `tier` and `tools` (L6).
- `type: parallel` is refused by `validate` and `run` with one line: "`parallel` is now `task` with `for_each`: change the type".
- One code path for both forms in the engine, packets, viewer, Markdown export, `sync`, skill tests, and Galtea upload.
- SPEC.md (6, 18 and the other mentions), AUTHORING.md, the example skills, and CHANGELOG.md describe one task block. Version 1.0.0.

## 2. Decisions

- **Every task block holds a list of jobs.** `ParallelTask` becomes `TaskJob` (`run_records.py`) with a new `context` field. Each task arrival creates its jobs (`start_jobs`, today's `start_parallel`). A task without `for_each` has one job (`item` is none), and its output is stored flat (`steps.<id>.<field>`). A task with `for_each` stores `{"results": [...]}`. An empty list completes at once, as today.
- **A job's context is computed once, when the job is created** (`job_context`, built like `task_tier`). Empty or none gives `main`. Any other value than `main` or `fresh` stops the run (`RunnerStop`). An adapter that cannot spawn subagents (`generic`) makes every job `main`. A `main` job gets no spawn wording (tier and tools ignored), and its `agent` text goes in front of its instruction, as the generic path does today.
- **Validate:** an error for `tier`, `tools`, or `agent` (fixed or `{{ }}`) when `context` is missing or written as `main`. An error for a written `context` that is not `main` or `fresh`. A computed `context` skips the rule, the way a computed tier skips the tier check; items that come out `main` then ignore tier and tools at run time.
- **Packet** (one function replaces `parallel_packet`):
  - No open fresh job: the main-agent packet of the next open main job. Without `for_each` it has no `--task`, so every existing task block prints the same packet as before. With `for_each` it uses `--task <n>`.
  - Open fresh jobs: today's spawn list (`render_parallel_packet`, heading reworded from "Parallel tasks" to "Subagent tasks"). When main jobs are open too, a section follows: do task `<n>` yourself, in this conversation, with its full instruction. The `pskill wait` line applies only when no main job is left.
- **Submit:** `--task` is required with `for_each` or with a fresh job. On a one-job main task it is optional and means job 0. The reply depends on the submitting job's context, not on `adapter.can_spawn_subagents`:
  - A fresh job never sees the next block: "Task k is recorded. d of n tasks are done.", or its own errors, or the paused line.
  - A main job: the next open main job's packet; or, when only fresh jobs are open, "recorded, wait for the subagents, then run `current`" (with the wait line when the harness can wake); or, when it was the last open job, the join and the next block's packet; or, when rejected, the packet again with the errors.
  - Attempts stay counted per job.
- **Old runs.** The loader refuses `type: parallel` with the one line. No reading mode for old copies (that would be a second code path). A run whose own skill copy has `parallel` cannot continue: `Run.skill_by_id` turns the load failure into a `RunError` with the line plus "Cancel this run and start a new one." (today it would be an internal error). `cancel` and `delete` work, because they never load the skill. The viewer still shows old runs: `load_run_skills` skips a copy that fails to load, so the run shows its steps without the canvas. The viewer keeps the `"parallel"` keys for old `block_started` rows, through one helper that is true for an old `parallel` row or a task row with tasks.
- **Trace.** `block_type` of a task block is `task`. `SCHEMA_VERSION` goes from 7 to 8. `block_started` keeps `task_names`, `skipped_tasks`, and `task_prompts` for a task with `for_each`, and adds `task_contexts` (the context of each job) when any job is fresh.
- **Galtea.** `version_facts` adds the tier facts for any task with a `tier`. `SPAN_TYPES` keeps `"parallel"` for old traces.
- **Example skills.** `implement-issue` `research_code` and `research_gaps`, and `review-round` `review`, become `type: task` with `context: fresh` (behavior unchanged). Two self-contained tasks move to a fresh context on a cheaper tier, so the examples cover a one-job fresh task and `tier`: `implement-issue` `finish` (`context: fresh`, `tier: standard`, `tools: read`, one added line to read the diff and the description first) and `review-head-check` `judge` (`context: fresh`, `tier: standard`, `tools: read`). New keys go after `description` (a skill-editor test checks the order). `resolve_item` stays in the main context: its instruction relies on earlier items, so moving it needs its own change.
- **This run.** This run of `implement-issue` uses the checkout's own runner (dev pin), and its skill copies say `type: parallel`. Once the loader refuses it, the run's next command fails. When the loader commit lands, its copies in `.pskill/runs/<run>/skills/` get the same two-line change as the example skills (by hand, in the ignored run folder), so the run goes on.

## 3. Approach

| File | Change | Copies |
|---|---|---|
| `skill_model.py` | `TaskBlock` gains `for_each`, `agent`, `task_name`, `tier`, `tools`, `context`; `ParallelBlock` removed; `CONTEXTS = ("main", "fresh")`. | `ParallelBlock` fields |
| `skill_schema.py` | `task` schema gains the optional fields; `parallel` schema removed. | `BLOCK_SCHEMAS["parallel"]` |
| `skill_loader.py` | `parallel` gives the one-line refusal; build the new `TaskBlock`. | the unknown-type message |
| `validator.py` | `main_context_problems`, `context_problems`; tier, tools, `when`, and agent-file checks run on tasks. | `tier_problems` |
| `run_records.py` | `TaskJob` with `context`; `SCHEMA_VERSION = 8`. | `ParallelTask` |
| `engine.py` | `start_jobs`, `job_context`, the job packet, submit and replies by job context, `skill_by_id` refusal. | the `--- parallel blocks ---` section |
| `packets.py` | "Subagent tasks" heading, the "do task n yourself" section, the wait line only with no main job left. | `render_parallel_packet` |
| `adapters.py`, `profile_agents.py` | profiles of fresh task jobs. | today's parallel lookups |
| `skill_tests.py` | `open_task` for every task. | itself |
| `viewer_data.py`, `skill_view.py`, `skill_export.py`, `skill_editor.py`, `agent_view.py`, `galtea.py` | task with `for_each` where parallel was; old `parallel` rows still read. | their parallel branches |
| `viewer/app.js`, `field_help.js`, `style.css` | `context` help; parallel styles keyed on a task with jobs. | `tier`/`tools` help |
| `cli.py` | the `task` command help says "a task job". | itself |
| SPEC.md, AUTHORING.md, README.md, CHANGELOG.md, version files | one task block; 1.0.0. | the 0.35.0 docs commit |

## 4. Steps (each one red-green cycle, then commit)

1. Model, schema, and loader: `TaskBlock` with the new fields, the `parallel` refusal. Migrate every test fixture and the example skills from `parallel` to `task` + `context: fresh` in the same commit (the loader tests fail otherwise). Migrate this run's copies.
2. Validator: the `main` context rule, the `context` value check, and today's tier, tools, `when`, and agent checks on tasks.
3. Run records and engine: `TaskJob`, `start_jobs` for every task, `job_context`, the flat output of a one-job task, `results` with `for_each`; `SCHEMA_VERSION` 8.
4. Engine and packets: the mixed packet (fresh jobs spawned, then main jobs one by one), submit replies by job context, `--task` optional on a one-job main task, the wait line.
5. Generic adapter: every job main, tier and tools ignored.
6. Old runs: `skill_by_id` refusal for a `parallel` run copy; viewer shows the old run with no canvas.
7. Viewer data, skill view, export, editor, agent view: one path for a task with jobs; old `parallel` rows still read.
8. `sync` profile agents and Galtea facts from fresh task jobs and tasks with a tier.
9. Example skills: `finish` and `judge` in a fresh context with `tier: standard` and `tools: read`.
10. Docs: SPEC.md (6 with five types, 6.1 holds the old 6.3, 7, 8, 9.3, 10.3, 10.4, 11, 12, 13.1, 13.3, 14, 15, 18 with a `parallel` row), AUTHORING.md and its tested example, README.md, CHANGELOG.md 1.0.0 (with "finish or cancel runs before updating"), version 1.0.0.

## 5. Checks

Tests to add (each in the test file of its module):
- Loader: `type: parallel` gives exactly the one line; a task takes every new field.
- Validator: `tier`, `tools`, `agent` on a task with no `context` or `context: main` are errors that name the block; a written unknown `context` is an error; a computed `context` passes.
- Engine: a one-job fresh task stores its output flat; `for_each` with only main jobs runs them one by one and stores `results`; a mixed block spawns the fresh jobs first, then gives the main jobs, and joins in item order; a computed context per item; an unknown computed context stops the run; generic runs every job main; `--task` optional on a one-job main task; replies per job context; a run copy with `parallel` refuses with the line and can still be cancelled.
- Packets: the "Subagent tasks" heading, the "do task n yourself" section, no wait line while a main job is open.
- Viewer data: a task with `for_each` draws as today's parallel; an old trace with `parallel` rows still gives its timeline.
- Galtea: tier facts for a task with a tier.
- Example skills: `pskill validate` and `pskill test` pass; `tests/test_authoring_example.py` passes.

Local checks before each push: `uv run ruff format --check . && uv run ruff check . && uv run mypy && uv run pytest --cov && uv run pskill.py validate && uv run pskill.py test`.

CI proves the same checks on Windows, macOS, and Linux.

## 6. Out of scope

- A wait block for long background work (its own issue).
- Migrating Galtea-AI/monorepo (Galtea-AI/monorepo#7545, after the release).
- Moving `resolve-pr-feedback` `resolve_item`, `write_description`, `review-pr` `triage`/`draft`, and `fix-ci` `fix_ci` to a fresh context: each needs its instruction reworked to stand alone.
- A reading mode for old run copies with `parallel`.
