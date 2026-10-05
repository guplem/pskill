Rewrite the description of pull request #{{ steps.open_draft_pr.json.pr_number }} so that it describes the code on the branch. Write it to a file. Post it with `gh api -X PATCH repos/{owner}/{repo}/pulls/{{ steps.open_draft_pr.json.pr_number }} -F body=@<file>`. Use capital `-F`: lowercase `-f` posts the text `@<file>` itself.

1. `## Summary`: the outcome in the first line, then the line `Closes #{{ steps.read_issue.json.number }}`, then one to three bullets.
2. `## Test plan`: `- [x]` only for the checks that really ran. Add `- [ ]` for the CI checks that still have to prove the change.
3. At most 400 words. Put long proof in a `<details>` block.

Follow a pull request template of the repository when it has one (`.github/pull_request_template.md`). Write for a reviewer who never saw this run. Do not mention the plan file: it leaves the branch before the pull request is ready.
