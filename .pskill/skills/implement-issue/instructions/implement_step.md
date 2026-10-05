Build the next step of the plan file `{{ steps.checkout_base.json.plan_file }}` on branch `{{ steps.checkout_base.json.branch }}`, in one red-green cycle.{% if history.implement_step %} This is cycle {{ (history.implement_step | length) + 1 }}. The last cycle built: {{ steps.implement_step.behavior }}{% endif %}

1. **Test:** write a small test for the step.
2. **Red:** run it, and see it fail for the expected reason.
3. **Green:** write the least code that makes it pass.
4. **Check:** run the fast local checks that the `AGENTS.md`, `CLAUDE.md`, or README files name for the touched code. Leave slow suites to CI.
5. **Push:** commit the test and the code together, with a message in the style of the repository, and push.

- A step that no test can show (docs, config, a purely visual change) skips Test and Red. Say why in `red`.
- When the plan turns out wrong or incomplete, update the plan file first. Commit and push that update alone. Describe it in `plan_update`.
- Follow the `AGENTS.md` and `CLAUDE.md` files of the touched code. Update the docs that the change affects in the same cycle.
