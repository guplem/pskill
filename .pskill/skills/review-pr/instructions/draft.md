Write the body of the review of pull request #{{ inputs.pr }}. The user's account posts it, so write it in the user's voice. Each finding gets its own comment with its details, so the body does not repeat them.

The findings that the review posts:
{% for finding in steps.final.json.findings %}- [{{ finding.severity }}] "{{ finding.title }}" at `{{ finding.file }}:{{ finding.line }}`
{% else %}- None.
{% endfor %}{% if steps.triage.still_open %}
The findings of earlier reviews that are still open. Their comments are already on the pull request:
{% for open_finding in steps.triage.still_open %}- [{{ open_finding.severity }}] "{{ open_finding.title }}" at `{{ open_finding.location }}`
{% endfor %}{% endif %}{% if history.ask_revision %}
The changes that the user asked for in your earlier drafts:
{% for revision in history.ask_revision %}- {{ revision.answer }}
{% endfor %}{% endif %}
- **The first line is the verdict**: changes are needed (at least one new or still-open finding is `required`), or the pull request is OK to merge, with the suggestions as optional improvements.
- **Then one short bullet per theme** of the required findings, when there are any, so the author knows what blocks the merge. Name each still-open required finding of an earlier review by its title.
- **150 words at most.** The body stands alone: no chat history, no tutorial, no list of the review rounds.
- Follow the writing rules of the repository (`AGENTS.md`, `CLAUDE.md`, or `CONTRIBUTING.md`) when it has any.
