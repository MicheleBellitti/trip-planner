"""The offline `FakeManagedAgentsClient` (tests/fakes): API rules, recording, faults, scripts.

The last section plays every shipped scenario end to end with `ReferenceConsumer`, a minimal
consumer that follows the documented protocol (open first, then send; open a thread stream,
then backfill it; answer submit_plan; reconcile on resume). It proves the fixtures are
playable; the real consumer has its own tests (test_consumer*.py).
"""

from __future__ import annotations

import asyncio
import datetime as dt
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from app.ma_client import (
    PRIMARY_SCOPE,
    AgentPin,
    ApiRejectedError,
    ApiUnavailableError,
    RawEvent,
    SessionBusyError,
    SessionInfo,
    SessionNotFoundError,
    SessionUsage,
    StreamDisconnectedError,
)
from app.plan import Plan, plan_rejection_message
from tests.fakes import (
    FAKE_EPOCH,
    FIXTURES_DIR,
    FakeManagedAgentsClient,
    FaultKind,
    ScriptMismatchError,
    _conforms,
    contains,
)

SID = "sesn_fake_0001"
PIN = AgentPin(id="agent_011CZcoordinator", version=3)
THREAD = "sthr_011CZflights00000000000"


def created_event(thread: str = THREAD, agent: str = "flights") -> dict[str, Any]:
    return {"type": "session.thread_created", "session_thread_id": thread, "agent_name": agent}


async def create(fake: FakeManagedAgentsClient, **overrides: Any) -> SessionInfo:
    args: dict[str, Any] = {
        "agent": PIN,
        "environment_id": "env_011CZcloud",
        "budget_cents": 60,
        "metadata": {"plan_id": "7f3c", "agent_profile": "development"},
        "title": "plan 7f3c",
    }
    args.update(overrides)
    return await fake.create_session(**args)


async def next_event(stream: AsyncIterator[RawEvent]) -> RawEvent:
    async with asyncio.timeout(1):
        return await anext(stream)


async def drain(fake: FakeManagedAgentsClient, session_id: str = SID) -> list[RawEvent]:
    events: list[RawEvent] = []
    page: str | None = None
    while True:
        result = await fake.list_events(session_id, page=page)
        events.extend(result.events)
        if result.next_page is None:
            return events
        page = result.next_page


# --- the Protocol -------------------------------------------------------------------------------


def test_the_fake_satisfies_the_protocol() -> None:
    fake = FakeManagedAgentsClient()
    assert _conforms(fake) is fake


async def test_create_session_records_the_call_and_starts_idle() -> None:
    fake = FakeManagedAgentsClient()
    info = await create(fake)
    assert info.id == SID
    assert info.status == "idle"
    assert info.budget_cents == 60
    assert info.usage.list_cost_cents == 0
    assert info.metadata == {"plan_id": "7f3c", "agent_profile": "development"}
    created = fake.created[0]
    assert (created.agent, created.environment_id, created.budget_cents) == (
        PIN,
        "env_011CZcloud",
        60,
    )
    assert created.title == "plan 7f3c"
    assert [call.method for call in fake.calls] == ["create_session"]
    assert fake.calls[0].session_id == SID


@pytest.mark.parametrize(
    "overrides",
    [
        {"budget_cents": 0},
        {"environment_id": ""},
        {"metadata": {f"k{index}": "v" for index in range(17)}},
        {"metadata": {"k" * 65: "v"}},
        {"metadata": {"plan_id": "x" * 513}},
    ],
)
async def test_create_session_enforces_the_api_limits(overrides: dict[str, Any]) -> None:
    fake = FakeManagedAgentsClient()
    with pytest.raises(ApiRejectedError):
        await create(fake, **overrides)
    assert fake.created == []
    assert isinstance(fake.calls[0].error, ApiRejectedError)


async def test_a_second_create_gets_an_unscripted_session() -> None:
    fake = FakeManagedAgentsClient()
    first = await create(fake)
    second = await create(fake, metadata={"plan_id": "other"})
    assert first.id == SID
    assert second.id != SID
    assert (await fake.retrieve_session(second.id)).metadata == {"plan_id": "other"}
    await fake.send_user_message(second.id, "hello")
    assert fake.sent[-1].session_id == second.id
    assert fake.history == []  # the scripted session saw nothing


async def test_unknown_sessions_and_threads_are_404() -> None:
    fake = FakeManagedAgentsClient()
    with pytest.raises(SessionNotFoundError):
        await fake.retrieve_session("sesn_missing")
    with pytest.raises(SessionNotFoundError):
        await fake.list_thread_events(SID, "sthr_missing")
    with pytest.raises(SessionNotFoundError):
        async with fake.stream_thread(SID, "sthr_missing"):
            pass
    with pytest.raises(SessionNotFoundError):
        await fake.send_interrupt(SID, "sthr_missing")


# --- streams --------------------------------------------------------------------------------


async def test_streams_deliver_only_events_emitted_after_they_open() -> None:
    fake = FakeManagedAgentsClient()
    before = fake.emit({"type": "session.status_running"})
    async with fake.stream_session(SID) as events:
        after = fake.emit({"type": "agent.thinking"})
        received = await next_event(events)
    assert received["id"] == after["id"]
    assert [event["id"] for event in fake.history] == [before["id"], after["id"]]


async def test_emitted_events_are_stamped_like_the_api() -> None:
    fake = FakeManagedAgentsClient()
    first = fake.emit({"type": "session.status_running"})
    second = fake.emit({"type": "agent.thinking"})
    explicit = fake.emit(
        {"type": "agent.thinking", "id": "sevt_given", "processed_at": "2026-10-12T12:30:00+02:00"}
    )
    third = fake.emit({"type": "agent.thinking"})
    assert first["id"].startswith("sevt_fake_")
    assert first["processed_at"] == "2026-10-12T10:00:00.000Z"
    assert second["processed_at"] == "2026-10-12T10:00:00.001Z"
    assert explicit["id"] == "sevt_given"
    assert explicit["processed_at"] == "2026-10-12T12:30:00+02:00"
    assert third["processed_at"] == "2026-10-12T10:30:00.001Z"


async def test_an_id_namespace_makes_every_event_id_unique_and_keeps_references() -> None:
    plain = FakeManagedAgentsClient.from_scenario("rejected_then_accepted")
    spaced = FakeManagedAgentsClient.from_scenario("rejected_then_accepted", id_namespace="r2")

    def emitted_ids(fake: FakeManagedAgentsClient) -> list[str]:
        return [step["event"]["id"] for step in fake.script if step["op"] == "emit"]

    assert emitted_ids(spaced) == [f"{event_id}_r2" for event_id in emitted_ids(plain)]
    # References follow: the await steps match the namespaced submit_plan uses.
    uses = {
        step["event"]["id"]
        for step in spaced.script
        if step["op"] == "emit" and step["event"]["type"] == "agent.custom_tool_use"
    }
    awaited = {
        step["match"]["custom_tool_use_id"]
        for step in spaced.script
        if step["op"] == "await" and "custom_tool_use_id" in step["match"]
    }
    assert awaited
    assert awaited <= uses
    # Text is never touched, only exact ids; generated ids carry the namespace too.
    assert spaced.meta == plain.meta
    assert spaced.emit({"type": "agent.thinking"})["id"] == "sevt_fake_r2_0001"


async def test_delivered_events_are_copies() -> None:
    fake = FakeManagedAgentsClient()
    async with fake.stream_session(SID) as events:
        fake.emit({"type": "agent.message", "content": [{"type": "text", "text": "ciao"}]})
        received = await next_event(events)
    received["content"][0]["text"] = "changed"
    assert fake.history[0]["content"][0]["text"] == "ciao"


async def test_thread_streams_are_scoped_and_threads_are_listed() -> None:
    fake = FakeManagedAgentsClient()
    fake.emit(created_event())
    early = fake.emit({"type": "agent.thinking"}, scope=THREAD)
    async with (
        fake.stream_session(SID) as session_events,
        fake.stream_thread(SID, THREAD) as thread_events,
    ):
        live = fake.emit({"type": "agent.message", "content": []}, scope=THREAD)
        status = fake.emit(
            {
                "type": "session.thread_status_idle",
                "session_thread_id": THREAD,
                "agent_name": "flights",
                "stop_reason": {"type": "end_turn"},
            }
        )
        assert (await next_event(thread_events))["id"] == live["id"]
        assert (await next_event(session_events))["id"] == status["id"]
    listed = await fake.list_thread_events(SID, THREAD)
    assert [event["id"] for event in listed.events] == [early["id"], live["id"]]
    assert all(event["type"] != "agent.thinking" for event in fake.history)
    threads = await fake.list_threads(SID)
    assert [(t.id, t.agent_name, t.is_primary, t.status) for t in threads] == [
        ("sthr_fake_primary", "coordinator", True, "idle"),
        (THREAD, "flights", False, "idle"),
    ]


async def test_terminated_ends_every_stream_normally_and_thread_terminated_ends_its_own() -> None:
    fake = FakeManagedAgentsClient()
    fake.emit(created_event())
    async with fake.stream_thread(SID, THREAD) as thread_events:
        fake.emit(
            {
                "type": "session.thread_status_terminated",
                "session_thread_id": THREAD,
                "agent_name": "flights",
            },
            scope=THREAD,
        )
        assert [event["type"] async for event in thread_events] == [
            "session.thread_status_terminated"
        ]
    async with fake.stream_session(SID) as events:
        fake.emit({"type": "session.status_terminated"})
        assert [event["type"] async for event in events] == ["session.status_terminated"]
    assert fake.status == "terminated"
    assert fake.open_streams == frozenset()


async def test_disconnect_drops_open_streams_until_they_reconnect() -> None:
    fake = FakeManagedAgentsClient()
    async with fake.stream_session(SID) as events:
        assert fake.disconnect(error_type="overloaded_error") == 1
        missed = fake.emit({"type": "agent.thinking"})
        with pytest.raises(StreamDisconnectedError) as raised:
            await next_event(events)
        assert raised.value.error_type == "overloaded_error"
        with pytest.raises(StopAsyncIteration):
            await anext(events)
    assert fake.open_streams == frozenset()
    async with fake.stream_session(SID) as events:
        later = fake.emit({"type": "agent.thinking"})
        assert (await next_event(events))["id"] == later["id"]
    assert missed["id"] in [event["id"] for event in await drain(fake)]


async def test_a_plain_disconnect_has_no_error_type() -> None:
    fake = FakeManagedAgentsClient()
    async with fake.stream_session(SID) as events:
        fake.disconnect()
        with pytest.raises(StreamDisconnectedError) as raised:
            await next_event(events)
    assert raised.value.error_type is None


# --- sends and echoes ---------------------------------------------------------------------------


async def test_sends_record_the_payload_and_the_streams_open_at_send_time() -> None:
    fake = FakeManagedAgentsClient()
    await fake.send_user_message(SID, "too early")
    async with fake.stream_session(SID) as events:
        await fake.send_user_message(SID, "brief")
        echo = await next_event(events)
    assert fake.sent[0].open_streams == frozenset()
    assert fake.sent[1].open_streams == frozenset({PRIMARY_SCOPE})
    assert fake.sent[1].payload == {
        "type": "user.message",
        "content": [{"type": "text", "text": "brief"}],
    }
    assert echo["type"] == "user.message"
    assert echo["id"].startswith("sevt_fake_")
    assert echo["processed_at"]
    assert [event["type"] for event in fake.history] == ["user.message", "user.message"]


async def test_interrupt_echo_has_an_empty_id() -> None:
    fake = FakeManagedAgentsClient()
    fake.emit(created_event())
    await fake.send_interrupt(SID)
    await fake.send_interrupt(SID, THREAD)
    assert [sent.payload for sent in fake.sent] == [
        {"type": "user.interrupt"},
        {"type": "user.interrupt", "session_thread_id": THREAD},
    ]
    echoes = [event for event in fake.history if event["type"] == "user.interrupt"]
    assert [event["id"] for event in echoes] == ["", ""]
    assert all(event["processed_at"] for event in echoes)


async def test_custom_tool_results_round_trip_and_a_second_result_is_not_echoed() -> None:
    fake = FakeManagedAgentsClient()
    use = fake.emit({"type": "agent.custom_tool_use", "name": "submit_plan", "input": {}})
    await fake.send_custom_tool_result(SID, use["id"], "Plan rejected", True)
    await fake.send_custom_tool_result(SID, use["id"], "Plan rejected", True)
    assert fake.sent[0].payload == {
        "type": "user.custom_tool_result",
        "custom_tool_use_id": use["id"],
        "content": [{"type": "text", "text": "Plan rejected"}],
        "is_error": True,
    }
    assert len(fake.sent) == 2
    echoes = [event for event in fake.history if event["type"] == "user.custom_tool_result"]
    assert len(echoes) == 1
    assert echoes[0]["custom_tool_use_id"] == use["id"]


async def test_a_result_for_an_unknown_tool_use_is_rejected() -> None:
    fake = FakeManagedAgentsClient()
    with pytest.raises(ApiRejectedError):
        await fake.send_custom_tool_result(SID, "sevt_unknown", "Plan accepted.", False)
    assert fake.sent == []


async def test_a_terminated_session_refuses_new_events() -> None:
    fake = FakeManagedAgentsClient()
    fake.emit({"type": "session.status_terminated"})
    with pytest.raises(ApiRejectedError):
        await fake.send_user_message(SID, "hello")
    with pytest.raises(ApiRejectedError):
        await fake.send_interrupt(SID)


# --- budget and status --------------------------------------------------------------------------


async def test_budget_reached_blocks_user_messages_until_the_budget_is_raised() -> None:
    fake = FakeManagedAgentsClient(budget_cents=60)
    fake.emit(
        {"type": "session.usage", "usage": {"list_cost": {"amount": "61", "currency": "USD"}}}
    )
    fake.emit({"type": "session.status_idle", "stop_reason": {"type": "budget_reached"}})
    with pytest.raises(ApiRejectedError):
        await fake.send_user_message(SID, "continua")
    await fake.send_interrupt(SID)  # settle events are still accepted
    with pytest.raises(ApiRejectedError) as raised:
        await fake.update_budget(SID, 61)
    assert raised.value.error_type == "budget_not_raised"
    info = await fake.update_budget(SID, 261)
    assert info.budget_cents == 261
    assert fake.budget_updates == [(SID, 261)]
    updated = fake.history[-1]
    assert updated["type"] == "session.updated"
    assert updated["budget"] == {
        "type": "limit",
        "max_list_cost": {"amount": "261", "currency": "USD"},
    }
    await fake.send_user_message(SID, "continua")


async def test_usage_events_update_the_tracked_usage() -> None:
    fake = FakeManagedAgentsClient(list_cost_cents=None)
    assert fake.session_info().usage == SessionUsage()
    fake.emit(
        {
            "type": "session.usage",
            "usage": {
                "input_tokens": 1000,
                "output_tokens": 200,
                "cache_read_input_tokens": 3000,
                "server_tool_use": {"web_search_requests": 4, "web_fetch_requests": 0},
                "active_seconds": 12.5,
                "list_cost": {"amount": "41", "currency": "USD"},
            },
        }
    )
    usage = (await fake.retrieve_session(SID)).usage
    assert usage == SessionUsage(
        list_cost_cents=41,
        input_tokens=1000,
        output_tokens=200,
        cache_read_input_tokens=3000,
        web_search_requests=4,
        active_seconds=12.5,
    )


async def test_status_follows_events_and_the_lag_reports_running_after_idle() -> None:
    fake = FakeManagedAgentsClient([{"op": "set", "status_lag": 2}])
    fake.start()
    await fake.wait_until_done()
    fake.emit({"type": "session.status_rescheduled"})
    assert (await fake.retrieve_session(SID)).status == "rescheduling"
    fake.emit({"type": "session.status_running"})
    fake.emit({"type": "session.status_idle", "stop_reason": {"type": "end_turn"}})
    with pytest.raises(SessionBusyError):
        await fake.archive_session(SID)
    statuses = [(await fake.retrieve_session(SID)).status for _ in range(3)]
    assert statuses == ["running", "running", "idle"]
    assert fake.status == "idle"


async def test_archive_refuses_a_running_session_then_terminates_it() -> None:
    fake = FakeManagedAgentsClient()
    fake.emit({"type": "session.status_running"})
    with pytest.raises(SessionBusyError):
        await fake.archive_session(SID)
    assert fake.archived == []
    fake.emit({"type": "session.status_idle", "stop_reason": {"type": "end_turn"}})
    async with fake.stream_session(SID) as events:
        await fake.archive_session(SID)
        assert [event["type"] async for event in events] == ["session.status_terminated"]
    await fake.archive_session(SID)  # no-op
    assert fake.archived == [SID]
    info = await fake.retrieve_session(SID)
    assert (info.archived, info.status) == (True, "terminated")


async def test_delete_ends_streams_and_forgets_the_session() -> None:
    fake = FakeManagedAgentsClient()
    fake.emit({"type": "session.status_running"})
    with pytest.raises(SessionBusyError):
        await fake.delete_session(SID)
    fake.emit({"type": "session.status_idle", "stop_reason": {"type": "end_turn"}})
    async with fake.stream_session(SID) as events:
        await fake.delete_session(SID)
        assert [event["type"] async for event in events] == ["session.deleted"]
    assert fake.deleted == [SID]
    with pytest.raises(SessionNotFoundError):
        await fake.list_events(SID)
    with pytest.raises(SessionNotFoundError):
        await fake.delete_session(SID)


async def test_list_sessions_reports_workspace_sessions_oldest_first() -> None:
    old = SessionInfo(
        id="sesn_old",
        status="idle",
        usage=SessionUsage(list_cost_cents=12),
        budget_cents=60,
        archived=True,
        metadata={"plan_id": "gone"},
        created_at=FAKE_EPOCH - dt.timedelta(days=120),
    )
    older = SessionInfo(
        id="sesn_older",
        status="idle",
        usage=SessionUsage(),
        budget_cents=None,
        archived=False,
        created_at=FAKE_EPOCH - dt.timedelta(days=200),
    )
    fake = FakeManagedAgentsClient(workspace_sessions=[old, older])
    cutoff = FAKE_EPOCH - dt.timedelta(days=90)
    listed = await fake.list_sessions(created_before=cutoff)
    assert [info.id for info in listed] == ["sesn_older", "sesn_old"]
    assert listed[1].metadata == {"plan_id": "gone"}
    unarchived = await fake.list_sessions(created_before=cutoff, include_archived=False)
    assert [info.id for info in unarchived] == ["sesn_older"]
    everything = await fake.list_sessions(created_before=FAKE_EPOCH + dt.timedelta(seconds=1))
    assert [info.id for info in everything] == ["sesn_older", "sesn_old", SID]
    await fake.delete_session("sesn_old")
    assert fake.deleted == ["sesn_old"]
    assert [info.id for info in await fake.list_sessions(created_before=cutoff)] == ["sesn_older"]


async def test_archive_thread_records_it_and_archived_threads_take_no_work() -> None:
    fake = FakeManagedAgentsClient()
    fake.emit(created_event())
    with pytest.raises(ApiRejectedError):
        await fake.archive_thread(SID, fake.primary_thread_id)
    await fake.archive_thread(SID, THREAD)
    await fake.archive_thread(SID, THREAD)
    assert fake.archived_threads == [(SID, THREAD)]
    assert [t.archived for t in fake.threads()] == [False, True]
    with pytest.raises(ValueError, match="archived thread"):
        fake.emit({"type": "agent.thinking"}, scope=THREAD)


# --- listings -----------------------------------------------------------------------------------


async def test_list_events_pages_oldest_first_with_cursors() -> None:
    fake = FakeManagedAgentsClient(page_size=2)
    ids = [fake.emit({"type": "agent.thinking"})["id"] for _ in range(5)]
    first = await fake.list_events(SID)
    assert [event["id"] for event in first.events] == ids[:2]
    assert first.next_page == "p2"
    second = await fake.list_events(SID, page=first.next_page, limit=1)
    assert [event["id"] for event in second.events] == ids[2:3]
    assert [event["id"] for event in await drain(fake)] == ids
    last = await fake.list_events(SID, page="p4")
    assert ([event["id"] for event in last.events], last.next_page) == (ids[4:], None)
    with pytest.raises(ApiRejectedError):
        await fake.list_events(SID, page="garbage")


async def test_list_events_since_is_inclusive_and_compares_instants() -> None:
    fake = FakeManagedAgentsClient()
    fake.emit({"type": "agent.thinking", "processed_at": "2026-10-12T10:00:00.000Z"})
    kept = fake.emit({"type": "agent.thinking", "processed_at": "2026-10-12T12:00:05+02:00"})
    later = fake.emit({"type": "agent.thinking", "processed_at": "2026-10-12T10:00:09.500Z"})
    page = await fake.list_events(SID, since=dt.datetime(2026, 10, 12, 10, 0, 5, tzinfo=dt.UTC))
    assert [event["id"] for event in page.events] == [kept["id"], later["id"]]
    with pytest.raises(ValueError, match="timezone-aware"):
        await fake.list_events(SID, since=dt.datetime(2026, 10, 12, 10, 0))  # noqa: DTZ001


# --- fault injection ----------------------------------------------------------------------------


async def test_fail_next_raises_once_after_the_given_number_of_calls() -> None:
    fake = FakeManagedAgentsClient()
    error = ApiUnavailableError("down", status_code=503)
    fake.fail_next("list_events", error, after=1)
    await fake.list_events(SID)
    with pytest.raises(ApiUnavailableError):
        await fake.list_events(SID)
    await fake.list_events(SID)
    assert [call.error for call in fake.calls_of("list_events")] == [None, error, None]


@pytest.mark.parametrize(
    ("kind", "error_type"),
    [
        ("api_unavailable", ApiUnavailableError),
        ("api_rejected", ApiRejectedError),
        ("not_found", SessionNotFoundError),
        ("busy", SessionBusyError),
        ("disconnected", StreamDisconnectedError),
    ],
)
async def test_fail_next_accepts_fault_kinds(kind: FaultKind, error_type: type[Exception]) -> None:
    fake = FakeManagedAgentsClient()
    fake.fail_next("stream_session", kind)
    with pytest.raises(error_type):
        async with fake.stream_session(SID):
            pass
    assert fake.open_streams == frozenset()


async def test_fail_next_rejects_unknown_methods() -> None:
    fake = FakeManagedAgentsClient()
    with pytest.raises(ValueError, match="unknown method"):
        fake.fail_next("send_message", "api_unavailable")


async def test_a_hung_call_blocks_until_cancelled_and_is_not_sent() -> None:
    fake = FakeManagedAgentsClient()
    use = fake.emit({"type": "agent.custom_tool_use", "name": "submit_plan", "input": {}})
    fake.fail_next("send_custom_tool_result", "hang")
    task = asyncio.create_task(
        fake.send_custom_tool_result(SID, use["id"], "Plan accepted.", False)
    )
    call = await fake.called("send_custom_tool_result")
    assert call.args["tool_use_id"] == use["id"]
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert fake.sent == []
    assert fake.mismatches == []
    await fake.send_custom_tool_result(SID, use["id"], "Plan accepted.", False)
    assert len(fake.sent) == 1


async def test_set_latency_delays_every_later_call_until_removed() -> None:
    fake = FakeManagedAgentsClient()
    fake.set_latency("retrieve_session", 0.2)
    loop = asyncio.get_running_loop()
    started = loop.time()
    task = asyncio.create_task(fake.retrieve_session(SID))
    await fake.called("retrieve_session")  # recorded at once, answered after the latency
    assert not task.done()
    await task
    assert loop.time() - started >= 0.2
    fake.fail_next("retrieve_session", "api_unavailable")
    with pytest.raises(ApiUnavailableError):  # the wait comes before the fault
        await fake.retrieve_session(SID)
    fake.set_latency("retrieve_session", 0)
    started = loop.time()
    await fake.retrieve_session(SID)
    assert loop.time() - started < 0.2
    with pytest.raises(ValueError, match="unknown method"):
        fake.set_latency("send_message", 1.0)
    with pytest.raises(ValueError, match=">= 0"):
        fake.set_latency("retrieve_session", -1.0)


async def test_a_hang_nobody_cancels_is_a_mismatch() -> None:
    fake = FakeManagedAgentsClient(await_timeout=0.05)
    fake.fail_next("retrieve_session", "hang")
    with pytest.raises(ApiUnavailableError):
        await fake.retrieve_session(SID)
    with pytest.raises(ScriptMismatchError, match="never cancelled"):
        fake.assert_script_done()


# --- scripts ------------------------------------------------------------------------------------


def write_script(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "script.jsonl"
    path.write_text(text, encoding="utf-8")
    return path


def test_from_jsonl_skips_comments_and_resolves_fixtures(tmp_path: Path) -> None:
    path = write_script(
        tmp_path,
        '{"op": "meta", "description": "demo"}\n'
        "# a comment\n"
        "\n"
        '{"op": "emit", "event": {"type": "agent.custom_tool_use", "name": "submit_plan", '
        '"input": {"$fixture": "ma/plans/lisbon_valid.json"}}}\n',
    )
    fake = FakeManagedAgentsClient.from_jsonl(path)
    assert fake.meta == {"description": "demo"}
    plan = fake.script[1]["event"]["input"]
    assert Plan.model_validate(plan).title.startswith("Lisbona")


def test_from_jsonl_finds_scenarios_by_name() -> None:
    fake = FakeManagedAgentsClient.from_jsonl("happy_path")
    assert fake.meta == FakeManagedAgentsClient.from_scenario("happy_path").meta
    assert fake.meta == FakeManagedAgentsClient.from_jsonl(FIXTURES_DIR / "happy_path.jsonl").meta


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("{not json}\n", "script.jsonl:1"),
        ('["op"]\n', "JSON object"),
        ('{"op": "jump"}\n', "unknown op"),
        ('{"op": "await"}\n', "match"),
        ('{"op": "emit", "event": {"id": "x"}}\n', "type"),
        ('{"op": "fail_next", "method": "list_events", "error": "boom"}\n', "error must be"),
        ('{"op": "await_call", "method": "nope"}\n', "unknown method"),
        ('{"op": "set", "colour": "red"}\n', "unknown fields"),
        ('{"op": "emit", "event": {"type": "x"}}\n{"op": "meta"}\n', "first step"),
    ],
)
def test_malformed_scripts_are_rejected_at_load(tmp_path: Path, text: str, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        FakeManagedAgentsClient.from_jsonl(write_script(tmp_path, text))


def test_contains_is_a_recursive_subset_match() -> None:
    payload = {
        "type": "user.custom_tool_result",
        "custom_tool_use_id": "sevt_1",
        "content": [{"type": "text", "text": "Plan accepted."}],
        "is_error": False,
    }
    assert contains(payload, {"type": "user.custom_tool_result", "is_error": False})
    assert contains(payload, {"content": [{"type": "text"}]})
    assert not contains(payload, {"is_error": 0})
    assert not contains(payload, {"content": []})
    assert not contains(payload, {"session_thread_id": None})


async def test_await_steps_match_sends_in_order() -> None:
    fake = FakeManagedAgentsClient(
        [
            {"op": "await", "match": {"type": "user.message"}},
            {"op": "emit", "event": {"type": "session.status_running"}},
            {"op": "await", "match": {"type": "user.interrupt"}, "count": 2},
        ]
    )
    async with fake.stream_session(SID) as events:
        await fake.send_user_message(SID, "brief")
        assert (await next_event(events))["type"] == "user.message"
        assert (await next_event(events))["type"] == "session.status_running"
        await fake.send_interrupt(SID)
        await fake.send_interrupt(SID)
        await fake.wait_until_done()
    fake.assert_script_done()
    assert fake.done
    assert fake.unmatched_sends == []


async def test_a_send_that_does_not_match_is_a_mismatch() -> None:
    fake = FakeManagedAgentsClient(
        [
            {"op": "await", "match": {"type": "user.message"}},
            {"op": "emit", "event": {"type": "session.status_running"}},
        ]
    )
    async with fake.stream_session(SID):
        await fake.send_interrupt(SID)  # never raises inside the backend's call
        with pytest.raises(ScriptMismatchError, match=r"user\.interrupt"):
            await fake.wait_until_done()
    with pytest.raises(ScriptMismatchError, match="expected a send matching"):
        fake.assert_script_done()
    assert fake.history[-1]["type"] == "user.interrupt"  # nothing emitted after the mismatch


async def test_a_blocking_step_times_out_into_a_mismatch() -> None:
    fake = FakeManagedAgentsClient(
        [{"op": "await", "match": {"type": "user.message"}, "timeout": 0.05}]
    )
    fake.start()
    with pytest.raises(ScriptMismatchError, match="timed out"):
        await fake.wait_until_done()


def test_assert_script_done_names_the_first_step_not_reached() -> None:
    fake = FakeManagedAgentsClient([{"op": "emit", "event": {"type": "agent.thinking"}}])
    with pytest.raises(AssertionError, match="step 0"):
        fake.assert_script_done()
    FakeManagedAgentsClient().assert_script_done()  # an empty script is done


async def test_emit_to_an_unknown_thread_is_a_mismatch() -> None:
    fake = FakeManagedAgentsClient(
        [{"op": "emit", "scope": THREAD, "event": {"type": "agent.thinking"}}]
    )
    fake.start()
    with pytest.raises(ScriptMismatchError, match="unknown thread scope"):
        await fake.wait_until_done()


async def test_checkpoints_stop_the_driver_until_released() -> None:
    fake = FakeManagedAgentsClient(
        [
            {"op": "checkpoint", "name": "crash"},
            {"op": "emit", "event": {"type": "agent.thinking"}},
        ]
    )
    fake.start()
    await fake.reached("crash")
    assert fake.history == []
    fake.release("crash")
    await fake.wait_until_done()
    assert [event["type"] for event in fake.history] == ["agent.thinking"]


async def test_a_checkpoint_can_be_released_before_it_is_reached() -> None:
    fake = FakeManagedAgentsClient([{"op": "checkpoint", "name": "early"}])
    fake.release("early")
    fake.start()
    await fake.wait_until_done()
    fake.assert_script_done()


async def test_reached_fails_when_the_script_never_gets_there() -> None:
    fake = FakeManagedAgentsClient([{"op": "emit", "event": {"type": "agent.thinking"}}])
    fake.start()
    with pytest.raises(AssertionError, match="without reaching"):
        await fake.reached("missing")


async def test_await_call_and_await_stream_follow_the_backend() -> None:
    fake = FakeManagedAgentsClient(
        [
            {"op": "await_stream", "scope": "session"},
            {
                "op": "emit",
                "event": {"type": "session.status_idle", "stop_reason": {"type": "budget_reached"}},
            },
            {"op": "await_call", "method": "update_budget"},
            {"op": "emit", "event": {"type": "session.status_running"}},
        ],
        budget_cents=60,
    )
    fake.start()
    async with fake.stream_session(SID) as events:
        assert (await next_event(events))["type"] == "session.status_idle"
        with pytest.raises(ApiRejectedError):
            await fake.update_budget(SID, 0)  # failed calls don't satisfy await_call
        await fake.update_budget(SID, 260)
        assert (await next_event(events))["type"] == "session.updated"
        assert (await next_event(events))["type"] == "session.status_running"
    fake.assert_script_done()


async def test_script_ops_set_usage_disconnect_and_fail_next() -> None:
    fake = FakeManagedAgentsClient(
        [
            {"op": "await_stream"},
            {"op": "set", "budget_cents": 100, "list_cost_cents": 7, "page_size": 1},
            {"op": "usage", "list_cost_cents": 9, "input_tokens": 10, "web_search_requests": 2},
            {"op": "fail_next", "method": "list_threads", "error": "api_unavailable", "after": 1},
            {"op": "disconnect", "error_type": "overloaded_error"},
        ]
    )
    fake.start()
    async with fake.stream_session(SID) as events:
        assert (await next_event(events))["type"] == "session.usage"
        with pytest.raises(StreamDisconnectedError):
            await next_event(events)
    await fake.wait_until_done()
    info = fake.session_info()
    assert (info.budget_cents, info.usage.list_cost_cents, info.usage.web_search_requests) == (
        100,
        9,
        2,
    )
    usage = fake.history[0]
    assert usage["usage"]["list_cost"] == {"amount": "9", "currency": "USD"}
    assert usage["budget"]["max_list_cost"]["amount"] == "100"
    assert (await fake.list_events(SID)).next_page is None  # one event, page size 1
    await fake.list_threads(SID)
    with pytest.raises(ApiUnavailableError):
        await fake.list_threads(SID)


# --- scenarios, end to end ----------------------------------------------------------------------


class ReferenceConsumer:
    """A minimal consumer of the documented protocol (module docstring). `seen` plays the role
    of the events table: a resumed consumer gets the previous one's set."""

    def __init__(
        self, fake: FakeManagedAgentsClient, *, seen: set[tuple[str, str]] | None = None
    ) -> None:
        self.fake = fake
        self.sid = fake.session_id
        self.seen: set[tuple[str, str]] = seen if seen is not None else set()
        self.received: dict[str, list[RawEvent]] = {}
        self.tool_uses: set[str] = set()
        self.failures = 0
        self.accepted = False
        self.interrupt_requested = False
        self.threads: dict[str, asyncio.Task[None]] = {}

    def store(self, scope: str, raw: RawEvent) -> bool:
        key = (scope, raw["id"] or f"noid:{raw['type']}:{raw.get('processed_at')}")
        if key in self.seen:
            return False
        self.seen.add(key)
        self.received.setdefault(scope, []).append(raw)
        return True

    async def run(self, first_message: str | None = None) -> str:
        try:
            async with self.fake.stream_session(self.sid) as events:
                if first_message is not None:
                    await self.fake.send_user_message(self.sid, first_message)
                else:
                    outcome = await self.reconcile()
                    if outcome is not None:
                        return outcome
                async for raw in events:
                    if not self.store(PRIMARY_SCOPE, raw):
                        continue
                    outcome = await self.act(raw)
                    if outcome is not None:
                        return outcome
                return "terminated"
        finally:
            tasks = list(self.threads.values())
            if tasks:  # let followers drain what their streams already hold
                _, pending = await asyncio.wait(tasks, timeout=0.5)
                for task in pending:
                    task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)

    async def reconcile(self) -> str | None:
        history = await drain(self.fake, self.sid)
        answered = {
            e["custom_tool_use_id"] for e in history if e["type"] == "user.custom_tool_result"
        }
        latest_status: RawEvent | None = None
        for raw in history:
            if raw["type"] == "agent.custom_tool_use":
                self.tool_uses.add(raw["id"])
            if self.store(PRIMARY_SCOPE, raw) and raw["type"] == "session.status_idle":
                latest_status = raw
        for thread in await self.fake.list_threads(self.sid):
            if not thread.is_primary:
                self.follow(thread.id)
        for raw in history:
            if raw["type"] == "agent.custom_tool_use" and raw["id"] not in answered:
                outcome = await self.answer(raw)
                if outcome is not None:
                    return outcome
        return None if latest_status is None else await self.act(latest_status)

    def follow(self, thread_id: str) -> None:
        if thread_id not in self.threads:
            self.threads[thread_id] = asyncio.create_task(self.follow_thread(thread_id))

    async def follow_thread(self, thread_id: str) -> None:
        async with self.fake.stream_thread(self.sid, thread_id) as events:
            page: str | None = None
            while True:  # open first, then backfill, skipping seen ids
                result = await self.fake.list_thread_events(self.sid, thread_id, page=page)
                for raw in result.events:
                    self.store(thread_id, raw)
                if (page := result.next_page) is None:
                    break
            async for raw in events:
                self.store(thread_id, raw)

    async def act(self, raw: RawEvent) -> str | None:
        if raw["type"] == "session.thread_created":
            self.follow(raw["session_thread_id"])
        elif raw["type"] == "agent.custom_tool_use":
            self.tool_uses.add(raw["id"])
            return await self.answer(raw)
        elif raw["type"] == "session.status_idle":
            return await self.decide(raw["stop_reason"])
        return None

    async def answer(self, raw: RawEvent) -> str | None:
        try:
            Plan.model_validate(raw["input"])
        except ValidationError as error:
            self.failures += 1
            await self.fake.send_custom_tool_result(
                self.sid, raw["id"], plan_rejection_message(error), True
            )
            if self.failures == 3:
                await self.fake.send_interrupt(self.sid)
                return "failed"
            return None
        self.accepted = True
        await self.fake.send_custom_tool_result(self.sid, raw["id"], "Plan accepted.", False)
        return None

    async def decide(self, stop_reason: dict[str, Any]) -> str | None:
        reason = stop_reason["type"]
        if reason == "requires_action" and set(stop_reason["event_ids"]) <= self.tool_uses:
            return None
        if self.accepted or (reason == "end_turn" and self.interrupt_requested):
            for _ in range(10):  # the post-idle race
                if (await self.fake.retrieve_session(self.sid)).status != "running":
                    break
            await self.fake.archive_session(self.sid)
            return "ready" if self.accepted else "interrupted"
        return {"budget_reached": "budget_paused", "requires_action": "blocked"}.get(
            reason, "failed"
        )


async def play(fake: FakeManagedAgentsClient) -> tuple[str, ReferenceConsumer]:
    consumer = ReferenceConsumer(fake)
    async with asyncio.timeout(10):
        status = await consumer.run("Today is 2026-10-12 (Europe/Rome). ...")
    return status, consumer


def types(events: list[RawEvent]) -> list[str]:
    return [event["type"] for event in events]


async def test_happy_path_end_to_end() -> None:
    fake = FakeManagedAgentsClient.from_scenario("happy_path")
    status, consumer = await play(fake)
    await fake.wait_until_done()
    fake.assert_script_done()
    assert status == "ready"
    assert PRIMARY_SCOPE in fake.sent[0].open_streams
    assert fake.archived == [SID]
    methods = [call.method for call in fake.calls]
    assert methods.count("retrieve_session") == 2  # status lag 1: one "running" read first
    last_retrieve = max(i for i, method in enumerate(methods) if method == "retrieve_session")
    assert methods.index("archive_session") > last_retrieve
    threads = [thread for thread in fake.threads() if not thread.is_primary]
    assert [thread.agent_name for thread in threads] == [
        "flights",
        "lodging",
        "activities",
        "transport",
    ]
    for thread in threads:
        expected = [event["id"] for event in fake.thread_history(thread.id)]
        assert [event["id"] for event in consumer.received[thread.id]] == expected
    session_types = types(consumer.received[PRIMARY_SCOPE])
    assert session_types.count("agent.thread_message_received") == 5
    assert "session.usage" in session_types
    assert session_types[-1] == "session.status_idle"
    cross_posted = [
        e
        for e in consumer.received[PRIMARY_SCOPE]
        if e["type"].startswith("agent.") and e.get("session_thread_id")
    ]
    assert types(cross_posted) == ["agent.mcp_tool_use"]


async def test_rejected_then_accepted_end_to_end() -> None:
    fake = FakeManagedAgentsClient.from_scenario("rejected_then_accepted")
    status, consumer = await play(fake)
    fake.assert_script_done()
    assert (status, consumer.failures) == ("ready", 1)
    results = [s.payload for s in fake.sent if s.payload["type"] == "user.custom_tool_result"]
    assert [payload["is_error"] for payload in results] == [True, False]
    assert "book_by" in results[0]["content"][0]["text"]


async def test_three_rejections_end_to_end() -> None:
    fake = FakeManagedAgentsClient.from_scenario("three_rejections_failed")
    status, _ = await play(fake)
    await fake.wait_until_done()
    fake.assert_script_done()
    assert status == "failed"
    assert [sent.payload["type"] for sent in fake.sent][-1] == "user.interrupt"
    assert fake.history[-1]["stop_reason"] == {"type": "end_turn"}


async def test_budget_reached_then_continue_end_to_end() -> None:
    fake = FakeManagedAgentsClient.from_scenario("budget_reached")
    status, consumer = await play(fake)
    assert status == "budget_paused"
    with pytest.raises(ApiRejectedError):
        await fake.send_user_message(SID, "continua")
    info = await fake.retrieve_session(SID)
    assert info.usage.list_cost_cents == 61
    await fake.update_budget(SID, max(info.budget_cents or 0, 61) + 200)
    resumed = ReferenceConsumer(fake, seen=consumer.seen)
    async with asyncio.timeout(10):
        assert await resumed.run() == "ready"
    fake.assert_script_done()
    assert fake.budget_updates == [(SID, 261)]


async def test_requires_action_blocked_end_to_end() -> None:
    fake = FakeManagedAgentsClient.from_scenario("requires_action_blocked")
    status, _ = await play(fake)
    fake.assert_script_done()
    assert status == "blocked"
    assert fake.archived == []


async def test_end_turn_without_plan_end_to_end() -> None:
    fake = FakeManagedAgentsClient.from_scenario("end_turn_without_plan")
    status, _ = await play(fake)
    fake.assert_script_done()
    assert status == "failed"
    assert not [s for s in fake.sent if s.payload["type"] == "user.custom_tool_result"]


async def test_mcp_failure_end_to_end() -> None:
    fake = FakeManagedAgentsClient.from_scenario("mcp_failure")
    status, consumer = await play(fake)
    fake.assert_script_done()
    assert status == "ready"
    errors = [e["error"] for e in consumer.received[PRIMARY_SCOPE] if e["type"] == "session.error"]
    assert [(e["type"], e["retry_status"]["type"]) for e in errors] == [
        ("mcp_connection_failed_error", "retrying"),
        ("mcp_connection_failed_error", "exhausted"),
    ]


async def test_interrupt_end_to_end() -> None:
    fake = FakeManagedAgentsClient.from_scenario("interrupt")
    consumer = ReferenceConsumer(fake)
    task = asyncio.create_task(consumer.run("brief"))
    await fake.reached("working")
    consumer.interrupt_requested = True
    await fake.send_interrupt(SID)
    fake.release("working")
    async with asyncio.timeout(10):
        assert await task == "interrupted"
    fake.assert_script_done()
    assert fake.archived == [SID]
    echoes = [e for e in consumer.received[PRIMARY_SCOPE] if e["type"] == "user.interrupt"]
    assert [e["id"] for e in echoes] == [""]


async def test_unknown_event_types_end_to_end() -> None:
    fake = FakeManagedAgentsClient.from_scenario("unknown_event_type")
    status, consumer = await play(fake)
    fake.assert_script_done()
    assert status == "ready"
    received = [e for events in consumer.received.values() for e in events]
    assert {"session.checkpoint_created", "agent.tool_progress"} <= set(types(received))


async def test_restart_resume_end_to_end() -> None:
    fake = FakeManagedAgentsClient.from_scenario("restart_resume", page_size=10)
    first = ReferenceConsumer(fake)
    task = asyncio.create_task(first.run("brief"))
    await fake.reached("crash")
    hung = await fake.called("send_custom_tool_result")
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert fake.sent[-1].payload["type"] == "user.message"  # the answer never left
    stored_before = len(first.seen)
    fake.fail_next("list_events", "api_unavailable", after=1)  # the backfill fails halfway
    resumed = ReferenceConsumer(fake, seen=set(first.seen))
    with pytest.raises(ApiUnavailableError):
        await resumed.reconcile()
    resumed = ReferenceConsumer(fake, seen=set(first.seen))
    fake.release("crash")
    async with asyncio.timeout(10):
        assert await resumed.run() == "ready"
    fake.assert_script_done()
    answers = [s.payload for s in fake.sent if s.payload["type"] == "user.custom_tool_result"]
    assert [a["custom_tool_use_id"] for a in answers] == [hung.args["tool_use_id"]]
    assert len(resumed.seen) > stored_before
    after_crash = [e for e in fake.history if e["processed_at"].endswith("+02:00")]
    assert types(after_crash) == [
        "session.status_running",
        "agent.message",
        "session.usage",
        "session.status_idle",
    ]


async def test_stream_error_event_end_to_end() -> None:
    fake = FakeManagedAgentsClient.from_scenario("stream_error_event")
    first = ReferenceConsumer(fake)
    with pytest.raises(StreamDisconnectedError) as raised:
        async with asyncio.timeout(10):
            await first.run("brief")
    assert raised.value.error_type == "overloaded_error"
    resumed = ReferenceConsumer(fake, seen=set(first.seen))
    async with asyncio.timeout(10):
        assert await resumed.run() == "ready"
    fake.assert_script_done()
    missed = [e["id"] for e in resumed.received[PRIMARY_SCOPE] if e["type"] == "agent.message"]
    assert missed  # emitted while the stream was down, recovered from the history
    assert len(fake.calls_of("stream_session")) == 2


async def test_redelegation_end_to_end() -> None:
    fake = FakeManagedAgentsClient.from_scenario("redelegation")
    status, _ = await play(fake)
    fake.assert_script_done()
    assert status == "ready"
    activities = [t for t in fake.threads() if t.agent_name == "activities"]
    assert len(activities) == 2
    assert [t.status for t in activities] == ["idle", "idle"]


async def test_accepted_then_budget_reached_end_to_end() -> None:
    fake = FakeManagedAgentsClient.from_scenario("accepted_then_budget_reached")
    status, _ = await play(fake)
    fake.assert_script_done()
    assert status == "ready"
    assert fake.archived == [SID]


async def test_rescheduled_and_errors_end_to_end() -> None:
    fake = FakeManagedAgentsClient.from_scenario("rescheduled_and_errors")
    status, consumer = await play(fake)
    fake.assert_script_done()
    assert status == "terminated"  # the stream ended normally after session.status_terminated
    errors = [e["error"] for e in consumer.received[PRIMARY_SCOPE] if e["type"] == "session.error"]
    assert [error["retry_status"]["type"] for error in errors] == ["retrying", "terminal"]
    assert fake.status == "terminated"
