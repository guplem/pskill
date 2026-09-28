Decide whether an existing issue already covers this request. Compare the intent, not the wording.

The request: {{ inputs.description }}

The search results:
{% for issue in steps.search_duplicates.json %}- #{{ issue.number }} ({{ issue.state }}) {{ issue.title }}
{% else %}- No issue matched the search.
{% endfor %}
Open any candidate that looks close (`gh issue view <number>`). A closed issue whose reason is "not planned" is a candidate to reopen, not a reason to file a duplicate. Give `match_number` for a duplicate or a related issue.
