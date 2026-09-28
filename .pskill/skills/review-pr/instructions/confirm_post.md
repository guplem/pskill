Show the user the review of pull request #{{ inputs.pr }} before anything is posted.

The verified findings:
{% for finding in steps.verify_quotes.json.findings %}- [{{ finding.severity }}] {{ finding.file }}:{{ finding.line }} {{ finding.summary }}
{% else %}- No findings survived the checks.
{% endfor %}
Explain the changes of the pull request in two or three plain sentences first, so the user can judge the findings. Then ask whether to post the review on GitHub.
