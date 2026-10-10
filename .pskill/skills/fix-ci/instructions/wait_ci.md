Wait until every CI check on the head commit of pull request #{{ inputs.pr }} has finished.

- Run `uv run {{ skill.dir }}/scripts/read_checks.py` with `{"pr": {{ inputs.pr }}, "wait_s": 540}` on stdin. Run it in the foreground, with a shell tool timeout of 10 minutes. The script reads every check of the head commit, and it waits while a check still runs.
- Do not end your turn to wait. Never use a `sleep` on its own.
- Read the `state` of its output:
  - `passed`: report `passed`. A skipped check counts as passed.
  - `failed`: report `failed`, with its `failed_checks`.
  - `pending`: run the script again.
  - `none`: no check started within 5 minutes. When `mergeable` is `null`, GitHub still computes it: run the script once more. Then:
    - `mergeable` is `false`: a conflict with the base starts no CI. Report `failed` with the failed check `merge conflict`.
    - `draft` is `true`: a draft starts no CI until it is ready for review. Report `failed` with the failed check `draft`.
    - Otherwise the repository runs no CI on this pull request: report `passed`.
- Take `head_sha` from its output.
