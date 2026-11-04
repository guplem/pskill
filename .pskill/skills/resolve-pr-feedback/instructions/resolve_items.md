Resolve the {{ steps.collect_items.json.count }} items of pull request #{{ inputs.pr }}, one after another, in this order:

{% for item in steps.collect_items.json.queue %}{{ loop.index }}. {% if item.kind == 'finding' %}**A finding of the {{ item.reviewer | default('review', true) }} reviewer:** [{{ item.severity }}] `{{ item.file }}:{{ item.line }}` {{ item.title }}: {{ item.summary }} (quote: `{{ item.quote }}`)
{% else %}**Comment {{ item.id }}** ({{ item.comment_kind }}, by {{ item.author }}{% if item.path %}, `{{ item.path }}:{{ item.line }}`{% endif %}): {{ item.body }}
{% endif %}{% endfor %}
Give one decision per item in `decisions`, in the same order. When you run out of time, stop after a whole item: a later run resolves the rest.

**The spec:** the pull request description and its linked issue{% if steps.checkout.outputs.plan_file %}, and the plan file `{{ steps.checkout.outputs.plan_file }}`. Read its last version with `git show $(git log -1 --format=%H --diff-filter=AM HEAD -- {{ steps.checkout.outputs.plan_file }}):{{ steps.checkout.outputs.plan_file }}`: the plan file is removed from the branch before the pull request is ready{% endif %}.

For each item:

1. **Check it** in the code. Read the code around it. A reviewer can be wrong. Findings on the same file and line come one after another: when this one is the same problem as an earlier item, give it the verdict of that item and name it.
{% set scope_sha = inputs.scope_sha or steps.checkout.outputs.head_sha %}2. **Fix it** when `{{ skill.dir }}/references/finding-acceptance.md` accepts it. The base branch is `{{ steps.checkout.outputs.base }}`, and the scope commit is `{{ scope_sha }}`.

   **How to fix:** follow the `AGENTS.md` and `CLAUDE.md` files of the touched code.
   - Plan the fix before you change code:
     - Read the context that the fix needs.
     - Find how the codebase already solves the same problem, and reuse that pattern. Do not make a new one.
     - List the cases that the fix touches: each value of an input, a save that fails half way, and the other places that share the code. Make the fix right in each case.
   - Make the fix that adds the least new code.
   - When the code breaks a written rule (a recorded decision, an `AGENTS.md` rule), change the code. Change the rule only when the rule itself is wrong.
   - Write a failing test first when the fix changes behavior.
   - Run the fast local checks that the `AGENTS.md`, `CLAUDE.md`, or README files name for the touched code. Run formatters only on the files that you changed.
   - Before you commit, check the fix's own diff (`git diff`): each branch that it adds has a test, no comment, docstring, or doc that it touches says something that is now false, and no import, variable, or helper that it leaves is unused. Fix what you find in the same commit.
   - Commit the fix as a new commit, give its short hash in `commit`, and push with `git push origin HEAD:{{ steps.checkout.outputs.branch }}`. Push to this branch, not to the session's `claude/` branch. Then check that the commit reached the remote: after `git fetch origin {{ steps.checkout.outputs.branch }}`, `git branch -r --contains <hash>` lists `origin/{{ steps.checkout.outputs.branch }}`. Never amend a pushed commit.
3. **Dismiss it** when the finding acceptance rules reject it. Give the reason in one sentence.
   - Dismiss a partial fix too: say what you fixed, and why you left the rest. The next reviewers see it.

A script posts the `reason` of each comment as its reply, so write it for the comment's author. Dismiss a comment that asks for nothing (praise, a notice) with a short reply. Answer a question in `reason`, and dismiss it, unless the answer shows a problem to fix. When a person (not a bot) asks for a change that step 2 leaves out, make it when it serves the goal of the pull request. Otherwise, change nothing: dismiss it, and suggest a separate issue in the reply.

When a fix makes a sentence of the pull request description false, rewrite that sentence. Read the description with `gh api repos/{owner}/{repo}/pulls/{{ inputs.pr }} --jq .body`. Write the new one to `<file>` in a temporary folder outside the repository. Then run `uv run {{ skill.dir }}/scripts/publish_body.py` with `{"pr": {{ inputs.pr }}, "body_file": "<file>"}` on stdin.
