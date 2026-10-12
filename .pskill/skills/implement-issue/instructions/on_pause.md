{% if run.mode == 'autonomous' %}This run is autonomous, so nobody reads this pause. Leave a trace on GitHub before you stop.
{% if steps.open_draft_pr or steps.read_issue %}{% set number = steps.open_draft_pr.json.pr_number if steps.open_draft_pr else steps.read_issue.json.number %}
Post one comment on {{ 'pull request' if steps.open_draft_pr else 'issue' }} #{{ number }}. In two or three sentences, say:
- at which block the run paused, and why (the error above, in plain words);
- what a person must do: fix the cause, then resume the run {{ run.id }} in this checkout (the commands below), or cancel it.

Write the comment to `<file>` in a temporary folder outside the repository. Then post it: run `uv run {{ skill.dir }}/scripts/post_comment.py` with `{"number": {{ number }}, "run_id": "{{ run.id }}", "body_file": "<file>"}` on stdin. It is safe to run twice: it updates this run's pause comment when there is one.
{% else %}
No issue or pull request exists yet, so there is nowhere to comment. Only tell the user why the run paused.
{% endif %}{% endif %}
