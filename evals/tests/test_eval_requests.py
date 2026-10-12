"""evals/requests.yaml: five valid PlanRequests, valid for a year, with consistent
expectations and no personal data."""

from __future__ import annotations

import datetime as dt
import json
import re

import pytest

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


@pytest.mark.parametrize("case_id", sorted(CASES))
def test_valid_today(case_id: str) -> None:
    """Fails once a date has passed: move every date forward (see requests.yaml header)."""
    PlanRequest.model_validate(CASES[case_id].request)


@pytest.mark.parametrize("case_id", sorted(CASES))
@pytest.mark.parametrize("on", [DATASET.authored_on, DATASET.valid_until])
def test_valid_for_a_year(case_id: str, on: dt.date, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(clock, "now", frozen_at(on))
    assert clock.today() == on
    PlanRequest.model_validate(CASES[case_id].request)


def test_valid_until_is_at_least_a_year_after_authoring() -> None:
    assert DATASET.valid_until - DATASET.authored_on >= dt.timedelta(days=365)


def test_the_dataset_goes_stale_when_the_first_trip_starts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The validity check really bites: on the day the earliest trip starts it fails."""
    earliest = min(
        dt.date.fromisoformat(case.request["dates"]["exact_start"])
        for case in DATASET.cases
        if "exact_start" in case.request["dates"]
    )
    monkeypatch.setattr(clock, "now", frozen_at(earliest))
    with pytest.raises(run.UsageError, match="dates in the past"):
        run.validate_requests(DATASET.cases)


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


def test_dates_are_strings_in_the_yaml() -> None:
    """Unquoted YAML dates would become date objects; quoted ones stay JSON-like."""
    for case in DATASET.cases:
        for value in case.request["dates"].values():
            assert isinstance(value, str | int)
