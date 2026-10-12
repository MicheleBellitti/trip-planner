#!/usr/bin/env python3
"""Look up a place with Photon (https://photon.komoot.io) and print its name and coordinates.

    python3 geocode.py "Castelo de São Jorge, Lisbon"
    python3 geocode.py "Lisbon" --city
    python3 geocode.py "Rossio" --near 38.7223,-9.1393 --limit 3
    python3 geocode.py "Lisbon Airport" --osm-tag aeroway:aerodrome

Prints a JSON array, best match first: [{"name", "lat", "lon", "label", "type"}], with lat/lon
in decimal degrees (WGS 84). Photon itself answers longitude first; this script already turns
that into named fields, so copy `lat` and `lon` as printed.

Photon matches English and local names; Italian exonyms often fail ("Lisbona" finds a bus stop
in Padua). Ask for "Lisbon" or "Lisboa", add --city for a city, --near LAT,LON for a place in a
known area, --country for a country.

Exit status: 0 found, 1 no match, 2 bad input, network or service error (message on stderr).
Stdlib only, Python 3.10+: this script runs inside the agent sandbox. Photon's public instance
is free within reasonable use: one query per place, never in a loop over guesses.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import re
import sys
import urllib.error
import urllib.request
from collections.abc import Mapping, Sequence
from typing import Any
from urllib.parse import quote, urlencode

PHOTON_URL = "https://photon.komoot.io/api/"
USER_AGENT = "trip-planner-agent/1.0 (travel-research-rules skill, geocode.py)"
TIMEOUT_SECONDS = 15
LANGUAGES = ("en", "default", "de", "fr")
"""What the public Photon instance accepts; Italian ("it") is rejected with HTTP 400."""
MAX_LIMIT = 10
MAX_QUERY = 300
OSM_TAG = re.compile(r"^!?[a-z_]+(:!?[a-z_0-9]+)?$")
COUNTRY = re.compile(r"^[A-Za-z]{2}$")


class GeocodeError(Exception):
    """Bad input, or Photon could not be reached or answered with an error."""


def parse_point(text: str) -> tuple[float, float]:
    """'38.72,-9.14' -> (38.72, -9.14), checked against the coordinate ranges."""
    try:
        lat_text, lon_text = text.split(",")
        lat, lon = float(lat_text), float(lon_text)
    except ValueError:
        msg = f"--near must be LAT,LON in decimal degrees, e.g. 38.7223,-9.1393 (got {text!r})"
        raise GeocodeError(msg) from None
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        msg = f"--near is out of range: latitude -90..90, longitude -180..180 (got {text!r})"
        raise GeocodeError(msg)
    return lat, lon


def build_url(
    query: str,
    *,
    limit: int = 1,
    lang: str = "en",
    city: bool = False,
    near: tuple[float, float] | None = None,
    country: str | None = None,
    osm_tag: str | None = None,
) -> str:
    text = " ".join(query.split())
    if not text:
        msg = "the place to look up is empty"
        raise GeocodeError(msg)
    if len(text) > MAX_QUERY or not text.isprintable():
        msg = f"the place must be one printable line of at most {MAX_QUERY} characters"
        raise GeocodeError(msg)
    if not 1 <= limit <= MAX_LIMIT:
        msg = f"--limit must be between 1 and {MAX_LIMIT} (got {limit})"
        raise GeocodeError(msg)
    if lang not in LANGUAGES:
        msg = (
            f"--lang must be one of {', '.join(LANGUAGES)}: Photon rejects other languages "
            f"(got {lang!r})"
        )
        raise GeocodeError(msg)
    params: list[tuple[str, str]] = [("q", text), ("limit", str(limit)), ("lang", lang)]
    if city:
        params.append(("layer", "city"))
    if near is not None:
        params += [("lat", f"{near[0]:.6f}"), ("lon", f"{near[1]:.6f}")]
    if country is not None:
        if not COUNTRY.match(country):
            msg = f"--country must be a two-letter ISO country code, e.g. PT (got {country!r})"
            raise GeocodeError(msg)
        params.append(("countrycode", country.upper()))
    if osm_tag is not None:
        if not OSM_TAG.match(osm_tag):
            msg = f"--osm-tag must look like key:value, e.g. aeroway:aerodrome (got {osm_tag!r})"
            raise GeocodeError(msg)
        params.append(("osm_tag", osm_tag))
    return f"{PHOTON_URL}?{urlencode(params, quote_via=quote)}"


def fetch(url: str) -> Any:
    request = urllib.request.Request(
        url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"}
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            body = response.read()
    except urllib.error.HTTPError as error:
        detail = ""
        with contextlib.suppress(OSError):
            detail = error.read().decode("utf-8", "replace")[:300]
        msg = f"Photon answered HTTP {error.code}" + (f": {detail}" if detail else "")
        raise GeocodeError(msg) from None
    except OSError as error:  # URLError, timeouts, refused connections
        reason = getattr(error, "reason", error)
        msg = (
            f"Photon could not be reached ({reason}); try again once, or take coordinates from "
            "the source page"
        )
        raise GeocodeError(msg) from None
    try:
        return json.loads(body)
    except ValueError:
        msg = "Photon answered something that is not JSON"
        raise GeocodeError(msg) from None


def _label(properties: Mapping[str, Any]) -> str:
    street = " ".join(
        str(part) for part in (properties.get("street"), properties.get("housenumber")) if part
    )
    parts: list[str] = []
    for part in (properties.get("name"), street, properties.get("city"), properties.get("country")):
        if part and str(part) not in parts:
            parts.append(str(part))
    return ", ".join(parts)


def parse_features(payload: Any) -> list[dict[str, Any]]:
    """Photon GeoJSON -> [{name, lat, lon, label, type}]. GeoJSON coordinates are [lon, lat]."""
    features = payload.get("features") if isinstance(payload, dict) else None
    if not isinstance(features, list):
        msg = "Photon's answer has no 'features' list"
        raise GeocodeError(msg)
    places: list[dict[str, Any]] = []
    for feature in features:
        if not isinstance(feature, dict):
            continue
        geometry = feature.get("geometry") or {}
        coordinates = geometry.get("coordinates") if isinstance(geometry, dict) else None
        if not (isinstance(coordinates, list) and len(coordinates) >= 2):
            continue
        lon, lat = coordinates[0], coordinates[1]
        if not all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in (lon, lat)):
            continue
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            continue
        properties = feature.get("properties") or {}
        if not isinstance(properties, dict):
            properties = {}
        name = properties.get("name") or properties.get("street") or properties.get("city")
        places.append(
            {
                "name": str(name) if name else _label(properties) or "?",
                "lat": round(float(lat), 6),
                "lon": round(float(lon), 6),
                "label": _label(properties),
                "type": properties.get("type"),
            }
        )
    return places


def geocode(query: str, **options: Any) -> list[dict[str, Any]]:
    """Look `query` up; best match first. Raises GeocodeError."""
    return parse_features(fetch(build_url(query, **options)))


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="geocode.py",
        description="Name and coordinates of a place, from Photon (OpenStreetMap data).",
        allow_abbrev=False,
    )
    parser.add_argument("place", help="the place, in English or the local language, with its city")
    parser.add_argument("--limit", type=int, default=1, help=f"results, 1-{MAX_LIMIT} (default 1)")
    parser.add_argument("--lang", default="en", help="en (default), default (local names), de, fr")
    parser.add_argument("--city", action="store_true", help="only cities and towns")
    parser.add_argument("--near", metavar="LAT,LON", help="prefer results near this point")
    parser.add_argument("--country", metavar="CC", help="two-letter country code, e.g. PT")
    parser.add_argument(
        "--osm-tag", metavar="KEY:VALUE", help="OpenStreetMap tag, e.g. aeroway:aerodrome"
    )
    args = parser.parse_args(argv)
    try:
        places = geocode(
            args.place,
            limit=args.limit,
            lang=args.lang,
            city=args.city,
            near=parse_point(args.near) if args.near else None,
            country=args.country,
            osm_tag=args.osm_tag,
        )
    except GeocodeError as error:
        print(f"geocode.py: error: {error}", file=sys.stderr)
        return 2
    if not places:
        print(
            f"geocode.py: no match for {args.place!r}; try the English or local name with the "
            "city, --city, or --near LAT,LON",
            file=sys.stderr,
        )
        return 1
    print(json.dumps(places[: args.limit], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
