Review pull request #{{ inputs.pr }} as the **{{ item.name }}** reviewer. Your angle: {{ item.focus }}

- **The head commit:** `{{ steps.checkout.outputs.head_sha }}`. Read the diff with `git diff origin/{{ steps.checkout.outputs.base }}...{{ steps.checkout.outputs.head_sha }}`. Read each changed file in full at the head commit: `git show {{ steps.checkout.outputs.head_sha }}:<path>`.
{% if steps.checkout.outputs.plan_file %}- **The spec:** the linked issue, and the plan file `{{ steps.checkout.outputs.plan_file }}`. Find the commit of its last version with `git log -1 --format=%H --diff-filter=AM {{ steps.checkout.outputs.head_sha }} -- {{ steps.checkout.outputs.plan_file }}`. Read it with `git show <commit>:{{ steps.checkout.outputs.plan_file }}`. Do not review the plan file itself: it leaves the branch before the pull request is ready.
{% else %}- **The spec:** the pull request description (`gh pr view {{ inputs.pr }}`) and its linked issue.
{% endif %}- **What to review:** the issue and the changed code first, against the `AGENTS.md` and `CLAUDE.md` files of the touched code. Also report a problem outside the changed code when the change depends on it or makes it worse, or when the plan missed it.
- **You change no file.** Do not run the full test suites, linters, or type checks that CI runs. Run any other script or test that your review needs, for example a throwaway script in a scratch folder that shows how the code behaves.
{% set mine = inputs.dismissed | default([]) | selectattr('reviewer', 'equalto', item.name) | list %}{% if mine %}- **Already dismissed:** earlier rounds dismissed these findings of yours. Do not report them again, unless you have new evidence.
{% for finding in mine %}  - "{{ finding.title }}": {{ finding.reason }}
{% endfor %}{% endif %}
Set `reviewer` to `{{ item.name }}`. Return only real findings for your angle. Severity: `required` (wrong output, a security hole, a missing deliverable, a broken test, a type error) or `suggestion` (it must name a precedent `path:line` or a written rule). Report no nitpicks: a matter of taste is not a finding.
