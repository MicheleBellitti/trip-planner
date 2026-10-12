"""app.cli: argument parsing, rendering, the guards of `run`, and an offline `replay`.

`run` is never executed past its guards here (it would start a real, paid session). `replay`
runs the whole start path offline: the fake client, the real consumer and hub, Postgres.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app import cli
from app.config import Settings
from app.db import EvalRunRecord, EventRecord, PlanRecord, PlanStatus
from app.events import AgentName, EventKind, UIEvent
from app.request import PlanRequest
from tests.test_jobs import uncached_structlog  # noqa: F401 (fixture)

MA_FIXTURES = Path(__file__).parent / "fixtures" / "ma"


def event(**overrides: Any) -> UIEvent:
    values: dict[str, Any] = {
        "seq": 3,
        "ts": dt.datetime(2026, 10, 12, 13, 4, 5, tzinfo=dt.UTC),  # 15:04:05 in Rome
        "agent": AgentName.FLIGHTS,
        "kind": EventKind.TOOL,
        "title": "Expedia · voli MXP→LIS · 14–18 nov",
        "detail": {"text": "never printed"},
        "cost_cents": 37,
    }
    values.update(overrides)
    return UIEvent.model_validate(values)


# --- parsing and loading -------------------------------------------------------------------------


def test_parser_commands() -> None:
    parser = cli.build_parser()
    run = parser.parse_args(["run", "--request", "r.json", "--yes", "--allow-production"])
    assert (run.command, run.request, run.yes, run.allow_production) == (
        "run",
        Path("r.json"),
        True,
        True,
    )
    assert run.no_color is False
    replay = parser.parse_args(["replay", "s.jsonl", "--no-color", "--out", "/tmp/x"])
    assert (replay.command, replay.fixture, replay.request, replay.no_color) == (
        "replay",
        Path("s.jsonl"),
        None,
        True,
    )
    assert replay.out == Path("/tmp/x")
    with pytest.raises(SystemExit) as caught:
        parser.parse_args(["run"])  # --request is required
    assert caught.value.code == cli.EXIT_USAGE


def test_load_request(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = tmp_path / "request.json"
    path.write_text(json.dumps(cli.DEFAULT_REPLAY_REQUEST), encoding="utf-8")
    assert cli.load_request(path, allow_past_dates=True) == PlanRequest.from_stored(
        cli.DEFAULT_REPLAY_REQUEST
    )

    past = {
        **cli.DEFAULT_REPLAY_REQUEST,
        "dates": {"exact_start": "2025-01-10", "exact_end": "2025-01-12"},
    }
    path.write_text(json.dumps(past), encoding="utf-8")
    assert cli.load_request(path, allow_past_dates=True).dates.exact_start == dt.date(2025, 1, 10)
    with pytest.raises(SystemExit) as caught:
        cli.load_request(path)  # a real run needs future dates
    assert caught.value.code == cli.EXIT_USAGE
    assert "Richiesta non valida" in capsys.readouterr().err

    path.write_text("{oops", encoding="utf-8")
    with pytest.raises(SystemExit):
        cli.load_request(path)
    with pytest.raises(SystemExit):
        cli.load_request(tmp_path / "missing.json")
    assert "Traceback" not in capsys.readouterr().err


# --- rendering -----------------------------------------------------------------------------------


def test_render_event_matches_the_documented_line() -> None:
    assert cli.render_event(event(), color=False) == (
        "15:04:05  flights     tool     Expedia · voli MXP→LIS · 14–18 nov   0,37 $"
    )


def test_render_event_without_cost_and_in_color() -> None:
    plain = cli.render_event(event(cost_cents=None, agent=AgentName.COORDINATOR), color=False)
    assert plain == "15:04:05  coordinator  tool     Expedia · voli MXP→LIS · 14–18 nov"
    colored = cli.render_event(event(kind=EventKind.ERROR), color=True)
    assert "\033[36mflights   \033[0m" in colored  # the lane's color
    assert "\033[31merror   \033[0m" in colored
    assert "never printed" not in colored


def test_render_summary_and_trip() -> None:
    summary = cli.render_summary(
        PlanStatus.READY, cost_cents=41, trip_path=Path("/tmp/trip-1.json")
    )
    assert summary.splitlines() == [
        "Stato finale: ready (pronto)",
        "Costo: 0,41 $",
        "Trip salvato in /tmp/trip-1.json",
    ]
    assert cli.render_summary(PlanStatus.BUDGET_PAUSED, cost_cents=61, trip_path=None).splitlines()[
        0
    ] == ("Stato finale: budget_paused (in pausa: budget raggiunto)")
    trip = {
        "title": "Lisbona, novembre",
        "destinationName": "Lisbona, Portogallo",
        "startDate": "2026-11-14",
        "endDate": "2026-11-19",
        "days": [{}] * 6,
        "bookings": [{}] * 8,
    }
    assert cli.render_trip_summary(trip) == (
        "Viaggio: Lisbona, novembre · Lisbona, Portogallo · 2026-11-14 → 2026-11-19 · "
        "6 giorni · 8 prenotazioni"
    )


# --- run: the guards before any money is spent ---------------------------------------------------


async def test_run_refuses_production_without_the_flag(
    make_settings: Callable[..., Settings], tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    settings = make_settings(agent_profile="production", anthropic_api_key="sk-test-not-real")
    code = await cli.run_command(
        tmp_path / "r.json", settings=settings, yes=True, allow_production=False, color=False
    )
    assert code == cli.EXIT_USAGE
    assert "--allow-production" in capsys.readouterr().err


async def test_run_refuses_demo_mode(
    make_settings: Callable[..., Settings], tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """DEMO_MODE's planner replays scripts: `run` (a real session) is refused, not faked."""
    settings = make_settings(demo_mode=True, anthropic_api_key="sk-test-not-real")
    code = await cli.run_command(
        tmp_path / "r.json", settings=settings, yes=True, allow_production=False, color=False
    )
    assert code == cli.EXIT_USAGE
    assert "DEMO_MODE" in capsys.readouterr().err


async def test_replay_ignores_demo_mode(
    make_settings: Callable[..., Settings],
    db_session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    """`replay` drives its own fake at full speed with the fixture lockfile, DEMO_MODE or not."""
    code = await cli.replay_command(
        MA_FIXTURES / "happy_path.jsonl",
        settings=make_settings(demo_mode=True),
        request_path=None,
        color=False,
        out_dir=tmp_path,
    )
    assert code == cli.EXIT_READY
    async with db_session_factory() as db:
        [plan] = list(await db.scalars(select(PlanRecord)))
    assert plan.agent_versions is not None
    assert plan.agent_versions["coordinator"]["id"] == "agent_devcoordinator01"  # fixture lock


async def test_run_refuses_without_a_key(
    make_settings: Callable[..., Settings], tmp_path: Path
) -> None:
    code = await cli.run_command(
        tmp_path / "r.json", settings=make_settings(), yes=True, allow_production=False, color=False
    )
    assert code == cli.EXIT_USAGE


async def test_run_needs_yes_without_a_terminal(
    make_settings: Callable[..., Settings],
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = {
        **cli.DEFAULT_REPLAY_REQUEST,
        "dates": {"exact_start": "2027-04-14", "exact_end": "2027-04-18"},
    }
    path = tmp_path / "request.json"
    path.write_text(json.dumps(request), encoding="utf-8")
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    settings = make_settings(anthropic_api_key="sk-test-not-real")
    code = await cli.run_command(
        path, settings=settings, yes=False, allow_production=False, color=False
    )
    assert code == cli.EXIT_USAGE
    captured = capsys.readouterr()
    assert "budget 0,60 $" in captured.out
    assert "--yes" in captured.err


# --- replay --------------------------------------------------------------------------------------


async def test_replay_happy_path_ends_with_a_ready_plan(
    make_settings: Callable[..., Settings],
    db_session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    code = await cli.replay_command(
        MA_FIXTURES / "happy_path.jsonl",
        settings=make_settings(),
        request_path=None,
        color=False,
        out_dir=tmp_path,
    )
    captured = capsys.readouterr()
    assert code == cli.EXIT_READY, captured.err

    async with db_session_factory() as db:
        [plan] = list(await db.scalars(select(PlanRecord)))
        stored_events = int(
            await db.scalar(
                select(func.count()).select_from(EventRecord).where(EventRecord.plan_id == plan.id)
            )
            or 0
        )
    assert plan.status == PlanStatus.READY
    assert plan.session_id == "sesn_fake_0001"
    assert plan.agent_versions is not None
    assert plan.agent_versions["coordinator"]["id"] == "agent_devcoordinator01"  # fixture lock

    lines = captured.out.splitlines()
    assert lines[0].startswith(f"Piano {plan.id} · profilo development · budget 0,60 $")
    timeline = [line for line in lines[1:] if line[:2].isdigit() and line[2] == ":"]
    assert len(timeline) == stored_events  # every event printed exactly once
    assert "coordinator  status   Piano avviato" in timeline[0]
    assert any("Piano accettato" in line for line in timeline)
    for lane in ("flights", "lodging", "activities", "transport"):
        assert any(line[10:].startswith(f"{lane} ") for line in timeline), lane
    assert any(line.endswith("   0,41 $") for line in timeline)

    trip_path = tmp_path / f"trip-{plan.id}.json"
    assert json.loads(trip_path.read_text(encoding="utf-8")) == plan.trip
    assert lines[-4].startswith("Viaggio: ")
    assert lines[-3:] == [
        "Stato finale: ready (pronto)",
        f"Costo: {plan.cost_cents // 100},{plan.cost_cents % 100:02d} $",
        f"Trip salvato in {trip_path}",
    ]


async def test_a_scenario_can_be_replayed_again_into_the_same_database(
    make_settings: Callable[..., Settings],
    db_session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """`events.ma_event_id` is unique across the database: the scenario's fixed event ids would
    make a second replay store nothing and stall, so every run namespaces them."""
    for _ in range(2):
        code = await cli.replay_command(
            MA_FIXTURES / "happy_path.jsonl",
            settings=make_settings(),
            request_path=None,
            color=False,
            out_dir=tmp_path,
        )
        assert code == cli.EXIT_READY, capsys.readouterr().err

    async with db_session_factory() as db:
        plans = list(await db.scalars(select(PlanRecord)))
        counts = [
            int(
                await db.scalar(
                    select(func.count())
                    .select_from(EventRecord)
                    .where(EventRecord.plan_id == plan.id)
                )
                or 0
            )
            for plan in plans
        ]
    assert [plan.status for plan in plans] == [PlanStatus.READY, PlanStatus.READY]
    assert counts[0] == counts[1] > 10


async def test_replay_of_a_paused_plan_exits_not_ready(
    make_settings: Callable[..., Settings],
    db_session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    code = await cli.replay_command(
        MA_FIXTURES / "budget_reached.jsonl",
        settings=make_settings(),
        request_path=None,
        color=False,
        out_dir=tmp_path,
    )
    assert code == cli.EXIT_NOT_READY
    assert "Stato finale: budget_paused" in capsys.readouterr().out
    async with db_session_factory() as db:
        [plan] = list(await db.scalars(select(PlanRecord)))
    assert plan.status == PlanStatus.BUDGET_PAUSED
    assert await asyncio.to_thread(lambda: list(tmp_path.iterdir())) == []  # no Trip


async def test_replay_refuses_production(
    make_settings: Callable[..., Settings], capsys: pytest.CaptureFixture[str]
) -> None:
    settings = make_settings(
        environment="production", auth_mode="triptracker", anthropic_api_key="sk-test-not-real"
    )
    code = await cli.replay_command(
        MA_FIXTURES / "happy_path.jsonl", settings=settings, request_path=None, color=False
    )
    assert code == cli.EXIT_USAGE
    assert "ENVIRONMENT=development" in capsys.readouterr().err


async def test_replay_of_a_missing_scenario(
    make_settings: Callable[..., Settings], tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = await cli.replay_command(
        tmp_path / "nope.jsonl", settings=make_settings(), request_path=None, color=False
    )
    assert code == cli.EXIT_USAGE
    assert "Scenario non trovato" in capsys.readouterr().err


@pytest.mark.usefixtures("uncached_structlog")
def test_main_replay_usage_error(settings: Settings, tmp_path: Path) -> None:
    assert cli.main(["replay", str(tmp_path / "nope.jsonl"), "--no-color"]) == cli.EXIT_USAGE


# --- import-evals -------------------------------------------------------------------------------

EVAL_RESULTS = MA_FIXTURES.parent / "evals" / "2026-10-12-5d22125b0352.json"


def test_parser_import_evals() -> None:
    parser = cli.build_parser()
    minimal = parser.parse_args(["import-evals", "r.json"])
    assert (minimal.command, minimal.results, minimal.comparison, minimal.workflow_run_url) == (
        "import-evals",
        Path("r.json"),
        None,
        None,
    )
    full = parser.parse_args(
        ["import-evals", "r.json", "--comparison", "c.json", "--workflow-run-url", "https://x/1"]
    )
    assert (full.comparison, full.workflow_run_url) == (Path("c.json"), "https://x/1")


async def test_import_evals_stores_the_run_and_a_repeat_is_harmless(
    settings: Settings,
    db_session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    comparison_path = tmp_path / "comparison.json"
    comparison_path.write_text(json.dumps({"status": "report_only"}), encoding="utf-8")

    async def run() -> int:
        return await cli.import_evals_command(
            EVAL_RESULTS,
            settings=settings,
            comparison_path=comparison_path,
            workflow_run_url="https://github.com/o/r/actions/runs/1",
        )

    assert await run() == cli.EXIT_READY
    assert "Importata: esecuzione " in capsys.readouterr().out
    assert await run() == cli.EXIT_READY
    assert "Già presente: esecuzione " in capsys.readouterr().out

    async with db_session_factory() as db:
        [record] = (await db.scalars(select(EvalRunRecord))).all()
    assert record.summary["compare_status"] == "report_only"
    assert record.summary["requests_total"] == 5
    assert record.workflow_run_url == "https://github.com/o/r/actions/runs/1"


@pytest.mark.parametrize(
    ("content", "message"),
    [
        (None, "Impossibile leggere"),
        ("{", "non è JSON valido"),
        ("[1]", "deve essere un oggetto JSON"),
        ('{"kind": "other"}', "non validi"),
    ],
)
async def test_import_evals_usage_errors(
    settings: Settings,
    db_session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    content: str | None,
    message: str,
) -> None:
    path = tmp_path / "results.json"
    if content is not None:
        path.write_text(content, encoding="utf-8")

    code = await cli.import_evals_command(
        path, settings=settings, comparison_path=None, workflow_run_url=None
    )

    assert code == cli.EXIT_USAGE
    assert message in capsys.readouterr().err
    async with db_session_factory() as db:
        assert await db.scalar(select(func.count()).select_from(EvalRunRecord)) == 0


@pytest.mark.usefixtures("uncached_structlog")
def test_main_import_evals_usage_error(settings: Settings, tmp_path: Path) -> None:
    assert cli.main(["import-evals", str(tmp_path / "nope.json")]) == cli.EXIT_USAGE
