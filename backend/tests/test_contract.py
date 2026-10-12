"""Contract with TripTracker (spec row "Contratto"): every Trip produced from the plan fixtures
passes the trip.json TripTracker exports, a 121-character title is rejected, and TripTracker's
caps (LIMITE) hold exactly at their edges.

The schema is the vendored `z.toJSONSchema(tripSchema)` output (zod 4.5.4, TripTracker 71be320,
docs/triptracker/schema-notes.md §7). Every Trip is checked twice: with the backend's own
`validate_trip` and with a plain `Draft202012Validator`, so a leniency in `validate_trip` cannot
hide a contract break.
"""

from __future__ import annotations

import copy
import datetime as dt
import json
from decimal import Decimal
from pathlib import Path
from typing import Any, cast
from zoneinfo import ZoneInfo

import pytest
from jsonschema import Draft202012Validator
from pydantic import ValidationError

from app.fx import FxQuote, FxRates, convert_cents
from app.mapping import MAX_NOTES, SeededTripIds, plan_to_trip
from app.plan import MAX_TRIP_DAYS, Plan
from app.triptracker_schema import TripSchema, TripSchemaError, validate_trip

FIXTURES_DIR = Path(__file__).parent / "fixtures"
PLANS_DIR = FIXTURES_DIR / "plans"
SCHEMA_PATH = FIXTURES_DIR / "triptracker" / "trip.schema.json"
VALID_TRIP_PATH = FIXTURES_DIR / "triptracker" / "valid_trip.json"
PLAN_FIXTURES = sorted(path.name for path in PLANS_DIR.glob("*.json"))

NOW = dt.datetime(2026, 10, 12, 10, 0, tzinfo=ZoneInfo("Europe/Rome"))
FX = FxRates(
    quotes={
        ("GBP", dt.date(2026, 10, 12)): FxQuote(
            "GBP", Decimal("0.8655"), dt.date(2026, 10, 12), "bdi_daily"
        ),
        ("GBP", dt.date(2026, 10, 11)): FxQuote(
            "GBP", Decimal("0.86512"), dt.date(2026, 10, 9), "bdi_daily"
        ),
        ("USD", dt.date(2026, 10, 12)): FxQuote(
            "USD", Decimal("1.1658"), dt.date(2026, 10, 12), "bdi_daily"
        ),
    }
)


# --- helpers ----------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def schema_document() -> dict[str, Any]:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def schema(schema_document: dict[str, Any]) -> TripSchema:
    return TripSchema.from_document(
        schema_document, source="file", url=SCHEMA_PATH.as_uri(), loaded_at=NOW
    )


@pytest.fixture(scope="module")
def plain_validator(schema_document: dict[str, Any]) -> Draft202012Validator:
    return Draft202012Validator(schema_document)


def fixture_data(name: str) -> dict[str, Any]:
    return json.loads((PLANS_DIR / name).read_text(encoding="utf-8"))


def map_trip(plan: Plan, *, fx: FxRates = FX) -> dict[str, Any]:
    trip = plan_to_trip(plan, now=NOW, fx=fx, ids=SeededTripIds(2027)).trip
    return copy.deepcopy(cast(dict[str, Any], trip))


def city_trip() -> dict[str, Any]:
    return map_trip(Plan.model_validate(fixture_data("city_weekend.json")))


def set_at(trip: dict[str, Any], path: tuple[str | int, ...], value: Any) -> None:
    target: Any = trip
    for part in path[:-1]:
        target = target[part]
    target[path[-1]] = value


def drop_at(trip: dict[str, Any], path: tuple[str | int, ...]) -> None:
    target: Any = trip
    for part in path[:-1]:
        target = target[part]
    del target[path[-1]]


def assert_valid(trip: dict[str, Any], schema: TripSchema, plain: Draft202012Validator) -> None:
    assert validate_trip(trip, schema=schema) == []
    assert [error.message for error in plain.iter_errors(trip)] == []


def a_day_with_stops(trip: dict[str, Any]) -> int:
    return next(index for index, day in enumerate(trip["days"]) if day["stops"])


# --- the fixtures ---------------------------------------------------------------------------


def test_the_vendored_trip_passes(
    schema: TripSchema, plain_validator: Draft202012Validator
) -> None:
    assert_valid(json.loads(VALID_TRIP_PATH.read_text(encoding="utf-8")), schema, plain_validator)


def test_there_are_at_least_four_plan_fixtures_in_2027() -> None:
    assert len(PLAN_FIXTURES) >= 4
    for name in PLAN_FIXTURES:
        plan = Plan.model_validate(fixture_data(name))
        assert plan.start_date.year == plan.end_date.year == 2027


@pytest.mark.parametrize("name", PLAN_FIXTURES)
def test_every_fixture_trip_passes_trip_json(
    name: str, schema: TripSchema, plain_validator: Draft202012Validator
) -> None:
    trip = map_trip(Plan.model_validate(fixture_data(name)))

    assert_valid(trip, schema, plain_validator)


@pytest.mark.parametrize("name", PLAN_FIXTURES)
def test_every_fixture_trip_passes_without_exchange_rates(
    name: str, schema: TripSchema, plain_validator: Draft202012Validator
) -> None:
    trip = map_trip(Plan.model_validate(fixture_data(name)), fx=FxRates())

    assert_valid(trip, schema, plain_validator)


@pytest.mark.parametrize("name", PLAN_FIXTURES)
def test_a_fixture_with_a_121_character_title_is_rejected(name: str) -> None:
    data = fixture_data(name)
    data["title"] = "T" * 121

    with pytest.raises(ValidationError) as caught:
        Plan.model_validate(data)

    assert [error["loc"] for error in caught.value.errors()] == [("title",)]


def test_a_trip_with_a_121_character_title_fails_trip_json(
    schema: TripSchema, plain_validator: Draft202012Validator
) -> None:
    data = fixture_data("city_weekend.json")
    data["title"] = "T" * 120
    trip = map_trip(Plan.model_validate(data))
    assert_valid(trip, schema, plain_validator)

    trip["title"] = "T" * 121

    assert validate_trip(trip, schema=schema) == [
        TripSchemaError(path="title", message="must be at most 120 characters (got 121)")
    ]
    assert not plain_validator.is_valid(trip)


# --- caps at their edges (LIMITE) ------------------------------------------------------------


def _string_caps(trip: dict[str, Any]) -> list[tuple[tuple[str | int, ...], int]]:
    day = a_day_with_stops(trip)
    stop: tuple[str | int, ...] = ("days", day, "stops", 0)
    booking: tuple[str | int, ...] = ("bookings", 0)
    return [
        (("title",), 120),
        (("destinationName",), 200),
        (("baseName",), 200),
        (("baseAddress",), 300),
        (("days", day, "title"), 120),
        ((*stop, "title"), 120),
        ((*stop, "locationName"), 200),
        ((*stop, "address"), 300),
        ((*stop, "url"), 2000),
        ((*stop, "notes"), 4000),
        ((*booking, "title"), 120),
        ((*booking, "vendor"), 200),
        ((*booking, "phone"), 40),
        ((*booking, "url"), 2000),
        ((*booking, "notes"), MAX_NOTES),
    ]


CAP_CASES = [path for path, _ in _string_caps(city_trip())]


@pytest.mark.parametrize("path", CAP_CASES, ids=lambda path: ".".join(map(str, path)))
def test_string_caps_hold_at_the_edge(
    path: tuple[str | int, ...], schema: TripSchema, plain_validator: Draft202012Validator
) -> None:
    trip = city_trip()
    cap = dict(_string_caps(trip))[path]

    set_at(trip, path, "x" * cap)
    assert_valid(trip, schema, plain_validator)

    set_at(trip, path, "x" * (cap + 1))
    errors = validate_trip(trip, schema=schema)
    assert len(errors) == 1
    assert errors[0].message == f"must be at most {cap} characters (got {cap + 1})"
    assert not plain_validator.is_valid(trip)


def test_caps_count_code_points_like_zod(
    schema: TripSchema, plain_validator: Draft202012Validator
) -> None:
    trip = city_trip()
    trip["title"] = "\U0001f642" * 120  # 240 UTF-16 units, 120 code points

    assert_valid(trip, schema, plain_validator)


def test_a_plan_at_every_cap_maps_to_a_valid_trip(
    schema: TripSchema, plain_validator: Draft202012Validator
) -> None:
    long_url = "https://www.booking.com/searchresults.html?ss=" + "x" * 1954
    source_url = "https://www.example.org/prezzi?q=" + "y" * 1967
    assert len(long_url) == len(source_url) == 2000
    stop = {
        "ref": "s",
        "title": "S" * 120,
        "kind": "activity",
        "location_name": "L" * 200,
        "address": "A" * 300,
        "url": "https://www.example.org/?q=" + "u" * 1973,
        "notes": "N" * 4000,
    }
    plan = Plan.model_validate(
        {
            "title": "T" * 120,
            "destination": "D" * 200,
            "timezone": "Europe/Rome",
            "start_date": "2027-06-14",
            "end_date": "2027-06-15",
            "travelers": 9,
            "lodging_name": "B" * 200,
            "lodging_address": "I" * 300,
            "days": [{"date": "2027-06-14", "title": "G" * 120, "stops": [stop]}],
            "bookings": [
                {
                    "title": "P" * 120,
                    "kind": "lodging",
                    "vendor": "V" * 200,
                    "book_by_reason": "R" * 300,
                    "scheduled_for": "2027-06-14T15:00:00+02:00",
                    "link": long_url,
                    "phone": "+" + "3" * 39,
                    "price": {
                        "amount_cents": 10**11,
                        "currency": "USD",
                        "status": "estimated",
                        "source_url": source_url,
                        "retrieved_at": "2026-10-12T09:00:00+02:00",
                    },
                    "stop_ref": "s",
                    "notes": "M" * 4000,
                }
            ],
            "summary": "S" * 4000,
        }
    )

    trip = map_trip(plan)

    assert_valid(trip, schema, plain_validator)
    booking = trip["bookings"][0]
    assert booking["url"] == long_url
    assert len(booking["notes"]) <= MAX_NOTES
    assert booking["costCents"] == convert_cents(10**11, Decimal("1.1658"))


def test_a_plan_of_120_days_maps_to_a_valid_trip(
    schema: TripSchema, plain_validator: Draft202012Validator
) -> None:
    start = dt.date(2027, 1, 1)
    end = start + dt.timedelta(days=MAX_TRIP_DAYS - 1)
    plan = Plan.model_validate(
        {
            "title": "Giro del mondo",
            "destination": "Mondo",
            "timezone": "UTC",
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "travelers": 1,
            "days": [],
            "bookings": [],
            "summary": "Centoventi giorni.",
        }
    )

    trip = map_trip(plan)

    assert len(trip["days"]) == MAX_TRIP_DAYS == 120
    assert_valid(trip, schema, plain_validator)

    extra = {**trip["days"][-1], "id": "extra-day", "date": "2027-05-01", "dayIndex": 120}
    trip["days"].append(extra)
    trip["endDate"] = "2027-05-01"
    assert validate_trip(trip, schema=schema) == [
        TripSchemaError(path="days", message="must have at most 120 items (got 121)")
    ]
    assert not plain_validator.is_valid(trip)


def test_a_plan_of_121_days_is_rejected_before_mapping() -> None:
    with pytest.raises(ValidationError, match=r"spans 121 days"):
        Plan.model_validate(
            {
                "title": "Troppo lungo",
                "destination": "Mondo",
                "timezone": "UTC",
                "start_date": "2027-01-01",
                "end_date": "2027-05-01",
                "travelers": 1,
                "days": [],
                "bookings": [],
                "summary": "Centoventuno giorni.",
            }
        )


# --- what TripTracker rejects (schema-notes §7 and §9) ---------------------------------------


def _stop(trip: dict[str, Any]) -> tuple[str | int, ...]:
    return ("days", a_day_with_stops(trip), "stops", 0)


@pytest.mark.parametrize(
    ("mutate", "path", "message"),
    [
        (lambda t: set_at(t, ("baseName",), None), "baseName", "must be a string, not null"),
        (
            lambda t: set_at(t, ("bookings", 0, "dueAt"), "2027-03-01T23:59:00"),
            "bookings[0].dueAt",
            "must match the pattern",
        ),
        (
            lambda t: set_at(t, (*_stop(t), "durationMin"), 0),
            "days[0].stops[0].durationMin",
            "must be greater than 0",
        ),
        (lambda t: set_at(t, (*_stop(t), "lat"), 91), "days[0].stops[0].lat", "must be at most 90"),
        (lambda t: set_at(t, (*_stop(t), "title"), ""), "days[0].stops[0].title", "must not be"),
        (
            lambda t: set_at(t, (*_stop(t), "startTime"), "24:00"),
            "days[0].stops[0].startTime",
            "must match the pattern",
        ),
        (
            lambda t: set_at(t, ("bookings", 0, "costCents"), -1),
            "bookings[0].costCents",
            "must be at least 0",
        ),
        (
            lambda t: set_at(t, ("bookings", 0, "costCents"), 10.5),
            "bookings[0].costCents",
            "must be an integer",
        ),
        (
            lambda t: set_at(t, ("bookings", 0, "status"), "planned"),
            "bookings[0].status",
            "must be one of",
        ),
        (
            lambda t: set_at(t, (*_stop(t), "state"), "to_book"),
            "days[0].stops[0].state",
            "must be one of",
        ),
        (lambda t: set_at(t, ("summary",), "x"), "summary", "is not a TripTracker field"),
        (lambda t: set_at(t, (*_stop(t), "ref"), "d1"), "days[0].stops[0].ref", "is not a"),
        (
            lambda t: set_at(t, ("bookings", 0, "stop_ref"), "d1"),
            "bookings[0].stop_ref",
            "is not a TripTracker field",
        ),
        (lambda t: drop_at(t, ("bookings", 0, "sortOrder")), "bookings[0].sortOrder", "required"),
        (lambda t: drop_at(t, ("coverSeed",)), "coverSeed", "is required"),
        (
            lambda t: set_at(t, ("endDate",), "2027-04-15"),
            "endDate",
            "must be on or after startDate",
        ),
        # JavaScript semantics, as Zod checks them at /import
        (
            lambda t: set_at(t, ("days", 0, "date"), "2027-04-16\n"),
            "days[0].date",
            "must match the pattern",
        ),
        (
            lambda t: set_at(t, ("endDate",), "2027-04-\u0661\u0668"),  # Arabic-Indic 18
            "endDate",
            "must match the pattern",
        ),
    ],
)
def test_what_triptracker_rejects_is_rejected(
    mutate: Any, path: str, message: str, schema: TripSchema
) -> None:
    trip = city_trip()
    mutate(trip)

    errors = validate_trip(trip, schema=schema)

    assert [error.path for error in errors] == [path]
    assert message in errors[0].message
