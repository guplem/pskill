# Plan: a skill's `on_pause` text tells the agent what to do when its run pauses (#158)

## Goal

A skill can name what the agent does when its run pauses. The runner puts that text in the pause packet, under the error, so an unattended run gets the skill's own cleanup steps (post a comment, release a claim) at the moment of the pause.

Acceptance criteria:
- A skill with `on_pause: instructions/on_pause.md` gets that text in its pause packet, under the error.
- A skill without it gets today's pause packet, byte for byte.
- `pskill validate` rejects an `on_pause` file that does not exist.

## Decisions

| Question | Answer | Why |
|---|---|---|
| Text, or blocks too? | Text only, one optional top-level key `on_pause`. No `on_end`. | Pause blocks would bring back `on_error` (SPEC 18). An `end` block already has its own `report`. |
| Form | Same as `instruction` and `report` (D19): a value that ends in `.md` is a file in the skill folder, any other value is the text. `{{ }}` works, with the names of that skill's frame (7.1). | One way to write prose. The text can name the issue or the pull request. |
| Autonomous only? | No mode field. The text says it, or uses `run.mode`. | One way to do it (principle 1). |
| Nested calls | The packet shows the `on_pause` of every skill on the call stack that has one, the paused skill first, out to the root, each under its own heading. Each text is rendered with its own frame's names. | Each skill knows its own cleanup; the root's text still reaches the agent when a child pauses. D10 holds: the runner renders, the child reads nothing of its caller. |
| A `{{ }}` that fails at pause time | The section shows the error and the text as written. The pause never fails. | The pause packet is the last thing the agent sees; `guarded()` and the Stop hook call `pause()`. |
| Packet layout | `### Error` (as today), then `### Pause steps of <skill-id>` per skill, then `### Next`, whose first line becomes "Do the pause steps above. Then tell the user why the run paused. ..." | With no `on_pause`, every line stays as today. |
| A text that renders empty | Adds no section, and the Next line stays as today. | An autonomous-only text (`{% if run.mode == 'autonomous' %}`) then leaves an interactive pause packet unchanged. |
| Pause reasons | The same packet for every reason, and for `current` on a paused run. | One pause packet. |
| The Stop hook's give-up pause | Out of scope: the agent is allowed to stop and sees no packet. Recorded as limitation L9. | Like a session that dies (the issue's out of scope). |

## Approach

- `skill_schema.py`: add `"on_pause": {"type": "string"}` to `TOP_LEVEL_SCHEMA`.
- `skill_model.py`: `Skill.on_pause: str | None = None` (last field). `skill_loader.build_skill`: `on_pause=raw.get("on_pause")`.
- `packets.py`: a small frozen dataclass `PauseSteps(skill_id, text)`; `render_pause_packet(..., pause_steps: Sequence[PauseSteps] = ())`. Copies the optional-section idiom of `### Error`.
- `engine.py`: `context_of(frame, item)` (the old `context` reads `self.frame` through it). `pause_steps()` walks the frames innermost first and renders each `on_pause` with `render_text` and its frame's names, catching `ComputedValueError` and `OSError` (a file missing in an old run copy). `pause_text()` passes them.
- `validator.py`: `on_pause_problems(skill)`: a missing `.md` file is an error ("the file ... does not exist", location `on_pause`), else `text_problems` (compile and references). `unused_instruction_file_warnings` counts `skill.on_pause` as used.
- `skill_view.py` + `viewer/app.js` + `viewer/field_help.js`: the skill screen shows the text under the goal, folded, with a `?` help entry `on_pause`.
- `skill_export.py`: a section `## If the work pauses` with `plain_text(prose(skill, skill.on_pause))`.
- `.pskill/skills/implement-issue/`: `on_pause: instructions/on_pause.md`. In an autonomous run it posts one comment, through `gh api` REST, on the draft pull request (or on the issue when there is none yet) that says where and why the run paused. Then `sync`.
- Docs and release: SPEC (3.1 L9, 5.1, 5.2, 7.4, 8, 11, 13.3, 14, 14.1), AUTHORING.md (a line or two, inline text in the example), CHANGELOG `0.38.0`, `__version__` and `pyproject.toml` to 0.38.0, `uv.lock`.

## Steps (one red-green cycle each)

1. Schema, model, loader: a skill loads its `on_pause`; a skill without it has `None`.
2. Packet: `render_pause_packet` with pause steps shows each section under the error and the changed Next line; with none, the exact old text.
3. Engine: a paused run's packet (block failure, user pause, `current`) shows the rendered `on_pause`; nested call shows child then parent, each with its own names; a failed `{{ }}` shows the error and the raw text; a missing file shows the error.
4. Validator: missing file error, compile and reference errors, the file is not an unused instruction file.
5. Viewer: `skill_view` gives `on_pause`; app.js draws it; field help entry.
6. Export: the section appears with `on_pause`, and not without it.
7. Example skill: `implement-issue` `on_pause.md`; a pytest renders it for an autonomous run with a pull request, with only an issue, and for an interactive run; `sync`, `validate`, `test`.
8. Docs and release 0.38.0.

## Checks

- New tests in `tests/test_skill_loader.py`, `test_packets.py`, `test_engine.py`, `test_engine_blocks.py` (nested), `test_validator.py`, `test_skill_view.py`, `test_skill_export.py`, `test_viewer_files.py` (help entry), `test_skill_implement_issue.py`.
- Local: `uv run ruff format --check . && uv run ruff check . && uv run mypy && uv run pytest --cov && uv run pskill.py validate && uv run pskill.py test`.
- CI on Windows, macOS, and Linux.

## Out of scope

- `on_end`, pause blocks, a per-block or per-mode `on_pause`.
- A session that dies, and the Stop hook's give-up pause: no packet reaches the agent (L9).
