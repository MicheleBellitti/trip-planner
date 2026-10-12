"""Tests for build_link.py and templates.json (spec, "Test e verifica": every provider yields a URL
on the expected host with dates and travellers encoded), plus bad input and the backend's
booking-link allowlist (backend/app/links.py), which every template host must satisfy.

Offline: URLs are checked by structure, never fetched (every provider blocks scripted clients,
docs/research/integrations.md 1.11).

Run: cd backend && uv run pytest ../skills -q
"""

from __future__ import annotations

import importlib
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest

HERE = Path(__file__).resolve().parent
SCRIPT = HERE / "build_link.py"
BACKEND = HERE.parents[1] / "backend"


def _load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("booking_links_build_link", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _backend_links() -> ModuleType:
    """backend/app/links.py, the allowlist the backend applies to every booking link."""
    if str(BACKEND) not in sys.path:
        sys.path.append(str(BACKEND))
    return importlib.import_module("app.links")


bl = _load_script()
TEMPLATES: dict[str, Any] = bl.load_templates()
LINKS = _backend_links()

# provider -> (raw params, expected path, expected decoded query: key -> every value in order)
CASES: dict[str, tuple[dict[str, str], str, dict[str, list[str]]]] = {
    "booking": (
        {
            "destination": "Alfama, Lisbona",
            "checkin": "2027-05-13",
            "checkout": "2027-05-18",
            "adults": "2",
            "child-ages": "8,5",
        },
        "/searchresults.it.html",
        {
            "ss": ["Alfama, Lisbona"],
            "checkin": ["2027-05-13"],
            "checkout": ["2027-05-18"],
            "group_adults": ["2"],
            "group_children": ["2"],
            "age": ["8", "5"],
            "no_rooms": ["1"],
            "selected_currency": ["EUR"],
        },
    ),
    "airbnb": (
        {
            "destination": "Reggio Emilia, RE",
            "checkin": "2027-05-13",
            "checkout": "2027-05-18",
            "adults": "2",
            "child-ages": "15,8,1",
        },
        "/s/Reggio-Emilia--RE/homes",
        {
            "checkin": ["2027-05-13"],
            "checkout": ["2027-05-18"],
            "adults": ["3"],
            "children": ["1"],
            "infants": ["1"],
            "pets": ["0"],
        },
    ),
    "google_flights": (
        {
            "from": "MXP",
            "to": "LIS",
            "depart": "2027-05-13",
            "return": "2027-05-18",
            "adults": "2",
            "child-ages": "8,5",
        },
        "/travel/flights",
        {
            "q": [
                "Flights to LIS from MXP on 2027-05-13 through 2027-05-18 "
                "for 2 adults and 2 children"
            ],
            "hl": ["it"],
            "gl": ["IT"],
            "curr": ["EUR"],
        },
    ),
    "expedia_hotels": (
        {
            "destination": "Lisbona, Portogallo",
            "checkin": "2027-05-13",
            "checkout": "2027-05-18",
            "adults": "3",
            "child-ages": "8,5",
            "rooms": "2",
        },
        "/Hotel-Search",
        {
            "destination": ["Lisbona, Portogallo"],
            "startDate": ["2027-05-13"],
            "endDate": ["2027-05-18"],
            "rooms": ["2"],
            "adults": ["2,1"],
            "children": ["1_8,2_5"],
        },
    ),
    "expedia_flights": (
        {
            "from": "MXP",
            "to": "LIS",
            "depart": "2027-05-13",
            "return": "2027-05-18",
            "adults": "2",
            "child-ages": "8,5",
        },
        "/Flights-Search",
        {
            "trip": ["roundtrip"],
            "leg1": ["from:MXP,to:LIS,departure:2027-05-13TANYT"],
            "leg2": ["from:LIS,to:MXP,departure:2027-05-18TANYT"],
            "passengers": ["adults:2,children:2[8;5],seniors:0,infantinlap:N"],
            "options": ["cabinclass:economy"],
            "mode": ["search"],
        },
    ),
    "kiwi": (
        {
            "from": "Milan, Italy",
            "to": "Lisbon, Portugal",
            "depart": "2027-05-13",
            "return": "2027-05-18",
            "adults": "2",
            "child-ages": "14,8,1",
        },
        "/en/search/results/milan-italy/lisbon-portugal/2027-05-13/2027-05-18",
        {"adults": ["3"], "children": ["1"], "infants": ["1"]},
    ),
    "lastminute": (
        {
            "from": "MIL",
            "to": "LIS",
            "depart": "2027-05-13",
            "return": "2027-05-18",
            "adults": "2",
            "child-ages": "8",
        },
        "/s/flights/search/v2/results",
        {
            "passengers.adults": ["2"],
            "passengers.children": ["1"],
            "passengers.childrenAge[0]": ["8"],
            "itinerary.type": ["ROUND_TRIP"],
            "itinerary.path[0].departure": ["MIL"],
            "itinerary.path[0].arrival": ["LIS"],
            "itinerary.path[0].date": ["20270513"],
            "itinerary.path[1].departure": ["LIS"],
            "itinerary.path[1].arrival": ["MIL"],
            "itinerary.path[1].date": ["20270518"],
        },
    ),
    "trenitalia": (
        {
            "from": "Firenze S. M. Novella",
            "to": "Napoli Centrale",
            "depart": "2027-05-13",
            "time": "09:00",
            "return": "2027-05-18",
            "return-time": "17:30",
            "adults": "2",
            "child-ages": "16,8",
        },
        "/Channels.Website.WEB/website/auth/handoff",
        {
            "action": ["searchTickets"],
            "departureStation": ["Firenze S. M. Novella"],
            "arrivalStation": ["Napoli Centrale"],
            "departureDate": ["13-05-2027"],
            "departureTime": ["09"],
            "returnDate": ["18-05-2027"],
            "isRoundTrip": ["true"],
            "returnTime": ["17"],
            "noOfAdults": ["3"],
            "noOfChildren": ["1"],
        },
    ),
    "italo": (
        {
            "from": "Milano Centrale",
            "to": "RMT",
            "depart": "2027-05-13",
            "return": "2027-05-18",
            "adults": "2",
            "child-ages": "16,8,1",
        },
        "/it/booking/ricerca-treni",
        {
            "osc": ["MC_"],
            "dsc": ["RMT"],
            "jt": ["return"],
            "od": ["13/05/2027"],
            "id": ["18/05/2027"],
            "adt": ["2"],
            "yng": ["1"],
            "chd": ["1"],
            "inf": ["1"],
            "startSearch": ["true"],
        },
    ),
    "omio": (
        {"from": "Firenze", "to": "Venezia", "depart": "2027-05-13"},
        "/treni/firenze/venezia",
        {"departure_date": ["13/05/2027"]},
    ),
}


def build(provider: str, **params: str) -> str:
    return bl.build_url(provider, {key.replace("_", "-"): value for key, value in params.items()})


def query(url: str) -> dict[str, list[str]]:
    return parse_qs(urlsplit(url).query, keep_blank_values=True, strict_parsing=True)


def host_allowed(entry: Any, url: str) -> bool:
    """The matching rule documented in backend/app/links.py (and integrations.md 1.12)."""
    parts = urlsplit(url)
    if parts.scheme != "https" or parts.username or parts.password or parts.port not in (None, 443):
        return False
    host = (parts.hostname or "").lower()
    allowed = host in entry.hosts or any(
        host == suffix or host.endswith("." + suffix) for suffix in entry.suffixes
    )
    if allowed and entry.path_prefix is not None:
        allowed = parts.path.startswith(entry.path_prefix)
    return allowed


# --- every provider ---------------------------------------------------------------------------


def test_every_provider_has_a_builder_and_a_case() -> None:
    assert set(TEMPLATES) == set(bl.BUILDERS) == set(CASES)


@pytest.mark.parametrize("provider", sorted(CASES))
def test_provider_url_on_expected_host_with_dates_and_travellers(provider: str) -> None:
    params, path, expected = CASES[provider]
    url = bl.build_url(provider, params)
    parts = urlsplit(url)
    assert parts.scheme == "https"
    assert parts.hostname == TEMPLATES[provider]["host"]
    assert parts.path == path
    assert not parts.fragment
    decoded = query(url)
    for key, values in expected.items():
        assert decoded.get(key) == values, key
    assert url.isascii()
    assert " " not in url
    assert len(url) <= bl.MAX_URL_LENGTH


@pytest.mark.parametrize("provider", sorted(CASES))
def test_template_host_is_on_the_backend_allowlist(provider: str) -> None:
    template = TEMPLATES[provider]
    entry = LINKS.PROVIDERS[template["allowlist"]]
    assert (
        urlsplit(template["url"].replace("{", "x").replace("}", "x")).hostname == template["host"]
    )
    host = template["host"]
    assert host in entry.hosts or any(host == s or host.endswith("." + s) for s in entry.suffixes)


@pytest.mark.parametrize("provider", sorted(CASES))
def test_built_url_passes_the_backend_allowlist(provider: str) -> None:
    params, _, _ = CASES[provider]
    url = bl.build_url(provider, params)
    entry = LINKS.PROVIDERS[TEMPLATES[provider]["allowlist"]]
    assert host_allowed(entry, url)
    try:
        verdict = LINKS.check_link(url)
    except NotImplementedError:
        pytest.skip("backend app.links.check_link is still a stub; checked against PROVIDERS")
    assert verdict.allowed
    assert verdict.provider == TEMPLATES[provider]["allowlist"]


def test_templates_are_consistent() -> None:
    statuses = {"verified", "partly_verified"}
    for name, provider in TEMPLATES.items():
        assert provider["status"] in statuses, name
        assert provider["category"] in {"flights", "lodging", "trains"}, name
        for param, spec in provider["params"].items():
            assert spec["type"] in bl.PARSERS, (name, param)
            for rule in ("after", "on_or_after", "requires"):
                if rule in spec:
                    assert spec[rule] in provider["params"], (name, param, rule)
            assert spec.get("help"), (name, param)


# --- variants: one way, bands, encoding -------------------------------------------------------


def test_one_way_variants() -> None:
    google = query(
        build("google_flights", **{"from": "LHR"}, to="FCO", depart="2027-12-03", adults="1")
    )
    assert google["q"] == ["One way flights to FCO from LHR on 2027-12-03 for 1 adult"]

    expedia = query(
        build("expedia_flights", **{"from": "FCO"}, to="BCN", depart="2027-12-03", adults="1")
    )
    assert expedia["trip"] == ["oneway"]
    assert "leg2" not in expedia
    assert expedia["passengers"] == ["adults:1,children:0,seniors:0,infantinlap:N"]

    kiwi = build(
        "kiwi", **{"from": "Milan, Italy"}, to="Lisbon, Portugal", depart="2027-12-05", adults="1"
    )
    assert urlsplit(kiwi).path.endswith("/2027-12-05/no-return")

    last = query(build("lastminute", **{"from": "MIL"}, to="LIS", depart="2027-12-05", adults="1"))
    assert last["itinerary.type"] == ["ONE_WAY"]
    assert not any(key.startswith("itinerary.path[1]") for key in last)

    treni = query(
        build(
            "trenitalia",
            **{"from": "Milano Centrale"},
            to="Roma Termini",
            depart="2027-11-14",
            adults="1",
        )
    )
    assert treni["returnDate"] == treni["departureDate"] == ["14-11-2027"]
    assert treni["departureTime"] == ["08"]
    assert "isRoundTrip" not in treni
    assert "returnTime" not in treni

    italo = query(build("italo", **{"from": "MC_"}, to="RMT", depart="2027-11-14", adults="1"))
    assert italo["jt"] == ["single"]
    assert "id" not in italo


def test_no_children_leaves_out_child_parameters() -> None:
    booking = query(
        build(
            "booking",
            destination="Lisbona",
            checkin="2027-05-13",
            checkout="2027-05-14",
            adults="1",
        )
    )
    assert booking["group_children"] == ["0"]
    assert "age" not in booking
    hotels = query(
        build(
            "expedia_hotels",
            destination="Lisbona",
            checkin="2027-05-13",
            checkout="2027-05-14",
            adults="2",
        )
    )
    assert "children" not in hotels
    assert hotels["adults"] == ["2"]


def test_google_counts_teenagers_as_adults_and_small_children_as_children() -> None:
    url = build(
        "google_flights",
        **{"from": "MXP"},
        to="LIS",
        depart="2027-05-13",
        adults="1",
        child_ages="13,11,1",
    )
    assert query(url)["q"] == [
        "One way flights to LIS from MXP on 2027-05-13 for 2 adults and 2 children"
    ]


def test_place_names_are_percent_encoded() -> None:
    url = build(
        "booking",
        destination="São Miguel, Açores",
        checkin="2027-05-13",
        checkout="2027-05-18",
        adults="2",
    )
    assert url.isascii()
    assert "ss=S%C3%A3o%20Miguel%2C%20A%C3%A7ores&" in url
    assert query(url)["ss"] == ["São Miguel, Açores"]
    airbnb = build(
        "airbnb",
        destination="São Miguel, Açores",
        checkin="2027-05-13",
        checkout="2027-05-18",
        adults="2",
    )
    assert urlsplit(airbnb).path == "/s/S%C3%A3o-Miguel--A%C3%A7ores/homes"
    kiwi = build(
        "kiwi",
        **{"from": "São Paulo, Brazil"},
        to="Lisbon, Portugal",
        depart="2027-05-13",
        adults="1",
    )
    assert "/sao-paulo-brazil/lisbon-portugal/" in kiwi


def test_italo_accepts_station_names_and_codes() -> None:
    by_name = query(
        build(
            "italo",
            **{"from": "firenze s. m. novella"},
            to="Napoli Centrale",
            depart="2027-05-13",
            adults="1",
        )
    )
    assert by_name["osc"] == ["SMN"]
    assert by_name["dsc"] == ["NAC"]


# --- bad input --------------------------------------------------------------------------------

BOOKING = {
    "destination": "Lisbona",
    "checkin": "2027-05-13",
    "checkout": "2027-05-18",
    "adults": "2",
}
FLIGHT = {"from": "MXP", "to": "LIS", "depart": "2027-05-13", "adults": "2"}

BAD_INPUT: list[tuple[str, dict[str, str], str]] = [
    ("booking", {**BOOKING, "checkin": "2027-02-30"}, "not a real calendar date"),
    ("booking", {**BOOKING, "checkin": "13/05/2027"}, "YYYY-MM-DD"),
    ("booking", {**BOOKING, "checkin": "2027-5-13"}, "YYYY-MM-DD"),
    ("booking", {**BOOKING, "checkout": "2027-05-13"}, "must be after --checkin"),
    ("booking", {**BOOKING, "checkout": "2027-05-01"}, "must be after --checkin"),
    ("booking", {**BOOKING, "checkout": "2027-10-01"}, "at most 120"),
    ("booking", {**BOOKING, "adults": "0"}, "between 1 and 9"),
    ("booking", {**BOOKING, "adults": "two"}, "whole number"),
    ("booking", {**BOOKING, "child-ages": "8,18"}, "not a child's age"),
    ("booking", {**BOOKING, "child-ages": "8;5"}, "separated by commas"),
    ("booking", {**BOOKING, "child-ages": "-1"}, "separated by commas"),
    ("booking", {**BOOKING, "adults": "5", "child-ages": "1,2,3,4,5"}, "at most 9"),
    ("booking", {**BOOKING, "rooms": "3"}, "every room needs an adult"),
    ("booking", {**BOOKING, "destination": "https://evil.example/x"}, "place name"),
    ("booking", {**BOOKING, "destination": "mario.rossi@example.com"}, "place name"),
    ("booking", {**BOOKING, "destination": "Roma&group_adults=9"}, "place name"),
    ("booking", {**BOOKING, "destination": "   "}, "must not be empty"),
    ("booking", {**BOOKING, "destination": "x" * 201}, "too long"),
    ("booking", {k: v for k, v in BOOKING.items() if k != "destination"}, "needs --destination"),
    ("booking", {**BOOKING, "from": "MXP"}, "does not take --from"),
    ("airbnb", {**BOOKING, "destination": "Lisbona"}, "province or country"),
    ("airbnb", {**BOOKING, "destination": "Lisbona/Alfama, Portogallo"}, "only letters"),
    ("google_flights", {**FLIGHT, "from": "mxp"}, "IATA"),
    ("google_flights", {**FLIGHT, "from": "MX"}, "IATA"),
    ("google_flights", {**FLIGHT, "to": "LISB"}, "IATA"),
    ("google_flights", {**FLIGHT, "to": "MXP"}, "same place"),
    ("google_flights", {**FLIGHT, "return": "2027-05-12"}, "on or after --depart"),
    (
        "expedia_flights",
        {**FLIGHT, "adults": "1", "child-ages": "0,1"},
        "one child under 2 per adult",
    ),
    ("kiwi", {**FLIGHT, "from": "Milano", "to": "Lisbon, Portugal"}, "province or country"),
    ("kiwi", {**FLIGHT, "from": "Lisbon, Portugal", "to": "Lisbon, Portugal"}, "same place"),
    (
        "italo",
        {**FLIGHT, "from": "Torino Porta Nuova", "to": "RMT"},
        "not in the Italo station table",
    ),
    (
        "trenitalia",
        {**FLIGHT, "from": "Milano Centrale", "to": "Roma Termini", "return-time": "18:00"},
        "needs --return",
    ),
    (
        "trenitalia",
        {**FLIGHT, "from": "Milano Centrale", "to": "Roma Termini", "time": "8:00"},
        "HH:MM",
    ),
    (
        "trenitalia",
        {
            **FLIGHT,
            "from": "Milano Centrale",
            "to": "Roma Termini",
            "time": "18:00",
            "return": "2027-05-13",
            "return-time": "09:00",
        },
        "later than --time",
    ),
    (
        "omio",
        {"from": "Firenze", "to": "Venezia", "depart": "2027-05-13", "adults": "2"},
        "does not take --adults",
    ),
    (
        "omio",
        {"from": "Firenze, Italia", "to": "Venezia", "depart": "2027-05-13"},
        "one Italian city name",
    ),
    ("ryanair", FLIGHT, "unknown provider"),
]


@pytest.mark.parametrize(("provider", "params", "message"), BAD_INPUT)
def test_bad_input_is_rejected(provider: str, params: dict[str, str], message: str) -> None:
    with pytest.raises(bl.LinkError) as caught:
        bl.build_url(provider, params)
    assert message in str(caught.value)


def test_url_longer_than_the_cap_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(bl, "MAX_URL_LENGTH", 100)
    with pytest.raises(bl.LinkError, match="more than 100"):
        bl.build_url("booking", BOOKING)


# --- command line -----------------------------------------------------------------------------


def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
        check=False,
        env=env,
        timeout=60,
    )


def test_cli_prints_exactly_one_url() -> None:
    result = run_cli(
        "booking", "--destination", "Lisbona", "--checkin", "2027-05-13",
        "--checkout", "2027-05-18", "--adults", "2", "--child-ages", "8,5",
    )  # fmt: skip
    assert result.returncode == 0, result.stderr
    lines = result.stdout.splitlines()
    assert len(lines) == 1
    assert lines[0] == bl.build_url("booking", {**BOOKING, "child-ages": "8,5"})
    assert result.stderr == ""


def test_cli_notes_go_to_stderr_only() -> None:
    result = run_cli(
        "kiwi",
        "--from",
        "Milan, Italy",
        "--to",
        "Lisbon, Portugal",
        "--depart",
        "2027-05-13",
        "--adults",
        "1",
    )
    assert result.returncode == 0, result.stderr
    assert len(result.stdout.splitlines()) == 1
    assert "note:" in result.stderr


@pytest.mark.parametrize(
    ("args", "message"),
    [
        (
            (
                "booking",
                "--destination",
                "Lisbona",
                "--checkin",
                "2027-02-30",
                "--checkout",
                "2027-03-02",
                "--adults",
                "2",
            ),
            "not a real calendar date",
        ),
        (
            (
                "booking",
                "--destination",
                "Lisbona",
                "--checkin",
                "2027-05-13",
                "--checkout",
                "2027-05-18",
                "--adults",
                "2",
                "--nights",
                "5",
            ),
            "unrecognized arguments",
        ),
        (
            (
                "booking",
                "--dest",
                "Lisbona",
                "--checkin",
                "2027-05-13",
                "--checkout",
                "2027-05-18",
                "--adults",
                "2",
            ),
            "unrecognized arguments",
        ),
        (
            (
                "booking",
                "--destination",
                "Lisbona",
                "--destination",
                "Porto",
                "--checkin",
                "2027-05-13",
                "--checkout",
                "2027-05-18",
                "--adults",
                "2",
            ),
            "given 2 times",
        ),
        (("ryanair", "--from", "MXP"), "unknown provider"),
        ((), "name a provider"),
    ],
)
def test_cli_bad_input_exits_non_zero_with_a_message(args: tuple[str, ...], message: str) -> None:
    result = run_cli(*args)
    assert result.returncode == 2
    assert result.stdout == ""
    assert message in result.stderr


def test_cli_list_names_every_provider_and_param() -> None:
    result = run_cli("--list")
    assert result.returncode == 0
    for name, provider in TEMPLATES.items():
        assert name in result.stdout
        assert provider["host"] in result.stdout
        for param in provider["params"]:
            assert f"--{param}" in result.stdout


def test_templates_file_header() -> None:
    data = json.loads((HERE / "templates.json").read_text(encoding="utf-8"))
    assert data["format_version"] == 1
    assert data["checked_on"] == "2026-10-12"
