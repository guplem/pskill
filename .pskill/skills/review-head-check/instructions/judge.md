The head of pull request #{{ inputs.pr }} moved from `{{ inputs.reviewed_sha }}` to `{{ steps.read_head.json.head_sha }}`. These commits change the pull request: {% for commit in steps.read_head.json.commits %}`{{ commit }}` {% endfor %}

Read each one with `git show <commit>`. A clean merge of the base branch is already left out.

- **Significant:** a change to the code, the tests, or a behavior that the review checks, or a merge that resolves a conflict in the code of the pull request.
- **Not significant:** a typo, a comment, formatting, a change to the description only, or a removed plan file.
