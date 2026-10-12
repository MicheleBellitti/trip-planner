"""Every log line carries `plan_id`, `session_id`, `agent` and `event_type` (CLAUDE.md, spec "Log
e resilienza"): the consumer, the lifecycle (sessions) and the jobs bind them in
`structlog.contextvars`, so lines written on a plan's behalf by code that knows nothing of the
plan (ma_client, fx, a fake standing in for them here) carry them too.

`client_calls` records, at every Managed Agents call the fake receives, the contextvars bound at
that moment, and writes one line from a logger of its own ("a foreign module"); `plan_logs`
captures lines with `structlog.testing.capture_logs` through the same processors as
main.configure_logging (`merge_contextvars`, then `add_plan_log_keys`).
"""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

import pytest
import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from structlog.typing import EventDict

from app import cli, jobs, sessions
from app import consumer as consumer_module
from app.config import PLAN_LOG_KEYS, Settings, add_plan_log_keys
from app.db import PlanStatus
from app.events import AgentName
from tests.fakes import FakeManagedAgentsClient, RecordedCall
from tests.test_consumer import SID, HarnessFactory, harness  # noqa: F401 (fixture)
from tests.test_e2e_offline import (  # noqa: F401 (fixtures)
    OpenBrowser,
    e2e_settings,
    frozen_clock,
    open_browser,
    scenario,
    triptracker_edge,
)
from tests.test_jobs import OLD, uncached_structlog, workspace_session  # noqa: F401 (fixture)
from tests.test_sessions import (
    FROZEN_NOW,
    insert_plan,
    open_planner,
    planner_settings,
)

FOREIGN_LOGGER = "tests.foreign_module"
SUBAGENTS = {name.value for name in AgentName if name is not AgentName.COORDINATOR}


@dataclass(frozen=True, slots=True)
class ClientCall:
    method: str
    session_id: str | None
    context: dict[str, Any]


@pytest.fixture
def client_calls(monkeypatch: pytest.MonkeyPatch) -> list[ClientCall]:
    """Every `FakeManagedAgentsClient` call of the test, with the contextvars bound when it was
    made; each call also writes a WARNING line from `FOREIGN_LOGGER`."""
    calls: list[ClientCall] = []
    record = FakeManagedAgentsClient._record

    def recording(
        self: FakeManagedAgentsClient, method: str, session_id: str | None, **args: Any
    ) -> RecordedCall:
        calls.append(ClientCall(method, session_id, dict(structlog.contextvars.get_contextvars())))
        structlog.get_logger(FOREIGN_LOGGER).warning("client_call", method=method)
        return record(self, method, session_id, **args)

    monkeypatch.setattr(FakeManagedAgentsClient, "_record", recording)
    return calls


def _uncached_debug_logger() -> Any:
    """A logger that uses the configured processors (so `capture_logs` sees it) at DEBUG level,
    whatever level and cache an earlier test configured globally."""
    return structlog.wrap_logger(
        None,
        wrapper_class=structlog.make_filtering_bound_logger(logging.DEBUG),
        cache_logger_on_first_use=False,
    )


@pytest.fixture
def debug_loggers(monkeypatch: pytest.MonkeyPatch) -> None:
    """The consumer's, the lifecycle's and the jobs' module loggers at DEBUG, uncached."""
    for module in (consumer_module, sessions, jobs):
        monkeypatch.setattr(module, "log", _uncached_debug_logger())


@contextmanager
def capture_plan_logs() -> Iterator[list[EventDict]]:
    """`capture_logs` through main.configure_logging's plan processors. Entered after any
    `create_app` (which configures structlog again and would drop the capture)."""
    processors = [structlog.contextvars.merge_contextvars, add_plan_log_keys]
    with structlog.testing.capture_logs(processors=processors) as entries:
        yield entries


@pytest.fixture
def plan_logs(debug_loggers: None) -> Iterator[list[EventDict]]:
    with capture_plan_logs() as entries:
        yield entries


def calls_of(calls: list[ClientCall], method: str) -> list[ClientCall]:
    return [call for call in calls if call.method == method]


def foreign_lines(entries: list[EventDict]) -> list[EventDict]:
    return [entry for entry in entries if entry["event"] == "client_call"]


def plan_keys(entry: EventDict) -> tuple[Any, ...]:
    return tuple(entry[key] for key in PLAN_LOG_KEYS)


# --- the consumer -------------------------------------------------------------------------------


async def test_consumer_lines_carry_the_plan_session_lane_and_event(
    harness: HarnessFactory,  # noqa: F811
    client_calls: list[ClientCall],
    plan_logs: list[EventDict],
) -> None:
    fake = FakeManagedAgentsClient.from_scenario("happy_path", await_timeout=10)
    h = harness(fake)
    plan_id = await h.create_plan()
    before = structlog.contextvars.get_contextvars()

    assert await h.run(plan_id) is PlanStatus.READY

    assert structlog.contextvars.get_contextvars() == before  # nothing leaks out of run()
    plan = str(plan_id)
    assert client_calls
    for call in client_calls:
        assert (call.context["plan_id"], call.context["session_id"]) == (plan, SID), call
    [answer] = calls_of(client_calls, "send_custom_tool_result")
    assert answer.context["agent"] == "coordinator"
    assert answer.context["event_type"] == "agent.custom_tool_use"
    [first] = calls_of(client_calls, "send_user_message")
    assert first.context.get("event_type") is None  # the brief: no event is being handled
    thread_streams = calls_of(client_calls, "stream_thread")
    assert {call.context["agent"] for call in thread_streams} == SUBAGENTS
    assert {call.context["event_type"] for call in thread_streams} == {None}

    # Lines from the foreign module and from the consumer itself, all four keys on each.
    lines = foreign_lines(plan_logs)
    assert len(lines) == len(client_calls)
    assert all(set(PLAN_LOG_KEYS) <= set(entry) for entry in plan_logs)
    answered = [line for line in lines if line["method"] == "send_custom_tool_result"]
    assert [plan_keys(line) for line in answered] == [
        (plan, SID, "coordinator", "agent.custom_tool_use")
    ]
    consumer_lines = [entry for entry in plan_logs if entry["event"] != "client_call"]
    assert {"consumer_started", "submit_plan_accepted", "consumer_stopped"} <= {
        entry["event"] for entry in consumer_lines
    }
    assert {(entry["plan_id"], entry["session_id"]) for entry in consumer_lines} == {(plan, SID)}


# --- the lifecycle ------------------------------------------------------------------------------


@pytest.mark.usefixtures("debug_loggers")
async def test_start_and_continue_bind_the_plan_then_the_session(
    open_browser: OpenBrowser,  # noqa: F811
    client_calls: list[ClientCall],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sessions, "CONTINUE_RESUME_WAIT_SECONDS", 3600.0)
    fake = scenario("budget_reached")
    try:
        async with open_browser(fake) as browser:
            with capture_plan_logs() as plan_logs:
                plan_id = await browser.create_plan(fake.meta["request"])
                await browser.wait_for_status(plan_id, PlanStatus.BUDGET_PAUSED)
                await browser.wait_for_consumer_exit(plan_id)
                continued = await browser.http.post(
                    f"/plans/{plan_id}/continue", headers=browser.frontend
                )
                assert continued.status_code == 202, continued.text
                await browser.wait_for_status(plan_id, PlanStatus.READY)
                await browser.wait_for_consumer_exit(plan_id)
    finally:
        await fake.shutdown()

    plan = str(plan_id)
    [created] = calls_of(client_calls, "create_session")
    assert created.context["plan_id"] == plan  # bound as soon as the plan id exists
    assert created.context.get("session_id") is None  # the session doesn't exist yet
    [update] = calls_of(client_calls, "update_budget")
    assert (update.context["plan_id"], update.context["session_id"]) == (plan, fake.session_id)
    for call in client_calls:
        if call.method in ("create_session", "aclose"):
            continue
        assert (call.context["plan_id"], call.context["session_id"]) == (
            plan,
            fake.session_id,
        ), call
    started = [entry for entry in plan_logs if entry["event"] == "plan_started"]
    continued_lines = [entry for entry in plan_logs if entry["event"] == "plan_continued"]
    assert [(e["plan_id"], e["session_id"]) for e in started + continued_lines] == [
        (plan, fake.session_id)
    ] * 2


@pytest.mark.usefixtures("debug_loggers")
async def test_an_interrupt_binds_the_plan_and_its_session(
    open_browser: OpenBrowser,  # noqa: F811
    client_calls: list[ClientCall],
) -> None:
    fake = scenario("interrupt")
    try:
        async with open_browser(fake) as browser:
            with capture_plan_logs() as plan_logs:
                plan_id = await browser.create_plan(fake.meta["request"])
                await fake.reached("working")
                response = await browser.http.post(
                    f"/plans/{plan_id}/interrupt", headers=browser.frontend
                )
                assert response.status_code == 202, response.text
                fake.release("working")
                await browser.wait_for_status(plan_id, PlanStatus.INTERRUPTED)
                await browser.wait_for_consumer_exit(plan_id)
    finally:
        await fake.shutdown()

    [interrupt] = calls_of(client_calls, "send_interrupt")
    assert (interrupt.context["plan_id"], interrupt.context["session_id"]) == (
        str(plan_id),
        fake.session_id,
    )
    [requested] = [entry for entry in plan_logs if entry["event"] == "plan_interrupt_requested"]
    assert plan_keys(requested)[:2] == (str(plan_id), fake.session_id)


# --- jobs ---------------------------------------------------------------------------------------


async def test_the_stuck_check_binds_each_plan_it_stops(
    make_settings: Callable[..., Settings],
    db_session_factory: async_sessionmaker[AsyncSession],
    client_calls: list[ClientCall],
    plan_logs: list[EventDict],
) -> None:
    async with open_planner(planner_settings(make_settings), db_session_factory) as planner:
        plan_id = await insert_plan(
            db_session_factory, running_since=FROZEN_NOW - jobs.STUCK_AFTER * 2
        )
        handled = await jobs.check_stuck_plans(planner.services, now=FROZEN_NOW)

    assert handled == [plan_id]
    session_calls = [call for call in client_calls if call.session_id is not None]
    assert {call.method for call in session_calls} >= {"send_interrupt", "retrieve_session"}
    for call in session_calls:
        assert (call.context["plan_id"], call.context["session_id"]) == (
            str(plan_id),
            "sesn_fake_0001",
        ), call
    for line in foreign_lines(plan_logs):
        assert line["plan_id"] == str(plan_id)
    assert structlog.contextvars.get_contextvars().get("plan_id") is None


async def test_the_nightly_cleanup_binds_each_plan_and_orphan(
    db_session_factory: async_sessionmaker[AsyncSession],
    client_calls: list[ClientCall],
) -> None:
    plan_id = await insert_plan(db_session_factory, session_id="sesn_old", created_at=OLD)
    orphan_plan = uuid.uuid4()
    fake = FakeManagedAgentsClient(
        workspace_sessions=[workspace_session("sesn_orphan", orphan_plan)]
    )
    report = await jobs.nightly_cleanup(
        session_factory=db_session_factory, client=fake, now=FROZEN_NOW
    )

    assert report.plans_deleted == 1
    deletes = {call.session_id: call.context for call in calls_of(client_calls, "delete_session")}
    assert deletes["sesn_old"]["plan_id"] == str(plan_id)
    assert deletes["sesn_old"]["session_id"] == "sesn_old"
    assert deletes["sesn_orphan"]["plan_id"] == str(orphan_plan)
    assert deletes["sesn_orphan"]["session_id"] == "sesn_orphan"


# --- entry points -------------------------------------------------------------------------------


@pytest.mark.usefixtures("uncached_structlog")
@pytest.mark.parametrize("entry_point", ["jobs", "cli"])
def test_entry_points_put_the_plan_keys_on_every_line(
    entry_point: str, capsys: pytest.CaptureFixture[str]
) -> None:
    if entry_point == "jobs":
        jobs._configure_logging("INFO")
    else:
        cli._configure_logging()
    processors = structlog.get_config()["processors"]
    merge = processors.index(structlog.contextvars.merge_contextvars)
    assert processors[merge + 1] is add_plan_log_keys

    logger = structlog.get_logger("tests.entry_point")
    logger.warning("outside")
    with structlog.contextvars.bound_contextvars(plan_id="p-1", session_id="sesn_1"):
        logger.warning("inside", agent="flights")
    captured = capsys.readouterr()
    out = captured.out if entry_point == "jobs" else captured.err  # cli keeps stdout clean
    lines = {line["event"]: line for line in map(json.loads, out.splitlines())}
    assert plan_keys(lines["outside"]) == (None, None, None, None)
    assert plan_keys(lines["inside"]) == ("p-1", "sesn_1", "flights", None)
