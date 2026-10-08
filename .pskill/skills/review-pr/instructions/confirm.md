Show the user the review of pull request #{{ inputs.pr }}, and ask if you can post it in their name. The user sees only your message, so make it self-contained.

- **The event:** {% if steps.final.json.has_required %}request changes, because a new or an earlier required finding is still open{% else %}approve, because no required finding is open{% endif %}. On the user's own pull request, GitHub allows only a comment.
- **The findings**, one line each, with severity, file, and line. Say that each one goes inline when the diff shows its line, and into the body otherwise:
{% for finding in steps.final.json.findings %}  - [{{ finding.severity }}] "{{ finding.title }}" at `{{ finding.file }}:{{ finding.line }}`
{% else %}  - None.
{% endfor %}{% if steps.triage.still_open %}- **The findings of earlier reviews that are still open.** The review does not post them again, but a required one still requests changes:
{% for open_finding in steps.triage.still_open %}  - [{{ open_finding.severity }}] "{{ open_finding.title }}" at `{{ open_finding.location }}`
{% endfor %}{% endif %}{% if steps.triage.dropped %}- **The findings that the triage dropped**, with the reason, so the user can object:
{% for dropped in steps.triage.dropped %}  - "{{ dropped.title }}": {{ dropped.reason }}
{% endfor %}{% endif %}- **The body**, word for word:

{{ steps.draft.body }}
