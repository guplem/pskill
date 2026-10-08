A review of pull request #{{ inputs.pr }} found a problem, and it is not clear if the problem is real or how severe it is. Ask the user what to do with it. The user sees only your message, so make it self-contained:

- **The finding:** "{{ inputs.finding.title }}" at `{{ inputs.finding.file }}:{{ inputs.finding.line }}`, reported as `{{ inputs.finding.severity }}` by the {{ inputs.finding.reviewer }} reviewer. {{ inputs.finding.summary }}
- **The code:** `{{ inputs.finding.quote }}`
- **The doubt:** {{ inputs.doubt }}
- **Your recommendation:** {{ inputs.recommendation }}.

Explain the problem and the doubt in plain words, and give the reason for your recommendation in one sentence. Then ask the user to pick one answer. Put any words that the user adds in `rationale`, as they wrote them.
