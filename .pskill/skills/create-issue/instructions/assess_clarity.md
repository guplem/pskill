Decide whether you understand exactly what this issue is about.

The user's description: {{ inputs.description }}
{% if history.ask_clarify %}
The answers so far:
{% for qa in history.ask_clarify %}- Q: {{ qa.question }} A: {{ qa.answer }}
{% endfor %}{% endif %}
1. Summarize for yourself: what is described, why it matters (who is affected), and where in the code it applies. Search the code to check.
2. For a bug, find the code path and check that the bug really exists. For a feature or an improvement, find the code that would change.
3. Look for gaps: could the description mean two things? Is the scope clear? For a bug, do you know how to reproduce it?

Return `clear: true` when nothing important is open. Otherwise return `clear: false` and the single most important question. Do not ask more than you need: if the description is genuinely clear, it is clear.
