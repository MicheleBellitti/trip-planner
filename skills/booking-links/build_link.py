#!/usr/bin/env python3
"""Print one prefilled booking-search URL built from templates.json.

    python3 build_link.py <provider> --param value ...   one URL on stdout, nothing else
    python3 build_link.py --list                          every provider and its parameters
    python3 build_link.py <provider> --help               one provider's parameters

The URL is a search page prefilled with places, dates and the party (counts and children's
ages). It is never a specific offer, and it never carries personal data. Bad input exits with
status 2 and a message on stderr that says what to fix; never write or edit the URL by hand
instead. Notes about unverified template parts go to stderr too, so stdout is always exactly
one URL.

Stdlib only, Python 3.10+: this script runs inside the agent sandbox.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
import unicodedata
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any
from urllib.parse import quote

TEMPLATES_PATH = Path(__file__).resolve().with_name("templates.json")

MAX_URL_LENGTH = 2000
"""TripTracker's URL cap (LIMITE.url) and PlanBooking.link's max_length."""
MAX_TRAVELLERS = 9
"""PlanRequest accepts at most 9 travellers."""
MAX_SPAN_DAYS = 120
"""TripTracker's longest trip; no stay or round trip is longer."""
MAX_PLACE_LENGTH = 200
"""TripTracker's name cap (LIMITE.nome)."""

DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")
TIME_PATTERN = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
IATA_PATTERN = re.compile(r"^[A-Z]{3}$")
PLACEHOLDER = re.compile(r"\{(\w+)\}")
LIST_PLACEHOLDER = re.compile(r"^\{(\w+)\[\]\}$")
# Characters that never belong in a place name; they would mostly be a URL, an e-mail address
# or markup slipped in from a web page.
FORBIDDEN_IN_PLACE = set('@<>{}[]|\\^`"#?=&;%*$~+')
SLUG_SAFE_PLACE = re.compile(r"^[\w .'’()-]+$")


class LinkError(ValueError):
    """Bad input. The message tells the agent what to change."""


Values = dict[str, Any]
"""Template variables: str, list[str] (for {name[]}) or None (leave the pair out)."""


# --- templates -----------------------------------------------------------------------------


def load_templates(path: Path = TEMPLATES_PATH) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        data = json.load(handle)
    providers = data.get("providers")
    if not isinstance(providers, dict) or not providers:
        msg = f"{path} has no providers"
        raise RuntimeError(msg)
    return providers


# --- parameter parsers: raw string -> value, LinkError on bad input -------------------------


def parse_date(name: str, raw: str) -> dt.date:
    text = raw.strip()
    if not DATE_PATTERN.match(text):
        msg = f"--{name} must be a date YYYY-MM-DD, e.g. 2027-05-13 (got {raw!r})"
        raise LinkError(msg)
    try:
        return dt.date.fromisoformat(text)
    except ValueError:
        msg = f"--{name} is not a real calendar date (got {raw!r})"
        raise LinkError(msg) from None


def parse_time(name: str, raw: str) -> str:
    text = raw.strip()
    if not TIME_PATTERN.match(text):
        msg = f"--{name} must be a local time HH:MM, 24h, e.g. 08:30 (got {raw!r})"
        raise LinkError(msg)
    return text


def parse_iata(name: str, raw: str) -> str:
    text = raw.strip()
    if not IATA_PATTERN.match(text):
        msg = (
            f"--{name} must be a 3-letter IATA airport or city code in upper case, e.g. MXP "
            f"or MIL (got {raw!r})"
        )
        raise LinkError(msg)
    return text


def parse_count(name: str, raw: str, spec: Mapping[str, Any]) -> int:
    text = raw.strip()
    if not text.isdigit() or not text.isascii():
        msg = f"--{name} must be a whole number (got {raw!r})"
        raise LinkError(msg)
    value = int(text)
    low, high = spec.get("min", 0), spec.get("max", MAX_TRAVELLERS)
    if not low <= value <= high:
        msg = f"--{name} must be between {low} and {high} (got {value})"
        raise LinkError(msg)
    return value


def parse_ages(name: str, raw: str) -> list[int]:
    text = raw.strip()
    if not text:
        return []
    ages: list[int] = []
    for item in text.split(","):
        part = item.strip()
        if not part.isdigit() or not part.isascii():
            msg = (
                f"--{name} must list the children's ages as whole numbers separated by commas, "
                f"e.g. 8,5 (got {raw!r})"
            )
            raise LinkError(msg)
        age = int(part)
        if age > 17:
            msg = (
                f"--{name}: {age} is not a child's age (0-17); count people aged 18 or more "
                "with --adults"
            )
            raise LinkError(msg)
        ages.append(age)
    return ages


def _clean_text(name: str, raw: str) -> str:
    text = " ".join(raw.split())
    if not text:
        msg = f"--{name} must not be empty"
        raise LinkError(msg)
    if len(text) > MAX_PLACE_LENGTH:
        msg = f"--{name} is too long ({len(text)} characters, at most {MAX_PLACE_LENGTH})"
        raise LinkError(msg)
    bad = sorted({char for char in text if char in FORBIDDEN_IN_PLACE or not char.isprintable()})
    if bad or "://" in text:
        shown = "".join(bad) or "://"
        msg = (
            f"--{name} must be a place name, not a URL, address book entry or code; remove "
            f"{shown!r} (got {raw!r})"
        )
        raise LinkError(msg)
    if not any(char.isalpha() for char in text):
        msg = f"--{name} must contain a place name (got {raw!r})"
        raise LinkError(msg)
    return text


def parse_place(name: str, raw: str) -> str:
    return _clean_text(name, raw)


def _place_parts(name: str, raw: str, *, example: str) -> list[str]:
    text = _clean_text(name, raw)
    parts = [part.strip() for part in text.split(",")]
    if len(parts) < 2 or not all(parts):
        msg = (
            f"--{name} needs the place and its province or country, e.g. {example!r} (got {raw!r})"
        )
        raise LinkError(msg)
    for part in parts:
        if not SLUG_SAFE_PLACE.match(part):
            msg = f"--{name} may hold only letters, digits, spaces and . ' - ( ) (got {raw!r})"
            raise LinkError(msg)
    return parts


def parse_place_parts(name: str, raw: str) -> list[str]:
    return _place_parts(name, raw, example="Lisbona, Portogallo")


def _ascii_slug(text: str) -> str:
    """'São Paulo' -> 'sao-paulo': accents dropped, lower case, other characters -> '-'."""
    decomposed = unicodedata.normalize("NFKD", text)
    ascii_text = decomposed.encode("ascii", "ignore").decode("ascii").lower()
    return re.sub(r"[^a-z0-9]+", "-", ascii_text).strip("-")


def parse_city_country_en(name: str, raw: str) -> str:
    parts = _place_parts(name, raw, example="Milan, Italy")
    slugs = [_ascii_slug(part) for part in parts]
    if not all(slugs):
        msg = f"--{name} must be written in English letters, e.g. 'Milan, Italy' (got {raw!r})"
        raise LinkError(msg)
    return "-".join(slugs)


def parse_city_it(name: str, raw: str) -> str:
    text = _clean_text(name, raw)
    if "," in text or not SLUG_SAFE_PLACE.match(text):
        msg = f"--{name} must be one Italian city name, e.g. 'Firenze' (got {raw!r})"
        raise LinkError(msg)
    slug = _ascii_slug(text)
    if not slug:
        msg = f"--{name} must contain letters (got {raw!r})"
        raise LinkError(msg)
    return slug


def parse_station(name: str, raw: str) -> str:
    return _clean_text(name, raw)


def parse_italo_station(name: str, raw: str, stations: Mapping[str, str]) -> str:
    text = " ".join(raw.split())
    if text in stations:
        return text
    by_name = {_ascii_slug(station): code for code, station in stations.items()}
    code = by_name.get(_ascii_slug(text))
    if code is None:
        known = "; ".join(f"{code} {station}" for code, station in stations.items())
        msg = (
            f"--{name}: {raw!r} is not in the Italo station table ({known}). For another "
            "station use trenitalia or omio"
        )
        raise LinkError(msg)
    return code


Parser = Callable[[str, str, Mapping[str, Any], Mapping[str, Any]], Any]

PARSERS: dict[str, Parser] = {
    "date": lambda name, raw, spec, provider: parse_date(name, raw),
    "time": lambda name, raw, spec, provider: parse_time(name, raw),
    "iata": lambda name, raw, spec, provider: parse_iata(name, raw),
    "count": lambda name, raw, spec, provider: parse_count(name, raw, spec),
    "ages": lambda name, raw, spec, provider: parse_ages(name, raw),
    "place": lambda name, raw, spec, provider: parse_place(name, raw),
    "place_parts": lambda name, raw, spec, provider: parse_place_parts(name, raw),
    "city_country_en": lambda name, raw, spec, provider: parse_city_country_en(name, raw),
    "city_it": lambda name, raw, spec, provider: parse_city_it(name, raw),
    "station": lambda name, raw, spec, provider: parse_station(name, raw),
    "italo_station": lambda name, raw, spec, provider: parse_italo_station(
        name, raw, provider["stations"]
    ),
}


# --- helpers for the builders ----------------------------------------------------------------


def count_ages(ages: Sequence[int], low: int, high: int) -> int:
    """How many ages fall in [low, high]."""
    return sum(1 for age in ages if low <= age <= high)


def ymd(value: dt.date) -> str:
    return value.strftime("%Y-%m-%d")


def dmy(value: dt.date, sep: str) -> str:
    return value.strftime(f"%d{sep}%m{sep}%Y")


def check_infants(params: Mapping[str, Any]) -> None:
    """Airlines seat at most one child under 2 per adult."""
    infants = count_ages(params.get("child-ages") or [], 0, 1)
    if infants > params["adults"]:
        msg = (
            f"{infants} children under 2 but only {params['adults']} adults: airlines allow one "
            "child under 2 per adult"
        )
        raise LinkError(msg)


def check_rooms(params: Mapping[str, Any]) -> None:
    if params["rooms"] > params["adults"]:
        msg = (
            f"--rooms ({params['rooms']}) cannot exceed --adults ({params['adults']}): every "
            "room needs an adult"
        )
        raise LinkError(msg)


# --- builders: parsed params -> template variables, one per provider -------------------------


def build_booking(p: Mapping[str, Any]) -> Values:
    check_rooms(p)
    ages: list[int] = p.get("child-ages") or []
    return {
        "destination": p["destination"],
        "checkin": ymd(p["checkin"]),
        "checkout": ymd(p["checkout"]),
        "adults": str(p["adults"]),
        "children": str(len(ages)),
        "child_ages": [str(age) for age in ages],
        "rooms": str(p["rooms"]),
    }


def build_airbnb(p: Mapping[str, Any]) -> Values:
    ages: list[int] = p.get("child-ages") or []
    slug = "--".join("-".join(part.split()) for part in p["destination"])
    return {
        "place_slug": slug,
        "checkin": ymd(p["checkin"]),
        "checkout": ymd(p["checkout"]),
        "adults": str(p["adults"] + count_ages(ages, 13, 17)),
        "children": str(count_ages(ages, 2, 12)),
        "infants": str(count_ages(ages, 0, 1)),
    }


def _plural(count: int, singular: str, plural: str) -> str:
    return f"{count} {singular if count == 1 else plural}"


def build_google_flights(p: Mapping[str, Any]) -> Values:
    check_infants(p)
    ages: list[int] = p.get("child-ages") or []
    adults = p["adults"] + count_ages(ages, 12, 17)
    children = count_ages(ages, 0, 11)
    party = _plural(adults, "adult", "adults")
    if children:
        party += " and " + _plural(children, "child", "children")
    if p.get("return") is not None:
        q = (
            f"Flights to {p['to']} from {p['from']} on {ymd(p['depart'])} through "
            f"{ymd(p['return'])} for {party}"
        )
    else:
        q = f"One way flights to {p['to']} from {p['from']} on {ymd(p['depart'])} for {party}"
    return {"q": q}


def build_expedia_hotels(p: Mapping[str, Any]) -> Values:
    check_rooms(p)
    ages: list[int] = p.get("child-ages") or []
    rooms, adults = p["rooms"], p["adults"]
    base, extra = divmod(adults, rooms)
    per_room = [base + 1] * extra + [base] * (rooms - extra)
    children = [f"{index % rooms + 1}_{age}" for index, age in enumerate(ages)]
    return {
        "destination": p["destination"],
        "checkin": ymd(p["checkin"]),
        "checkout": ymd(p["checkout"]),
        "rooms": str(rooms),
        "adults_per_room": ",".join(str(count) for count in per_room),
        "room_children": ",".join(children) or None,
    }


def build_expedia_flights(p: Mapping[str, Any]) -> Values:
    check_infants(p)
    ages: list[int] = p.get("child-ages") or []
    back = p.get("return")
    return {
        "trip": "roundtrip" if back is not None else "oneway",
        "from": p["from"],
        "to": p["to"],
        "depart": ymd(p["depart"]),
        "return": ymd(back) if back is not None else None,
        "adults": str(p["adults"]),
        "children": str(len(ages)),
        "child_age_list": "[" + ";".join(str(age) for age in ages) + "]" if ages else "",
    }


def build_kiwi(p: Mapping[str, Any]) -> Values:
    check_infants(p)
    ages: list[int] = p.get("child-ages") or []
    back = p.get("return")
    return {
        "from_slug": p["from"],
        "to_slug": p["to"],
        "depart": ymd(p["depart"]),
        "return_or_no_return": ymd(back) if back is not None else "no-return",
        "adults": str(p["adults"] + count_ages(ages, 12, 17)),
        "children": str(count_ages(ages, 2, 11)),
        "infants": str(count_ages(ages, 0, 1)),
    }


def build_lastminute(p: Mapping[str, Any]) -> Values:
    check_infants(p)
    ages: list[int] = p.get("child-ages") or []
    children = [age for age in ages if age < 12]
    back = p.get("return")
    return {
        "adults": str(p["adults"] + count_ages(ages, 12, 17)),
        "children": str(len(children)),
        "child_ages": [str(age) for age in children],
        "trip_type": "ROUND_TRIP" if back is not None else "ONE_WAY",
        "from": p["from"],
        "to": p["to"],
        "depart": p["depart"].strftime("%Y%m%d"),
        "return_from": p["to"] if back is not None else None,
        "return_to": p["from"] if back is not None else None,
        "return": back.strftime("%Y%m%d") if back is not None else None,
    }


def build_trenitalia(p: Mapping[str, Any]) -> Values:
    ages: list[int] = p.get("child-ages") or []
    back: dt.date | None = p.get("return")
    if back is not None and back == p["depart"] and p["return-time"] <= p["time"]:
        msg = "--return-time must be later than --time for a same-day return"
        raise LinkError(msg)
    return {
        "from": p["from"],
        "to": p["to"],
        "depart": dmy(p["depart"], "-"),
        "depart_hour": p["time"][:2],
        # One way: returnDate must still be sent, equal to the departure date.
        "return_date": dmy(back if back is not None else p["depart"], "-"),
        "round_trip": "true" if back is not None else None,
        "return_hour": p["return-time"][:2] if back is not None else None,
        "adults": str(p["adults"] + count_ages(ages, 15, 17)),
        "children": str(count_ages(ages, 0, 14)),
    }


def build_italo(p: Mapping[str, Any]) -> Values:
    ages: list[int] = p.get("child-ages") or []
    back: dt.date | None = p.get("return")
    return {
        "from": p["from"],
        "to": p["to"],
        "journey": "return" if back is not None else "single",
        "depart": dmy(p["depart"], "/"),
        "return": dmy(back, "/") if back is not None else None,
        "adults": str(p["adults"]),
        "young": str(count_ages(ages, 14, 17)),
        "children": str(count_ages(ages, 3, 13)),
        "infants": str(count_ages(ages, 0, 2)),
    }


def build_omio(p: Mapping[str, Any]) -> Values:
    return {"from_slug": p["from"], "to_slug": p["to"], "depart": dmy(p["depart"], "/")}


BUILDERS: dict[str, Callable[[Mapping[str, Any]], Values]] = {
    "booking": build_booking,
    "airbnb": build_airbnb,
    "google_flights": build_google_flights,
    "expedia_hotels": build_expedia_hotels,
    "expedia_flights": build_expedia_flights,
    "kiwi": build_kiwi,
    "lastminute": build_lastminute,
    "trenitalia": build_trenitalia,
    "italo": build_italo,
    "omio": build_omio,
}


# --- validation and rendering ----------------------------------------------------------------


def parse_params(
    provider_name: str, provider: Mapping[str, Any], raw: Mapping[str, str | None]
) -> dict[str, Any]:
    """Check names, required params and defaults, parse every value, check cross-param rules."""
    specs: Mapping[str, Mapping[str, Any]] = provider["params"]
    unknown = sorted(name for name, value in raw.items() if value is not None and name not in specs)
    if unknown:
        allowed = ", ".join(f"--{name}" for name in specs)
        given = ", ".join(f"--{name}" for name in unknown)
        msg = f"{provider_name} does not take {given}; it takes {allowed}"
        raise LinkError(msg)

    parsed: dict[str, Any] = {}
    for name, spec in specs.items():
        value = raw.get(name)
        requires = spec.get("requires")
        if value is not None and requires and raw.get(requires) is None:
            msg = f"--{name} needs --{requires}"
            raise LinkError(msg)
        if value is None:
            if spec.get("required"):
                msg = f"{provider_name} needs --{name}: {spec.get('help', '')}".rstrip(": ")
                raise LinkError(msg)
            if "default" in spec and (not requires or raw.get(requires) is not None):
                value = str(spec["default"])
            else:
                parsed[name] = None
                continue
        parsed[name] = PARSERS[spec["type"]](name, value, spec, provider)

    for name, spec in specs.items():
        for rule in ("after", "on_or_after"):
            other = spec.get(rule)
            if other is None or parsed.get(name) is None or parsed.get(other) is None:
                continue
            start, end = parsed[other], parsed[name]
            if end < start or (rule == "after" and end == start):
                relation = "after" if rule == "after" else "on or after"
                msg = f"--{name} ({end}) must be {relation} --{other} ({start})"
                raise LinkError(msg)
            if (end - start).days > MAX_SPAN_DAYS:
                days = (end - start).days
                msg = f"--{other} to --{name} spans {days} days; at most {MAX_SPAN_DAYS}"
                raise LinkError(msg)

    if "from" in specs and "to" in specs and parsed["from"] == parsed["to"]:
        msg = f"--from and --to are the same place ({parsed['from']})"
        raise LinkError(msg)
    if "adults" in specs:
        total = parsed["adults"] + len(parsed.get("child-ages") or [])
        if total > MAX_TRAVELLERS:
            msg = f"{total} travellers: a plan has at most {MAX_TRAVELLERS}"
            raise LinkError(msg)
    return parsed


def _fill(template: str, values: Values, *, encode: Callable[[str], str] | None) -> str | None:
    """Replace every {name}; None when one of them has no value. `encode` quotes the values
    (path segments); the query encodes the whole filled value instead."""
    missing = False

    def substitute(match: re.Match[str]) -> str:
        nonlocal missing
        value = values[match.group(1)]  # KeyError: templates.json and the builder disagree
        if value is None:
            missing = True
            return ""
        if not isinstance(value, str):
            msg = f"template variable {match.group(1)!r} is not a string"
            raise TypeError(msg)
        return encode(value) if encode else value

    text = PLACEHOLDER.sub(substitute, template)
    return None if missing else text


def render_url(provider: Mapping[str, Any], values: Values) -> str:
    base = _fill(provider["url"], values, encode=lambda value: quote(value, safe=""))
    if base is None:
        msg = "a path placeholder has no value"
        raise RuntimeError(msg)
    value_safe: str = provider.get("safe", "")
    key_safe: str = provider.get("key_safe", "")
    pairs: list[str] = []
    for key_template, value_template in provider["query"]:
        list_match = LIST_PLACEHOLDER.match(value_template)
        if list_match:
            items = values[list_match.group(1)] or []
            for index, item in enumerate(items):
                key = key_template.replace("{i}", str(index))
                pairs.append(f"{quote(key, safe=key_safe)}={quote(item, safe=value_safe)}")
            continue
        value = _fill(value_template, values, encode=None)
        if value is None:
            continue
        pairs.append(f"{quote(key_template, safe=key_safe)}={quote(value, safe=value_safe)}")
    return f"{base}?{'&'.join(pairs)}" if pairs else base


def build_url(
    provider_name: str,
    raw_params: Mapping[str, str | None],
    *,
    templates: Mapping[str, Any] | None = None,
) -> str:
    """The URL for `provider_name` with the given raw (string) parameters; LinkError on bad
    input. Parameter names are the command-line ones without dashes: 'child-ages'."""
    providers = templates if templates is not None else load_templates()
    provider = providers.get(provider_name)
    if provider is None:
        msg = f"unknown provider {provider_name!r}; known: {', '.join(providers)}"
        raise LinkError(msg)
    params = parse_params(provider_name, provider, raw_params)
    url = render_url(provider, BUILDERS[provider_name](params))
    if len(url) > MAX_URL_LENGTH:
        msg = (
            f"the URL would be {len(url)} characters, more than {MAX_URL_LENGTH}; shorten the "
            "place names"
        )
        raise LinkError(msg)
    return url


# --- command line ----------------------------------------------------------------------------


def describe(providers: Mapping[str, Any]) -> str:
    """The --list text: providers, hosts, verification status and parameters."""
    lines: list[str] = []
    for name, provider in providers.items():
        lines.append(
            f"{name}  ({provider['label']}, {provider['category']}, host {provider['host']}, "
            f"{provider['status'].replace('_', ' ')})"
        )
        for param, spec in provider["params"].items():
            if spec.get("required"):
                flag = "required"
            elif "default" in spec:
                flag = f"default {spec['default']}"
            else:
                flag = "optional"
            lines.append(f"    --{param:<12} {flag:<14} {spec.get('help', '')}")
        lines.append(f"    travellers: {provider['travellers']}")
        if provider.get("unverified"):
            lines.append(f"    unverified: {'; '.join(provider['unverified'])}")
        if provider.get("warning"):
            lines.append(f"    warning: {provider['warning']}")
        if provider.get("note_it"):
            lines.append(f"    note for the user (Italian): {provider['note_it']}")
    return "\n".join(lines)


def _provider_parser(name: str, provider: Mapping[str, Any]) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=f"build_link.py {name}",
        description=f"{provider['label']} search link ({provider['host']}). "
        f"Travellers: {provider['travellers']}",
        allow_abbrev=False,
    )
    for param, spec in provider["params"].items():
        parser.add_argument(f"--{param}", action="append", metavar="VALUE", help=spec.get("help"))
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    try:
        providers = load_templates()
    except (OSError, ValueError, RuntimeError) as error:
        print(
            f"build_link.py: internal error: cannot read templates.json: {error}", file=sys.stderr
        )
        return 1
    if not args:
        print(
            "build_link.py: error: name a provider: build_link.py <provider> --param value ... "
            f"(providers: {', '.join(providers)}; details: --list)",
            file=sys.stderr,
        )
        return 2
    if args[0] in {"-h", "--help"}:
        print((__doc__ or "").strip())
        return 0
    if args[0] == "--list":
        print(describe(providers))
        return 0
    name = args[0]
    provider = providers.get(name)
    if provider is None:
        print(
            f"build_link.py: error: unknown provider {name!r}; known: {', '.join(providers)} "
            "(see --list)",
            file=sys.stderr,
        )
        return 2
    namespace = _provider_parser(name, provider).parse_args(args[1:])  # exits 2 on bad flags
    raw: dict[str, str | None] = {}
    for param in provider["params"]:
        given: list[str] | None = getattr(namespace, param.replace("-", "_"))
        if given is not None and len(given) > 1:
            print(f"build_link.py: error: --{param} given {len(given)} times", file=sys.stderr)
            return 2
        raw[param] = given[0] if given else None
    try:
        url = build_url(name, raw, templates=providers)
    except LinkError as error:
        print(f"build_link.py: error: {name}: {error}", file=sys.stderr)
        return 2
    if provider.get("warning"):
        print(f"build_link.py: note: {provider['warning']}", file=sys.stderr)
    print(url)
    return 0


if __name__ == "__main__":
    sys.exit(main())
