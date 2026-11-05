# Plan for #193: fix the last required-only round's findings, run up to 4 rounds, block only on broken code

## 1. Goal

The required-only review rounds after CI in `implement-issue` (`final_review` and `final_resolve`) block only on
broken code, run up to 4 times, and fix the required findings of the last round instead of leaving them open.

Acceptance criteria (issue #193):

- A `review-round` round with `since_sha` treats as `required` only: wrong output, a security hole, a missing or
  broken test for new behavior, a type error, text that the new code makes false. A finding that only breaks a
  style rule or a project pattern is a `suggestion`, and the round leaves it out.
- `implement-issue` runs up to 4 required-only rounds after CI.
- The required findings of the last round get resolved, and the run reviews nothing after that.
- `finish.md` and `report.md` name the commits that no review saw, and no longer say that a required finding stays
  open. `list_limits.py` and the cases match.
- SPEC 13.2 ("No unchecked last fix") says that the last round's findings get fixed, unreviewed.

## 2. Decisions

- **review-pr follow-up reviews** pass `since_sha` too. The narrower bar applies to them as well: the issue states
  it for every `since_sha` round, and a follow-up review looks only at new code. SPEC 13.2 says so.
- **CI on the last fix.** After the 4th round's fixes, `check_unreviewed` goes to `ready` when the head is not the
  commit that CI checked, so CI runs on the last fix. Then `check_unreviewed` finds the head checked and goes to
  `limits`. `get_ci_green`'s cap of 7 bounds this loop.
- **The `final_review` limit** fires only when a commit is unreviewed (`final_required` goes away).
- **`finding-acceptance.md`** stays as it is (shared file); the narrower bar lives in the `since_sha` bullet of
  `review-round/instructions/review.md` and the `since_sha` input description.
- **No CHANGELOG entry and no version bump:** skill-only changes (#172, #192) added none.

## 3. Approach

- `.pskill/skills/review-round/instructions/review.md`: the `since_sha` bullet lists the narrower `required` bar.
  `review-round/skill.yaml`: the `since_sha` description says the same in short. Then `uv run dev.py sync`.
- `.pskill/skills/implement-issue/skill.yaml`:
  - `final_review`: required findings → `final_resolve` always; else → `check_unreviewed`. `max_visits: 4`.
  - `check_unreviewed`: unreviewed and fewer than 4 rounds → `final_review`; head == CI head → `limits`; else →
    `ready`.
  - `limits` input: drop `final_required`; add nothing else.
- `scripts/list_limits.py`: `FINAL_ROUNDS` goes (only the edge counts rounds now); `final_review` when `unreviewed`.
  Drop `final_rounds` too if unused.
- `instructions/finish.md` and `report.md`: "The required-only review rounds used their 4 rounds, so these commits
  got no review: <commits>." from `steps.check_unreviewed.json.commits`, guarded.
- Cases: `final-rounds-cap.yaml` (4 rounds, last fixed, CI again, capped), check the others that pass the rounds.
- SPEC.md 13.2: "Severity", "Every late fix gets a review", "No unchecked last fix".

## 4. Steps

1. `list_limits.py`: the `final_review` limit only on `unreviewed` (pytest table first).
2. `skill.yaml` routing to 4 rounds, last round fixed, CI on the last fix (case files first).
3. `finish.md` and `report.md` name the unreviewed commits (rendering test first).
4. `review-round` `since_sha` bar (text test first), `dev.py sync`.
5. SPEC 13.2.

## 5. Lists

**New cases:**
- `final_review` limit only when unreviewed, required count ignored: `test_list_limits` rows.
- 4th round's required findings get fixed, CI runs again, then capped: `final-rounds-cap.yaml`.
- Rounds used, head already checked by CI → `limits`: covered by the same case's last `check_unreviewed`.
- finish/report name the unreviewed commits: new test in `tests/test_skill_implement_issue.py`.
- `since_sha` bar text: new test in `tests/test_skill_review_round.py`.

**Stale texts (git grep):**
- `skill.yaml:277` "the 2 extra rounds"; `:291-293` cap comment; `:297-301` edges and "The 2nd round's fixes ...
  stay open"; `:326` `final_required`.
- `list_limits.py:8,13,24,33` docstring, `FINAL_ROUNDS`, the clause.
- `finish.md:12`, `report.md:5`.
- `tests/test_skill_implement_issue.py:611,625,626`.
- `final-rounds-cap.yaml:1,49`.
- `SPEC.md:978,980,988`.

**Reused code:** `check_unreviewed.py` output `commits` (exists); the routing pattern of the `limits`/`ready` edges
of `check_unreviewed`; `render_text` for rendering tests.

## 6. Checks

`uv run dev.py fast` per step; `uv run dev.py check` before push. CI: `static` and `checks` on three OSes.

## 7. Out of scope

`finding-acceptance.md` and the full-round bar; the review loop before CI (`review`/`resolve`, 3 rounds); fix-ci.
