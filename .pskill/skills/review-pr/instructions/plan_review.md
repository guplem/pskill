Plan the review of pull request #{{ inputs.pr }}. Its size: {{ steps.read_pr.json.additions }} lines added, {{ steps.read_pr.json.deletions }} deleted, {{ steps.read_pr.json.files | length }} files changed.

1. Read the pull request: `gh pr view {{ inputs.pr }}` and `gh pr diff {{ inputs.pr }} --name-only`.
2. Read the linked issues (`Closes #123`, `Fixes #45`) with their comments, because the comments often hold the agreed approach: `gh issue view <number> --comments`.
3. Pick the review angles that this pull request needs. Each angle becomes one independent review subagent.
   - A small, simple change needs one or two angles.
   - A large or risky change (security, data, public interfaces) needs more.
   - Always include `correctness`. Include `tests` when the diff changes behavior.
4. For each angle, write a short brief: what that subagent must look at in this pull request, with the files and the linked issue's expectations.
