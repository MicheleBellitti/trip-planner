"""Booking-link allowlist (app/links.py): only https links to a provider's own hosts become a
"Prenota su <sito>" button; everything else is shown as text (spec "Sicurezza e privacy",
CLAUDE.md rule 4, integrations.md §1.12)."""

from __future__ import annotations

import pytest

from app.links import (
    MAX_LINK_LENGTH,
    MCP_PROVIDERS,
    PROVIDERS,
    LinkVerdict,
    check_link,
    is_allowed_link,
)

# One real link per provider, as build_link.py or an MCP would produce it (integrations.md §1).
PROVIDER_LINKS: list[tuple[str, str]] = [
    (
        "booking",
        "https://www.booking.com/searchresults.it.html?ss=Lisbona&checkin=2027-04-16"
        "&checkout=2027-04-18&group_adults=2&no_rooms=1&selected_currency=EUR",
    ),
    ("booking", "https://booking.com/hotel/pt/example.html"),
    (
        "airbnb",
        "https://www.airbnb.it/s/Lisbona--Portogallo/homes?checkin=2027-04-16"
        "&checkout=2027-04-18&adults=2",
    ),
    ("airbnb", "https://www.airbnb.com/rooms/12345"),
    (
        "google_flights",
        "https://www.google.com/travel/flights?q=Flights+from+MXP+to+LIS+on+2027-04-16&hl=it",
    ),
    ("google_flights", "https://www.google.it/travel/flights/search?tfs=CBwQAhoeEgoyMDI3"),
    ("expedia", "https://www.expedia.it/Hotel-Search?destination=Lisbona&startDate=2027-04-16"),
    ("expedia", "https://www.expedia.co.uk/Flights-Search?trip=oneway"),
    ("expedia", "https://expedia.com/Hotel-Search"),
    ("kiwi", "https://www.kiwi.com/en/search/results/milan-italy/lisbon-portugal/2027-04-16"),
    ("kiwi", "https://kiwi.com/deep?token=abc"),
    ("kiwi", "https://deeplink.kiwi.com/booking?token=abc"),
    ("lastminute", "https://www.lastminute.com/flights/search?from=MIL&to=LIS"),
    ("lastminute", "https://www.it.lastminute.com/voli"),
    ("lastminute", "https://secure.lastminute.com/booking/123"),
    ("lastminute", "https://fr.lastminute.be/vols"),
    (
        "trenitalia",
        "https://www.lefrecce.it/Channels.Website.WEB/website/auth/handoff?action=searchTickets"
        "&departureStation=Milano%20Centrale&arrivalStation=Roma%20Termini",
    ),
    ("trenitalia", "https://www.trenitalia.com/it.html"),
    (
        "italo",
        "https://biglietti.italotreno.com/it/booking/ricerca-treni?osc=MC_&dsc=RMT"
        "&od=16/04/2027&adt=2",
    ),
    ("omio", "https://www.omio.it/treni/milano/roma?departure_date=16/04/2027"),
]


@pytest.mark.parametrize(("provider", "url"), PROVIDER_LINKS)
def test_every_provider_link_is_allowed(provider: str, url: str) -> None:
    verdict = check_link(url)

    assert verdict == LinkVerdict(
        allowed=True,
        provider=provider,
        label=PROVIDERS[provider].label,
        host=verdict.host,
        reason=None,
    )
    assert verdict.host is not None
    assert url.lower().startswith(f"https://{verdict.host}")


@pytest.mark.parametrize("host", sorted(PROVIDERS["expedia"].hosts))
def test_every_expedia_point_of_sale_is_allowed(host: str) -> None:
    assert check_link(f"https://{host}/Hotel-Search?destination=Roma").provider == "expedia"


def test_host_is_compared_lower_case_and_reported_lower_case() -> None:
    verdict = check_link("https://WWW.Booking.COM/searchresults.html")

    assert verdict.allowed
    assert verdict.host == "www.booking.com"


def test_the_default_https_port_is_accepted() -> None:
    assert check_link("https://www.booking.com:443/searchresults.html").allowed


@pytest.mark.parametrize(
    ("url", "reason"),
    [
        # Scheme
        ("http://www.booking.com/searchresults.html", "not_https"),
        ("javascript:alert(document.cookie)", "not_https"),
        ("data:text/html,<script>alert(1)</script>", "not_https"),
        ("ftp://www.booking.com/", "not_https"),
        ("//www.booking.com/searchresults.html", "not_https"),
        # User info: the real host is after the @
        ("https://www.booking.com@evil.example/", "userinfo"),
        ("https://user:secret@www.booking.com/", "userinfo"),
        ("https://@www.booking.com/", "userinfo"),
        ("https://www.booking.com:443@evil.example/", "userinfo"),
        # Ports
        ("https://www.booking.com:8443/", "port"),
        ("https://www.booking.com:80/", "port"),
        ("https://www.booking.com:abc/", "port"),
        ("https://www.booking.com:99999/", "port"),
        # Lookalike and foreign hosts: never a substring or prefix match
        ("https://booking.com.evil.example/", "unknown_host"),
        ("https://www.booking.com.evil.example/searchresults.html", "unknown_host"),
        ("https://evilbooking.com/", "unknown_host"),
        ("https://secure.booking.com/", "unknown_host"),
        ("https://notkiwi.com/", "unknown_host"),
        ("https://kiwi.com.evil.example/", "unknown_host"),
        ("https://www.lastminute.com.evil.example/", "unknown_host"),
        ("https://www.expedia.evil/", "unknown_host"),
        ("https://www.google.com.evil.example/travel/flights", "unknown_host"),
        ("https://evil.example#@www.booking.com", "unknown_host"),
        ("https://evil.example/?u=https://www.booking.com/", "unknown_host"),
        ("https://www.booking.com./searchresults.html", "unknown_host"),
        # IDN and punycode lookalikes (Cyrillic o/a/i in place of Latin letters)
        ("https://www.b\u043e\u043eking.com/", "unknown_host"),
        ("https://www.\u0430irbnb.it/", "unknown_host"),
        ("https://k\u0456wi.com/", "unknown_host"),
        ("https://www.xn--bking-gcea.com/", "unknown_host"),
        ("https://xn--80ak6aa92e.kiwi.com/", "unknown_host"),
        ("https://\uff57\uff57\uff57.booking.com/", "unknown_host"),
        ("https://www\u3002booking\u3002com/", "unknown_host"),
        # IP hosts
        ("https://142.250.180.4/travel/flights", "unknown_host"),
        ("https://[2a00:1450:4002:402::200e]/travel/flights", "unknown_host"),
        # Google is allowed only under /travel/flights, never via a dot segment
        ("https://www.google.com/", "path"),
        ("https://www.google.com/maps", "path"),
        ("https://www.google.com/travel/flightsx", "path"),
        ("https://www.google.com/url?q=https://evil.example", "path"),
        ("https://www.google.com/travel/flights/../../url?q=https://evil.example", "path"),
        ("https://www.google.com/travel/flights/%2e%2e/%2E%2E/url?q=https://evil.example", "path"),
        ("https://www.google.com/travel/flights/.%2e/x", "path"),
        # Characters browsers reinterpret: a backslash is a slash, so the host would be evil
        ("https://evil.example\\.kiwi.com/", "unparseable"),
        (
            "https://www.google.com/travel/flights\\..\\..\\url?q=https://evil.example",
            "unparseable",
        ),
        ("https://www.booking.com/search results", "unparseable"),
        ("https://www.booking.com/\tsearch", "unparseable"),
        ("https://www.booking.com/\nsearch", "unparseable"),
        (" https://www.booking.com/", "unparseable"),
        ("https://www.booking.com/\x00", "unparseable"),
        # Not a URL at all
        ("", "unparseable"),
        ("https://", "unparseable"),
        ("https:///www.booking.com/", "unparseable"),
        ("https:www.booking.com", "unparseable"),
        ("https://[::1", "unparseable"),
        ("www.booking.com/searchresults.html", "not_https"),
    ],
)
def test_rejected_links_say_why(url: str, reason: str) -> None:
    verdict = check_link(url)

    assert not verdict.allowed
    assert verdict.reason == reason
    assert verdict.provider is None
    assert verdict.label is None


def test_a_rejected_parseable_link_still_reports_its_host() -> None:
    verdict = check_link("https://booking.com.evil.example/x")

    assert verdict.host == "booking.com.evil.example"


def test_length_cap_is_triptracker_url_cap() -> None:
    base = "https://www.booking.com/searchresults.html?ss="
    at_cap = base + "x" * (MAX_LINK_LENGTH - len(base))

    assert len(at_cap) == MAX_LINK_LENGTH == 2000
    assert check_link(at_cap).allowed
    assert check_link(at_cap + "x").reason == "too_long"


def test_providers_restricts_the_allowlist() -> None:
    booking = "https://www.booking.com/searchresults.html"
    kiwi = "https://www.kiwi.com/en/booking?token=abc"

    assert check_link(booking, providers=MCP_PROVIDERS).reason == "unknown_host"
    assert check_link(kiwi, providers=MCP_PROVIDERS).provider == "kiwi"
    assert check_link(booking, providers=["booking"]).allowed


def test_unknown_provider_keys_fail_closed() -> None:
    url = "https://www.booking.com/searchresults.html"

    assert check_link(url, providers=["no_such_provider"]).reason == "unknown_host"
    assert check_link(url, providers=[]).reason == "unknown_host"


def test_mcp_providers_exist() -> None:
    assert set(MCP_PROVIDERS) <= set(PROVIDERS)


@pytest.mark.parametrize(
    ("url", "allowed"),
    [
        (None, False),
        ("", False),
        ("https://www.omio.it/treni/milano/roma", True),
        ("https://www.omio.it.evil.example/", False),
    ],
)
def test_is_allowed_link(url: str | None, allowed: bool) -> None:
    assert is_allowed_link(url) is allowed


@pytest.mark.parametrize("value", [None, 42, b"https://www.booking.com/"])
def test_check_link_never_raises_on_a_non_string(value: object) -> None:
    verdict = check_link(value)  # pyright: ignore[reportArgumentType]

    assert verdict == LinkVerdict(allowed=False, reason="unparseable")
