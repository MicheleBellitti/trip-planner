"""Anthropic credentials: an API key, or Workload Identity Federation (dev, CI, production).

Everything here is offline: the federation config is a temporary token file and fake ids, and
building a client never exchanges the token (the SDK does that lazily, at the first request).
The offline guard of conftest.py stays in force; each test sets only the variables it needs.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from app.config import Settings
from app.ma_client import (
    MAX_RETRIES,
    REQUEST_TIMEOUT_SECONDS,
    SdkManagedAgentsClient,
    anthropic_client_kwargs,
    build_async_anthropic,
)

MakeSettings = Callable[..., Settings]

FAKE_TOKEN = "fake.identity.token-not-a-secret"


def _isolate_from_profiles(monkeypatch: pytest.MonkeyPatch, home: Path) -> None:
    """The offline guard points ANTHROPIC_CONFIG_DIR at a missing directory, which makes the SDK
    pick a profile (it ranks above env-var federation). Remove it, and give the SDK an empty
    HOME so no `active_config` pointer of the developer's machine is found either."""
    monkeypatch.delenv("ANTHROPIC_CONFIG_DIR", raising=False)
    monkeypatch.delenv("ANTHROPIC_PROFILE", raising=False)
    monkeypatch.setenv("HOME", str(home))


@pytest.fixture
def federation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """A fake federation config: Settings overrides, and the same values in the process
    environment, where the SDK reads them."""
    token_file = tmp_path / "identity-token"
    token_file.write_text(FAKE_TOKEN, encoding="utf-8")
    _isolate_from_profiles(monkeypatch, tmp_path)
    monkeypatch.setenv("ANTHROPIC_IDENTITY_TOKEN_FILE", str(token_file))
    monkeypatch.setenv("ANTHROPIC_FEDERATION_RULE_ID", "fdrl_fake")
    monkeypatch.setenv("ANTHROPIC_ORGANIZATION_ID", "org-fake")
    monkeypatch.setenv("ANTHROPIC_WORKSPACE_ID", "wrkspc_fake")
    return {
        "anthropic_identity_token_file": str(token_file),
        "anthropic_federation_rule_id": "fdrl_fake",
        "anthropic_organization_id": "org-fake",
        "anthropic_workspace_id": "wrkspc_fake",
    }


# --- Settings ---------------------------------------------------------------------------------


def test_no_credentials_by_default(make_settings: MakeSettings) -> None:
    settings = make_settings()

    assert settings.anthropic_auth_mode is None
    assert not settings.anthropic_credentials_available
    assert not settings.anthropic_federation_configured


def test_the_api_key_is_a_credential(make_settings: MakeSettings) -> None:
    settings = make_settings(anthropic_api_key="sk-ant-test-not-a-real-key")

    assert settings.anthropic_auth_mode == "api_key"
    assert settings.anthropic_credentials_available


def test_federation_is_a_credential_in_development(
    make_settings: MakeSettings, federation: dict[str, Any]
) -> None:
    settings = make_settings(**federation)

    assert settings.anthropic_federation_configured
    assert settings.anthropic_auth_mode == "federation"
    assert settings.anthropic_credentials_available


def test_a_literal_identity_token_counts_and_stays_secret(make_settings: MakeSettings) -> None:
    settings = make_settings(
        anthropic_identity_token=FAKE_TOKEN,
        anthropic_federation_rule_id="fdrl_fake",
        anthropic_organization_id="org-fake",
    )

    assert settings.anthropic_auth_mode == "federation"
    assert FAKE_TOKEN not in repr(settings)
    assert FAKE_TOKEN not in str(settings.model_dump())


@pytest.mark.parametrize(
    "missing",
    ["anthropic_federation_rule_id", "anthropic_organization_id", "anthropic_identity_token_file"],
)
def test_federation_needs_the_rule_the_organization_and_a_token(
    make_settings: MakeSettings, federation: dict[str, Any], missing: str
) -> None:
    federation[missing] = "  "  # blank means unset

    settings = make_settings(**federation)

    assert not settings.anthropic_federation_configured
    assert settings.anthropic_auth_mode is None


def test_the_workspace_is_optional(make_settings: MakeSettings, federation: dict[str, Any]) -> None:
    federation["anthropic_workspace_id"] = ""

    settings = make_settings(**federation)

    assert settings.anthropic_workspace_id is None
    assert settings.anthropic_auth_mode == "federation"


def test_the_key_wins_over_federation(
    make_settings: MakeSettings, federation: dict[str, Any]
) -> None:
    settings = make_settings(anthropic_api_key="sk-ant-test-not-a-real-key", **federation)

    assert settings.anthropic_auth_mode == "api_key"


def test_production_accepts_federation_when_configured(
    make_settings: MakeSettings, federation: dict[str, Any]
) -> None:
    # No stored key, but full federation config: production starts and uses federation, so
    # Railway can run without a long-lived key (docs/security-hardening.md).
    settings = make_settings(
        environment="production",
        auth_mode="triptracker",
        agent_profile="production",
        **federation,
    )

    assert settings.anthropic_auth_mode == "federation"
    assert settings.anthropic_credentials_available


def test_production_refuses_no_credentials(make_settings: MakeSettings) -> None:
    with pytest.raises(ValidationError, match="is required when ENVIRONMENT=production") as caught:
        make_settings(environment="production", auth_mode="triptracker", agent_profile="production")

    assert "Workload Identity Federation" in str(caught.value)


def test_production_with_the_key_still_works_next_to_federation_variables(
    make_settings: MakeSettings, federation: dict[str, Any]
) -> None:
    settings = make_settings(
        environment="production",
        auth_mode="triptracker",
        agent_profile="production",
        anthropic_api_key="sk-ant-test-not-a-real-key",
        **federation,
    )

    assert settings.anthropic_auth_mode == "api_key"


# --- the client -------------------------------------------------------------------------------


def test_kwargs_with_a_key_pass_it_explicitly(make_settings: MakeSettings) -> None:
    kwargs = anthropic_client_kwargs(
        make_settings(anthropic_api_key=" sk-ant-test-not-a-real-key "),
        max_retries=MAX_RETRIES,
        timeout=REQUEST_TIMEOUT_SECONDS,
    )

    assert kwargs == {
        "api_key": "sk-ant-test-not-a-real-key",
        "max_retries": 4,
        "timeout": REQUEST_TIMEOUT_SECONDS,
    }


def test_kwargs_under_federation_carry_no_api_key(
    make_settings: MakeSettings, federation: dict[str, Any]
) -> None:
    kwargs = anthropic_client_kwargs(make_settings(**federation), max_retries=2)

    assert kwargs == {"max_retries": 2}


def test_kwargs_without_credentials_raise(make_settings: MakeSettings) -> None:
    with pytest.raises(ValueError, match="ANTHROPIC_API_KEY"):
        anthropic_client_kwargs(make_settings(), max_retries=2)


def test_the_federation_client_is_built_with_credentials_and_no_key(
    make_settings: MakeSettings, federation: dict[str, Any]
) -> None:
    client = SdkManagedAgentsClient.from_settings(make_settings(**federation))

    sdk = client._sdk
    assert sdk.api_key is None
    assert sdk.auth_token is None
    assert sdk.credentials is not None  # the SDK resolved env-var federation by itself
    assert sdk.max_retries == MAX_RETRIES
    assert sdk.timeout == REQUEST_TIMEOUT_SECONDS
    once = client._sdk_once
    assert once.max_retries == 0
    assert once.api_key is None
    assert once.credentials is not None


def test_the_judge_style_client_is_built_the_same_way(
    make_settings: MakeSettings, federation: dict[str, Any]
) -> None:
    sdk = build_async_anthropic(make_settings(**federation), max_retries=2)

    assert sdk.api_key is None
    assert sdk.credentials is not None
    assert sdk.max_retries == 2


def test_the_key_beats_federation_in_the_sdk_too(
    make_settings: MakeSettings, federation: dict[str, Any]
) -> None:
    client = SdkManagedAgentsClient.from_settings(
        make_settings(anthropic_api_key="sk-ant-test-not-a-real-key", **federation)
    )

    assert client._sdk.api_key == "sk-ant-test-not-a-real-key"
    assert client._sdk.credentials is None
