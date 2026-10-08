# pskill: portable programmatic skills (implementation specification)

> Audience: a coding agent that implements this system from zero.
> Status: design approved, not implemented. Date: 2026-09-27.
> Name: `pskill`. Repository: `github.com/guplem/pskill` (the user's personal account). Public, MIT license (`LICENSE` file at the repository root).

## 0. Read this first

**What pskill is.** A small runner that executes agent skills written as a graph of typed blocks instead of prose. The agent (Claude Code, Codex CLI, Gemini CLI, Cursor) stays in the user's live session. The agent asks the runner for the current block, does the work, and submits a typed result. The runner validates the result, stores it, picks the next block, and prints the next instruction. The agent never sees the full workflow.

**What pskill is not.**
- It is not an agent framework. It never calls an LLM.
- It does not replace prose skills. Reference and rules skills (for example `write-commit`) stay normal `SKILL.md` files. Port only workflow skills.
- It is not a harness. The harness provides the agent, its tools, its permissions, and its subagents.

**Why it exists.** Evidence from the user's real skills:
- **Order enforced by prose.** `implement-issue` (Galtea monorepo, 919 lines) has 52 "never" and 21 "MUST". `review-pr-bot` admits that one rule "depends on you honouring an instruction, not on a mechanism".
- **Run-away helpers.** `generate-changelog` records helpers that "ran the whole skill and overwrote the output files".
- **Lost state.** Skills tell the agent to write values to files because shell variables do not survive tool calls.
- **Brittle links.** `review-pr-bot` cites `review-pr` by line number. `implement-issue` depends on the exact headings of `.reviews/<PR>-review.md`. Nothing checks these links.
- **Mode explosion.** `--auto`, `--no-verdict`, `--preapproved`, each with prose like "never call AskUserQuestion in autonomous mode".
- **Manual resume.** "Run `/implement-issue <ISSUE>` to continue".
- **No way to observe, test, or compare a skill run.**

## 1. Core principles

These rules decide every open question. When a feature conflicts with them, drop the feature.

1. **Simplicity first.** Few block types, few keywords, and one way to do each thing. A skill file must be readable by a person who has never seen pskill. A feature that adds much complexity for little user value stays out. Section 18 lists the features that were removed on purpose. Do not add them back.
2. **The runner owns the order. The agent owns the judgment.** The agent cannot skip, reorder, or invent blocks. At a branch, the agent picks from a fixed list of choices.
3. **Test first (red-green).** Write a failing test for every behavior before the code. See section 16.
4. **Portable by default.** The runner works on Windows, macOS, and Linux, and with any harness that can run a shell command and write a file. Harness-specific features only make things stronger or nicer. They are never required.

## 2. Vocabulary (one meaning per word)

| Term | Meaning |
|---|---|
| **harness** | The host program that runs the agent: Claude Code, Codex CLI, Gemini CLI, Cursor. |
| **agent** | The LLM inside the harness, in the user's live session. |
| **runner** | The program that executes skills: the entry script `pskill.py` plus the package `pskill_runner/` next to it. |
| **skill** | A folder `.pskill/skills/<skill-id>/` with `skill.yaml`, instruction files, and optional scripts and tests. |
| **block** | One node of a skill graph. It has one type from the list in section 6. |
| **edge** | The link from a block to the next block, with an optional condition. |
| **run** | One execution of a skill, stored in `.pskill/runs/<run-id>/`. Nested skill calls stay inside the same run. |
| **packet** | The text that the runner prints for the agent: the instruction and how to submit the result. |
| **submission** | The YAML result that the agent gives back for a block, in the same command that asks for the next block. |
| **trace** | The append-only event file `events.jsonl` of a run. |
| **adapter** | The harness-specific code in the runner: stub folder, hooks, packet wording. |
| **stub** | A generated, read-only `SKILL.md` that makes a skill visible to a harness. |
| **mode** | `interactive` or `autonomous`. A run parameter. |

## 3. Decisions (do not re-open)

| # | Decision | Reason |
|---|---|---|
| D1 | The agent pulls blocks from the runner inside the live session. The runner does not launch agents. | The user keeps the live chat. A headless `eval` command can come later, from the same files. |
| D2 | The runner owns the graph. The agent picks choices from fixed lists. | Order becomes a mechanism. |
| D3 | The skill format is new and is the only source of truth. | A clean format. D4 restores discovery. |
| D4 | `pskill sync` writes one read-only stub per skill into each folder in `config.stub_folders` (default `.agents/skills/` and `.claude/skills/`). All stubs have the same content and pass `--harness auto`. | Harnesses pick skills by their description. Without stubs, auto-triggering stops. The folder list is configurable because projects already own these folders differently (see 9.3). |
| D5 | One run can mix main-agent work, parallel subagents, scripts, and questions to the human. | The real skills use all four. |
| D6 | Every skill can run in `autonomous` mode. A `decision` block has `decider: agent` or `decider: human`. In autonomous mode the agent takes human decisions itself, from the skill goal, the session, and the project. | User requirement. Replaces all mode-specific prose. |
| D7 | A Stop hook blocks the agent from ending its turn while a block is open, on harnesses that have such a hook. Other harnesses get packet wording only. | Otherwise the agent can simply stop calling the runner. |
| D8 | The stub gives the skill goal and the loop rules once. A packet contains the current instruction and its return format, and no future blocks. It repeats the goal only where the agent never saw the stub: a subagent task, the first packet of a child skill, and `current` or `resume` (with the rules). | Fewer tokens, no running ahead, one obvious place for the goal, and enough context for autonomous answers. Changed in 0.10.0: before, every packet repeated the goal and the rules. |
| D9 | Every agent block declares a typed output. The runner rejects invalid submissions with the error text. | State lives in the runner, typed, and survives tool calls. |
| D10 | A nested skill call works like a function: inputs in, outputs out, no access to the caller's state. | Replaces line-number citations and file-heading contracts. |
| D11 | Visit caps are optional. The validator warns about a loop with no cap. | User choice. |
| D12 | When a block fails, the runner retries it, then pauses the run with a report. | Recoverable by default. |
| D13 | A run survives the session. Any session in any harness in the same checkout can resume it. | State is in files, not in the chat. |
| D14 | "Replay" means visual step-through of past runs in the viewer. | User scope. |
| D15 | No up-front checks for required tools. A missing tool fails its block, and D12 applies. | User choice. |
| D16 | Transport is the CLI: `uv run .pskill/pskill.py <command>`. **One tool call per block:** the agent pipes its answer into `submit` through a literal block on stdin (a bash heredoc, or a PowerShell here-string), and the same call prints the next packet. The answer is YAML (JSON also works, because JSON is valid YAML). **A long answer goes in a file:** for an answer over about 5 KB, the agent writes it to the file that the packet names and runs `submit --file <path>`. Changed in 0.31.0 (#132): before, stdin was the only way. | Every harness can run a shell command. One call per block saves usage. A literal stdin block needs no escaping in any shell. YAML takes multi-line text (plans, comments) with no `\n` escapes. The file form exists because Claude Code's Bash tool on Windows breaks long heredocs: a command over about 7.3 KB with an apostrophe in the body fails before the runner starts (`unexpected EOF while looking for matching '`). It failed 56 of 64 times in one user's transcripts, and 12 pskill submits hit it. The same text runs in plain bash, so the cause is the tool, which pskill cannot fix. |
| D17 | For a `parallel` block, the harness spawns the subagents. The runner only says what to spawn. Without subagent support, the agent runs the tasks one by one. | Same harness, same permissions. Works everywhere. |
| D18 | The trace records the packet text given to the agent, the submission returned, and durations. | Enough for step-through, simple analytics, and later comparison. |
| D19 | `skill.yaml` holds the graph. An `instruction` (or `report`) is either a path that ends in `.md` or the text itself. Long prose goes in `instructions/<block-id>.md`; one or two lines can stay inline. | Readable large skills, small diffs, and no tiny files for one-line steps. |
| D20 | A project commits only the entry script `.pskill/pskill.py`. Its pin (version, release URL, sha256) names one release archive. The first call on a computer downloads that archive once into a cache for the user, checks the sha256, and unpacks it; later calls run the cached copy with no network. `pskill update` moves the pin. Changed in 0.22.0: before, every project vendored the whole runner. | Version pinned per project, no install step for teammates, and no runner code in the project's diffs and searches. Always running the latest release instead would change the runner mid-run, give teammates on the same commit different versions, and need the network on every call. |
| D21 | The entry script has a PEP 723 header. `uv run` installs Python and the four dependencies. The entry script puts the runner folder (the cached release, or the checkout next to it) on the import path, so `pskill_runner/` needs no install step. | Python has no built-in YAML parser. `uv` is the only machine requirement. |
| D22 | A run copies the skills and pskill agents that it uses into the run folder at start and always resumes from that copy. | The simplest correct behavior when a skill changes mid-run. |
| D23 | Everything lives in `.pskill/`. Runs live in `.pskill/runs/`, which git ignores. | User choice. |
| D24 | The MVP viewer is read-only. The skill editor came after the MVP (issue #3, section 14.2). | The editor is the most expensive part. |
| D25 | MVP adapters: `claude-code` (the reference), `codex`, and `generic`. `generic` makes every skill run in any other harness (Gemini CLI, Cursor, and others) with soft enforcement and one-by-one parallel tasks. Dedicated Gemini and Cursor adapters come after the MVP, and only when a gap hurts. | Each adapter adds harness facts that need checking and upkeep. `generic` already covers the rest. |
| D26 | Example skills: `implement-issue` (one pull request, built red-green, then reviewed and resolved round after round until CI is green), `review-pr` (a deep review that posts one GitHub review), `resolve-pr-feedback`, `fix-ci`, `create-issue`, and the internal `checkout-pr`, `review-round`, `review-head-check`, and `review-doubt` (section 13). They are a base that most software projects on GitHub can copy, so they read the project's rules from its own files and hard-code no project detail. Together they must exercise every feature (section 13.3). Changed after 0.23.1: before, three proof skills ported from the setup-guplem-standard templates. Changed after 0.32.0: before, `review-pr` was one round that posted loose comments. | Real runs of the first version showed what a useful base needs: a plan in a draft pull request, separate find and fix steps, replies to comments, and a CI wait. Stacked pull requests and worktree subagents can come later. |
| D27 | `pskill test` runs skill tests with a scripted fake agent. | Test graph paths with no LLM, no cost, in CI. |
| D28 | `pskill sync` adds one narrow allow rule to each harness's project settings: the runner command. | Without it, the user gets a permission prompt on every block. Every other agent action still asks as usual. |

### 3.1 Known limitations (accepted)

- **L1. Autonomous mode removes human gates.** In autonomous mode the agent takes every human decision, including "post publicly" or "close the issue". Then only the harness permission system protects outward actions. Say this clearly in the README.
- **L2. The runner trusts the agent's claim that a human answered.**
- **L3. Enforcement is soft without a Stop hook.** `pskill runs --open` and `pskill current` recover a run that the agent left.
- **L4. The Stop hook binds by harness, checkout, and session.** A run holds only the session that owns it, so two sessions in the same folder do not conflict. A harness that gives no session id (`generic`), and a run from before 0.9.0, hold every session of the harness in the checkout.
- **L5. Instruction files are on disk.** The agent could read future blocks. This is not a security boundary.
- **L7. Codex needs Full access.** Inside the Codex sandbox, `uv` cannot open its cache (outside the project) or reach PyPI. The Codex rule lets only plain runner commands, such as `start` and `current`, run outside the sandbox: Codex does not match the rule to the `submit` form with an answer on stdin (verified in #24). So the user runs Codex with Full access (`--sandbox danger-full-access`), or approves each `submit`. pskill never changes this setting. Full access also means that the runner's `script` blocks run without the sandbox.
- **L6. No isolation without subagents.** With the `generic` adapter, parallel tasks run one by one in the main agent's context, so each task can see the earlier ones.

### 3.2 Items to verify at implementation time

Harness features change fast. Every statement tagged **VERIFY** comes from research on 2026-09-26. Check it against the current official docs before you code it. Record the doc URL in a code comment.

---

## 4. Architecture

```text
 user <-> harness (Claude Code | Codex | Gemini CLI | Cursor | any other)
              |  agent reads a stub: .claude/skills/<id>/SKILL.md or .agents/skills/<id>/SKILL.md
              |  agent runs:  uv run .pskill/pskill.py start | current | submit ...
              |  hooks run:   uv run .pskill/pskill.py hook stop|session-start --harness <h>
              v
        pskill.py + pskill_runner/ (the runner)
          ├─ loader + validator   .pskill/skills/<id>/skill.yaml
          ├─ engine               executes blocks, keeps a call stack for nested skills
          ├─ run store            .pskill/runs/<run-id>/
          ├─ adapters             claude-code, codex, generic
          ├─ sync                 stubs + hooks
          ├─ test runner          scripted fake agent
          └─ viewer server        127.0.0.1, serves .pskill/viewer/ + a JSON API
```

**The loop for one agent block:**
1. The runner prints a packet.
2. The agent does the work with its own tools.
3. The agent runs `submit` once, with its answer on stdin (a long answer: in the file that the packet names, with `--file`).
4. The runner validates the answer. If it is invalid, the runner prints the same packet with the errors.
5. If it is valid, the runner stores it, records the duration, follows the edge, executes every following `script`, `call`, and `end` block by itself, and stops at the next agent block.
6. The runner prints the next packet, as the output of the same command.

---

## 5. Skill format (`skill.yaml`, schema `pskill/v1`)

### 5.1 Top level

```yaml
schema: pskill/v1               # required
id: implement-issue             # required. Lowercase letters, digits, hyphens. Equals the folder name.
description: >-                 # required, max 1024 chars. Goes into the stubs for discovery.
  Implement a GitHub issue end to end. Use when the user asks to implement or fix an issue.
goal: >-                        # required. Goes into the stub, and into packets only where D8 says.
  Resolve the issue with a reviewed pull request that follows the plan the user approved.
invocation: auto                # auto (default) | manual | internal
inputs: {}                      # field map (5.3)
outputs: {}                     # field map
entry: read_issue               # first block. Same forms as `next` (5.4), except the choice map.
blocks: {}                      # map: block id -> block
```

- Block ids use lowercase letters, digits, and underscores.
- Load `skill.yaml` with a PyYAML `SafeLoader` subclass in which only `true` and `false` are booleans (the YAML 1.2 rule). `yes`, `no`, `on`, and `off` stay text, so a choice named `no` works.
- Top-level keys that start with `x-` are free. Use them for YAML anchors (reusable pieces, see 13.2).
- `invocation`:
  - `auto`: the agent may start the skill from its description.
  - `manual`: only the user starts it by name. Claude gets `disable-model-invocation: true`; Codex gets an `agents/openai.yaml` sidecar (VERIFY).
  - `internal`: no stub. Only a `call` block can start it, and any number of skills may call it. `pskill start` refuses it; `pskill test` still replays its cases. The viewer lists it in its own "Internal skills" section.

### 5.2 Instructions

- Every agent block has an `instruction`. The same rule applies to `report` on `end` blocks:
  - A value that ends in `.md` is a path, relative to the skill folder. Name the file `instructions/<block-id>.md`.
  - Any other value is the instruction text itself.
- Both forms are Markdown and may use `{{ }}` (section 7.1).
- Use a file for anything longer than about two lines. Keep one-line steps inline:
  ```yaml
  ask_user:
    type: decision
    decider: human
    instruction: "Ask the user this question: {{ steps.create_plan.question }}"
    next: create_plan
  ```
- An instruction describes only that block's job. Do not repeat the return format; the packet adds it. Do not write rules about order; the graph handles order.
- Inside one block the agent works from prose again. Split a block where agents deviated in real runs (skipped a check, ran ahead). Keep a block whole where the work has no fixed order.

### 5.3 Field maps

A small subset of JSON Schema, written in YAML:

```yaml
pr_number:
  type: integer        # string | integer | number | boolean | array | object
  description: Number of the pull request.   # required on top-level fields (see below)
  optional: true       # default false: the field is required
  default: 0           # inputs only
  enum: [a, b]         # optional
  items: {type: string}        # arrays: required
  properties: {..}             # objects: required, a nested field map
```

The runner checks each answer against the field map directly: the types, `enum`, required fields, and no unknown fields. It does not go through JSON Schema, so every error message can name the field in plain words. (The `jsonschema` package validates only the structure of `skill.yaml` itself.)

- **`description` is required** on every top-level field of `inputs`, `outputs`, and each block `output`. It tells the agent what the data is. The packet shows it next to the field.
- Fields nested inside `items` or `properties` may omit it, so small structures stay short.
- The fields that the runner adds (`choice`, `rationale`, `answer`) have built-in descriptions.

### 5.4 Edges (`next`)

```yaml
next: target                         # 1. always go to target

next:                                # 2. conditions, first match wins; the last item has no `when`
  - when: "{{ steps.create_plan.status == 'question' }}"
    to: ask_user
  - to: approve_plan

next:                                # 3. decision blocks with choices only: one entry per choice
  approve: publish_plan
  change: create_plan

next:                                # 3b. a choice can take an edge list (form 2) instead of one block
  fix:
    - when: "{{ (history.ask_finding | length) < (steps.list_findings.json.findings | length) }}"
      to: ask_finding
    - to: fix_findings
  skip: ask_finding
```

In form 3b the runner first follows the choice, then the first matching edge of that choice's list. This keeps the question buttons in a per-item loop, where the block after a choice depends on how many items are left.

### 5.5 Visit caps

```yaml
max_visits: 3          # optional, on any block
on_max_visits: capped  # optional: an end whose report names the cap
```

A transition into a block that already has `max_visits` visits goes to `on_max_visits` instead. With no `on_max_visits`, the block fails (section 7.4).

---

## 6. Block types (six, closed list)

| Type | Who acts | Purpose |
|---|---|---|
| `task` | agent | Do work and return typed output. |
| `decision` | agent or human | Pick one choice from a list, or answer a question. |
| `parallel` | subagents | One task per list item, run at the same time, joined into one list. |
| `script` | runner | Run a command. No LLM. |
| `call` | runner | Run another skill and get its outputs. |
| `end` | runner | Finish the skill with a status and outputs. |

Every block may have `description:` (a short label for the viewer).

### 6.1 `task`

```yaml
implement:
  type: task
  instruction: instructions/implement.md
  output:
    pr_number: {type: integer, description: "Number of the pull request you opened."}
    pr_url: {type: string, description: "URL of that pull request."}
  next: review
```

### 6.2 `decision`

```yaml
approve_plan:
  type: decision
  decider: human                       # agent | human
  instruction: instructions/approve_plan.md
  choices:                             # optional. Choice id -> meaning. 2 or more.
    approve: Publish the plan and start the implementation.
    change: Revise the plan with the user's feedback.
    stop: Stop without changes.
  output:                              # optional extra fields
    feedback: {type: string, optional: true, description: "What the user wants changed."}
  next: {approve: publish_plan, change: create_plan, stop: stopped}

ask_user:
  type: decision                       # no choices: a free-text question
  decider: human
  instruction: "Ask the user this question: {{ steps.create_plan.question }}"
  next: create_plan
```

- **With choices**, the output always has `choice` and `rationale`, and `next` uses the choice map. Each choice maps to one block, or to an edge list (section 5.4, form 3b).
- **Without choices**, the output always has `answer`, and `next` uses form 1 or 2. `decider: agent` needs choices; otherwise use a `task`.
- **Human decider, interactive mode.** The agent prepares what the instruction says, shows it to the user, asks exactly one question, and waits. It submits the user's answer with `"$answered_by": "human"`.
- **A free-text reply to a decision with choices** (for example the "Other" field of Claude's question tool): the agent maps it to the closest choice and copies the user's words into `rationale`. When no choice fits, the agent asks again.
- **Human decider, autonomous mode.** The agent decides as the user would, from the goal, the session, and the project, and explains it in `rationale`. The trace records `decided_by: agent_autonomous`.

### 6.3 `parallel`

```yaml
research:
  type: parallel
  for_each:                            # a YAML list, or one {{ }} that gives a list
    - {agent: pattern-scout, focus: "Find the closest existing code and its conventions."}
    - {agent: adr-checker, focus: "Find the ADRs that limit this change."}
  agent: "{{ item.agent }}"            # optional: a pskill agent from .pskill/agents/
  task_name: "{{ item.agent }}"        # optional: the name of each task, in the packet and the viewer
  instruction: instructions/research.md   # uses {{ item.focus }}
  output:                              # the output of each task
    report: {type: string, description: "What you found, with file paths."}
  next: create_plan
```

**A dynamic number of subagents.** The list can come from any earlier block, so the count is decided during the run:
- **One subagent per thing** (for example, fact-check every document): a `script` lists the things, and `parallel` runs one task per item.
- **The main agent decides:** a `task` returns the list, with one brief per subagent. The count and each brief are the main agent's choice, within the output schema.

```yaml
list_docs:
  type: script
  run: [uv, run, "{{ skill.dir }}/scripts/list_docs.py", "{{ inputs.folder }}"]
  parse: json                          # prints {"files": ["docs/a.md", "docs/b.md", ...]}
  next: fact_check

fact_check:
  type: parallel
  for_each: "{{ steps.list_docs.json.files }}"
  agent: fact-checker
  instruction: "Check every factual claim in {{ item }} against its cited sources."
  output:
    wrong_claims: {type: array, items: {type: string}, description: "Each wrong claim, with the correct fact."}
  next: report
```

- Each item becomes one task. `item` is the current list element in the templates.
- **A `when` per item.** In a `for_each` written as a YAML list, an item may have a `when` (exactly one `{{ }}`, like an edge's). The item starts a task only when its `when` is true, and the task's `item` has no `when` key. This keeps one way to list tasks: a fixed list, where each subagent says when it is needed. The `block_started` event lists the skipped items (section 10.3), and the viewer shows them. In a list computed during the run, a `when` key is plain data.
- **`agent`** names a file `.pskill/agents/<name>.md`. The file is the subagent's role and rules, in Markdown. The runner puts its text at the top of the task prompt. The harness then spawns a plain subagent, so the same agent works on every harness. With no `agent`, the task gets a plain subagent with only its instruction.
- **`task_name`** is one `{{ }}` value, computed once per item, that names the task. The packet heads the task with `#### Task <n> · <name>`, and the viewer labels the task's node and chip with it. The runner puts the name on one line and cuts it to 60 characters. A name that is missing, empty, or fails to compute is no name: the task shows as `task <n>`, and the run goes on. When the main agent builds the list, give each item an optional `name` field in that block's `output`, and set `task_name: "{{ item.name }}"`.
- pskill agents are only reusable prompt text. pskill never reads harness agent files (`.claude/agents/`, `.codex/agents/`), and `sync` never writes them. The main agent spawns a plain subagent (in Claude: `general-purpose`) and gives it the prompt that the runner built. This keeps agents versioned with the skills, so they cannot drift apart.
- `steps.research.results` is the list of task outputs, in item order.
- Each task has its own submission. The block completes when every task has a valid submission. An empty list completes at once.
- A task is one agent job. It cannot contain other blocks.
- **Isolated contexts.** Each subagent gets only its own prompt: the goal, its rendered instruction, and its return format. It never sees the other tasks or their outputs. The results meet only in the next block, which reads `steps.<id>.results`.
- Without subagent support (the `generic` adapter), the main agent does the tasks one by one in its own context, so the isolation is lost (limitation L6).

### 6.4 `script`

```yaml
read_issue:
  type: script
  run: [gh, issue, view, "{{ inputs.issue }}", --json, "number,title,body,labels"]
  parse: json            # text (default) | json
  next: check_applies

verify_quotes:
  type: script
  run: [uv, run, "{{ skill.dir }}/scripts/verify_quotes.py"]
  input: {pr: "{{ inputs.pr }}", findings: "{{ steps.triage.findings }}"}   # optional: what the script reads on stdin
  parse: json
  next: report
```

- **The runner executes the script, never the agent.** It costs no agent tool call and no tokens, and it gives the same result every time.
- `run` is an argument list. The runner computes each element, converts it to text, and runs the list with no shell. This prevents shell injection and removes shell differences between operating systems.
- Put real logic in `scripts/` as Python or Node, and call it: `[uv, run, "{{ skill.dir }}/scripts/verify_quotes.py"]`.
- **A script gets its data through `input`, on stdin.** The runner computes `input`, then writes it to the script's stdin: a text as it is, and any other value (usually a mapping) as one JSON object. Stdin has no length limit; a command line has one (about 32,000 characters on Windows). Without `input`, stdin is empty.
- So a script has one way in and one way out. A Python script reads `json.load(sys.stdin)` and prints `json.dumps(result)`. It never reads the run state by itself: the skill names every value that the script gets.
- `run` names the command and its fixed options. A command that reads a text on stdin, such as `gh issue comment --body-file -`, takes that text as its `input`.
- The working directory is the project root. The environment adds `PSKILL_RUN_DIR` (the run folder) and `PYTHONIOENCODING=utf-8`, so a Python script reads and writes UTF-8 on every system, as the runner does.
- Changed in 0.20.0: before, a long value went to a script as a file path (the `to_file` filter), and a script could read a copy of the whole run state (`PSKILL_STATE_FILE`).
- Output: `steps.<id>.stdout`, and `steps.<id>.json` with `parse: json`.
- **Output limit.** With `parse: json`, the runner keeps the whole stdout: it is the block's value. It keeps the first 64 KiB of any other stdout, and of stderr, and appends a note on its own line: `[pskill cut this output: it keeps the first 65536 of <size> characters.]`. So no later step takes a cut text as whole. The runner checks the whole result first, so a failure message shows the real end of stderr. Changed in 0.32.1 (#139): before, the runner cut stdout and stderr to 64 KiB with no note, so a JSON value over 64 KiB failed as "not valid JSON".
- A non-zero exit code, a timeout (config `script_timeout_s`, default 300, or the block's own `timeout_s: <seconds>`), or bad JSON is a block failure. A script that wants to report a normal "no" result exits 0 and prints JSON.

### 6.5 `call`

```yaml
review:
  type: call
  skill: review-pr
  inputs:                              # child input -> value
    pr: "{{ steps.implement.pr_number }}"
    post_verdict: false
  next: after_review
```

- The runner pushes a new frame on the run's call stack. The frame has the child's own inputs and steps. The child cannot read the caller's state.
- The first packet inside the child shows the child's goal once (D8). The packet header shows the chain (`implement-issue > review-round`).
- When the child reaches an `end` block, the call block completes with `steps.review.status` (`succeeded`, `failed`, or `cancelled`) and `steps.review.outputs`. The caller branches on `status` when it matters.
- The validator rejects call cycles.

### 6.6 `end`

```yaml
done:
  type: end
  status: succeeded                    # succeeded | failed | cancelled
  outputs:                             # a `succeeded` end must cover every required skill output
    pr_url: "{{ steps.implement.pr_url }}"
    result: implemented                # plain text is just text
  report: instructions/report_done.md  # optional: the final packet asks the agent to tell the user this
```

---

## 7. Computed values, state, and execution

### 7.1 Computed values: one syntax

- One engine: Jinja2 `SandboxedEnvironment`. One syntax: **anything inside `{{ }}` is computed. Everything else is plain text.**
- `{{ }}` works in every string value of `skill.yaml` and in instruction and `report` files.
- **Types.** A YAML value that is exactly one `{{ ... }}` and nothing else keeps the type of its result: a number, a list, an object, or true or false. Any other string with `{{ }}` renders to text. Implement it with `env.compile_expression` for the first case and a normal template for the second.
- A plain YAML value (`post_verdict: false`, `result: implemented`) is used as it is.
- `when` must be exactly one `{{ ... }}`. Its result counts as true or false. The validator rejects any other `when`.
- **Names:**

| Name | Content |
|---|---|
| `inputs` | Skill inputs, with defaults applied. |
| `steps.<block_id>` | The latest valid output of that block. |
| `history.<block_id>` | A list of every valid output of that block in the current frame, oldest first. A child skill's frame starts empty. |
| `run` | `id`, `mode`, `harness`, `dir`. |
| `skill` | `id`, `dir`. |
| `item` | The current element, in a `parallel` block only. |

- **Missing values.** A value from a block that has not run, or an optional field that was not given, is undefined.
  - Chains over it do not crash, `| default(x)` replaces it, and `is defined` tests it. A comparison with it is false.
  - Rendering it as text, using it as a whole value, or iterating over it is a block failure. This prevents silent empty text, such as an empty comment posted to GitHub.
  - Implement this as a subclass of Jinja's `ChainableUndefined` that raises on `__str__` and `__iter__`.
  - The validator still rejects references to blocks or inputs that do not exist (section 11).
- Put parentheses around a filter inside a comparison: `(inputs.issue | int(0)) > 0`.
- **One extra test: `matches`.** `{{ text is matches(pattern) }}` is true when the regular expression matches anywhere in the text (`re.search`). With `select`, it keeps the matching items of a list: `{{ paths | select('matches', '^api/') | list }}`.
- There are no variables and no assignments. `steps` and `history` hold all the state. This is on purpose (section 18).

### 7.2 Run statuses

| Status | Meaning | Stop hook |
|---|---|---|
| `active` | The runner waits for the agent's submission. | Blocks the stop. |
| `waiting_for_human` | A human decision in interactive mode is open. | Allows the stop. |
| `paused` | A block failed, `pskill pause` ran, or the Stop hook gave up. `pause_reason` says why. | Allows the stop. |
| `succeeded`, `failed`, `cancelled` | Final. | Allows the stop. |

### 7.3 Submissions

- **One command per block.** The packet prints the exact `submit` command, in the form for the agent's shell. The agent replaces the example answer and runs it.
  - bash, zsh, Git Bash:
    ```bash
    uv run .pskill/pskill.py submit r-20260927-1432-ab12 <<'PSKILL'
    status: question
    plan: |
      1. Add the column.
      2. Backfill it.
    question: Should old rows get a default value?
    PSKILL
    ```
  - PowerShell (the first statement forces UTF-8 on Windows PowerShell 5.1):
    ```powershell
    $OutputEncoding = [System.Text.UTF8Encoding]::new($false); @'
    status: question
    plan: |
      1. Add the column.
    question: Should old rows get a default value?
    '@ | uv run .pskill/pskill.py submit r-20260927-1432-ab12
    ```
  - Both forms are literal: the shell changes nothing inside them (no quote, `$`, or backtick handling).
- **A long answer goes in a file** (D16). The Return section of each packet, and each task prompt, has one line after the submit command that names an answer file and the full command: `uv run .pskill/pskill.py submit <run> [--task <n>] --file <path>`. The agent uses it for an answer over about 5 KB.
  - The path is `.pskill/runs/<run>/answers/<block>.yaml`, or `<block>-task-<n>.yaml` for a parallel task, so parallel subagents never write the same file. The runner creates the `answers/` folder when it prints the packet.
  - The command has no stdin, so it is the same in bash and PowerShell.
  - The runner reads the file as UTF-8 and drops a byte order mark. It then handles the text exactly like the same text on stdin. A missing, empty, or non-UTF-8 file (such as UTF-16, which Windows PowerShell 5.1 writes) is a usage error (exit code 1). With `--file`, the runner never reads stdin. After it records the answer, it deletes the file (a file that another program holds open stays), so a later visit of the block does not send an old answer. It deletes only a file inside the run's `answers/` folder, never a file of the user's. A rejected answer keeps its file, so the agent fixes only the wrong fields.
- **Shell detection.** On macOS and Linux, use the bash form. On Windows, use the bash form when the env var `MSYSTEM` is set (Git Bash), else the PowerShell form. The adapter may override this (VERIFY which shell Codex uses on Windows). When `submit` fails to parse, its error message shows the other form too.
- **No answer.** When stdin is a terminal, or no data arrives within 10 s, `submit` fails at once with the correct command form. It never hangs.
- **Parsing.** Read the answer with PyYAML's `BaseLoader`, so every value arrives as text. Then convert each field to its declared type from the block's output schema: `integer`, `number`, `boolean` (only `true` or `false`), arrays and objects field by field. So `choice: no` stays the text `no`, and `question: 1.10` stays `1.10`. A value that does not convert is a validation error that names the field.
- **Parallel tasks:** each subagent runs `submit <run> --task <n>` with its own answer. The reply only says that the task is recorded, also for the last task: the main agent reads the next block with `current`.
- **A task answer while the run is paused:** when the Stop hook paused the run (reason `agent_stopped`), `submit --task` still records a valid task answer, so a subagent that was still working loses nothing. It only records: `resume` advances, and it completes a parallel block whose tasks all have answers. Any other pause still refuses every answer.
- **Reserved keys**, removed before validation:
  - `$answered_by`: `human` or `agent`. Required for human decisions in interactive mode.
  - `$cannot_complete`: a reason text. The agent declares that it cannot do the block. This counts as a failed attempt. It is the agent's only escape.
- An invalid submission is logged with its raw text. The packet comes back with an "Errors" section.
- **Stats need no extra call.** The runner stamps the time when it prints a packet and when the answer arrives, and it computes `duration_ms` and `decided_by` itself.

### 7.4 Failures

Two kinds of failure exist:
- **Retried failures** can succeed on a second try: an invalid submission, a `$cannot_complete`, and a failed script. The runner retries up to `retries` times (config, default 2): it reprints the packet with the errors, or it runs the script again. After that it pauses the run with the reason `block_failed`. A `task`, `decision`, `parallel`, or `script` block can set its own `retries: <n>` (0 means no second try), which overrides the config value for that block.
- **Runner-side failures** fail the same way every time, because nothing changed: a computed value that fails, no matching edge, a visit cap with no `on_max_visits`, and invalid end outputs. The runner pauses the run at once with the reason `runner_error`.

The pause packet shows the error and three commands: `resume` (retry the block with a fresh count), `cancel`, and `current`.

As a guard, a run pauses when more than 1,000 runner-only blocks run without an agent block in between.

### 7.5 Modes

Set the mode with `start --mode interactive|autonomous` (default from config: `interactive`). The mode is fixed for the whole run, nested calls included. It changes only human decisions (6.2).

### 7.6 Resume

- `pskill current [<run-id>]` prints the current packet again. With no id, it uses the newest unfinished run.
- `pskill resume <run-id>` moves a paused run back to `active` and prints the packet.
- `pskill runs --open` lists the unfinished runs. The session-start hook does not list them: a run of another live session would invite the new session to take it over (L4).
- A run always uses its own copy of the skills in `runs/<id>/skills/` (D22).
- `start`, `current`, `submit`, and `resume` detect the harness on every call. When it differs from `run.harness`, the runner updates `run.harness` and logs `harness_changed`. The Stop hook and the packet wording then follow the new harness.
- The same commands read the session id of the calling app: `CLAUDE_CODE_SESSION_ID` in Claude Code, `CODEX_THREAD_ID` in Codex (VERIFY: that it equals the hook's `session_id`). When it differs from `run.session_id`, the runner updates it and logs `session_changed`. So the session that continues a run (after `/clear`, or in a new session) becomes its owner. A `submit --task` never changes the owner: a subagent sends it, and a subagent may have its own id.
- `start` adds one line to its packet when other unfinished runs exist in this checkout. It still starts the new run.

### 7.7 File safety

- Write `run.json` and `state.json` to a temp file, then call `os.replace` (atomic on every OS).
- Every command holds a lock on `runs/<run-id>/.lock`. Create it with `os.open(O_CREAT | O_EXCL)`. Wait up to 10 s. Break a lock older than 60 s. Parallel task submissions depend on this lock.

---

## 8. Packets (what the agent sees)

Packets are short Markdown on stdout, and never contain future blocks.

```text
## pskill · implement-issue · create_plan (visit 2)
Run r-20260927-1432-ab12 · interactive

### Instruction
<rendered instructions/create_plan.md>

### Return
When the work is done, run this one command. Replace the example values.
uv run .pskill/pskill.py submit r-20260927-1432-ab12 <<'PSKILL'
status: finished        # required, finished | question: finished when no open question is left.
plan: |                 # required, text: the full plan, or the draft so far when status is question.
  ...
question: ...           # optional, text: the single most important open question.
PSKILL
For an answer over about 5 KB, write it to the file `.pskill/runs/r-20260927-1432-ab12/answers/create_plan.yaml` instead, then run: `uv run .pskill/pskill.py submit r-20260927-1432-ab12 --file .pskill/runs/r-20260927-1432-ab12/answers/create_plan.yaml`
```

The stub gives the goal and the rules (section 9.3), so a normal packet has neither (D8). Two cases add them:
- **Goal only:** the first packet of a child skill, as `### Goal` after the header.
- **Goal and rules:** `current` and `resume`, because a new session, or a session after `/clear` or compaction, may not have read the stub. The `### Rules` section comes last:

```text
### Rules
- Do only this block. The runner gives you the next one.
- If you cannot do it, submit only the line `$cannot_complete: <reason>`.
- If the user asks to stop, run: uv run .pskill/pskill.py pause r-20260927-1432-ab12
```

Additions by block type:
- **Decision with choices:** the Return section lists each choice and its meaning.
- **Human decision, interactive:** "Ask the user and wait. Submit the user's answer with `"$answered_by": "human"`. Do not decide for the user." The adapter adds the wording for its question tool (section 9).
- **Human decision, autonomous:** "This run is autonomous. Decide as the user would, from the goal, this session, and the project. Explain why in `rationale`."
- **Parallel with subagents:** the packet lists every open task under the heading `#### Task <n>` (`#### Task <n> · <name>` with a `task_name`), with a one-line prompt: "You are a subagent of pskill run <run>. In the folder `<project root>`, run `pskill task <run> <n>`, and do what it prints." `pskill task` prints the task's full prompt: the work folder, the agent role, the goal, the instruction, the return format, and its own submit command with `--task <n>`, plus its `--file` line. The packet says: "Spawn one subagent per task, all at once, each with a fresh context (none of this conversation). Give each subagent exactly the one-line prompt of its task. When every subagent has finished, run `pskill current <run>`." The same line restarts a task whose subagent stalled. Changed in 0.12.0: before, the packet held every full prompt, which the main agent copied by hand.
- **Parallel without subagents:** the packet gives one task at a time, like a normal block.
- **Final packet:** the status, the rendered `report`, the outputs, and "The run is finished."

---

## 9. Harness adapters

```python
class HarnessAdapter(Protocol):
    name: str
    def detect(self, env: Mapping[str, str]) -> bool: ...
    def hook_files(self, runner_cmd: list[str]) -> list[HookFileChange]: ...
    def can_spawn_subagents(self) -> bool: ...
    def question_wording(self, prompt: HumanPrompt) -> str: ...
    def subagent_wording(self, task: TaskPrompt) -> str: ...
    def stop_response(self, block: bool, reason: str) -> tuple[str, int]: ...   # stdout, exit code
```

### 9.1 Capability matrix (VERIFY every cell)

| | Claude Code | Codex CLI | generic (any other harness) |
|---|---|---|---|
| Detect | env `CLAUDECODE=1` | env `CODEX_THREAD_ID` (set for every command) | fallback when nothing else matches |
| Stub folder | `.claude/skills/` | `.agents/skills/` | `.agents/skills/` |
| Stop hook | `Stop`; pskill answers with `hookSpecificOutput.additionalContext` (non-error feedback that keeps Claude working; Claude Code also caps continuations at 8) | `Stop` in `.codex/hooks.json`; pskill answers with `{"decision": "block", "reason": ...}` (Codex needs JSON on stdout) | none |
| Session-start hook | `SessionStart` with matcher `startup\|resume\|clear\|compact`; its plain stdout becomes context | `SessionStart`; its plain stdout becomes context | none |
| Subagents | Agent tool with `subagent_type: general-purpose` and `run_in_background: false` (the turn waits for every subagent; the calls still run in parallel) | `spawn_agent`, then `wait_agent` | no (one by one) |
| Question tool | `AskUserQuestion` (2-4 options; above 4, use a plain question) | plain question | plain question |

- An adapter that cannot VERIFY a capability uses the `generic` behavior for it.
- Gemini CLI and Cursor use `generic` in the MVP. They read `.agents/skills/` (VERIFY), so they find the stubs.
- Codex runs project hooks and rules only after the user trusts the project, and asks the user to trust each hook definition once (`/hooks`). The README must say so.
- Codex runs hooks from the session's folder, with no project-root placeholder. pskill's Codex hooks find the runner from the git root (`git rev-parse --show-toplevel`).
- Codex verified facts, with sources, live in `pskill_runner/codex.py`.
- `--harness` beats detection. Stubs always pass `--harness auto`, so one stub text works in every folder and every harness.
- The "Stub folder" row only says which folder each harness reads. `config.stub_folders` decides where `sync` writes.
- Claude Code reads project skills only from `.claude/skills/`, not from `.agents/skills/` (verified on 2026-09-28), so the default `stub_folders` shows no duplicates.
- Claude Code verified facts, with the doc URLs, live in `pskill_runner/claude_code.py`. Hook commands read the `CLAUDE_PROJECT_DIR` environment variable, which Claude Code sets, so they work from any folder.
- **Every hook command is one `uv run --no-project python -c "..."` call** (`hook_command` in `pskill_runner/hook_settings.py`). It runs the runner's `hook` subcommand only when `.pskill/pskill.py` exists, and otherwise exits 0 with no output. It always exits 0: Claude Code and Codex read exit code 2 from a Stop hook as "block the stop", and a failed `uv run` (for example, no network on a cold cache) exits 2. The runner blocks a stop with JSON on stdout instead. Each hook has a `timeout`: 30 s for Stop, 120 s for session start, which may download the runner. The command text holds no `$`, backslash, or percent sign inside its double quotes, so bash, PowerShell, and cmd read it the same.

### 9.2 Hooks (two only)

`sync` installs them for each target harness that supports them. The command is `uv run .pskill/pskill.py hook <event> --harness <name>`. `sync` finds its own entries by this command string, and never touches other hooks.

- **Stop.**
  - Look only at the newest `active` run for this harness in this checkout that holds this session: its `session_id` equals the hook input's `session_id`, or one of the two is missing. If it exists, block with the reason: "pskill run <id> has an open block. Run `uv run .pskill/pskill.py current <id>`."
  - Never block the stop of a subagent. Claude Code sends subagent stops as a separate `SubagentStop` event, which pskill does not hook. VERIFY how Codex marks a subagent stop.
  - After 3 blocks in a row (config `stop_hook_max_blocks`) with no submission between them, allow the stop and pause the run with reason `agent_stopped`. This prevents an endless loop.
  - For any other case, allow the stop.
- **Session start.** One job:
  - **Refresh the stubs.** Run the stub part of `sync` (not hooks, not permission rules). When it changed files, print one line: "pskill: updated <n> stubs (<skill ids>)." Skip a skill whose `skill.yaml` does not load, and print one warning line for it. This covers skill edits from any source: the agent, an IDE, `git pull`, or a teammate.
  - It lists no runs, and never resumes one (section 7.6).
- A stub goes stale only when a skill is added or removed, or when its `id`, `description`, `goal`, `inputs`, or `invocation` changes. Other edits need no sync, because `start` reads `skill.yaml` fresh.

### 9.2.1 Permission rules (D28)

`sync` adds exactly one allow rule for each target harness, and nothing else:
- **Claude Code** (`.claude/settings.json`, key `permissions.allow`): `Bash(uv run .pskill/pskill.py *)` (verified: the `*` form matches the whole command, including a heredoc).
- **Codex** (`.codex/rules/pskill.rules`): `prefix_rule(pattern = ["uv", "run", ".pskill/pskill.py"], decision = "allow")`, plus `prefix_rule(pattern = ["uv", "run", ".pskill/pskill.py", ["update", "init"]], decision = "prompt")`. The strictest matching rule wins, so a runner update or install asks first, in every spelling: `--from` can name any URL. Codex runs an allowed command **outside its sandbox** (limitation L7). The rule matches only a plain command: the `submit` form with an answer on stdin does not match (verified in #24), so Codex needs Full access (L7).

Rules:
- `sync` finds its own rule by its exact text. It never removes or changes other rules.
- `sync --check` reports a missing rule.
- The README shows the exact rule that `sync` adds.

### 9.3 Stubs

```markdown
---
name: implement-issue
description: "Implement a GitHub issue end to end. Use when the user asks to implement or fix an issue."
---
<!-- Generated by pskill from .pskill/skills/implement-issue. Do not edit. Run: uv run .pskill/pskill.py sync -->
Source: `.pskill/skills/implement-issue/`. This is a programmatic skill: the pskill runner gives you its steps,
one at a time.

Goal: Resolve the issue with a reviewed pull request that follows the plan the user approved.

1. Map the request to the inputs:
   - `issue` (string): issue number, or a text that describes new work.
   - `unattended` (boolean, optional, default: false): true when the user wants no questions.
   Ask the user for each required input that the request does not give, before you run `start`.
2. Run: `uv run .pskill/pskill.py start implement-issue --harness auto --input issue=<value>`
   Add `--input <name>=<value>` for each optional input that the request gives.
   If a value has spaces, quotes, or several lines, pass `--inputs -` and give the inputs as YAML on stdin, in the same literal form as `submit`.
   Add `--mode autonomous` only when the user asked for no questions.
3. The runner prints one step. Do only that step, then run the submit command at its end.
   The runner checks your answer and prints the next step.
4. Repeat step 3 until the runner says the run is finished. Never skip a step, and never stop before the end.
   If you cannot do a step, submit only the line `$cannot_complete: <reason>`.
5. If the user asks to stop, run: `uv run .pskill/pskill.py pause <run-id>`. Each step names its run id.
```

- The frontmatter follows the Agent Skills spec.
- **Inputs:** each input shows its type, `optional`, and its `default`. The start command names only the required inputs, so the agent never invents a value for an optional one. When a skill has a required input, the stub tells the agent to ask the user for each one that the request does not give, before `start`. (Added in 0.21.0: before, the start command named every input, and the stub showed no default.)
- `sync` overwrites and deletes only files that carry the generated marker. If a hand-written skill has the same name, `sync` stops with an error.
- `sync` also writes one built-in stub, `pskill`: "Resume, inspect, pause, or cancel a pskill run. Use when the user mentions an unfinished skill run." Its body lists `runs`, `current`, `resume`, `pause`, `cancel`, and `view`.
- Commit the stubs. `pskill validate` fails when a stub is out of date.
- Set `stub_folders` to match how the project already owns these folders:
  - In a project where another tool mirrors `.agents/skills/` into a gitignored `.claude/skills/` (the Galtea monorepo's `sync-skills-to-claude.js`), use `[.agents/skills]` only. The mirror then copies the stubs.
  - In a project whose ADR forbids `.agents/skills/` (the setup-guplem-standard ADR 0001), use `[.claude/skills]`, or update that ADR first.

---

## 10. Storage and trace

### 10.0 The `guplem/pskill` repository

```text
pskill/
├── pskill.py              # the entry script (PEP 723 header) and the template of every project's pinned copy
├── pskill_runner/         # the runner package, one module per concern
├── pyproject.toml         # development tools only: pytest, ruff, mypy
├── viewer/                # the viewer source
├── AUTHORING.md
├── tests/                 # pytest suite; tests/fixtures/<harness>/ holds saved hook payloads
├── .pskill/               # pskill installed into its own repository (the test bed)
│   ├── pskill.py          # the entry script with the dev pin: it runs this checkout. Refresh it with: uv run pskill.py update --from .
│   ├── skills/{implement-issue, review-pr, review-round, review-head-check, review-doubt, resolve-pr-feedback, fix-ci, create-issue, checkout-pr}/   # the example skills (section 13)
│   └── agents/{reviewer, explorer, pattern-scout, adr-checker}.md   # their pskill agents
├── .claude/skills/, .agents/skills/   # stubs generated by sync
├── .github/workflows/ci.yml           # section 16; release job builds pskill.zip on a tag
├── README.md              # human-facing: install, use, limitations L1 to L6, the rules that sync adds
├── AGENTS.md              # agent-facing map; CLAUDE.md is a one-line @AGENTS.md shim
├── CHANGELOG.md
└── LICENSE                # MIT
```

- The example skills work on the issues and pull requests of `guplem/pskill` itself. Milestones M3 and M4 run them there.
- A pytest test checks that `.pskill/pskill.py` equals the root `pskill.py` with the dev pin. It fails when someone forgets `update --from .`.

### 10.1 Project layout

```text
.pskill/
├── pskill.py            # the entry script with the pin (D20). Never edit; `pskill update` moves the pin.
├── config.yaml
├── .gitignore           # runs/
├── skills/<skill-id>/{skill.yaml, instructions/, scripts/, tests/}
├── agents/<name>.md     # pskill agents: subagent roles, shared by all skills (section 6.3)
└── runs/<run-id>/       # gitignored
```

The runner itself lives in the user's cache: `PSKILL_CACHE_DIR` when set, else `%LOCALAPPDATA%\pskill\` (Windows) or `$XDG_CACHE_HOME/pskill/` (default `~/.cache/pskill/`), one folder `<version>-<sha256 prefix>` per release. The runner writes every file with LF line endings and UTF-8.

`config.yaml`:

- **`hook_files`** are paths, because every hooks file has the same shape (`{"hooks": {...}}`). An app's own file (`.claude/settings.json`, `.codex/hooks.json`) gets that app's hook commands. Any other file, such as a project's own source of hooks that generates the app files, gets shared commands that pass `--harness auto`. The runner then detects the app from the hook input (`turn_id` means Codex) or the environment (`CLAUDE_PROJECT_DIR` means Claude Code). `sync` removes an app's own pskill hooks from its app file when that file is not listed. It keeps the shared hooks there: only the project's generator puts them there, when it copies the listed source.
- **`permissions`** are app names, because each app keeps its rules in its own format, in a fixed place: Claude Code in `permissions.allow` of `.claude/settings.json`, Codex in `.codex/rules/pskill.rules`.
- The old setting `harnesses` stops with an error that names these two settings.

```yaml
stub_folders: [.agents/skills, .claude/skills]          # where sync writes stubs
hook_files: [.claude/settings.json, .codex/hooks.json]  # where sync writes the two hooks
permissions: [claude-code, codex]                       # the apps that get the rule to run pskill without asking
default_mode: interactive
retries: 2
script_timeout_s: 300
stop_hook_max_blocks: 3
viewer_port: 7777
```

### 10.2 Run folder

```text
runs/<run-id>/
├── run.json       # metadata + status
├── state.json     # the call stack: per frame, skill id, inputs, steps, history, visits
├── events.jsonl   # the trace
├── skills/        # copies of every skill that this run can reach through calls
├── agents/        # copies of every pskill agent in `.pskill/agents/`
└── answers/       # the files for long answers, one per block or task (section 7.3)
```

`run.json` fields:
- `schema_version`, `run_id`, `skill_id`, `skill_hash` (sha256 of the copied skill files)
- `repo_commit`, `repo_dirty`, `runner_version`, `harness`, `session_id` (the owner session, or null), `mode`, `inputs`
- `status`, `pause_reason`, `current` (`{frame, block, visit}`), `attempts`, `stop_blocks`
- `created_at`, `updated_at`, `ended_at`, `outputs`

### 10.3 Events

Each line of `events.jsonl` has `ts` (UTC ISO 8601 with milliseconds), `seq` (a counter), `type`, and `frame` (for example `implement-issue>review-round`).

| type | Extra fields |
|---|---|
| `run_started` | `skill_id`, `skill_hash`, `inputs`, `mode`, `harness`, `runner_version` |
| `block_started` | `block`, `block_type`, `visit`, `from`, `reason` (the condition, the choice, or `always`), `packet` (the exact text given to the agent; none for runner blocks), `task?` (the task of a one-by-one parallel packet), `task_names?` (a parallel block with a `task_name`: the name of each task, or null), `skipped_tasks?` (a parallel block: each item of its fixed list whose `when` was false, as `{name, when}`; since schema version 3), `task_prompts?` (a parallel block with subagents: the full prompt of each task, which the viewer shows; since schema version 4) |
| `submission_rejected` | `block`, `task?`, `errors`, `raw` |
| `block_completed` | `block`, `task?`, `output`, `decided_by` (`agent`, `human`, `agent_autonomous`, `runner`), `duration_ms` |
| `script_ran` | `block`, `argv`, `input` (what the script read on stdin, or null; since schema version 5), `exit_code`, `stdout` (whole with `parse: json`, else limited as in 6.4), `stderr` (limited as in 6.4), `duration_ms` |
| `run_paused` / `run_resumed` | `reason` |
| `harness_changed` | `from`, `to` |
| `session_changed` | `from`, `to` |
| `run_ended` | `status`, `outputs`, `duration_ms` |

- `duration_ms` of an agent block runs from its packet to its valid submission. For human decisions it is mostly human time. The viewer shows it apart.
- This file is the contract for the viewer and for later evaluation work. A change needs a new `schema_version`.

---

## 11. Validation (`pskill validate`)

**Errors:**
1. The file fails the meta-schema.
2. The id does not match the folder name.
3. An unknown block type, or an unknown key.
4. The entry or an edge target does not exist.
5. A block is unreachable.
6. A non-`end` block has no `next`.
7. A choice map does not match `choices` one to one.
8. A `{{ }}` does not compile, or a `when` (of an edge, or of an item of a fixed `for_each` list) is not exactly one `{{ ... }}`.
9. A reference to an unknown input, `steps` block, or `history` block. The strings inside the items of a fixed `for_each` list count too.
10. An `instruction` or `report` value ends in `.md`, but the file is missing.
11. A top-level field of `inputs`, `outputs`, or a block `output` has no `description`.
12. An `agent` names a file that does not exist in `.pskill/agents/`. The validator checks plain names and the items of a fixed `for_each` list. An agent name computed from run data is checked at run time, and a missing file fails the block.
13. A `call` to an unknown skill, with an unknown input, or with a missing required input.
14. A call cycle.
15. A `succeeded` end that misses a required skill output. (`failed` and `cancelled` ends may give any subset.)
16. A skill description longer than 1024 chars.
17. A stub out of date.

**Warnings:**
1. A loop with no `max_visits`.
2. A condition list whose last item has a `when`.
3. An instruction file that no block uses.

---

## 12. Skill tests (`pskill test`)

A file `tests/<case>.yaml` is one case. A scripted fake agent answers. No harness and no LLM take part.

```yaml
name: obsolete issue closes after the user confirms
inputs: {issue: "42"}
mode: interactive
answers:                      # per agent block: one submission per visit, in order
  check_applies:
    - {choice: obsolete, rationale: "Fixed in #40", evidence: "src/save.ts:12"}
  confirm_close:
    - {choice: close, rationale: "User agreed", comment: "Fixed by #40.", "$answered_by": human}
scripts:                      # per script block: one result per visit
  read_issue:
    - {exit_code: 0, stdout: '{"number": 42, "title": "Crash on save", "body": "", "labels": []}'}
  close_issue:
    - {exit_code: 0, stdout: ""}
calls: {}                     # per call block: one {status, outputs, inputs} per visit (inputs is optional)
expect:
  path: [read_issue, check_applies, confirm_close, close_issue, closed]   # or path_contains
  status: succeeded
  outputs: {result: closed}
```

Rules:
- Scripts and calls are always mocked in tests. A called skill has its own tests.
- A recorded call can state `inputs`: the values that the call block must send on that visit. The case checks only the named inputs, and an input that the block does not send is a mismatch. The FAIL line names the block, the visit, the input, and the expected and actual values. A recorded call without `inputs` checks nothing.
- For a `parallel` block, list the answers of its tasks in task order, as for any other block. The test runner uses the one-by-one mode, so each task takes the next answer in the queue.
- An answer that fails validation is rejected, as in a real run, and the next answer is used. This lets a test prove that the schema catches bad output.
- When a case runs out of answers, it fails and names the block that asked for more.
- When a case file is not valid YAML and the error points at a `?` inside `{ }`, the problem adds a hint: put the value in quotes.
- The output has one PASS or FAIL line per case, and the first mismatch for each FAIL.

---

## 13. Example skills

The example skills are a base that almost any software project on GitHub can copy and then adapt. They also run on this repository's own issues and pull requests (the test bed), and together they exercise every runtime feature (13.3). The files in `.pskill/skills/` and `.pskill/agents/` are the source of truth: this section gives their shape and the rules behind it, not their text.

### 13.1 The skills

| Skill | What it does | Its blocks, in order |
|---|---|---|
| `implement-issue` | An issue (or a described change) to a pull request that is ready to merge. It never merges. | `create_new_issue` (call `create-issue`, for a described change only), `read_issue`, `checkout_default`, `understand`, `checkout_base`, `research_code` and `research_gaps` (parallel), `ask_user`, `write_plan`, `approve_plan`, `open_draft_pr`, `implement_step` (one red-green cycle per visit), `write_description`, then the loop `review` (call `review-round`) and `resolve` (call `resolve-pr-feedback`), then `ready`, `get_ci_green` (call `fix-ci`), `answer_comments` (call `resolve-pr-feedback`), `check_unreviewed`, the required-only loop `final_review` and `final_resolve`, and `finish`. |
| `review-pr` | A deep review that ends in one GitHub review that the user confirms: it requests changes while a required finding is open, approves otherwise, and only comments on the user's own pull request. It changes no file. An autonomous run ends with the draft. | `read_earlier` (the findings of earlier reviews and their replies), then the loop `review` (call `review-round`) and `check_head_before_round` (call `review-head-check`), `triage`, `settle_doubt` (call `review-doubt`, once per finding in doubt), `final`, `draft`, `confirm` and `ask_revision` in a loop, `check_head_before_post`, `post`. |
| `review-round` (internal) | One review round: five reviewer subagents (correctness, tests, completeness, conventions, docs) in parallel. It finds problems only, and skips the findings that it is told were already raised or reported. | `checkout` (call `checkout-pr`), `read_pr`, `review` (parallel over a fixed list, with a `when` per angle), `collect_findings`. |
| `review-head-check` (internal) | Whether the review can go on after the head of the pull request moved: a clean merge of the base or a small change goes on, a significant change asks the user. | `read_head`, `judge`, `ask`. |
| `review-doubt` (internal) | The verdict on one finding in real doubt: required, suggestion, or drop. "I don't know" starts simple yes/no questions, at most 6. | `ask`, then `next_question` and `ask_question` in a loop, `decide`. |
| `resolve-pr-feedback` | Each given finding and each unaddressed pull request comment, one at a time: fix it or dismiss it, and reply to the comment. | `checkout`, `collect_items`, then per item `claim_item` (the 👀 reaction), `resolve_item`, `finish_item` (the reply). |
| `fix-ci` | The CI checks of a pull request green, or a reason why the pull request cannot fix them. | `checkout`, `wait_ci`, `fix_ci`, in a loop. |
| `create-issue` | One clear issue, after the user approves the draft, or the existing issue that covers it. | `resolve_repo` (the target repository: the `repo` input, or the current one), `assess_clarity` and `ask_clarify` in a loop, `extract_terms`, `search_duplicates`, `judge_duplicates`, `confirm_duplicate`, `draft_issue`, `confirm_draft`, `create`, and in autonomous mode `ensure_label` and `label_issue`. |
| `checkout-pr` (internal) | The checkout on the pull request branch at its latest commit. It pauses the run instead of discarding a change. | `checkout_pr`. |

The pskill agents: `reviewer` (one review angle, no quote no finding), `explorer` (one research question), `pattern-scout` (the closest existing code), and `adr-checker` (the recorded decisions that limit a change).

### 13.2 Design rules (learned from real runs)

- **Low coupling to the project.** The skills need git, `gh`, and `uv`, a remote named `origin`, and the repository's default branch. They read the project's own rules from its `AGENTS.md`, `CLAUDE.md`, `CONTRIBUTING.md`, README, and ADR files. They hard-code no command, folder, or label beyond the conventions in the README section "Recommended setup for the example skills".
- **Scripts do the mechanical work.** Checking out, naming the branch, opening the draft, marking it ready, collecting comments, adding reactions, and posting replies are scripts with typed JSON output. An agent never runs those steps by hand.
- **The plan lives in the draft.** `implement-issue` writes a plan file, the user approves it, and a script pushes it as the only change of a draft pull request. Every later step reads it. `ready` removes it before CI runs on the ready pull request.
- **One set of acceptance rules.** `references/finding-acceptance.md` decides which finding is real, belongs to the pull request, and has which severity. The reviewers, the triage of `review-pr`, `review-doubt`, and `resolve-pr-feedback` each keep an identical copy, and a test fails when the copies differ.
- **Ask the user little.** The triage of `review-pr` asks about a finding only when one of the four tests of `references/decision-gate.md` fails and the answer changes what the review posts. An autonomous run takes the triage's recommendation.
- **Find and fix are separate.** `review-round` only reports; `resolve-pr-feedback` only resolves. The loop between them ends when a round fixes nothing, after the 4th round with no required finding, or at a cap of 7 rounds. Every reviewer sees every dismissed finding.
- **A fixed review scope.** The first review round's commit ends the scope. A changed line brings in its innermost function (or, outside any function, its section or block). An older problem is fixed only when the new code runs the broken part, it blocks the goal, or its fix stays inside the changed function.
- **Severity.** `required`: wrong code, a broken written rule, or a broken clear project pattern. `suggestion`: a better way that no rule or pattern asks for.
- **Every late fix gets a review.** After CI and the late comments, `check_unreviewed` (a script) lists the commits that no review saw, without the plan removal and clean merges. Each such commit gets a required-only round, up to 5 rounds; then `finish` labels the pull request.
- **No quote, no finding.** `collect_findings` drops a finding whose quote is not in its file. `post` of `review-pr` finds each finding again by its quote at the reviewed commit, because an earlier round can report a line of an older head.
- **One item at a time.** `resolve-pr-feedback` claims each comment with the 👀 reaction before its work starts, and its reply carries the marker `<!-- resolve-pr-feedback-reply: <id> -->`, so a later round never answers it twice.
- **Change the code, not the rule.** A finding that the code breaks a written rule is fixed in the code. The rule changes only when the rule itself is wrong.
- **Wait in the foreground.** `fix-ci` waits for CI inside the turn, so the Stop hook never sees an agent that ends its turn to wait.
- **A human label, not a merge.** `finish` adds `waiting-for-human-review` when a human must look (a risky area, a visible change, a cap reached, a dismissed finding, CI not green), with a short note at the top of the description that says what to check. The run never merges.
- **A limit says so.** In `implement-issue` and `resolve-pr-feedback`, a visit limit that cuts work short never ends the run as `succeeded`. `implement-issue` still runs to `finish`, then ends on `capped` (failed), whose `limits` output and report name each limit and the work it skipped. `resolve-pr-feedback` ends on its own `capped` past 100 items.

### 13.3 Feature coverage

The example skills together must exercise every runtime feature. pytest fixtures cover the features that no real skill needs.

| Feature | Covered by |
|---|---|
| `task` | `implement-issue.understand`, `resolve-pr-feedback.resolve_item` |
| Agent `decision` | `create-issue.judge_duplicates` |
| Human `decision` with choices | `implement-issue.approve_plan`, `review-pr.confirm`, `review-doubt.ask` |
| Human `decision` without choices (a question) | `implement-issue.ask_user`, `create-issue.ask_clarify` |
| A revision loop through a human decision | `implement-issue`: `write_plan` to `approve_plan` to `write_plan` |
| `parallel` over a fixed list, with an agent per item | `implement-issue.research_code` |
| `parallel` over a fixed list, with a `when` per item | `review-round.review` |
| `parallel` over a list computed during the run | `implement-issue.research_gaps` (one task per gap from `understand`) |
| pskill agents (`.pskill/agents/`) | `implement-issue.research_code` (from the item), `implement-issue.research_gaps` and `review-round.review` (fixed) |
| Inline instruction text | `implement-issue.research_gaps`, `implement-issue.approve_plan` |
| `script` with `parse: json` and with text | `implement-issue.read_issue`; `create-issue.create` |
| A script that enforces a rule | `review-round.collect_findings` (no quote, no finding) |
| Nested `call`, with typed outputs, several levels deep | `review-pr.review` calls `review-round`, which calls `checkout-pr` |
| Branch on a child's `status` | `implement-issue.create_new_issue` |
| `max_visits` with and without `on_max_visits` | `implement-issue.implement_step`; `create-issue.assess_clarity` |
| `history` | `resolve-pr-feedback.claim_item` (the next item), `implement-issue.review` (the dismissed findings) |
| Conditional `entry` | `implement-issue` |
| A script's `input` on stdin, as JSON and as text | `implement-issue.checkout_base`; `create-issue.create` |
| `run.mode` in a condition | `create-issue.create` |
| `succeeded`, `failed`, and `cancelled` ends | `fix-ci.passed`, `fix-ci.failed`, `implement-issue.held` |
| `invocation: internal` | `checkout-pr`, `review-round`, `review-head-check`, `review-doubt` |
| `autonomous` mode | test cases below |
| `$cannot_complete`, retries, then pause | test cases below |
| `invocation: manual` | `review-pr` |
| Parallel one by one, Stop hook, resume in a new session | the M3 and M4 acceptance runs |

### 13.4 Tests to ship

Each skill has test cases in `tests/`, for each of its paths: for example a clean run, a review loop that converges, the review round cap, the required-only rounds and their cap, a fix after CI, a CI failure that the base branch has too, a question for the user and a plan change, autonomous mode, `$cannot_complete` that pauses the run, and each reason to hold or stop. The scripts have pytest tests in `tests/test_skill_<skill>.py`, with a fake shell.

---

## 14. Viewer

- `pskill view` starts a `ThreadingHTTPServer` on `127.0.0.1` only and opens the browser. It shows one project.
- **The hosted viewer** shows the same screens on GitHub Pages, for every folder that the user picks (section 14.3).
- `viewer_api.py` answers the API for both: a request path in, an answer out.
- **All logic lives in the Python server,** so pytest covers it. The server builds:
  - the canvas: one Mermaid template for the whole run. Each child skill that the run entered is a framed `subgraph` inside the frame of the skill that called it, linked by a dotted edge from its call block. Each parallel block that the run entered has a frame of task nodes next to it, one per task, in balanced rows of at most 4, linked by a dotted edge. Node ids are `f<frame>_<block>`, and `f<frame>_<block>_T<n>` for a task (upper case, which a block id cannot contain). Each node label is a token that the page replaces.
  - the timeline rows. Each row carries its node, the edge that it arrived by (matched from the logged `from` and `reason`), its node label after the step, whether a person decides it, and the edge that it left by. It also carries its input and output titles, the stdout of each script run parsed as JSON when it is JSON, and, for a parallel block, every task of its visit: its name (from `task_name`, logged on `block_started`), its state (done, rejected, or open), its prompt, its answers, and its output.
  - a hint in plain words for each node (the block's `description`, what its type does, who decides) and each edge (when the run takes it, with the whole condition). The page shows them as hover tooltips.
  - the current step and its state (now, waiting for the user, or failed),
  - the summary numbers.
  - the main line of each frame: the usual way to a succeeded end. It is the longest way from the entry to a succeeded end that never goes back to an earlier block, without each block that the way can skip (its previous block also leads straight to its next one). The canvas lists the ids of the edges along it.

  The front end only draws them. For the replay, it adds up the rows up to the chosen step. It has no build step: plain HTML, CSS, and JavaScript.
- **Mermaid comes from a CDN.** `index.html` loads one exact, pinned version from jsDelivr (`https://cdn.jsdelivr.net/npm/mermaid@<version>/dist/mermaid.min.js`), with a Subresource Integrity hash.
- **ELK lays the graph out.** Mermaid's `@mermaid-js/layout-elk` package draws the graph top to bottom. It comes from jsDelivr too: an import map in `index.html` pins its version, with a hash for each of its files. Each main-line edge asks ELK to stay straight (`elk.layered.priority.straightness`), so the main line is one straight column, and the side branches go beside it. Main-line edges are thicker; on the skill screen, the other edges are lighter. When ELK does not load, Mermaid's own layout draws the graph.
- **Fonts:** Manrope and IBM Plex Mono from Google Fonts. The page falls back to the system fonts when they do not load.
- **Offline:** the canvas shows "Graph unavailable offline (Mermaid did not load)" and the steps (or, on the skill screen, the blocks) as a list of cards in the node style. The side panel, the replay bar, and the Runs, Content, and Folders screens still work, because they do not need Mermaid.
- While the open run is unfinished, the page polls every second (every 2 s on the Runs screen).
- **Refresh.** The app bar shows the live status: a dot and the time since the last read. The dot pulses with "Live" while a run updates, is solid while the automatic refresh is on, and is hollow when it is off. Next to it, a choice (off, 10 s, 30 s by default, 1 min, 5 min, kept in `localStorage`) and a button read everything again; on the hosted viewer, a refresh looks for new clones and worktrees first. A screen draws again only where its data changed. The refresh and the polls wait while the tab is hidden, and run at once when it comes back. They never run over an open editor or a dialog, and the automatic refresh also waits while a text field has the focus.
- **Top bar.** One row on every screen: the logo, then the tabs on the list screens (Runs, Content, Folders) or the screen's own parts on a run, skill, or agent screen, then the refresh. On a list screen, the logo opens pskill on GitHub in a new tab. On a run, skill, or agent screen, it shows a back arrow and leads back to the runs, or to the content of the project that the screen shows. The facts of a run or a skill (harness, mode, invocation, project, pause reason) wait behind a Details button, in a card that closes on a click outside or on Escape. Fit, zoom, and Follow live float in the canvas's top right corner. No label wraps onto two lines: a row that runs out of room wraps whole items.

| Endpoint | Returns |
|---|---|
| `GET /api/version` | The version of the runner that serves the viewer, and the project's folder name. The list screens show the version at the bottom left. |
| `GET /api/runs?skill=` | Run rows, plus one summary row per skill: runs, success rate, median duration. |
| `GET /api/runs/<id>` | `run.json`, the canvas, the collapsed canvas (only the run's own skill), the timeline rows, and the current state. |
| `GET /api/skills` | One row per skill in `.pskill/skills/`: description, invocation, block count, run count, and the load error of a skill that does not load. |
| `GET /api/skills/<id>` | The skill's facts, its canvas (its blocks, with each call block drawn as its child's frame, and no run parts), the details of each block, the details of each child block by node id, and the `pskill validate` problems, or the load error. |
| `GET /api/skills/<id>/export` | The skill as plain Markdown skills, in a zip file (section 14.1). |
| `POST /api/skills/<id>/edit` | The skill editor's one write: update, add, or delete a block (section 14.2). Returns the new skill detail, or the problems. |
| `GET /api/agents` | One row per agent in `.pskill/agents/`: its name, its first line, and the skills that use it. |
| `GET /api/agents/<name>` | The agent's file path, its text, and each skill and parallel block that uses it. |
| `POST /api/agents/<name>/edit` | The agent editor's one write: the new text of an existing agent file (`{"text": ...}`). Returns the new agent detail, or the problems. |
| `POST /api/runs/<id>/cancel` | Cancel an unfinished run, as `pskill cancel` does. Returns the new run detail, or the runner's reason. |
| `POST /api/runs/<id>/delete` | Delete a finished run, as `pskill delete` does. Returns `{"deleted": <id>}`, or the runner's reason. |

**Style:** a light grey dotted ground, and one color per meaning: blue for done, orange for now, purple for waiting for the user, red for a problem, dashed grey for not visited, and teal for a block that the text under the pointer names. Blue also marks what you can act on: links, the main buttons, the switch, and the keyboard focus ring. Every text color reaches 4.5:1 on its background in both themes, and the font sizes and corner radii come from one short scale each (a test checks both). Taken edges are solid blue. Each block type has its own icon, drawn for pskill as inline SVG: on its node above the block name, and next to the type in the side panel. Below the name, a node shows its type; a call block's node shows `call: <child skill>`, so the flow reads without a click. The page follows the system's dark mode.

**Two tabs, Runs and Content, and five screens.** Each address names its project, the place: for example `#/run/<place>/<run>` and `#/skill/<place>/<skill>`. `pskill view` has one place, `local`.
1. **Runs** (the Runs tab).
   - The runs of every project, newest first, with the filters Unfinished, All, and Failed, and a folder filter when there are several projects.
   - On the hosted viewer, each run card names its project: its path, its kind (clone or worktree), and its branch.
   - Under the cards, a "By skill" section: a table on a card like the run cards, with the runs, the success rate, and the median time of each skill, over every run, whatever the filters. The numbers align right.
   - For cleanup, one button deletes the finished runs that the filters show. It asks first, and the unfinished runs stay.
2. **Run.**
   - In the top bar: a run switcher (each option is the skill and the run id, grouped by status), the status, the Details button, a "skill changed" pill when the skill changed after the run started, Collapse sub-skills, Skill graph, and Cancel run or Delete run. Follow live, Fit, and zoom are on the canvas.
   - **Collapse sub-skills:** an on and off switch, shown when the run entered a child skill. It draws each call block as one node instead of its child's frame. It is off by default, so a live run shows its exact step; the page keeps only a choice to collapse, in `localStorage`. The server sends this second canvas too (`collapsed_canvas`): the run's own skill, with the edge ids of the full canvas, so the timeline rows fit both, and its current step on the call block at the top. The full canvas lists each child frame with its call block (`child_frames`). A step inside a collapsed child skill shows on its call block, which Follow live then follows. The side panel still shows the step's own block, with a note and an Expand sub-skills button.
   - The canvas: the graph fills the screen. Drag to pan, and use the wheel to zoom. It opens at a readable zoom, centered on the current step. With Follow live, it keeps the current step in view.
   - A side panel for the clicked node. Drag its left edge to change its width; the page keeps the width in `localStorage`.
     - the status and the type, and a visit picker when the block ran more than once,
     - where it came from and why, the duration, who decided, and the edge that it left by,
     - the input: the packet as rendered Markdown, or the command of a script,
     - for a parallel block, one chip per task, with the task's name (or `task <n>`); a click on a chip or on a task node shows that task's prompt, answers, and output,
     - every submission (rejected ones with their errors), and the output: a JSON tree, or the exit code and parsed result of a script,
     - the run state as a JSON tree.

     Long content shows its first 3 lines, with a button to show all of it. The panel builds Markdown and JSON trees from elements, never from HTML.

     A close button at the panel's top right, or Escape, clears the selection: the panel shows the current step again. On the skill screen, it shows the skill again. On the run screen, "Arrived from" and "Went next to" name their blocks as references (see screen 4).
   - A link to the skill screen of the run's skill.
   - "Cancel run" on an unfinished run, and "Delete run" on a finished one. Each asks first. The agent of a cancelled run learns it at its next pskill command.
   - A replay bar: one mark per step, with rejected answers and human decisions marked. Drag it, press play, or use the left and right arrow keys, and the canvas and the panel show the run as it was at that step. At its end, it follows the live run. This is the step-through replay (D14).
3. **Content** (the Content tab). The skills and the agents of one project. With several projects, a picker chooses it, and the tab reopens the last one.
   - One card per skill in `.pskill/skills/`, also a skill with no runs, with its description, block count, and run count. A skill that does not load shows its error. The `internal` skills come last, in their own section.
   - One card per agent in `.pskill/agents/`, with its first line and the skills that use it. `agent_view.py` builds it.
4. **Skill.** One skill's graph without a run, read from `.pskill/skills/` (never from a run copy). `skill_view.py` builds it.
   - The same canvas as the run screen, with every block and every edge, and no run parts: no status, no current step, no timeline, and no replay bar. Every node has the same plain style.
   - **Child skills:** each call block is drawn as a dashed frame that holds its child skill, in the call block's place. The edges into the call block end at the frame, and its exits leave from the frame. The frame's title, at its top left, is the call block's name, with `call: <child skill>` below it. A click on the title or on the frame's empty area selects the call block. A child's own call blocks are frames inside its frame. (The run screen keeps the call block as a node, with the child's frame next to it.) A child that does not load, or a call back into a skill of its own chain, gets no frame. A click on a block of a child frame shows its details read-only, with a link to the child skill's own screen, where it can be edited. The panel finds a child block by its node id, because its name can be the name of a block of the parent.
   - **Collapse sub-skills:** an on and off switch in the top bar draws each call block as one node instead of its child's frame. It is on by default, for a quick look at the flow of a skill with many child skills. The server sends this second canvas too (`collapsed_canvas`). A block of a child frame that the panel shows gives way to the call block that holds it. The page keeps only a choice to expand, in `localStorage`. A skill with no child skill has no switch.
   - The side panel with nothing selected: the goal, the inputs and outputs, and the `pskill validate` problems.
   - The side panel for a clicked block: its facts (decider, visit cap, retries, command), its instruction as Markdown (with the `{{ }}` values unfilled), its choices, its output fields, the inputs and outputs of a call or an end block, and where it can go. A name that leads to another screen is a link with an arrow: the child skill of a call block, and the agent of a parallel block (one link per agent of a fixed `for_each` list). An agent name computed from run data has no link.
   - A script block also shows the text of each file inside its skill folder that its command runs as `{{ skill.dir }}/<path>`.
   - Each output field is a card: its name, its type, optional, its default, its allowed values, its description, and its nested fields.
   - Each exit is a card: the target block, a tag (if, otherwise, always, choice, or visit cap), and the whole condition. A hover on the card highlights its edge and its target on the canvas. A click opens the target.
   - **References:** each `steps.<block>` and `history.<block>` in the panel (an instruction, a fact, a command, an input or output value, an item's `when`, an exit condition) is a teal reference to that block of the same frame. A hover lights up the block on the canvas, and a click opens it. A hover on an edge of the canvas lights up the blocks that its condition reads. A problem whose location is a block, and the call block that runs a child, are references too.
   - **Field help:** each field of a block (in the panel and in the editor), and the goal, inputs, and outputs of the skill, has a "?" button. Its tooltip says what the field is. A click opens a dialog with the details and YAML examples. `viewer/field_help.js` holds the texts; a test checks that every block field of the schema has one.
   - A skill that does not load shows its load error instead of a graph.
   - An "Export" button downloads the export as Markdown (section 14.1).
   - An "Edit" button turns on the skill editor (section 14.2).
5. **Agent.** One agent: its file, a link to each skill that uses it (with the block names), and its text as Markdown.
   - "Used by" lists only the uses that `pskill validate` can see: a plain agent name, or the items of a fixed `for_each` list.
   - An "Edit" button shows the text in a plain text box. "Save" replaces the file; a CRLF file stays CRLF. The editor changes only an agent file that exists, so a name never points outside `.pskill/agents/`.

### 14.1 Export as Markdown

`skill_export.py` turns a skill into a plain `SKILL.md` that any agent can follow without pskill. No runner checks the agent then, so the export only describes the graph as clearly as it can:

- **Frontmatter:** `name` and `description`, plus `disable-model-invocation: true` for a `manual` or `internal` skill.
- **Steps:** one `## Step N: <block>` heading per block, in graph order (breadth first from the entry). A short "How to follow this skill" part comes first.
- **Edges:** "go to step N" lines, with each condition as a plain expression. A visit cap becomes "Do this step at most N times".
- **Values:** `{{ steps.x.y }}` becomes `x.y`, `history.x` becomes `x.all_visits`, and `{% %}` tags become words. Inside the author's own code, a value stays a bare name.
- **Block types:** a human decision asks the user, a script is a command that the agent runs, a parallel block uses subagents or does the items one by one, and an end step names its status, outputs, and report.
- **Files:** the zip holds `<skill>/SKILL.md`, the skill's `scripts/`, and each pskill agent that it uses as `<skill>/subagents/<name>.md`. (Not `agents/`: Codex reads `agents/openai.yaml` there.)
- **Child skills:** each child skill of a call block is exported as its own folder in the same zip. The call step tells the agent to follow it, then to come back.
- **Script input:** a script step with an `input` tells the agent what to send on the command's standard input: each field of the JSON object, or the text.

### 14.2 The skill editor

The skill screen can change a skill. `skill_editor.py` writes the change to `skill.yaml`.

- **What it edits:** a block's description, visit cap, retries, instruction or report (inline, or the text of its `.md` file), `next` edges (with conditions, and per choice), choices, decider, command, parse, timeout, child skill, agent, task name, `for_each`, and end status. It also adds a block of any type (the smallest valid block) and deletes a block that no edge leads to. It does not edit field maps, `inputs`, `outputs`, or the skill's top level: edit those in the file.
- **Only the changed block changes.** `ruamel.yaml` (a YAML library that keeps comments) reads the file. The editor replaces only the lines of the changed block, so every other line stays byte for byte the same. Inside the block, the comments, the quotes, and the anchors stay. A new key goes where the skill files put it (for example `description` after `type`). A list that the author wrapped over two lines becomes one line, but only in the changed block.
- **Only keys that changed:** the page sends only the keys that the user changed, so an untouched key keeps its exact form.
- **A structure error is refused:** a change after which the skill does not load is not saved, and the file stays as it was. A validation problem (for example an end that misses a required output) is saved, and the checks show it, because many edits need several steps.
- **No node positions:** Mermaid lays out the canvas automatically, so there are no positions to keep in a sidecar file.
- **Only the viewer page may write.** The server is on 127.0.0.1, but any web page in the user's browser can send requests to it. So the edit endpoint takes only JSON (a browser asks first before it sends JSON to another site, and this server never allows it), a `Host` of this server (against DNS rebinding), and no `Origin` other than this server.
- After an edit, run `pskill validate`, `pskill test`, and `pskill sync` as after any skill change.

### 14.3 The hosted viewer

The viewer also runs on GitHub Pages, with no server: <https://guplem.github.io/pskill/>. (It leads to the account's custom domain while one is set; the docs link the github.io address, which stays valid without it.) It shows the runs of many projects at once: clones, worktrees, and separate projects.

- **Which mode:** the page asks `/api/version` first. When no local server answers, `app.js` loads `hosted.js`, and the page is the hosted viewer.
- **Folders:** the Folders tab picks folders with the File System Access API (Chrome and Edge only). A folder is one project, or a folder of projects. IndexedDB keeps the picked folders, so a reload only asks the browser for permission again.
- **Finding the projects:** each folder that holds `.pskill/` is a place. The scan looks at the picked folder, its subfolders up to 3 levels down (without hidden folders and folders such as `node_modules`), and the worktrees of each git checkout (`.claude/worktrees/`, `.worktrees/`, `worktrees/`). It does not go inside a checkout otherwise. It looks again every minute and on "Look again", so new clones and worktrees appear by themselves.
- **A pattern per folder:** a regular expression that a place's path must match, such as `monorepo-clone-\d+`. An empty pattern keeps every place. An invalid pattern shows its error and keeps every place.
- **The branch:** a clone's branch comes from `.git/HEAD`. A worktree's branch comes from its clone's `.git/worktrees/<name>/HEAD`, when the clone is in the same picked folder.
- **Python in the browser:** Pyodide (pinned in the import map, with a hash per module) runs the runner from `pskill_runner.zip`. `micropip` installs `ruamel.yaml`, which Pyodide does not ship. The first visit downloads about 15 MB.
- **A copy of each project:** `hosted.js` copies what a request reads into Pyodide's memory: `config.yaml`, every file of `skills/` and `agents/` (`folder_hash` counts every file), each run's `run.json`, and the whole folder of the open run. It skips a file whose size and time did not change, and a finished run after its last copy. It copies the same part of a project at most once a second.
- **Edits reach the folder:** after a save, a cancel, or a delete, `hosted.js` writes each file that Python changed back to the picked folder, and removes each file that Python deleted (a deleted run removes its whole folder). Before a cancel, it copies the run's newest files. If the browser refuses, the page says so and reads the folder again.
- **The site:** `pskill_runner/hosted_site.py` builds it (`viewer/` plus `pskill_runner.zip`). `.github/workflows/pages.yml` publishes it on every push to `main`.

---

## 15. CLI

Every command: `uv run .pskill/pskill.py <command>`. Exit codes: 0 ok, 1 usage error, 2 validation error, 3 internal error.

| Command | Purpose |
|---|---|
| `init [--from <source>]` | Create `.pskill/` with only what a project commits: the pinned `pskill.py`, `config.yaml`, `.gitignore` (`runs/`, `__pycache__/`), and `skills/`. Put the release in the cache, then run `sync`. A source is a release `.zip` (a file or a URL). Default: the latest release, pinned by its versioned URL. When `pskill.py` runs alone from a URL, it first downloads the latest release archive (`PSKILL_RELEASE_URL` overrides the URL), so `uv run https://raw.githubusercontent.com/guplem/pskill/main/pskill.py init` installs in one command. |
| `update [--from <source>]` | Move the pin of `.pskill/pskill.py`, put the release in the cache, then run `sync` with the new runner. Default source: the latest release archive. `--from .` in the pskill repository writes the dev pin. Remove the runner files of a vendored install (`VENDORED`, `pskill_runner/`, `viewer/`, `launchers/`, `AUTHORING.md`). Never touch `skills/`, `agents/`, `runs/`, or `config.yaml`. |
| `authoring` | Print `AUTHORING.md`, the guide for agents that write skills. |
| `list` | Skills: id, invocation, description. |
| `start <skill> [--input k=v]... [--inputs -] [--mode m] [--harness h]` | Validate the skill (errors 1 to 16 only; a stale stub never blocks a run), create the run, and print the first packet. Values convert to the declared input types, as for submissions. `--inputs -` reads YAML inputs from stdin, for free text. |
| `current [<run>]` | Print the current packet. No state change. |
| `task <run> <n>` | Print the full prompt of task `<n>` of the current parallel block. A subagent runs it first. No state change. |
| `submit <run> [--task <n>] [--file <path>]` | Read the answer (YAML) from stdin, or from the file with `--file` (a long answer), validate it, advance, and print the next packet. One call per block. |
| `pause <run>` / `resume <run>` / `cancel <run>` | Lifecycle control. |
| `delete <run>` | Delete the folder of a finished run, for cleanup. An unfinished run must be cancelled first. The id must name a folder right inside `runs/`. |
| `runs [--open]` | List runs. |
| `validate [<skill>]` | Section 11. |
| `test [<skill>]` | Section 12. |
| `sync [--check]` | Write stubs and hooks. `--check` only reports differences. |
| `view` | Start the viewer. |
| `hook stop\|session-start --harness <h>` | Internal. The harness calls it. |

Run ids look like `r-YYYYMMDD-HHMM-<4 hex>`.

### 15.1 `AUTHORING.md` (the guide for agents that write skills; `pskill authoring` prints it)

Keep it under 150 lines. It covers:
1. **When to write a programmatic skill:** an ordered workflow with branches, loops, human decisions, or nested skills. Reference and rules content stays a normal prose skill.
2. **The six block types,** with one short example each.
3. **Edges, `max_visits`, and `{{ }}`,** including the "exactly one `{{ }}` keeps its type" rule.
4. **Instructions:** only the block's own job, no return format, and no rules about order. Inline text for one or two lines; a `.md` file for anything longer.
5. **How to port a prose skill:**
   - Every "do X before Y" becomes an edge.
   - Every mode flag becomes an input, or disappears (D6).
   - Every "at most N rounds" becomes `max_visits`.
   - Every mechanical check becomes a `script`.
   - Every file-heading contract between skills becomes typed outputs.
6. **The edit loop,** in this order:
   1. Write or change a test case.
   2. Run `pskill test` and see it fail.
   3. Edit the skill.
   4. Run `pskill test` and `pskill validate` until both pass.
   5. Run `pskill sync`.

---

## 16. Development method: red-green, always

Build every behavior test first:
1. **Red.** Write one small test for the next behavior. Run it. See it fail, for the expected reason.
2. **Green.** Write the least code that makes it pass. Run the full suite.
3. **Refactor.** Clean up while every test stays green.

Rules:
- No production code without a failing test that asks for it. This covers the runner, the viewer server, adapters, sync, and the example skills.
- Every bug fix starts with a test that reproduces the bug.
- Skill authors follow the same loop. First write the `tests/<case>.yaml` with the expected path. See `pskill test` fail. Then change `skill.yaml` until it passes. `AUTHORING.md` teaches this.
- Commit each test together with the code that makes it pass.
- Adapter behavior that depends on a harness (hook JSON formats, stub folders) gets tests against saved sample payloads in `tests/fixtures/<harness>/`. Save each sample from the harness docs, or from a real run, during the VERIFY step.

**Test layers:**

| Layer | Tool | Covers |
|---|---|---|
| Unit | pytest | Loader, field maps, computed values, validator rules, engine rules, packet text, adapters, sync, the viewer's data building. |
| CLI | pytest + `subprocess` | Commands, exit codes, and a full run through `start` and `submit` against fixture skills. |
| Skill | `pskill test` | The example skills' paths. |
| Manual acceptance | a checklist in the milestone | A real run in Claude Code and Codex, and one run through `generic`. It supplements the automated tests and never replaces them. |

**CI:** GitHub Actions on `ubuntu-latest`, `macos-latest`, and `windows-latest`. Steps: install uv, then `ruff`, `mypy --strict`, `pytest`, and `pskill validate` plus `pskill test` on the example skills in `.pskill/skills/`.

---

## 17. Milestones

Each milestone starts with the listed failing tests and ends with green CI on the three operating systems.

| # | Milestone | First red tests | Done when |
|---|---|---|---|
| M1 | Core engine | Load a skill; reject an unknown block type; `task` then `end`; a choice map picks the edge; a condition list picks the first match; an invalid submission is rejected with errors; a YAML answer with `choice: no` and a multi-line `plan` converts by schema; `submit` with no stdin fails in under 10 s; retries run out and the run pauses; `max_visits` redirects; `history` keeps every visit | A 5-block fixture skill runs to the end with `start` and `submit`. |
| M2 | All blocks + tests | A `script` result lands in `steps`; a failing script pauses; a script reads its `input` on stdin; a `call` runs the child and returns `status` and `outputs`; a child cannot read the caller's steps; `parallel` completes only after all tasks; one-by-one mode; the lock holds under concurrent submits; the `pskill test` answer queue and path check | The three proof skills validate, and all their test cases pass. |
| M3 | Claude Code | The stub text; `sync` is idempotent; `sync` keeps foreign hooks, foreign permission rules, and hand-written skills; `sync` adds the one allow rule; the Stop hook blocks an `active` run and gives up after 3 blocks; the session-start hook rewrites a stale stub, skips a broken skill with a warning, and lists open runs; `init` and `update` with a hash check | In the `guplem/pskill` repository, `implement-issue` runs in real Claude Code from trigger to end on a real issue. An early stop gets blocked. A new session resumes the run. |
| M4 | Codex + generic check | Codex: detection, `.codex/hooks.json` merge that keeps foreign hooks, Stop and session-start responses from fixtures, subagent wording, the `agents/openai.yaml` sidecar for `manual` skills. Generic: an unknown environment falls back to `generic`; its packets name no harness tool | In the same repository, `implement-issue` runs in real Codex from trigger to end, with an early stop blocked. A manual run in Gemini CLI or Cursor through `generic` also reaches the end. The trace shows the right harness each time. |
| M5 | Viewer | Canvas marks; the page still shows the steps when Mermaid fails to load; timeline rows; summary numbers; the API returns 404 for an unknown run; the server binds only to 127.0.0.1 | A live run updates within 2 s. A finished run can be stepped through. |
| M6 | Docs + release | A test that builds the release archive and runs `init --from <archive>` into a temp project | A merge to `main` that raises the runner version makes CI tag it and publish `pskill.zip` as a release asset. A new project gets from zero to a first run with only the README. The first install command is `uv run https://raw.githubusercontent.com/guplem/pskill/main/pskill.py init` (VERIFY that `uv run` accepts a script URL). |

---

## 18. Removed on purpose (do not add back)

Each of these was in an earlier draft. Each one added complexity for little user value. Keep them out of the MVP. A few return as backlog issues (18.1), and only through their own design.

| Removed | Use instead |
|---|---|
| Variables and `set` on edges | `steps` (latest output) and `history` (all outputs) |
| A `route` block | Conditional `entry`, and conditional `next` on any block |
| A separate `question` block | `decision` with no `choices` |
| Named reusable types | YAML anchors under `x-` keys |
| A static task list in a parallel block | `for_each` over a YAML list |
| `for_each` on `call` | A loop through edges, with `history` |
| `on_error` per block | Retries (global, or the block's own `retries`), then pause, then `resume` |
| `ok_exit_codes` | Exit 0 plus JSON output |
| Child runs with their own ids and folders | One run with a call stack |
| A UserPromptSubmit hook | Two hooks, bound by harness, checkout, and session (L4) |
| A managed block inside `AGENTS.md` | `AUTHORING.md`, and one line in the README that tells users to point to it |
| `--format json`, `show`, `graph`, `schema`, `retry` commands | The viewer, `current`, and `resume` |
| Real scripts and real child calls in skill tests | Mocks; each skill has its own tests |
| Static-flow warnings ("a step can run before its source") | The runtime error for missing values, plus skill tests |
| Bare expressions without braces (`when: "a == b"`, `result: "'text'"`) | One syntax: `{{ }}` means computed, everything else is plain text |
| Submissions through an `outbox/` folder, JSON-only answers, `--inputs-file` | One `submit` call with a literal YAML block on stdin. `submit --file` is back since 0.31.0, only for a long answer (D16). |
| Harness agent files (`.claude/agents/`, `.codex/agents/`) as subagents | pskill agents in `.pskill/agents/`, versioned with the skills |
| Token counts per block | Durations only. Harness session files are private formats that change without notice. |
| Mermaid copied into every project (about 3 MB) | A pinned CDN copy; the viewer works without the graph when offline |
| A hook that runs `sync` after each file edit, and git hooks | The session-start hook refreshes stubs; `AUTHORING.md` tells the agent to run `sync` after an edit; CI fails on a stale stub |
| An analytics screen | A summary row on the Runs screen |
| The `to_file` filter (a long value as a file path in a script argument) | A script's `input`, on stdin |
| `PSKILL_STATE_FILE` (a script reads a copy of the whole run state) | A script's `input`: the skill names each value that the script gets |

### 18.1 Backlog: future issues

Each item below exists as a GitHub issue with the label `future` (guplem/pskill issues #1 to #13). Each issue states the idea, why it waits, and a link to this section. Open a new `future` issue for any new postponed idea. None of them is promised. Each one needs its own design and must pass principle 1 (simplicity).

| Issue title | Why it waits |
|---|---|
| Gemini CLI adapter (hooks, subagents) | `generic` already runs skills there. |
| Cursor adapter (hooks, subagents) | Same. |
| `pskill eval`: run one skill headless in several harnesses on the same inputs and compare the traces | Needs the runner to launch agents (the opposite direction of D1). |
| Export traces to OpenTelemetry, and upload runs to Galtea | The trace format must settle first. |
| MCP front door (the same commands as MCP tools) | The CLI works everywhere. |
| `parallel` blocks that run whole skills per item | Tasks are single jobs in the MVP. |
| Token counts per block | Harness session files are private formats. |
| Replay from a chosen block (fork a run) | Step-through playback covers the MVP need. |
| Up-front check of required tools and connectors | A missing tool fails its block, then the run pauses. |
| Tool limits and model choice for a block or a pskill agent | Harness-specific; pskill agents are prompt-only in the MVP. |
| `implement-issue`: split big issues into stacked PRs, worktree subagents | The example version makes one PR. (`resolve-pr-feedback` now replies to review threads.) |

---

## 19. Prior art (borrow ideas, do not rebuild)

| Project | Borrow | Difference |
|---|---|---|
| Agent Skills standard (agentskills.io) | Stub frontmatter rules | It has no workflow model. |
| WorkRail (an MCP server) | One block at a time, hidden future blocks | Tiny. No subagents, hooks, or typed outputs. |
| Spec Kit workflows (GitHub) | Gates, loops, fan-out; a run folder with state and a JSONL log | Its runtime drives the agent. No nesting yet. |
| Archon v2 | YAML node types | It replaces the live session. |
| acpx flows | The run bundle and the timeline viewer | Flows defined in code. |
| Claude Code workflows | An output schema per agent | Claude only. No human input mid-run. |
| BMAD step files | One step file at a time | Prompts only. Nothing enforces it. |
