# pskill

**Run agent skills as programs, not as long text.** A normal skill is a text file that asks your coding agent (Claude Code, Codex, and others) to follow some steps. A pskill skill is a map of steps, and a small program (the **runner**) gives the agent one step at a time. The agent cannot skip a step or change the order.

![The implement-issue skill in the pskill viewer: its steps as a graph, and the details of one step](docs/viewer-implement-issue.png)

*The example skill `implement-issue` in the viewer. Each box is one step, and the arrows show where each step can go next.*

## Open the viewer, with no install

**<https://guplem.github.io/pskill/>**

Open it in Chrome or Edge. On the Folders tab, pick your project folder, or a folder of clones and worktrees. You then see every run and every skill in them. Your files stay on your computer: the page reads them in the browser.

## Why

Agents often skip a step of a long skill, forget a value, or jump ahead. With pskill, the runner keeps the order and the values. The agent only does the current step.

## How it works

1. You ask your agent for a task, for example "implement issue 42".
2. The agent starts the matching skill. One use of a skill is a **run**.
3. The runner gives the agent one step. The agent does it and sends back its answer.
4. The runner checks the answer and gives the next step. If the answer is incomplete, the agent must fix it.
5. This repeats until the skill ends. When a step needs your decision, the agent asks you.

## Requirements

- [uv](https://docs.astral.sh/uv/), a small tool that installs everything else (Python included).
- git. The example skills also use the [GitHub CLI](https://cli.github.com/) (`gh`).

## Install

In the main folder of your project, run:

```bash
uv run https://raw.githubusercontent.com/guplem/pskill/main/pskill.py init
```

This creates a small `.pskill/` folder. Commit it to git. Its file `pskill.py` names the pskill version. The first time someone runs it, it downloads that version once, so your teammates install nothing.

To move to the newest version later (this changes one line in `.pskill/pskill.py`):

```bash
uv run .pskill/pskill.py update
```

## What pskill adds to your project

- **One small file per skill** (`SKILL.md` in `.claude/skills/` and `.agents/skills/`). Your agent finds the skill through it. It holds the skill's goal and tells the agent how to use the runner.
- **Two hooks** (commands that your agent app runs by itself):
  - When the agent tries to stop while a step is still open, the hook tells it to continue. After 3 tries, it lets the agent stop and pauses the run.
  - When you open a session, the hook updates the small skill files.
- **One permission rule**, so your agent app does not ask you each time the agent talks to the runner. It allows only `uv run .pskill/pskill.py ...`.

Claude Code and Codex use the hooks only after you trust the project folder. Codex also asks you once to approve each hook (type `/hooks`). If your project builds its settings files with its own script, set `hook_files` in `.pskill/config.yaml`.

## Use

Ask your agent for the task. The skill starts by itself. Answer its questions.

You can also use the runner yourself. Each command starts with `uv run .pskill/pskill.py`:

| Command | What it does |
|---|---|
| `list` | List the skills. |
| `start <skill> --input name=value` | Start a skill. Add `--mode autonomous` so the agent decides alone, with no questions. |
| `runs --open` | List the unfinished runs. |
| `current <run>` | Show the current step of a run. |
| `task <run> <n>` | Show the full prompt of one parallel task. A subagent runs this first. |
| `pause <run>`, `resume <run>`, `cancel <run>` | Pause, continue, or stop a run. A run survives when you close the session. |
| `delete <run>` | Delete a finished run, for cleanup. |
| `view` | Open the viewer in your browser (below). |
| `validate` | Check the skills for mistakes. |
| `test` | Run the skills' test cases with recorded answers. No AI model runs. |
| `sync` | Update the small skill files, the hooks, and the permission rule. |

**The viewer** shows each skill as a graph of steps, and each run as the path that it took. Click a step to see its details. You can edit skills and agents there, replay a run step by step, cancel a run, and delete finished runs.

**The hosted viewer** shows the same screens without a command, for many projects at once: open <https://guplem.github.io/pskill/> in Chrome or Edge (see [Open the viewer, with no install](#open-the-viewer-with-no-install)), and pick your project folders on the Folders tab. A folder of clones and worktrees works too: the viewer finds each project in it, and names the folder and the branch of every run. Your files stay on your computer.

## The example skills

[`.pskill/skills/`](.pskill/skills/) holds skills for the daily work on a GitHub project. Copy the ones you want into your own `.pskill/skills/` (with the agents in [`.pskill/agents/`](.pskill/agents/)), run `sync`, and adapt them.

| Skill | What it does |
|---|---|
| `implement-issue` | From an issue (or a described change) to a pull request that is ready to merge. It understands the issue, asks you only what the code cannot answer, and shows you a plan. Then it opens a draft pull request and builds the change test-first. Fresh reviewers check it, round after round, until a round finds nothing to fix. Then it marks the pull request ready, gets CI green, answers late comments, and gives each later fix a short review for real problems only. It never merges. |
| `review-pr` | One review of a pull request by five reviewers at once: correctness, tests, completeness, conventions, and docs. Each finding quotes the code line. It posts them when you agree. |
| `resolve-pr-feedback` | Answers each open comment of a pull request, one at a time: it fixes the code or explains why not, and replies. |
| `fix-ci` | Waits for the CI checks of a pull request, and fixes the failures that the pull request causes. |
| `create-issue` | Writes a clear issue with you, after a check for duplicates. It files the issue in the current repository, or in the one that you name. |

### Recommended setup for the example skills

The skills read your project's rules from its own files, so they work in most repositories as they are. These settings make them work best:

- **Run CI only on ready pull requests.** `implement-issue` pushes many commits to a draft, and marks it ready at the end. In each pull request workflow, start the checks on `ready_for_review` too, skip drafts, and let a new push cancel the older run:
  ```yaml
  on:
    pull_request:
      types: [opened, synchronize, reopened, ready_for_review]
  concurrency:
    group: checks-${{ github.ref }}
    cancel-in-progress: true
  jobs:
    checks:
      if: github.event_name != 'pull_request' || !github.event.pull_request.draft
  ```
- **Name your fast checks in `AGENTS.md`** (or `CLAUDE.md`, or the README): the lint, type check, and test commands. The skills run them before each push, and leave slow suites to CI.
- **Use the labels:**
  - A label that starts with `waiting-for-` (for example `waiting-for-design`) holds an issue: `implement-issue` does not start on it.
  - `implement-issue` adds `waiting-for-human-review` to a pull request that a person must look at before the merge. It creates the label when it is missing.
  - In autonomous mode, `create-issue` adds `waiting-for-human-check` to an issue that no person has read yet.
- **Protect the default branch:** require the CI checks and one approval. The skills never merge, so a person always does.
- **Record your decisions** in `adr/` or `docs/adr/` (one file per decision). The skills check a change against them.
- **Work in a clean checkout.** The skills stop when the checkout has uncommitted changes, because those changes are yours. They expect the GitHub remote to be named `origin`.
- **Add your own reviewers.** Each reviewer is one row in the `review` block of `review-pr`, with an optional `when`, for example a database reviewer when the change touches your migrations.

This repository follows the same setup, with two differences: it requires no approval (it has one maintainer), and its decisions live in `SPEC.md` section 3, which `AGENTS.md` names.

## Write a skill

Read [`AUTHORING.md`](AUTHORING.md), or run `uv run .pskill/pskill.py authoring`. The example skills are working examples of every feature.

## Which agent apps work

| Agent app | What works |
|---|---|
| Claude Code | Everything. |
| Codex | Everything, with "Full access" (see below). |
| Others (Gemini CLI, Cursor, ...) | The basics. There are no hooks, so the agent can stop halfway. Parallel tasks run one after another, so each task sees the earlier ones. |

## Know before you use it

- **Autonomous mode asks you nothing.** The agent also takes decisions that normally need you, like "close this issue". Only your agent app's permission settings protect you then.
- **Codex needs "Full access".** Its sandbox (the area that limits what commands can do) stops the runner from sending answers. Choose "Full access" in Codex's permissions menu, or start it with `codex --sandbox danger-full-access`. This turns off the sandbox for every command, not only for pskill.
- **One session per folder, in apps other than Claude Code and Codex.** There, two sessions in the same folder share the hooks.
- **pskill trusts the agent** when it says that you answered a question.
- **The steps are plain files.** The agent could read the later steps. This is not a security barrier.

## Problems

- **The skill does not start:** run `uv run .pskill/pskill.py sync`, then open a new session.
- **You lost a run:** run `runs --open`, then `current <run>`.
- **A run is paused:** the message says why. Fix the cause, then run `resume <run>`.
- **`update` refuses to run:** someone edited a runner file by hand. Undo it, or run `update --force`.

## Develop pskill

See [`AGENTS.md`](AGENTS.md) and the full design in [`SPEC.md`](SPEC.md).

## License

MIT. See [`LICENSE`](LICENSE).
