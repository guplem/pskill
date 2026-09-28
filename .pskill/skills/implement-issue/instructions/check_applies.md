Check whether issue #{{ steps.read_issue.json.number }} still applies to the current code.

**{{ steps.read_issue.json.title }}**

{{ steps.read_issue.json.body }}

1. Find the code that the issue talks about.
2. For a bug, check whether the bug still happens in the current code. For a feature, check whether it already exists.
3. Read the issue's comments for later decisions: `gh issue view {{ steps.read_issue.json.number }} --comments`.

Choose `obsolete` only with evidence (files and lines). When in doubt, choose `applies`.
