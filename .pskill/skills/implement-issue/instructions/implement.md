Implement issue #{{ steps.read_issue.json.number }} ("{{ steps.read_issue.json.title }}") by following the approved plan:

{{ steps.create_plan.plan }}

1. Read `AGENTS.md` for the conventions and the check commands.
2. Create a branch from `main`: `git switch -c {{ steps.read_issue.json.number }}-<short-slug> main`.
3. **Red-green:** write each failing test first, run it, and see it fail for the expected reason. Then write the least code that passes.
4. Implement only what the plan describes. Do not touch code outside its scope.
5. Run every check in `AGENTS.md`, and fix every failure that you introduced.
6. Commit each test with the code that makes it pass, then push: `git push -u origin HEAD`.
7. Open the pull request: `gh pr create --base main --title "<short title>" --body "<what changed and why>. Closes #{{ steps.read_issue.json.number }}" --assignee @me`.
