The research left these questions open. Ask the user all of them together, each with its options (the recommended one first), and give back every answer.

{% for result in steps.research_gaps.results %}{% if result.status == 'needs_user' %}- **{{ steps.understand.gaps[loop.index0].name }}:** {{ steps.understand.gaps[loop.index0].question }} What the research found: {{ result.answer }}{% if result.options %} Options: {{ result.options | join('; ') }}{% endif %}
{% endif %}{% endfor %}