Post one review on pull request #{{ inputs.pr }}, with one inline comment per finding, in a single API call.

1. Build the payload: `{"event": "COMMENT", "body": "...", "comments": [{"path": ..., "line": ..., "side": "RIGHT", "body": ...}]}`.
   - Use `REQUEST_CHANGES` instead of `COMMENT` when a finding is a `blocker`, unless you are the author of the pull request (GitHub rejects that).
   - Start every inline comment with `**[<severity>] <one-line title>**`, then the problem, why it matters, and a concrete fix.
   - Start the body with what the pull request does well, then the key findings in 3 to 6 sentences.
2. Post it: `gh api repos/guplem/pskill/pulls/{{ inputs.pr }}/reviews -X POST --input <payload file>`.
3. If GitHub rejects a comment because its line is not in the diff (HTTP 422), move that finding into the body with its `file:line`, and post again.
