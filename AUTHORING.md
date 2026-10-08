# Writing programmatic skills

A programmatic skill is a graph of typed blocks in `.pskill/skills/<skill-id>/skill.yaml`. The pskill runner executes it one block at a time: it gives the agent one instruction, checks the typed answer, and picks the next block. The agent never sees the whole workflow.

## When to write one

- **Write a programmatic skill** for an ordered workflow: steps in a fixed order, branches, loops, questions to the user, or calls to other skills.
- **Keep a normal prose skill** (`SKILL.md`) for reference and rules content, such as "how we write commits".

## The files of a skill

```text
.pskill/skills/<skill-id>/
├── skill.yaml              # the graph
├── instructions/<block>.md # the prose of the longer blocks
├── scripts/                # helper scripts that script blocks run
└── tests/<case>.yaml       # test cases for `pskill test`
```

## A complete example

This skill uses all six block types. `tests/test_authoring_example.py` checks that it stays valid.

```yaml
schema: pskill/v1
id: my-skill                  # equals the folder name
description: >-               # what harnesses show to decide when to use the skill (max 1024 chars)
  Plan and check a change. Use when the user asks to plan a change.
goal: A plan that the user approved, with the names in the changed files checked.
invocation: auto              # auto (default) | manual (only the user starts it) | internal (only call blocks; `pskill start` refuses it)
inputs:
  topic: {type: string, description: "What the user wants to change."}
  files: {type: array, items: {type: string}, description: "The files to check."}
outputs:
  result: {type: string, enum: [done, stopped], description: "How the skill ended."}
entry: write_plan
blocks:
  write_plan:                 # task: the agent does work and returns typed output
    type: task
    instruction: "Write a plan for {{ inputs.topic }}. {% for qa in history.ask_user %}Earlier: {{ qa.answer }} {% endfor %}"
    max_visits: 5
    on_max_visits: stopped
    output:
      status: {type: string, enum: [finished, question], description: "finished when nothing is open."}
      plan: {type: string, description: "The plan so far."}
      question: {type: string, optional: true, description: "The one open question."}
    next:
      - when: "{{ steps.write_plan.status == 'question' }}"
        to: ask_user
      - to: approve

  ask_user:                   # decision without choices: one free-text question to the user
    type: decision
    decider: human
    instruction: "Ask the user: {{ steps.write_plan.question }}"
    next: write_plan

  approve:                    # decision with choices: the next block follows the choice
    type: decision
    decider: human            # human: the user decides (the agent, in autonomous mode) | agent
    instruction: "Show the plan and ask whether to go on: {{ steps.write_plan.plan }}"
    choices:
      go: Start the checks.
      stop: Stop here.
    next: {go: list_files, stop: stopped}

  list_files:                 # script: the runner runs the command (no shell, no LLM)
    type: script
    run: [git, ls-files]
    next: check_names

  check_names:                # parallel: one subagent task per item, joined into steps.check_names.results
    type: parallel
    for_each: "{{ inputs.files }}"
    task_name: "{{ item }}"   # optional: the name of each task in the viewer
    instruction: "Check the names in {{ item }}."
    output:
      problems: {type: array, items: {type: string}, description: "Bad names."}
    next: review

  review:                     # call: run another skill; steps.review.status and steps.review.outputs
    type: call
    skill: review-names
    inputs: {files: "{{ inputs.files }}"}
    next: done

  done:                       # end: the run (or the child skill) ends with a status and outputs
    type: end
    status: succeeded         # succeeded | failed | cancelled
    outputs: {result: done}
    report: "Tell the user what the checks found."

  stopped:
    type: end
    status: cancelled
    outputs: {result: stopped}
```

- Every top-level field of `inputs`, `outputs`, and each block `output` needs a `description`.
- Field types: `string`, `integer`, `number`, `boolean`, `array` (with `items`), `object` (with `properties`). A field is required unless `optional: true`.
- Make an input required only when the skill cannot start without it: the stub tells the agent to ask the user for each missing one. Give an optional input a `default` for the common case. A calling skill passes another value where it needs one.
- A `parallel` block may name `agent: <name>`: the text of `.pskill/agents/<name>.md` then heads each task's prompt.
- A `parallel` block may set `task_name`, a `{{ }}` value per item, to name each task in the packet and the viewer. Without a name, a task shows as "task 0". When a block of the main agent builds the list, add an optional `name` field to its items and set `task_name: "{{ item.name }}"`.
- In a `for_each` written as a YAML list, an item may have a `when`: the item starts a task only when its `when` is true. The task's `item` has no `when` key. The viewer lists the skipped items with their condition. Use it for a fixed set of subagents where each one runs only when it is needed:
  ```yaml
  for_each:
    - {name: docs, brief: "Find stale docs."}
    - {name: api, brief: "Check the API rules.", when: "{{ steps.read.json.paths | select('matches', '^api/') | list }}"}
  ```
- A `script` gives `steps.<id>.exit_code`, `.stdout`, and `.stderr`, plus `.json` with `parse: json`.
- A `script` gets its data only through `input`, on stdin: a mapping goes as one JSON object, a text as it is. Stdin has no length limit. A Python script reads `json.load(sys.stdin)` and prints JSON:
  ```yaml
  verify:
    type: script
    run: [uv, run, "{{ skill.dir }}/scripts/verify_quotes.py"]
    input: {pr: "{{ inputs.pr }}", findings: "{{ steps.review.findings }}"}
    parse: json
    next: report
  ```
- A failed block tries again `retries` times (2 by default, set in `.pskill/config.yaml`), then the run pauses. A `task`, `decision`, `parallel`, or `script` block can set its own `retries: 0` (no second try) or more. A `script` can set its own `timeout_s: 60` (300 by default).

## Edges and loops

- `next: target` always goes to `target`.
- A list of edges takes the first one whose `when` is true. The last edge has no `when`:
  ```yaml
  next:
    - when: "{{ steps.write_plan.status == 'question' }}"
      to: ask_user
    - to: approve
  ```
- A decision with choices uses a map: one entry per choice, and no other entries. A choice can take one block, or an edge list for when the next block depends on more than the choice.
- **A per-item loop** asks about one item per visit and keeps the question buttons. Each choice goes back to the same block until every item has an answer:
  ```yaml
  ask_finding:
    type: decision
    decider: human
    instruction: "Show finding {{ (history.ask_finding | length) + 1 }} and ask what to do with it."
    max_visits: 50
    choices:
      fix: Fix this finding.
      skip: Leave this finding.
    next:
      fix:
        - when: "{{ (history.ask_finding | length) < (steps.list_findings.json.findings | length) }}"
          to: ask_finding
        - to: fix_findings
      skip:
        - when: "{{ (history.ask_finding | length) < (steps.list_findings.json.findings | length) }}"
          to: ask_finding
        - to: fix_findings
  ```
  While the block is open, `history.ask_finding` holds the earlier answers only. After the answer, it holds this one too, so the edges count every answer.
  `history` spans the whole run of the skill, not one pass through the loop. So when an earlier block can lead back into the loop (a second review round), the count starts at the first pass's answers and reads past the new list. Put such a loop in its own `internal` skill and run it with a `call` block: each call starts with an empty `history`.
- `max_visits: 3` with `on_max_visits: done` caps a loop. Without `on_max_visits`, reaching the cap pauses the run. The validator warns about a loop with no cap.

## Computed values

- Anything inside `{{ }}` is computed. Everything else is plain text, so `result: done` needs no quotes.
- A value that is exactly one `{{ ... }}` keeps its type (a number, a list, true or false).
- Names you can read: `inputs`, `steps.<block>` (the latest output), `history.<block>` (every output in this run of the skill, oldest first), `run` (`id`, `mode`, `harness`, `dir`), `skill` (`id`, `dir`), and `item` inside a parallel block.
- A value from a block that has not run is missing. You can compare it (the result is false) or replace it: `{{ steps.x.value | default('none') }}`. Printing a missing value fails the run on purpose.
- Put parentheses around a filter inside a comparison: `{{ (steps.review.outputs.findings | length) > 0 }}`.
- `matches` tests text against a regular expression, anywhere in the text: `{{ path is matches('^api/') }}`, or `{{ paths | select('matches', '[.]ts$') | list }}`. Anchor the pattern with `^` and `$`.

## Writing instructions

- Keep a skill self-contained. Its instructions, briefs, scripts, and agent roles live under `.pskill/`. Never send the agent to another skill, or to a subagent role outside `.pskill/agents/`. Copy what the skill needs into its own folder instead. The project's own rules (`AGENTS.md`, recorded decisions) are fine to read.
- An instruction is one block's job only. Do not describe the return format: the packet adds it from `output`.
- Do not write rules about order ("never skip", "before X do Y"): the graph enforces order.
- One or two lines can stay inline in `skill.yaml`. Put anything longer in `instructions/<block>.md`.
- Split a block where agents deviated in real runs (skipped a check, ran ahead). Keep a block whole where the work has no fixed order.

## Porting a prose skill

| In the prose skill | In the programmatic skill |
|---|---|
| "Do X before Y", "never skip Z" | An edge |
| A mode flag (`--auto`, `--no-verdict`) | An input and a condition, or nothing: every skill can run in autonomous mode |
| "At most N rounds" | `max_visits` |
| A mechanical check (a quote is in the diff, a file exists) | A `script` block |
| A file whose headings another skill reads | Typed `outputs` of a skill, read through a `call` block |

## The edit loop (red-green)

1. Write or change a test case in `tests/<case>.yaml`: the answers per block, the recorded script and call results, and the expected `path`, `status`, and `outputs`. Inside `{ }`, put a value with `?` or `: ` in quotes: `{question: "Which database?"}`. Without quotes, YAML fails to parse the case.
2. Run `uv run .pskill/pskill.py test <skill-id>` and see it fail.
3. Edit the skill.
4. Run `uv run .pskill/pskill.py test <skill-id>` and `uv run .pskill/pskill.py validate` until both pass.
5. Run `uv run .pskill/pskill.py sync`, so the harnesses see the new description and inputs.
