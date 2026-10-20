"""plan_to_trip() (app/mapping.py): Plan -> TripTracker Trip.

The spec's row ("Test e verifica"): a Day for every date, increasing sortOrder, a fallback dueAt
never in the past, EUR in costCents and conversion of other currencies, stopId resolved from
stop_ref. Plus: links outside the allowlist go to the notes, the notes budget, time zones across
DST, and the purity of the function (now, fx and ids are injected).
"""

from __future__ import annotations

import copy
import datetime as dt
import json
import re
import uuid
from decimal import Decimal
from pathlib import Path
from typing import Any, cast
from zoneinfo import ZoneInfo

import pytest
import time_machine

from app import mapping
from app.fx import FxQuote, FxRates, convert_cents
from app.link_health import LinkHealth, LinkHealthMap
from app.links import check_link
from app.mapping import (
    COVER_SEED_RANGE,
    DEFAULT_LEAD_DAYS,
    MAX_NOTES,
    NOTE_BOOK_BY_REASON,
    NOTE_BOOK_NOW,
    NOTE_ELLIPSIS,
    NOTE_FX_CONVERTED,
    NOTE_FX_MISSING,
    NOTE_PRICE_ESTIMATED,
    NOTE_PRICE_SOURCE,
    NOTE_PRICE_SOURCE_MISSING,
    NOTE_PRICE_VERIFIED,
    NOTE_UNCHECKED_LINK,
    NOTE_URL_KEEP,
    SORT_ORDER_STEP,
    WARNING_BOOK_NOW,
    WARNING_FX_MISSING,
    RandomTripIds,
    SeededTripIds,
    TripMapping,
    booking_notes,
    fallback_due_at,
    format_amount,
    format_instant,
    plan_to_trip,
)
from app.plan import BookingKind, Plan, PlanBooking

PLANS_DIR = Path(__file__).parent / "fixtures" / "plans"
FIXTURES = sorted(path.name for path in PLANS_DIR.glob("*.json"))

ROME = ZoneInfo("Europe/Rome")
UTC = dt.UTC
NOW = dt.datetime(2026, 10, 12, 10, 0, tzinfo=ROME)
"""The tests' "now": the planner runs on 2026-10-12, the fixtures travel in 2027."""

GBP_TODAY = FxQuote("GBP", Decimal("0.8655"), dt.date(2026, 10, 12), "bdi_daily")
GBP_FRIDAY = FxQuote("GBP", Decimal("0.86512"), dt.date(2026, 10, 9), "bdi_daily")
FX = FxRates(
    quotes={
        ("GBP", dt.date(2026, 10, 12)): GBP_TODAY,
        # 2026-10-11 is a Sunday: the latest Banca d'Italia rate is Friday's.
        ("GBP", dt.date(2026, 10, 11)): GBP_FRIDAY,
    }
)

# TripTracker's `instant` regex (lib/schema.ts), with JavaScript's ASCII \d.
INSTANT = re.compile(
    r"^\d{4}-\d{2}-\d{2}T([01]\d|2[0-3]):[0-5]\d(:[0-5]\d)?(\.\d+)?"
    r"(Z|[+-]([01]\d|2[0-3]):[0-5]\d)$",
    re.ASCII,
)

PRICE: dict[str, Any] = {
    "amount_cents": 12000,
    "currency": "EUR",
    "status": "estimated",
    "source_url": "https://www.example.org/prezzi",
    "retrieved_at": "2026-10-12T09:00:00+02:00",
}


# --- helpers ----------------------------------------------------------------------------------


def fixture_data(name: str) -> dict[str, Any]:
    return json.loads((PLANS_DIR / name).read_text(encoding="utf-8"))


def fixture_plan(name: str) -> Plan:
    return Plan.model_validate(fixture_data(name))


def make_plan(
    *,
    bookings: list[dict[str, Any]] | None = None,
    timezone: str = "Europe/Rome",
    start_date: str = "2027-06-14",
    end_date: str = "2027-06-16",
    **overrides: Any,
) -> Plan:
    """A small valid plan: three days, one stop (`d1-visit`) on the first."""
    data: dict[str, Any] = {
        "title": "Torino, tre giorni a giugno",
        "destination": "Torino, Italia",
        "timezone": timezone,
        "start_date": start_date,
        "end_date": end_date,
        "travelers": 2,
        "days": [
            {
                "date": start_date,
                "title": "Arrivo",
                "stops": [{"ref": "d1-visit", "title": "Museo Egizio", "kind": "activity"}],
            }
        ],
        "bookings": bookings or [],
        "summary": "Tre giorni a Torino.",
    }
    data.update(overrides)
    return Plan.model_validate(data)


def run(plan: Plan, *, now: dt.datetime = NOW, fx: FxRates = FX, seed: int = 7) -> TripMapping:
    return plan_to_trip(plan, now=now, fx=fx, ids=SeededTripIds(seed))


def run_with(
    plan: Plan, *, health: LinkHealthMap | None, now: dt.datetime = NOW, seed: int = 7
) -> TripMapping:
    return plan_to_trip(plan, now=now, fx=FX, ids=SeededTripIds(seed), health=health)


def dead(url: str, *, fallback: str | None = None, allowed: bool = False) -> LinkHealthMap:
    entry = LinkHealth("dead", "http_404", 404, fallback=fallback, fallback_allowed=allowed)
    return LinkHealthMap({url: entry})


def trip_of(result: TripMapping) -> dict[str, Any]:
    """The Trip as plain JSON data (TripTracker's keys, no TypedDict narrowing)."""
    return cast(dict[str, Any], result.trip)


def booking_titled(trip: dict[str, Any], title: str) -> dict[str, Any]:
    matches = [booking for booking in trip["bookings"] if booking["title"] == title]
    assert len(matches) == 1, title
    return matches[0]


def all_stops(trip: dict[str, Any]) -> list[dict[str, Any]]:
    return [stop for day in trip["days"] for stop in day["stops"]]


def walk(value: Any) -> list[Any]:
    """Every value nested in `value`, itself included."""
    found = [value]
    if isinstance(value, dict):
        for item in cast(dict[str, Any], value).values():
            found.extend(walk(item))
    elif isinstance(value, list):
        for item in cast(list[Any], value):
            found.extend(walk(item))
    return found


def parse_instant(text: str) -> dt.datetime:
    return dt.datetime.fromisoformat(text)


# --- days ------------------------------------------------------------------------------------


@pytest.mark.parametrize("name", FIXTURES)
def test_one_day_per_date_in_order(name: str) -> None:
    plan = fixture_plan(name)
    result = run(plan)
    trip = trip_of(result)

    assert [day["date"] for day in trip["days"]] == [d.isoformat() for d in plan.trip_dates()]
    assert [day["dayIndex"] for day in trip["days"]] == list(range(len(plan.trip_dates())))
    assert {day["tripId"] for day in trip["days"]} == {trip["id"]}


def test_dates_without_stops_still_get_a_day() -> None:
    trip = trip_of(run(fixture_plan("seaside_week_children.json")))

    empty = [day for day in trip["days"] if not day["stops"]]

    assert [day["date"] for day in empty] == ["2027-07-12", "2027-07-14", "2027-07-16"]
    assert all(set(day) == {"id", "tripId", "date", "dayIndex", "stops"} for day in empty)


def test_day_title_is_copied_only_when_present() -> None:
    trip = trip_of(run(fixture_plan("train_trip.json")))
    titles = {day["date"]: day.get("title") for day in trip["days"]}

    assert titles["2027-03-26"] == "Roma → Firenze"
    assert "title" not in trip["days"][3]  # 2027-03-29 has stops but no title


# --- stops -----------------------------------------------------------------------------------


@pytest.mark.parametrize("name", FIXTURES)
def test_stops_keep_the_plan_order_with_sort_order_steps(name: str) -> None:
    plan = fixture_plan(name)
    trip = trip_of(run(plan))
    plan_days = {day.date.isoformat(): day for day in plan.days}

    for day in trip["days"]:
        orders = [stop["sortOrder"] for stop in day["stops"]]
        assert orders == [SORT_ORDER_STEP * (i + 1) for i in range(len(orders))]
        assert orders == sorted(orders)
        assert all(stop["dayId"] == day["id"] for stop in day["stops"])
        assert all(stop["state"] == "planned" for stop in day["stops"])
        plan_day = plan_days.get(day["date"])
        expected = [stop.title for stop in plan_day.stops] if plan_day else []
        assert [stop["title"] for stop in day["stops"]] == expected


def test_stop_fields_are_copied_with_triptracker_names() -> None:
    trip = trip_of(run(fixture_plan("city_weekend.json")))
    dinner = next(stop for stop in all_stops(trip) if stop["title"] == "Cena al Figlmüller")

    assert dinner == {
        "id": dinner["id"],
        "dayId": trip["days"][0]["id"],
        "title": "Cena al Figlmüller",
        "kind": "meal",
        "startTime": "20:00",
        "durationMin": 90,
        "locationName": "Figlmüller Wollzeile",
        "address": "Wollzeile 5, 1010 Wien",
        "lat": 48.2089,
        "lon": 16.3747,
        "notes": "Specialità: Wiener Schnitzel. Si paga anche con carta.",
        "sortOrder": 5000,
        "state": "planned",
    }


def test_missing_optional_stop_fields_are_omitted_not_null() -> None:
    trip = trip_of(run(fixture_plan("city_weekend.json")))
    rest = next(stop for stop in all_stops(trip) if stop["title"] == "Pomeriggio libero")

    assert set(rest) == {"id", "dayId", "title", "kind", "sortOrder", "state"}


def test_stop_url_is_copied_unchanged() -> None:
    trip = trip_of(run(fixture_plan("city_weekend.json")))
    stephansdom = next(stop for stop in all_stops(trip) if stop["title"].startswith("Duomo"))

    assert stephansdom["url"] == "https://www.stephanskirche.at/"


def test_coordinates_only_when_both_are_present() -> None:
    trip = trip_of(run(fixture_plan("flexible_month_non_eur.json")))
    stops = {stop["title"]: stop for stop in all_stops(trip)}

    studio = stops["Warner Bros. Studio Tour London"]  # the plan has lat without lon
    hotel = stops["Check-in al The Hoxton"]

    assert "lat" not in studio
    assert "lon" not in studio
    assert (hotel["lat"], hotel["lon"]) == (51.5175, -0.1213)


def test_zero_coordinates_are_kept() -> None:
    plan = make_plan(
        days=[
            {
                "date": "2027-06-14",
                "stops": [
                    {"ref": "s", "title": "Null Island", "kind": "rest", "lat": 0.0, "lon": 0.0}
                ],
            }
        ]
    )
    stop = all_stops(trip_of(run(plan)))[0]

    assert (stop["lat"], stop["lon"]) == (0.0, 0.0)


# --- trip ------------------------------------------------------------------------------------


def test_trip_fields_are_copied_and_planner_only_fields_stay_out() -> None:
    plan = fixture_plan("city_weekend.json")
    trip = trip_of(run(plan))

    assert {
        key: trip[key] for key in trip if key not in {"id", "coverSeed", "days", "bookings"}
    } == {
        "title": "Vienna, weekend lungo di aprile",
        "destinationName": "Vienna, Austria",
        "timezone": "Europe/Vienna",
        "startDate": "2027-04-16",
        "endDate": "2027-04-18",
        "baseName": "Hotel Am Konzerthaus Vienna",
        "baseAddress": "Am Heumarkt 35-37, 1030 Wien",
    }
    text = json.dumps(trip, ensure_ascii=False)
    assert plan.summary not in text
    assert plan.warnings[0] not in text
    assert "Hotel Motto" not in text  # the alternative stays in the planner
    assert len(trip["bookings"]) == len(plan.bookings)


def test_lodging_is_optional() -> None:
    trip = trip_of(run(make_plan()))

    assert "baseName" not in trip
    assert "baseAddress" not in trip


@pytest.mark.parametrize("name", FIXTURES)
def test_trip_is_plain_json_without_nulls(name: str) -> None:
    trip = trip_of(run(fixture_plan(name)))
    values = walk(trip)

    assert None not in values
    assert all(isinstance(v, str | int | float | list | dict) for v in values)
    assert json.loads(json.dumps(trip)) == trip


# --- ids -------------------------------------------------------------------------------------


@pytest.mark.parametrize("name", FIXTURES)
def test_ids_are_unique_uuid4_and_cover_seed_in_range(name: str) -> None:
    trip = trip_of(run(fixture_plan(name)))
    ids = [trip["id"]]
    ids += [day["id"] for day in trip["days"]]
    ids += [stop["id"] for stop in all_stops(trip)]
    ids += [booking["id"] for booking in trip["bookings"]]

    assert len(set(ids)) == len(ids)
    for value in ids:
        parsed = uuid.UUID(value)
        assert parsed.version == 4
        assert str(parsed) == value
    assert 0 <= trip["coverSeed"] < COVER_SEED_RANGE


def test_seeded_ids_are_deterministic() -> None:
    plan = fixture_plan("train_trip.json")

    assert run(plan, seed=11) == run(plan, seed=11)
    assert trip_of(run(plan, seed=11))["id"] != trip_of(run(plan, seed=12))["id"]


def test_random_ids_are_uuid4_and_seeds_in_range() -> None:
    ids = RandomTripIds()
    values = [ids.new_id() for _ in range(200)]
    seeds = [ids.cover_seed() for _ in range(200)]

    assert len(set(values)) == 200
    assert all(uuid.UUID(value).version == 4 for value in values)
    assert all(0 <= seed < COVER_SEED_RANGE for seed in seeds)


def test_stop_ids_map_every_ref() -> None:
    plan = fixture_plan("seaside_week_children.json")
    result = run(plan)
    stop_ids = {stop["id"] for stop in all_stops(trip_of(result))}

    assert set(result.stop_ids) == {stop.ref for _, _, stop in plan.iter_stops()}
    assert set(result.stop_ids.values()) == stop_ids


# --- bookings --------------------------------------------------------------------------------


@pytest.mark.parametrize("name", FIXTURES)
def test_bookings_are_to_book_in_plan_order(name: str) -> None:
    plan = fixture_plan(name)
    trip = trip_of(run(plan))

    assert [b["title"] for b in trip["bookings"]] == [b.title for b in plan.bookings]
    assert [b["sortOrder"] for b in trip["bookings"]] == [
        SORT_ORDER_STEP * (i + 1) for i in range(len(plan.bookings))
    ]
    assert all(b["status"] == "to_book" for b in trip["bookings"])
    assert all(b["tripId"] == trip["id"] for b in trip["bookings"])


@pytest.mark.parametrize("name", FIXTURES)
def test_stop_id_is_resolved_from_stop_ref(name: str) -> None:
    plan = fixture_plan(name)
    result = run(plan)
    trip = trip_of(result)
    stops_by_id = {stop["id"]: stop for stop in all_stops(trip)}
    plan_stops = {stop.ref: stop for _, _, stop in plan.iter_stops()}

    for plan_booking, booking in zip(plan.bookings, trip["bookings"], strict=True):
        if plan_booking.stop_ref is None:
            assert "stopId" not in booking
            continue
        assert booking["stopId"] == result.stop_ids[plan_booking.stop_ref]
        assert stops_by_id[booking["stopId"]]["title"] == plan_stops[plan_booking.stop_ref].title


def test_booking_fields_are_copied() -> None:
    trip = trip_of(run(fixture_plan("city_weekend.json")))
    dinner = booking_titled(trip, "Cena al Figlmüller")

    assert dinner == {
        "id": dinner["id"],
        "tripId": trip["id"],
        "stopId": dinner["stopId"],
        "title": "Cena al Figlmüller",
        "vendor": "Figlmüller Wollzeile",
        "kind": "restaurant",
        "status": "to_book",
        "dueAt": "2027-04-14T20:00:00+02:00",
        "scheduledFor": "2027-04-16T20:00:00+02:00",
        "phone": "+43 1 512 6177",
        "sortOrder": 3000,
    }


def test_never_set_fields() -> None:
    for name in FIXTURES:
        trip = trip_of(run(fixture_plan(name)))
        for key in ("notes", "baseLat", "baseLon", "icsSequence"):
            assert key not in trip
        assert all("notes" not in day for day in trip["days"])
        for booking in trip["bookings"]:
            assert "leadDays" not in booking
            assert "confirmationRef" not in booking


# --- the two dates ---------------------------------------------------------------------------


def test_book_by_and_scheduled_for_are_rendered_in_the_trip_timezone() -> None:
    trip = trip_of(run(fixture_plan("flexible_month_non_eur.json")))
    flights = booking_titled(trip, "Voli Milano Linate ⇄ London Heathrow")

    assert flights["dueAt"] == "2027-02-28T23:59:00+00:00"
    # 08:05 in Milan is 07:05 in London: same instant, the trip's offset.
    assert flights["scheduledFor"] == "2027-05-10T07:05:00+01:00"


def test_an_explicit_book_by_is_converted_to_the_trip_zone() -> None:
    plan = make_plan(
        timezone="Europe/Lisbon",
        bookings=[
            {
                "title": "Biglietti",
                "kind": "ticket",
                "book_by": "2027-02-15T12:00:00+01:00",
                "scheduled_for": "2027-06-15T10:00:00+01:00",
            }
        ],
    )
    booking = trip_of(run(plan))["bookings"][0]

    assert booking["dueAt"] == "2027-02-15T11:00:00+00:00"
    assert booking["scheduledFor"] == "2027-06-15T10:00:00+01:00"


@pytest.mark.parametrize("name", FIXTURES)
def test_due_at_is_never_in_the_past_and_always_before_scheduled_for(name: str) -> None:
    trip = trip_of(run(fixture_plan(name)))

    for booking in trip["bookings"]:
        for key in ("dueAt", "scheduledFor"):
            if key in booking:
                assert INSTANT.match(booking[key]), booking[key]
        if "dueAt" in booking:
            assert parse_instant(booking["dueAt"]) > NOW
        if "dueAt" in booking and "scheduledFor" in booking:
            assert parse_instant(booking["dueAt"]) < parse_instant(booking["scheduledFor"])
            assert booking["dueAt"] != booking["scheduledFor"]


@pytest.mark.parametrize("kind", sorted(DEFAULT_LEAD_DAYS))
def test_fallback_is_scheduled_for_minus_the_kind_default_lead(kind: BookingKind) -> None:
    scheduled = dt.datetime(2027, 6, 15, 18, 0, tzinfo=ROME)

    due = fallback_due_at(scheduled, kind, tz=ROME, now=NOW)

    assert due == scheduled - dt.timedelta(days=DEFAULT_LEAD_DAYS[kind])
    assert due is not None
    assert due.utcoffset() == dt.timedelta(hours=2)


def test_default_lead_days_copy_triptracker() -> None:
    assert dict(DEFAULT_LEAD_DAYS) == {
        "restaurant": 2,
        "wellness": 3,
        "ticket": 3,
        "parking": 1,
        "transport": 1,
        "lodging": 7,
        "activity": 2,
        "other": 2,
    }


def test_fallback_keeps_the_wall_clock_across_spring_dst() -> None:
    trip = trip_of(run(fixture_plan("train_trip.json")))

    hotel = booking_titled(trip, "Hotel Antico Doge, 2 notti")
    train = booking_titled(trip, "Frecciarossa Firenze → Venezia")

    assert hotel["scheduledFor"] == "2027-03-28T15:00:00+02:00"
    assert hotel["dueAt"] == "2027-03-21T15:00:00+01:00"
    assert train["scheduledFor"] == "2027-03-28T09:30:00+02:00"
    assert train["dueAt"] == "2027-03-27T09:30:00+01:00"


def test_fallback_keeps_the_wall_clock_across_autumn_dst() -> None:
    scheduled = dt.datetime.fromisoformat("2027-11-03T09:00:00+01:00")

    due = fallback_due_at(scheduled, "lodging", tz=ROME, now=NOW)

    assert due is not None
    assert format_instant(due, ROME) == "2027-10-27T09:00:00+02:00"


def test_fallback_inside_the_spring_gap_moves_forward() -> None:
    # 02:30 on 2027-03-28 does not exist in Rome (02:00 -> 03:00).
    scheduled = dt.datetime.fromisoformat("2027-03-29T02:30:00+02:00")

    due = fallback_due_at(scheduled, "transport", tz=ROME, now=NOW)

    assert due is not None
    assert format_instant(due, ROME) == "2027-03-28T03:30:00+02:00"


def test_fallback_inside_the_autumn_fold_takes_the_earlier_instant() -> None:
    # 02:30 on 2027-10-31 happens twice in Rome (03:00 CEST -> 02:00 CET).
    scheduled = dt.datetime.fromisoformat("2027-11-01T02:30:00+01:00")

    due = fallback_due_at(scheduled, "transport", tz=ROME, now=NOW)

    assert due is not None
    assert format_instant(due, ROME) == "2027-10-31T02:30:00+02:00"


def test_fallback_is_never_before_tomorrow() -> None:
    scheduled = dt.datetime.fromisoformat("2026-10-15T09:00:00+02:00")  # lodging: 7 days ago

    due = fallback_due_at(scheduled, "lodging", tz=ROME, now=NOW)

    assert due is not None
    assert format_instant(due, ROME) == "2026-10-13T10:00:00+02:00"
    assert NOW < due < scheduled


def test_fallback_floor_is_truncated_to_the_minute() -> None:
    now = dt.datetime(2026, 10, 12, 10, 0, 45, 500_000, tzinfo=ROME)
    scheduled = dt.datetime.fromisoformat("2026-10-15T09:00:00+02:00")

    due = fallback_due_at(scheduled, "lodging", tz=ROME, now=now)

    assert due is not None
    assert format_instant(due, ROME) == "2026-10-13T10:00:00+02:00"


def test_fallback_tomorrow_is_in_the_trip_timezone() -> None:
    new_york = ZoneInfo("America/New_York")
    now = dt.datetime.fromisoformat("2026-10-12T23:30:00+02:00")  # 17:30 in New York
    scheduled = dt.datetime.fromisoformat("2026-10-20T12:00:00-04:00")

    due = fallback_due_at(scheduled, "lodging", tz=new_york, now=now)

    assert due is not None
    assert format_instant(due, new_york) == "2026-10-13T17:30:00-04:00"


def test_fallback_tomorrow_is_a_calendar_day_across_dst() -> None:
    now = dt.datetime.fromisoformat("2026-10-24T12:00:00+02:00")  # the day before DST ends
    scheduled = dt.datetime.fromisoformat("2026-10-27T12:00:00+01:00")

    due = fallback_due_at(scheduled, "lodging", tz=ROME, now=now)

    assert due is not None
    assert format_instant(due, ROME) == "2026-10-25T12:00:00+01:00"  # 25 hours later


def test_fallback_gives_up_when_the_floor_is_not_before_the_event() -> None:
    floor = dt.datetime.fromisoformat("2026-10-13T10:00:00+02:00")

    assert fallback_due_at(floor, "transport", tz=ROME, now=NOW) is None
    assert fallback_due_at(floor - dt.timedelta(hours=3), "transport", tz=ROME, now=NOW) is None
    one_minute_later = floor + dt.timedelta(minutes=1)
    assert fallback_due_at(one_minute_later, "transport", tz=ROME, now=NOW) == floor


def test_a_booking_too_close_for_a_deadline_has_no_due_at_and_a_warning() -> None:
    soon = {"kind": "restaurant", "scheduled_for": "2026-10-13T09:00:00+02:00"}
    plan = make_plan(
        start_date="2026-10-13",
        end_date="2026-10-14",
        bookings=[
            {**soon, "title": "Pranzo da Consorzio"},
            {**soon, "title": "Pranzo da Consorzio", "notes": "Secondo turno."},
        ],
    )

    result = run(plan)
    first, second = trip_of(result)["bookings"]

    assert "dueAt" not in first
    assert first["scheduledFor"] == "2026-10-13T09:00:00+02:00"
    assert first["notes"] == NOTE_BOOK_NOW
    assert second["notes"] == f"Secondo turno.\n{NOTE_BOOK_NOW}"
    assert result.warnings == [WARNING_BOOK_NOW.format(title="Pranzo da Consorzio")]


def test_a_booking_without_dates_has_neither_date() -> None:
    trip = trip_of(run(fixture_plan("train_trip.json")))
    vaporetto = booking_titled(trip, "Abbonamento vaporetto ACTV 48 ore")

    assert "dueAt" not in vaporetto
    assert "scheduledFor" not in vaporetto
    assert NOTE_BOOK_NOW not in vaporetto["notes"]


def test_book_by_without_scheduled_for_gives_only_due_at() -> None:
    plan = make_plan(
        bookings=[
            {"title": "Tessera musei", "kind": "ticket", "book_by": "2027-05-01T12:00:00+02:00"}
        ]
    )
    booking = trip_of(run(plan))["bookings"][0]

    assert booking["dueAt"] == "2027-05-01T12:00:00+02:00"
    assert "scheduledFor" not in booking


def test_naive_datetimes_are_programming_errors() -> None:
    naive = dt.datetime(2027, 6, 15, 18, 0)  # noqa: DTZ001 - the point of the test

    with pytest.raises(ValueError, match="timezone-aware"):
        plan_to_trip(make_plan(), now=naive, fx=FX, ids=SeededTripIds(1))
    with pytest.raises(ValueError, match="timezone-aware"):
        fallback_due_at(naive, "lodging", tz=ROME, now=NOW)
    with pytest.raises(ValueError, match="timezone-aware"):
        fallback_due_at(dt.datetime(2027, 6, 15, tzinfo=ROME), "lodging", tz=ROME, now=naive)
    with pytest.raises(ValueError, match="timezone-aware"):
        format_instant(naive, ROME)


@pytest.mark.parametrize(
    ("value", "tz", "expected"),
    [
        (
            dt.datetime(2026, 11, 14, 15, 0, 0, 123_456, tzinfo=UTC),
            "Europe/Lisbon",
            "2026-11-14T15:00:00+00:00",
        ),
        (dt.datetime(2026, 11, 14, 15, 0, tzinfo=UTC), "Europe/Rome", "2026-11-14T16:00:00+01:00"),
        (dt.datetime(2027, 7, 1, 15, 0, tzinfo=UTC), "Europe/Rome", "2027-07-01T17:00:00+02:00"),
        (
            dt.datetime(2027, 7, 1, 15, 0, tzinfo=UTC),
            "America/New_York",
            "2027-07-01T11:00:00-04:00",
        ),
        (dt.datetime(2027, 7, 1, 15, 0, tzinfo=UTC), "Asia/Kolkata", "2027-07-01T20:30:00+05:30"),
    ],
)
def test_format_instant(value: dt.datetime, tz: str, expected: str) -> None:
    text = format_instant(value, ZoneInfo(tz))

    assert text == expected
    assert INSTANT.match(text)


# --- prices ----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("cents", "text"),
    [(12345, "123,45"), (5, "0,05"), (0, "0,00"), (100, "1,00"), (10**11, "1000000000,00")],
)
def test_format_amount(cents: int, text: str) -> None:
    assert format_amount(cents) == text


def test_eur_prices_go_to_cost_cents_unchanged() -> None:
    trip = trip_of(run(fixture_plan("city_weekend.json")))

    assert booking_titled(trip, "Voli Milano Malpensa ⇄ Vienna")["costCents"] == 31480
    assert "costCents" not in booking_titled(trip, "Cena al Figlmüller")


def test_other_currencies_are_converted_with_the_details_in_the_notes() -> None:
    trip = trip_of(run(fixture_plan("flexible_month_non_eur.json")))
    express = booking_titled(trip, "Heathrow Express, 2 biglietti")

    assert express["costCents"] == convert_cents(5000, GBP_TODAY.rate) == 5777
    expected = NOTE_FX_CONVERTED.format(
        amount="50,00", currency="GBP", rate="0,8655", source="Banca d'Italia", date="12/10/2026"
    )
    assert expected in express["notes"].split("\n")


def test_the_rate_is_the_one_of_the_day_the_price_was_read_in_rome() -> None:
    trip = trip_of(run(fixture_plan("flexible_month_non_eur.json")))

    # Read at 23:30 UTC on 2026-10-11, which is already 2026-10-12 in Rome.
    musical = booking_titled(trip, "Biglietti per il musical")
    # Read at 20:00 Rome time on 2026-10-11 (a Sunday): Friday's rate.
    studio = booking_titled(trip, "Warner Bros. Studio Tour, ingresso delle 10:00")

    assert musical["costCents"] == convert_cents(15000, GBP_TODAY.rate)
    assert studio["costCents"] == convert_cents(11000, GBP_FRIDAY.rate)
    assert "(Banca d'Italia, 09/10/2026)" in studio["notes"]


def test_inforeuro_rates_name_their_source() -> None:
    quote = FxQuote("USD", Decimal("1.1658"), dt.date(2026, 10, 1), "inforeuro_monthly")
    fx = FxRates(quotes={("USD", dt.date(2026, 10, 12)): quote})
    trip = trip_of(run(fixture_plan("flexible_month_non_eur.json"), fx=fx))
    esim = booking_titled(trip, "eSIM dati Regno Unito, 7 giorni")

    assert esim["costCents"] == convert_cents(1900, quote.rate) == 1630
    assert esim["notes"].endswith(
        "Prezzo originale: 19,00 USD, cambio 1,1658 USD per 1 EUR (InforEuro, 01/10/2026)"
    )


def test_a_missing_rate_keeps_the_original_amount_in_the_notes_and_warns() -> None:
    result = run(fixture_plan("flexible_month_non_eur.json"))
    esim = booking_titled(trip_of(result), "eSIM dati Regno Unito, 7 giorni")

    assert "costCents" not in esim
    assert NOTE_FX_MISSING.format(amount="19,00", currency="USD") in esim["notes"]
    assert result.warnings == [
        WARNING_FX_MISSING.format(currency="USD", title="eSIM dati Regno Unito, 7 giorni")
    ]


def test_without_any_rate_every_foreign_price_warns_once() -> None:
    plan = fixture_plan("flexible_month_non_eur.json")
    gbp = {"amount_cents": 1000, "currency": "GBP"}
    twice = make_plan(
        bookings=[
            {"title": "Oyster card", "kind": "transport", "price": {**PRICE, **gbp}},
            {"title": "Oyster card", "kind": "transport", "price": {**PRICE, **gbp}},
        ]
    )

    result = run(plan, fx=FxRates())
    repeated = run(twice, fx=FxRates())

    foreign = [b.title for b in plan.bookings if b.price and b.price.currency != "EUR"]
    assert len(result.warnings) == len(foreign) == 5
    assert repeated.warnings == [WARNING_FX_MISSING.format(currency="GBP", title="Oyster card")]
    assert all("costCents" not in b for b in trip_of(repeated)["bookings"])


# --- links -----------------------------------------------------------------------------------


def test_an_allowed_link_becomes_the_booking_url_exactly() -> None:
    plan = fixture_plan("city_weekend.json")
    trip = trip_of(run(plan))
    flights = booking_titled(trip, "Voli Milano Malpensa ⇄ Vienna")

    assert flights["url"] == plan.bookings[0].link
    assert "Link da verificare" not in flights["notes"]


def test_a_link_outside_the_allowlist_goes_to_the_notes_as_text() -> None:
    plan = fixture_plan("city_weekend.json")
    concert = booking_titled(trip_of(run(plan)), "Concerto al Musikverein, 2 posti in platea")

    assert "url" not in concert
    assert concert["notes"].endswith(
        NOTE_UNCHECKED_LINK.format(url="https://www.musikverein.at/konzerte")
    )


@pytest.mark.parametrize(
    "link",
    [
        "javascript:alert(document.cookie)",
        "http://www.booking.com/searchresults.html",
        "https://www.booking.com.evil.example/searchresults.html",
        "https://user@www.booking.com/",
        "https://evil.example\\.kiwi.com/",
    ],
)
def test_unsafe_links_never_become_a_url(link: str) -> None:
    plan = make_plan(bookings=[{"title": "Hotel", "kind": "lodging", "link": link}])
    booking = trip_of(run(plan))["bookings"][0]

    assert not check_link(link).allowed
    assert "url" not in booking
    assert booking["notes"] == NOTE_UNCHECKED_LINK.format(url=link)


# --- notes -----------------------------------------------------------------------------------


def test_notes_are_the_plan_notes_then_one_provenance_line_each() -> None:
    plan = fixture_plan("city_weekend.json")
    flights = booking_titled(trip_of(run(plan)), "Voli Milano Malpensa ⇄ Vienna")
    price = plan.bookings[0].price
    assert price is not None

    assert flights["notes"].split("\n") == [
        "Andata OS 512 alle 07:10, ritorno OS 517 alle 18:20. Bagaglio a mano da 8 kg incluso.",
        NOTE_PRICE_VERIFIED,
        NOTE_PRICE_SOURCE.format(url=str(price.source_url)),
        NOTE_BOOK_BY_REASON.format(
            reason="La tariffa Light di andata e ritorno sale dopo l'inizio di marzo"
        ),
    ]


def test_estimated_prices_say_so() -> None:
    trip = trip_of(run(fixture_plan("city_weekend.json")))
    hotel = booking_titled(trip, "Hotel Am Konzerthaus, 2 notti")

    assert hotel["notes"].split("\n")[1] == NOTE_PRICE_ESTIMATED


def test_a_reason_without_a_price_is_still_written() -> None:
    trip = trip_of(run(fixture_plan("seaside_week_children.json")))
    boat = booking_titled(trip, "Giro in barca alle grotte")

    assert NOTE_BOOK_BY_REASON.format(
        reason="A luglio le uscite del mattino sono le più richieste"
    ) in boat["notes"].split("\n")


def test_stop_notes_are_copied_without_provenance() -> None:
    trip = trip_of(run(fixture_plan("seaside_week_children.json")))
    boat = next(stop for stop in all_stops(trip) if stop["title"].startswith("Giro in barca"))

    assert boat["notes"] == "Giubbotti salvagente per bambini inclusi; adatto dai 3 anni."


def test_nothing_to_write_means_no_notes() -> None:
    booking = PlanBooking(title="Cena", kind="restaurant")

    assert booking_notes(booking, quote=None, link=None, book_now=False) is None


def _long_url(host: str, length: int) -> str:
    base = f"https://{host}/p?q="
    return base + "a" * (length - len(base))


def _worst_case_booking(**overrides: Any) -> PlanBooking:
    data: dict[str, Any] = {
        "title": "T" * 120,
        "kind": "lodging",
        "book_by_reason": "r" * 300,
        "link": _long_url("www.not-allowed.example", 2000),
        "price": {
            **PRICE,
            "amount_cents": 10**11,
            "currency": "XXX",
            "source_url": _long_url("www.prices.example", 2000),
        },
        "notes": "n" * 4000,
    }
    data.update(overrides)
    return PlanBooking.model_validate(data)


WORST_QUOTE = FxQuote(
    "XXX", Decimal("1234567.123456789"), dt.date(2026, 10, 1), "inforeuro_monthly"
)


def test_every_notes_line_at_its_maximum_still_fits() -> None:
    booking = _worst_case_booking()
    link = check_link(booking.link or "")

    notes = booking_notes(booking, quote=WORST_QUOTE, link=link, book_now=True)

    assert notes is not None
    assert len(notes) <= MAX_NOTES
    free, *provenance = notes.split("\n")
    # Cutting the unchecked link is enough with today's caps; the room it leaves goes back to
    # the plan's own (shortened) notes.
    assert set(free[:-1]) == {"n"}
    assert free.endswith(NOTE_ELLIPSIS)
    assert booking.price is not None
    cut_link = (booking.link or "")[:NOTE_URL_KEEP] + NOTE_ELLIPSIS
    assert provenance == [
        NOTE_PRICE_ESTIMATED,
        NOTE_PRICE_SOURCE.format(url=str(booking.price.source_url)),
        NOTE_BOOK_BY_REASON.format(reason="r" * 300),
        "Prezzo originale: 1000000000,00 XXX, cambio 1234567,123457 XXX per 1 EUR "
        "(InforEuro, 01/10/2026)",
        NOTE_UNCHECKED_LINK.format(url=cut_link),
        NOTE_BOOK_NOW,
    ]


def test_the_price_source_url_is_cut_when_the_link_cut_is_not_enough() -> None:
    # Only reachable if a contract cap grows (here a reason far above plan.MAX_REASON, built
    # without validation): the second URL is cut too, and the cap still holds.
    valid = _worst_case_booking()
    booking = PlanBooking.model_construct(**{**dict(valid), "book_by_reason": "r" * 1800})
    link = check_link(booking.link or "")

    notes = booking_notes(booking, quote=WORST_QUOTE, link=link, book_now=True)

    assert notes is not None
    assert len(notes) <= MAX_NOTES
    assert valid.price is not None
    cut_source = str(valid.price.source_url)[:NOTE_URL_KEEP] + NOTE_ELLIPSIS
    assert NOTE_PRICE_SOURCE.format(url=cut_source) in notes.split("\n")


def test_the_cap_holds_even_beyond_the_contract() -> None:
    valid = _worst_case_booking()
    booking = PlanBooking.model_construct(**{**dict(valid), "book_by_reason": "r" * 9000})

    notes = booking_notes(booking, quote=WORST_QUOTE, link=check_link("x"), book_now=True)

    assert notes is not None
    assert len(notes) == MAX_NOTES
    assert notes.endswith(NOTE_ELLIPSIS)


def test_every_notes_line_at_its_maximum_maps_into_a_valid_length() -> None:
    plan = make_plan(
        bookings=[
            _worst_case_booking(scheduled_for="2026-10-13T08:00:00+02:00").model_dump(mode="json")
        ]
    )
    result = run(plan, fx=FxRates(quotes={("XXX", dt.date(2026, 10, 12)): WORST_QUOTE}))
    booking = trip_of(result)["bookings"][0]

    assert len(booking["notes"]) <= MAX_NOTES
    assert "dueAt" not in booking
    assert "url" not in booking


def test_long_plan_notes_are_shortened_before_any_provenance_line() -> None:
    booking = _worst_case_booking(link=None, price={**PRICE}, book_by_reason="Posti limitati")

    notes = booking_notes(booking, quote=None, link=None, book_now=False)

    assert notes is not None
    assert len(notes) == MAX_NOTES
    free, *provenance = notes.split("\n")
    assert free.endswith(NOTE_ELLIPSIS)
    assert set(free[:-1]) == {"n"}
    assert provenance == [
        NOTE_PRICE_ESTIMATED,
        NOTE_PRICE_SOURCE.format(url="https://www.example.org/prezzi"),
        NOTE_BOOK_BY_REASON.format(reason="Posti limitati"),
    ]


def test_the_unchecked_link_is_cut_first_and_the_room_goes_back_to_the_notes() -> None:
    booking = _worst_case_booking(notes="Colazione inclusa.", book_by_reason=None)
    link = check_link(booking.link or "")

    notes = booking_notes(booking, quote=WORST_QUOTE, link=link, book_now=False)

    assert notes is not None
    assert len(notes) <= MAX_NOTES
    lines = notes.split("\n")
    assert booking.price is not None
    assert lines[0] == "Colazione inclusa."
    assert lines[2] == NOTE_PRICE_SOURCE.format(url=str(booking.price.source_url))
    assert lines[-1] == NOTE_UNCHECKED_LINK.format(
        url=(booking.link or "")[:NOTE_URL_KEEP] + NOTE_ELLIPSIS
    )


def test_short_urls_are_never_cut() -> None:
    booking = _worst_case_booking(link="https://www.musikverein.at/konzerte", book_by_reason=None)
    link = check_link(booking.link or "")

    notes = booking_notes(booking, quote=WORST_QUOTE, link=link, book_now=False)

    assert notes is not None
    assert notes.endswith(NOTE_UNCHECKED_LINK.format(url="https://www.musikverein.at/konzerte"))


# --- purity ----------------------------------------------------------------------------------


def test_the_mapping_reads_no_clock_and_does_not_touch_its_input() -> None:
    plan = fixture_plan("flexible_month_non_eur.json")
    before = copy.deepcopy(plan.model_dump(mode="json"))
    expected = run(plan)

    with time_machine.travel(dt.datetime(2031, 1, 1, tzinfo=UTC), tick=False):
        again = run(plan)

    assert again == expected
    assert plan.model_dump(mode="json") == before


def test_the_module_defaults_are_triptracker_constants() -> None:
    assert mapping.SORT_ORDER_STEP == 1000
    assert mapping.COVER_SEED_RANGE == 10_000
    assert mapping.MAX_NOTES == 4000


# --- the link check's verdicts ---------------------------------------------------------------


def stop_plan(url: str) -> Plan:
    return make_plan(
        days=[
            {
                "date": "2027-06-14",
                "stops": [{"ref": "s", "title": "Museo", "kind": "activity", "url": url}],
            }
        ]
    )


def test_dead_stop_url_uses_the_homepage() -> None:
    url = "https://a.example/mostra/2027"
    plan = stop_plan(url)

    trip = trip_of(run_with(plan, health=dead(url, fallback="https://a.example/")))

    assert all_stops(trip)[0]["url"] == "https://a.example/"


def test_dead_stop_url_without_fallback_is_omitted() -> None:
    url = "https://a.example/"
    trip = trip_of(run_with(stop_plan(url), health=dead(url)))

    assert "url" not in all_stops(trip)[0]


def test_dead_booking_link_with_allowed_fallback_points_to_it() -> None:
    link = "https://www.booking.com/hotel/it/x.html"
    plan = make_plan(bookings=[{"title": "Hotel", "kind": "lodging", "link": link}])

    health = dead(link, fallback="https://www.booking.com/", allowed=True)
    booking = trip_of(run_with(plan, health=health))["bookings"][0]

    assert booking["url"] == "https://www.booking.com/"
    assert "notes" not in booking


def test_dead_booking_link_with_a_disallowed_fallback_is_dropped() -> None:
    link = "https://www.musikverein.at/konzerte/x"
    plan = make_plan(bookings=[{"title": "Concerto", "kind": "ticket", "link": link}])

    health = dead(link, fallback="https://www.musikverein.at/", allowed=False)
    booking = trip_of(run_with(plan, health=health))["bookings"][0]

    assert "url" not in booking
    assert "notes" not in booking


def test_dead_google_flights_link_has_no_url_and_no_unchecked_note() -> None:
    plan = fixture_plan("city_weekend.json")
    link = plan.bookings[0].link
    assert link is not None

    flights = booking_titled(
        trip_of(run_with(plan, health=dead(link))), "Voli Milano Malpensa ⇄ Vienna"
    )

    assert "url" not in flights
    assert "Link da verificare" not in flights["notes"]


def test_an_alive_link_outside_the_allowlist_keeps_the_unchecked_note() -> None:
    link = "https://www.musikverein.at/konzerte"
    plan = make_plan(bookings=[{"title": "Concerto", "kind": "ticket", "link": link}])
    health = LinkHealthMap({link: LinkHealth("ok", "ok", 200)})

    booking = trip_of(run_with(plan, health=health))["bookings"][0]

    assert "url" not in booking
    assert booking["notes"] == NOTE_UNCHECKED_LINK.format(url=link)


def priced_booking(source: str) -> list[dict[str, Any]]:
    price = {**PRICE, "source_url": source}
    return [{"title": "Museo", "kind": "ticket", "price": price}]


def test_dead_price_source_note_says_page_not_found() -> None:
    source = "https://www.A.example/prezzi"
    plan = make_plan(bookings=priced_booking(source))
    price = plan.bookings[0].price
    assert price is not None

    booking = trip_of(run_with(plan, health=dead(str(price.source_url))))["bookings"][0]

    assert NOTE_PRICE_SOURCE_MISSING.format(host="a.example") in booking["notes"]
    assert "Fonte del prezzo: pagina non trovata (a.example)" in booking["notes"]
    assert "prezzi" not in booking["notes"]


def test_dead_price_source_with_a_homepage_names_the_site() -> None:
    """The homepage stands in for the dead page: the note says it is the site, not the price's
    page."""
    source = "https://www.a.example/prezzi"
    plan = make_plan(bookings=priced_booking(source))
    health = dead(source, fallback="https://www.a.example/")

    booking = trip_of(run_with(plan, health=health))["bookings"][0]

    assert "Fonte del prezzo: sito di a.example (https://www.a.example/)" in booking["notes"]
    assert "Fonte del prezzo: https://" not in booking["notes"]
    assert "prezzi" not in booking["notes"]


def test_a_dead_link_that_fails_the_allowlist_is_dropped_even_with_an_allowed_homepage() -> None:
    """As the web app: the homepage replaces a dead booking link only when the link itself also
    passes the allowlist (fail closed). A backslash fails it on an allowlisted host."""
    link = "https://www.booking.com/hotel\\it/x.html"
    assert not check_link(link).allowed
    assert check_link("https://www.booking.com/").allowed
    plan = make_plan(bookings=[{"title": "Hotel", "kind": "lodging", "link": link}])
    health = dead(link, fallback="https://www.booking.com/", allowed=True)

    booking = trip_of(run_with(plan, health=health))["bookings"][0]

    assert "url" not in booking
    assert "notes" not in booking


def test_without_health_the_trip_is_unchanged() -> None:
    plan = fixture_plan("city_weekend.json")

    assert run(plan) == run_with(plan, health=None) == run_with(plan, health=LinkHealthMap.empty())
