"""evals/run.py offline: arguments and guards, selection, file names, the per-plan
orchestration against faked backend functions, and the results document compare.py reads.
Nothing here starts a session, opens Postgres or calls the Anthropic API."""

from __future__ import annotations

import asyncio
import datetime as dt
import json
import sys
import uuid
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import compare
import judge
import run
from app import sessions

FIXTURES = Path(__file__).resolve().parent / "fixtures"
DATASET = run.load_dataset(run_date=dt.date(2027, 10, 1))  # Lisbon on the fixtures' dates
LISBON = next(case for case in DATASET.cases if case.id == "city-weekend-lisbon")


def fixture(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


# --- guards -------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("explicit", "configured", "expected"),
    [
        (None, None, "development"),
        (None, "development", "development"),
        ("development", "production", "development"),
        ("production", "development", "production"),
        ("production", None, "production"),
    ],
)
def test_resolve_profile(explicit: str | None, configured: str | None, expected: str) -> None:
    assert run.resolve_profile(explicit, configured) == expected


def test_production_is_refused_unless_explicit() -> None:
    with pytest.raises(run.UsageError, match="--profile production"):
        run.resolve_profile(None, "production")


def test_main_refuses_a_configured_production_profile(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.setenv("AGENT_PROFILE", "production")
    monkeypatch.setenv("DATABASE_URL", "postgresql://localhost:5432/trip_planner")
    monkeypatch.setattr(run, "prepare_database", _forbidden("database"))
    assert run.main(["--yes"]) == run.EXIT_USAGE
    assert "--profile production" in capsys.readouterr().err


def test_main_needs_a_real_key_before_anything_is_spent(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.setenv("AGENT_PROFILE", "development")
    monkeypatch.setenv("DATABASE_URL", "postgresql://localhost:5432/trip_planner")
    monkeypatch.setattr(run, "prepare_database", _forbidden("database"))
    assert run.main(["--yes", "--profile", "production"]) == run.EXIT_USAGE
    assert "ANTHROPIC_API_KEY" in capsys.readouterr().err


def test_confirmation_is_required_without_a_terminal(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    with pytest.raises(run.UsageError, match="--yes"):
        run.confirm("spend?", yes=False)
    assert run.confirm("spend?", yes=True)


def test_judge_cap_cannot_exceed_one_dollar(capsys: pytest.CaptureFixture[str]) -> None:
    assert run.main(["--dry-run", "--judge-cap-cents", "150"]) == run.EXIT_USAGE
    assert "at most 100" in capsys.readouterr().err


def _forbidden(what: str) -> Callable[..., Any]:
    def fail(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError(f"{what} must not be touched")

    return fail


# --- selection and dry run ----------------------------------------------------------------------


def test_select_by_tags_matches_any_tag() -> None:
    selected = run.select_cases(DATASET.cases, tags=["train", "sea"])
    assert [case.id for case in selected] == ["sea-week-family", "train-trip-florence"]


def test_select_by_ids_and_tags() -> None:
    selected = run.select_cases(DATASET.cases, tags=["flights"], ids=["flexible-dates-budapest"])
    assert [case.id for case in selected] == ["flexible-dates-budapest"]


def test_select_errors() -> None:
    with pytest.raises(run.UsageError, match="unknown request id"):
        run.select_cases(DATASET.cases, ids=["nope"])
    with pytest.raises(run.UsageError, match="no request matches"):
        run.select_cases(DATASET.cases, tags=["no-such-tag"])


def test_dry_run_spends_nothing(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(run, "prepare_database", _forbidden("database"))
    monkeypatch.setattr(run, "execute", _forbidden("execution"))
    assert run.main(["--dry-run", "--tags", "train"]) == run.EXIT_OK
    out = capsys.readouterr().out
    assert "1 request(s), profile development, ceiling 2.00 $" in out
    assert "train-trip-florence" in out


def test_dry_run_resolves_the_dates_for_the_run_date(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from app import clock

    day = dt.date(2026, 10, 13)
    monkeypatch.setattr(
        clock, "now", lambda: dt.datetime.combine(day, dt.time(12), tzinfo=clock.HOME_TIMEZONE)
    )
    assert run.main(["--dry-run", "--run-date", "2026-10-13"]) == run.EXIT_OK
    out = capsys.readouterr().out
    assert "run date 2026-10-13" in out
    assert "city-weekend-lisbon" in out
    assert "2026-11-27 -> 2026-11-29" in out  # Fri to Sun, 6 weeks ahead
    assert "2026-12, 4 nights" in out


def test_run_date_must_be_a_date(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as stop:
        run.main(["--dry-run", "--run-date", "13/10/2026"])
    assert stop.value.code == 2
    assert "YYYY-MM-DD" in capsys.readouterr().err


def test_a_run_date_in_the_past_is_refused(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from app import clock

    monkeypatch.setattr(
        clock, "now", lambda: dt.datetime(2026, 10, 13, 12, tzinfo=clock.HOME_TIMEZONE)
    )
    assert run.main(["--dry-run", "--run-date", "2026-01-05"]) == run.EXIT_USAGE
    assert "run date" in capsys.readouterr().err


def test_spending_ceiling() -> None:
    assert run.spending_ceiling_cents(6, "development", judge_cap_cents=100) == 700
    assert run.spending_ceiling_cents(6, "production", judge_cap_cents=100) == 2500


# --- database and files -------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        (
            "postgres://u:p@db.example:5432/trip_planner",
            "postgresql+asyncpg://u:p@db.example:5432/trip_planner_evals",
        ),
        (
            "postgresql+asyncpg://localhost:5432/trip_planner_evals",
            "postgresql+asyncpg://localhost:5432/trip_planner_evals",
        ),
    ],
)
def test_eval_database_url(source: str, expected: str) -> None:
    assert run.eval_database_url(source) == expected


def test_eval_database_url_needs_a_name() -> None:
    with pytest.raises(run.UsageError):
        run.eval_database_url("postgresql://localhost:5432")


def test_results_path_never_overwrites(tmp_path: Path) -> None:
    day = dt.date(2026, 10, 13)
    first = run.results_path(tmp_path, date=day, git_sha="1a2b3c4d5e6f7a8b9c0d")
    assert first.name == "2026-10-13-1a2b3c4d5e6f.json"
    first.write_text("{}")
    assert run.results_path(tmp_path, date=day, git_sha="1a2b3c4d5e6f7a8b9c0d").name == (
        "2026-10-13-1a2b3c4d5e6f-2.json"
    )
    assert run.results_path(tmp_path, date=day, git_sha=None).name == "2026-10-13-nogit.json"


# --- one plan, against faked backend functions --------------------------------------------------


def plan_row(status: str, **overrides: Any) -> SimpleNamespace:
    values: dict[str, Any] = {
        "id": uuid.UUID("00000000-0000-4000-8000-000000000001"),
        "session_id": "sesn_eval",
        "status": status,
        "failure_reason": None,
        "submit_attempts": 1,
        "cost_cents": 38,
        "plan": fixture("plan_lisbon_ok.json") if status == "ready" else None,
        "trip": fixture("trip_lisbon_ok.json") if status == "ready" else None,
        "agent_versions": {
            "profile": "development",
            "coordinator": {"id": "agent_x", "version": 3},
        },
    }
    values.update(overrides)
    return SimpleNamespace(**values)


class FakeMaClient:
    def __init__(self) -> None:
        self.retrieved: list[str] = []

    async def retrieve_session(self, session_id: str) -> Any:
        self.retrieved.append(session_id)
        return SimpleNamespace(
            usage=SimpleNamespace(
                list_cost_cents=41,
                input_tokens=900_000,
                output_tokens=40_000,
                cache_read_input_tokens=500_000,
                web_search_requests=12,
                active_seconds=600.0,
            )
        )


class FakeJudgeMessages:
    def __init__(self) -> None:
        self.calls = 0

    async def count_tokens(self, **kwargs: Any) -> Any:
        return SimpleNamespace(input_tokens=12_000)

    async def create(self, **kwargs: Any) -> Any:
        self.calls += 1
        text = json.dumps({c: {"reason": "ok", "score": 4} for c in judge.CRITERIA})
        return SimpleNamespace(
            content=[SimpleNamespace(type="text", text=text)],
            stop_reason="end_turn",
            usage=SimpleNamespace(input_tokens=12_000, output_tokens=2_000),
        )


def context(
    monkeypatch: pytest.MonkeyPatch,
    rows: list[SimpleNamespace | None],
    *,
    start: Callable[..., Any] | None = None,
) -> tuple[run.RunContext, dict[str, Any]]:
    calls: dict[str, Any] = {"interrupted": [], "started": []}
    plan_id = uuid.UUID("00000000-0000-4000-8000-000000000001")

    async def fake_start(
        request: Any, user: Any, *, services: Any, user_quota_applies: bool = True
    ) -> uuid.UUID:
        calls["started"].append(user.email)
        calls.setdefault("user_quota_applies", []).append(user_quota_applies)
        return plan_id

    async def fake_interrupt(pid: uuid.UUID, user: Any, *, services: Any) -> Any:
        calls["interrupted"].append(pid)
        return "running"

    async def fake_load(factory: Any, pid: uuid.UUID) -> Any:
        return rows.pop(0) if len(rows) > 1 else rows[0]

    monkeypatch.setattr(sessions, "start_plan", start or fake_start)
    monkeypatch.setattr(sessions, "interrupt_plan", fake_interrupt)
    monkeypatch.setattr(run, "load_plan", fake_load)
    ma_client = FakeMaClient()
    planner = SimpleNamespace(
        settings=SimpleNamespace(local_user_email=None),
        session_factory=object(),
        client=ma_client,
    )
    judge_messages = FakeJudgeMessages()
    ctx = run.RunContext(
        planner=planner,  # pyright: ignore[reportArgumentType]
        profile="development",
        today=dt.date(2026, 10, 12),
        timeout_seconds=0.05,
        judge_client=SimpleNamespace(messages=judge_messages),  # pyright: ignore[reportArgumentType]
        judge_budget=judge.JudgeBudget(),
        rubric="rubric",
        poll_seconds=0.0,
        interrupt_grace_seconds=0.0,
    )
    calls["ma_client"] = ma_client
    calls["judge"] = judge_messages
    return ctx, calls


def request_for(case: run.EvalCase) -> Any:
    from app.request import PlanRequest

    return PlanRequest.from_stored(case.request)


def test_run_case_ready_plan(monkeypatch: pytest.MonkeyPatch) -> None:
    ctx, calls = context(monkeypatch, [plan_row("running"), plan_row("ready")])
    entry = asyncio.run(run.run_case(LISBON, request_for(LISBON), ctx))
    assert calls["started"] == [run.EVAL_USER_EMAIL]
    assert calls["user_quota_applies"] == [False]  # the eval user is exempt from the user quota
    assert calls["interrupted"] == []
    assert calls["ma_client"].retrieved == ["sesn_eval"]
    assert entry["status"] == "ready"
    assert entry["timed_out"] is False
    assert entry["cost_cents"] == 41
    assert entry["cost_source"] == "session_usage"
    assert entry["web_search_requests"] == 12
    assert entry["checks_passed"], entry["checks"]
    assert entry["judge"]["status"] == "ok"
    assert entry["agent_versions"]["coordinator"]["version"] == 3
    assert entry["warnings_count"] == 1
    json.dumps(entry)


def test_run_case_timeout_interrupts_the_plan(monkeypatch: pytest.MonkeyPatch) -> None:
    ctx, calls = context(monkeypatch, [plan_row("running", submit_attempts=0)])
    entry = asyncio.run(run.run_case(LISBON, request_for(LISBON), ctx))
    assert calls["interrupted"] == [uuid.UUID("00000000-0000-4000-8000-000000000001")]
    assert entry["timed_out"] is True
    assert entry["status"] == "running"
    assert not entry["checks_passed"]
    assert entry["judge"]["status"] == "skipped"
    assert calls["judge"].calls == 0


def test_run_case_start_failure_is_recorded(monkeypatch: pytest.MonkeyPatch) -> None:
    async def refused(request: Any, user: Any, **kwargs: Any) -> uuid.UUID:
        raise sessions.MonthlyLimitReachedError(5000, 5000)

    ctx, calls = context(monkeypatch, [None], start=refused)
    entry = asyncio.run(run.run_case(LISBON, request_for(LISBON), ctx))
    assert entry["error"].startswith("MonthlyLimitReachedError")
    assert entry["status"] is None
    assert "schema_valid" in entry["blocking_failures"]
    assert calls["ma_client"].retrieved == []


def test_cost_falls_back_to_the_plan_row_when_usage_has_no_list_cost() -> None:
    row = run.record_fields(plan_row("ready", cost_cents=37))  # pyright: ignore[reportArgumentType]
    usage = SimpleNamespace(list_cost_cents=None, web_search_requests=None)
    entry = run.build_entry(
        LISBON,
        request_for(LISBON),
        record=row,
        usage=usage,
        profile="development",
        judge_result=judge.JudgeResult(status="skipped"),
        extra={},
    )
    assert entry["cost_cents"] == 37
    assert entry["cost_source"] == "plans.cost_cents"
    statuses = {check["name"]: check["status"] for check in entry["checks"]}
    assert statuses["cost_and_searches_vs_estimate"] == "warn"  # searches unknown


# --- the results document -----------------------------------------------------------------------


def test_results_document_is_what_compare_reads(monkeypatch: pytest.MonkeyPatch) -> None:
    ctx, _ = context(monkeypatch, [plan_row("ready")])
    entry = asyncio.run(run.run_case(LISBON, request_for(LISBON), ctx))
    started = dt.datetime(2026, 10, 13, 9, 0, tzinfo=dt.UTC)
    document = run.results_document(
        entries=[entry],
        profile="development",
        git_sha="1a2b3c4d5e6f7a8b",
        started_at=started,
        finished_at=started + dt.timedelta(minutes=14),
        dataset=DATASET,
        selected=[LISBON],
        tags=["smoke"],
        agent_versions={"profile": "development"},
        judge_budget=ctx.judge_budget,
        judge_enabled=True,
        aborted=False,
    )
    json.dumps(document)
    assert compare.is_results(document)
    assert document["date"] == "2026-10-13"
    assert document["dataset"]["run_date"] == "2027-10-01"
    assert document["dataset"]["resolved_dates"] == {
        "city-weekend-lisbon": {"exact_start": "2027-11-12", "exact_end": "2027-11-14"}
    }
    assert document["dataset"]["selected"] == ["city-weekend-lisbon"]
    summary = document["summary"]
    assert summary["valid"] == 1
    assert summary["mean_cost_cents"] == 41
    assert summary["judge_means"]["time_coherence"] == 4
    assert document["judge"]["spent_cents"] > 0
    comparison = compare.compare(document, compare.baseline_from_results(document))
    assert not comparison.blocked
    assert compare.compare(document, None).report_only


def test_summarize_counts() -> None:
    entries = [
        {"status": "ready", "checks_passed": True, "cost_cents": 40, "warnings_count": 2},
        {
            "status": "failed",
            "checks_passed": False,
            "cost_cents": None,
            "blocking_failures": ["a"],
        },
    ]
    summary = run.summarize(entries)
    assert summary["plans"] == 2
    assert summary["ready"] == 1
    assert summary["valid"] == 1
    assert summary["mean_cost_cents"] == 40
    assert summary["cost_known"] == 1
    assert summary["blocking_failures"] == 1
    assert summary["warnings"] == 2
    assert summary["judge_means"]["summary_clarity"] is None
