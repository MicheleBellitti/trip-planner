"""The offline guard of tests/conftest.py: no test can reach the Anthropic API.

anthropic 1.13.0 runs on `httpx2`, which respx does not patch, so a mocked-by-mistake SDK call
would otherwise go to the network with whatever credentials the machine has.
"""

from __future__ import annotations

import os

import anthropic
import httpx
import httpx2
import pytest

from tests.conftest import OFFLINE_ANTHROPIC_ENV


def test_every_sdk_environment_variable_is_neutralized() -> None:
    for key, value in OFFLINE_ANTHROPIC_ENV.items():
        assert os.environ.get(key) == value, key


def test_a_client_without_explicit_credentials_refuses_to_build() -> None:
    with pytest.raises(anthropic.AnthropicError):
        anthropic.AsyncAnthropic()


async def test_an_unmocked_sdk_call_fails_locally_without_traffic() -> None:
    sdk = anthropic.AsyncAnthropic(api_key="sk-test-not-a-real-key", max_retries=0)

    assert str(sdk.base_url).startswith("http://127.0.0.1:9")
    with pytest.raises(anthropic.APIConnectionError):
        await sdk.beta.sessions.retrieve("sesn_test")


async def test_the_sdk_rejects_an_httpx_client_so_respx_cannot_mock_it() -> None:
    async with httpx.AsyncClient() as http:
        with pytest.raises(TypeError, match="httpx2"):
            anthropic.AsyncAnthropic(
                api_key="sk-test-not-a-real-key",
                http_client=http,  # pyright: ignore[reportArgumentType]  # the point of the test
            )


async def test_an_httpx2_mock_transport_is_the_sdk_test_seam() -> None:
    seen: list[str] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request.url.path)
        return httpx2.Response(404, json={"type": "error", "error": {"type": "not_found_error"}})

    sdk = anthropic.AsyncAnthropic(
        api_key="sk-test-not-a-real-key",
        base_url="http://ma.test",
        max_retries=0,
        http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(handler)),
    )
    with pytest.raises(anthropic.NotFoundError):
        await sdk.beta.sessions.retrieve("sesn_test")

    assert seen == ["/v1/sessions/sesn_test"]
