{% set index = history.resolve_item | default([]) | length %}{% set item = steps.collect_items.json.queue[index] %}Resolve item {{ index + 1 }} of {{ steps.collect_items.json.count }} on pull request #{{ inputs.pr }}.

{% if item.kind == 'finding' %}**A finding of the {{ item.reviewer | default('review', true) }} reviewer:** [{{ item.severity }}] `{{ item.file }}:{{ item.line }}` {{ item.title }}: {{ item.summary }} (quote: `{{ item.quote }}`)
{% else %}**Comment {{ item.id }}** ({{ item.comment_kind }}, by {{ item.author }}{% if item.path %}, `{{ item.path }}:{{ item.line }}`{% endif %}): {{ item.body }}
{% endif %}
**The spec:** the pull request description and its linked issue{% if steps.checkout.outputs.plan_file %}, and the plan file `{{ steps.checkout.outputs.plan_file }}`. Read its last version with `git show $(git log -1 --format=%H --diff-filter=AM HEAD -- {{ steps.checkout.outputs.plan_file }}):{{ steps.checkout.outputs.plan_file }}`: the plan file leaves the branch before the pull request is ready{% endif %}.

1. **Check it** in the code. Read the code around it. A reviewer can be wrong.
2. **Fix it** when it is true and belongs in this pull request: it is about the issue or the plan, the changed code, code that the change depends on or makes worse, or code that the plan missed (out of date, or against the architecture). Follow the `AGENTS.md` and `CLAUDE.md` files of the touched code.
   - When the code breaks a written rule (an ADR, an `AGENTS.md` rule), change the code. Change the rule only when the rule itself is wrong.
   - Write a failing test first when the fix changes behavior.
   - Run the fast local checks that the `AGENTS.md`, `CLAUDE.md`, or README files name for the touched code.
   - Commit and push the fix.
3. **Dismiss it** when it is false, only a matter of taste, or about code that this pull request neither touches, depends on, nor makes worse. Give the reason in one sentence.
{% if item.kind == 'comment' %}
A script posts your `reason` as the reply, so write it for {{ item.author }}. A comment that asks for nothing (praise, a notice) is dismissed with a short reply.
{% endif %}
When a fix makes a sentence of the pull request description false, rewrite that sentence: `gh api -X PATCH repos/{owner}/{repo}/pulls/{{ inputs.pr }} -F body=@<file>`. Use capital `-F`: lowercase `-f` posts the text `@<file>` itself.
