Wait until every CI check on the head commit of pull request #{{ inputs.pr }} has finished.

- Read the head commit with `gh pr view {{ inputs.pr }} --json headRefOid`. Count only the checks of that commit.
- Wait in the foreground: run `gh pr checks {{ inputs.pr }} --watch --interval 30` with the longest timeout that your shell tool allows. Where the `timeout` command exists, `timeout 540 gh pr checks {{ inputs.pr }} --watch --interval 30` stops before a 10-minute tool limit. Repeat it until every check has finished.
- Do not end your turn to wait. Never use a `sleep` on its own.
- A skipped check counts as passed.
- When no check starts within 5 minutes, read `gh pr view {{ inputs.pr }} --json mergeable,isDraft`.
  - A conflict with the base starts no CI: report it as the failed check `merge conflict`.
  - A draft can start no CI until it is ready for review: report the failed check `draft`.
  - Otherwise the repository runs no CI on this pull request: report `passed`.
