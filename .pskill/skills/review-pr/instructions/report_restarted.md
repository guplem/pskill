{% set check = steps.check_head_before_post if steps.check_head_before_post is defined else steps.check_head_before_round %}Tell the user that the head of pull request #{{ inputs.pr }} moved to `{{ check.outputs.head_sha }}`, so the review starts again at their choice. Nothing is posted.

Then run this skill again right away, on pull request #{{ inputs.pr }}, with max_rounds {{ inputs.max_rounds }}, rounds_without_required {{ inputs.rounds_without_required }}, and rounds_without_findings {{ inputs.rounds_without_findings }}.
