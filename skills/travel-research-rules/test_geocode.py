"""Tests for geocode.py with a monkeypatched urllib: the Photon request it builds, the GeoJSON it
parses (coordinates are [lon, lat]) and its errors. Never touches the network.

Run: cd backend && uv run pytest ../skills -q
"""

from __future__ import annotations

import importlib.util
import io
import json
import urllib.error
import urllib.request
from pathlib import Path
from types import ModuleType
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest

HERE = Path(__file__).resolve().parent


def _load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("travel_rules_geocode", HERE / "geocode.py")
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


geo = _load_script()

# Shape of a real Photon answer (integrations.md 3.1), trimmed.
CASTLE = {
    "type": "FeatureCollection",
    "features": [
        {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [-9.1334003, 38.7139158]},
            "properties": {
                "osm_type": "W",
                "osm_id": 25319526,
                "osm_key": "historic",
                "osm_value": "castle",
                "type": "house",
                "name": "Castelo de São Jorge",
                "street": "Rua de Santa Cruz do Castelo",
                "housenumber": "1",
                "postcode": "1100-129",
                "city": "Lisbon",
                "country": "Portugal",
                "countrycode": "PT",
            },
        },
        {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [-9.1, 38.7]},
            "properties": {
                "type": "street",
                "street": "Calçada do Castelo",
                "city": "Lisbon",
                "country": "Portugal",
            },
        },
        {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [200, 38.7]},
            "properties": {"name": "broken"},
        },
        {"type": "Feature", "geometry": None, "properties": {"name": "no geometry"}},
    ],
}


class FakeResponse(io.BytesIO):
    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


class FakePhoton:
    """Replaces urllib.request.urlopen; records every request."""

    def __init__(self, payload: Any = None, error: Exception | None = None) -> None:
        self.payload = payload
        self.error = error
        self.requests: list[urllib.request.Request] = []
        self.timeouts: list[float] = []

    def __call__(self, request: urllib.request.Request, timeout: float) -> FakeResponse:
        self.requests.append(request)
        self.timeouts.append(timeout)
        if self.error is not None:
            raise self.error
        body = (
            self.payload if isinstance(self.payload, bytes) else json.dumps(self.payload).encode()
        )
        return FakeResponse(body)

    def query(self) -> dict[str, list[str]]:
        return parse_qs(urlsplit(self.requests[-1].full_url).query)


@pytest.fixture
def photon(monkeypatch: pytest.MonkeyPatch) -> FakePhoton:
    fake = FakePhoton(CASTLE)
    monkeypatch.setattr(geo.urllib.request, "urlopen", fake)
    return fake


def test_lookup_returns_name_lat_lon_in_that_order(photon: FakePhoton) -> None:
    places = geo.geocode("Castelo de São Jorge, Lisbon", limit=2)
    assert places[0] == {
        "name": "Castelo de São Jorge",
        "lat": 38.713916,
        "lon": -9.1334,
        "label": "Castelo de São Jorge, Rua de Santa Cruz do Castelo 1, Lisbon, Portugal",
        "type": "house",
    }
    assert places[1]["name"] == "Calçada do Castelo"
    assert len(places) == 2  # out-of-range and missing coordinates are dropped


def test_request_shape(photon: FakePhoton) -> None:
    geo.geocode("Rossio", limit=3, near=(38.7223, -9.1393), country="pt", osm_tag="railway:station")
    request = photon.requests[-1]
    parts = urlsplit(request.full_url)
    assert (parts.scheme, parts.hostname, parts.path) == ("https", "photon.komoot.io", "/api/")
    assert photon.query() == {
        "q": ["Rossio"],
        "limit": ["3"],
        "lang": ["en"],
        "lat": ["38.722300"],
        "lon": ["-9.139300"],
        "countrycode": ["PT"],
        "osm_tag": ["railway:station"],
    }
    assert request.get_header("User-agent") == geo.USER_AGENT
    assert photon.timeouts == [geo.TIMEOUT_SECONDS]


def test_city_layer_and_encoding(photon: FakePhoton) -> None:
    geo.geocode("São Paulo", city=True)
    assert photon.query()["layer"] == ["city"]
    assert "q=S%C3%A3o%20Paulo" in photon.requests[-1].full_url


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"query": "   "}, "empty"),
        ({"query": "x" * 301}, "at most 300"),
        ({"query": "Roma\x07"}, "printable"),
        ({"query": "Lisbon", "lang": "it"}, "Photon rejects other languages"),
        ({"query": "Lisbon", "limit": 0}, "between 1 and 10"),
        ({"query": "Lisbon", "limit": 11}, "between 1 and 10"),
        ({"query": "Lisbon", "country": "PRT"}, "two-letter"),
        ({"query": "Lisbon", "osm_tag": "amenity=cafe"}, "key:value"),
    ],
)
def test_bad_input_is_rejected_before_any_request(
    kwargs: dict[str, Any], message: str, photon: FakePhoton
) -> None:
    options = dict(kwargs)
    query = options.pop("query")
    with pytest.raises(geo.GeocodeError, match=message):
        geo.geocode(query, **options)
    assert photon.requests == []


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("38.7", "LAT,LON"),
        ("north,south", "LAT,LON"),
        ("91,0", "out of range"),
        ("0,181", "out of range"),
    ],
)
def test_bad_point(text: str, message: str) -> None:
    with pytest.raises(geo.GeocodeError, match=message):
        geo.parse_point(text)


def test_http_error_carries_photon_message(monkeypatch: pytest.MonkeyPatch) -> None:
    body = io.BytesIO(b'{"message":"Language is not supported."}')
    error = urllib.error.HTTPError(geo.PHOTON_URL, 400, "Bad Request", {}, body)  # type: ignore[arg-type]
    monkeypatch.setattr(geo.urllib.request, "urlopen", FakePhoton(error=error))
    with pytest.raises(geo.GeocodeError, match=r"HTTP 400: .*Language is not supported"):
        geo.geocode("Lisbon")


def test_network_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        geo.urllib.request, "urlopen", FakePhoton(error=urllib.error.URLError("timed out"))
    )
    with pytest.raises(geo.GeocodeError, match="could not be reached"):
        geo.geocode("Lisbon")


@pytest.mark.parametrize("payload", [b"<html>", {"type": "FeatureCollection"}, ["not", "geojson"]])
def test_malformed_answer(payload: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(geo.urllib.request, "urlopen", FakePhoton(payload))
    with pytest.raises(geo.GeocodeError):
        geo.geocode("Lisbon")


def test_cli_prints_json(photon: FakePhoton, capsys: pytest.CaptureFixture[str]) -> None:
    assert geo.main(["Castelo de São Jorge, Lisbon", "--near", "38.71,-9.13"]) == 0
    printed = json.loads(capsys.readouterr().out)
    assert [(p["name"], p["lat"], p["lon"]) for p in printed] == [
        ("Castelo de São Jorge", 38.713916, -9.1334)
    ]


def test_cli_no_match_exits_1(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        geo.urllib.request, "urlopen", FakePhoton({"type": "FeatureCollection", "features": []})
    )
    assert geo.main(["Lisbona"]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "no match" in captured.err


def test_cli_error_exits_2(photon: FakePhoton, capsys: pytest.CaptureFixture[str]) -> None:
    assert geo.main(["Lisbon", "--lang", "it"]) == 2
    assert "error:" in capsys.readouterr().err
    assert photon.requests == []
