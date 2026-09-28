Merge the findings of the review subagents into one list.

The findings, one list per review angle:
{% for result in steps.analyze.results %}
- {{ steps.plan_review.angles[loop.index0].focus }}:
{% for finding in result.findings %}  - [{{ finding.severity }}] {{ finding.file }}:{{ finding.line }} {{ finding.summary }}
{% else %}  - (none)
{% endfor %}{% endfor %}

1. **Verify each finding** by opening the cited file at the cited lines. Delete any finding that the code does not support.
2. **Deduplicate:** merge findings that share one root cause, and keep the highest severity.
3. **Check each severity:** `blocker` for wrong output, security holes, missing deliverables, and broken tests; `major` for real problems that do not break the feature; `minor` for small, cheap fixes.
4. Keep each finding's `quote` as the exact lines from the diff. A later script drops every finding whose quote is not in the diff.
