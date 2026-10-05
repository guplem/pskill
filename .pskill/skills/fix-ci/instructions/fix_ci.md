CI failed on pull request #{{ inputs.pr }}, at commit `{{ steps.wait_ci.head_sha }}`:

{% for check in steps.wait_ci.failed_checks %}- {{ check }}
{% endfor %}
For each failed check:

1. **Find the cause** in its log: `gh run view <run-id> --log-failed`. The run id is in the check link.
2. **Caused by this pull request:** fix it, commit, and push.
   - Run the failing check locally first only when it is fast. Push the fix of a slow suite, and let CI prove it.
   - For `merge conflict`, merge the base branch and resolve the conflict.
3. **Flaky** (a timeout, or an outage outside this code): rerun the failed jobs once with `gh run rerun <run-id> --failed`.
4. **Not caused by this pull request** (it fails on the base branch too): change nothing.
5. **`draft`:** change nothing, and report the cause `unrelated`. Only the author marks the pull request ready.
