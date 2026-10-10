Understand issue #{{ steps.read_issue.json.number }}: **{{ steps.read_issue.json.title }}**

{{ steps.read_issue.json.body }}

- Labels: {{ steps.read_issue.json.labels | join(', ') | default('none', true) }}
- Comments: {{ steps.read_issue.json.comments | length }}. When a newer comment and the body disagree, follow the comment.
{% for comment in steps.read_issue.json.comments %}
  **{{ comment.author }}:** {{ comment.body | indent(2) }}
{% endfor %}{% if steps.read_issue.json.cross_references %}- Linked: {% for ref in steps.read_issue.json.cross_references %}#{{ ref.number }} ({{ ref.title }}){% if not loop.last %}, {% endif %}{% endfor %}
{% endif %}{% if steps.read_issue.json.existing_branches %}- Branches that already exist for it: {{ steps.read_issue.json.existing_branches | join(', ') }}
{% endif %}
The checkout is at the latest `{{ steps.checkout_default.json.default_branch }}`. When the work builds on an unmerged branch, fetch it with `git fetch origin <branch>`. Read its code with `git show origin/<branch>:<path>`.

1. **Gather** everything about it: the linked issues and pull requests, and the code, docs, and recorded decisions that it touches. Check each claim against the code: an issue can be out of date.
2. **Base:** `{{ steps.checkout_default.json.default_branch }}`, unless the work builds on an unmerged branch. Then that branch is the base.
3. **Gaps:** keep each gap small enough for one subagent to research. A clear bug fix often has none. Do not answer them here.
4. **Blocker:** only when the work must not start: the work is already done, or an open pull request already does it.
