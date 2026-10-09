Decide whether a human must check pull request #{{ steps.open_draft_pr.json.pr_number }} before the merge. When yes, add the label: `gh pr edit {{ steps.open_draft_pr.json.pr_number }} --add-label waiting-for-human-review`. When the repository has no such label yet, create it first: `gh label create waiting-for-human-review --color FBCA04 --description "A human must review this before the merge"`.

Add **`waiting-for-human-review`** when any of these is true:
- The change is risky or large: a data migration, authentication or permissions, payments, a public contract (an API, an SDK, a command, a file format), a recorded decision or a new architecture pattern, a CI workflow, or many areas at once.
- The change alters what a user sees. A human must check it visually.
{% if not steps.implement_step.done %}- The build ended at its visit cap after {{ history.implement_step | length }} red-green cycles, so plan steps can be missing.
{% endif %}{% if steps.get_ci_green.outputs.state == 'failed' %}- CI is not green: {{ steps.get_ci_green.outputs.failed_checks | join('; ') }}.
{% endif %}{% if steps.check_unreviewed.json.unreviewed %}- The 5 required-only review rounds are used, and the last fixes had no review.
{% endif %}{% set dismissed = (history.resolve + (history.final_resolve | default([]))) | map(attribute='outputs') | map(attribute='decisions') | sum(start=[]) | selectattr('verdict', 'equalto', 'dismissed') | selectattr('reviewer') | list %}{% if dismissed %}- The resolution dismissed these findings: {% for finding in dismissed %}"{{ finding.title }}" ({{ finding.reason }}){% if not loop.last %}; {% endif %}{% endfor %}. Add the label when a human must confirm one of them.
{% endif %}- CI did not run on the head commit: `gh pr view {{ steps.open_draft_pr.json.pr_number }} --json headRefOid` is not `{{ steps.get_ci_green.outputs.head_sha }}`.

Then update the pull request description.

- **Make it match the branch.** Compare it with `gh pr diff {{ steps.open_draft_pr.json.pr_number }}`. Rewrite each part that is no longer true. Keep each part that is still true.
{% if steps.get_ci_green.outputs.state == 'passed' %}  - CI passed, so tick each CI box in the `## Test plan`.
{% endif %}- **When you add `waiting-for-human-review`,** put this note at the very top. If the description already has the note, replace it.

  ```markdown
  <!-- human-review-note -->
  > [!IMPORTANT]
  > **This pull request needs a human review before it merges.**
  > **Why:** <one or two sentences: the risk or the open decision>
  >
  > **What to check:**
  > - <a decision or a risk to verify, with its file or commit>
  <!-- /human-review-note -->
  ```

  - Keep the note under 80 words, with at most 4 checks, the most important first.
  - Name what a human must decide or verify, not what the code does. Example: "Decide if the new retry limit in `config/defaults.toml` stays."
- **When you do not add `waiting-for-human-review`,** remove the note if there is one.

Write a changed description in one call: `gh api -X PATCH repos/{owner}/{repo}/pulls/{{ steps.open_draft_pr.json.pr_number }} -F body=@<file>`. Write `<file>` in a temporary folder outside the repository. Use capital `-F`: lowercase `-f` posts the text `@<file>` itself.
