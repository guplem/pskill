{% set check = steps.check_head_before_post if steps.check_head_before_post is defined else steps.check_head_before_round %}Tell the user that the review of pull request #{{ inputs.pr }} stopped at their choice, after the head moved to `{{ check.outputs.head_sha }}`. Nothing is posted.{% if steps.draft is defined %}

Show the drafted body, word for word:

{{ steps.draft.body }}{% endif %}
