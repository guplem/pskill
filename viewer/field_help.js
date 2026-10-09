// The help for each field of skill.yaml that the skill screen shows (SPEC.md sections 5 and 6).
// `short` is the tooltip of the "?" button, so it is plain text. A click on the button opens a dialog
// with `details` (text with `code` in backticks) and `examples` (YAML).
// Keep every text true to SPEC.md: a wrong help text is worse than no help text.

export const FIELD_HELP = {
  type: {
    title: "type",
    short: "What the block does, and who acts: the agent, a person, the runner, or subagents.",
    details: [
      "Every block has exactly one of six types. The type decides which other fields the block can have.",
      "`task`: the agent does work and returns typed output.",
      "`decision`: the agent or the user picks one choice, or the user answers one question.",
      "`parallel`: one task per list item. Each task has its own subagent, and the tasks run at the same time.",
      "`script`: the runner runs a command. No LLM.",
      "`call`: the runner runs another skill and gets its outputs.",
      "`end`: the skill finishes with a status and outputs.",
    ],
    examples: [
      {
        caption: "A task block",
        code: 'write_plan:\n  type: task\n  instruction: Write a plan for {{ inputs.topic }}.\n  output:\n    plan: {type: string, description: "The plan."}\n  next: approve',
      },
      { caption: "An end block", code: "done:\n  type: end\n  status: succeeded" },
    ],
  },
  description: {
    title: "description",
    short: "A short label for the viewer. The agent does not see it.",
    details: [
      "Optional, on every block type. The viewer shows it in the hover hint of the block on the canvas.",
      "Keep it to a few words. The real job of the block goes into its `instruction`.",
    ],
    examples: [{ caption: "A label", code: "check_applies:\n  type: decision\n  description: Does the issue still apply?" }],
  },
  max_visits: {
    title: "max_visits (visits at most)",
    short: "The most times a run may enter this block. It caps a loop.",
    details: [
      "Optional, on every block type. The runner counts how many times a run entered the block.",
      "When a run tries to enter the block again after the last visit, the runner goes to `on_max_visits` instead. With no `on_max_visits`, the block fails and the run pauses.",
      "`pskill validate` warns about a loop that has no cap, because an agent could go round it forever.",
    ],
    examples: [
      {
        caption: "At most 3 plans, then stop",
        code: "write_plan:\n  type: task\n  instruction: instructions/write_plan.md\n  max_visits: 3\n  on_max_visits: stopped\n  output:\n    plan: {type: string, description: \"The plan.\"}\n  next: approve",
      },
    ],
  },
  on_max_visits: {
    title: "on_max_visits",
    short: "The block to go to when this block has no visits left.",
    details: [
      "Optional. It works together with `max_visits`. When a run tries to enter the block after its last visit, the run goes to this block instead.",
      "Without it, the cap is a failure: the run pauses, and the user can resume it or cancel it.",
      "Often it is an `end` block, so the skill stops in a clean way.",
    ],
    examples: [
      {
        caption: "Stop after 5 questions",
        code: "ask_user:\n  type: decision\n  decider: human\n  instruction: Ask the next question.\n  max_visits: 5\n  on_max_visits: stopped\n  next: write_plan",
      },
    ],
  },
  ask_on_max_visits: {
    title: "ask_on_max_visits",
    short: "Whether the run asks \"more rounds, or move on?\" when this block reaches its cap. Default: true.",
    details: [
      "Optional, on a block with `max_visits`. At the cap, the run asks the user (or, in autonomous mode, the agent) whether to run more rounds or to go to `on_max_visits`.",
      "`false` skips the question in both modes: the run goes to `on_max_visits` at once. Use it where a later block covers the work, such as a review loop whose last fixes get later review rounds.",
    ],
    examples: [
      {
        caption: "A safety net that never asks",
        code: "review:\n  type: call\n  skill: review-round\n  max_visits: 7\n  on_max_visits: ready\n  ask_on_max_visits: false\n  next: resolve",
      },
    ],
  },
  autonomous_max_visits: {
    title: "autonomous_max_visits",
    short: "The most visits that the agent may allow in autonomous mode. The default comes from .pskill/config.yaml (150).",
    details: [
      "Optional, on a block with `max_visits`, and at least `max_visits`. It counts every visit of the block, the extra rounds too.",
      "In autonomous mode the agent answers the cap question itself. At this ceiling the run goes to `on_max_visits` with no question. The agent never sees the number.",
      "A user in interactive mode can go past it.",
    ],
    examples: [
      {
        caption: "Ask at 40 cycles; the agent may go on up to 60",
        code: "implement_step:\n  type: task\n  instruction: instructions/implement_step.md\n  max_visits: 40\n  on_max_visits: write_description\n  autonomous_max_visits: 60\n  output:\n    done: {type: boolean, description: \"true when every step is built.\"}\n  next: implement_step",
      },
    ],
  },
  retries: {
    title: "retries",
    short: "How many more tries the block gets after a failure. The default comes from .pskill/config.yaml (2).",
    details: [
      "Optional, on `task`, `decision`, `parallel`, and `script` blocks. It overrides the global `retries` of `.pskill/config.yaml` for this block only.",
      "A retried failure is an answer that does not match the output fields, an agent that says that it cannot complete the block, or a script that fails or times out. The runner shows the packet again with the errors, or runs the script again.",
      "After the last retry, the run pauses. `0` means no second try.",
    ],
    examples: [
      {
        caption: "A flaky network call gets 4 more tries",
        code: 'fetch_pr:\n  type: script\n  run: [gh, pr, view, "{{ inputs.pr }}", --json, title]\n  parse: json\n  retries: 4\n  next: review',
      },
      { caption: "No second try", code: 'publish:\n  type: script\n  run: [gh, release, create, "{{ inputs.tag }}"]\n  retries: 0\n  next: done' },
    ],
  },
  timeout_s: {
    title: "timeout_s (timeout)",
    short: "How many seconds the command may run. The default comes from .pskill/config.yaml (300).",
    details: [
      "Optional, on `script` blocks only. It overrides `script_timeout_s` of `.pskill/config.yaml` for this block.",
      "When the command runs longer, the runner stops it, and the block fails. A timeout is a retried failure, so `retries` applies.",
    ],
    examples: [{ caption: "Give a slow test suite 20 minutes", code: "run_tests:\n  type: script\n  run: [uv, run, pytest]\n  timeout_s: 1200\n  next: report" }],
  },
  decider: {
    title: "decider",
    short: "Who makes the decision: human (the user) or agent.",
    details: [
      "Required on `decision` blocks.",
      "`human` in interactive mode: the agent shows what the instruction says, asks the user exactly one question, and waits for the answer.",
      "`human` in autonomous mode: the agent decides as the user would, and explains why in `rationale`.",
      "`agent`: the agent decides on its own. A decision with `decider: agent` needs `choices`. For free-text work by the agent, use a `task` block.",
    ],
    examples: [
      {
        caption: "The user approves the plan",
        code: "approve:\n  type: decision\n  decider: human\n  instruction: Show the plan and ask whether to go on.\n  choices:\n    go: Start the work.\n    stop: Stop here.\n  next: {go: implement, stop: stopped}",
      },
      {
        caption: "The agent judges",
        code: "judge:\n  type: decision\n  decider: agent\n  instruction: Is this issue a duplicate of {{ steps.search.json.best }}?\n  choices:\n    duplicate: It is a duplicate.\n    new: It is a new issue.\n  next: {duplicate: close, new: create}",
      },
    ],
  },
  choices: {
    title: "choices",
    short: "The options of a decision: a choice id and what it means. With choices, next has one entry per choice.",
    details: [
      "Optional, on `decision` blocks. Write 2 or more. Each entry is a choice id (the key) and its meaning (the text that the decider reads).",
      "With choices, the answer always has `choice` and `rationale`, and `next` maps each choice to where the run goes.",
      "Without choices, the decision is one free-text question, the answer has `answer`, and `next` is one block or an edge list.",
      "A choice id can be any word, also `no` or `yes`: pskill reads only `true` and `false` as booleans.",
    ],
    examples: [
      {
        caption: "Three choices",
        code: "approve_plan:\n  type: decision\n  decider: human\n  instruction: instructions/approve_plan.md\n  choices:\n    approve: Publish the plan and start.\n    change: Revise the plan with the user's feedback.\n    stop: Stop without changes.\n  next: {approve: publish_plan, change: create_plan, stop: stopped}",
      },
      {
        caption: "No choices: a free-text question",
        code: 'ask_user:\n  type: decision\n  decider: human\n  instruction: "Ask the user: {{ steps.write_plan.question }}"\n  next: write_plan',
      },
    ],
  },
  parse: {
    title: "parse",
    short: "How the runner reads the command's output: text (the default) or json.",
    details: [
      "Optional, on `script` blocks. Every script gives `steps.<block>.exit_code`, `.stdout`, and `.stderr`.",
      "With `parse: json`, the runner also reads stdout as JSON, into `steps.<block>.json`. Output that is not valid JSON makes the block fail.",
      "To report a normal \"no\" result, a script exits with 0 and prints JSON that says so. A non-zero exit code is a failure.",
    ],
    examples: [
      {
        caption: "Read a JSON result",
        code: 'read_issue:\n  type: script\n  run: [gh, issue, view, "{{ inputs.issue }}", --json, "number,title,body"]\n  parse: json\n  next: plan\n\n# A later block reads {{ steps.read_issue.json.title }}.',
      },
    ],
  },
  status: {
    title: "status",
    short: "How the skill ends: succeeded, failed, or cancelled.",
    details: [
      "Required on `end` blocks. It is the status of the run, or of the child skill when a `call` block started the skill.",
      "A `call` block gets it as `steps.<call block>.status`, so the parent skill can branch on it.",
      "A `succeeded` end must give every required output of the skill.",
    ],
    examples: [
      {
        caption: "A good end and a stop",
        code: "done:\n  type: end\n  status: succeeded\n  outputs: {result: done}\n\nstopped:\n  type: end\n  status: cancelled\n  outputs: {result: stopped}",
      },
    ],
  },
  skill: {
    title: "skill (child skill)",
    short: "The id of the skill that this call block runs.",
    details: [
      "Required on `call` blocks. The child skill is a folder in `.pskill/skills/`.",
      "The child runs with its own inputs and its own steps. It cannot read the state of the parent skill.",
      "When the child reaches an `end` block, the call block completes with `steps.<call block>.status` and `steps.<call block>.outputs`.",
      "`pskill validate` refuses a call cycle, for example a skill that calls itself.",
    ],
    examples: [
      {
        caption: "Review the pull request with another skill",
        code: "review:\n  type: call\n  skill: review-pr\n  inputs:\n    pr: \"{{ steps.implement.pr_number }}\"\n  next:\n    - when: \"{{ steps.review.status == 'succeeded' }}\"\n      to: done\n    - to: failed",
      },
    ],
  },
  inputs: {
    title: "inputs (to the child skill)",
    short: "The values that the call block gives to the inputs of the child skill.",
    details: [
      "Optional, on `call` blocks. Each key is an input of the child skill. Each value is plain text, a number, a list, or a `{{ }}` computed value.",
      "`pskill validate` checks that the child gets every input that it requires and that has no `default`.",
    ],
    examples: [
      {
        caption: "Pass values on",
        code: 'review:\n  type: call\n  skill: review-pr\n  inputs:\n    pr: "{{ steps.implement.pr_number }}"\n    post_verdict: false\n  next: after_review',
      },
    ],
  },
  agent: {
    title: "agent",
    short: "A file in .pskill/agents/ whose text heads the prompt of each subagent.",
    details: [
      "Optional, on `parallel` blocks. `agent: fact-checker` reads `.pskill/agents/fact-checker.md`. The file is the subagent's role and rules, in Markdown.",
      "The runner puts the text of the file at the top of each task prompt. With no agent, each task gets only its instruction.",
      "It can be a computed value, so each item can have its own agent.",
    ],
    examples: [
      {
        caption: "The same agent for every task",
        code: 'fact_check:\n  type: parallel\n  for_each: "{{ steps.list_docs.json.files }}"\n  agent: fact-checker\n  instruction: Check every claim in {{ item }}.\n  output:\n    wrong_claims: {type: array, items: {type: string}, description: "Each wrong claim."}\n  next: report',
      },
      {
        caption: "An agent per item",
        code: 'research:\n  type: parallel\n  for_each:\n    - {agent: pattern-scout, focus: "Find the closest code."}\n    - {agent: adr-checker, focus: "Find the ADRs."}\n  agent: "{{ item.agent }}"\n  instruction: "{{ item.focus }}"\n  output:\n    report: {type: string, description: "What you found."}\n  next: plan',
      },
    ],
  },
  task_name: {
    title: "task_name (task name)",
    short: "A short name for each task, computed from its item. The viewer and the packet show it instead of \"task 0\".",
    details: [
      "Optional, on `parallel` blocks. It is a `{{ }}` value, computed once per item, like `agent`. `item` is the current list element.",
      "The name heads the task in the packet (`#### Task 0 · security`), and it labels the task's node and chip in the viewer. Keep it to a few words.",
      "A name that is missing, empty, or fails to compute is no name: the task shows as \"task 0\", \"task 1\", and the run goes on.",
      "When the main agent builds the list (for example in a `task` block before the parallel block), give each item a `name` field in that block's `output`, and set `task_name: \"{{ item.name }}\"`. The main agent then names each task.",
    ],
    examples: [
      {
        caption: "A name from a fixed list",
        code: 'research:\n  type: parallel\n  for_each:\n    - {agent: pattern-scout, focus: "Find the closest code."}\n    - {agent: adr-checker, focus: "Find the ADRs."}\n  agent: "{{ item.agent }}"\n  task_name: "{{ item.agent }}"\n  instruction: "{{ item.focus }}"\n  output:\n    report: {type: string, description: "What you found."}\n  next: plan',
      },
      {
        caption: "The main agent names each task",
        code: 'plan_review:\n  type: task\n  instruction: Pick the review angles.\n  output:\n    angles:\n      type: array\n      description: "One entry per review subagent."\n      items:\n        type: object\n        properties:\n          name: {type: string, optional: true, description: \"A name of 2 to 4 words.\"}\n          brief: {type: string}\n  next: analyze\n\nanalyze:\n  type: parallel\n  for_each: "{{ steps.plan_review.angles }}"\n  task_name: "{{ item.name }}"\n  instruction: "{{ item.brief }}"\n  output:\n    findings: {type: array, items: {type: string}, description: "What you found."}\n  next: report',
      },
      { caption: "A file name as the name", code: 'for_each: "{{ steps.list_docs.json.files }}"\ntask_name: "{{ item }}"' },
    ],
  },
  for_each: {
    title: "for_each (for each)",
    short: "The list to split into tasks: one task, and one subagent, per item.",
    details: [
      "Required on `parallel` blocks. It is a YAML list, or one `{{ }}` value that gives a list. So an earlier block can decide how many tasks there are.",
      "In the instruction, in `agent`, and in `task_name`, `item` is the current list element.",
      "The block completes when every task has a valid answer. `steps.<block>.results` is the list of the task outputs, in item order. An empty list completes at once.",
      "Each subagent sees only its own task, never the other tasks.",
    ],
    examples: [
      {
        caption: "A list from a script",
        code: 'check_names:\n  type: parallel\n  for_each: "{{ steps.list_files.json.files }}"\n  instruction: Check the names in {{ item }}.\n  output:\n    problems: {type: array, items: {type: string}, description: "Bad names."}\n  next: report',
      },
      { caption: "A fixed list", code: "for_each:\n  - security\n  - speed\n  - style" },
    ],
  },
  run: {
    title: "run (command)",
    short: "The command that the runner runs, as a list of arguments. No shell, and no LLM.",
    details: [
      "Required on `script` blocks. The runner runs it, never the agent, so it costs no tokens and gives the same result every time.",
      "It is a list of arguments, not a shell line: pipes and `&&` do not work. The runner computes each `{{ }}` argument, then runs the list. This prevents shell injection.",
      "The command runs in the project root. It gets the environment variable `PSKILL_RUN_DIR`.",
      "Put real logic in the skill's `scripts/` folder, and call it. A non-zero exit code is a failure.",
      "Give the script its data through `input`, not through arguments: arguments have a length limit.",
    ],
    examples: [
      { caption: "A command", code: "list_files:\n  type: script\n  run: [git, ls-files]\n  next: check_names" },
      {
        caption: "A script of the skill",
        code: 'verify:\n  type: script\n  run: [uv, run, "{{ skill.dir }}/scripts/verify_quotes.py"]\n  input: {findings: "{{ steps.review.findings }}"}\n  parse: json\n  next: report',
      },
    ],
  },
  input: {
    title: "input (script stdin)",
    short: "The data that the script reads on stdin. The only way to give a script data.",
    details: [
      "Optional, on `script` blocks. The runner computes its `{{ }}` values, then writes it to the script's stdin.",
      "A mapping (or any other value that is not text) goes as one JSON object. A text goes as it is.",
      "Stdin has no length limit, so a long value fits. Without `input`, the script reads an empty stdin.",
      "A Python script reads it with `json.load(sys.stdin)`, and prints its result as JSON on stdout.",
    ],
    examples: [
      {
        caption: "JSON for a script of the skill",
        code: 'input: {pr: "{{ inputs.pr }}", findings: "{{ steps.review.findings }}"}',
      },
      {
        caption: "A text for a command that reads stdin",
        code: 'run: [gh, issue, comment, "{{ inputs.issue }}", --body-file, "-"]\ninput: "{{ steps.write.comment }}"',
      },
    ],
  },
  instruction: {
    title: "instruction",
    short: "What the agent must do in this block. Markdown, with {{ }} values filled in during the run.",
    details: [
      "Required on `task`, `decision`, and `parallel` blocks. A value that ends in `.md` is a file in the skill folder, usually `instructions/<block>.md`. Any other value is the text itself.",
      "Describe only this block's job. Do not describe the answer format: the packet adds it from the output fields. Do not write rules about order: the edges decide the order.",
      "Keep one or two lines inline. Put anything longer in a file.",
      "Values in `{{ }}` are computed: `inputs`, `steps.<block>` (the latest output of a block), `history.<block>` (every output, oldest first), `run`, `skill`, and `item` in a parallel block.",
    ],
    examples: [
      { caption: "Inline", code: 'instruction: "Ask the user: {{ steps.write_plan.question }}"' },
      { caption: "From a file", code: "instruction: instructions/write_plan.md" },
      { caption: "A missing value gets a default", code: "instruction: \"Fix {{ steps.review.finding | default('the open finding') }}.\"" },
    ],
  },
  report: {
    title: "report",
    short: "What the agent tells the user when the run reaches this end.",
    details: [
      "Optional, on `end` blocks. The final packet asks the agent to tell the user this.",
      "It works like an instruction: a value that ends in `.md` is a file in the skill folder, and `{{ }}` values are filled in.",
    ],
    examples: [
      {
        caption: "Inline",
        code: 'done:\n  type: end\n  status: succeeded\n  report: "Tell the user that the pull request is ready: {{ steps.implement.pr_url }}"',
      },
      { caption: "From a file", code: "report: instructions/report_done.md" },
    ],
  },
  output: {
    title: "output",
    short: "The fields that the answer must hold. The runner refuses an answer that does not match.",
    details: [
      "Required on `task` and `parallel` blocks (on a parallel block, it is the output of each task). Optional on a `decision`: extra fields next to the ones that the runner adds (`choice` and `rationale`, or `answer`).",
      "Each key is a field name. The runner checks the type, the `enum`, the required fields, and unknown fields.",
      "Types: `string`, `integer`, `number`, `boolean`, `array` (with `items`), and `object` (with `properties`). A field is required unless it has `optional: true`.",
      "Every top-level field needs a `description`: the agent reads it next to the field.",
      "Later blocks read the answer as `steps.<block>.<field>`.",
    ],
    examples: [
      {
        caption: "Two fields, one of them optional",
        code: 'output:\n  status: {type: string, enum: [finished, question], description: "finished when nothing is open."}\n  question: {type: string, optional: true, description: "The one open question."}',
      },
      {
        caption: "A list of objects",
        code: 'output:\n  findings:\n    type: array\n    description: "Each problem that you found."\n    items:\n      type: object\n      properties:\n        file: {type: string}\n        problem: {type: string}',
      },
    ],
  },
  outputs: {
    title: "outputs (of the skill)",
    short: "The values that the skill gives back when it ends here.",
    details: [
      "Optional, on `end` blocks. Each key is an output of the skill. Each value is plain text, a number, a list, or a `{{ }}` computed value.",
      "A `succeeded` end must give every required output of the skill. A `call` block in a parent skill reads them as `steps.<call block>.outputs`.",
    ],
    examples: [
      {
        caption: "Plain text and a computed value",
        code: 'done:\n  type: end\n  status: succeeded\n  outputs:\n    result: implemented\n    pr_url: "{{ steps.implement.pr_url }}"',
      },
    ],
  },
  next: {
    title: "next",
    short: "Where the run goes after this block. With conditions, the first true edge wins.",
    details: [
      "Required on every block type except `end`. It has three forms.",
      "**One block id:** the run always goes there.",
      "**An edge list:** the runner takes the first edge whose `when` is true. The last edge has no `when`, so one edge always matches.",
      "**A choice map**, on a decision with choices only: one entry per choice. A choice takes one block id, or its own edge list, for when the next block depends on more than the choice.",
      "Put parentheses around a filter inside a comparison: `{{ (steps.review.findings | length) > 0 }}`.",
    ],
    examples: [
      { caption: "Always the same block", code: "next: review" },
      { caption: "Conditions", code: "next:\n  - when: \"{{ steps.write_plan.status == 'question' }}\"\n    to: ask_user\n  - to: approve" },
      { caption: "A choice map", code: "next: {go: implement, stop: stopped}" },
      {
        caption: "A choice with its own conditions",
        code: 'next:\n  fix:\n    - when: "{{ (history.ask_finding | length) < (steps.list_findings.json.findings | length) }}"\n      to: ask_finding\n    - to: fix_findings\n  skip: ask_finding',
      },
    ],
  },
  goal: {
    title: "goal",
    short: "What the whole skill must reach. It goes into every packet that the agent gets.",
    details: [
      "Required, at the top of `skill.yaml`. The agent sees only one block at a time, so the goal keeps the larger aim in view.",
      "Write the result, not the steps.",
    ],
    examples: [{ caption: "A goal", code: "goal: A plan that the user approved, with the names in the changed files checked." }],
  },
  skill_inputs: {
    title: "inputs (of the skill)",
    short: "The values that a run of the skill starts with. Blocks read them as inputs.<name>.",
    details: [
      "A field map at the top of `skill.yaml`. Each field has a `type` and a `description`, and can be `optional` or have a `default`.",
      "Blocks read them as `inputs.<name>`. A `call` block of another skill gives these values in its own `inputs`.",
    ],
    examples: [
      {
        caption: "Two inputs",
        code: 'inputs:\n  topic: {type: string, description: "What the user wants to change."}\n  files: {type: array, items: {type: string}, optional: true, description: "The files to check."}',
      },
    ],
  },
  skill_outputs: {
    title: "outputs (of the skill)",
    short: "The values that the skill gives back. Each end block sets them.",
    details: [
      "A field map at the top of `skill.yaml`. A `succeeded` end block must give every required output.",
      "A `call` block in a parent skill reads them as `steps.<call block>.outputs`.",
    ],
    examples: [{ caption: "One output", code: 'outputs:\n  result: {type: string, enum: [done, stopped], description: "How the skill ended."}' }],
  },
};

// The fact names that skill_view.py sends, and the field of each.
export const FACT_FIELDS = {
  decider: "decider",
  "for each": "for_each",
  agent: "agent",
  "task name": "task_name",
  parse: "parse",
  timeout: "timeout_s",
  skill: "skill",
  status: "status",
  "visits at most": "max_visits",
  "at the cap": "ask_on_max_visits",
  "autonomous ceiling": "autonomous_max_visits",
  retries: "retries",
};
