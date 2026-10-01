# pskill

**Run agent skills as programs, not as long prose.** A normal skill is a text file that asks the agent (Claude Code, Codex, and others) to follow steps. A pskill skill is a small map of steps in YAML, and a program (the pskill runner) walks the agent through it: one step at a time, in a fixed order. The agent cannot skip or reorder steps, and every run leaves a record that you can replay step by step.

```text
you  <->  your agent (Claude Code, Codex, ...)  <->  pskill runner  <->  the skill (.pskill/skills/<skill>/skill.yaml)
```

## Why

Long prose skills break in the same ways again and again: the agent skips a step, forgets a value between steps, or jumps ahead. With pskill, the runner keeps the order and the values. The agent only does the work of the current step.

## How a run works

1. You ask your agent for a task in plain words, for example "implement issue 42".
2. The agent recognizes the skill and starts a **run** (one use of a skill).
3. The runner gives the agent **one step**: what to do, and what to answer.
4. The agent does the work, then sends its answer back to the runner.
5. The runner checks the answer. If it is incomplete, the agent must fix it. If it is good, the runner gives the next step.
6. This repeats until the skill ends. When a step needs your decision, the agent asks you.

## Requirements

- [uv](https://docs.astral.sh/uv/), a small Python tool. It installs everything else that pskill needs, Python included.
- git. The example skills also need the [GitHub CLI](https://cli.github.com/) (`gh`).
- Windows, macOS, or Linux.

## Install

In the root folder of your project, run:

```bash
uv run https://raw.githubusercontent.com/guplem/pskill/main/pskill.py init
```

This creates a `.pskill/` folder with a copy of the runner inside. Commit that folder to git, so everyone on your team uses the same version with no extra install. (git already ignores `.pskill/runs/`, where your run records go.) Do not edit the runner files in `.pskill/` by hand.

To get a newer version of the runner later:

```bash
uv run .pskill/pskill.py update
```

## What pskill adds to your project

`init` runs `pskill sync`, and you run it again after you add a skill or change its description. `sync` only adds or updates its own files and entries. It never overwrites a file that you wrote.

- **A small "signpost" file per skill** (`.claude/skills/<skill>/SKILL.md` and `.agents/skills/<skill>/SKILL.md`). Agents discover skills through these files. Each one tells the agent to start the runner. The real skill stays in `.pskill/skills/`.
- **Two hooks** (small commands that your agent app runs by itself at certain moments):
  - **When the agent tries to finish its reply:** if a step of a run that this session started is still open, the hook sends the agent a message: "a pskill step is still open, continue it". So the agent keeps working instead of stopping halfway. If the agent still tries to stop 3 times in a row without sending an answer, pskill lets it stop and pauses the run. You can continue that run later.
  - **When you open a new session:** the hook lists your unfinished runs, so the agent can continue them.
- **A permission rule**, so your agent app does not ask your permission every time the agent talks to the runner. It allows only the runner command (`uv run .pskill/pskill.py ...`), nothing else.

Where these go: `.claude/settings.json` for Claude Code; `.codex/hooks.json` and `.codex/rules/pskill.rules` for Codex. If your project generates these files from its own source (a script that rebuilds them), list that source in `hook_files` in `.pskill/config.yaml`. Then `sync` writes the two hooks there, and your script copies them into the app files. Both apps use them only after you trust the project folder. Claude Code asks you the first time that you open the folder. Codex also asks you once to approve each hook (type `/hooks` in Codex).

`init` also adds one line to `.gitattributes` (the git file that sets rules per path): `.pskill/** text eol=lf`. This line keeps the files in `.pskill/` at LF line endings (the Unix style) on every OS. So the file hashes that pskill records stay the same, and `update` does not think that you edited the runner. The line matters only when you commit `.pskill/`. If you do not commit `.pskill/`, you can remove the line.

## Use

Usually, you just ask your agent for the task, and the skill starts by itself. You answer the questions that the skill asks.

You can also run the runner yourself. Every command starts with `uv run .pskill/pskill.py`:

| Command | What it does |
|---|---|
| `list` | List the skills. |
| `runs --open` | List the unfinished runs. |
| `current <run>` | Show the current step of a run again. |
| `pause <run>`, `resume <run>`, `cancel <run>` | Pause a run, continue it, or stop it for good. A run survives when you close your session: you can continue it tomorrow, even in another agent app. |
| `view` | Open the viewer in your browser. The Skills screen shows each skill's graph, also for a skill that never ran: click a block to see its instruction, its fields, and where it can go. Each field has a "?" button: hover it for a short explanation, or click it for the details and examples. "Export as Markdown" downloads the skill as a plain `SKILL.md` (with its scripts and child skills) for a project without pskill. "Edit" lets you change blocks and edges, add and delete blocks, and save to `skill.yaml`: only the changed block changes, and its comments stay. The Agents screen shows each agent in `.pskill/agents/` as Markdown, with the skills that use it, and "Edit" changes its text. A skill or agent name in a block's panel is a link to its screen. Each run is a graph of its skill with the path it took. Click a step to see its input and its output, or a subagent's task to see what it answered, and drag the replay bar to see the run as it was at any step. You can also double-click `.pskill/launchers/view.cmd` (Windows), `view.command` (macOS), or `view.sh` (Linux). |
| `validate` | Check every skill for mistakes. |
| `test` | Run every skill's test cases. A fake agent gives recorded answers, so no AI model runs and it costs nothing. |
| `sync` | Update the signpost files, the hooks, and the permission rule. `sync --check` only reports what is out of date. |

To start a skill yourself: `uv run .pskill/pskill.py start <skill> --input name=value`. Add `--mode autonomous` to let the agent answer the skill's questions itself, without you.

## Write a skill

Read [`AUTHORING.md`](AUTHORING.md): the six kinds of steps, a complete example, and how to test a skill. The skills in [`.pskill/skills/`](.pskill/skills/) are working examples.

## Which agent apps work

| Agent app | What works |
|---|---|
| Claude Code | Everything: signpost files, hooks, the permission rule, questions with its question buttons, and parallel helper agents (subagents). |
| Codex | Everything, with Full access (see the known limitations): signpost files, hooks, the permission rule, and parallel helper agents. It asks its questions in the chat. |
| Any other (Gemini CLI, Cursor, ...) | The basics: signpost files in `.agents/skills/`, and questions in the chat. There are no hooks, so nothing stops the agent from ending its reply early, and no session lists your unfinished runs (use `runs --open`). Parallel tasks run one after another. |

## Known limitations

- **Autonomous mode means no questions to you.** With `--mode autonomous`, the agent also makes the decisions that normally need you, such as "post this publicly" or "close this issue". Only your agent app's own permission settings then protect you.
- **pskill trusts the agent when it says that you answered a question.**
- **Without hooks, the agent can stop halfway.** Find the run with `runs --open`, then continue it with `current <run>`.
- **In other agent apps, two sessions in the same folder share the hooks.** Claude Code and Codex tell pskill which session runs a skill, so the hook holds only that session. Other apps do not: keep one session per folder there.
- **The agent could read the later steps of a skill.** They are plain files on disk. This does not matter for normal use, but it is not a security barrier.
- **Without helper agents, parallel tasks share one context.** In apps without subagents, the agent does the tasks one after another, so each task can see the earlier ones.
- **Codex needs Full access.** Codex's sandbox (the safety area that limits what commands can do) stops the runner from sending answers, because the runner needs files outside your project and the internet. Choose "Full access" in Codex's permissions menu, or start Codex with `codex --sandbox danger-full-access`. Full access turns off the sandbox for every command of the agent, not only for pskill. If you keep the sandbox, Codex asks you to approve each answer.

## Troubleshooting

- **The skill does not start:** run `uv run .pskill/pskill.py sync`, then open a new session.
- **You lost track of a run:** run `uv run .pskill/pskill.py runs --open`, then `current <run>`.
- **A run is paused:** the pause message says why. Fix the cause, then run `resume <run>`.
- **`update` refuses to run:** someone changed a runner file in `.pskill/` by hand. Undo that change, or run `update --force` to overwrite it.

## Develop pskill

See [`AGENTS.md`](AGENTS.md) for the repository map, the commands, and the rules. The full design is in [`SPEC.md`](SPEC.md).

## License

MIT. See [`LICENSE`](LICENSE).
