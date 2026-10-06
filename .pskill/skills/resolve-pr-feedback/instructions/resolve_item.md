{% set index = history.resolve_item | default([]) | length %}{% set item = steps.collect_items.json.queue[index] %}Resolve item {{ index + 1 }} of {{ steps.collect_items.json.count }} on pull request #{{ inputs.pr }}.

{% if item.kind == 'finding' %}**A finding of the {{ item.reviewer | default('review', true) }} reviewer:** [{{ item.severity }}] `{{ item.file }}:{{ item.line }}` {{ item.title }}: {{ item.summary }} (quote: `{{ item.quote }}`)
{% else %}**Comment {{ item.id }}** ({{ item.comment_kind }}, by {{ item.author }}{% if item.path %}, `{{ item.path }}:{{ item.line }}`{% endif %}): {{ item.body }}
{% endif %}
**The spec:** the pull request description and its linked issue{% if steps.checkout.outputs.plan_file %}, and the plan file `{{ steps.checkout.outputs.plan_file }}`. Read its last version with `git show $(git log -1 --format=%H --diff-filter=AM HEAD -- {{ steps.checkout.outputs.plan_file }}):{{ steps.checkout.outputs.plan_file }}`: the plan file is removed from the branch before the pull request is ready{% endif %}.

1. **Check it** in the code. Read the code around it. A reviewer can be wrong.
{% set scope_sha = inputs.scope_sha or steps.checkout.outputs.head_sha %}2. **Fix it** when it is true and belongs in this pull request: it is about the issue or the plan, or about a line that the pull request added, even when the fix is in another place. An older problem belongs here only in one of these cases:
   - The new code runs the broken part, or the problem stops the pull request from reaching its goal. Fix it, wherever the fix goes.
   - It is inside the scope, and its fix stays inside the same function, section, or block. The scope is the code that `git diff origin/{{ steps.checkout.outputs.base }}...{{ scope_sha }}` changes. For each changed line, the scope is the innermost function, method, or constructor around it. For a changed line outside any function, it is the section or block of that line.
   - The new code copies an old pattern from code around it, in a file or class that the pull request changes or that its plan names. Change that old code to the new pattern.

   **How to fix:** follow the `AGENTS.md` and `CLAUDE.md` files of the touched code.
   - Read the context that the fix needs first. Then make the fix that adds the least new code.
   - When the code breaks a written rule (a recorded decision, an `AGENTS.md` rule), change the code. Change the rule only when the rule itself is wrong.
   - Write a failing test first when the fix changes behavior.
   - Run the fast local checks that the `AGENTS.md`, `CLAUDE.md`, or README files name for the touched code. Run formatters only on the files that you changed.
   - Commit and push the fix as a new commit. Never amend a pushed commit.
3. **Dismiss it** when it is false, only a matter of taste, or an older problem that step 2 leaves out. Give the reason in one sentence.
   - Dismiss a partial fix too: say what you fixed, and why you left the rest. The next reviewers see it.
{% if item.kind == 'comment' %}
A script posts your `reason` as the reply, so write it for {{ item.author }}. Dismiss a comment that asks for nothing (praise, a notice) with a short reply. Answer a question in `reason`, and dismiss it, unless the answer shows a problem to fix. When a person (not a bot) asks for a change that step 2 leaves out, make it when it serves the goal of the pull request. Otherwise, change nothing: dismiss it, and suggest a separate issue in the reply.
{% endif %}
When a fix makes a sentence of the pull request description false, rewrite that sentence: `gh api -X PATCH repos/{owner}/{repo}/pulls/{{ inputs.pr }} -F body=@<file>`. Write `<file>` in a temporary folder outside the repository. Use capital `-F`: lowercase `-f` posts the text `@<file>` itself.
