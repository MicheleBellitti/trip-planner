"""example.json is the coordinator's model of a complete plan: it must pass the backend's Plan
validation (the submit_plan input), keep the three rules of the skill, cover the shapes the
SKILL.md promises, and pass the deterministic eval checks that apply to a plan alone.

Run: cd backend && uv run pytest ../skills -q
"""

from __future__ import annotations

import datetime as dt
import importlib
import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any
from zoneinfo import ZoneInfo

import pytest

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
BACKEND = REPO / "backend"
EXAMPLE = HERE / "example.json"

if str(BACKEND) not in sys.path:
    sys.path.append(str(BACKEND))

plan_module = importlib.import_module("app.plan")
links = importlib.import_module("app.links")


@pytest.fixture(scope="module")
def raw() -> dict[str, Any]:
    return json.loads(EXAMPLE.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def plan(raw: dict[str, Any]) -> Any:
    return plan_module.Plan.model_validate(raw)


def test_example_is_a_valid_submit_plan_input(plan: Any) -> None:
    assert plan.start_date.year == plan.end_date.year == 2027


def test_every_date_has_a_day_with_stops(plan: Any) -> None:
    assert [day.date for day in plan.days] == plan.trip_dates()
    assert len(plan.days) == 6
    assert all(day.stops for day in plan.days)


def test_covers_every_stop_kind_and_several_booking_kinds(plan: Any) -> None:
    assert {stop.kind for _, _, stop in plan.iter_stops()} == {
        "activity",
        "meal",
        "transfer",
        "rest",
    }
    assert len({booking.kind for booking in plan.bookings}) >= 5
    both = [b for b in plan.bookings if b.book_by is not None and b.scheduled_for is not None]
    assert len({b.kind for b in both}) >= 4
    assert any(b.book_by is None and b.scheduled_for is not None for b in plan.bookings)
    assert plan.alternatives
    assert plan.warnings


def test_book_by_strictly_before_scheduled_for(plan: Any) -> None:
    for booking in [*plan.bookings, *plan.alternatives]:
        if booking.book_by is not None and booking.scheduled_for is not None:
            assert booking.book_by < booking.scheduled_for, booking.title


def test_instants_carry_the_trip_zone_offset_of_their_date(plan: Any) -> None:
    zone = ZoneInfo(plan.timezone)
    for booking in [*plan.bookings, *plan.alternatives]:
        for instant in (booking.book_by, booking.scheduled_for):
            if instant is None:
                continue
            assert instant.utcoffset() == instant.astimezone(zone).utcoffset(), booking.title
    # The example shows both offsets of Europe/London: a deadline before the March change.
    offsets = {b.book_by.utcoffset() for b in plan.bookings if b.book_by is not None}
    assert offsets == {dt.timedelta(0), dt.timedelta(hours=1)}


def test_has_a_non_eur_price_and_every_price_has_its_source(plan: Any) -> None:
    prices = [b.price for b in [*plan.bookings, *plan.alternatives] if b.price is not None]
    assert {price.currency for price in prices} >= {"EUR", "GBP"}
    assert {price.status for price in prices} == {"verified", "estimated"}
    for price in prices:
        assert price.source_url is not None
        assert price.retrieved_at.utcoffset() is not None


def test_booking_links_are_on_the_backend_allowlist(plan: Any) -> None:
    urls = [b.link for b in [*plan.bookings, *plan.alternatives] if b.link is not None]
    assert urls
    for url in urls:
        try:
            verdict = links.check_link(url)
        except NotImplementedError:
            pytest.skip("backend app.links.check_link is still a stub")
        assert verdict.allowed, url


def test_summary_has_three_lines_with_a_total(plan: Any) -> None:
    lines = plan.summary.split("\n")
    assert len(lines) == 3
    assert "€" in lines[2]
    assert "budget" in lines[2]


def _evals_checks() -> ModuleType | None:
    path = REPO / "evals" / "checks.py"
    if not path.is_file():
        return None
    spec = importlib.util.spec_from_file_location("skills_test_evals_checks", path)
    if spec is None or spec.loader is None:
        return None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses resolve their module by name
    try:
        spec.loader.exec_module(module)
    except Exception:  # the evals are another team's work in progress
        sys.modules.pop(spec.name, None)
        return None
    return module


def test_passes_the_plan_only_eval_checks(raw: dict[str, Any]) -> None:
    checks = _evals_checks()
    if checks is None:
        pytest.skip("evals/checks.py is not available")
    request = importlib.import_module("app.request").PlanRequest.model_validate(
        {
            "origin": "Milano",
            "destination": "Edimburgo",
            "dates": {"exact_start": "2027-05-13", "exact_end": "2027-05-18"},
            "travelers": [{"kind": "adult"}, {"kind": "adult"}, {"kind": "child", "age": 10}],
            "budget_eur": 2500,
        },
        context={"allow_past_dates": True},
    )
    metadata = checks.RunMetadata(profile="development", status="ready", submit_attempts=1)
    names = (
        "book_by_before_scheduled_for",
        "within_budget_or_warned",
        "prices_have_source",
        "links_on_allowed_domains",
        "no_empty_days",
    )
    results = {result.name: result for result in checks.run_checks(request, raw, None, metadata)}
    for name in names:
        assert results[name].status in {"pass", "warn"}, (
            name,
            results[name].message,
            results[name].details,
        )
