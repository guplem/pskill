The user does not know what to do with this finding of the review of pull request #{{ inputs.pr }}: "{{ inputs.finding.title }}" at `{{ inputs.finding.file }}:{{ inputs.finding.line }}`. {{ inputs.finding.summary }} The doubt: {{ inputs.doubt }}

Pick the next question that helps you find out what the user wants: post the finding as required, post it as a suggestion, or drop it. Use the game "Akinator" as the model: each question is simple, and each answer narrows down what the user wants.

{% if history.ask_question %}The answers so far:
{% for asked in history.next_question %}{% if loop.index <= (history.ask_question | length) %}- {{ asked.question }} → **{{ history.ask_question[loop.index0].choice }}**{% if history.ask_question[loop.index0].rationale %} ("{{ history.ask_question[loop.index0].rationale }}"){% endif %}
{% endif %}{% endfor %}{% else %}Read the code around `{{ inputs.finding.file }}:{{ inputs.finding.line }}` first, and list the facts and preferences that decide the verdict: whether the problem can happen, who it hurts, and how much the user cares about that kind of problem.
{% endif %}
- **Ask what the user wants to happen, or a fact that the user knows**, never which severity is right.
- **Make the question easy.** The user can answer it with yes, no, maybe or "I don't know", without deep knowledge or long reasoning.
- **Make it self-contained.** The user sees only the question. Explain the point in plain words, name the file or the field, and say what "yes" means. Number it ("Q2 of ~3").
- **Treat "I don't know" as a request for your recommendation** on that point, and do not ask it again.
