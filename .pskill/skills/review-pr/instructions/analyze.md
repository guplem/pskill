Review pull request #{{ inputs.pr }} for **{{ item.focus }}** only.

Your brief: {{ item.brief }}

{% if item.focus == "correctness" %}Check that the code does what the linked issue asks, and that no input gives a wrong result. Trace the changed code paths end to end.{% endif %}
{%- if item.focus == "security" %}Check for injection, path traversal, secrets in code or logs, missing input checks, and unsafe subprocess or file use.{% endif %}
{%- if item.focus == "tests" %}Check that the new tests assert real behavior (red-green), and name the realistic inputs that no test covers.{% endif %}
{%- if item.focus == "conventions" %}Compare the new code with two or three similar places in the codebase. Report where it breaks the convention, and cite the example it should follow.{% endif %}
{%- if item.focus == "performance" %}Check for work that grows badly with input size, repeated expensive calls, and blocking calls on hot paths.{% endif %}
