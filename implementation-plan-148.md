# Implementation plan: issue #148

## Goal

Every example skill in `.pskill/skills/` reaches GitHub only through `gh api` REST paths, `gh pr diff`, `gh run`, and `gh workflow`, with no `--paginate` and no `--slurp`. Then the skills run in a Claude Code cloud session, where the GitHub proxy refuses GraphQL (HTTP 403) and the next-page link. This mirrors Galtea-AI/monorepo#6018.

Acceptance: the criteria of #148. The manual cloud run is a check after the merge; the pull request says that it is not proven yet.

## Decisions

- **Helper:** `github_rest.py` (`gh_api_call`, `gh_api`, `gh_api_pages`, `is_cross_repository`), with the code of the monorepo copy. Its header names every copy, the copy test, and the proxy reason. One copy in each skill that calls GitHub: checkout-pr, create-issue, fix-ci, implement-issue, resolve-pr-feedback, review-head-check, review-pr. No `# bearer:disable` lines.
- **Unchanged:** `claim_item.py` and `finish_item.py` already POST through `gh api`.
- **fix-ci:** new `scripts/read_checks.py` (monorepo code, no `repository` input), plus `draft` in its output. `wait_ci.md` keeps the pskill rules: `merge conflict`, `draft`, and "no CI on a ready pull request means passed".
- **mark_ready.py:** reads `draft` through REST, runs `gh pr ready`, and on the GraphQL refusal POSTs `pulls/{n}/ccr/ready_for_review`. It is the one exception of the static test.
- **publish_body.py:** in implement-issue and resolve-pr-feedback (two identical copies). Takes `{"pr", "body_file"}` on stdin, strips the proxy footer, and writes only a changed body. `finish.md`, `write_description.md`, and `resolve_item.md` call it.
- **create-issue:** `resolve_repo` becomes `gh api repos/<repo or {owner}/{repo}>`, so `full_name` replaces `nameWithOwner`. Search is refused in the cloud, so new `scripts/search_issues.py` pages the issues (state all, pull requests left out) and keeps the 30 issues that hold the most search words. `create` stays a text script: `gh api repos/R/issues -f title=... -F body=@- --jq .html_url`, so SPEC 13.3 stays true. `ensure_label` becomes `scripts/ensure_label.py` (POST the label; an existing label is fine), and `label_issue` POSTs `issues/N/labels`. The block names stay, so SPEC 13.1 stays true.
- **Instructions:** `understand.md` lists the comments from the read_issue output. `review.md` reads the body with `gh api`. `finish.md` labels and reads the head with `gh api`. `judge_duplicates.md` opens a candidate with `gh api`.
- **Tests:** `load_skill_script` puts the scripts folder on `sys.path` and drops a cached `github_rest`. `install_shell` also routes `gh_api` and `gh_api_pages` when the script has them; they record `gh api <METHOD> <path>`.
- **mypy:** exclude every `github_rest.py` and `publish_body.py` copy except the implement-issue one (duplicate module names; the copies are identical).
- **Docs:** one rule line in `AGENTS.md`; one bullet in SPEC 13.2. No release: the skills are not in `pskill.zip`.

## Steps (one red-green cycle each)

1. Helper, test helpers, copy test, mypy exclude: `tests/test_skill_github_rest.py`.
2. implement-issue scripts: read_issue, checkout_default_branch, checkout_base, open_draft_pr, mark_ready, check_unreviewed.
3. checkout-pr and review-head-check scripts.
4. resolve-pr-feedback collect_items; review-pr post_review and read_earlier_reviews.
5. publish_body.py copies and the three instructions.
6. fix-ci read_checks.py (new `tests/test_skill_fix_ci.py`) and wait_ci.md.
7. create-issue: skill.yaml, the two scripts, judge_duplicates.md, case files.
8. Remaining instructions (understand, finish, review).
9. Static test `tests/test_skills_github_calls.py`, `AGENTS.md`, SPEC 13.2.

## Checks

- Each step: its tests fail first, then pass.
- Local: `uv run ruff format --check . && uv run ruff check . && uv run mypy && uv run pytest --cov && uv run pskill.py validate && uv run pskill.py test`.
- CI on Windows, macOS, and Linux.

## Out of scope

- The runner and the viewer.
- Finding issues that are linked only in the Development sidebar.
