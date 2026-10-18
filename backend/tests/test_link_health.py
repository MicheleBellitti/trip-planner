"""Pure helpers of app.link_health: URL collection, homepage, public addresses, soft 404."""

from __future__ import annotations

import datetime as dt
import ipaddress
from typing import Any

import pytest

from app.link_health import (
    LinkHealth,
    LinkHealthMap,
    collect_plan_urls,
    homepage_of,
    is_public_address,
    looks_not_found,
)
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
