Deduce the verdict for this finding of the review of pull request #{{ inputs.pr }}: "{{ inputs.finding.title }}" at `{{ inputs.finding.file }}:{{ inputs.finding.line }}`. {{ inputs.finding.summary }} The doubt: {{ inputs.doubt }}

The user's answers:
{% for asked in history.next_question %}{% if loop.index <= (history.ask_question | length) %}- {{ asked.question }} → **{{ history.ask_question[loop.index0].choice }}**{% if history.ask_question[loop.index0].rationale %} ("{{ history.ask_question[loop.index0].rationale }}"){% endif %}
{% endif %}{% endfor %}
For an "I don't know" answer, use your recommendation on that point ({{ inputs.recommendation }} for the whole finding). Take the severity from `{{ skill.dir }}/references/finding-acceptance.md`. Drop the finding when that file rejects it, or when the user does not care about it.
