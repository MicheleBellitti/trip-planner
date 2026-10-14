"""app.evals_store: validation, the derived list fields, and the idempotent store (Postgres)."""

from __future__ import annotations

import asyncio
import copy
import datetime as dt
import json
import uuid
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app import evals_store
from app.db import EvalRunRecord
from app.evals_store import InvalidEvalResultsError

FIXTURE = Path(__file__).parent / "fixtures" / "evals" / "2026-10-12-5d22125b0352.json"


def real_results() -> dict[str, Any]:
    """Today's first CI run (five requests, all `budget_paused`, the judge skipped)."""
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def make_results(**overrides: Any) -> dict[str, Any]:
    values: dict[str, Any] = {
        "kind": "trip-planner-eval-results",
        "format": 1,
        "started_at": "2026-10-13T09:00:00+02:00",
        "finished_at": "2026-10-13T09:10:00+02:00",
        "git_sha": "abc123",
        "profile": "development",
        "aborted": False,
        "requests": [],
    }
    values.update(overrides)
    return values


def entry(**overrides: Any) -> dict[str, Any]:
    values: dict[str, Any] = {
        "id": "city-weekend-lisbon",
        "status": "ready",
        "checks_passed": True,
        "blocking_failures": [],
        "cost_cents": 40,
        "web_search_requests": 6,
        "judge": {
            "status": "ok",
            "scores": {"time_coherence": {"score": 4}, "summary_clarity": {"score": 5}},
        },
    }
    values.update(overrides)
    return values


def comparison(**overrides: Any) -> dict[str, Any]:
    values: dict[str, Any] = {
        "kind": "trip-planner-eval-comparison",
        "format": 1,
        "status": "passed",
        "blocked": False,
        "report_only": False,
    }
    values.update(overrides)
    return values


# --- the derived list fields ---------------------------------------------------------------------


def test_the_real_run_summarizes_like_run_py() -> None:
    results = real_results()

    metrics = evals_store.summarize_run(results["requests"], None)

    assert metrics.model_dump() == {
        "requests_total": 5,
        "requests_accepted": 0,
        "checks_passed": 0,
        "blocking_failures_count": results["summary"]["blocking_failures"],
        "total_cost_cents": results["summary"]["total_cost_cents"],
        "web_search_requests": results["summary"]["total_web_search_requests"],
        "judge_mean": None,
        "compare_status": None,
        "reference_judge_mean": None,
        "reference_cost_per_plan_cents": None,
        "blocking_findings": [],
    }
    assert (metrics.total_cost_cents, metrics.web_search_requests) == (309, 59)


def test_summary_counts_accepted_checked_and_scored_requests() -> None:
    requests = [
        entry(),
        entry(status="budget_paused", checks_passed=False, blocking_failures=["a", "b"]),
        entry(judge={"status": "ok", "scores": {"time_coherence": {"score": 2}}}),
        {"cost_cents": None, "web_search_requests": True, "judge": None},  # unknown values
    ]

    metrics = evals_store.summarize_run(requests, comparison(status="blocked"))

    assert metrics.requests_total == 4
    assert metrics.requests_accepted == 2
    assert metrics.checks_passed == 2
    assert metrics.blocking_failures_count == 2
    assert metrics.total_cost_cents == 120
    assert metrics.web_search_requests == 18
    assert metrics.judge_mean == pytest.approx((4 + 5 + 4 + 5 + 2) / 5, abs=1e-3)
    assert metrics.compare_status == "blocked"


def test_summary_keeps_the_baseline_the_gate_measured_against() -> None:
    document = comparison(
        criteria=[
            {"criterion": "time_coherence", "baseline_mean": 4.0, "current_mean": 3.0},
            {"criterion": "summary_clarity", "baseline_mean": 3.5, "current_mean": 4.0},
            {"criterion": "alternatives_quality", "baseline_mean": None, "current_mean": 4.0},
        ],
        cost={"baseline_mean_cents": 52.5, "current_mean_cents": 60.0},
    )

    metrics = evals_store.summarize_run([entry()], document)

    assert metrics.reference_judge_mean == pytest.approx(3.75)
    assert metrics.reference_cost_per_plan_cents == pytest.approx(52.5)
    assert evals_store.summarize_run([entry()], comparison()).reference_judge_mean is None
    assert evals_store.summarize_run([entry()], None).reference_cost_per_plan_cents is None


def finding(
    rule: str, message: str, request_id: str | None = None, **flags: bool
) -> dict[str, Any]:
    return {"rule": rule, "message": message, "request_id": request_id, **flags}


def test_summary_keeps_the_first_blocking_findings_with_their_request_titles() -> None:
    requests = [
        entry(id="sea-week-family", title="Settimana al mare con bambini"),
        entry(id="city-weekend-lisbon", title="Weekend in città europea"),
    ]
    document = comparison(
        status="blocked",
        blocked=True,
        findings=[
            finding("mean cost per plan", "cost up", blocking=False),
            finding("deterministic checks", "a", "sea-week-family", blocking=True, blocks=True),
            # A blocking rule that does not block this comparison (no baseline): not a reason.
            finding("judge criteria", "b", blocking=True, blocks=False),
            finding("run", "c", blocking=True),
            finding("deterministic checks", "d", "unknown-id", blocking=True),
            finding("deterministic checks", "e", "city-weekend-lisbon", blocking=True),
        ],
    )

    findings = evals_store.summarize_run(requests, document).blocking_findings

    assert [item.model_dump() for item in findings] == [
        {
            "rule": "deterministic checks",
            "message": "a",
            "request_id": "sea-week-family",
            "request_title": "Settimana al mare con bambini",
        },
        {"rule": "run", "message": "c", "request_id": None, "request_title": None},
        {
            "rule": "deterministic checks",
            "message": "d",
            "request_id": "unknown-id",
            "request_title": None,
        },
    ]


@pytest.mark.parametrize(
    ("document", "expected"),
    [
        (None, None),
        ({"status": "passed"}, "passed"),
        ({"status": "blocked", "blocked": False}, "blocked"),
        ({"status": "report_only"}, "report_only"),
        ({"blocked": True}, "blocked"),
        ({"blocked": True, "report_only": True}, "blocked"),
        ({"blocked": False, "report_only": True}, "report_only"),
        ({"blocked": False, "report_only": False}, "passed"),
        ({"status": "weird"}, None),
        ({}, None),
    ],
)
def test_comparison_status(document: dict[str, Any] | None, expected: str | None) -> None:
    assert evals_store.comparison_status(document) == expected


def test_run_key_is_the_same_instant_whatever_its_offset() -> None:
    rome = dt.datetime.fromisoformat("2026-10-13T09:00:00+02:00")
    utc = dt.datetime.fromisoformat("2026-10-13T07:00:00+00:00")

    assert evals_store.run_key("development", "abc", rome) == evals_store.run_key(
        "development", "abc", utc
    )
    assert evals_store.run_key("development", "abc", rome) != evals_store.run_key(
        "production", "abc", rome
    )
    assert evals_store.run_key("development", None, rome).startswith("development||")


# --- validation ----------------------------------------------------------------------------------


def test_the_real_results_file_is_valid() -> None:
    head = evals_store.validate_results(real_results())

    assert head.profile == "development"
    assert head.started_at.utcoffset() == dt.timedelta(hours=2)
    assert len(head.requests) == 5


@pytest.mark.parametrize(
    ("overrides", "field"),
    [
        ({"kind": "something-else"}, "results.kind"),
        ({"format": 2}, "results.format"),
        ({"started_at": "2026-10-13T09:00:00"}, "results.started_at"),
        ({"started_at": 1760000000}, "results.started_at"),
        ({"started_at": "yesterday"}, "results.started_at"),
        ({"profile": ""}, "results.profile"),
        ({"profile": None}, "results.profile"),
        ({"requests": {}}, "results.requests"),
        ({"requests": ["x"]}, "results.requests.0"),
        ({"aborted": "no"}, "results.aborted"),
        ({"git_sha": "x" * 65}, "results.git_sha"),
    ],
)
def test_loose_validation_still_refuses_a_document_that_is_not_a_run(
    overrides: dict[str, Any], field: str
) -> None:
    with pytest.raises(InvalidEvalResultsError) as caught:
        evals_store.validate_results(make_results(**overrides))

    assert field in [error["field"] for error in caught.value.errors]
    assert "something-else" not in str(caught.value)  # reasons never echo the input


def test_a_results_file_without_a_kind_is_refused() -> None:
    results = make_results()
    del results["kind"]

    with pytest.raises(InvalidEvalResultsError):
        evals_store.validate_results(results)


def test_unknown_extra_keys_are_accepted() -> None:
    evals_store.validate_results(make_results(future_field={"a": 1}))


def test_a_comparison_of_another_kind_or_format_is_refused() -> None:
    evals_store.validate_comparison(None)
    evals_store.validate_comparison(comparison())
    evals_store.validate_comparison({"status": "passed"})  # no kind: accepted
    for bad in ({"kind": "other"}, {"kind": "trip-planner-eval-comparison", "format": 3}):
        with pytest.raises(InvalidEvalResultsError):
            evals_store.validate_comparison(bad)


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        (None, None),
        ("", None),
        ("  ", None),
        (" https://github.com/o/r/actions/runs/1 ", "https://github.com/o/r/actions/runs/1"),
        ("http://localhost/run", "http://localhost/run"),
    ],
)
def test_workflow_run_url_is_normalized(url: str | None, expected: str | None) -> None:
    assert evals_store.validate_workflow_run_url(url) == expected


@pytest.mark.parametrize(
    "url",
    [
        "javascript:alert(1)",
        "ftp://example.com/x",
        "github.com/o/r",
        "https://example.com/a b",
        "https://example.com/" + "x" * evals_store.MAX_URL_LENGTH,
    ],
)
def test_workflow_run_url_must_be_a_plain_http_url(url: str) -> None:
    with pytest.raises(InvalidEvalResultsError):
        evals_store.validate_workflow_run_url(url)


def test_parse_json_refuses_what_jsonb_cannot_hold() -> None:
    assert evals_store.parse_json(b'{"a": [1, 2.5, "x"]}') == {"a": [1, 2.5, "x"]}
    for raw in (b"{", b"NaN", b'{"a": Infinity}', b"\xff\xfe", b"[" * 100_000):
        with pytest.raises(InvalidEvalResultsError):
            evals_store.parse_json(raw)


def test_clean_json_strips_nul_from_strings_and_keys() -> None:
    cleaned = evals_store.clean_json(
        {"a\x00b": ["x\x00y", {"k": "\x00"}], "n": 1, "f": 1.5, "z": None}
    )

    assert cleaned == {"ab": ["xy", {"k": ""}], "n": 1, "f": 1.5, "z": None}
    with pytest.raises(InvalidEvalResultsError):
        evals_store.clean_json({"f": float("nan")})


# --- the store -----------------------------------------------------------------------------------


async def count(db: AsyncSession) -> int:
    return await db.scalar(select(func.count()).select_from(EvalRunRecord)) or 0


async def test_store_creates_a_run_with_its_summary(db_session: AsyncSession) -> None:
    stored = await evals_store.store_eval_run(
        db_session,
        results=real_results(),
        comparison=comparison(status="report_only", report_only=True),
        workflow_run_url="https://github.com/o/r/actions/runs/9",
    )

    assert stored.created
    record = await db_session.get_one(EvalRunRecord, stored.id)
    assert record.profile == "development"
    assert record.git_sha == "5d22125b035243839e5ce2ece301861aaf5e4977"
    assert record.started_at == dt.datetime(2026, 10, 12, 20, 49, 40, 848706, tzinfo=dt.UTC)
    assert record.finished_at is not None
    assert record.aborted is False
    assert record.run_key.startswith("development|5d22125b")
    assert record.workflow_run_url == "https://github.com/o/r/actions/runs/9"
    assert record.results == real_results()
    assert record.comparison is not None
    assert record.summary["requests_total"] == 5
    assert record.summary["total_cost_cents"] == 309
    assert record.summary["compare_status"] == "report_only"


async def test_a_run_without_comparison_stores_sql_null(db_session: AsyncSession) -> None:
    stored = await evals_store.store_eval_run(db_session, results=make_results())

    record = await db_session.get_one(EvalRunRecord, stored.id)
    assert record.comparison is None
    assert record.workflow_run_url is None
    assert record.summary["compare_status"] is None
    null_count = await db_session.scalar(
        select(func.count()).where(EvalRunRecord.comparison.is_(None))
    )
    assert null_count == 1  # SQL NULL, not the JSON literal 'null'


async def test_uploading_the_same_run_again_is_idempotent(db_session: AsyncSession) -> None:
    first = await evals_store.store_eval_run(db_session, results=make_results())
    # Same instant, written in UTC: still the same run.
    again = await evals_store.store_eval_run(
        db_session, results=make_results(started_at="2026-10-13T07:00:00+00:00")
    )

    assert (again.id, again.created) == (first.id, False)
    assert await count(db_session) == 1


async def test_a_repeat_updates_the_comparison_and_the_link_but_never_erases_them(
    db_session: AsyncSession,
) -> None:
    results = make_results(requests=[entry()])
    first = await evals_store.store_eval_run(db_session, results=results)

    await evals_store.store_eval_run(
        db_session,
        results=results,
        comparison=comparison(
            status="blocked",
            blocked=True,
            findings=[{"rule": "run", "blocking": True, "message": "late", "request_id": None}],
            cost={"baseline_mean_cents": 35.0, "current_mean_cents": 40.0},
        ),
        workflow_run_url="https://github.com/o/r/actions/runs/1",
    )
    record = await db_session.get_one(EvalRunRecord, first.id)
    await db_session.refresh(record)
    assert record.comparison is not None
    assert record.comparison["status"] == "blocked"
    assert record.summary["compare_status"] == "blocked"
    # What the new comparison brings (its baseline, its blocking findings) joins the summary.
    assert record.summary["reference_cost_per_plan_cents"] == 35.0
    assert [finding["message"] for finding in record.summary["blocking_findings"]] == ["late"]
    assert record.summary["requests_total"] == 1  # the rest of the summary is kept
    assert record.workflow_run_url == "https://github.com/o/r/actions/runs/1"

    await evals_store.store_eval_run(db_session, results=results)  # a retry without them
    await db_session.refresh(record)
    assert record.summary["compare_status"] == "blocked"
    assert record.workflow_run_url == "https://github.com/o/r/actions/runs/1"

    await evals_store.store_eval_run(
        db_session,
        results=results,
        comparison=comparison(status="passed"),
        workflow_run_url="https://github.com/o/r/actions/runs/2",
    )
    await db_session.refresh(record)
    assert record.summary["compare_status"] == "passed"
    assert record.workflow_run_url == "https://github.com/o/r/actions/runs/2"
    assert await count(db_session) == 1


async def test_a_repeat_keeps_the_stored_results(db_session: AsyncSession) -> None:
    first = await evals_store.store_eval_run(db_session, results=make_results(requests=[entry()]))

    await evals_store.store_eval_run(db_session, results=make_results(requests=[]))

    record = await db_session.get_one(EvalRunRecord, first.id)
    await db_session.refresh(record)
    assert len(record.results["requests"]) == 1


async def test_other_start_sha_or_profile_is_another_run(db_session: AsyncSession) -> None:
    await evals_store.store_eval_run(db_session, results=make_results())
    await evals_store.store_eval_run(
        db_session, results=make_results(started_at="2026-10-13T09:00:01+02:00")
    )
    await evals_store.store_eval_run(db_session, results=make_results(git_sha="def456"))
    await evals_store.store_eval_run(db_session, results=make_results(profile="production"))
    await evals_store.store_eval_run(db_session, results=make_results(git_sha=None))

    assert await count(db_session) == 5


async def test_concurrent_uploads_of_one_run_store_it_once(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async def upload() -> evals_store.StoredEvalRun:
        async with db_session_factory() as session:
            return await evals_store.store_eval_run(session, results=make_results())

    stored = await asyncio.gather(*(upload() for _ in range(5)))

    assert len({s.id for s in stored}) == 1
    assert sum(1 for s in stored if s.created) == 1
    async with db_session_factory() as session:
        assert await count(session) == 1


async def test_invalid_documents_store_nothing(db_session: AsyncSession) -> None:
    with pytest.raises(InvalidEvalResultsError):
        await evals_store.store_eval_run(db_session, results=make_results(kind="nope"))
    with pytest.raises(InvalidEvalResultsError):
        await evals_store.store_eval_run(
            db_session, results=make_results(), comparison={"kind": "nope"}
        )
    with pytest.raises(InvalidEvalResultsError):
        await evals_store.store_eval_run(
            db_session, results=make_results(), workflow_run_url="javascript:alert(1)"
        )

    assert await count(db_session) == 0


async def test_nul_characters_are_stripped_before_postgres_sees_them(
    db_session: AsyncSession,
) -> None:
    results = make_results(requests=[entry(title="Lisbon\x00 trip")], note="a\x00b")

    stored = await evals_store.store_eval_run(db_session, results=results)

    record = await db_session.get_one(EvalRunRecord, stored.id)
    assert record.results["note"] == "ab"
    assert record.results["requests"][0]["title"] == "Lisbon trip"


async def test_store_does_not_mutate_its_input(db_session: AsyncSession) -> None:
    results = make_results(requests=[entry(title="x\x00")])
    before = copy.deepcopy(results)

    await evals_store.store_eval_run(db_session, results=results)

    assert results == before


# --- reading -------------------------------------------------------------------------------------


async def test_list_is_newest_first_and_limited(db_session: AsyncSession) -> None:
    for day in (11, 13, 12):
        await evals_store.store_eval_run(
            db_session, results=make_results(started_at=f"2026-10-{day}T09:00:00+02:00")
        )

    runs = await evals_store.list_eval_runs(db_session)
    assert [run.started_at.day for run in runs] == [13, 12, 11]

    limited = await evals_store.list_eval_runs(db_session, limit=2)
    assert [run.started_at.day for run in limited] == [13, 12]


async def test_list_skips_offset_runs_and_counts_them_all(db_session: AsyncSession) -> None:
    for day in (11, 13, 12, 14):
        await evals_store.store_eval_run(
            db_session, results=make_results(started_at=f"2026-10-{day}T09:00:00+02:00")
        )

    page = await evals_store.list_eval_runs(db_session, limit=2, offset=2)
    assert [run.started_at.day for run in page] == [12, 11]
    assert await evals_store.list_eval_runs(db_session, limit=2, offset=4) == []
    assert await evals_store.count_eval_runs(db_session) == 4


async def test_list_items_carry_the_contract_fields(db_session: AsyncSession) -> None:
    stored = await evals_store.store_eval_run(
        db_session,
        results=real_results(),
        comparison=comparison(status="blocked", blocked=True),
        workflow_run_url="https://github.com/o/r/actions/runs/9",
    )

    [run] = await evals_store.list_eval_runs(db_session)

    assert run.model_dump(mode="json") == {
        "id": str(stored.id),
        "started_at": "2026-10-12T20:49:40.848706Z",
        "finished_at": "2026-10-12T20:52:22.043410Z",
        "git_sha": "5d22125b035243839e5ce2ece301861aaf5e4977",
        "profile": "development",
        "aborted": False,
        "requests_total": 5,
        "requests_accepted": 0,
        "checks_passed": 0,
        "blocking_failures_count": 10,
        "total_cost_cents": 309,
        "web_search_requests": 59,
        "judge_mean": None,
        "compare_status": "blocked",
        "reference_judge_mean": None,
        "reference_cost_per_plan_cents": None,
        "blocking_findings": [],
        "workflow_run_url": "https://github.com/o/r/actions/runs/9",
    }


async def test_get_returns_the_stored_documents(db_session: AsyncSession) -> None:
    stored = await evals_store.store_eval_run(
        db_session, results=real_results(), comparison=comparison()
    )

    run = await evals_store.get_eval_run(db_session, stored.id)

    assert run is not None
    assert run.results == real_results()
    assert run.comparison == comparison()
    assert run.requests_total == 5
    assert await evals_store.get_eval_run(db_session, uuid.uuid4()) is None


async def test_get_gives_the_runs_before_and_after_in_the_list_order(
    db_session: AsyncSession,
) -> None:
    stored = {
        day: await evals_store.store_eval_run(
            db_session, results=make_results(started_at=f"2026-10-{day}T09:00:00+02:00")
        )
        for day in (11, 13, 12)
    }

    middle = await evals_store.get_eval_run(db_session, stored[12].id)
    newest = await evals_store.get_eval_run(db_session, stored[13].id)
    oldest = await evals_store.get_eval_run(db_session, stored[11].id)

    assert middle is not None
    assert newest is not None
    assert oldest is not None
    assert middle.previous_run is not None
    assert middle.previous_run.id == stored[11].id
    assert middle.next_run is not None
    assert middle.next_run.id == stored[13].id
    assert newest.next_run is None
    assert oldest.previous_run is None
    assert oldest.next_run is not None
    assert oldest.next_run.started_at.day == 12
