<!-- One of four identical copies, in the references/ folder of review-round, review-pr, review-doubt, and resolve-pr-feedback. Change all four together: tests/test_skill_review_pr.py fails when they differ. -->

The rules that decide which review findings to accept. The reviewers report, the triage keeps, and the
resolution fixes the same findings, because they all read these rules. Each reader names two values: the base
branch and the scope commit.

---

# Finding acceptance

A finding is accepted when it is true at the head commit, it belongs to the pull request (section 1), and it is
more than a matter of taste. Section 2 then sets its severity.

## 1. What belongs to the pull request

**The scope** is the code that `git diff origin/<base branch>...<scope commit>` changes. For each changed line,
the innermost function, method, or constructor around it is in the scope as a whole, older lines included. For a
changed line outside any function (module-level code, a config file, a document), its section or block is in the
scope instead. The rest of the file or class is not.

A finding belongs to the pull request in one of these cases:

- It is about the issue or the plan, or about what a line of the pull request adds, even when the fix goes in
  another place.
- It is an older problem inside the scope, and its fix stays inside the same function, section, or block.
- It is an older problem, and the new code runs the broken part, or the problem stops the pull request from
  reaching its goal. The fix can go anywhere.
- The new code copies an old pattern from code around it, in a file or class that the pull request changes or
  that its plan names. The fix changes that old code to the new pattern.

These limits apply to every case:

- **A line that only renames or moves code brings in no older problem around it.** A renamed call does not make
  its caller's old shape part of the pull request.
- **The "Out of scope" section of the issue or the plan wins.** A finding that asks for work it excludes does not
  belong to the pull request.
- **A decision that the issue or the plan leaves open for a named person is not a finding.** That person settles
  it in the issue.

## 2. Severity

- `required`: the code is wrong (wrong output, a security hole, a missing deliverable, a broken test, a type
  error), it breaks a written rule (`AGENTS.md`, `CLAUDE.md`, `CONTRIBUTING.md`, a recorded decision), or it breaks
  a clear project pattern (for example, it rewrites an existing helper by hand, or names a file unlike its
  siblings). The finding names the rule, or the pattern as `path:line`.
- `suggestion`: a better way that no rule or pattern asks for, for example a long function split in two.

## 3. Rejected

Reject a finding in each of these cases, and give the reason in one sentence:

- It is false at the head commit.
- It is only a matter of taste.
- It does not belong to the pull request (section 1).
