Check and merge the findings of the {{ history.review | length }} review rounds of pull request #{{ inputs.pr }}. The head commit is `{{ steps.review.outputs.reviewed_sha }}`.

{% for round in history.review %}Round {{ loop.index }}:
{% for finding in round.outputs.findings %}- [{{ finding.severity }}] "{{ finding.title }}" at `{{ finding.file }}:{{ finding.line }}` ({{ finding.reviewer }} reviewer): {{ finding.summary }} Quote: `{{ finding.quote }}`
{% else %}- No new finding.
{% endfor %}{% endfor %}{% if steps.read_earlier.json.dismissed %}
Earlier reviews of this pull request already posted these findings:
{% for posted in steps.read_earlier.json.dismissed %}- [{{ posted.severity }}] "{{ posted.title }}": {{ posted.reason }}
{% endfor %}{% endif %}
- **Check each finding** with `{{ skill.dir }}/references/finding-acceptance.md`. The base branch is the base branch of the pull request, and the scope commit is `{{ steps.review.outputs.scope_sha }}`. Drop each finding that it rejects, and give the reason. Fix the severity when the reviewer picked the wrong one.
- **Merge the findings that describe the same problem** into one, and drop the others as repeats. Drop a finding that an earlier review already posted, too: its comment thread is still on the pull request.
- **Check each finding of an earlier review** at the head commit, and read the replies under it. Leave it out when the head fixes it. When the head does not fix it:
  - **A serious finding** is a security hole or a loss of data. A reply that declines it settles it only when the code at the head confirms its reason.
  - **Any other finding** is settled by a reply of the author that declines it, with or without a reason.
  - Leave out a settled finding. Put an unsettled one in `still_open`, with its severity and location: the review does not post it again, but a required one still requests changes.
  - When you cannot tell if a declined finding is serious, put it in `doubts`, built from its location at the head. When the user keeps it, the review posts it again, so the author sees that it still blocks.
- **Ask the user as little as possible.** Read `{{ skill.dir }}/references/decision-gate.md`. Put a finding in `doubts` only when one of its four tests fails **and** the user's answer changes what the review posts: the finding is posted or not, or it blocks the merge or not. Decide every other finding yourself, whatever its severity. In `doubt`, name the test that failed and say why the answer is not clear, in plain words: the user reads it.
- Each finding of a round goes to exactly one list: `findings`, `dropped`, or `doubts`.
