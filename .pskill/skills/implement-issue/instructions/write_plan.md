Write the implementation plan for "{{ steps.understand.title }}" in the plan file `{{ steps.checkout_base.json.plan_file }}`, at the repository root. Do not commit it: a later step pushes it.

The brief:

{{ steps.understand.brief }}

The closest code and its conventions:

{{ steps.research_code.results[0].report }}

The recorded decisions that limit the change:

{{ steps.research_code.results[1].report }}
{% for result in steps.research_gaps.results %}{% if loop.first %}
The answers to the open questions:
{% endif %}- **{{ steps.understand.gaps[loop.index0].question }}** {% if result.status == 'resolved' %}{{ result.answer }}{% else %}Left for the user.{% endif %}
{% endfor %}{% if steps.ask_user is defined %}
The user's answers to the open questions: {{ steps.ask_user.answer }}
{% endif %}{% if history.approve_plan | default([]) %}
The user asked for changes to the last version of the plan: {{ steps.approve_plan.feedback | default('no details') }}
{% endif %}
**The plan** is the spec for every later step, so keep it short and concrete:
1. **Goal** and the acceptance criteria.
2. **Decisions:** each open question with its answer.
3. **Approach:** the files to change, and the existing code that each change copies.
4. **Steps:** the plan steps to build, in order. Each step is one red-green cycle.
5. **Checks:** the fast local checks to run, and the CI checks that prove the rest.
6. **Out of scope.**
