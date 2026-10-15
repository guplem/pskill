"""Tests for pskill_runner.galtea: the upload of runs to Galtea, with a fake Galtea."""

import urllib.error
from email.message import Message
from pathlib import Path
from typing import Any

import pytest

from pskill_runner import galtea
from pskill_runner.engine import cancel_run, pause_run, resume_run, start_run, submit_answer
from pskill_runner.galtea_client import GalteaClient
from pskill_runner.project import Project, find_project
from pskill_runner.run_store import read_json
from tests.skill_files import write_skill
from tests.test_engine_blocks import CHILD_SKILL, PARALLEL_SKILL, PARENT_SKILL, SCRIPT_SKILL

KEY = {"GALTEA_API_KEY": "gsk_test"}


class FakeGaltea:
    """A Galtea stand-in: it records every call and gives each created object a numbered id."""

    def __init__(
        self,
        products: list[dict[str, Any]] | None = None,
        fail_on: str | None = None,
        sessions: list[dict[str, Any]] | None = None,
        error: Exception | None = None,
    ) -> None:
        self.calls: list[tuple[str, str, Any]] = []
        self.products = products or []
        self.sessions = sessions or []
        self.error = error or OSError("Galtea is down")
        self.fail_on = fail_on
        self.count = 0

    def send(self, method: str, path: str, body: Any) -> Any:
        self.calls.append((method, path, body))
        if self.fail_on is not None and self.fail_on in path:
            raise self.error
        self.count += 1
        if method == "GET":
            return self.sessions if path.startswith("/sessions") else self.products
        replies = {
            "/products": "prod",
            "/versions/get-or-create": "ver",
            "/sessions": "ses",
            "/inferenceResults": "inf",
        }
        prefix = replies.get(path)
        return {"id": f"{prefix}_{self.count}"} if prefix else None

    def client(self, api_key: str) -> GalteaClient:
        assert api_key == "gsk_test"
        return GalteaClient(self.send)

    def bodies(self, method: str, path: str) -> list[Any]:
        return [body for call_method, call_path, body in self.calls if (call_method, call_path) == (method, path)]


def with_product(skill_yaml: str, product: str, extra: str = "") -> str:
    return skill_yaml.replace("schema: pskill/v1\n", f"schema: pskill/v1\nx-galtea:\n  product: {product}\n{extra}", 1)


def make_project(tmp_path: Path, skills: dict[str, str]) -> Project:
    for skill_id, skill_yaml in skills.items():
        write_skill(tmp_path / ".pskill" / "skills", skill_id, skill_yaml)
    (tmp_path / ".pskill" / "agents").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".pskill" / "agents" / "checker.md").write_text("You check facts.", encoding="utf-8")
    return find_project(tmp_path)


def upload(project: Project, run_id: str, fake: FakeGaltea, environment: dict[str, str] = KEY) -> None:
    galtea.upload_run(project, run_id, make_client=fake.client, environment=environment)


# --- the key ----------------------------------------------------------------------------------------


def test_with_no_key_nothing_is_sent_and_no_file_is_written(tmp_path: Path) -> None:
    project = make_project(tmp_path, {"parent": with_product(PARENT_SKILL, "p"), "child": CHILD_SKILL})
    run_id, _ = start_run(project, "parent", {}, mode="interactive", harness="generic")
    fake = FakeGaltea()

    upload(project, run_id, fake, environment={})

    assert fake.calls == []
    assert not (project.runs_folder / run_id / "galtea.json").exists()


def test_the_key_file_in_pskill_wins_over_the_environment(tmp_path: Path) -> None:
    project = make_project(tmp_path, {})
    (project.pskill_folder / "galtea.env").write_text("# comment\nOTHER=1\nGALTEA_API_KEY = 'gsk_file'\n")

    assert galtea.read_api_key(project, {"GALTEA_API_KEY": "gsk_env"}) == "gsk_file"
    (project.pskill_folder / "galtea.env").write_text("GALTEA_API_KEY=\n")
    assert galtea.read_api_key(project, {"GALTEA_API_KEY": "gsk_env"}) == "gsk_env"
    assert galtea.read_api_key(project, {}) is None


# --- one skill --------------------------------------------------------------------------------------


def test_a_run_becomes_one_production_session_with_a_turn_per_block(tmp_path: Path) -> None:
    project = make_project(tmp_path, {"parent": with_product(PARENT_SKILL, "pskill parent"), "child": CHILD_SKILL})
    run_id, _ = start_run(project, "parent", {}, mode="interactive", harness="generic", llm="claude-opus-5-5")
    fake = FakeGaltea()

    upload(project, run_id, fake)
    assert fake.calls == []  # no block completed yet

    submit_answer(project, run_id, "text: Hello from the parent.\n")
    upload(project, run_id, fake)
    submit_answer(project, run_id, "text: Hello, Ada!\n")
    upload(project, run_id, fake)

    assert fake.bodies("POST", "/products") == [{"name": "pskill parent", "description": "Calls a child."}]
    product_updates = [body for method, path, body in fake.calls if method == "PATCH" and path.startswith("/products/")]
    assert product_updates == [
        {
            "description": "Calls a child.",
            "autoCloseInactivityMinutes": 10080,
            "closedSessionInferenceCreationPolicy": "REOPEN_AND_REEVALUATE",
        }
    ]
    [version] = fake.bodies("POST", "/versions/get-or-create")
    assert version["facts"]["llm"] == "claude-opus-5-5"
    assert version["facts"]["harness"] == "generic"
    assert version["facts"]["skill"].startswith("sha256:")
    assert "tiers" not in version["facts"]
    [session] = fake.bodies("POST", "/sessions")
    assert session["customId"] == f"parent@{run_id}"
    assert session["isProduction"] is True
    assert session["context"] == "Get a greeting from the child."
    assert session["metadata"]["run_id"] == run_id
    turns = fake.bodies("POST", "/inferenceResults")
    assert [turn["index"] for turn in turns] == [0, 1, 2]
    assert turns[0]["input"].startswith("## pskill · parent · greet")
    assert turns[0]["actualOutput"] == '{"text": "Hello from the parent."}'
    assert turns[1]["input"] == '{"name": "Ada"}'
    assert '"child_session"' not in turns[1]["actualOutput"]  # the child names no product
    assert all(turn["status"] == "GENERATED" for turn in turns)
    finish = fake.bodies("PATCH", f"/sessions/{fake_session_id(fake)}/finish")
    assert finish == [{"stoppingReason": "succeeded"}]
    [final_update] = fake.bodies("PATCH", f"/sessions/{fake_session_id(fake)}")
    assert final_update["metadata"]["status"] == "succeeded"
    assert final_update["metadata"]["ended_at"].endswith("Z")
    assert final_update["metadata"]["duration_ms"] >= 0


def fake_session_id(fake: FakeGaltea) -> str:
    index = next(i for i, call in enumerate(fake.calls) if call[:2] == ("POST", "/sessions"))
    return f"ses_{index + 1}"


def test_each_turn_has_a_root_span_for_its_block(tmp_path: Path) -> None:
    project = make_project(tmp_path, {"parent": with_product(PARENT_SKILL, "p"), "child": CHILD_SKILL})
    run_id, _ = start_run(project, "parent", {}, mode="interactive", harness="generic")
    submit_answer(project, run_id, "nonsense: 1\n")
    submit_answer(project, run_id, "text: Hello.\n")
    fake = FakeGaltea([{"id": "prod_old"}])

    upload(project, run_id, fake)

    assert fake.bodies("POST", "/products") == []  # the product exists
    spans = fake.bodies("POST", "/traces/batch?includeRejected=true")[0]["traces"]
    root, rejected = spans
    assert root["name"] == "greet"
    assert root["type"] == "AGENT"
    assert root["metadata"]["decided_by"] == "agent"
    assert rejected["name"] == "rejected submission"
    assert rejected["parentTraceId"] == root["id"]
    assert rejected["inputData"] == {"raw": "nonsense: 1\n"}


def test_a_failing_script_gives_a_failed_turn_with_its_attempts(tmp_path: Path) -> None:
    failing = SCRIPT_SKILL.replace(
        "\"import json; print(json.dumps({'files': ['a.md', 'b.md']}))\"", '"import sys; sys.exit(3)"'
    )
    project = make_project(tmp_path, {"scripted": with_product(failing, "s")})
    run_id, _ = start_run(project, "scripted", {}, mode="interactive", harness="generic")
    fake = FakeGaltea()

    upload(project, run_id, fake)

    [turn] = fake.bodies("POST", "/inferenceResults")
    assert turn["status"] == "FAILED"
    assert "exit code 3" in turn["error"]
    assert '"argv"' in turn["input"]
    spans = fake.bodies("POST", "/traces/batch?includeRejected=true")[0]["traces"]
    assert [span["name"] for span in spans] == ["list_files", "script attempt", "script attempt", "script attempt"]
    assert spans[1]["outputData"]["exit_code"] == 3


def test_a_script_turn_shows_its_command_and_a_cancelled_run_finishes_with_an_error(tmp_path: Path) -> None:
    project = make_project(tmp_path, {"scripted": with_product(SCRIPT_SKILL, "s")})
    run_id, _ = start_run(project, "scripted", {}, mode="interactive", harness="generic")
    fake = FakeGaltea()

    upload(project, run_id, fake)

    script_turn, end_turn = fake.bodies("POST", "/inferenceResults")
    assert '"argv"' in script_turn["input"]
    assert end_turn["input"] == '{"block": "done"}'


def test_a_cancelled_run_finishes_its_session_with_an_error(tmp_path: Path) -> None:
    project = make_project(tmp_path, {"parent": with_product(PARENT_SKILL, "p"), "child": CHILD_SKILL})
    run_id, _ = start_run(project, "parent", {}, mode="interactive", harness="generic")
    submit_answer(project, run_id, "text: Hello.\n")
    cancel_run(project, run_id)
    fake = FakeGaltea()

    upload(project, run_id, fake)

    finish = [body for method, path, body in fake.calls if path.endswith("/finish")]
    assert finish == [{"error": "cancelled"}]


# --- child skills ----------------------------------------------------------------------------------


def test_a_child_with_its_own_product_gets_its_own_linked_session(tmp_path: Path) -> None:
    project = make_project(
        tmp_path, {"parent": with_product(PARENT_SKILL, "p"), "child": with_product(CHILD_SKILL, "c")}
    )
    run_id, _ = start_run(project, "parent", {}, mode="interactive", harness="generic")
    submit_answer(project, run_id, "text: Hello from the parent.\n")
    submit_answer(project, run_id, "text: Hello, Ada!\n")
    fake = FakeGaltea()

    upload(project, run_id, fake)

    _, child_session = fake.bodies("POST", "/sessions")
    assert child_session["customId"] == f"child@{run_id}/child#1"
    assert child_session["metadata"]["parent_session_custom_id"] == f"parent@{run_id}"
    turns = fake.bodies("POST", "/inferenceResults")
    child_session_id = [call for call in fake.calls if call[:2] == ("POST", "/sessions")]
    child_session_index = fake.calls.index(child_session_id[1])
    child_turns = [turn for turn in turns if turn["sessionId"] == f"ses_{child_session_index + 1}"]
    assert len(child_turns) == 2  # its task and its end block, in its own session
    call_turn = next(turn for turn in turns if turn["input"] == '{"name": "Ada"}')
    assert f'"child_session": "child@{run_id}/child#1"' in call_turn["actualOutput"]
    finishes = [path for method, path, body in fake.calls if path.endswith("/finish")]
    assert len(finishes) == 2


def test_a_child_with_a_product_uploads_even_when_its_caller_has_none(tmp_path: Path) -> None:
    project = make_project(tmp_path, {"parent": PARENT_SKILL, "child": with_product(CHILD_SKILL, "c")})
    run_id, _ = start_run(project, "parent", {}, mode="interactive", harness="generic")
    submit_answer(project, run_id, "text: Hello from the parent.\n")
    submit_answer(project, run_id, "text: Hello, Ada!\n")
    fake = FakeGaltea()

    upload(project, run_id, fake)

    [session] = fake.bodies("POST", "/sessions")
    assert session["customId"] == f"child@{run_id}/child#1"
    assert session["metadata"]["parent_session_custom_id"] == f"parent@{run_id}"
    assert len(fake.bodies("POST", "/inferenceResults")) == 2


# --- metadata, secrets, failures ------------------------------------------------------------------


def test_metadata_templates_are_sent_once_their_steps_have_run(tmp_path: Path) -> None:
    extra = '  metadata:\n    greeting: "{{ steps.greet.text }}"\n    run: "{{ run.id }}"\n'
    project = make_project(tmp_path, {"parent": with_product(PARENT_SKILL, "p", extra), "child": CHILD_SKILL})
    run_id, _ = start_run(project, "parent", {}, mode="interactive", harness="generic")
    submit_answer(project, run_id, "text: Hi there.\n")
    fake = FakeGaltea()

    upload(project, run_id, fake)
    upload(project, run_id, fake)  # nothing new: no second update

    updates = [body for method, path, body in fake.calls if method == "PATCH" and path.startswith("/sessions/")]
    assert len(updates) == 1
    assert updates[0]["metadata"]["greeting"] == "Hi there."
    assert updates[0]["metadata"]["run"] == run_id


def test_a_template_that_cannot_render_yet_is_skipped() -> None:
    context: dict[str, Any] = {"inputs": {}, "steps": {}}

    assert galtea.rendered_metadata({"pr": "{{ steps.open_pr.number }}", "fixed": "x"}, context) == {"fixed": "x"}


def test_secrets_are_redacted_and_long_texts_are_cut() -> None:
    value = {"a": ["token ghp_" + "a" * 36, "Bearer abcdefghijklmnopqrstu"], "b": "x" * 200_000, "c": 3}

    cleaned = galtea.redacted(value)

    assert cleaned["a"] == ["token [redacted]", "[redacted]"]
    assert len(cleaned["b"]) == galtea.TEXT_LIMIT
    assert cleaned["c"] == 3


def test_a_galtea_failure_is_swallowed_and_not_retried(tmp_path: Path) -> None:
    project = make_project(tmp_path, {"parent": with_product(PARENT_SKILL, "p"), "child": CHILD_SKILL})
    run_id, _ = start_run(project, "parent", {}, mode="interactive", harness="generic")
    submit_answer(project, run_id, "text: Hello.\n")
    fake = FakeGaltea(fail_on="/products")

    upload(project, run_id, fake)
    calls_after_first_upload = len(fake.calls)
    upload(project, run_id, fake)

    assert len(fake.calls) == calls_after_first_upload
    assert read_json(project.runs_folder / run_id / "galtea.json")["last_seq"] > 0


def test_an_unreadable_run_is_ignored(tmp_path: Path) -> None:
    project = make_project(tmp_path, {})

    galtea.upload_run(project, "r-missing", make_client=FakeGaltea().client, environment=KEY)


# --- parallel tasks ---------------------------------------------------------------------------------


def test_parallel_task_turns_name_their_tier_model(tmp_path: Path) -> None:
    tiered = PARALLEL_SKILL.replace("    agent: checker\n", "    agent: checker\n    tier: deep\n")
    project = make_project(tmp_path, {"fanout": with_product(tiered, "f")})
    run_id, _ = start_run(project, "fanout", {"files": ["a.md", "b.md"]}, mode="interactive", harness="claude-code")
    submit_answer(project, run_id, "wrong: []\n", task=0)
    fake = FakeGaltea()

    upload(project, run_id, fake)

    [version] = fake.bodies("POST", "/versions/get-or-create")
    assert '"deep": "opus"' in version["facts"]["tiers"]
    root = fake.bodies("POST", "/traces/batch?includeRejected=true")[0]["traces"][0]
    assert root["metadata"]["task"] == 0
    assert root["metadata"]["tier_model"] == "opus"


@pytest.mark.parametrize(("tier", "expected"), [("deep", "opus"), ("other", "inherited")])
def test_a_project_tier_row_replaces_the_default_model(tmp_path: Path, tier: str, expected: str) -> None:
    project = make_project(tmp_path, {})
    upload_state = galtea.RunUpload.__new__(galtea.RunUpload)
    upload_state.project = project
    upload_state.info = {"harness": "claude-code"}  # type: ignore[typeddict-item]

    assert upload_state.tier_model(tier) == expected


def test_the_default_client_talks_to_galtea_over_urllib() -> None:
    assert isinstance(galtea.default_client("gsk_test"), GalteaClient)


def test_a_failing_block_of_a_skill_without_a_product_sends_nothing(tmp_path: Path) -> None:
    failing = SCRIPT_SKILL.replace(
        "\"import json; print(json.dumps({'files': ['a.md', 'b.md']}))\"", '"import sys; sys.exit(3)"'
    )
    project = make_project(tmp_path, {"scripted": failing})
    run_id, _ = start_run(project, "scripted", {}, mode="interactive", harness="generic")
    fake = FakeGaltea()

    upload(project, run_id, fake)

    assert fake.calls == []


def test_a_pause_and_resume_inside_a_block_are_spans_of_its_turn(tmp_path: Path) -> None:
    project = make_project(tmp_path, {"parent": with_product(PARENT_SKILL, "p"), "child": CHILD_SKILL})
    run_id, _ = start_run(project, "parent", {}, mode="interactive", harness="generic")
    pause_run(project, run_id)
    resume_run(project, run_id)
    submit_answer(project, run_id, "text: Hello.\n")
    fake = FakeGaltea()

    upload(project, run_id, fake)

    spans = fake.bodies("POST", "/traces/batch?includeRejected=true")[0]["traces"]
    assert [span["name"] for span in spans] == ["greet", "run paused", "run resumed"]
    assert spans[1]["metadata"] == {"reason": "paused_by_user"}


def test_two_sessions_of_one_product_share_its_product_id(tmp_path: Path) -> None:
    project = make_project(
        tmp_path, {"parent": with_product(PARENT_SKILL, "p"), "child": with_product(CHILD_SKILL, "p")}
    )
    run_id, _ = start_run(project, "parent", {}, mode="interactive", harness="generic")
    submit_answer(project, run_id, "text: Hello from the parent.\n")
    submit_answer(project, run_id, "text: Hello, Ada!\n")
    fake = FakeGaltea()

    upload(project, run_id, fake)

    assert len(fake.bodies("GET", "/products?names=p")) == 1
    assert len(fake.bodies("POST", "/sessions")) == 2


def test_a_failed_metadata_update_is_swallowed(tmp_path: Path) -> None:
    extra = '  metadata:\n    run: "{{ run.id }}"\n'
    project = make_project(tmp_path, {"parent": with_product(PARENT_SKILL, "p", extra), "child": CHILD_SKILL})
    run_id, _ = start_run(project, "parent", {}, mode="interactive", harness="generic")
    submit_answer(project, run_id, "text: Hi.\n")
    fake = FakeGaltea(fail_on="/sessions/ses")

    upload(project, run_id, fake)

    assert any(path.startswith("/sessions/ses") for _, path, _ in fake.calls)


def test_a_task_with_no_tier_or_a_finished_block_names_no_model(tmp_path: Path) -> None:
    project = make_project(tmp_path, {"fanout": with_product(PARALLEL_SKILL, "f")})
    run_id, _ = start_run(project, "fanout", {"files": ["a.md", "b.md"]}, mode="interactive", harness="claude-code")
    submit_answer(project, run_id, "wrong: []\n", task=0)
    submit_answer(project, run_id, "wrong: []\n", task=1)
    fake = FakeGaltea()

    upload(project, run_id, fake)

    roots = [batch["traces"][0] for batch in fake.bodies("POST", "/traces/batch?includeRejected=true")]
    task_roots = [root for root in roots if "task" in root["metadata"]]
    assert len(task_roots) == 2
    assert all("tier_model" not in root["metadata"] for root in task_roots)


def test_an_unreachable_galtea_is_tried_once_per_command(tmp_path: Path) -> None:
    project = make_project(tmp_path, {"scripted": with_product(SCRIPT_SKILL, "s")})
    run_id, _ = start_run(project, "scripted", {}, mode="interactive", harness="generic")
    fake = FakeGaltea(fail_on="/products")

    upload(project, run_id, fake)

    assert len(fake.calls) == 1  # the script turn and the end turn would each try again
    assert read_json(project.runs_folder / run_id / "galtea.json")["last_seq"] > 0


def test_an_odd_galtea_reply_skips_only_its_event(tmp_path: Path) -> None:
    project = make_project(tmp_path, {"scripted": with_product(SCRIPT_SKILL, "s")})
    run_id, _ = start_run(project, "scripted", {}, mode="interactive", harness="generic")
    fake = FakeGaltea(products=[{"name": "s"}])  # a product with no id

    upload(project, run_id, fake)

    assert len(fake.bodies("GET", "/products?names=s")) == 2  # one try for each of the two turns


def test_a_session_that_another_command_created_is_reused(tmp_path: Path) -> None:
    project = make_project(tmp_path, {"scripted": with_product(SCRIPT_SKILL, "s")})
    run_id, _ = start_run(project, "scripted", {}, mode="interactive", harness="generic")
    fake = FakeGaltea(sessions=[{"id": "ses_other"}])

    upload(project, run_id, fake)

    assert fake.bodies("POST", "/sessions") == []
    assert {turn["sessionId"] for turn in fake.bodies("POST", "/inferenceResults")} == {"ses_other"}


def test_an_http_error_from_galtea_does_not_stop_the_command(tmp_path: Path) -> None:
    project = make_project(tmp_path, {"scripted": with_product(SCRIPT_SKILL, "s")})
    run_id, _ = start_run(project, "scripted", {}, mode="interactive", harness="generic")
    refused = urllib.error.HTTPError("https://api.galtea.ai/products", 400, "Bad Request", Message(), None)
    fake = FakeGaltea(fail_on="/products", error=refused)

    upload(project, run_id, fake)

    assert len(fake.bodies("GET", "/products?names=s")) == 2  # each turn tries again
