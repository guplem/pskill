Show the user the plan for issue #{{ steps.read_issue.json.number }}, then ask whether to approve it.

{{ steps.create_plan.plan }}

When the user approves, the plan is posted as a comment on the issue and the implementation starts.
