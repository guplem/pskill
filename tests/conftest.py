"""Settings for every test."""

import pytest


@pytest.fixture(autouse=True)
def no_galtea_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """Hide a Galtea key of the shell that runs the tests, so that no test uploads a run to Galtea."""
    monkeypatch.delenv("GALTEA_API_KEY", raising=False)


@pytest.fixture(autouse=True)
def no_worktree_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    """Hide the worktree mode of the shell that runs the tests, so that no run starts in a worktree by chance."""
    monkeypatch.delenv("PSKILL_RUN_IN_WORKTREE", raising=False)
