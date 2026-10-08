# Plan: Example skills say when a visit limit cuts work short (#141)

## Goal

Each visit limit in the example skills that skips work ends the run on a step that names the limit and the skipped work. The run no longer ends "succeeded" when a limit skipped work.

Acceptance criteria (issue #141):

- A skill test for each limit shows that the final message names the limit and the skipped work.
- The AUTHORING.md loop-limit example ends on a step that reports the limit.
- The limits that already end on `failed` or `stopped` (fix-ci `wait_ci`, implement-issue `write_plan`) behave as before.

## Decisions

- **The run goes on after a limit fires.** Ending at the limit only loses work: after the build cap or the review limit, the run still writes the description, marks the pull request ready, runs CI, and adds the label. So every `on_max_visits` target in implement-issue stays where it is.
- **implement-issue ends on a new end `capped` after `finish`.** `finish` gets a condition list: any limit fired goes to `capped`, else to `done`. `capped` has `status: failed` (the goal is not met, as fix-ci `wait_ci` -> `failed`), `result: capped` (new enum value), `pr_number`, `pr_url`, and a new optional output `limits` (the names of the limits that fired). Its report names each limit and the skipped work. `done` stays `succeeded`, reached only when no limit fired.
- **Each limit is detected from `steps` and `history`.** No engine change (templates cannot see why a block was entered):
  | Limit | Name in `limits` | Detection | Skipped work |
  |---|---|---|---|
  | `implement_step` cap (40) | `implement_step` | `not steps.implement_step.done` | Plan steps can be missing. |
  | Review loop (7 fixed rounds) | `review` | the last `resolve` fixed something, and more than 6 `resolve` rounds fixed something | The full review of the last fixes (they got only the required-only rounds). |
  | `get_ci_green` cap (7) | `get_ci_green` | `history.ready` has more visits than `history.get_ci_green` | CI on the head commit, and the comments and review of that commit. |
  | Required-only rounds (5) | `final_review` | `steps.check_unreviewed.json.unreviewed` | The last fixes have no review. |
  | resolve-pr-feedback item cap (100) | `resolve_items` | a `resolve`, `answer_comments`, or `final_resolve` visit with `status == 'failed'` | Items without a verdict or a reply. |
- **The shadowed caps stay as safety nets.** `review` (7) and `final_review` (5) cannot fire, because the `resolve` and `check_unreviewed` edges stop the loops first. Those edge exits are the real limits, and the table above detects them. Keep both caps (removing `review`'s cap adds a validator warning) and keep their comments.
- **fix-ci ending `failed` is not a limit of implement-issue.** The run goes on to `done`, as `unrelated-ci-failure.yaml` shows today.
- **resolve-pr-feedback `claim_item` (100) goes to a new end `capped`.** `status: failed` (the goal "every item has a verdict" is not met). It gives both `decisions` and `fixed` with the same expressions as `resolved`, because implement-issue reads both with no default. Its report names the cap of 100 items, how many items got a verdict, and how many are left.
- **Tests prove it through `path`, `status`, and `outputs`.** A skill test cannot read report text. The path ends `finish, capped`, the status is `failed`, and `outputs.limits` names the limit. The final packet also prints the outputs, so `limits` is in the final message.
- **AUTHORING.md:** change only the line-155 example to `on_max_visits: capped`, an end whose report names the limit and the skipped work. No new rule sentence.
- **Release 0.32.2.** AUTHORING.md ships in `pskill.zip` (`pskill authoring` prints it), so the change needs a patch release and a CHANGELOG section.

## Approach

- `.pskill/skills/implement-issue/skill.yaml`: `finish` edge list; new end `capped`; `capped` in the `result` enum; new optional output `limits`.
- `.pskill/skills/implement-issue/instructions/`: `finish.md` gets a label reason for each limit (the build cap and the required-only rounds have one today; add the review limit, the CI limit, and the item cap). The `capped` report names each limit and its skipped work; `done` and `capped` share one report file, `report.md` (renamed from `report_done.md`), with an `{% if %}` block, so the stats lines are not copied. The "ended at the cap" clause moves out of the `done` text.
- `.pskill/skills/resolve-pr-feedback/skill.yaml`: `claim_item.on_max_visits: capped`; new end `capped`, copied from `resolved`.
- Copy the report style of implement-issue `stopped` (`{% if %}` per case) and the cap end of fix-ci `failed` (all outputs given).
- `AUTHORING.md` line 155; `SPEC.md` 13.3 row "`max_visits` with and without `on_max_visits`" (cite `implement-issue.implement_step`, a cap that fires); `CHANGELOG.md`; version in `pskill_runner/__init__.py` and `pyproject.toml`.
- Run `uv run .pskill/pskill.py sync` if a skill description changes.

## Steps

1. **Review limit.** Update `capped-review-final-rounds.yaml` to expect `[..., finish, capped]`, `failed`, `limits: [review]`. See it fail. Add the `finish` edge, the `capped` end, its report, and the `limits` output with the review detection.
2. **Required-only rounds.** Update `final-rounds-cap.yaml` to expect `capped` with `limits: [final_review]`. See it fail. Add the detection.
3. **Build cap.** Add `build-cap.yaml`: 40 `implement_step` answers with `done: false`, `limits: [implement_step]`. See it fail. Add the detection; move the "ended at the cap" text to the `capped` report.
4. **CI cap.** Add `ci-cap.yaml`: the check_unreviewed -> ready -> get_ci_green loop runs 7 times; the 8th `ready` redirects to `finish`; `limits: [get_ci_green]`. See it fail. Add the detection.
5. **Item cap in resolve-pr-feedback.** Add `items-cap.yaml` (generated: a queue of 101 items, 100 results per looped block), expecting `path` to end `claim_item, capped`, `failed`, and both outputs. See it fail. Add the `capped` end.
6. **Item cap seen by implement-issue.** Add `resolve-items-cap.yaml`: a recorded `resolve` call with `status: failed`; `limits: [resolve_items]`. See it fail. Add the detection.
7. **finish.md label reasons** for the review, CI, and item limits.
8. **Docs and release:** AUTHORING.md example, SPEC.md 13.3 row, CHANGELOG 0.32.2, version bump.

## Checks

- New and updated skill tests: listed in the steps. The existing cases that end on `done` keep passing (no limit fired). `unrelated-ci-failure.yaml` and `plan-stopped.yaml` keep their behavior. fix-ci `capped.yaml` is untouched.
- Local: `uv run .pskill/pskill.py test implement-issue`, `uv run .pskill/pskill.py test resolve-pr-feedback`, `uv run .pskill/pskill.py validate`, then the full CI command from AGENTS.md (ruff, mypy, `pytest --cov`, validate, test).
- CI: the same checks on Windows, macOS, and Linux.

## Out of scope

- Planned limits that skip no work: create-issue and review-doubt question caps, and the review loop exit after 4 rounds with no required finding (it skips only suggestions).
- review-pr `settle_doubt` (cap 50 -> `final`) skips doubts past 50 with no report. The issue does not list it: mention it in the pull request as a possible follow-up.
- Skills in other repositories (the Galtea skills).
- Any engine change.
