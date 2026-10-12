"""Fixtures for the scripts' tests. Everything is offline.

Run from backend/: `uv run pytest ../scripts -q` (the backend venv has anthropic, httpx2, PyYAML,
jsonschema). The Anthropic SDK is only ever driven through `httpx2.MockTransport`; every
credential variable is blanked and ANTHROPIC_BASE_URL points at a closed local port, so a
forgotten mock fails instead of reaching the network. Shared helpers live in scripts_testlib.py.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from scripts_testlib import CLOSED_PORT_URL, CREDENTIAL_VARS, FakeAnthropicApi, make_fake_repo


@pytest.fixture(autouse=True)
def _offline(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in CREDENTIAL_VARS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("ANTHROPIC_BASE_URL", CLOSED_PORT_URL)
    monkeypatch.delenv("CI", raising=False)


@pytest.fixture
def fake_repo(tmp_path: Path) -> Path:
    """A copy of the repository's agent sources with stub skills, rendered: what bootstrap
    and the renderer read, isolated from the real tree (other teams write skills/ in parallel)."""
    return make_fake_repo(tmp_path)


@pytest.fixture
def fake_api() -> FakeAnthropicApi:
    return FakeAnthropicApi()
