"""Settings for every test."""

import pytest


@pytest.fixture(autouse=True)
def no_galtea_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """Hide a Galtea key of the shell that runs the tests, so that no test uploads a run to Galtea."""
    monkeypatch.delenv("GALTEA_API_KEY", raising=False)
