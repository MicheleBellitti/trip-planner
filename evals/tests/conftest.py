"""Offline test setup for evals/: import paths and the Anthropic offline guard.

Run from backend/ (its venv has pydantic, pyyaml, jsonschema and the `app` package):

    cd backend && uv run pytest ../evals/tests -q

backend/pyproject.toml is not an ancestor of these files, so pytest does not read it here:
this file puts backend/ (for `app`) and evals/ (for `checks`, `judge`, `run`, `compare`) on
sys.path, and the tests are plain synchronous functions (no pytest-asyncio settings needed).
Nothing here calls the Anthropic API, a Managed Agents session, Postgres or any network: the
judge is driven by a fake client and the SDK credentials are blanked as a safety net.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

TESTS_DIR = Path(__file__).resolve().parent
EVALS_DIR = TESTS_DIR.parent
BACKEND_DIR = EVALS_DIR.parent / "backend"

for path in (BACKEND_DIR, EVALS_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

OFFLINE_ANTHROPIC_ENV: dict[str, str | None] = {
    "ANTHROPIC_API_KEY": "",
    "ANTHROPIC_AUTH_TOKEN": "",
    "ANTHROPIC_BASE_URL": "http://127.0.0.1:9",  # discard port: connection refused
    "ANTHROPIC_CONFIG_DIR": "/nonexistent/trip-planner-evals-tests/anthropic",
    "ANTHROPIC_PROFILE": None,
    "ANTHROPIC_IDENTITY_TOKEN": None,
    "ANTHROPIC_IDENTITY_TOKEN_FILE": None,
    "ANTHROPIC_FEDERATION_RULE_ID": None,
    "ANTHROPIC_ORGANIZATION_ID": None,
    "ANTHROPIC_WORKSPACE_ID": None,
}

for key, value in OFFLINE_ANTHROPIC_ENV.items():
    if value is None:
        os.environ.pop(key, None)
    else:
        os.environ[key] = value


@pytest.fixture(autouse=True)
def _offline_anthropic(monkeypatch: pytest.MonkeyPatch) -> None:
    for key, value in OFFLINE_ANTHROPIC_ENV.items():
        if value is None:
            monkeypatch.delenv(key, raising=False)
        else:
            monkeypatch.setenv(key, value)
