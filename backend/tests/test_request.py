"""Trip request (app/request.py): POST /plans body rules, with "today" frozen in Europe/Rome."""

from __future__ import annotations

import datetime as dt
import json
from collections.abc import Iterator
from typing import Any

import pytest
import time_machine
from pydantic import ValidationError

from app import clock
from app.request import (
    ALLOW_PAST_DATES,
    MAX_NIGHTS,
    REQUEST_ERRORS,
    DateWindow,
    PlanRequest,
    RequestErrorCode,
    Traveler,
)

ROME = clock.HOME_TIMEZONE
TODAY = dt.date(2026, 10, 12)


@pytest.fixture(autouse=True)
def frozen_today() -> Iterator[None]:
    """Noon in Rome on 2026-10-12; tests that need another instant travel again inside."""
    with time_machine.travel(dt.datetime(2026, 10, 12, 12, 0, tzinfo=ROME), tick=False):
        yield


def make_request(**overrides: Any) -> dict[str, Any]:
    request: dict[str, Any] = {
        "origin": "Milano",
        "destination": "Lisbona",
        "dates": {"exact_start": "2026-11-14", "exact_end": "2026-11-17"},
        "travelers": [{"kind": "adult"}, {"kind": "adult"}, {"kind": "child", "age": 7}],
        "budget_eur": 1500,
        "preferences": "Niente voli prima delle 8, cucina locale.",
    }
    request.update(overrides)
    return request


def flexible(month: str = "2026-11", nights: int = 4) -> dict[str, Any]:
    return {"month": month, "nights": nights}


def errors_of(data: dict[str, Any], **kwargs: Any) -> list[dict[str, Any]]:
    with pytest.raises(ValidationError) as caught:
        PlanRequest.model_validate(data, **kwargs)
    return [dict(error) for error in caught.value.errors(include_url=False)]


def error_types(data: dict[str, Any]) -> set[tuple[tuple[str | int, ...], str]]:
    return {(tuple(error["loc"]), error["type"]) for error in errors_of(data)}


# --- clock ---------------------------------------------------------------------------------


def test_clock_is_in_rome_and_follows_time_machine() -> None:
    assert clock.today() == TODAY
    assert clock.current_month() == "2026-10"
    now = clock.now()
    assert now.tzinfo is ROME
    assert now == dt.datetime(2026, 10, 12, 12, 0, tzinfo=ROME)


def test_clock_uses_the_rome_date_not_the_utc_date() -> None:
    with time_machine.travel(dt.datetime(2026, 10, 31, 23, 30, tzinfo=dt.UTC), tick=False):
        assert clock.today() == dt.date(2026, 11, 1)
        assert clock.current_month() == "2026-11"


# --- happy paths ---------------------------------------------------------------------------


def test_exact_dates_request_is_valid() -> None:
    request = PlanRequest.model_validate(make_request())

    assert request.dates.is_exact
    assert request.dates.exact_start == dt.date(2026, 11, 14)
    assert request.adults == 2
    assert request.child_ages == [7]
    assert request.suggest_destination is False


def test_flexible_dates_request_is_valid() -> None:
    request = PlanRequest.model_validate(make_request(dates=flexible("2027-01", 7)))

    assert not request.dates.is_exact
    assert (request.dates.month, request.dates.nights) == ("2027-01", 7)


def test_suggest_destination_request_is_valid() -> None:
    request = PlanRequest.model_validate(
        make_request(
            destination=None,
            suggest_destination=True,
            destination_idea="mare a novembre, volo diretto",
        )
    )

    assert request.destination is None
    assert request.destination_idea == "mare a novembre, volo diretto"


def test_minimal_request_uses_defaults() -> None:
    request = PlanRequest.model_validate(
        {
            "origin": "MXP",
            "destination": "Porto",
            "dates": flexible(),
            "travelers": [{"kind": "adult"}],
            "budget_eur": 400,
        }
    )

    assert request.preferences is None
    assert request.destination_idea is None
    assert request.child_ages == []


def test_text_is_stripped_and_blank_optionals_become_none() -> None:
    request = PlanRequest.model_validate(
        make_request(
            origin="  Milano  ",
            destination="   ",
            suggest_destination=True,
            destination_idea="",
            preferences=" \n ",
        )
    )

    assert request.origin == "Milano"
    assert request.destination is None
    assert request.destination_idea is None
    assert request.preferences is None


def test_json_round_trip_is_lossless() -> None:
    request = PlanRequest.model_validate(make_request())

    assert PlanRequest.model_validate_json(request.model_dump_json()) == request
    assert request.model_dump(mode="json")["dates"] == {
        "exact_start": "2026-11-14",
        "exact_end": "2026-11-17",
        "month": None,
        "nights": None,
    }


# --- field constraints ---------------------------------------------------------------------


@pytest.mark.parametrize(
    ("field", "limit"),
    [("origin", 200), ("destination", 200), ("destination_idea", 500), ("preferences", 2000)],
)
def test_text_caps(field: str, limit: int) -> None:
    extra = (
        {"suggest_destination": True, "destination": None} if field == "destination_idea" else {}
    )
    PlanRequest.model_validate(make_request(**{**extra, field: "x" * limit}))

    assert error_types(make_request(**{**extra, field: "x" * (limit + 1)})) == {
        ((field,), "string_too_long")
    }


def test_origin_is_required_and_not_blank() -> None:
    data = make_request()
    del data["origin"]
    assert error_types(data) == {(("origin",), "missing")}
    assert error_types(make_request(origin="  ")) == {(("origin",), "string_too_short")}


@pytest.mark.parametrize("budget", [0, -100])
def test_budget_is_positive(budget: int) -> None:
    assert error_types(make_request(budget_eur=budget)) == {(("budget_eur",), "greater_than")}


def test_travelers_between_one_and_nine() -> None:
    assert error_types(make_request(travelers=[])) == {(("travelers",), "too_short")}
    assert error_types(make_request(travelers=[{"kind": "adult"}] * 10)) == {
        (("travelers",), "too_long")
    }
    PlanRequest.model_validate(make_request(travelers=[{"kind": "adult"}] * 9))


def test_unknown_fields_are_rejected() -> None:
    data = make_request(currency="EUR")
    data["dates"]["flexible"] = True

    assert error_types(data) == {
        (("currency",), "extra_forbidden"),
        (("dates", "flexible"), "extra_forbidden"),
    }


# --- destination ---------------------------------------------------------------------------


def test_destination_or_suggestion_is_required() -> None:
    (error,) = errors_of(make_request(destination=None))

    assert (error["loc"], error["type"]) == (("destination",), "destination_required")
    assert error["msg"] == REQUEST_ERRORS[RequestErrorCode.DESTINATION_REQUIRED]


def test_blank_destination_counts_as_missing() -> None:
    assert error_types(make_request(destination="  ")) == {
        (("destination",), "destination_required")
    }


def test_destination_and_suggestion_together_are_rejected() -> None:
    assert error_types(make_request(suggest_destination=True)) == {
        (("destination",), "destination_conflict")
    }


def test_destination_idea_without_the_suggestion_is_dropped() -> None:
    request = PlanRequest.model_validate(make_request(destination_idea="mare"))

    assert request.destination == "Lisbona"
    assert request.destination_idea is None
    assert "destination_idea" not in request.model_dump(mode="json", exclude_none=True)


# --- travelers -----------------------------------------------------------------------------


def test_children_need_an_age() -> None:
    data = make_request(travelers=[{"kind": "adult"}, {"kind": "child"}])

    (error,) = errors_of(data)

    assert (error["loc"], error["type"]) == (("travelers", 1, "age"), "child_age_required")


@pytest.mark.parametrize("age", [0, 17])
def test_child_age_bounds_are_inclusive(age: int) -> None:
    assert Traveler.model_validate({"kind": "child", "age": age}).age == age


@pytest.mark.parametrize(("age", "error"), [(18, "less_than_equal"), (-1, "greater_than_equal")])
def test_child_age_out_of_range(age: int, error: str) -> None:
    data = make_request(travelers=[{"kind": "adult"}, {"kind": "child", "age": age}])

    assert error_types(data) == {(("travelers", 1, "age"), error)}


@pytest.mark.parametrize("age", [0, 12, 35])
def test_adults_must_not_have_an_age(age: int) -> None:
    data = make_request(travelers=[{"kind": "adult", "age": age}])

    (error,) = errors_of(data)

    assert (error["loc"], error["type"]) == (("travelers", 0, "age"), "adult_age_not_allowed")
    assert error["msg"] == "age is only for children; leave it empty for adults"


@pytest.mark.parametrize("age", [None, ""])
def test_adult_with_empty_age_is_valid(age: Any) -> None:
    assert Traveler.model_validate({"kind": "adult", "age": age}).age is None


def test_traveler_kind_is_a_closed_set() -> None:
    assert error_types(make_request(travelers=[{"kind": "infant", "age": 1}])) == {
        (("travelers", 0, "kind"), "literal_error")
    }


def test_at_least_one_adult_travels() -> None:
    data = make_request(travelers=[{"kind": "child", "age": 15}])

    assert error_types(data) == {(("travelers",), "adult_required")}


def test_traveler_instances_are_accepted() -> None:
    request = PlanRequest.model_validate(
        make_request(travelers=[Traveler(kind="adult"), Traveler(kind="child", age=3)])
    )

    assert request.child_ages == [3]


# --- dates: shape --------------------------------------------------------------------------


def test_dates_are_required() -> None:
    assert error_types(make_request(dates={})) == {(("dates",), "dates_required")}


def test_fixed_and_flexible_dates_together_are_rejected() -> None:
    dates = {"exact_start": "2026-11-14", "exact_end": "2026-11-17", **flexible()}

    assert error_types(make_request(dates=dates)) == {(("dates",), "dates_conflict")}


def test_partial_fixed_and_flexible_dates_together_are_rejected() -> None:
    assert error_types(make_request(dates={"exact_start": "2026-11-14", "nights": 3})) == {
        (("dates",), "dates_conflict")
    }


def test_exact_start_needs_exact_end() -> None:
    assert error_types(make_request(dates={"exact_start": "2026-11-14"})) == {
        (("dates", "exact_end"), "exact_end_required")
    }


def test_exact_end_needs_exact_start() -> None:
    assert error_types(make_request(dates={"exact_end": "2026-11-14"})) == {
        (("dates", "exact_start"), "exact_start_required")
    }


@pytest.mark.parametrize("end", ["2026-11-13", "2026-11-10"])
def test_exact_end_must_not_be_before_exact_start(end: str) -> None:
    (error,) = errors_of(make_request(dates={"exact_start": "2026-11-14", "exact_end": end}))

    assert (error["loc"], error["type"]) == (("dates", "exact_end"), "end_before_start")
    assert error["msg"] == f"exact_end ({end}) must be on or after exact_start (2026-11-14)"


def test_a_day_trip_has_the_same_start_and_end() -> None:
    request = PlanRequest.model_validate(
        make_request(dates={"exact_start": "2026-11-14", "exact_end": "2026-11-14"})
    )

    assert request.dates.exact_start == request.dates.exact_end == dt.date(2026, 11, 14)


def test_one_night_is_enough() -> None:
    PlanRequest.model_validate(
        make_request(dates={"exact_start": "2026-11-14", "exact_end": "2026-11-15"})
    )


def test_fixed_trip_is_capped_at_120_days() -> None:
    start = dt.date(2026, 11, 1)
    longest = {
        "exact_start": start.isoformat(),
        "exact_end": (start + dt.timedelta(days=MAX_NIGHTS)).isoformat(),
    }
    too_long = {**longest, "exact_end": (start + dt.timedelta(days=MAX_NIGHTS + 1)).isoformat()}

    PlanRequest.model_validate(make_request(dates=longest))
    (error,) = errors_of(make_request(dates=too_long))
    assert (error["loc"], error["type"]) == (("dates", "exact_end"), "trip_too_long")
    assert error["msg"] == "the trip can last at most 120 days (119 nights), got 120 nights"


def test_month_needs_nights() -> None:
    assert error_types(make_request(dates={"month": "2026-11"})) == {
        (("dates", "nights"), "nights_required")
    }


def test_nights_need_a_month() -> None:
    assert error_types(make_request(dates={"nights": 4})) == {
        (("dates", "month"), "month_required")
    }


def test_blank_month_counts_as_missing() -> None:
    assert error_types(make_request(dates={"month": " ", "nights": 4})) == {
        (("dates", "month"), "month_required")
    }


@pytest.mark.parametrize("month", ["2026-13", "2026-00", "2026-\u0661\u0661"])
def test_month_must_exist(month: str) -> None:
    assert error_types(make_request(dates=flexible(month))) == {
        (("dates", "month"), "invalid_month")
    }


@pytest.mark.parametrize("month", ["2026-1", "11-2026", "2026/11", "novembre"])
def test_month_format(month: str) -> None:
    assert error_types(make_request(dates=flexible(month))) == {
        (("dates", "month"), "string_pattern_mismatch")
    }


@pytest.mark.parametrize(
    ("nights", "error"), [(0, "greater_than"), (MAX_NIGHTS + 1, "trip_too_long")]
)
def test_nights_bounds(nights: int, error: str) -> None:
    assert error_types(make_request(dates=flexible(nights=nights))) == {
        (("dates", "nights"), error)
    }


def test_nights_upper_bound_is_inclusive() -> None:
    PlanRequest.model_validate(make_request(dates=flexible(nights=MAX_NIGHTS)))


# --- dates: in the future ------------------------------------------------------------------


@pytest.mark.parametrize("start", ["2026-10-12", "2026-10-11", "2026-08-30"])
def test_exact_start_must_be_after_today(start: str) -> None:
    (error,) = errors_of(make_request(dates={"exact_start": start, "exact_end": "2026-11-20"}))

    assert (error["loc"], error["type"]) == (("dates", "exact_start"), "start_not_in_future")
    assert error["msg"] == f"exact_start ({start}) must be after today (2026-10-12)"
    assert error["ctx"] == {"exact_start": start, "today": "2026-10-12"}


def test_tomorrow_is_in_the_future() -> None:
    PlanRequest.model_validate(
        make_request(dates={"exact_start": "2026-10-13", "exact_end": "2026-10-15"})
    )


def test_past_start_and_missing_end_are_both_reported() -> None:
    assert error_types(make_request(dates={"exact_start": "2026-10-01"})) == {
        (("dates", "exact_start"), "start_not_in_future"),
        (("dates", "exact_end"), "exact_end_required"),
    }


def test_today_is_the_date_in_rome() -> None:
    # 23:30 UTC on Oct 12 is already Oct 13 in Rome: a trip starting Oct 13 starts "today".
    dates = {"exact_start": "2026-10-13", "exact_end": "2026-10-15"}
    with time_machine.travel(dt.datetime(2026, 10, 12, 23, 30, tzinfo=dt.UTC), tick=False):
        assert error_types(make_request(dates=dates)) == {
            (("dates", "exact_start"), "start_not_in_future")
        }


@pytest.mark.parametrize("month", ["2026-10", "2026-11", "2027-02"])
def test_this_month_or_later_is_accepted(month: str) -> None:
    PlanRequest.model_validate(make_request(dates=flexible(month)))


@pytest.mark.parametrize("month", ["2026-09", "2025-12"])
def test_past_months_are_rejected(month: str) -> None:
    (error,) = errors_of(make_request(dates=flexible(month)))

    assert (error["loc"], error["type"]) == (("dates", "month"), "month_in_past")
    assert error["msg"] == f"month {month} is in the past: choose 2026-10 or later"


def test_current_month_follows_rome() -> None:
    with time_machine.travel(dt.datetime(2026, 10, 31, 23, 30, tzinfo=dt.UTC), tick=False):
        assert error_types(make_request(dates=flexible("2026-10"))) == {
            (("dates", "month"), "month_in_past")
        }


def test_stored_requests_skip_the_future_checks() -> None:
    past = make_request(dates={"exact_start": "2026-03-01", "exact_end": "2026-03-05"})
    past_month = make_request(dates=flexible("2026-03"))

    assert PlanRequest.from_stored(past).dates.exact_start == dt.date(2026, 3, 1)
    assert PlanRequest.from_stored(past_month).dates.month == "2026-03"
    PlanRequest.model_validate(past, context={ALLOW_PAST_DATES: True})
    assert error_types(past) == {(("dates", "exact_start"), "start_not_in_future")}


def test_stored_requests_still_follow_the_other_rules() -> None:
    data = make_request(dates={"exact_start": "2026-03-05", "exact_end": "2026-03-01"})

    with pytest.raises(ValidationError, match="end_before_start"):
        PlanRequest.from_stored(data)


def test_unrelated_context_keeps_the_future_checks() -> None:
    data = make_request(dates={"exact_start": "2026-03-01", "exact_end": "2026-03-05"})

    with pytest.raises(ValidationError, match="start_not_in_future"):
        PlanRequest.model_validate(data, context={"something": "else"})


def test_date_window_validates_on_its_own() -> None:
    window = DateWindow.model_validate({"month": "2026-12", "nights": 3})

    assert not window.is_exact
    with pytest.raises(ValidationError, match="dates_required"):
        DateWindow.model_validate({})


# --- reporting -----------------------------------------------------------------------------


def test_independent_problems_are_reported_together() -> None:
    data = make_request(destination=None, travelers=[{"kind": "child", "age": 9}])

    assert error_types(data) == {
        (("destination",), "destination_required"),
        (("travelers",), "adult_required"),
    }


@pytest.mark.parametrize(
    ("field", "value"),
    [("origin", "Mila\x00no"), ("preferences", "cucina\x00locale"), ("destination", "\x07Roma")],
)
def test_control_characters_are_rejected(field: str, value: str) -> None:
    assert error_types(make_request(**{field: value})) == {((field,), "control_character")}


def test_newlines_in_preferences_are_allowed() -> None:
    request = PlanRequest.model_validate(make_request(preferences="Mare\r\nCucina locale"))

    assert request.preferences == "Mare\r\nCucina locale"


def test_errors_serialize_to_json_with_their_context() -> None:
    with pytest.raises(ValidationError) as caught:
        PlanRequest.model_validate(make_request(dates=flexible("2026-01")))

    (error,) = json.loads(caught.value.json())
    assert error["type"] == "month_in_past"
    assert error["loc"] == ["dates", "month"]
    assert error["ctx"] == {"month": "2026-01", "current_month": "2026-10"}


def test_every_error_code_has_a_message_and_is_in_the_schema() -> None:
    assert set(REQUEST_ERRORS) == set(RequestErrorCode)
    extra = PlanRequest.model_json_schema()["x-error-codes"]
    assert extra == {code.value: message for code, message in REQUEST_ERRORS.items()}


def test_every_field_has_a_description() -> None:
    for model in (PlanRequest, DateWindow, Traveler):
        for name, field in model.model_fields.items():
            assert field.description, f"{model.__name__}.{name} has no description"


# --- journey mode --------------------------------------------------------------------------


@pytest.mark.parametrize("mode", ["flight", "train", "ferry", "car", "coach"])
def test_journey_mode_accepts_each_mode(mode: str) -> None:
    assert PlanRequest.model_validate(make_request(journey_mode=mode)).journey_mode == mode


def test_journey_mode_defaults_to_none() -> None:
    assert PlanRequest.model_validate(make_request()).journey_mode is None


def test_journey_mode_rejects_an_unknown_mode() -> None:
    errors = errors_of(make_request(journey_mode="plane"))

    assert [tuple(error["loc"]) for error in errors] == [("journey_mode",)]


def test_from_stored_reads_a_request_stored_before_the_mode() -> None:
    stored = make_request(dates={"exact_start": "2026-03-01", "exact_end": "2026-03-05"})
    assert "journey_mode" not in stored

    assert PlanRequest.from_stored(stored).journey_mode is None
