Tell the user that the review of pull request #{{ inputs.pr }} is posted ({{ steps.post.json.review_url }}), after {{ history.review | length }} review rounds. Its event: {{ steps.post.json.result }}.{% if steps.post.json.result == 'commented' %} Say that GitHub does not let the user approve or request changes on their own pull request, so the review only comments.{% endif %}

Say where its findings are: {{ steps.post.json.inline }} as inline comments, and {{ steps.post.json.in_body }} in the review body.{% if steps.post.json.fallback %} Say that GitHub refused the inline comments, so every finding went into the body.{% elif steps.post.json.in_body %} Say that the body holds the findings whose line the diff does not show.{% endif %}{% if steps.triage.still_open %}

Name the findings of earlier reviews that are still open, one line each. The review did not post them again:
{% for open_finding in steps.triage.still_open %}- [{{ open_finding.severity }}] "{{ open_finding.title }}" at `{{ open_finding.location }}`
{% endfor %}{% endif %}{% if steps.triage.dropped %}

Name the findings that the triage dropped, one line each, with the reason:
{% for dropped in steps.triage.dropped %}- "{{ dropped.title }}": {{ dropped.reason }}
{% endfor %}{% endif %}
