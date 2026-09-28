Draft the issue for this request: {{ inputs.description }}
{% if history.ask_clarify %}
What the user clarified:
{% for qa in history.ask_clarify %}- Q: {{ qa.question }} A: {{ qa.answer }}
{% endfor %}{% endif %}{% if steps.judge_duplicates.choice == "related" %}
Link the related issue #{{ steps.judge_duplicates.match_number }} under "Related Issues & PRs".
{% endif %}{% if history.confirm_draft %}
The user's feedback on the last draft: {{ steps.confirm_draft.feedback | default("none") }}
{% endif %}
Rules for the body:
- **Start with a TL;DR line:** `**TL;DR:** <one sentence>`. It names what the issue makes true and what it replaces, for example "Currently X; this issue makes Y."
- **Sections:** `## Context` (what, who is affected, why it matters), then `## Steps to Reproduce` for a bug, then `## Acceptance Criteria` as a checklist of observable behavior, then `## Related Issues & PRs` only when there are links.
- **No "Proposed Solution" section** unless the user proposed a solution. Your own code research is not a user-proposed solution.
- **Never state a root cause as fact.** Write "most likely caused by X" or "might be related to X", or leave it out.
- **No redundancy:** no section repeats another, Context does not repeat the title, and there are no generic criteria such as "tests pass".
- Write for someone who skims: short sentences, the point first.

The title: under 80 characters, specific, describes the outcome, and has no `fix:` or `feat:` prefix.
