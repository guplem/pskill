Tell the user that the review of pull request #{{ inputs.pr }} is not posted, after {{ history.review | length }} review rounds.{% if run.mode == 'autonomous' %} Say that an autonomous run never posts a review: an interactive run posts it after the user confirms it.{% endif %}

Show the drafted body, word for word:

{{ steps.draft.body }}

Then the findings, one line each:
{% for finding in steps.final.json.findings %}- [{{ finding.severity }}] "{{ finding.title }}" at `{{ finding.file }}:{{ finding.line }}`
{% else %}- None.
{% endfor %}{% if steps.triage.still_open %}

Name the findings of earlier reviews that are still open, one line each. The review did not post them again:
{% for open_finding in steps.triage.still_open %}- [{{ open_finding.severity }}] "{{ open_finding.title }}" at `{{ open_finding.location }}`
{% endfor %}{% endif %}{% if steps.triage.dropped %}
And the findings that the triage dropped, with the reason:
{% for dropped in steps.triage.dropped %}- "{{ dropped.title }}": {{ dropped.reason }}
{% endfor %}{% endif %}
