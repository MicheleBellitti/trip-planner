"""Plan contract (app/plan.py): field caps, formats and every consistency rule, plus the
error text returned to the coordinator when submit_plan rejects a plan."""

from __future__ import annotations

import copy
import datetime as dt
import json
from typing import Any

import pytest
from pydantic import ValidationError

from app.plan import (
    MAX_AMOUNT_CENTS,
    MAX_DURATION_MIN,
    MAX_REASON,
    MAX_TRIP_DAYS,
    Plan,
    PlanBooking,
    Price,
    Problems,
    describe_validation_errors,
    format_location,
    is_iana_timezone,
    plan_rejection_message,
)

PRICE: dict[str, Any] = {
    "amount_cents": 31480,
    "currency": "EUR",
    "status": "verified",
    "source_url": "https://www.expedia.it/Flights-Search?trip=roundtrip",
    "retrieved_at": "2026-10-12T15:04:00+02:00",
}


def make_plan(**overrides: Any) -> dict[str, Any]:
    """A complete, valid plan as the coordinator would submit it (JSON-shaped)."""
    plan: dict[str, Any] = {
        "title": "Lisbona, weekend lungo di novembre",
        "destination": "Lisbona, Portogallo",
        "timezone": "Europe/Lisbon",
        "start_date": "2026-11-14",
        "end_date": "2026-11-17",
        "travelers": 2,
        "lodging_name": "Hotel Lisboa Plaza",
        "lodging_address": "Travessa do Salitre 7, 1269-066 Lisboa",
        "days": [
            {
                "date": "2026-11-14",
                "title": "Arrivo e Alfama",
                "stops": [
                    {
                        "ref": "d1-flight",
                        "title": "Volo Milano Malpensa → Lisbona",
                        "kind": "transfer",
                        "start_time": "07:05",
                        "duration_min": 170,
                    },
                    {
                        "ref": "d1-dinner",
                        "title": "Cena ad Alfama",
                        "kind": "meal",
                        "start_time": "20:00",
                        "location_name": "Taberna Sal Grosso",
                        "address": "Calçada do Forte 22, Lisboa",
                        "lat": 38.7139,
                        "lon": -9.1257,
                        "url": "https://www.openstreetmap.org/",
                        "notes": "Prenotare un tavolo all'aperto.",
                    },
                ],
            },
            {
                "date": "2026-11-15",
                "stops": [
                    {
                        "ref": "d2-jeronimos",
                        "title": "Visita al Mosteiro dos Jerónimos",
                        "kind": "activity",
                        "start_time": "10:00",
                        "duration_min": 120,
                    },
                    {"ref": "d2-rest", "title": "Pomeriggio libero", "kind": "rest"},
                ],
            },
        ],
        "bookings": [
            {
                "title": "Volo Milano Malpensa → Lisbona",
                "kind": "transport",
                "vendor": "TAP Air Portugal",
                "book_by": "2026-11-07T18:00:00+01:00",
                "book_by_reason": "Tariffa garantita fino al 7 novembre",
                "scheduled_for": "2026-11-14T07:05:00+01:00",
                "link": "https://www.expedia.it/Flights-Search?trip=roundtrip",
                "price": PRICE,
                "stop_ref": "d1-flight",
            },
            {
                "title": "Cena da Sal Grosso",
                "kind": "restaurant",
                "scheduled_for": "2026-11-14T20:00:00+00:00",
                "phone": "+351 21 887 7024",
                "stop_ref": "d1-dinner",
            },
            {
                "title": "Biglietti Jerónimos",
                "kind": "ticket",
                "scheduled_for": "2026-11-15T10:00:00Z",
                "price": {**PRICE, "amount_cents": 3600, "status": "estimated"},
            },
        ],
        "alternatives": [
            {
                "title": "Volo easyJet Milano Malpensa → Lisbona",
                "kind": "transport",
                "scheduled_for": "2026-11-14T06:20:00+01:00",
                "stop_ref": "d1-flight",
            }
        ],
        "warnings": ["Il prezzo dei biglietti Jerónimos è solo stimato."],
        "summary": "Quattro giorni a Lisbona: Alfama, Belém e cucina locale. Totale stimato 650 €.",
    }
    plan.update(overrides)
    return plan


def errors_of(data: dict[str, Any]) -> list[dict[str, Any]]:
    with pytest.raises(ValidationError) as caught:
        Plan.model_validate(data)
    return [dict(error) for error in caught.value.errors(include_url=False)]


def error_types(data: dict[str, Any]) -> set[tuple[tuple[str | int, ...], str]]:
    return {(tuple(error["loc"]), error["type"]) for error in errors_of(data)}


# --- happy path ----------------------------------------------------------------------------


def test_valid_plan_parses_into_typed_values() -> None:
    plan = Plan.model_validate(make_plan())

    assert plan.start_date == dt.date(2026, 11, 14)
    assert plan.days[0].stops[1].lat == pytest.approx(38.7139)
    flight = plan.bookings[0]
    assert flight.book_by is not None
    assert flight.book_by.utcoffset() == dt.timedelta(hours=1)
    assert flight.price is not None
    assert str(flight.price.source_url).startswith("https://www.expedia.it/")
    assert plan.bookings[2].scheduled_for == dt.datetime(2026, 11, 15, 10, tzinfo=dt.UTC)


def test_optional_lists_default_to_empty() -> None:
    data = make_plan()
    del data["alternatives"], data["warnings"]

    plan = Plan.model_validate(data)

    assert plan.alternatives == []
    assert plan.warnings == []


def test_json_round_trip_is_lossless() -> None:
    plan = Plan.model_validate(make_plan())

    assert Plan.model_validate_json(plan.model_dump_json()) == plan
    dumped = plan.model_dump(mode="json")
    assert Plan.model_validate(dumped) == plan
    assert dumped["bookings"][0]["book_by"] == "2026-11-07T18:00:00+01:00"
    assert dumped["start_date"] == "2026-11-14"


def test_whitespace_is_stripped_before_the_caps() -> None:
    plan = Plan.model_validate(make_plan(title="  " + "x" * 120 + "  "))

    assert plan.title == "x" * 120


def test_single_day_trip_is_valid() -> None:
    data = make_plan(start_date="2026-11-14", end_date="2026-11-14")
    data["days"] = data["days"][:1]

    assert Plan.model_validate(data).trip_dates() == [dt.date(2026, 11, 14)]


def test_trip_of_exactly_max_days_is_valid() -> None:
    start = dt.date(2026, 11, 1)
    end = start + dt.timedelta(days=MAX_TRIP_DAYS - 1)

    plan = Plan.model_validate(make_plan(start_date=start.isoformat(), end_date=end.isoformat()))

    assert len(plan.trip_dates()) == MAX_TRIP_DAYS


def test_iter_stops_and_trip_dates() -> None:
    plan = Plan.model_validate(make_plan())

    assert [(d, s, stop.ref) for d, s, stop in plan.iter_stops()] == [
        (0, 0, "d1-flight"),
        (0, 1, "d1-dinner"),
        (1, 0, "d2-jeronimos"),
        (1, 1, "d2-rest"),
    ]
    assert plan.trip_dates() == [dt.date(2026, 11, d) for d in (14, 15, 16, 17)]


# --- field constraints ---------------------------------------------------------------------


@pytest.mark.parametrize(
    ("path", "limit"),
    [
        (("title",), 120),
        (("destination",), 200),
        (("lodging_name",), 200),
        (("lodging_address",), 300),
        (("summary",), 4000),
        (("days", 0, "title"), 120),
        (("days", 0, "stops", 1, "title"), 120),
        (("days", 0, "stops", 1, "location_name"), 200),
        (("days", 0, "stops", 1, "address"), 300),
        (("days", 0, "stops", 1, "url"), 2000),
        (("days", 0, "stops", 1, "notes"), 4000),
        (("bookings", 0, "title"), 120),
        (("bookings", 0, "vendor"), 200),
        (("bookings", 0, "link"), 2000),
        (("bookings", 1, "phone"), 40),
        (("bookings", 0, "notes"), 4000),
    ],
)
def test_text_caps_match_triptracker(path: tuple[str | int, ...], limit: int) -> None:
    prefix = "https://example.com/" if path[-1] == "url" else ""

    def with_value(value: str) -> dict[str, Any]:
        data = make_plan()
        target: Any = data
        for key in path[:-1]:
            target = target[key]
        target[path[-1]] = value
        return data

    Plan.model_validate(with_value(prefix + "x" * (limit - len(prefix))))
    too_long = with_value(prefix + "x" * (limit + 1 - len(prefix)))
    assert error_types(too_long) == {(path, "string_too_long")}


def test_book_by_reason_is_capped_so_the_notes_fit() -> None:
    data = make_plan()
    data["bookings"][0]["book_by_reason"] = "x" * MAX_REASON
    Plan.model_validate(data)

    data["bookings"][0]["book_by_reason"] = "x" * (MAX_REASON + 1)
    assert error_types(data) == {(("bookings", 0, "book_by_reason"), "string_too_long")}


def test_source_url_is_capped_like_a_triptracker_url() -> None:
    prefix = "https://example.com/"
    data = make_plan()
    data["bookings"][0]["price"] = {**PRICE, "source_url": prefix + "x" * (2000 - len(prefix))}
    Plan.model_validate(data)

    data["bookings"][0]["price"] = {**PRICE, "source_url": prefix + "x" * (2001 - len(prefix))}
    assert error_types(data) == {(("bookings", 0, "price", "source_url"), "url_too_long")}


@pytest.mark.parametrize(
    "url",
    [
        "javascript:alert(1)",
        "http://www.museu.pt/",
        "www.museu.pt",
        "/relative/path",
        "https://user:secret@www.museu.pt/",
        "https://",
        "data:text/html,hi",
    ],
)
def test_stop_url_must_be_an_absolute_https_url(url: str) -> None:
    data = make_plan()
    data["days"][0]["stops"][1]["url"] = url

    assert error_types(data) == {(("days", 0, "stops", 1, "url"), "https_url_required")}


def test_stop_url_accepts_https_and_null() -> None:
    data = make_plan()
    data["days"][0]["stops"][1]["url"] = "HTTPS://www.Museu.pt/visita?lang=it"
    Plan.model_validate(data)

    data["days"][0]["stops"][1]["url"] = None
    assert Plan.model_validate(data).days[0].stops[1].url is None


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("title",), "Lisbona\x00"),
        (("summary",), "riga\x0buno"),
        (("days", 0, "stops", 1, "notes"), "\x1b[31mrosso"),
        (("bookings", 0, "book_by_reason"), "a\x00b"),
        (("bookings", 0, "price", "source_url"), "https://www.expedia.it/\x00"),
    ],
)
def test_control_characters_are_rejected(path: tuple[str | int, ...], value: str) -> None:
    data = copy.deepcopy(make_plan())  # make_plan shares the PRICE dict
    target: Any = data
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value

    assert error_types(data) == {(path, "control_character")}


def test_control_characters_in_a_list_name_the_item() -> None:
    (error,) = errors_of(make_plan(warnings=["ok", "fonte\x00 caduta"]))

    assert (error["loc"], error["type"]) == (("warnings",), "control_character")
    assert error["msg"].startswith("item 1 contains the control character U+0000 at position 5")


def test_tab_and_newlines_are_allowed() -> None:
    plan = Plan.model_validate(make_plan(summary="Riga uno\r\nRiga due\tcon tab"))

    assert plan.summary == "Riga uno\r\nRiga due\tcon tab"


def test_a_plan_with_control_characters_is_rejected_from_json_too() -> None:
    raw = json.dumps(make_plan(title="Lisbona\u0000"))

    with pytest.raises(ValidationError, match="control_character"):
        Plan.model_validate_json(raw)


@pytest.mark.parametrize("field", ["title", "destination", "summary"])
def test_required_text_cannot_be_blank(field: str) -> None:
    assert error_types(make_plan(**{field: "   "})) == {((field,), "string_too_short")}


@pytest.mark.parametrize("field", ["title", "ref"])
def test_stop_title_and_ref_cannot_be_blank(field: str) -> None:
    data = make_plan()
    data["days"][1]["stops"][1][field] = ""

    assert error_types(data) == {(("days", 1, "stops", 1, field), "string_too_short")}


def test_booking_title_cannot_be_blank() -> None:
    data = make_plan()
    data["bookings"][2]["title"] = " "

    assert error_types(data) == {(("bookings", 2, "title"), "string_too_short")}


def test_missing_required_fields_are_reported() -> None:
    data = make_plan()
    del data["timezone"], data["summary"]
    del data["days"][0]["stops"][0]["kind"]

    assert error_types(data) == {
        (("timezone",), "missing"),
        (("summary",), "missing"),
        (("days", 0, "stops", 0, "kind"), "missing"),
    }


def test_unknown_fields_are_rejected() -> None:
    data = make_plan(budget_eur=900)
    data["bookings"][0]["due_at"] = "2026-11-07T18:00:00+01:00"

    assert error_types(data) == {
        (("budget_eur",), "extra_forbidden"),
        (("bookings", 0, "due_at"), "extra_forbidden"),
    }


@pytest.mark.parametrize("value", ["00:00", "09:30", "23:59"])
def test_start_time_accepts_hh_mm(value: str) -> None:
    data = make_plan()
    data["days"][0]["stops"][0]["start_time"] = value

    Plan.model_validate(data)


@pytest.mark.parametrize("value", ["24:00", "9:30", "12:60", "12:30:00", "7am", ""])
def test_start_time_rejects_anything_else(value: str) -> None:
    data = make_plan()
    data["days"][0]["stops"][0]["start_time"] = value

    assert error_types(data) == {(("days", 0, "stops", 0, "start_time"), "string_pattern_mismatch")}


def test_stop_kind_is_a_closed_set() -> None:
    data = make_plan()
    data["days"][0]["stops"][0]["kind"] = "flight"

    assert error_types(data) == {(("days", 0, "stops", 0, "kind"), "literal_error")}


def test_booking_kind_is_a_closed_set() -> None:
    data = make_plan()
    data["bookings"][0]["kind"] = "flight"

    assert error_types(data) == {(("bookings", 0, "kind"), "literal_error")}


@pytest.mark.parametrize(("field", "value"), [("duration_min", 0), ("duration_min", -5)])
def test_stop_duration_is_positive(field: str, value: int) -> None:
    data = make_plan()
    data["days"][0]["stops"][0][field] = value

    assert error_types(data) == {(("days", 0, "stops", 0, field), "greater_than")}


def test_stop_duration_is_capped_at_a_week() -> None:
    data = make_plan()
    data["days"][0]["stops"][0]["duration_min"] = MAX_DURATION_MIN
    Plan.model_validate(data)

    data["days"][0]["stops"][0]["duration_min"] = 10**20
    assert error_types(data) == {(("days", 0, "stops", 0, "duration_min"), "less_than_equal")}


@pytest.mark.parametrize(
    ("field", "value", "error"),
    [
        ("lat", 90.5, "less_than_equal"),
        ("lat", -91, "greater_than_equal"),
        ("lon", 180.1, "less_than_equal"),
        ("lon", -181, "greater_than_equal"),
    ],
)
def test_coordinates_are_in_range(field: str, value: float, error: str) -> None:
    data = make_plan()
    data["days"][0]["stops"][1][field] = value

    assert error_types(data) == {(("days", 0, "stops", 1, field), error)}


def test_a_lone_coordinate_is_allowed() -> None:
    data = make_plan()
    del data["days"][0]["stops"][1]["lon"]

    assert Plan.model_validate(data).days[0].stops[1].lon is None


def test_travelers_is_positive() -> None:
    assert error_types(make_plan(travelers=0)) == {(("travelers",), "greater_than")}


def test_days_are_capped_at_120_entries() -> None:
    start = dt.date(2026, 11, 1)
    days = [
        {"date": (start + dt.timedelta(days=offset)).isoformat(), "stops": []}
        for offset in range(MAX_TRIP_DAYS + 1)
    ]

    assert ((("days",), "too_long")) in error_types(make_plan(days=days))


# --- price ---------------------------------------------------------------------------------


def test_price_parses() -> None:
    price = Price.model_validate(PRICE)

    assert price.amount_cents == 31480
    assert price.retrieved_at.utcoffset() == dt.timedelta(hours=2)


@pytest.mark.parametrize(
    ("field", "value", "error"),
    [
        ("amount_cents", -1, "greater_than_equal"),
        ("amount_cents", MAX_AMOUNT_CENTS + 1, "less_than_equal"),
        ("amount_cents", 10**20, "less_than_equal"),
        ("amount_cents", 12.5, "int_from_float"),
        ("currency", "eur", "string_pattern_mismatch"),
        ("currency", "EURO", "string_pattern_mismatch"),
        ("status", "confirmed", "literal_error"),
        ("source_url", "expedia", "url_parsing"),
        ("source_url", "ftp://example.com/file", "url_scheme"),
        ("retrieved_at", "2026-10-12T15:04:00", "timezone_aware"),
        ("retrieved_at", "yesterday", "datetime_from_date_parsing"),
    ],
)
def test_price_rejects_bad_values(field: str, value: Any, error: str) -> None:
    data = make_plan()
    data["bookings"][0]["price"] = {**PRICE, field: value}

    assert error_types(data) == {(("bookings", 0, "price", field), error)}


@pytest.mark.parametrize("field", ["source_url", "retrieved_at", "status", "currency"])
def test_price_provenance_is_mandatory(field: str) -> None:
    price = {key: value for key, value in PRICE.items() if key != field}

    with pytest.raises(ValidationError) as caught:
        Price.model_validate(price)
    assert [(e["loc"], e["type"]) for e in caught.value.errors()] == [((field,), "missing")]


# --- instants with offset ------------------------------------------------------------------


@pytest.mark.parametrize("field", ["book_by", "scheduled_for"])
def test_booking_instants_must_carry_an_offset(field: str) -> None:
    data = make_plan()
    data["bookings"][0][field] = "2026-11-10T10:00:00"

    assert error_types(data) == {(("bookings", 0, field), "timezone_aware")}


def test_booking_instants_reject_bare_dates() -> None:
    data = make_plan()
    data["bookings"][1]["scheduled_for"] = "2026-11-14"

    assert error_types(data) == {(("bookings", 1, "scheduled_for"), "timezone_aware")}


def test_aware_datetime_objects_are_accepted_naive_ones_are_not() -> None:
    booking = PlanBooking(
        title="Cena",
        kind="restaurant",
        scheduled_for=dt.datetime(2026, 11, 14, 20, tzinfo=dt.UTC),
    )
    assert booking.scheduled_for is not None

    with pytest.raises(ValidationError, match="timezone_aware"):
        PlanBooking.model_validate(
            {"title": "Cena", "kind": "restaurant", "scheduled_for": dt.datetime(2026, 11, 14, 20)}  # noqa: DTZ001
        )


# --- book_by strictly before scheduled_for -------------------------------------------------


def test_book_by_before_scheduled_for_is_valid() -> None:
    booking = PlanBooking.model_validate(
        {
            "title": "Hotel",
            "kind": "lodging",
            "book_by": "2026-11-13T23:59:59+00:00",
            "scheduled_for": "2026-11-14T00:00:00+00:00",
        }
    )
    assert booking.book_by is not None


@pytest.mark.parametrize(
    ("book_by", "scheduled_for"),
    [
        # Equal: the spec's rule is book_by != scheduled_for.
        ("2026-11-14T07:05:00+01:00", "2026-11-14T07:05:00+01:00"),
        # The same instant written with two offsets is still equal.
        ("2026-11-14T06:05:00+00:00", "2026-11-14T07:05:00+01:00"),
        # After.
        ("2026-11-15T07:05:00+01:00", "2026-11-14T07:05:00+01:00"),
    ],
)
def test_book_by_not_strictly_before_scheduled_for_is_rejected(
    book_by: str, scheduled_for: str
) -> None:
    data = make_plan()
    data["bookings"][0].update(book_by=book_by, scheduled_for=scheduled_for)

    (error,) = errors_of(data)

    assert error["loc"] == ("bookings", 0, "book_by")
    assert error["type"] == "book_by_not_before_scheduled_for"
    assert "strictly before scheduled_for" in error["msg"]
    assert error["ctx"] == {
        "book_by": dt.datetime.fromisoformat(book_by).isoformat(),
        "scheduled_for": dt.datetime.fromisoformat(scheduled_for).isoformat(),
    }


@pytest.mark.parametrize("missing", ["book_by", "scheduled_for"])
def test_one_date_alone_is_valid(missing: str) -> None:
    data = make_plan()
    data["bookings"][0][missing] = None

    Plan.model_validate(data)


def test_the_rule_also_applies_to_alternatives() -> None:
    data = make_plan()
    data["alternatives"][0]["book_by"] = data["alternatives"][0]["scheduled_for"]

    assert error_types(data) == {
        (("alternatives", 0, "book_by"), "book_by_not_before_scheduled_for")
    }


# --- time zone -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "zone", ["Europe/Lisbon", "Europe/Rome", "UTC", "America/Argentina/Buenos_Aires"]
)
def test_iana_time_zones_are_accepted(zone: str) -> None:
    assert Plan.model_validate(make_plan(timezone=zone)).timezone == zone


@pytest.mark.parametrize(
    "zone", ["Europe", "Mars/Olympus", "", "../etc/passwd", "/etc/localtime", "GMT+1", "Lisbon"]
)
def test_unknown_time_zones_are_rejected(zone: str) -> None:
    (error,) = errors_of(make_plan(timezone=zone))

    assert error["loc"] == ("timezone",)
    assert error["type"] == "invalid_timezone"
    assert "Europe/Lisbon" in error["msg"]


def test_wrong_case_time_zone_gets_a_suggestion() -> None:
    (error,) = errors_of(make_plan(timezone="europe/lisbon"))

    assert error["type"] == "invalid_timezone"
    assert error["msg"] == (
        "'europe/lisbon' is not an IANA time zone name; did you mean 'Europe/Lisbon'?"
    )


def test_is_iana_timezone_is_case_sensitive() -> None:
    assert is_iana_timezone("Asia/Tokyo")
    assert not is_iana_timezone("asia/tokyo")
    assert not is_iana_timezone("Factory")


# --- dates and days ------------------------------------------------------------------------


def test_end_before_start_is_rejected_without_flagging_every_day() -> None:
    errors = errors_of(make_plan(start_date="2026-11-17", end_date="2026-11-14"))

    assert [(e["loc"], e["type"]) for e in errors] == [(("end_date",), "end_before_start")]
    assert errors[0]["msg"].startswith("end_date 2026-11-14 is before start_date 2026-11-17")


def test_trip_longer_than_120_days_is_rejected() -> None:
    start = dt.date(2026, 11, 1)
    end = start + dt.timedelta(days=MAX_TRIP_DAYS)

    (error,) = errors_of(make_plan(start_date=start.isoformat(), end_date=end.isoformat()))

    assert (error["loc"], error["type"]) == (("end_date",), "trip_too_long")
    assert error["ctx"]["days"] == MAX_TRIP_DAYS + 1


@pytest.mark.parametrize("date", ["2026-11-13", "2026-11-18", "2027-11-14"])
def test_days_outside_the_trip_are_rejected(date: str) -> None:
    data = make_plan()
    data["days"][1]["date"] = date

    (error,) = errors_of(data)

    assert (error["loc"], error["type"]) == (("days", 1, "date"), "day_out_of_range")
    assert error["msg"].startswith(f"day {date} is outside the trip (2026-11-14 to 2026-11-17)")


def test_days_on_the_boundaries_are_valid() -> None:
    data = make_plan()
    data["days"][1]["date"] = "2026-11-17"

    plan = Plan.model_validate(data)

    assert [day.date for day in plan.days] == [plan.start_date, plan.end_date]


def test_duplicate_days_are_rejected() -> None:
    data = make_plan()
    data["days"][1]["date"] = "2026-11-14"

    (error,) = errors_of(data)

    assert (error["loc"], error["type"]) == (("days", 1, "date"), "duplicate_day")
    assert "already appears at days[0]" in error["msg"]


def test_days_may_be_sparse_and_unordered() -> None:
    data = make_plan()
    data["days"].reverse()
    data["days"][0]["date"] = "2026-11-17"

    Plan.model_validate(data)


# --- stop refs -----------------------------------------------------------------------------


def test_duplicate_stop_refs_within_a_day_are_rejected() -> None:
    data = make_plan()
    data["days"][1]["stops"][1]["ref"] = "d2-jeronimos"

    (error,) = errors_of(data)

    assert (error["loc"], error["type"]) == (("days", 1, "stops", 1, "ref"), "duplicate_stop_ref")
    assert "already used by days[1].stops[0]" in error["msg"]


def test_duplicate_stop_refs_across_days_are_rejected() -> None:
    data = make_plan()
    data["days"][1]["stops"][1]["ref"] = "d1-dinner"

    assert error_types(data) == {(("days", 1, "stops", 1, "ref"), "duplicate_stop_ref")}


@pytest.mark.parametrize("field", ["bookings", "alternatives"])
def test_stop_ref_must_point_at_an_existing_stop(field: str) -> None:
    data = make_plan()
    data[field][0]["stop_ref"] = "d9-nowhere"

    (error,) = errors_of(data)

    assert (error["loc"], error["type"]) == ((field, 0, "stop_ref"), "unknown_stop_ref")
    assert "d9-nowhere" in error["msg"]
    assert "d1-dinner, d1-flight, d2-jeronimos, d2-rest" in error["msg"]


def test_stop_ref_is_optional() -> None:
    data = make_plan()
    for booking in data["bookings"]:
        booking["stop_ref"] = None

    Plan.model_validate(data)


# --- reporting -----------------------------------------------------------------------------


def test_every_consistency_problem_is_reported_at_once() -> None:
    data = make_plan()
    data["days"][1]["date"] = "2026-11-20"
    data["days"][1]["stops"][0]["ref"] = "d1-flight"
    data["bookings"][1]["stop_ref"] = "missing"
    data["alternatives"][0]["stop_ref"] = "also-missing"

    assert error_types(data) == {
        (("days", 1, "date"), "day_out_of_range"),
        (("days", 1, "stops", 0, "ref"), "duplicate_stop_ref"),
        (("bookings", 1, "stop_ref"), "unknown_stop_ref"),
        (("alternatives", 0, "stop_ref"), "unknown_stop_ref"),
    }


def test_errors_serialize_to_json() -> None:
    data = make_plan(start_date="2026-11-17", end_date="2026-11-14")
    data["bookings"][0]["book_by"] = data["bookings"][0]["scheduled_for"]

    with pytest.raises(ValidationError) as caught:
        Plan.model_validate(data)

    errors = json.loads(caught.value.json())
    assert {error["type"] for error in errors} == {"book_by_not_before_scheduled_for"}


@pytest.mark.parametrize(
    ("loc", "expected"),
    [
        ((), "(plan)"),
        (("title",), "title"),
        (("days", 2, "stops", 0, "start_time"), "days[2].stops[0].start_time"),
        (("bookings", 1), "bookings[1]"),
    ],
)
def test_format_location(loc: tuple[str | int, ...], expected: str) -> None:
    assert format_location(loc) == expected


def test_rejection_message_lists_every_error_with_its_path() -> None:
    data = make_plan(timezone="Lisbon")
    data["days"][0]["stops"][0]["start_time"] = "7:05"
    del data["days"][0]["stops"][1]["kind"]

    with pytest.raises(ValidationError) as caught:
        Plan.model_validate(data)
    message = plan_rejection_message(caught.value)

    lines = message.splitlines()
    assert lines[0].startswith("Plan rejected: 3 validation errors. Fix every one")
    assert "call submit_plan again" in lines[0]
    assert lines[1:] == [
        "- timezone: 'Lisbon' is not an IANA time zone name; use the destination's zone, "
        "e.g. 'Europe/Lisbon' or 'America/New_York' (got \"Lisbon\")",
        "- days[0].stops[0].start_time: String should match pattern "
        "'^([01]\\d|2[0-3]):[0-5]\\d$' (got \"7:05\")",
        "- days[0].stops[1].kind: Field required",
    ]


def test_rejection_message_for_a_cross_field_error() -> None:
    data = make_plan()
    data["bookings"][0]["book_by"] = data["bookings"][0]["scheduled_for"]

    with pytest.raises(ValidationError) as caught:
        Plan.model_validate(data)
    message = plan_rejection_message(caught.value)

    assert message.startswith("Plan rejected: 1 validation error. ")
    assert "- bookings[0].book_by: book_by (2026-11-14T07:05:00+01:00) must be strictly " in message
    assert message.endswith("(got 2026-11-14T07:05:00+01:00)")


def test_rejection_message_explains_how_to_fix_common_mistakes() -> None:
    data = make_plan(budget_eur=900)
    data["bookings"][0]["book_by"] = "2026-11-07T18:00:00"

    with pytest.raises(ValidationError) as caught:
        Plan.model_validate(data)

    assert describe_validation_errors(caught.value) == [
        "bookings[0].book_by: Input should have timezone info; add the UTC offset of the local "
        'time, e.g. 2026-11-14T07:05:00+01:00 (got "2026-11-07T18:00:00")',
        "budget_eur: Extra inputs are not permitted; remove this key: it is not part of the "
        "schema (got 900)",
    ]


def test_long_inputs_are_shortened_in_the_message() -> None:
    with pytest.raises(ValidationError) as caught:
        Plan.model_validate(make_plan(title="t" * 130))

    (line,) = describe_validation_errors(caught.value)

    assert line.endswith('(got 130 characters: "' + "t" * 50 + '…")')


def test_object_inputs_are_not_echoed() -> None:
    data = make_plan()
    data["bookings"][0]["price"] = "about 300 euro"
    data["days"][0]["stops"] = {"ref": "x"}

    with pytest.raises(ValidationError) as caught:
        Plan.model_validate(data)

    lines = describe_validation_errors(caught.value)
    assert any(line.startswith("days[0].stops: Input should be a valid list") for line in lines)
    assert not any("{'ref'" in line for line in lines)


def test_description_is_capped() -> None:
    data = make_plan()
    data["days"] = [copy.deepcopy(data["days"][0]) for _ in range(3)]
    for index, day in enumerate(data["days"]):
        for stop in day["stops"]:
            stop["start_time"] = "late"
            stop["ref"] = f"{stop['ref']}-{index}"

    with pytest.raises(ValidationError) as caught:
        Plan.model_validate(data)

    lines = describe_validation_errors(caught.value, limit=4)
    assert len(lines) == 5
    assert lines[-1] == f"... and {caught.value.error_count() - 4} more errors"


def test_problems_collects_without_raising_until_asked() -> None:
    problems = Problems("Example")
    assert not problems
    problems.raise_if_any()

    problems.add(("a",), "first", "first {n}", 1, n=dt.date(2026, 1, 2))
    problems.add(("b", 0), "second", "second", None)
    assert problems

    with pytest.raises(ValidationError) as caught:
        problems.raise_if_any()
    assert [(e["loc"], e["type"], e["msg"]) for e in caught.value.errors()] == [
        (("a",), "first", "first 2026-01-02"),
        (("b", 0), "second", "second"),
    ]
