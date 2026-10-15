# Implementation plan: upload runs to Galtea (issue #5, Galtea half)

## Goal
An optional module uploads every run of a skill whose `skill.yaml` names `x-galtea.product` to Galtea as production usage, live, block by block. With no Galtea key, nothing changes: no network, no output, no file.

Acceptance criteria:
- With a key, each execution of a skill with a product (root run, or one child call) is one production session, with one turn per block and spans inside each turn.
- A call is one turn in its caller. A child with its own product gets its own session, whatever its caller. A child without a product uploads nothing.
- A failing block gives a FAILED turn. The run end finishes the session.
- An upload error never changes the output or the exit code of a command.
- No new dependency. 100% coverage. CI is green on three OSes.

## Decisions (final, settled with the user; see the issue #5 comment)
- Product by exact name, created if missing. pskill syncs its description and forces `autoCloseInactivityMinutes: 10080` and `closedSessionInferenceCreationPolicy: REOPEN_AND_REEVALUATE`.
- Version facts: `skill` (run.json `skill_hash` for the root, `folder_hash` of the child copy for a child), `runner`, `harness`, `llm` (`start --model`, else `unknown`), and `tiers` (only when the skill has a parallel block).
- customId: `<skill id>@<run id>` for the root, and `<skill id>@<run id>/<call id>` for a child.
- Metadata: automatic fields at creation. The `x-galtea.metadata` templates are rendered after each upload, with a PATCH only when a value is new.
- Key: `.pskill/galtea.env` (`GALTEA_API_KEY=...`, gitignored), else the env var `GALTEA_API_KEY`.
- Upload after each run command, outside the run lock. No lock, no retry, no sync command. Every error is swallowed.
- Secrets are redacted. Fields are cut to fit the 512 KB body limit.

## Approach
- `pskill_runner/galtea_client.py` (new): a typed `GalteaClient` over an injected `send(method, url, body) -> object`. The default sender uses `urllib` with a Bearer header and a 5 s timeout, as `release.py` does. The docstring holds the verified API facts, as `codex.py` does.
- `pskill_runner/galtea.py` (new): `upload_run(project, run_id, client_factory=...)`.
  - Reads the key.
  - Reads `x-galtea` from the raw YAML of the run's skill copies (`yaml_loading`).
  - Reads `events.jsonl` from `last_seq` (`run_store.read_events`).
  - Maps the events to turns and spans, and keeps its state in `runs/<id>/galtea.json` (`write_json_atomic`).
  - Catches every exception. The pattern is `run_waits.py`.
- `engine.py`: `Run.log` adds `call_id` (the chain of call instances, `""` at the root, for example `review#2` or `review#2>doubt#1`). A frame keeps its own `call_id`. A call's `block_started` logs `inputs`.
- `run_records.py`: `SCHEMA_VERSION = 7`, the frame field `call_id`, and the optional `RunInfo.llm`.
- `cli.py`: `start --model`, and one `galtea.upload_run(...)` call after start, submit, task, current, resume, pause, and cancel. Never from hooks or `test`.
- `stubs.py`: the start line asks the agent to pass `--model <its model id>`.
- `install.py`: `init` writes `galtea.env` in `.gitignore`. `update` appends the line when it is missing.
- `validator.py`: checks `x-galtea` when it is present (`product` is a non-empty text, `metadata` is a map of texts).
- Docs:
  - SPEC: D29, and sections 5.1, 7.7, 10.1, 10.2, 10.3, 15, and 18.1.
  - AUTHORING.md, README, the AGENTS.md table, and the CHANGELOG.
  - Version 0.39.0.

## Steps (each step is one red-green cycle)
1. Events schema 7: `call_id` on every event, and `inputs` on a call's `block_started`. Then check the viewer.
2. `start --model` stores `RunInfo.llm`, and the stub tells the agent to pass it.
3. `galtea_client.py`: the requests, the Bearer header, the injected send, and the default urllib sender (tested with a local `ThreadingHTTPServer`, as in `test_viewer_server.py`).
4. `galtea.py` key lookup and `x-galtea` reading. With no key or no product, nothing happens.
5. Product, version, and session setup, cached in `galtea.json`.
6. Turns for every block type, the FAILED turn on a failing pause, spans, and session finish.
7. Child sessions and the call turn.
8. Metadata templates, and the PATCH when a value is new.
9. Redaction and size cuts.
10. The CLI wiring, the validator check, and the `.gitignore` line in `init`/`update`.
11. The docs, the version, and the CHANGELOG.

## Checks
- New tests: `tests/test_galtea.py` and `tests/test_galtea_client.py`.
- Extended tests: engine (`call_id`, `inputs`), CLI (`--model`, and the upload call that never breaks a command), install, validator, and stubs.
- Local: `uv run ruff format --check . && uv run ruff check . && uv run mypy && uv run pytest --cov && uv run pskill.py validate && uv run pskill.py test`.
- CI: the same checks on Windows, macOS, and Linux.

## Out of scope
- The OpenTelemetry export (it stays in 18.1).
- Monitors.
- Tokens and cost.
- A sync or retry command.
- `x-galtea` in the example skills (the user adds the products).
