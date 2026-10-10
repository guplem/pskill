Rewrite the description of pull request #{{ steps.open_draft_pr.json.pr_number }} so that it describes the code on the branch. Write it to `<file>` in a temporary folder outside the repository. Then post it: run `uv run {{ skill.dir }}/scripts/publish_body.py` with `{"pr": {{ steps.open_draft_pr.json.pr_number }}, "body_file": "<file>"}` on stdin.

1. `## Summary`: the outcome in the first line. Then the line `Closes #{{ steps.read_issue.json.number }}`. Then one to three bullets.
2. `## Test plan`: `- [x]` only for the checks that really ran. Add `- [ ]` for the CI checks that still have to prove the change.
3. At most 400 words. Put long proof in a `<details>` block.

Follow a pull request template of the repository when it has one (`.github/pull_request_template.md`). Write for a reviewer who never saw this run. Do not mention the plan file: it is removed from the branch before the pull request is ready.
