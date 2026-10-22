"""Subagent result files (app/results.py): the shared envelope, each option type, parse_result."""

from __future__ import annotations

import datetime as dt
import json
from typing import Any

import pytest
from pydantic import ValidationError

from app.events import AgentName
from app.plan import MAX_DURATION_MIN
from app.results import (
    RESULT_MODELS,
    SUBAGENTS,
    ActivitiesResult,
    ActivityOption,
    FlightOption,
    FlightSegment,
    FlightsResult,
    LodgingOption,
    LodgingResult,
    TransferOption,
    TransportResult,
    parse_result,
    result_path,
)

PRICE: dict[str, Any] = {
    "amount_cents": 31480,
    "currency": "EUR",
    "status": "verified",
    "source_url": "https://www.expedia.it/Flights-Search",
    "retrieved_at": "2026-10-12T15:04:00+02:00",
}
ESTIMATED = {**PRICE, "status": "estimated", "source_url": "https://www.example.com/prices"}


def segment(**overrides: Any) -> dict[str, Any]:
    return {
        "from_airport": "MXP",
        "to_airport": "LIS",
        "depart_at": "2026-11-14T07:05:00+01:00",
        "arrive_at": "2026-11-14T08:55:00+00:00",
        "carrier": "TAP Air Portugal",
        "flight_number": "TP827",
        **overrides,
    }


def flight(**overrides: Any) -> dict[str, Any]:
    return {
        "id": "f1",
        "segments": [
            segment(),
            segment(
                from_airport="LIS",
                to_airport="MXP",
                depart_at="2026-11-17T19:30:00+00:00",
                arrive_at="2026-11-17T23:15:00+01:00",
                flight_number="TP828",
            ),
        ],
        "stops": 0,
        "baggage_included": True,
        "price": PRICE,
        "link": "https://www.expedia.it/Flights-Search?leg1=MXP-LIS",
        "source": "expedia",
        **overrides,
    }


def lodging(**overrides: Any) -> dict[str, Any]:
    return {
        "id": "h1",
        "name": "Hotel Lisboa Plaza",
        "kind": "hotel",
        "address": "Travessa do Salitre 7, 1269-066 Lisboa",
        "lat": 38.7202,
        "lon": -9.1453,
        "check_in": "2026-11-14",
        "check_out": "2026-11-17",
        "free_cancellation_until": "2026-11-12T23:59:00+00:00",
        "price": {**PRICE, "amount_cents": 54000},
        "link": "https://www.expedia.it/Lisbon-Hotels-Lisboa-Plaza.h1.Hotel-Information",
        "source": "expedia",
        **overrides,
    }


def activity(**overrides: Any) -> dict[str, Any]:
    return {
        "id": "a1",
        "title": "Mosteiro dos Jerónimos",
        "suggested_day": "2026-11-15",
        "start_time": "10:00",
        "duration_min": 120,
        "location_name": "Mosteiro dos Jerónimos",
        "lat": 38.6979,
        "lon": -9.2068,
        "booking_required": True,
        "book_by": "2026-11-13T18:00:00+00:00",
        "price": ESTIMATED,
        "link": None,
        **overrides,
    }


def transfer(**overrides: Any) -> dict[str, Any]:
    return {
        "id": "t1",
        "from": "Aeroporto di Lisbona (LIS)",
        "to": "Hotel Lisboa Plaza",
        "mode": "metro",
        "depart_at": "2026-11-14T09:30:00+00:00",
        "arrive_at": "2026-11-14T10:05:00+00:00",
        "duration_min": 35,
        "price": {**ESTIMATED, "amount_cents": 360},
        "link": None,
        **overrides,
    }


# A car_rental drive as a file written before `distance_km` existed has it: no such key.
OLD_RENTAL: dict[str, Any] = {
    "id": "t3",
    "from": "Milano",
    "to": "Genova Porto",
    "mode": "car_rental",
    "depart_at": None,
    "arrive_at": None,
    "duration_min": 110,
    "price": ESTIMATED,
    "link": None,
}


OPTION_BUILDERS = {
    "flights": flight,
    "lodging": lodging,
    "activities": activity,
    "transport": transfer,
}


def envelope(agent: str, *options: dict[str, Any], **overrides: Any) -> dict[str, Any]:
    return {
        "agent": agent,
        "version": 1,
        "updated_at": "2026-10-12T15:10:00+02:00",
        "options": list(options) or [OPTION_BUILDERS[agent]()],
        "failures": [
            {
                "source": "kiwi",
                "reason": "timeout after 30 s",
                "at": "2026-10-12T15:06:00+02:00",
            }
        ],
        "warnings": ["Prezzi del transfer solo stimati."],
        **overrides,
    }


def error_types(agent: str, data: dict[str, Any]) -> set[tuple[tuple[str | int, ...], str]]:
    with pytest.raises(ValidationError) as caught:
        parse_result(agent, data)
    return {(tuple(e["loc"]), e["type"]) for e in caught.value.errors()}


def option_error_types(agent: str, option: dict[str, Any]) -> set[tuple[Any, ...]]:
    """Errors of a single option, with the ("options", 0) prefix removed."""
    return {(loc[2:], kind) for loc, kind in error_types(agent, envelope(agent, option))}


# --- parse_result and the envelope ---------------------------------------------------------


@pytest.mark.parametrize(
    ("agent", "model"),
    [
        ("flights", FlightsResult),
        ("lodging", LodgingResult),
        ("activities", ActivitiesResult),
        ("transport", TransportResult),
    ],
)
def test_parse_result_returns_the_agents_envelope(agent: str, model: type[Any]) -> None:
    result = parse_result(agent, envelope(agent))

    assert type(result) is model
    assert result.agent == agent
    assert result.version == 1
    assert result.updated_at.utcoffset() == dt.timedelta(hours=2)
    assert len(result.options) == 1
    assert result.failures[0].source == "kiwi"
    assert result.warnings == ["Prezzi del transfer solo stimati."]


@pytest.mark.parametrize("agent", SUBAGENTS)
def test_parse_result_accepts_raw_json(agent: str) -> None:
    text = json.dumps(envelope(agent))

    assert parse_result(agent, text) == parse_result(agent, text.encode())
    assert parse_result(agent, text) == parse_result(agent, json.loads(text))


@pytest.mark.parametrize("agent", SUBAGENTS)
def test_json_round_trip_is_lossless(agent: str) -> None:
    result = parse_result(agent, envelope(agent))

    assert parse_result(agent, result.model_dump_json()) == result
    assert parse_result(agent, result.model_dump(mode="json")) == result


def test_parse_result_is_typed_per_agent() -> None:
    flights = parse_result("flights", envelope("flights"))
    transport = parse_result("transport", envelope("transport"))

    # Attribute access type-checks only with the per-agent overloads.
    assert flights.options[0].segments[0].from_airport == "MXP"
    assert transport.options[0].from_ == "Aeroporto di Lisbona (LIS)"


def test_parse_result_rejects_an_unknown_agent() -> None:
    with pytest.raises(ValueError, match="unknown subagent 'coordinator'"):
        parse_result("coordinator", envelope("flights"))


def test_a_file_written_by_another_agent_is_rejected() -> None:
    data = envelope("lodging")
    data["options"] = [flight()]

    assert ((("agent",), "literal_error")) in error_types("flights", data)


def test_failures_and_warnings_default_to_empty() -> None:
    data = envelope("flights")
    del data["failures"], data["warnings"]

    result = parse_result("flights", data)

    assert result.failures == []
    assert result.warnings == []


def test_options_may_be_empty() -> None:
    data = envelope("lodging")
    data["options"] = []

    assert parse_result("lodging", data).options == []


@pytest.mark.parametrize(("version", "error"), [(0, "greater_than_equal"), ("v1", "int_parsing")])
def test_version_starts_at_one(version: Any, error: str) -> None:
    assert error_types("flights", envelope("flights", version=version)) == {(("version",), error)}


def test_updated_at_needs_an_offset() -> None:
    data = envelope("flights", updated_at="2026-10-12T15:10:00")

    assert error_types("flights", data) == {(("updated_at",), "timezone_aware")}


def test_failure_entries_are_validated() -> None:
    data = envelope("flights")
    data["failures"] = [
        {"source": "", "reason": "down", "at": "2026-10-12T15:06:00+02:00"},
        {"source": "kiwi", "reason": "down", "at": "2026-10-12T15:06:00"},
        {"source": "kiwi"},
    ]

    assert error_types("flights", data) == {
        (("failures", 0, "source"), "string_too_short"),
        (("failures", 1, "at"), "timezone_aware"),
        (("failures", 2, "reason"), "missing"),
        (("failures", 2, "at"), "missing"),
    }


def test_option_ids_are_unique_within_a_file() -> None:
    data = envelope("activities", activity(), activity(id="a2"), activity())

    with pytest.raises(ValidationError) as caught:
        parse_result("activities", data)

    (error,) = caught.value.errors()
    assert (error["loc"], error["type"]) == (("options", 2, "id"), "duplicate_option_id")
    assert error["msg"] == "id 'a1' is already used by options[0]"


def test_unknown_keys_are_rejected() -> None:
    data = envelope("flights", flight(airline="TAP"), notes="x")

    assert error_types("flights", data) == {
        (("notes",), "extra_forbidden"),
        (("options", 0, "airline"), "extra_forbidden"),
    }


def test_registry_covers_every_subagent() -> None:
    assert set(RESULT_MODELS) == set(SUBAGENTS)
    assert {*SUBAGENTS, "coordinator"} == {name.value for name in AgentName}
    for agent, model in RESULT_MODELS.items():
        assert model.model_json_schema()["properties"]["agent"]["const"] == agent


def test_result_path() -> None:
    assert result_path("transport") == "/workspace/results/transport.json"


# --- flights -------------------------------------------------------------------------------


def test_flight_option_parses() -> None:
    option = FlightOption.model_validate(flight())

    assert [s.flight_number for s in option.segments] == ["TP827", "TP828"]
    assert option.segments[0].arrive_at.utcoffset() == dt.timedelta(0)
    assert option.price.status == "verified"


@pytest.mark.parametrize("number", ["TP827", "U2 3841", "9W123", "FR1234A", "AZ7", "EZY4321"])
def test_flight_numbers(number: str) -> None:
    FlightSegment.model_validate(segment(flight_number=number))


@pytest.mark.parametrize("number", ["827", "12 345", "TP", "tp827", "TP 12345", ""])
def test_bad_flight_numbers(number: str) -> None:
    assert option_error_types("flights", flight(segments=[segment(flight_number=number)])) == {
        (("segments", 0, "flight_number"), "string_pattern_mismatch")
    }


@pytest.mark.parametrize("code", ["mxp", "MXPA", "MX", "M1P"])
def test_airports_are_iata_codes(code: str) -> None:
    assert option_error_types("flights", flight(segments=[segment(from_airport=code)])) == {
        (("segments", 0, "from_airport"), "string_pattern_mismatch")
    }


def test_a_leg_goes_somewhere() -> None:
    assert option_error_types("flights", flight(segments=[segment(to_airport="MXP")])) == {
        (("segments", 0, "to_airport"), "same_airport")
    }


@pytest.mark.parametrize(
    "arrive_at",
    [
        "2026-11-14T07:05:00+01:00",  # same instant as departure
        "2026-11-14T06:00:00+00:00",  # earlier than departure (06:05 UTC)
    ],
)
def test_a_leg_lands_after_it_takes_off(arrive_at: str) -> None:
    assert option_error_types("flights", flight(segments=[segment(arrive_at=arrive_at)])) == {
        (("segments", 0, "arrive_at"), "times_out_of_order")
    }


def test_leg_times_need_offsets() -> None:
    assert option_error_types(
        "flights", flight(segments=[segment(depart_at="2026-11-14T07:05:00")])
    ) == {(("segments", 0, "depart_at"), "timezone_aware")}


def test_legs_are_in_travel_order() -> None:
    data = flight()
    data["segments"].reverse()

    assert option_error_types("flights", data) == {
        (("segments", 1, "depart_at"), "times_out_of_order")
    }


def test_a_connection_departing_when_the_first_leg_lands_is_rejected() -> None:
    first = segment(to_airport="OPO", arrive_at="2026-11-14T08:30:00+00:00")
    second = segment(
        from_airport="OPO",
        depart_at="2026-11-14T08:30:00+00:00",
        arrive_at="2026-11-14T09:30:00+00:00",
        flight_number="TP1941",
    )

    assert option_error_types("flights", flight(segments=[first, second], stops=1)) == {
        (("segments", 1, "depart_at"), "times_out_of_order")
    }


def test_a_flight_has_at_least_one_leg() -> None:
    assert option_error_types("flights", flight(segments=[])) == {(("segments",), "too_short")}


def test_stops_cannot_be_negative() -> None:
    assert option_error_types("flights", flight(stops=-1)) == {(("stops",), "greater_than_equal")}


def test_flight_sources_are_a_closed_set() -> None:
    assert option_error_types("flights", flight(source="skyscanner")) == {
        (("source",), "literal_error")
    }


@pytest.mark.parametrize("source", ["expedia", "kiwi", "lastminute"])
def test_mcp_prices_may_be_verified_or_estimated(source: str) -> None:
    FlightOption.model_validate(flight(source=source))
    FlightOption.model_validate(flight(source=source, price=ESTIMATED))


def test_web_prices_are_never_verified() -> None:
    assert option_error_types("flights", flight(source="web")) == {
        (("price", "status"), "price_not_verifiable")
    }
    FlightOption.model_validate(flight(source="web", price=ESTIMATED))


def test_a_flight_needs_a_price_with_provenance() -> None:
    price = {key: value for key, value in PRICE.items() if key != "source_url"}

    assert option_error_types("flights", flight(price=price)) == {
        (("price", "source_url"), "missing")
    }


# --- lodging -------------------------------------------------------------------------------


def test_lodging_option_parses() -> None:
    option = LodgingOption.model_validate(lodging())

    assert option.check_in == dt.date(2026, 11, 14)
    assert option.free_cancellation_until is not None


def test_lodging_minimal_fields() -> None:
    data = lodging(lat=None, lon=None, free_cancellation_until=None, link=None)

    assert LodgingOption.model_validate(data).lat is None


@pytest.mark.parametrize("check_out", ["2026-11-14", "2026-11-13"])
def test_check_out_is_after_check_in(check_out: str) -> None:
    assert option_error_types("lodging", lodging(check_out=check_out)) == {
        (("check_out",), "check_out_not_after_check_in")
    }


@pytest.mark.parametrize(("missing", "reported"), [("lat", "lat"), ("lon", "lon")])
def test_lodging_coordinates_come_in_pairs(missing: str, reported: str) -> None:
    assert option_error_types("lodging", lodging(**{missing: None})) == {
        ((reported,), "coordinates_incomplete")
    }


def test_lodging_sources() -> None:
    assert option_error_types("lodging", lodging(source="kiwi")) == {(("source",), "literal_error")}
    assert option_error_types("lodging", lodging(source="web")) == {
        (("price", "status"), "price_not_verifiable")
    }


def test_lodging_kinds_are_a_closed_set() -> None:
    assert option_error_types("lodging", lodging(kind="castle")) == {(("kind",), "literal_error")}


def test_lodging_address_is_required() -> None:
    assert option_error_types("lodging", lodging(address="")) == {
        (("address",), "string_too_short")
    }


def test_free_cancellation_needs_an_offset() -> None:
    assert option_error_types(
        "lodging", lodging(free_cancellation_until="2026-11-12T23:59:00")
    ) == {(("free_cancellation_until",), "timezone_aware")}


# --- activities ----------------------------------------------------------------------------


def test_activity_option_parses() -> None:
    option = ActivityOption.model_validate(activity())

    assert option.suggested_day == dt.date(2026, 11, 15)
    assert option.price is not None
    assert option.price.status == "estimated"


def test_activity_minimal_fields() -> None:
    option = ActivityOption.model_validate(
        {"id": "a9", "title": "Passeggiata a Belém", "booking_required": False}
    )

    assert option.price is None
    assert option.suggested_day is None


def test_activity_coordinates_come_in_pairs() -> None:
    assert option_error_types("activities", activity(lon=None)) == {
        (("lon",), "coordinates_incomplete")
    }


def test_activity_fields_are_checked() -> None:
    data = activity(start_time="10", duration_min=0, book_by="2026-11-13", title="t" * 121)

    assert option_error_types("activities", data) == {
        (("title",), "string_too_long"),
        (("start_time",), "string_pattern_mismatch"),
        (("duration_min",), "greater_than"),
        (("book_by",), "timezone_aware"),
    }


# --- transport -----------------------------------------------------------------------------


def test_transfer_uses_from_and_to_in_json() -> None:
    option = TransferOption.model_validate(transfer())

    assert option.from_ == "Aeroporto di Lisbona (LIS)"
    assert option.to == "Hotel Lisboa Plaza"
    dumped = option.model_dump(mode="json")
    assert dumped["from"] == "Aeroporto di Lisbona (LIS)"
    assert "from_" not in dumped
    assert json.loads(option.model_dump_json())["from"] == option.from_


def test_transfer_can_be_built_in_python() -> None:
    option = TransferOption(id="t2", from_="Hotel", to="Alfama", mode="walk", duration_min=20)

    assert option.depart_at is None
    assert TransferOption.model_validate(option.model_dump()) == option


def test_transfer_needs_from() -> None:
    data = transfer()
    del data["from"]

    assert option_error_types("transport", data) == {(("from",), "missing")}


def test_on_demand_transfers_have_no_schedule() -> None:
    option = TransferOption.model_validate(
        transfer(mode="taxi", depart_at=None, arrive_at=None, price=None)
    )

    assert option.price is None


@pytest.mark.parametrize("arrive_at", ["2026-11-14T09:30:00+00:00", "2026-11-14T09:00:00+00:00"])
def test_transfer_arrives_after_it_departs(arrive_at: str) -> None:
    assert option_error_types("transport", transfer(arrive_at=arrive_at)) == {
        (("arrive_at",), "times_out_of_order")
    }


def test_transfer_fields_are_checked() -> None:
    data = transfer(mode="hoverboard", duration_min=None, depart_at="2026-11-14T09:30:00")

    assert option_error_types("transport", data) == {
        (("mode",), "literal_error"),
        (("duration_min",), "int_type"),
        (("depart_at",), "timezone_aware"),
    }


def test_transfer_option_accepts_own_car_with_distance() -> None:
    option = TransferOption.model_validate({**OLD_RENTAL, "mode": "car", "distance_km": 160})

    assert (option.mode, option.distance_km) == ("car", 160)


@pytest.mark.parametrize("distance", [0, -5, 20_001])
def test_transfer_option_rejects_a_distance_out_of_range(distance: int) -> None:
    assert option_error_types("transport", {**OLD_RENTAL, "distance_km": distance}) == {
        (("distance_km",), "greater_than_equal" if distance < 1 else "less_than_equal")
    }


def test_transfer_option_without_distance_still_validates() -> None:
    # a transport option written before this PR: no distance_km key, mode car_rental
    assert TransferOption.model_validate(OLD_RENTAL).distance_km is None


# --- rules shared by every option ----------------------------------------------------------


@pytest.mark.parametrize(
    ("agent", "option"),
    [("activities", activity()), ("transport", transfer())],
)
def test_agents_without_an_mcp_never_have_verified_prices(
    agent: str, option: dict[str, Any]
) -> None:
    data = {**option, "price": PRICE}

    assert option_error_types(agent, data) == {(("price", "status"), "price_not_verifiable")}


@pytest.mark.parametrize(
    ("agent", "option"), [("activities", activity()), ("transport", transfer())]
)
def test_durations_are_capped_at_a_week(agent: str, option: dict[str, Any]) -> None:
    parse_result(agent, envelope(agent, {**option, "duration_min": MAX_DURATION_MIN}))

    assert option_error_types(agent, {**option, "duration_min": 10**20}) == {
        (("duration_min",), "less_than_equal")
    }


def test_control_characters_are_rejected_in_results() -> None:
    raw = json.dumps(envelope("flights", warnings=["ok", "fonte\u0000 caduta"]))

    with pytest.raises(ValidationError) as caught:
        parse_result("flights", raw)
    assert [(e["loc"], e["type"]) for e in caught.value.errors()] == [
        (("warnings",), "control_character")
    ]


def test_control_characters_are_rejected_in_options() -> None:
    assert option_error_types("lodging", lodging(name="Hotel\x00Plaza")) == {
        (("name",), "control_character")
    }
