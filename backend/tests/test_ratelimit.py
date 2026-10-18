"""app/ratelimit.py: the sliding window, the stream counter, the client IP rule."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import Request
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from app.ratelimit import Decision, SlidingWindow, StreamCounter, client_ip


class Clock:
    def __init__(self, start: float = 1000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now


def test_sliding_window_allows_the_limit_then_refuses_until_the_oldest_leaves() -> None:
    clock = Clock()
    window = SlidingWindow(limit=3, window_seconds=60, now=clock)

    allowed = []
    for _ in range(3):  # at +0, +10, +20
        allowed.append(window.hit("a").allowed)
        clock.now += 10
    assert allowed == [True, True, True]
    clock.now -= 10  # back at +20
    assert window.hit("a") == Decision(
        allowed=False, retry_after_seconds=40
    )  # the +0 hit leaves at +60

    clock.now = 1059.5
    assert window.hit("a") == Decision(allowed=False, retry_after_seconds=1)
    clock.now = 1060.0
    assert window.hit("a").allowed is True  # the +0 hit left: one slot
    assert window.hit("a") == Decision(
        allowed=False, retry_after_seconds=10
    )  # until the +10 hit leaves


def test_sliding_window_keys_are_independent_and_a_refusal_records_nothing() -> None:
    clock = Clock()
    window = SlidingWindow(limit=1, window_seconds=10, now=clock)
    assert window.hit("a").allowed
    assert window.hit("b").allowed
    assert not window.hit("a").allowed
    clock.now += 10
    assert window.hit("a").allowed  # the refusal did not extend the window


def test_sliding_window_forgets_keys_without_recent_hits() -> None:
    clock = Clock()
    window = SlidingWindow(limit=2, window_seconds=10, now=clock)
    window.hit("a")
    window.hit("b")
    clock.now += 11
    window.hit("a")  # sweeps a's old hit, keeps the key
    assert len(window) == 1  # b's empty deque is swept by __len__
    window.forget("a")
    assert len(window) == 0


def test_stream_counter_holds_the_limit_and_releases() -> None:
    streams = StreamCounter(limit=2)
    assert streams.acquire("u").allowed
    assert streams.acquire("u").allowed
    assert streams.acquire("u") == Decision(allowed=False, retry_after_seconds=5)
    assert streams.held("u") == 2
    streams.release("u")
    assert streams.acquire("u").allowed
    streams.release("u")
    streams.release("u")
    streams.release("u")  # one too many: never negative
    assert streams.held("u") == 0
    assert streams.acquire("v").allowed


def test_sliding_window_drops_the_keys_whose_events_left_the_window() -> None:
    clock = Clock()
    window = SlidingWindow(limit=2, window_seconds=60, now=clock)
    for n in range(100):
        window.hit(f"203.0.113.{n}")
    assert len(window._hits) == 100  # pyright: ignore[reportPrivateUsage]

    clock.now += 61
    window.hit("198.51.100.1")  # the first hit after a window sweeps the stale keys

    assert list(window._hits) == ["198.51.100.1"]  # pyright: ignore[reportPrivateUsage]


def test_sliding_window_undo_takes_back_one_allowed_hit() -> None:
    clock = Clock()
    window = SlidingWindow(limit=1, window_seconds=60, now=clock)
    first = window.hit("a")
    assert first.allowed
    refused = window.hit("a")
    assert not refused.allowed

    window.undo("a", refused)  # a refusal recorded nothing: nothing to take back
    assert not window.hit("a").allowed
    window.undo("a", first)
    assert "a" not in window._hits  # pyright: ignore[reportPrivateUsage]
    assert window.hit("a").allowed


def request_with(headers: dict[str, str], client: tuple[str, int] | None) -> Request:
    scope: dict[str, Any] = {
        "type": "http",
        "method": "GET",
        "path": "/",
        "query_string": b"",
        "headers": [(key.lower().encode(), value.encode()) for key, value in headers.items()],
        "client": client,
    }
    return Request(scope)


@pytest.mark.parametrize(
    ("headers", "client", "trust", "expected"),
    [
        ({}, ("10.0.0.7", 1234), False, "10.0.0.7"),
        ({"X-Forwarded-For": "203.0.113.9"}, ("10.0.0.7", 1234), False, "10.0.0.7"),
        ({"X-Forwarded-For": "203.0.113.9"}, ("10.0.0.7", 1234), True, "203.0.113.9"),
        # The client's own forged values come first; the proxy appends the real one last.
        (
            {"X-Forwarded-For": "1.1.1.1, 2.2.2.2, 203.0.113.9"},
            ("10.0.0.7", 1234),
            True,
            "203.0.113.9",
        ),
        ({"X-Forwarded-For": "  "}, ("10.0.0.7", 1234), True, "10.0.0.7"),
        ({}, None, True, "unknown"),
    ],
)
def test_client_ip(
    headers: dict[str, str], client: tuple[str, int] | None, trust: bool, expected: str
) -> None:
    assert client_ip(request_with(headers, client), trust_proxy=trust) == expected


def test_client_ip_reads_every_forwarded_header_in_order() -> None:
    # A client that sends its own X-Forwarded-For may get the proxy's value in a second header.
    scope: dict[str, Any] = {
        "type": "http",
        "method": "GET",
        "path": "/",
        "query_string": b"",
        "headers": [
            (b"x-forwarded-for", b"9.9.9.9"),
            (b"x-forwarded-for", b"203.0.113.9"),
        ],
        "client": ("10.0.0.7", 1234),
    }
    assert client_ip(Request(scope), trust_proxy=True) == "203.0.113.9"


async def test_behind_uvicorns_proxy_headers_only_the_last_value_is_safe() -> None:
    """The image runs uvicorn with --proxy-headers and FORWARDED_ALLOW_IPS="*": it rewrites
    request.client to the leftmost X-Forwarded-For value, the one the client chose. That is why
    TRUST_PROXY_HEADERS must stay on behind Railway."""
    seen: dict[str, str] = {}

    async def app(scope: Any, receive: Any, send: Any) -> None:
        request = Request(scope)
        seen["client"] = request.client.host if request.client else ""
        seen["key"] = client_ip(request, trust_proxy=True)

    wrapped = ProxyHeadersMiddleware(app, trusted_hosts="*")
    scope: dict[str, Any] = {
        "type": "http",
        "method": "GET",
        "path": "/",
        "query_string": b"",
        "headers": [(b"x-forwarded-for", b"6.6.6.6, 203.0.113.9")],
        "client": ("100.64.0.2", 4321),  # Railway's edge
    }
    await wrapped(scope, None, None)  # pyright: ignore[reportArgumentType]

    assert seen == {"client": "6.6.6.6", "key": "203.0.113.9"}
