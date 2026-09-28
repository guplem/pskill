The review of pull request #{{ steps.implement.pr_number }} found these problems:

{% for finding in steps.review.outputs.findings %}- [{{ finding.severity }}] {{ finding.file }}:{{ finding.line }} {{ finding.summary }}
  Quote: `{{ finding.quote }}`
{% endfor %}
Decide for each finding, with judgment, not only by severity:
- Always fix a `blocker`.
- Fix a `major` or `minor` finding when it is a real bug, when leaving it creates future cost, or when the fix is small and in scope.
- Leave the rest, each with a one-sentence reason.

Fix red-green (a failing test first), run every check in `AGENTS.md`, commit, and push to the same branch. Then, for each finding, reply on its review thread: `**Applied** in <short sha>: <what changed>.` or `**Not applied**: <reason>.`
