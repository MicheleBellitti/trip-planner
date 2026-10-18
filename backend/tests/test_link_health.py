"""app.link_health: the pure helpers (URL collection, homepage, public addresses, soft 404),
the HTTP checker and the transport pinned to public addresses. Offline: a fake resolver and
httpx.MockTransport over a respx router; only `system_resolver` resolves, and only localhost."""

from __future__ import annotations

import asyncio
import datetime as dt
import ipaddress
import logging
import socket
import ssl
import time
from collections.abc import AsyncIterator, Callable, Iterable
from pathlib import Path
from typing import Any

import httpcore
import httpx
import pytest
import respx
import structlog
from structlog.testing import LogCapture
from structlog.typing import EventDict

from app import link_health
from app.config import Settings
from app.link_health import (
    NO_LINK_CHECKS,
    HostNotFoundError,
    HttpLinkChecker,
    LinkHealth,
    LinkHealthMap,
    PinnedNetworkBackend,
    build_link_checker,
    collect_plan_urls,
    homepage_of,
    is_public_address,
    looks_not_found,
    system_resolver,
)
from app.plan import Plan
from tests.test_mapping import make_plan

BOOKING_LINK = "https://www.expedia.it/Flights-Search?trip=roundtrip"
STOP_URL = "https://www.museoegizio.it/"
ALT_LINK = "https://www.booking.com/hotel/it/alt.html"


def booking(**fields: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "title": "Volo Milano Torino",
        "kind": "transport",
        "scheduled_for": "2027-06-14T09:00:00+02:00",
    }
    data.update(fields)
    return data


def price(source_url: str) -> dict[str, Any]:
    return {
        "amount_cents": 10000,
        "currency": "EUR",
        "status": "verified",
        "source_url": source_url,
        "retrieved_at": "2026-10-12T09:15:00+02:00",
    }


def test_collect_plan_urls_dedupes_in_first_seen_order() -> None:
    plan = make_plan(bookings=[booking(link=BOOKING_LINK, price=price(STOP_URL))])
    plan.days[0].stops[0].url = STOP_URL
    assert collect_plan_urls(plan) == [BOOKING_LINK, STOP_URL]


def test_collect_plan_urls_covers_alternatives_stops_and_prices() -> None:
    plan = make_plan(
        bookings=[booking(link=BOOKING_LINK)],
        alternatives=[booking(link=ALT_LINK, price=price("https://www.booking.com/src"))],
    )
    plan.days[0].stops[0].url = STOP_URL
    assert collect_plan_urls(plan) == [
        BOOKING_LINK,
        ALT_LINK,
        STOP_URL,
        "https://www.booking.com/src",
    ]


def test_collect_plan_urls_empty_plan() -> None:
    assert collect_plan_urls(make_plan()) == []


@pytest.mark.parametrize(
    ("url", "home"),
    [
        ("https://www.carris.pt/tarifas/aeroporto", "https://www.carris.pt/"),
        ("http://example.org:8080/a?b=1", "http://example.org:8080/"),
        ("https://www.carris.pt/", None),
        ("https://www.carris.pt", None),
        ("https://www.carris.pt/?a=1", "https://www.carris.pt/"),
        ("not a url", None),
    ],
)
def test_homepage_of(url: str, home: str | None) -> None:
    assert homepage_of(url) == home


@pytest.mark.parametrize(
    ("address", "public"),
    [
        ("93.184.216.34", True),
        ("2606:4700::1111", True),
        ("10.0.0.1", False),
        ("172.16.5.4", False),
        ("192.168.1.1", False),
        ("127.0.0.1", False),
        ("169.254.169.254", False),
        ("100.64.0.1", False),
        ("0.0.0.0", False),
        ("224.0.0.1", False),
        ("::1", False),
        ("fd00::1", False),
        ("fe80::1", False),
        ("::ffff:10.0.0.1", False),
        ("::ffff:93.184.216.34", True),
        # IPv6 that embeds an IPv4 address: public only when the IPv4 address is.
        ("2002:0a00:0001::1", False),  # 6to4 of 10.0.0.1
        ("2001:0:4136:e378:8000:63bf:f5ff:fffe", False),  # Teredo, client 10.0.0.1
        ("64:ff9b::a00:1", False),  # NAT64 of 10.0.0.1
        ("64:ff9b::7f00:1", False),  # NAT64 of 127.0.0.1
        ("64:ff9b::5db8:d822", True),  # NAT64 of 93.184.216.34
        # Deprecated forms that Python still calls global.
        ("::a00:1", False),  # IPv4-compatible
        ("::ffff:0:a00:1", False),  # IPv4-translated
        ("fec0::1", False),  # site-local
    ],
)
def test_is_public_address(address: str, public: bool) -> None:
    assert is_public_address(ipaddress.ip_address(address)) is public


@pytest.mark.parametrize(
    ("title", "dead"),
    [
        ("Pagina non trovata - Carris", True),
        ("404 Not Found", True),
        ("Page not found", True),
        ("Página no encontrada", True),
        ("Página não encontrada", True),
        ("Page introuvable", True),
        ("Seite nicht gefunden", True),
        ("Errore 404 - pagina non trovata", True),
        ("Linea 404 · Carris", False),
        ("Tarifas | Carris", False),
    ],
)
def test_looks_not_found_reads_the_title(title: str, dead: bool) -> None:
    body = f"<html><head><title>{title}</title></head></html>".encode()
    assert looks_not_found("text/html; charset=utf-8", body) is dead


def test_looks_not_found_ignores_non_html() -> None:
    assert looks_not_found("application/pdf", b"<title>Page not found</title>") is False
    assert looks_not_found(None, b"<title>Page not found</title>") is False


def test_looks_not_found_handles_whitespace_entities_and_no_title() -> None:
    assert looks_not_found("text/html", b"<TITLE>\n  Page\n  Not   Found </TITLE>") is True
    assert looks_not_found("text/html", b"<title>Pagina non trovata &amp; altro</title>") is True
    assert looks_not_found("text/html", b"<html><body>Page not found</body></html>") is False
    assert looks_not_found("text/html", b"\xff\xfe<title>ok</title>") is False


def dead_map() -> LinkHealthMap:
    return LinkHealthMap.from_json(
        {
            "https://a.example/x": {
                "status": "dead",
                "reason": "http_404",
                "fallback": "https://a.example/",
                "fallback_allowed": False,
            },
            "https://b.example/y": {
                "status": "dead",
                "reason": "http_410",
                "fallback": "https://b.example/",
                "fallback_allowed": True,
            },
            "https://c.example/z": {"status": "dead", "reason": "nxdomain"},
            "https://d.example/": {"status": "unknown", "reason": "http_503"},
        }
    )


def test_resolve_dead_with_fallback_and_booking_rule() -> None:
    health = LinkHealthMap.from_json(
        {
            "https://a.example/x": {
                "status": "dead",
                "reason": "http_404",
                "fallback": "https://a.example/",
                "fallback_allowed": False,
            },
        }
    )
    assert health.resolve("https://a.example/x") == "https://a.example/"
    assert health.resolve("https://a.example/x", booking=True) is None
    assert health.resolve("https://other.example/") == "https://other.example/"
    assert health.resolve(None) is None


def test_resolve_booking_uses_fallback_only_when_allowed() -> None:
    health = dead_map()
    assert health.resolve("https://b.example/y", booking=True) == "https://b.example/"
    assert health.resolve("https://c.example/z") is None
    assert health.resolve("https://d.example/") == "https://d.example/"


def test_counts_and_get() -> None:
    health = dead_map()
    assert health.counts() == {"ok": 0, "dead": 3, "unknown": 1}
    assert health.get("https://d.example/") == LinkHealth(status="unknown", reason="http_503")
    assert health.get("https://nope.example/") is None


def test_from_json_tolerates_null_and_malformed_entries() -> None:
    assert LinkHealthMap.from_json(None).to_json() == {}
    assert LinkHealthMap.from_json({"u": {"status": "weird"}, "v": 3}).to_json() == {}
    assert LinkHealthMap.from_json([1, 2]).to_json() == {}
    assert LinkHealthMap.empty().to_json() == {}


def test_json_round_trip_with_checked_at() -> None:
    checked = dt.datetime(2026, 10, 18, 9, 30, tzinfo=dt.UTC)
    health = LinkHealthMap.from_json(
        {
            "https://a.example/x": {
                "status": "dead",
                "reason": "soft_404",
                "http_status": 200,
                "fallback": "https://a.example/",
                "fallback_allowed": True,
                "checked_at": checked.isoformat(),
            }
        }
    )
    entry = health.get("https://a.example/x")
    assert entry == LinkHealth(
        status="dead",
        reason="soft_404",
        http_status=200,
        fallback="https://a.example/",
        fallback_allowed=True,
        checked_at=checked,
    )
    assert LinkHealthMap.from_json(health.to_json()).to_json() == health.to_json()
    assert health.to_json()["https://a.example/x"]["checked_at"] == checked.isoformat()


# --- the HTTP checker -------------------------------------------------------------------------

NOW = dt.datetime(2026, 10, 18, 9, 30, tzinfo=dt.UTC)
USER_AGENT = "AtlasLinkCheck/1.0 (+https://atlas.example)"
PUBLIC_ADDRESS = "93.184.216.34"
PAGE = "https://a.example/x"
HOME = "https://a.example/"


class FakeResolver:
    """Host -> addresses (default: one public address), or an exception to raise."""

    def __init__(self, answers: dict[str, list[str] | Exception] | None = None) -> None:
        self.answers = answers or {}
        self.calls: list[str] = []

    async def __call__(self, host: str) -> list[ipaddress.IPv4Address | ipaddress.IPv6Address]:
        self.calls.append(host)
        answer = self.answers.get(host, [PUBLIC_ADDRESS])
        if isinstance(answer, Exception):
            raise answer
        return [ipaddress.ip_address(address) for address in answer]


@pytest.fixture
def router() -> respx.MockRouter:
    return respx.MockRouter(assert_all_called=False)


def make_checker(
    router: respx.MockRouter, resolver: FakeResolver | None = None, **options: Any
) -> HttpLinkChecker:
    return HttpLinkChecker(
        transport=httpx.MockTransport(router.async_handler),
        resolver=resolver or FakeResolver(),
        user_agent=USER_AGENT,
        now=lambda: NOW,
        **options,
    )


def verdict(health: LinkHealth) -> tuple[str, str]:
    return health.status, health.reason


def entry_of(health: LinkHealthMap, url: str) -> LinkHealth:
    found = health.get(url)
    assert found is not None, url
    return found


def plan_with_urls(*urls: str) -> Plan:
    """A plan whose bookings carry `urls` as links, in order."""
    return make_plan(
        bookings=[booking(title=f"Volo {index}", link=url) for index, url in enumerate(urls)]
    )


async def test_200_is_ok(router: respx.MockRouter) -> None:
    router.get(PAGE).respond(200, html="<title>Museo Egizio</title>")
    health = await make_checker(router).check_url(PAGE)
    assert health == LinkHealth(status="ok", reason="ok", http_status=200, checked_at=NOW)


@pytest.mark.parametrize("code", [404, 410])
async def test_404_and_410_are_dead_with_reason(router: respx.MockRouter, code: int) -> None:
    router.get(PAGE).respond(code)
    router.get(HOME).respond(404)
    health = await make_checker(router).check_url(PAGE)
    assert verdict(health) == ("dead", f"http_{code}")
    assert health.http_status == code


@pytest.mark.parametrize("code", [401, 403, 405, 429, 500, 503, 300, 301, 304])
async def test_other_answers_are_unknown_never_dead(router: respx.MockRouter, code: int) -> None:
    router.get(PAGE).respond(code)
    health = await make_checker(router).check_url(PAGE)
    assert verdict(health) == ("unknown", f"http_{code}")
    assert health.fallback is None


async def test_redirect_to_404_is_dead(router: respx.MockRouter) -> None:
    router.get(PAGE).respond(301, headers={"Location": "/gone"})
    router.get("https://a.example/gone").respond(404)
    router.get(HOME).respond(404)
    health = await make_checker(router).check_url(PAGE)
    assert verdict(health) == ("dead", "http_404")


async def test_redirect_to_a_private_address_is_unknown_and_not_fetched(
    router: respx.MockRouter,
) -> None:
    router.get(PAGE).respond(302, headers={"Location": "https://intranet.example/admin"})
    resolver = FakeResolver({"intranet.example": ["10.0.0.1"]})
    health = await make_checker(router, resolver).check_url(PAGE)
    assert verdict(health) == ("unknown", "unsafe_address")
    assert router.calls.call_count == 1
    assert resolver.calls == ["a.example", "intranet.example"]


@pytest.mark.parametrize(
    "url",
    [
        "ftp://a.example/file",
        "https://user:pw@a.example/",
        "https://a.example:8443/",
        "http://a.example:22/",
        "javascript:alert(1)",
        "https:///no-host",
        "not a url",
    ],
)
async def test_unsafe_urls_are_never_fetched(router: respx.MockRouter, url: str) -> None:
    resolver = FakeResolver()
    health = await make_checker(router, resolver).check_url(url)
    assert verdict(health) == ("unknown", "unsafe_url")
    assert router.calls.call_count == 0
    assert resolver.calls == []


@pytest.mark.parametrize("url", ["http://127.0.0.1/", "http://[::1]/x", "http://10.1.2.3:80/"])
async def test_private_ip_literals_are_never_fetched(router: respx.MockRouter, url: str) -> None:
    resolver = FakeResolver()
    health = await make_checker(router, resolver).check_url(url)
    assert verdict(health) == ("unknown", "unsafe_address")
    assert router.calls.call_count == 0
    assert resolver.calls == []


async def test_a_host_with_one_private_address_is_unsafe(router: respx.MockRouter) -> None:
    resolver = FakeResolver({"a.example": [PUBLIC_ADDRESS, "192.168.1.1"]})
    health = await make_checker(router, resolver).check_url(PAGE)
    assert verdict(health) == ("unknown", "unsafe_address")
    assert router.calls.call_count == 0


async def test_redirect_to_a_non_http_url_is_unsafe(router: respx.MockRouter) -> None:
    router.get(PAGE).respond(302, headers={"Location": "file:///etc/passwd"})
    health = await make_checker(router).check_url(PAGE)
    assert verdict(health) == ("unknown", "unsafe_url")
    assert router.calls.call_count == 1


async def test_unknown_host_is_dead_without_fallback(router: respx.MockRouter) -> None:
    resolver = FakeResolver({"gone.example": HostNotFoundError("gone.example")})
    health = await make_checker(router, resolver).check_url("https://gone.example/x")
    assert health == LinkHealth(status="dead", reason="nxdomain", checked_at=NOW)
    assert resolver.calls == ["gone.example"]
    assert router.calls.call_count == 0


async def test_a_redirect_to_an_unknown_host_keeps_the_homepage_fallback(
    router: respx.MockRouter,
) -> None:
    """Only the URL's own missing host rules the fallback out; this host exists."""
    router.get(PAGE).respond(302, headers={"Location": "https://gone.example/x"})
    router.get(HOME).respond(200)
    resolver = FakeResolver({"gone.example": HostNotFoundError("gone.example")})
    health = await make_checker(router, resolver).check_url(PAGE)
    assert verdict(health) == ("dead", "redirect_nxdomain")
    assert health.fallback == HOME


async def test_a_malformed_redirect_location_is_unsafe(router: respx.MockRouter) -> None:
    router.get(PAGE).respond(302, headers={"Location": "http://[::1/"})
    health = await make_checker(router).check_url(PAGE)
    assert verdict(health) == ("unknown", "unsafe_url")
    assert router.calls.call_count == 1


async def test_a_resolver_failure_is_unknown(router: respx.MockRouter) -> None:
    resolver = FakeResolver({"a.example": OSError("temporary failure")})
    health = await make_checker(router, resolver).check_url(PAGE)
    assert verdict(health) == ("unknown", "dns_error")


async def test_soft_404_is_dead(router: respx.MockRouter) -> None:
    router.get(PAGE).respond(200, html="<html><title>Pagina non trovata</title></html>")
    router.get(HOME).respond(200, html="<title>Home</title>")
    health = await make_checker(router).check_url(PAGE)
    assert verdict(health) == ("dead", "soft_404")
    assert health.http_status == 200
    assert health.fallback == HOME


async def test_only_the_first_max_body_bytes_are_read(router: respx.MockRouter) -> None:
    late_title = b"<html>" + b" " * 70_000 + b"<title>Page not found</title></html>"
    router.get(PAGE).respond(200, content=late_title, headers={"Content-Type": "text/html"})
    health = await make_checker(router).check_url(PAGE)
    assert verdict(health) == ("ok", "ok")


@pytest.mark.parametrize(
    ("redirects", "expected"), [(5, ("ok", "ok")), (6, ("unknown", "redirects"))]
)
async def test_more_than_five_redirects_is_unknown(
    router: respx.MockRouter, redirects: int, expected: tuple[str, str]
) -> None:
    def hop(request: httpx.Request) -> httpx.Response:
        step = int(request.url.path.removeprefix("/r"))
        if step < redirects:
            return httpx.Response(302, headers={"Location": f"/r{step + 1}"})
        return httpx.Response(200)

    router.get(url__regex=r"^https://a\.example/r\d+$").mock(side_effect=hop)
    health = await make_checker(router).check_url("https://a.example/r0")
    assert verdict(health) == expected
    assert router.calls.call_count == min(redirects, 5) + 1


async def test_dead_page_gets_its_homepage_when_it_answers(router: respx.MockRouter) -> None:
    router.get(PAGE).respond(404)
    router.get(HOME).respond(200, html="<title>A</title>")
    health = await make_checker(router).check_url(PAGE)
    assert health == LinkHealth(
        status="dead",
        reason="http_404",
        http_status=404,
        fallback=HOME,
        fallback_allowed=False,
        checked_at=NOW,
    )


@pytest.mark.parametrize(
    ("home_answer", "fallback"),
    [
        (httpx.Response(503), HOME),
        (httpx.Response(404), None),
        (httpx.Response(410), None),
        (httpx.Response(200, html="<title>Page not found</title>"), None),
    ],
)
async def test_the_homepage_fallback_follows_the_homepage_verdict(
    router: respx.MockRouter, home_answer: httpx.Response, fallback: str | None
) -> None:
    router.get(PAGE).respond(404)
    router.get(HOME).mock(return_value=home_answer)
    health = await make_checker(router).check_url(PAGE)
    assert verdict(health) == ("dead", "http_404")
    assert health.fallback == fallback


async def test_dead_page_and_dead_homepage_have_no_fallback(router: respx.MockRouter) -> None:
    router.get(PAGE).respond(410)
    router.get(HOME).respond(404)
    health = await make_checker(router).check_url(PAGE)
    assert (health.fallback, health.fallback_allowed) == (None, False)


async def test_a_dead_homepage_has_no_fallback_of_its_own(router: respx.MockRouter) -> None:
    router.get(HOME).respond(404)
    health = await make_checker(router).check_url(HOME)
    assert verdict(health) == ("dead", "http_404")
    assert health.fallback is None
    assert router.calls.call_count == 1


@pytest.mark.parametrize(
    ("url", "home", "allowed"),
    [
        (
            "https://www.booking.com/searchresults.it.html?x",
            "https://www.booking.com/",
            True,
        ),
        ("https://www.google.com/travel/flights?q=x", "https://www.google.com/", False),
    ],
)
async def test_dead_booking_link_fallback_allowed_follows_the_allowlist(
    router: respx.MockRouter, url: str, home: str, allowed: bool
) -> None:
    router.get(url).respond(404)
    router.get(home).respond(200)
    health = await make_checker(router).check_url(url)
    assert (health.fallback, health.fallback_allowed) == (home, allowed)


@pytest.mark.parametrize(
    ("error", "reason"),
    [
        (httpx.ConnectTimeout("slow"), "timeout"),
        (httpx.ReadTimeout("slow"), "timeout"),
        (httpx.ConnectError("refused"), "connect_error"),
        (httpx.RemoteProtocolError("garbage"), "network_error"),
        (httpx.ReadError("reset"), "network_error"),
    ],
)
async def test_network_errors_are_unknown(
    router: respx.MockRouter, error: Exception, reason: str
) -> None:
    router.get(PAGE).mock(side_effect=error)
    health = await make_checker(router).check_url(PAGE)
    assert verdict(health) == ("unknown", reason)


async def test_a_tls_failure_is_unknown() -> None:
    def refuse(request: httpx.Request) -> httpx.Response:
        """httpx's chain for a bad certificate: httpx error <- httpcore error <- ssl error.
        (A plain handler: respx re-raises side effects from its own wrapper.)"""
        try:
            try:
                raise ssl.SSLCertVerificationError("certificate verify failed")
            except ssl.SSLError as exc:
                raise httpcore.ConnectError(str(exc)) from exc
        except httpcore.ConnectError as exc:
            raise httpx.ConnectError(str(exc)) from exc

    checker = HttpLinkChecker(
        transport=httpx.MockTransport(refuse),
        resolver=FakeResolver(),
        user_agent=USER_AGENT,
        now=lambda: NOW,
    )
    assert verdict(await checker.check_url(PAGE)) == ("unknown", "tls_error")


async def test_a_stalled_request_times_out(router: respx.MockRouter) -> None:
    """MockTransport ignores httpcore's timeouts: the asyncio guard fires, 0.5 s after them."""

    async def stall(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(3)
        return httpx.Response(200)

    router.get(PAGE).mock(side_effect=stall)
    started = time.perf_counter()
    health = await make_checker(router, request_timeout=0.1).check_url(PAGE)
    assert 0.55 <= time.perf_counter() - started < 1.5
    assert verdict(health) == ("unknown", "timeout")


async def test_a_stalled_body_read_times_out(router: respx.MockRouter) -> None:
    class StalledBody(httpx.AsyncByteStream):
        async def __aiter__(self) -> AsyncIterator[bytes]:
            yield b"<html><title>"
            await asyncio.sleep(3)
            yield b"Page not found</title></html>"

    stalled = httpx.Response(200, headers={"Content-Type": "text/html"}, stream=StalledBody())
    router.get(PAGE).mock(return_value=stalled)
    started = time.perf_counter()
    health = await make_checker(router, request_timeout=0.1).check_url(PAGE)
    assert 0.55 <= time.perf_counter() - started < 1.5
    assert verdict(health) == ("unknown", "timeout")


async def test_slow_url_becomes_unknown_within_the_deadline(router: respx.MockRouter) -> None:
    slow = "https://slow.example/x"

    async def stall(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(1)
        return httpx.Response(200)

    router.get(PAGE).respond(200)
    router.get(slow).mock(side_effect=stall)
    checker = make_checker(router, total_deadline=0.2)
    started = time.perf_counter()
    health = await checker.check_plan(plan_with_urls(PAGE, slow))
    assert time.perf_counter() - started < 0.5
    assert verdict(entry_of(health, PAGE)) == ("ok", "ok")
    assert entry_of(health, slow) == LinkHealth(status="unknown", reason="deadline", checked_at=NOW)


async def test_check_plan_enforces_its_own_deadline(router: respx.MockRouter) -> None:
    """Independent of check_url's own deadline: a check that never ends is cut off by the
    plan's."""

    class HangingChecker(HttpLinkChecker):
        async def check_url(self, url: str) -> LinkHealth:
            await asyncio.sleep(3)
            raise AssertionError("the plan deadline should have cancelled this check")

    checker = HangingChecker(
        transport=httpx.MockTransport(router.async_handler),
        resolver=FakeResolver(),
        user_agent=USER_AGENT,
        now=lambda: NOW,
        total_deadline=0.2,
    )
    started = time.perf_counter()
    health = await checker.check_plan(plan_with_urls(PAGE, "https://b.example/y"))
    assert time.perf_counter() - started < 0.5
    assert health.counts() == {"ok": 0, "dead": 0, "unknown": 2}
    assert verdict(entry_of(health, PAGE)) == ("unknown", "deadline")


async def test_check_plan_checks_each_distinct_url_once(router: respx.MockRouter) -> None:
    other = "https://b.example/y"
    router.get(PAGE).respond(200)
    router.get(other).respond(200)
    plan = make_plan(
        bookings=[booking(link=PAGE, price=price(PAGE)), booking(title="Treno", link=other)],
    )
    plan.days[0].stops[0].url = other
    health = await make_checker(router).check_plan(plan)
    assert list(health) == [PAGE, other]
    assert sorted(str(call.request.url) for call in router.calls) == [PAGE, other]


async def test_check_plan_runs_at_most_concurrency_requests_at_once(
    router: respx.MockRouter,
) -> None:
    running = 0
    peak = 0

    async def count(request: httpx.Request) -> httpx.Response:
        nonlocal running, peak
        running += 1
        peak = max(peak, running)
        await asyncio.sleep(0.01)
        running -= 1
        return httpx.Response(200)

    router.get(url__regex=r"^https://a\.example/p\d+$").mock(side_effect=count)
    urls = [f"https://a.example/p{index}" for index in range(6)]
    health = await make_checker(router, concurrency=2).check_plan(plan_with_urls(*urls))
    assert health.counts() == {"ok": 6, "dead": 0, "unknown": 0}
    assert peak == 2


async def test_a_failing_check_never_fails_the_plan(router: respx.MockRouter) -> None:
    resolver = FakeResolver({"a.example": RuntimeError("bug")})
    router.get("https://b.example/y").respond(200)
    health = await make_checker(router, resolver).check_plan(
        plan_with_urls(PAGE, "https://b.example/y")
    )
    assert verdict(entry_of(health, PAGE)) == ("unknown", "error")
    assert verdict(entry_of(health, "https://b.example/y")) == ("ok", "ok")


async def test_requests_carry_the_user_agent_and_no_cookie(router: respx.MockRouter) -> None:
    router.get(PAGE).respond(
        302, headers={"Location": "/next", "Set-Cookie": "session=abc; Path=/"}
    )
    router.get("https://a.example/next").respond(200)
    health = await make_checker(router, request_timeout=4.0).check_url(PAGE)
    assert verdict(health) == ("ok", "ok")
    requests = [call.request for call in router.calls]
    assert len(requests) == 2
    for request in requests:
        assert request.method == "GET"
        assert request.headers["User-Agent"] == USER_AGENT
        assert request.headers["Accept"] == "text/html,*/*;q=0.8"
        assert request.headers["Accept-Language"] == "it,en;q=0.8"
        assert request.headers["Accept-Encoding"] == "identity"
        assert "Cookie" not in request.headers
        assert "Authorization" not in request.headers
        assert request.extensions["timeout"] == {
            "connect": 4.0,
            "read": 4.0,
            "write": 4.0,
            "pool": 4.0,
        }


@pytest.fixture
def logs(monkeypatch: pytest.MonkeyPatch) -> list[EventDict]:
    capture = LogCapture()
    logger = structlog.wrap_logger(
        structlog.PrintLogger(),
        processors=[capture],
        wrapper_class=structlog.make_filtering_bound_logger(logging.DEBUG),
    )
    monkeypatch.setattr(link_health, "log", logger)
    return capture.entries


async def test_check_plan_logs_counts_and_dead_hosts_only(
    router: respx.MockRouter, logs: list[EventDict]
) -> None:
    router.get(PAGE).respond(404)
    router.get(HOME).respond(404)
    router.get("https://b.example/y").respond(200)
    await make_checker(router).check_plan(plan_with_urls(PAGE, "https://b.example/y"))
    summary = [entry for entry in logs if entry["event"] == "link_check"]
    assert len(summary) == 1
    assert (summary[0]["urls"], summary[0]["ok"], summary[0]["dead"], summary[0]["unknown"]) == (
        2,
        1,
        1,
        0,
    )
    assert isinstance(summary[0]["elapsed_ms"], int)
    dead = [entry for entry in logs if entry["event"] == "link_dead"]
    assert [(entry["host"], entry["reason"]) for entry in dead] == [("a.example", "http_404")]
    assert "https://" not in repr(logs)


async def test_no_link_checks_returns_an_empty_map() -> None:
    assert len(await NO_LINK_CHECKS.check_plan(plan_with_urls(PAGE))) == 0
    await NO_LINK_CHECKS.aclose()


async def test_aclose_closes_the_transport(router: respx.MockRouter) -> None:
    closed: list[bool] = []

    class ClosingTransport(httpx.MockTransport):
        async def aclose(self) -> None:
            closed.append(True)

    checker = HttpLinkChecker(
        transport=ClosingTransport(router.async_handler),
        resolver=FakeResolver(),
        user_agent=USER_AGENT,
        now=lambda: NOW,
    )
    await checker.aclose()
    assert closed == [True]


# --- the pinned transport ---------------------------------------------------------------------


class RecordingBackend(httpcore.AsyncNetworkBackend):
    """Records connect_tcp calls; refuses the addresses in `refused`."""

    def __init__(self, refused: tuple[str, ...] = ()) -> None:
        self.calls: list[tuple[str, int]] = []
        self.refused = refused

    async def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,  # noqa: ASYNC109 (httpcore's signature)
        local_address: str | None = None,
        socket_options: Iterable[Any] | None = None,
    ) -> httpcore.AsyncNetworkStream:
        self.calls.append((host, port))
        if host in self.refused:
            raise httpcore.ConnectError(f"refused by {host}")
        return httpcore.AsyncMockStream([])

    async def sleep(self, seconds: float) -> None:
        return None


async def test_pinned_backend_refuses_private_addresses() -> None:
    inner = RecordingBackend()
    backend = PinnedNetworkBackend(FakeResolver({"evil.example": ["10.0.0.1"]}), inner=inner)
    with pytest.raises(httpcore.ConnectError):
        await backend.connect_tcp("evil.example", 443)
    assert inner.calls == []


async def test_pinned_backend_refuses_an_unknown_host() -> None:
    inner = RecordingBackend()
    resolver = FakeResolver({"gone.example": HostNotFoundError("gone.example")})
    backend = PinnedNetworkBackend(resolver, inner=inner)
    with pytest.raises(httpcore.ConnectError):
        await backend.connect_tcp("gone.example", 443)
    assert inner.calls == []


async def test_pinned_backend_connects_to_the_vetted_address() -> None:
    inner = RecordingBackend()
    backend = PinnedNetworkBackend(FakeResolver(), inner=inner)
    stream = await backend.connect_tcp("a.example", 443, timeout=5.0)
    assert isinstance(stream, httpcore.AsyncMockStream)
    assert inner.calls == [(PUBLIC_ADDRESS, 443)]


async def test_pinned_backend_skips_private_answers_and_falls_over() -> None:
    inner = RecordingBackend(refused=("2606:4700::1111",))
    resolver = FakeResolver({"a.example": ["10.0.0.1", "2606:4700::1111", PUBLIC_ADDRESS]})
    backend = PinnedNetworkBackend(resolver, inner=inner)
    await backend.connect_tcp("a.example", 80)
    assert inner.calls == [("2606:4700::1111", 80), (PUBLIC_ADDRESS, 80)]


async def test_the_built_checker_connects_through_the_pinned_backend(
    make_settings: Callable[..., Settings], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """build_link_checker replaces httpx 0.28.1's private `AsyncHTTPTransport._pool`: a request
    through its transport must reach PinnedNetworkBackend (here refused, so offline). The pool
    keeps no idle connection, and nothing comes from the environment: with trust_env, the
    missing SSL_CERT_FILE would make building the TLS context fail."""
    monkeypatch.setenv("SSL_CERT_FILE", str(tmp_path / "missing.pem"))
    resolver = FakeResolver({"evil.example": ["10.0.0.1"]})
    monkeypatch.setattr(link_health, "system_resolver", resolver)
    checker = build_link_checker(
        make_settings(frontend_origin="https://atlas.example"), now=lambda: NOW
    )
    try:
        transport = checker._transport
        assert isinstance(transport, httpx.AsyncHTTPTransport)
        pool = transport._pool
        assert isinstance(pool, httpcore.AsyncConnectionPool)
        assert (pool._max_connections, pool._max_keepalive_connections) == (100, 0)
        with pytest.raises(httpx.ConnectError, match="no public address"):
            await transport.handle_async_request(httpx.Request("GET", "https://evil.example/"))
        assert resolver.calls == ["evil.example"]
        assert checker._user_agent == "AtlasLinkCheck/1.0 (+https://atlas.example)"
    finally:
        await checker.aclose()


async def test_system_resolver_resolves_localhost() -> None:
    addresses = await system_resolver("localhost")
    assert addresses
    assert all(address.is_loopback for address in addresses)


@pytest.mark.parametrize(
    "errno", [socket.EAI_NONAME, getattr(socket, "EAI_NODATA", socket.EAI_NONAME)]
)
async def test_system_resolver_maps_a_missing_name(
    monkeypatch: pytest.MonkeyPatch, errno: int
) -> None:
    async def missing(*args: Any, **kwargs: Any) -> Any:
        raise socket.gaierror(errno, "not known")

    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", missing)
    with pytest.raises(HostNotFoundError):
        await system_resolver("gone.example")


async def test_system_resolver_keeps_other_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    async def again(*args: Any, **kwargs: Any) -> Any:
        raise socket.gaierror(socket.EAI_AGAIN, "try again")

    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", again)
    with pytest.raises(socket.gaierror):
        await system_resolver("a.example")
