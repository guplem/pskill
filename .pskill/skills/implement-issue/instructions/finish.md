{% set limits = (['implement_step'] if not steps.implement_step.done else []) + (['review'] if steps.resolve.outputs.fixed > 0 and (history.resolve | map(attribute='outputs') | selectattr('fixed', 'gt', 0) | list | length) > 6 else []) + (['get_ci_green'] if (history.ready | length) > (history.get_ci_green | length) else []) + (['final_review'] if steps.check_unreviewed.json.unreviewed or ((history.final_review | length) >= 5 and (steps.final_review.outputs.findings | selectattr('severity', 'equalto', 'required') | list)) else []) + (['resolve_items'] if (history.resolve + history.answer_comments + history.final_resolve) | map(attribute='outputs') | selectattr('left') | list else []) %}Decide whether a human must check pull request #{{ steps.open_draft_pr.json.pr_number }} before the merge. When yes, add the label: `gh api repos/{owner}/{repo}/issues/{{ steps.open_draft_pr.json.pr_number }}/labels -f "labels[]=waiting-for-human-review"`. When the repository has no such label yet, create it first: `gh api repos/{owner}/{repo}/labels -f name=waiting-for-human-review -f color=FBCA04 -f description="A human must review this before the merge"`.

Add **`waiting-for-human-review`** when any of these is true:
- The change is risky or large: a data migration, authentication or permissions, payments, a public contract (an API, an SDK, a command, a file format), a recorded decision or a new architecture pattern, a CI workflow, or many areas at once.
- The change alters what a user sees. A human must check it visually.
{% if 'implement_step' in limits %}- The build ended at its visit cap after {{ history.implement_step | length }} red-green cycles, so plan steps can be missing.
{% endif %}{% if 'review' in limits %}- The review loop used its 7 rounds, so the last fixes got only required-only review rounds.
{% endif %}{% if 'get_ci_green' in limits %}- CI ended at its visit cap after {{ history.get_ci_green | length }} rounds, so CI did not run on the head commit.
{% endif %}{% if steps.get_ci_green.outputs.state == 'failed' %}- CI is not green: {{ steps.get_ci_green.outputs.failed_checks | join('; ') }}.
{% endif %}{% if 'final_review' in limits %}{% set open_findings = (steps.final_review.outputs.findings | selectattr('severity', 'equalto', 'required') | map(attribute='title') | list) if (history.final_review | length) >= 5 else [] %}- The required-only review rounds used their 5 rounds, so {% if open_findings %}these required findings stay open, with no fix: {{ open_findings | join('; ') }}{% else %}the last fixes have no review{% endif %}.
{% endif %}{% if 'resolve_items' in limits %}- A feedback round stopped at its item cap, so some findings or comments have no verdict and no reply.
{% endif %}{% set dismissed = (history.resolve + (history.final_resolve | default([]))) | map(attribute='outputs') | map(attribute='decisions') | sum(start=[]) | selectattr('verdict', 'equalto', 'dismissed') | selectattr('reviewer') | list %}{% if dismissed %}- The resolution dismissed these findings: {% for finding in dismissed %}"{{ finding.title }}" ({{ finding.reason }}){% if not loop.last %}; {% endif %}{% endfor %}. Add the label when a human must confirm one of them.
{% endif %}- CI did not run on the head commit: `gh api repos/{owner}/{repo}/pulls/{{ steps.open_draft_pr.json.pr_number }} --jq .head.sha` is not `{{ steps.get_ci_green.outputs.head_sha }}`.

Then update the pull request description. Read it with `gh api repos/{owner}/{repo}/pulls/{{ steps.open_draft_pr.json.pr_number }} --jq .body`.

- **Make it match the branch.** Compare it with `gh pr diff {{ steps.open_draft_pr.json.pr_number }}`. Rewrite each part that is no longer true. Keep each part that is still true.
{% if steps.get_ci_green.outputs.state == 'passed' %}  - CI passed, so tick each CI box in the `## Test plan`.
{% endif %}{% if limits %}- **A limit cut work short (the reasons above that start with a limit).** Put this warning at the very top, above any other note, with one line per limit whose skipped work matters. If the description already has it, replace it.

  ```markdown
  <!-- incomplete-note -->
  > [!WARNING]
  > **Incomplete:** <one line per limit: what was skipped, and what is still open>
  <!-- /incomplete-note -->
  ```

  - Leave out a limit whose skipped work does not matter, for example CI that did not run only on a commit that changed a code comment. Say why in `reasons`. With no limit left, add no warning.
  - Keep the warning even when the user chose to move on at a cap: other reviewers did not see that choice.
{% endif %}- **When you add `waiting-for-human-review`,** put this note at the very top, below an Incomplete warning. If the description already has the note, replace it.

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
- **When you do not add `waiting-for-human-review`,** remove the note if there is one. Remove an Incomplete warning that no longer applies.

Write the description to `<file>` in a temporary folder outside the repository. Then run `uv run {{ skill.dir }}/scripts/publish_body.py` with `{"pr": {{ steps.open_draft_pr.json.pr_number }}, "body_file": "<file>"}` on stdin. It writes the description only when it changed.
