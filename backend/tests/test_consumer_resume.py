"""Resume (the spec's "Ripresa" row): a consumer interrupted mid-run and restarted from the
history stores no event twice (`ma_event_id` unique) and completes the plan.

Driven by `FakeManagedAgentsClient` instead of a development session (CLAUDE.md, "Testing
offline"). A restart is modelled as the consumer task being cancelled (the process dying: no
cleanup reaches the database) and a new consumer started in resume mode on the same plan, as
`sessions.resume_running_plans` does at process start.
"""

from __future__ import annotations

import asyncio
import datetime as dt
from collections.abc import AsyncIterator, Callable
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app import consumer as consumer_module
from app.config import Settings
from app.consumer import (
    PLAN_ACCEPTED_TEXT,
    ConsumerRegistry,
    EventSink,
    PlanUpdate,
    backend_event,
    backend_event_id,
)
from app.db import PlanStatus
from app.events import EventKind
from tests.fakes import FakeManagedAgentsClient
from tests.test_consumer import (
    BRIEF,
    NOW,
    RUN_TIMEOUT,
    SID,
    BlockingFx,
    HarnessFactory,
    api_keys,
    by_key,
    harness_factory,
    offline_http,
    owned_keys,
    scenario,
    tool_results,
)

RESTART_TOOL_USE = "sevt_011CZv95QMnpRSTerY4jSH9y"


@pytest.fixture
async def harness(
    db_session_factory: async_sessionmaker[AsyncSession],
    make_settings: Callable[..., Settings],
) -> AsyncIterator[HarnessFactory]:
    async with offline_http() as http:
        yield harness_factory(db_session_factory, make_settings, http)


async def finish(task: asyncio.Task[PlanStatus]) -> PlanStatus:
    async with asyncio.timeout(RUN_TIMEOUT):
        return await task


@pytest.mark.parametrize("listing_fails_halfway", [False, True])
async def test_a_restarted_consumer_answers_the_pending_submit_from_the_stored_outcome(
    harness: HarnessFactory, *, listing_fails_halfway: bool
) -> None:
    fake = scenario("restart_resume", page_size=10)
    h = harness(fake)
    plan_id = await h.create_plan()
    registry = ConsumerRegistry(h.deps)

    first = registry.start(plan_id, SID, first_message=BRIEF)
    await fake.reached("crash")
    hung = await fake.called("send_custom_tool_result")
    assert hung.args["tool_use_id"] == RESTART_TOOL_USE
    await registry.stop(plan_id)  # the process dies while the answer is on the wire
    assert first.done
    assert tool_results(fake) == []  # the answer never left

    record = await h.plan(plan_id)
    assert (record.status, record.submit_attempts) == ("running", 1)
    assert record.plan is not None  # the outcome was committed before the answer
    before = await h.events(plan_id)
    outcome_key = backend_event_id(plan_id, "submit", RESTART_TOOL_USE)
    assert outcome_key in by_key(before)

    if listing_fails_halfway:
        fake.fail_next("list_events", "api_unavailable", after=1)
    resumed = h.consumer(plan_id, fresh=False)
    task = asyncio.create_task(resumed.run())
    fake.release("crash")
    assert await finish(task) is PlanStatus.READY
    fake.assert_script_done()

    # Answered once, from the record: never evaluated a second time.
    assert [(r["custom_tool_use_id"], r["is_error"]) for r in tool_results(fake)] == [
        (RESTART_TOOL_USE, False)
    ]
    assert tool_results(fake)[0]["content"][0]["text"] == PLAN_ACCEPTED_TEXT
    record = await h.plan(plan_id)
    assert (record.status, record.submit_attempts, record.cost_cents) == ("ready", 1, 36)
    assert fake.archived == [SID]

    rows = await h.events(plan_id)
    keys = api_keys(rows)
    assert len(keys) == len(set(keys))
    assert set(keys) == owned_keys(fake, plan_id, skip_types=["session.status_terminated"])
    outcomes = [
        row for row in rows if (row.ma_event_id or "").endswith(f":submit:{RESTART_TOOL_USE}")
    ]
    assert len(outcomes) == 1
    # What consumer 1 stored is untouched; the resumed consumer continues the sequence.
    assert [(row.seq, row.ma_event_id) for row in rows[: len(before)]] == [
        (row.seq, row.ma_event_id) for row in before
    ]
    assert [row.seq for row in rows] == list(range(len(rows)))
    # Events after the crash carry +02:00 offsets: stored as instants, not strings.
    final_idle = by_key(rows)["sevt_011CZ1ep6MWzs4cb7cDNpsdv"]
    assert final_idle.ts == dt.datetime(2026, 10, 12, 10, 1, 24, 556000, tzinfo=dt.UTC)
    # The resumed consumer reopened every subagent thread.
    reopened = {call.args["thread_id"] for call in fake.calls_of("stream_thread")}
    assert reopened == {thread.id for thread in fake.threads() if not thread.is_primary}

    if listing_fails_halfway:
        # The failed pass acted on nothing; the next connection reconciled again.
        assert len(h.sleeps) == 1
        assert len(fake.calls_of("stream_session")) == 3
        failed = [call for call in fake.calls_of("list_events") if call.error is not None]
        assert len(failed) == 1
    else:
        assert h.sleeps == []
        assert len(fake.calls_of("stream_session")) == 2


async def test_an_interrupt_requested_before_the_restart_ends_the_plan_interrupted(
    harness: HarnessFactory,
) -> None:
    fake = scenario("interrupt")
    h = harness(fake)
    plan_id = await h.create_plan()
    first = h.consumer(plan_id)
    first_task = asyncio.create_task(first.run())
    await fake.reached("working")
    # sessions.request_interrupt: stored with its event, consumer told, user.interrupt sent.
    await EventSink(plan_id, session_factory=h.factory, hub=h.hub).emit(
        backend_event(EventKind.STATUS, "Interruzione richiesta", ts=NOW),
        ma_event_id=backend_event_id(plan_id, "status", "interrupt-requested:1"),
        update=PlanUpdate(interrupt_requested_at=NOW),
    )
    first.request_interrupt()
    await fake.send_interrupt(SID)
    first_task.cancel()  # the process dies before the session idles
    with pytest.raises(asyncio.CancelledError):
        await first_task

    resumed = h.consumer(plan_id, fresh=False)
    task = asyncio.create_task(resumed.run())
    fake.release("working")
    assert await finish(task) is PlanStatus.INTERRUPTED  # from plans.interrupt_requested_at
    fake.assert_script_done()
    assert fake.archived == [SID]
    rows = await h.events(plan_id)
    keys = api_keys(rows)
    assert len(keys) == len(set(keys))
    echoes = [r for r in rows if (r.detail or {}).get("event_type") == "user.interrupt"]
    assert len(echoes) == 1  # the empty-id echo, under its synthetic key


def tool_use(event_id: str) -> dict[str, Any]:
    return {
        "op": "emit",
        "event": {
            "id": event_id,
            "type": "agent.custom_tool_use",
            "name": "submit_plan",
            "input": {"$fixture": "ma/plans/lisbon_valid.json"},
        },
    }


def emit(event_type: str, **fields: Any) -> dict[str, Any]:
    return {"op": "emit", "event": {"type": event_type, **fields}}


async def test_a_consumer_killed_before_evaluating_evaluates_once_after_the_restart(
    harness: HarnessFactory,
) -> None:
    steps = [
        {"op": "await", "match": {"type": "user.message"}},
        emit("session.status_running"),
        tool_use("sevt_u1"),
        {"op": "usage", "list_cost_cents": 20},
        emit(
            "session.status_idle",
            stop_reason={"type": "requires_action", "event_ids": ["sevt_u1"]},
        ),
        {"op": "await", "match": {"custom_tool_use_id": "sevt_u1", "is_error": False}},
        emit("session.status_running"),
        {"op": "usage", "list_cost_cents": 22},
        emit("session.status_idle", stop_reason={"type": "end_turn"}),
    ]
    fake = FakeManagedAgentsClient(steps, await_timeout=10)
    blocking = BlockingFx()
    crashed = harness(fake, fx=blocking)
    plan_id = await crashed.create_plan()
    first_task = asyncio.create_task(crashed.consumer(plan_id).run())
    async with asyncio.timeout(RUN_TIMEOUT):
        await blocking.entered.wait()  # evaluating sevt_u1
    first_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first_task
    stored = by_key(await crashed.events(plan_id))
    assert "sevt_u1" in stored  # seen...
    assert backend_event_id(plan_id, "submit", "sevt_u1") not in stored  # ...but not handled

    h = harness(fake)
    assert await finish(asyncio.create_task(h.consumer(plan_id, fresh=False).run())) is (
        PlanStatus.READY
    )
    fake.assert_script_done()
    assert len(tool_results(fake)) == 1
    record = await h.plan(plan_id)
    assert (record.status, record.submit_attempts, record.cost_cents) == ("ready", 1, 22)
    keys = api_keys(await h.events(plan_id))
    assert len(keys) == len(set(keys))


async def test_only_the_latest_status_event_missed_while_down_is_acted_on(
    harness: HarnessFactory,
) -> None:
    """While no consumer listened the coordinator ended a turn (an `end_turn` idle that would
    fail the plan) and then resumed working: the resumed consumer stores that idle but acts
    only on the latest status event (running), and the plan completes."""
    message = {"content": [{"type": "text", "text": "Proseguo con la ricerca."}]}
    steps = [
        {"op": "await", "match": {"type": "user.message"}},
        emit("session.status_running"),
        {"op": "checkpoint", "name": "down"},
        emit("agent.message", **message),
        emit("session.status_idle", id="sevt_superseded", stop_reason={"type": "end_turn"}),
        emit("session.status_running"),
        emit("agent.message", **message),
        {"op": "await_stream"},
        tool_use("sevt_u1"),
        {"op": "usage", "list_cost_cents": 20},
        emit(
            "session.status_idle",
            stop_reason={"type": "requires_action", "event_ids": ["sevt_u1"]},
        ),
        {"op": "await", "match": {"custom_tool_use_id": "sevt_u1", "is_error": False}},
        emit("session.status_running"),
        {"op": "usage", "list_cost_cents": 22},
        {"op": "set", "status_lag": 1},
        emit("session.status_idle", id="sevt_last", stop_reason={"type": "end_turn"}),
    ]
    fake = FakeManagedAgentsClient(steps, await_timeout=10)
    h = harness(fake)
    plan_id = await h.create_plan()
    first_task = asyncio.create_task(h.consumer(plan_id).run())
    await fake.reached("down")
    first_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first_task
    fake.release("down")

    status = await finish(asyncio.create_task(h.consumer(plan_id, fresh=False).run()))
    assert status is PlanStatus.READY
    fake.assert_script_done()
    record = await h.plan(plan_id)
    assert (record.status, record.failure_reason) == ("ready", None)
    stored = by_key(await h.events(plan_id))
    assert {"sevt_superseded", "sevt_last"} <= set(stored)
    assert h.hub.ended == [(plan_id, PlanStatus.READY)]
    assert fake.archived == [SID]


async def test_a_resumed_consumer_reads_an_archived_thread_from_its_history_only(
    harness: HarnessFactory,
) -> None:
    """A thread archived as superseded before the restart gets no new events: the resumed
    consumer backfills its history without opening its stream, and doesn't archive it again."""
    old, new = "sthr_activities_1", "sthr_activities_2"
    message = {"type": "agent.message", "content": [{"type": "text", "text": "Ho finito."}]}
    steps = [
        {"op": "await", "match": {"type": "user.message"}},
        emit("session.status_running"),
        emit("session.thread_created", session_thread_id=old, agent_name="activities"),
        {"op": "await_stream", "scope": old},
        {"op": "emit", "scope": old, "event": message},
        emit(
            "session.thread_status_idle",
            session_thread_id=old,
            agent_name="activities",
            stop_reason={"type": "end_turn"},
        ),
        emit("session.thread_created", session_thread_id=new, agent_name="activities"),
        {"op": "await_call", "method": "archive_thread"},
        {"op": "checkpoint", "name": "down"},
        {"op": "await_stream", "scope": new},  # the resumed consumer follows the live thread
        {"op": "usage", "list_cost_cents": 12},
        emit("session.status_idle", stop_reason={"type": "end_turn"}),
    ]
    fake = FakeManagedAgentsClient(steps, await_timeout=10)
    h = harness(fake)
    plan_id = await h.create_plan()
    first_task = asyncio.create_task(h.consumer(plan_id).run())
    await fake.reached("down")
    first_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first_task
    assert fake.archived_threads == [(SID, old)]

    resumed = asyncio.create_task(h.consumer(plan_id, fresh=False).run())
    fake.release("down")
    assert await finish(resumed) is PlanStatus.FAILED  # end_turn without a plan
    fake.assert_script_done()

    def thread_calls(method: str, thread_id: str) -> int:
        return sum(1 for call in fake.calls_of(method) if call.args["thread_id"] == thread_id)

    assert thread_calls("stream_thread", old) == 1  # the first consumer's only
    assert thread_calls("list_thread_events", old) == 2  # one backfill per consumer
    assert thread_calls("stream_thread", new) == 2
    assert fake.archived_threads == [(SID, old)]  # not archived twice
    rows = await h.events(plan_id)
    keys = api_keys(rows)
    assert len(keys) == len(set(keys))
    assert set(keys) == owned_keys(fake, plan_id)
    assert by_key(rows)[fake.thread_history(old)[0]["id"]].agent == "activities"


async def test_a_dropped_stream_relists_and_acts_on_an_idle_it_missed(
    harness: HarnessFactory,
) -> None:
    """The stream drops just before the final idle; the reconnect finds it in the history and
    closes the plan from there (not from a live event)."""
    steps = [
        {"op": "await", "match": {"type": "user.message"}},
        emit("session.status_running"),
        tool_use("sevt_u1"),
        emit(
            "session.status_idle",
            stop_reason={"type": "requires_action", "event_ids": ["sevt_u1"]},
        ),
        {"op": "await", "match": {"custom_tool_use_id": "sevt_u1", "is_error": False}},
        emit("session.status_running"),
        {"op": "disconnect"},
        {"op": "usage", "list_cost_cents": 22},
        emit("session.status_idle", id="sevt_missed", stop_reason={"type": "end_turn"}),
    ]
    fake = FakeManagedAgentsClient(steps, await_timeout=10)
    h = harness(fake)
    plan_id = await h.create_plan()
    assert await h.run(plan_id) is PlanStatus.READY
    fake.assert_script_done()
    assert len(fake.calls_of("stream_session")) == 2
    assert "sevt_missed" in by_key(await h.events(plan_id))
    assert (await h.plan(plan_id)).cost_cents == 22
    assert fake.archived == [SID]


FLIGHTS_THREAD = "sthr_flights_1"


def ended_while_down() -> FakeManagedAgentsClient:
    """A session that delegated to flights and ended its turn while no consumer listened: the
    subagent's events exist only in its thread's history."""
    thread_message = {"type": "agent.message", "content": [{"type": "text", "text": "Fatto."}]}
    steps = [
        {"op": "await", "match": {"type": "user.message"}},
        emit("session.status_running"),
        {"op": "checkpoint", "name": "down"},
        emit("session.thread_created", session_thread_id=FLIGHTS_THREAD, agent_name="flights"),
        {
            "op": "emit",
            "scope": FLIGHTS_THREAD,
            "event": {
                "type": "agent.tool_use",
                "name": "web_search",
                "input": {"query": "voli MXP LIS 14 aprile"},
            },
        },
        {"op": "emit", "scope": FLIGHTS_THREAD, "event": thread_message},
        emit(
            "session.thread_status_idle",
            session_thread_id=FLIGHTS_THREAD,
            agent_name="flights",
            stop_reason={"type": "end_turn"},
        ),
        {"op": "usage", "list_cost_cents": 12},
        emit("session.status_idle", stop_reason={"type": "end_turn"}),
    ]
    return FakeManagedAgentsClient(steps, await_timeout=10)


async def crash_at_down(h: Any, fake: FakeManagedAgentsClient) -> Any:
    plan_id = await h.create_plan()
    first = asyncio.create_task(h.consumer(plan_id).run())
    await fake.reached("down")
    first.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first
    fake.release("down")
    await fake.wait_until_done()  # the session ended while no consumer listened
    return plan_id


async def test_a_session_that_ended_while_down_still_gets_its_threads_backfilled(
    harness: HarnessFactory,
) -> None:
    """Regression: the resume acted on the final idle at once, the plan ended, and the thread
    backfills still in flight (a real listing takes time) were cancelled: every subagent event
    of the downtime was lost. Now the reconcile waits for the backfills before acting."""
    fake = ended_while_down()
    h = harness(fake)
    plan_id = await crash_at_down(h, fake)
    fake.set_latency("list_thread_events", 0.3)

    consumer = h.consumer(plan_id, fresh=False)
    assert await finish(asyncio.create_task(consumer.run())) is PlanStatus.FAILED
    fake.assert_script_done()
    rows = await h.events(plan_id)
    keys = api_keys(rows)
    assert len(keys) == len(set(keys))
    thread_keys = {raw["id"] for raw in fake.thread_history(FLIGHTS_THREAD)}
    assert thread_keys <= set(keys)
    assert set(keys) == owned_keys(fake, plan_id)
    assert {by_key(rows)[key].agent for key in thread_keys} == {"flights"}
    record = await h.plan(plan_id)
    assert (record.status, record.cost_cents) == ("failed", 12)


async def test_a_backfill_that_never_answers_does_not_hold_the_resume(
    harness: HarnessFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The waits for thread backfills are bounded: a listing that hangs is logged and given up,
    and the plan is still closed from the session history."""
    monkeypatch.setattr(consumer_module, "RESUME_BACKFILL_WAIT_SECONDS", 0.2)
    monkeypatch.setattr(consumer_module, "SETTLE_BACKFILL_WAIT_SECONDS", 0.1)
    fake = ended_while_down()
    h = harness(fake)
    plan_id = await crash_at_down(h, fake)
    fake.fail_next("list_thread_events", "hang")

    assert await finish(asyncio.create_task(h.consumer(plan_id, fresh=False).run())) is (
        PlanStatus.FAILED
    )
    hung = [call for call in fake.calls_of("list_thread_events") if call.error is not None]
    assert len(hung) == 1  # cancelled when the consumer stopped, not left running
    assert fake.mismatches == []
    stored = set(api_keys(await h.events(plan_id)))
    assert not {raw["id"] for raw in fake.thread_history(FLIGHTS_THREAD)} & stored


async def test_a_thread_whose_stream_is_refused_is_still_backfilled_from_its_history(
    harness: HarnessFactory,
) -> None:
    """A thread stream that can't be opened (refused, not a network drop) is given up, but
    what the thread already did is read from its history and stored."""
    fake = ended_while_down()
    h = harness(fake)
    plan_id = await crash_at_down(h, fake)
    fake.fail_next("stream_thread", "api_rejected")

    assert await finish(asyncio.create_task(h.consumer(plan_id, fresh=False).run())) is (
        PlanStatus.FAILED
    )
    stored = set(api_keys(await h.events(plan_id)))
    assert {raw["id"] for raw in fake.thread_history(FLIGHTS_THREAD)} <= stored
    assert stored == owned_keys(fake, plan_id)
