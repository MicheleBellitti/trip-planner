"""evals/checks.py over handcrafted fixtures: a plan that passes every check (the Lisbon
weekend of evals/requests.yaml) and, for every rule, a copy that violates it."""

from __future__ import annotations

import copy
import datetime as dt
import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

import checks
import run
from app.request import PlanRequest

FIXTURES = Path(__file__).resolve().parent / "fixtures"
DATASET = Path(checks.EVALS_DIR) / "requests.yaml"

Json = dict[str, Any]


@dataclass(frozen=True)
class FakeVerdict:
    allowed: bool
    host: str | None = None
    reason: str | None = None


ALLOWED_HOSTS = {"www.expedia.it", "www.booking.com", "www.airbnb.it", "www.kiwi.com"}


def fake_link_checker(url: str) -> FakeVerdict:
    """A stand-in for app.links.check_link: exact hosts, https only."""
    from urllib.parse import urlsplit

    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    if parts.scheme != "https":
        return FakeVerdict(False, host, "not_https")
    if host not in ALLOWED_HOSTS:
        return FakeVerdict(False, host, "unknown_host")
    return FakeVerdict(True, host)


FIXTURE_RUN_DATE = dt.date(2027, 10, 1)
"""The run date that puts the Lisbon weekend on the fixtures' dates (Fri 2027-11-12 to Sun
2027-11-14): 6 weeks later is exactly that Friday."""


def lisbon_case() -> run.EvalCase:
    dataset = run.load_dataset(DATASET, run_date=FIXTURE_RUN_DATE)
    return next(case for case in dataset.cases if case.id == "city-weekend-lisbon")


def lisbon_request() -> PlanRequest:
    return PlanRequest.from_stored(lisbon_case().request)


def lisbon_expect() -> checks.Expectations:
    return lisbon_case().expectations


def ok_plan() -> Json:
    return json.loads((FIXTURES / "plan_lisbon_ok.json").read_text(encoding="utf-8"))


def ok_trip() -> Json:
    return json.loads((FIXTURES / "trip_lisbon_ok.json").read_text(encoding="utf-8"))


def _verdict(status: str = "ok", reason: str = "ok", *, fallback: str | None = None) -> Json:
    return {
        "status": status,
        "reason": reason,
        "http_status": None,
        "fallback": fallback,
        "fallback_allowed": fallback is not None,
        "checked_at": "2026-10-18T10:00:00+00:00",
    }


HEALTHY_LINKS: Json = {
    "https://a.example/x": _verdict(),
    "https://b.example/y": _verdict(),
    "https://c.example/z": _verdict("unknown", "timeout"),
}

OK_METADATA = checks.RunMetadata(
    profile="development",
    status="ready",
    submit_attempts=1,
    cost_cents=41,
    web_search_requests=12,
    link_health=HEALTHY_LINKS,
)


def run_all(
    plan: Json | None,
    trip: Json | None,
    metadata: checks.RunMetadata = OK_METADATA,
    *,
    link_checker: checks.LinkChecker = fake_link_checker,
) -> dict[str, checks.CheckResult]:
    results = checks.run_checks(
        lisbon_request(),
        plan,
        trip,
        metadata,
        expect=lisbon_expect(),
        link_checker=link_checker,
    )
    return {result.name: result for result in results}


# --- the passing fixture ------------------------------------------------------------------------


def test_the_ok_fixture_passes_every_check() -> None:
    results = run_all(ok_plan(), ok_trip())
    assert list(results) == list(checks.CHECK_NAMES)
    assert {name: r.status for name, r in results.items()} == dict.fromkeys(
        checks.CHECK_NAMES, "pass"
    )
    assert checks.blocking_failures(results.values()) == []


def test_results_are_json_serializable() -> None:
    results = run_all(ok_plan(), ok_trip())
    json.dumps([r.to_json() for r in results.values()])


# --- one violation per rule ---------------------------------------------------------------------


@dataclass(frozen=True)
class Violation:
    check: str
    mutate: Callable[[Json, Json], None]
    metadata: checks.RunMetadata = OK_METADATA
    expected_status: str = "fail"


def _summary_empty(plan: Json, trip: Json) -> None:
    plan["summary"] = ""


def _trip_title_too_long(plan: Json, trip: Json) -> None:
    trip["title"] = "x" * 121


def _trip_end_before_start(plan: Json, trip: Json) -> None:
    trip["endDate"] = "2027-11-11"


def _plan_unknown_key(plan: Json, trip: Json) -> None:
    plan["days"][0]["stops"][0]["colour"] = "blue"


def _book_by_equals_scheduled(plan: Json, trip: Json) -> None:
    booking = plan["bookings"][1]
    booking["book_by"] = booking["scheduled_for"]


def _book_by_after_scheduled_in_alternative(plan: Json, trip: Json) -> None:
    plan["alternatives"][0]["book_by"] = "2027-11-13T09:00:00+00:00"


def _due_at_after_scheduled_in_trip(plan: Json, trip: Json) -> None:
    trip["bookings"][2]["dueAt"] = "2027-11-13T11:00:00+00:00"


def _naive_book_by(plan: Json, trip: Json) -> None:
    plan["bookings"][0]["book_by"] = "2027-10-29T20:00:00"


def _over_budget(plan: Json, trip: Json) -> None:
    plan["bookings"][1]["price"]["amount_cents"] = 80000
    trip["bookings"][1]["costCents"] = 80000


def _price_without_source(plan: Json, trip: Json) -> None:
    del plan["bookings"][2]["price"]["source_url"]


def _price_without_offset(plan: Json, trip: Json) -> None:
    plan["alternatives"][0]["price"]["retrieved_at"] = "2026-10-12T15:04:00"


def _link_on_unknown_domain(plan: Json, trip: Json) -> None:
    plan["bookings"][1]["link"] = "https://booking.com.evil.example/searchresults.html"


def _trip_url_on_unknown_domain(plan: Json, trip: Json) -> None:
    trip["bookings"][0]["url"] = "http://www.expedia.it/Flights-Search"


def _empty_middle_day(plan: Json, trip: Json) -> None:
    plan["days"][1]["stops"] = []
    plan["bookings"][2]["stop_ref"] = None


def _missing_middle_day(plan: Json, trip: Json) -> None:
    del plan["days"][1]
    plan["bookings"][2]["stop_ref"] = None


def _wrong_travelers(plan: Json, trip: Json) -> None:
    plan["travelers"] = 3


def _wrong_dates(plan: Json, trip: Json) -> None:
    plan["end_date"] = "2027-11-15"


def _no_museum(plan: Json, trip: Json) -> None:
    for day in plan["days"]:
        day["stops"] = [
            s for s in day["stops"] if not s["ref"].startswith(("d2-jeronimos", "d2-azulejo"))
        ]
    plan["bookings"] = [b for b in plan["bookings"] if b["kind"] != "ticket"]
    plan["summary"] = "Tre giorni a Lisbona. Costo stimato totale: 698 € per due persone."
    plan["days"][1]["title"] = "Belém"


def _wrong_destination(plan: Json, trip: Json) -> None:
    plan["destination"] = "Porto, Portogallo"


def _nothing(plan: Json, trip: Json) -> None:
    return None


VIOLATIONS: dict[str, Violation] = {
    "summary_empty": Violation(checks.SCHEMA_VALID, _summary_empty),
    "trip_title_too_long": Violation(checks.SCHEMA_VALID, _trip_title_too_long),
    "trip_end_before_start": Violation(checks.SCHEMA_VALID, _trip_end_before_start),
    "plan_unknown_key": Violation(checks.SCHEMA_VALID, _plan_unknown_key),
    "book_by_equals_scheduled": Violation(
        checks.BOOK_BY_BEFORE_SCHEDULED, _book_by_equals_scheduled
    ),
    "book_by_after_in_alternative": Violation(
        checks.BOOK_BY_BEFORE_SCHEDULED, _book_by_after_scheduled_in_alternative
    ),
    "due_at_after_in_trip": Violation(
        checks.BOOK_BY_BEFORE_SCHEDULED, _due_at_after_scheduled_in_trip
    ),
    "naive_book_by": Violation(checks.BOOK_BY_BEFORE_SCHEDULED, _naive_book_by),
    "over_budget_without_warning": Violation(checks.WITHIN_BUDGET, _over_budget),
    "price_without_source": Violation(checks.PRICES_HAVE_SOURCE, _price_without_source),
    "price_without_offset": Violation(checks.PRICES_HAVE_SOURCE, _price_without_offset),
    "link_on_unknown_domain": Violation(checks.LINKS_ALLOWED, _link_on_unknown_domain),
    "trip_url_not_https": Violation(checks.LINKS_ALLOWED, _trip_url_on_unknown_domain),
    "empty_middle_day": Violation(checks.NO_EMPTY_DAYS, _empty_middle_day),
    "missing_middle_day": Violation(checks.NO_EMPTY_DAYS, _missing_middle_day),
    "third_attempt": Violation(
        checks.SUBMIT_ATTEMPTS,
        _nothing,
        checks.RunMetadata(
            status="ready", submit_attempts=3, cost_cents=41, web_search_requests=12
        ),
    ),
    "not_ready": Violation(
        checks.SUBMIT_ATTEMPTS,
        _nothing,
        checks.RunMetadata(
            status="failed", submit_attempts=3, cost_cents=41, web_search_requests=1
        ),
    ),
    "attempts_not_recorded": Violation(
        checks.SUBMIT_ATTEMPTS,
        _nothing,
        checks.RunMetadata(status="ready", submit_attempts=None, cost_cents=41),
    ),
    "cost_above_estimate": Violation(
        checks.COST_VS_ESTIMATE,
        _nothing,
        checks.RunMetadata(
            status="ready", submit_attempts=1, cost_cents=71, web_search_requests=31
        ),
        expected_status="warn",
    ),
    "cost_not_recorded": Violation(
        checks.COST_VS_ESTIMATE,
        _nothing,
        checks.RunMetadata(status="ready", submit_attempts=1),
        expected_status="warn",
    ),
    "dead_link": Violation(
        checks.DEAD_LINKS,
        _nothing,
        checks.RunMetadata(
            status="ready",
            submit_attempts=1,
            cost_cents=41,
            web_search_requests=12,
            link_health={
                "https://www.A.example/secret/path?q=1": _verdict(
                    "dead", "http_404", fallback="https://www.a.example/"
                )
            },
        ),
        expected_status="warn",
    ),
    "wrong_travelers": Violation(checks.MATCHES_REQUEST, _wrong_travelers),
    "wrong_dates": Violation(checks.MATCHES_REQUEST, _wrong_dates),
    "preference_not_mentioned": Violation(checks.MATCHES_REQUEST, _no_museum),
    "wrong_destination": Violation(checks.MATCHES_REQUEST, _wrong_destination),
}


@pytest.mark.parametrize("name", sorted(VIOLATIONS))
def test_each_violation_fails_its_check(name: str) -> None:
    violation = VIOLATIONS[name]
    plan, trip = ok_plan(), ok_trip()
    violation.mutate(plan, trip)
    results = run_all(plan, trip, violation.metadata)
    result = results[violation.check]
    assert result.status == violation.expected_status, result
    assert result.blocks is (violation.expected_status == "fail")


def test_every_check_has_a_violation() -> None:
    covered = {violation.check for violation in VIOLATIONS.values()}
    assert covered == set(checks.CHECK_NAMES)


def test_violating_fixture_fails_every_blocking_rule() -> None:
    """One plan that breaks every rule at once: every blocking check fails."""
    plan, trip = ok_plan(), ok_trip()
    for mutate in (
        _summary_empty,
        _book_by_equals_scheduled,
        _over_budget,
        _price_without_source,
        _link_on_unknown_domain,
        _empty_middle_day,
        _wrong_travelers,
    ):
        mutate(plan, trip)
    metadata = checks.RunMetadata(status="ready", submit_attempts=3, cost_cents=90)
    results = run_all(plan, trip, metadata)
    failing = {name for name, r in results.items() if r.blocks}
    assert failing == set(checks.CHECK_NAMES) - {checks.COST_VS_ESTIMATE, checks.DEAD_LINKS}
    assert results[checks.COST_VS_ESTIMATE].status == "warn"
    assert not results[checks.COST_VS_ESTIMATE].blocks


# --- edge cases ---------------------------------------------------------------------------------


def test_over_budget_with_an_explicit_warning_passes() -> None:
    plan, trip = ok_plan(), ok_trip()
    _over_budget(plan, trip)
    plan["warnings"].append("Il totale stimato (1.154 €) supera il budget di 900 €.")
    result = run_all(plan, trip)[checks.WITHIN_BUDGET]
    assert result.status == "pass"
    assert "warning:" in result.details[-1]


def test_budget_uses_the_trips_eur_amounts_for_other_currencies() -> None:
    plan, trip = ok_plan(), ok_trip()
    price = plan["bookings"][1]["price"]
    price["currency"] = "USD"
    price["amount_cents"] = 41000
    trip["bookings"][1]["costCents"] = 38000  # converted by the backend
    assert run_all(plan, trip)[checks.WITHIN_BUDGET].status == "pass"


def test_budget_warns_when_a_price_has_no_eur_amount() -> None:
    plan, trip = ok_plan(), ok_trip()
    plan["bookings"][1]["price"]["currency"] = "USD"
    del trip["bookings"][1]["costCents"]  # the conversion failed
    result = run_all(plan, trip)[checks.WITHIN_BUDGET]
    assert result.status == "warn"
    assert not result.blocks


def test_empty_arrival_day_is_only_a_warning() -> None:
    plan, trip = ok_plan(), ok_trip()
    plan["days"][0]["stops"] = []
    for booking in plan["bookings"]:
        if booking.get("stop_ref", "") and booking["stop_ref"].startswith("d1-"):
            booking["stop_ref"] = None
    result = run_all(plan, trip)[checks.NO_EMPTY_DAYS]
    assert result.status == "warn"
    assert not result.blocks


def test_second_attempt_passes() -> None:
    metadata = checks.RunMetadata(status="ready", submit_attempts=2, cost_cents=41)
    assert run_all(ok_plan(), ok_trip(), metadata)[checks.SUBMIT_ATTEMPTS].status == "pass"


def test_no_plan_fails_schema_and_attempts_and_skips_content_checks() -> None:
    metadata = checks.RunMetadata(status="failed", submit_attempts=3, cost_cents=60)
    results = run_all(None, None, metadata)
    assert results[checks.SCHEMA_VALID].status == "fail"
    assert results[checks.SUBMIT_ATTEMPTS].status == "fail"
    for name in (
        checks.BOOK_BY_BEFORE_SCHEDULED,
        checks.WITHIN_BUDGET,
        checks.PRICES_HAVE_SOURCE,
        checks.LINKS_ALLOWED,
        checks.NO_EMPTY_DAYS,
        checks.MATCHES_REQUEST,
        checks.DEAD_LINKS,
    ):
        assert results[name].status == "skip", name


def test_ready_plan_without_trip_fails_schema() -> None:
    result = run_all(ok_plan(), None)[checks.SCHEMA_VALID]
    assert result.status == "fail"
    assert any("trip: missing" in line for line in result.details)


def test_extra_keys_of_the_stored_plan_are_ignored() -> None:
    plan = ok_plan()
    plan["mapping_warnings"] = ["x"]
    result = run_all(plan, ok_trip())[checks.SCHEMA_VALID]
    assert result.status == "pass"
    assert "mapping_warnings" in result.message


def test_unimplemented_link_checker_is_a_blocking_error() -> None:
    def not_implemented(url: str) -> FakeVerdict:
        raise NotImplementedError

    result = run_all(ok_plan(), ok_trip(), link_checker=not_implemented)[checks.LINKS_ALLOWED]
    assert result.status == "error"
    assert result.blocks


def test_a_crashing_check_becomes_an_error_not_an_exception() -> None:
    def explode(url: str) -> FakeVerdict:
        raise RuntimeError("boom")

    result = run_all(ok_plan(), ok_trip(), link_checker=explode)[checks.LINKS_ALLOWED]
    assert result.status == "error"
    assert "boom" in result.message


def test_the_backend_allowlist_accepts_the_ok_fixture_links() -> None:
    """The real app.links.check_link, once the backend implements it."""
    from app.links import check_link

    try:
        check_link("https://www.booking.com/")
    except NotImplementedError:
        pytest.skip("app.links.check_link is still a stub")
    results = run_all(ok_plan(), ok_trip(), link_checker=check_link)
    assert results[checks.LINKS_ALLOWED].status == "pass", results[checks.LINKS_ALLOWED]
    plan = ok_plan()
    _link_on_unknown_domain(plan, {})
    assert run_all(plan, ok_trip(), link_checker=check_link)[checks.LINKS_ALLOWED].status == "fail"


@pytest.mark.parametrize(
    ("text", "keyword", "expected"),
    [
        ("Prenota un tavolo", "volo", False),
        ("Volo diretto per Lisbona", "volo", True),
        ("Attività per i bambini", "bambin", True),
        ("Città d'arte", "citta", True),
        ("Széchenyi fürdő", "furdo", True),
        ("alta velocità", "alta velocita", True),
    ],
)
def test_keyword_matching(text: str, keyword: str, expected: bool) -> None:
    assert checks.mentions(checks.fold(text), keyword) is expected


def test_must_not_book_looks_at_bookings_only() -> None:
    plan, trip = ok_plan(), ok_trip()
    expect = checks.Expectations.from_mapping({**lisbon_case().expect, "must_not_book": ["volo"]})
    result = checks.check_matches_request(lisbon_request(), plan, trip, OK_METADATA, expect=expect)
    assert result.status == "fail"
    plan["bookings"] = [b for b in plan["bookings"] if b["kind"] != "transport"]
    result = checks.check_matches_request(lisbon_request(), plan, trip, OK_METADATA, expect=expect)
    assert result.status == "pass"  # stops still say "Volo": only bookings are forbidden


def test_flexible_dates_expectation() -> None:
    expect = checks.Expectations.from_mapping({"dates": {"month": "2027-11", "nights": 2}})
    plan = ok_plan()
    request = lisbon_request()
    assert checks.check_matches_request(request, plan, None, OK_METADATA, expect=expect).status == (
        "pass"
    )
    plan["end_date"] = "2027-11-15"
    plan["days"].append(
        {"date": "2027-11-15", "stops": [{"ref": "d4", "title": "x", "kind": "rest"}]}
    )
    result = checks.check_matches_request(request, plan, None, OK_METADATA, expect=expect)
    assert result.status == "fail"
    assert "3 night(s), expected 2" in result.details


def test_details_are_capped() -> None:
    plan = ok_plan()
    plan["alternatives"] = [copy.deepcopy(plan["alternatives"][0]) for _ in range(30)]
    for alternative in plan["alternatives"]:
        alternative["link"] = "https://evil.example/"
    result = run_all(plan, ok_trip())[checks.LINKS_ALLOWED]
    assert len(result.details) == checks.MAX_DETAILS + 1
    assert result.details[-1] == "... and 10 more"


# --- dead_links ---------------------------------------------------------------------------------


def test_dead_links_passes_with_none_dead() -> None:
    result = run_all(ok_plan(), ok_trip())[checks.DEAD_LINKS]
    assert result.status == "pass"
    assert result.message == "3 link(s) checked, none dead"
    assert not result.blocking


def test_dead_links_warns_with_hosts_and_reasons() -> None:
    metadata = checks.RunMetadata(
        status="ready",
        submit_attempts=1,
        cost_cents=41,
        web_search_requests=12,
        link_health={
            "https://www.A.example/secret/path?q=1": _verdict(
                "dead", "http_404", fallback="https://a.example/"
            ),
            "https://b.example/ok": _verdict(),
        },
    )
    result = run_all(ok_plan(), ok_trip(), metadata)[checks.DEAD_LINKS]
    assert result.status == "warn"
    assert result.blocking is False
    assert not result.blocks
    assert result.details == ["a.example http_404 (homepage: yes)"]


def test_dead_links_skips_without_a_plan_or_without_verdicts() -> None:
    no_plan = run_all(None, None)[checks.DEAD_LINKS]
    assert no_plan.status == "skip"
    unchecked = run_all(
        ok_plan(),
        ok_trip(),
        checks.RunMetadata(status="ready", submit_attempts=1, cost_cents=41),
    )[checks.DEAD_LINKS]
    assert unchecked.status == "skip"
    assert "not checked" in unchecked.message
