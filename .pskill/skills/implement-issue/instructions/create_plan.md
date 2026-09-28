Write the implementation plan for issue #{{ steps.read_issue.json.number }}: **{{ steps.read_issue.json.title }}**

{{ steps.read_issue.json.body }}

The research:
{% for result in steps.research.results %}
{{ result.report }}
{% endfor %}
{% if history.ask_user %}The user's answers so far:
{% for qa in history.ask_user %}- Q: {{ qa.question }} A: {{ qa.answer }}
{% endfor %}{% endif %}{% if history.approve_plan %}The user's feedback on the last plan: {{ steps.approve_plan.feedback | default("none") }}
{% endif %}
The plan must name:
1. The files to change, and what changes in each, following the conventions that the research found.
2. The failing tests to write first (red-green, as `AGENTS.md` requires), one per behavior.
3. What stays out of scope.

When a decision is the user's to make (scope, behavior, a trade-off), return `status: question` with the single most important question and the plan so far. The runner asks the user and brings you back here with the answer. Ask one question at a time. Return `status: finished` when nothing is open.
