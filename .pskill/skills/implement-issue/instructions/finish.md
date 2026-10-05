Decide whether a human must look at pull request #{{ steps.open_draft_pr.json.pr_number }} before the merge. When yes, add the label: `gh pr edit {{ steps.open_draft_pr.json.pr_number }} --add-label waiting-for-human-review`. When the repository has no such label yet, create it first: `gh label create waiting-for-human-review --color FBCA04 --description "A human must review this before the merge"`.

Add **`waiting-for-human-review`** when any of these is true:
- The change is risky or large: a data migration, authentication or permissions, payments, a public contract (an API, an SDK, a command, a file format), a recorded decision or a new architecture pattern, a CI workflow, or many areas at once.
- The change alters what a user sees: a human checks it visually.
{% if not steps.implement_step.done %}- The build stopped at its cap of 40 red-green cycles, so steps of the plan can be missing.
{% endif %}{% if steps.get_ci_green.outputs.state == 'failed' %}- CI is not green: {{ steps.get_ci_green.outputs.failed_checks | join('; ') }}.
{% endif %}{% if steps.resolve.outputs.fixed > 0 %}- The review stopped at its round cap, so the last fixes had no review.
{% endif %}{% set dismissed = history.resolve | map(attribute='outputs') | map(attribute='decisions') | sum(start=[]) | selectattr('verdict', 'equalto', 'dismissed') | selectattr('reviewer') | list %}{% if dismissed %}- The resolution dismissed these findings: {% for finding in dismissed %}"{{ finding.title }}" ({{ finding.reason }}){% if not loop.last %}; {% endif %}{% endfor %}. Add the label when a human must confirm one of them.
{% endif %}- CI did not run on the last commit: `gh pr view {{ steps.open_draft_pr.json.pr_number }} --json headRefOid` is not `{{ steps.get_ci_green.outputs.head_sha }}`.
{% if steps.get_ci_green.outputs.state == 'passed' %}
CI passed, so tick each CI box in the `## Test plan` of the pull request description: `gh api -X PATCH repos/{owner}/{repo}/pulls/{{ steps.open_draft_pr.json.pr_number }} -F body=@<file>`. Use capital `-F`: lowercase `-f` posts the text `@<file>` itself.
{% endif %}
