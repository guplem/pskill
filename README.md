# pskill

**Run agent skills as programs, not prose.** A pskill skill is a small graph of typed blocks in YAML. The pskill runner executes it one block at a time inside your normal agent session (Claude Code, Codex, and others): it gives the agent one instruction, checks the typed answer, and picks the next block. The agent cannot skip, reorder, or invent steps, and every run leaves a trace that you can step through.

```text
you <-> agent (Claude Code, Codex, ...) <-> pskill runner <-> .pskill/skills/<skill>/skill.yaml
```

## Why

Long prose skills break in the same ways again and again: the agent skips a step, loses state between tool calls, or runs ahead. pskill moves the order into a graph that a program enforces, and leaves only each step's judgment to the agent.

## Requirements

- [uv](https://docs.astral.sh/uv/) on your machine. It installs Python and the runner's three dependencies by itself.
- git and, for the example skills, the [GitHub CLI](https://cli.github.com/) (`gh`).
- Windows, macOS, or Linux.

## Install

In the root folder of your project, run:

```bash
uv run https://raw.githubusercontent.com/guplem/pskill/main/pskill.py init
```

`init` copies the runner into `.pskill/` (commit that folder; git ignores `.pskill/runs/`), then runs `sync`. The runner is vendored: every teammate uses the same version, with no install step. Never edit the vendored files by hand; `update` replaces them.

To update later:

```bash
uv run .pskill/pskill.py update
```

## What `sync` writes

`sync` makes your skills visible to each harness. It changes only its own entries, and never overwrites a hand-written file:

| File | What pskill adds |
|---|---|
| `.claude/skills/<skill>/SKILL.md`, `.agents/skills/<skill>/SKILL.md` | One short generated stub per skill, so the agent can start it. Set the folders with `stub_folders` in `.pskill/config.yaml`. |
| `.claude/settings.json` | A Stop hook, a SessionStart hook, and the permission rule `Bash(uv run .pskill/pskill.py *)`. |
| `.codex/hooks.json`, `.codex/rules/pskill.rules` | The same two hooks for Codex, and a rule that allows `uv run .pskill/pskill.py` without a prompt. |

- **Stop hook:** while a run has an open block, it keeps the agent working (at most 3 times in a row, then the run pauses).
- **SessionStart hook:** it refreshes the stubs and lists your unfinished runs.
- **Codex:** it loads project hooks and rules only after you trust the project, and it asks you once to trust each hook (`/hooks`).

Run `sync` again after you add a skill or change a skill's description or inputs.

## Use

Ask your agent for the task in plain words ("implement issue 42"). The stub triggers the skill, and the agent follows the runner's packets until the run ends. You answer the questions the skill asks.

| Command (`uv run .pskill/pskill.py ...`) | What it does |
|---|---|
| `list` | List the skills. |
| `start <skill> --input name=value` | Start a run. Add `--mode autonomous` to let the agent answer the skill's questions itself. |
| `current [<run>]` | Show the current block of a run again. |
| `runs --open` | List the unfinished runs. |
| `pause`, `resume`, `cancel <run>` | Control a run. A run survives the session: resume it tomorrow, in any harness. |
| `view` | Open the read-only run viewer in your browser (or double-click `.pskill/launchers/view.cmd`, `view.command`, or `view.sh`). |
| `validate` | Check every skill for errors and warnings. |
| `test` | Run every skill's test cases with a scripted fake agent. No LLM, no cost. |
| `sync` | Write the stubs, hooks, and rules (`--check` only reports). |

## Write a skill

Read [`AUTHORING.md`](AUTHORING.md): the six block types, a complete example, and the edit loop (write a failing test case, change the skill, then run `test`, `validate`, and `sync`). This repository's own skills are working examples: [`.pskill/skills/`](.pskill/skills/).

## Harnesses

| Harness | Support |
|---|---|
| Claude Code | Full: stubs, hooks, the permission rule, questions with its question tool, parallel subagents. |
| Codex | Full: stubs, hooks, the command rule, parallel subagents. |
| Any other (Gemini CLI, Cursor, ...) | The `generic` adapter: stubs in `.agents/skills/`, questions in the chat, parallel tasks one by one, no hooks. |

## Known limitations

- **Autonomous mode removes the human gates.** In `--mode autonomous` the agent takes every human decision itself, including "post publicly" or "close the issue". Only your harness's permission settings then protect outward actions.
- **The runner trusts the agent's claim that you answered a question.**
- **Without a Stop hook, enforcement is soft.** The agent can end its turn with an open block; `current` and the session-start message recover the run.
- **The Stop hook binds to the harness and the checkout.** Two sessions of the same harness in the same folder share it. Separate checkouts do not conflict.
- **The skill files are on disk.** An agent could read future blocks. This is not a security boundary.
- **No isolation without subagents.** With the generic adapter, parallel tasks run one by one in the main agent's context.
- **Codex runs allowed commands outside its sandbox.** The rule that lets the agent call the runner without a prompt also runs the runner, and so the skills' `script` blocks, outside the Codex sandbox. Delete `.codex/rules/pskill.rules` to keep the sandbox; Codex then asks once per block.

## Troubleshooting

- **The skill does not trigger:** run `uv run .pskill/pskill.py sync`, then check that the stub exists in the folder your harness reads.
- **A run seems lost:** run `uv run .pskill/pskill.py runs --open`, then `current <run>`.
- **A run is paused:** the pause message names the reason. Fix it, then run `resume <run>`.
- **`update` refuses to run:** someone edited a vendored file by hand. Move the change upstream, or run `update --force`.

## Develop pskill

See [`AGENTS.md`](AGENTS.md) for the repository map, the commands, and the rules (red-green, always). The design is in [`SPEC.md`](SPEC.md).

## License

MIT. See [`LICENSE`](LICENSE).
