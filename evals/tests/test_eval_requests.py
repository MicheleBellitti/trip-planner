"""evals/requests.yaml: five PlanRequests whose dates are relative to the run date (valid on
any day, trips a few weeks ahead), with consistent expectations and no personal data."""

from __future__ import annotations

import datetime as dt
import json
import re

import pytest
import yaml

import checks
import run
from app import clock
from app.request import PlanRequest

DATASET = run.load_dataset()
CASES = {case.id: case for case in DATASET.cases}


def frozen_at(day: dt.date):
    instant = dt.datetime.combine(day, dt.time(12, 0), tzinfo=clock.HOME_TIMEZONE)
    return lambda: instant


def test_five_reference_requests() -> None:
    assert len(DATASET.cases) == 5
    assert len(CASES) == 5


def test_the_spec_categories_are_covered() -> None:
    """Weekend in a European city, a week at the sea with children, "suggest one" on a low
    budget, a train trip, flexible dates (spec "Eval sui piani")."""
    requests = {case_id: case.request for case_id, case in CASES.items()}
    city = requests["city-weekend-lisbon"]
    start = dt.date.fromisoformat(city["dates"]["exact_start"])
    end = dt.date.fromisoformat(city["dates"]["exact_end"])
    assert start.weekday() == 4
    assert (end - start).days == 2
    sea = requests["sea-week-family"]
    assert any(t["kind"] == "child" for t in sea["travelers"])
    sea_start = dt.date.fromisoformat(sea["dates"]["exact_start"])
    assert (dt.date.fromisoformat(sea["dates"]["exact_end"]) - sea_start).days == 7
    suggest = requests["suggest-low-budget"]
    assert suggest["suggest_destination"] is True
    assert "destination" not in suggest
    assert suggest["budget_eur"] <= 300
    train = requests["train-trip-florence"]
    assert "treno" in train["preferences"].lower()
    assert "train" in CASES["train-trip-florence"].tags
    flexible = requests["flexible-dates-budapest"]
    assert set(flexible["dates"]) == {"month", "nights"}


RUN_DATES = [
    clock.today(),
    dt.date(2026, 10, 13),
    dt.date(2026, 12, 28),  # trips cross the new year
    dt.date(2027, 1, 31),  # month end: in_months must not overflow into March
    dt.date(2027, 12, 31),  # the flexible month lands in a leap February
    dt.date(2028, 2, 29),  # leap day
    dt.date(2028, 12, 31),
]


def month_bounds(month: str) -> tuple[dt.date, dt.date]:
    first = dt.date.fromisoformat(month + "-01")
    return first, (first + dt.timedelta(days=32)).replace(day=1) - dt.timedelta(days=1)


def dataset_for(day: dt.date, monkeypatch: pytest.MonkeyPatch) -> run.Dataset:
    monkeypatch.setattr(clock, "now", frozen_at(day))
    assert clock.today() == day
    return run.load_dataset(run_date=day)


@pytest.mark.parametrize("on", RUN_DATES, ids=str)
def test_every_request_is_valid_for_any_run_date(
    on: dt.date, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The dates never go stale: on any run date every entry resolves to a PlanRequest the
    backend accepts (trip in the future), and the whole dataset passes the run's validation."""
    dataset = dataset_for(on, monkeypatch)
    assert dataset.run_date == on
    requests = run.validate_requests(dataset.cases)
    assert set(requests) == set(CASES)
    for case in dataset.cases:
        PlanRequest.model_validate(case.request)


@pytest.mark.parametrize("on", RUN_DATES, ids=str)
def test_trips_are_a_few_weeks_to_a_few_months_ahead(
    on: dt.date, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Near enough that flight schedules, timetables and hotel rates are published."""
    for case in dataset_for(on, monkeypatch).cases:
        dates = case.request["dates"]
        if "exact_start" in dates:
            start = dt.date.fromisoformat(dates["exact_start"])
            assert dt.timedelta(weeks=5) <= start - on <= dt.timedelta(weeks=14), case.id
        else:
            first, last = month_bounds(dates["month"])
            assert first > on, case.id
            assert (last - on).days <= 4 * 31, case.id


@pytest.mark.parametrize("on", RUN_DATES, ids=str)
def test_the_weekday_the_request_implies_holds(
    on: dt.date, monkeypatch: pytest.MonkeyPatch
) -> None:
    cases = {case.id: case for case in dataset_for(on, monkeypatch).cases}
    weekend = cases["city-weekend-lisbon"].request["dates"]
    assert dt.date.fromisoformat(weekend["exact_start"]).weekday() == 4  # Friday
    assert dt.date.fromisoformat(weekend["exact_end"]).weekday() == 6  # Sunday
    cheap = cases["suggest-low-budget"].request["dates"]
    assert dt.date.fromisoformat(cheap["exact_start"]).weekday() == 4
    sea = cases["sea-week-family"].request["dates"]
    assert dt.date.fromisoformat(sea["exact_start"]).weekday() == 5  # Saturday


def test_the_dates_resolve_for_the_reference_run_date(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pins the offsets of requests.yaml: a change to them is deliberate."""
    dataset = dataset_for(dt.date(2026, 10, 13), monkeypatch)
    assert dataset.resolved_dates() == {
        "city-weekend-lisbon": {"exact_start": "2026-11-27", "exact_end": "2026-11-29"},
        "sea-week-family": {"exact_start": "2027-01-09", "exact_end": "2027-01-16"},
        "suggest-low-budget": {"exact_start": "2026-11-20", "exact_end": "2026-11-22"},
        "train-trip-florence": {"exact_start": "2026-12-04", "exact_end": "2026-12-08"},
        "flexible-dates-budapest": {"month": "2026-12", "nights": 4},
    }


def test_the_month_at_the_end_of_a_month_does_not_overflow() -> None:
    assert run.resolve_month({"in_months": 1}, dt.date(2027, 1, 31), "m") == "2027-02"
    assert run.resolve_month({"in_months": 2}, dt.date(2027, 12, 31), "m") == "2028-02"
    assert run.resolve_month({"in_months": 3}, dt.date(2026, 11, 30), "m") == "2027-02"
    assert run.resolve_month({"in_months": 0}, dt.date(2026, 10, 12), "m") == "2026-10"


def test_resolve_date_offsets_and_weekdays() -> None:
    day = dt.date(2026, 10, 13)  # a Tuesday
    assert run.resolve_date({"in_days": 10}, day, "d") == dt.date(2026, 10, 23)
    assert run.resolve_date({"in_weeks": 2}, day, "d") == dt.date(2026, 10, 27)
    assert run.resolve_date({"in_weeks": 2, "weekday": "Tuesday"}, day, "d") == dt.date(
        2026, 10, 27
    )
    assert run.resolve_date({"in_weeks": 2, "weekday": "friday"}, day, "d") == dt.date(2026, 10, 30)
    assert run.resolve_date({"in_days": 7, "weekday": "monday"}, day, "d") == dt.date(2026, 10, 26)
    assert run.resolve_date("2026-12-24", day, "d") == dt.date(2026, 12, 24)


@pytest.mark.parametrize(
    "spec",
    [
        {},
        {"in_days": 3, "in_weeks": 1},
        {"in_weeks": -1},
        {"in_weeks": "2"},
        {"in_weeks": 2, "weekday": "someday"},
        {"in_weeks": 2, "unknown": 1},
        "not a date",
    ],
)
def test_bad_date_specs_are_usage_errors(spec: object) -> None:
    with pytest.raises(run.UsageError):
        run.resolve_date(spec, dt.date(2026, 10, 13), "d")


def test_literal_dates_pass_through_and_relative_ones_need_nights() -> None:
    day = dt.date(2026, 10, 13)
    literal = {"exact_start": "2026-12-04", "exact_end": "2026-12-06"}
    assert run.resolve_dates(literal, day, "d") == literal
    with pytest.raises(run.UsageError, match="takes nights"):
        run.resolve_dates({"exact_start": {"in_weeks": 4}}, day, "d")
    with pytest.raises(run.UsageError, match="takes nights"):
        run.resolve_dates(
            {"exact_start": {"in_weeks": 4}, "exact_end": "2026-12-06", "nights": 2}, day, "d"
        )
    with pytest.raises(run.UsageError):
        run.resolve_month({"in_weeks": 1}, day, "m")


def test_expect_dates_are_derived_not_written() -> None:
    raw = {
        "id": "x",
        "request": {"dates": {"exact_start": {"in_weeks": 4}, "nights": 1}},
        "expect": {"dates": {"start": "2026-11-10", "end": "2026-11-11"}},
    }
    with pytest.raises(run.UsageError, match="derived"):
        run.resolve_case(raw, dt.date(2026, 10, 13))


def test_the_yaml_has_no_expiry_fields_and_no_expect_dates() -> None:
    text = run.DATASET_PATH.read_text(encoding="utf-8")
    data = yaml.safe_load(text)
    assert "valid_until" not in data
    assert "authored_on" not in data
    for entry in data["requests"]:
        assert "dates" not in entry["expect"], entry["id"]


@pytest.mark.parametrize("case_id", sorted(CASES))
def test_expectations_match_the_request(case_id: str) -> None:
    case = CASES[case_id]
    request = PlanRequest.from_stored(case.request)
    expect = case.expectations
    assert expect.travelers == len(request.travelers)
    assert expect.budget_eur == request.budget_eur
    if request.dates.is_exact:
        assert (expect.start, expect.end) == (request.dates.exact_start, request.dates.exact_end)
        assert expect.month is None
        assert expect.nights is None
    else:
        assert (expect.month, expect.nights) == (request.dates.month, request.dates.nights)
        assert expect.start is None
        assert expect.end is None
    if request.suggest_destination:
        assert expect.destination_any == ()
    else:
        assert request.destination is not None
        assert any(
            checks.mentions(checks.fold(request.destination), k) for k in expect.destination_any
        )
    assert expect.must_mention, "every request names at least one preference to find"
    for group in expect.must_mention:
        assert group
        assert all(isinstance(k, str) and k.strip() for k in group)


@pytest.mark.parametrize("case_id", sorted(CASES))
def test_tags_and_titles(case_id: str) -> None:
    case = CASES[case_id]
    assert case.tags
    assert all(re.fullmatch(r"[a-z0-9-]+", tag) for tag in case.tags)
    assert case.title
    assert case.title != case.id


@pytest.mark.parametrize("case_id", sorted(CASES))
def test_no_personal_data(case_id: str) -> None:
    """Agents only get cities, dates, travellers' kinds and ages, budget and preferences."""
    request = PlanRequest.from_stored(CASES[case_id].request)
    text = json.dumps(request.model_dump(mode="json", exclude_none=True), ensure_ascii=False)
    assert not re.search(r"[\w.+-]+@[\w-]+\.", text)  # no email
    assert not re.search(r"\+?\d[\d ]{8,}\d", text)  # no phone number
    assert set(request.model_dump(exclude_none=True)) <= {
        "origin",
        "destination",
        "suggest_destination",
        "destination_idea",
        "dates",
        "travelers",
        "budget_eur",
        "preferences",
    }


def test_resolved_dates_are_strings() -> None:
    """Unquoted YAML dates would become date objects; resolved ones are ISO strings."""
    for case in DATASET.cases:
        for key, value in case.request["dates"].items():
            assert isinstance(value, int if key == "nights" else str), (case.id, key)
