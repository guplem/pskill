# Plan: Galtea upload checks the key's organization (#197)

## Goal

A project that sets `galtea_organization_id` in `.pskill/config.yaml` never writes to another Galtea organization,
whatever key the shell holds. A refused key skips the upload with one stderr notice per run; the run goes on.
A project without the setting behaves exactly as today.

Acceptance:
- With the setting, `upload_run` calls `GET /auth/user` first; only a `200` with the same `organizationId` uploads.
- Another organization or an HTTP error: no other call, `last_seq` unchanged, one stderr line per run naming the
  organizations (or the status) and the key source, never the key, giving no order.
- A network error on the check: silent, no other call, `last_seq` unchanged.
- No setting, or no key: no extra call, no output. stdout and exit code of `print_and_upload` never change.

## Decisions

- `galtea_organization_id:` with no value (YAML null) means unset (the field's type is `str | None`). Any other
  non-text or empty text is a `ProjectError`: "'galtea_organization_id' must be a non-empty text, such as 'org_abc123'".
- `read_api_key` returns `ApiKey(value, source)` (a NamedTuple) or None. Source texts: "from .pskill/galtea.env" and
  "from the environment variable GALTEA_API_KEY", built from `KEY_FILE_NAME` and `KEY_VARIABLE`.
- The check is a `RunUpload` method called by `upload_run` before `upload_new_events` (that method moves `last_seq`).
  It catches `HTTPError` (refusal, with the status); any other `OSError` reaches `upload_run`'s `except` (silent).
- The flag is `organization_notice_shown` in `galtea.json`, a plain `UploadState` key read with `.get(..., False)`.
- Notice texts:
  - "pskill: Galtea upload off for this run: the API key (from ...) belongs to organization org_x, not org_y."
  - "pskill: Galtea upload off for this run: Galtea refused the API key (from ...) with HTTP 401, so its organization is unknown, not checked against org_y."
- Version 1.2.0.

## Approach

- `pskill_runner/project.py`: field on `Config`; guard in `load_config` like `worktree_folder`; predicate `is_text`.
- `pskill_runner/galtea_client.py`: `current_user()` like `find_product`; docstring line for `GET /auth/user`.
- `pskill_runner/galtea.py`: `ApiKey`, `read_api_key`, `RunUpload.refusal(source)` and `show_notice`, `upload_run`.
- Docs: SPEC 10.1, 10.2 (`galtea.json`), 10.4 Key and Best effort, D29; README; CHANGELOG 1.2.0; version bump.

## Steps

1. Setting in `Config` and `load_config` (tests in `tests/test_project.py`).
2. `GalteaClient.current_user` (test in `tests/test_galtea_client.py`).
3. `read_api_key` returns the key and its source (update its test).
4. The organization check in `upload_run`, with the notice once per run (tests in `tests/test_galtea.py`).
5. Docs, CHANGELOG, version.

## Lists

New cases:
- no setting -> `None`: `test_the_galtea_organization_is_none_by_default`
- text kept: `test_a_galtea_organization_setting_is_kept`
- null -> unset: same test
- empty, number, list rejected: `test_a_wrong_galtea_organization_setting_is_an_error`
- client route: `test_current_user_asks_for_the_user_of_the_key`
- key from file / env / none with source: `test_the_key_file_in_pskill_wins_over_the_environment`
- no setting, no `/auth/user` call: `test_with_no_organization_setting_the_key_is_not_checked`
- matching organization uploads: `test_a_key_of_the_project_organization_uploads`
- other organization: `test_a_key_of_another_organization_sends_nothing_and_says_so_once`
- HTTP 401: `test_a_refused_key_sends_nothing_and_names_the_status`
- notice once over two commands: in the other-organization test
- refused then correct key uploads the whole run: `test_a_correct_key_after_a_refused_one_uploads_the_whole_run`
- network error on check: `test_a_network_error_on_the_check_stays_silent`
- stdout/exit code unchanged: `test_a_skipped_upload_keeps_the_output_and_exit_code` (tests/test_cli_main.py)

Stale texts (git grep `read_api_key`, `galtea.json`, `Best effort`, `galtea.env`):
- `pskill_runner/galtea.py` module docstring ("Any error is swallowed") and `read_api_key` docstring
- SPEC.md 10.2 `galtea.json` line, 10.4 Key and Best effort, D29 row
- README "Upload runs to Galtea"
- `tests/test_galtea.py` key test

Reused code:
- setting guard: `worktree_folder` guard in `load_config`
- client method: `find_product`
- error order: `upload_new_events`
- once flag: `RunInfo.pause_steps_shown`
- stderr line: `cli.py` `print(f"pskill: ...", file=sys.stderr)`

## Checks

Local: `uv run dev.py fast`, then `uv run dev.py check`. CI: static, checks on 3 OSes.

## Out of scope

A dedicated variable name for the key; the empty line in `galtea.env` falling back to the environment.
