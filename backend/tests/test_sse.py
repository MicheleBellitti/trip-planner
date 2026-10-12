"""SSE (GET /plans/{id}/events): Postgres replay after Last-Event-ID, then the live hub.

httpx's ASGITransport collects the whole body before returning, so it can't read an endless
stream: `SseStream` drives the ASGI app directly, reads the body chunk by chunk and sends
`http.disconnect` on demand. The lifespan runs with conftest's `stub_planner`, and the replay
reader is conftest's `reference_load_events_after` (`stub_event_replay`), so these tests pin the
route's protocol: subscribe first, replay, live, gap filling, lag recovery, ping, end, cleanup.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractContextManager, asynccontextmanager
from dataclasses import dataclass, field
from typing import Any, cast
from urllib.parse import urlsplit

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from sqlalchemy.pool import QueuePool
from starlette.types import Message

from app import consumer, routes, sessions
from app.cli import REPLAY_LOCKFILE_DIR
from app.config import Settings
from app.db import EventRecord, PlanRecord, PlanStatus
from app.events import UIEvent
from app.hub import PlanHub, Subscription
from app.sessions import PlannerServices
from app.triptracker_schema import DEV_FALLBACK_SCHEMA_PATH
from tests.conftest import AppFactory, PlanRows, StubPlanner, reference_load_events_after
from tests.fakes import FakeManagedAgentsClient

TIMEOUT = 3.0


class StreamClosedError(Exception):
    """The response body ended."""


@dataclass
class SseMessage:
    id: str | None = None
    event: str | None = None
    data: str | None = None
    comments: list[str] = field(default_factory=list[str])

    @property
    def json(self) -> Any:
        assert self.data is not None
        return json.loads(self.data)


class SseStream:
    """One GET request against the ASGI app, read incrementally."""

    def __init__(self, app: FastAPI, url: str, headers: dict[str, str]) -> None:
        parts = urlsplit(url)
        raw_headers = [(b"host", b"testserver")]
        raw_headers += [(key.lower().encode(), value.encode()) for key, value in headers.items()]
        self._scope: dict[str, Any] = {
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": "2.3"},
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": parts.path,
            "raw_path": parts.path.encode(),
            "query_string": parts.query.encode(),
            "root_path": "",
            "headers": raw_headers,
            "client": ("127.0.0.1", 50000),
            "server": ("testserver", 80),
        }
        self._app = app
        self._chunks: asyncio.Queue[bytes | None] = asyncio.Queue()
        self._started: asyncio.Future[Message] = asyncio.get_running_loop().create_future()
        self._disconnect = asyncio.Event()
        self._request_sent = False
        self._buffer = b""
        self._closed = False
        self._task: asyncio.Task[None] | None = None

    async def _receive(self) -> Message:
        if not self._request_sent:
            self._request_sent = True
            return {"type": "http.request", "body": b"", "more_body": False}
        await self._disconnect.wait()
        return {"type": "http.disconnect"}

    async def _send(self, message: Message) -> None:
        if message["type"] == "http.response.start":
            self._started.set_result(message)
        elif message["type"] == "http.response.body":
            if message.get("body"):
                await self._chunks.put(message["body"])
            if not message.get("more_body", False):
                await self._chunks.put(None)

    async def open(self) -> None:
        self._task = asyncio.create_task(self._app(self._scope, self._receive, self._send))
        start = await asyncio.wait_for(self._started, TIMEOUT)
        self.status: int = start["status"]
        self.headers = {key.decode().lower(): value.decode() for key, value in start["headers"]}

    async def message(self) -> SseMessage:
        """The next SSE message, comments (pings) included."""
        separator = b"\r\n\r\n"
        while separator not in self._buffer:
            if self._closed:
                raise StreamClosedError
            chunk = await asyncio.wait_for(self._chunks.get(), TIMEOUT)
            if chunk is None:
                self._closed = True
            else:
                self._buffer += chunk
        raw, self._buffer = self._buffer.split(separator, 1)
        message = SseMessage()
        for line in raw.decode().split("\r\n"):
            name, _, value = line.partition(": ")
            if name == "":
                message.comments.append(value)
            elif name == "id":
                message.id = value
            elif name == "event":
                message.event = value
            elif name == "data":
                message.data = value if message.data is None else f"{message.data}\n{value}"
        return message

    async def event(self) -> SseMessage:
        """The next message that is not a ping."""
        while True:
            message = await self.message()
            if message.comments and message.data is None:
                continue
            return message

    async def body(self) -> bytes:
        """The rest of the body of a response that ends by itself."""
        while not self._closed:
            chunk = await asyncio.wait_for(self._chunks.get(), TIMEOUT)
            if chunk is None:
                self._closed = True
            else:
                self._buffer += chunk
        rest, self._buffer = self._buffer, b""
        return rest

    async def expect_closed(self) -> None:
        assert await self.body() == b""
        await self.finished()

    async def finished(self) -> None:
        assert self._task is not None
        await asyncio.wait_for(self._task, TIMEOUT)

    async def disconnect(self) -> None:
        self._disconnect.set()
        await self.finished()


@pytest.fixture
def sse_ready(stub_planner: StubPlanner, stub_event_replay: None, db_session_factory: Any) -> None:
    """Stub planner, reference replay reader, empty test database."""


@pytest.fixture
async def app(make_app: AppFactory, sse_ready: None) -> AsyncIterator[FastAPI]:
    async with make_app() as application:
        yield application


@pytest.fixture
def hub(app: FastAPI) -> PlanHub:
    return app.state.hub


@asynccontextmanager
async def open_stream(
    app: FastAPI, plan_id: uuid.UUID, *, query: str = "", headers: dict[str, str] | None = None
) -> AsyncIterator[SseStream]:
    url = f"/plans/{plan_id}/events" + (f"?{query}" if query else "")
    stream = SseStream(app, url, headers or {})
    await stream.open()
    try:
        yield stream
    finally:
        await stream.disconnect()


async def until(condition: Callable[[], bool], *, step: float = 0.005) -> None:
    for _ in range(int(TIMEOUT / step)):
        if condition():
            return
        await asyncio.sleep(step)
    raise AssertionError("condition not reached")


async def settle() -> None:
    """Let the stream's generator reach its next await (the live subscription)."""
    for _ in range(20):
        await asyncio.sleep(0)


def seqs(messages: list[SseMessage]) -> list[int]:
    return [int(message.id) for message in messages if message.id is not None]


async def events(stream: SseStream, count: int) -> list[SseMessage]:
    return [await stream.event() for _ in range(count)]


# --- replay and live ------------------------------------------------------------------------------


async def test_replay_after_last_event_id_then_live_then_end(
    app: FastAPI, hub: PlanHub, plan_rows: PlanRows
) -> None:
    record = await plan_rows.add_plan()
    stored = [await plan_rows.add_event(record.id, seq) for seq in range(5)]

    async with open_stream(app, record.id, headers={"Last-Event-ID": "2"}) as stream:
        assert stream.status == 200
        assert stream.headers["content-type"].startswith("text/event-stream")
        assert stream.headers["cache-control"] == "no-store"
        assert stream.headers["x-accel-buffering"] == "no"

        replayed = await events(stream, 2)
        assert seqs(replayed) == [3, 4]
        assert UIEvent.model_validate_json(replayed[0].data or "") == stored[3]
        assert replayed[0].event is None  # default `message` events

        live = await plan_rows.add_event(record.id, 5, title="Ricerca voli")
        hub.publish(record.id, live)
        message = await stream.event()
        assert message.id == "5"
        assert UIEvent.model_validate_json(message.data or "") == live

        await plan_rows.set_status(record.id, PlanStatus.READY)
        hub.end(record.id, PlanStatus.READY)
        end = await stream.event()
        assert end.event == "end"
        assert end.id is None
        assert end.json == {"status": "ready"}
        await stream.expect_closed()

    assert hub.subscriber_count(record.id) == 0


async def test_no_resume_point_replays_everything(app: FastAPI, plan_rows: PlanRows) -> None:
    record = await plan_rows.add_plan()
    for seq in range(3):
        await plan_rows.add_event(record.id, seq)

    async with open_stream(app, record.id) as stream:
        assert seqs(await events(stream, 3)) == [0, 1, 2]


async def test_after_query_parameter_resumes_a_first_connection(
    app: FastAPI, plan_rows: PlanRows
) -> None:
    record = await plan_rows.add_plan(status=PlanStatus.FAILED)
    for seq in range(4):
        await plan_rows.add_event(record.id, seq)

    async with open_stream(app, record.id, query="after=1") as stream:
        assert seqs(await events(stream, 2)) == [2, 3]
        assert (await stream.event()).event == "end"

    # Last-Event-ID (sent by EventSource on reconnection) wins over ?after=.
    headers = {"Last-Event-ID": "2"}
    async with open_stream(app, record.id, query="after=0", headers=headers) as stream:
        assert seqs(await events(stream, 1)) == [3]

    # A malformed header is ignored, not an error.
    headers = {"Last-Event-ID": "not-a-seq"}
    async with open_stream(app, record.id, query="after=2", headers=headers) as stream:
        assert seqs(await events(stream, 1)) == [3]


async def test_negative_after_is_a_validation_error(app: FastAPI, plan_rows: PlanRows) -> None:
    record = await plan_rows.add_plan()

    stream = SseStream(app, f"/plans/{record.id}/events?after=-1", {})
    await stream.open()

    assert stream.status == 422
    await stream.body()
    await stream.finished()


@pytest.mark.parametrize(
    "status",
    [PlanStatus.READY, PlanStatus.FAILED, PlanStatus.BLOCKED, PlanStatus.INTERRUPTED],
)
async def test_a_terminal_plan_replays_then_ends_and_closes(
    app: FastAPI, hub: PlanHub, plan_rows: PlanRows, status: PlanStatus
) -> None:
    record = await plan_rows.add_plan(status=status)
    for seq in range(2):
        await plan_rows.add_event(record.id, seq)

    async with open_stream(app, record.id) as stream:
        assert seqs(await events(stream, 2)) == [0, 1]
        end = await stream.event()
        assert (end.event, end.json) == ("end", {"status": status.value})
        await stream.expect_closed()

    assert hub.subscriber_count(record.id) == 0


async def test_budget_paused_is_not_terminal(
    app: FastAPI, hub: PlanHub, plan_rows: PlanRows
) -> None:
    record = await plan_rows.add_plan(status=PlanStatus.BUDGET_PAUSED)
    await plan_rows.add_event(record.id, 0)

    async with open_stream(app, record.id) as stream:
        assert seqs(await events(stream, 1)) == [0]
        # "Continua" later: the stream is still open and carries the next events.
        resumed = await plan_rows.add_event(record.id, 1, title="Budget aumentato: si riprende")
        hub.publish(record.id, resumed)
        message = await stream.event()
        assert (message.id, message.event) == ("1", None)


async def test_subscription_comes_before_the_postgres_read(
    app: FastAPI, hub: PlanHub, plan_rows: PlanRows, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An event committed and published right after the replay's read is not lost."""
    record = await plan_rows.add_plan()
    await plan_rows.add_event(record.id, 0)
    late: list[UIEvent] = []

    async def read_then_publish(
        db: AsyncSession, plan_id: uuid.UUID, after_seq: int | None, *, limit: int = 1000
    ) -> list[UIEvent]:
        page = await reference_load_events_after(db, plan_id, after_seq, limit=limit)
        if not late:
            late.append(await plan_rows.add_event(plan_id, 1))
            hub.publish(plan_id, late[0])
        return page

    monkeypatch.setattr(consumer, "load_events_after", read_then_publish)

    async with open_stream(app, record.id) as stream:
        assert seqs(await events(stream, 2)) == [0, 1]


# --- gaps, duplicates, lag ------------------------------------------------------------------------


async def test_a_gap_is_filled_from_postgres_and_late_copies_are_skipped(
    app: FastAPI, hub: PlanHub, plan_rows: PlanRows
) -> None:
    record = await plan_rows.add_plan()
    for seq in range(2):
        await plan_rows.add_event(record.id, seq)

    async with open_stream(app, record.id) as stream:
        assert seqs(await events(stream, 2)) == [0, 1]

        second = await plan_rows.add_event(record.id, 2)
        third = await plan_rows.add_event(record.id, 3)
        hub.publish(record.id, third)  # seq 3 before seq 2: writers publish out of order
        assert seqs(await events(stream, 2)) == [2, 3]

        hub.publish(record.id, second)  # the late copy: already sent
        hub.publish(record.id, third)  # a duplicate
        fourth = await plan_rows.add_event(record.id, 4)
        hub.publish(record.id, fourth)
        assert seqs(await events(stream, 1)) == [4]


async def test_first_live_event_with_an_empty_replay(
    app: FastAPI, hub: PlanHub, plan_rows: PlanRows
) -> None:
    record = await plan_rows.add_plan()

    async with open_stream(app, record.id) as stream:
        await until(lambda: hub.subscriber_count(record.id) == 1)
        hub.publish(record.id, await plan_rows.add_event(record.id, 0))
        assert seqs(await events(stream, 1)) == [0]

        await plan_rows.add_event(record.id, 1)
        hub.publish(record.id, await plan_rows.add_event(record.id, 2))
        assert seqs(await events(stream, 2)) == [1, 2]


async def test_a_lagged_subscriber_replays_from_postgres_and_resubscribes(
    make_app: AppFactory,
    sse_ready: None,
    stub_planner: StubPlanner,
    plan_rows: PlanRows,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub_planner.queue_size = 2
    async with make_app() as app:
        hub: PlanHub = app.state.hub
        subscriptions: list[Subscription] = []
        subscribe = hub.subscribe

        def counting_subscribe(plan_id: uuid.UUID) -> AbstractContextManager[Subscription]:
            manager = subscribe(plan_id)

            class Counting:
                def __enter__(self) -> Subscription:
                    subscription = manager.__enter__()
                    subscriptions.append(subscription)
                    return subscription

                def __exit__(self, *exc: Any) -> bool | None:
                    return manager.__exit__(*exc)

            return Counting()

        monkeypatch.setattr(hub, "subscribe", counting_subscribe)
        record = await plan_rows.add_plan()

        async with open_stream(app, record.id) as stream:
            await until(lambda: hub.subscriber_count(record.id) == 1)
            await settle()
            burst = [await plan_rows.add_event(record.id, seq) for seq in range(6)]
            for event in burst:  # no await in between: the 2-slot buffer overflows
                hub.publish(record.id, event)

            assert seqs(await events(stream, 6)) == [0, 1, 2, 3, 4, 5]
            assert subscriptions[0].lagged
            assert len(subscriptions) == 2

            hub.publish(record.id, await plan_rows.add_event(record.id, 6))
            assert seqs(await events(stream, 1)) == [6]
            assert hub.subscriber_count(record.id) == 1


# --- end, ping, disconnect, ownership -------------------------------------------------------------


async def test_the_end_follows_a_final_catch_up(
    app: FastAPI, hub: PlanHub, plan_rows: PlanRows
) -> None:
    record = await plan_rows.add_plan()
    await plan_rows.add_event(record.id, 0)

    async with open_stream(app, record.id) as stream:
        assert seqs(await events(stream, 1)) == [0]
        # Committed with the terminal status but not published (or published after the end).
        await plan_rows.add_event(record.id, 1, title="Piano accettato")
        await plan_rows.set_status(record.id, PlanStatus.READY)
        hub.end(record.id, PlanStatus.READY)

        assert seqs(await events(stream, 1)) == [1]
        end = await stream.event()
        assert (end.event, end.json) == ("end", {"status": "ready"})
        await stream.expect_closed()


class WindingDownConsumer:
    """A live consumer after its terminal decision: it still stores what its streams had
    delivered until `settle()` (consumer.PlanConsumer.wait_settled)."""

    def __init__(self) -> None:
        self.settled = asyncio.Event()

    async def wait_settled(self) -> None:
        await self.settled.wait()


class OneConsumerRegistry:
    """The part of `ConsumerRegistry` the SSE route uses: `get(plan_id)`."""

    def __init__(self, plan_id: uuid.UUID, consumer: WindingDownConsumer) -> None:
        self.plan_id = plan_id
        self.consumer: WindingDownConsumer | None = consumer

    def get(self, plan_id: uuid.UUID) -> WindingDownConsumer | None:
        return self.consumer if plan_id == self.plan_id else None


def install_registry(app: FastAPI, registry: OneConsumerRegistry) -> None:
    planner: PlannerServices = app.state.planner
    planner.registry = cast(consumer.ConsumerRegistry, registry)


async def test_the_end_waits_for_the_live_consumer_to_store_what_it_had_received(
    app: FastAPI, hub: PlanHub, plan_rows: PlanRows
) -> None:
    """The consumer commits its terminal decision (the hub's `PlanEnded`), then stores events
    its thread streams had already delivered: the browser gets them before `end`."""
    record = await plan_rows.add_plan()
    await plan_rows.add_event(record.id, 0)
    winding_down = WindingDownConsumer()
    install_registry(app, OneConsumerRegistry(record.id, winding_down))

    async with open_stream(app, record.id) as stream:
        assert seqs(await events(stream, 1)) == [0]
        await plan_rows.add_event(record.id, 1, title="Turno concluso")
        await plan_rows.set_status(record.id, PlanStatus.INTERRUPTED)
        hub.end(record.id, PlanStatus.INTERRUPTED)
        await settle()
        late = await plan_rows.add_event(record.id, 2, title="Ragionamento in corso")
        hub.publish(record.id, late)  # after the end: the subscription has stopped
        winding_down.settled.set()

        assert seqs(await events(stream, 2)) == [1, 2]
        end = await stream.event()
        assert (end.event, end.json) == ("end", {"status": "interrupted"})
        await stream.expect_closed()


async def test_a_terminal_plan_with_a_live_consumer_waits_for_it_before_the_replay(
    app: FastAPI, plan_rows: PlanRows
) -> None:
    record = await plan_rows.add_plan(status=PlanStatus.READY)
    await plan_rows.add_event(record.id, 0)
    winding_down = WindingDownConsumer()
    install_registry(app, OneConsumerRegistry(record.id, winding_down))

    async with open_stream(app, record.id) as stream:
        await settle()
        await plan_rows.add_event(record.id, 1)  # stored by the winding-down consumer
        winding_down.settled.set()

        assert seqs(await events(stream, 2)) == [0, 1]
        assert (await stream.event()).json == {"status": "ready"}
        await stream.expect_closed()


async def test_a_consumer_that_never_settles_delays_the_end_only_so_long(
    app: FastAPI, hub: PlanHub, plan_rows: PlanRows, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(routes, "END_SETTLE_SECONDS", 0.05)
    record = await plan_rows.add_plan()
    install_registry(app, OneConsumerRegistry(record.id, WindingDownConsumer()))

    async with open_stream(app, record.id) as stream:
        await settle()
        await plan_rows.set_status(record.id, PlanStatus.FAILED)
        hub.end(record.id, PlanStatus.FAILED)
        assert (await stream.event()).json == {"status": "failed"}
        await stream.expect_closed()


async def test_ping_comment_every_interval(
    app: FastAPI, plan_rows: PlanRows, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(routes, "PING_SECONDS", 0.05)
    record = await plan_rows.add_plan()

    async with open_stream(app, record.id) as stream:
        first, second = await stream.message(), await stream.message()

    assert first.comments == ["ping"]
    assert (first.id, first.event, first.data) == (None, None, None)
    assert second.comments == ["ping"]


async def test_disconnect_closes_the_subscription_and_holds_no_connection(
    app: FastAPI, hub: PlanHub, plan_rows: PlanRows
) -> None:
    record = await plan_rows.add_plan()
    await plan_rows.add_event(record.id, 0)
    engine: AsyncEngine = app.state.engine

    stream = SseStream(app, f"/plans/{record.id}/events", {})
    await stream.open()
    assert seqs(await events(stream, 1)) == [0]
    await until(lambda: hub.subscriber_count(record.id) == 1)
    await settle()
    # The request's DB session was released before streaming; the replay used short sessions.
    pool = engine.sync_engine.pool
    assert isinstance(pool, QueuePool)
    assert pool.checkedout() == 0

    await stream.disconnect()

    assert hub.subscriber_count(record.id) == 0


async def test_another_users_plan_is_404_before_streaming(
    app: FastAPI, hub: PlanHub, plan_rows: PlanRows
) -> None:
    record = await plan_rows.add_plan(user_email="other@example.com")

    stream = SseStream(app, f"/plans/{record.id}/events", {})
    await stream.open()

    assert stream.status == 404
    assert json.loads(await stream.body()) == {
        "detail": {"code": "plan_not_found", "message": "Questo piano non c'è.", "data": None}
    }
    await stream.finished()
    assert hub.subscriber_count(record.id) == 0


async def test_a_deleted_plan_closes_the_stream(
    app: FastAPI, plan_rows: PlanRows, monkeypatch: pytest.MonkeyPatch
) -> None:
    record = await plan_rows.add_plan()

    async def gone(planner: PlannerServices, plan_id: uuid.UUID) -> PlanStatus | None:
        return None

    monkeypatch.setattr(routes, "_read_status", gone)

    async with open_stream(app, record.id) as stream:
        await stream.expect_closed()


# --- end to end through the real wiring -----------------------------------------------------------


async def test_a_plan_end_to_end_through_the_real_wiring(
    make_app: AppFactory,
    make_settings: Callable[..., Settings],
    db_session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """POST /plans, the SSE stream until `end`, then GET /plans/{id}, /trip and /plans, with the
    real lifespan, sessions, consumer and hub driven by the fake Managed Agents client through
    `make_app(client=...)`. Offline like `app.cli replay`: the dev trip.json fallback, the
    fixture lockfile, FX from the cache only, no resume of other plans."""
    start_planner = sessions.start_planner

    async def offline_start_planner(settings: Settings, **kwargs: Any) -> PlannerServices:
        return await start_planner(settings, **{**kwargs, "fx_offline": True, "resume": False})

    monkeypatch.setattr(sessions, "start_planner", offline_start_planner)
    settings = make_settings(
        trip_schema_url=DEV_FALLBACK_SCHEMA_PATH.as_uri(),
        lockfile_path=REPLAY_LOCKFILE_DIR / "claude-lock.development.json",
    )
    fake = FakeManagedAgentsClient.from_scenario("happy_path")
    frontend = settings.frontend_origin
    try:
        async with make_app(settings=settings, client=fake) as app:
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as http:
                created = await http.post(
                    "/plans", json=dict(fake.meta["request"]), headers={"Origin": frontend}
                )
                assert created.status_code == 201, created.text
                plan_id = uuid.UUID(created.json()["id"])

                async with open_stream(app, plan_id) as stream:
                    received: list[SseMessage] = []
                    while (message := await stream.event()).event is None:
                        received.append(message)
                    assert (message.event, message.json) == ("end", {"status": "ready"})
                    await stream.expect_closed()

                async with db_session_factory() as db:
                    stored = await db.scalar(
                        select(func.count())
                        .select_from(EventRecord)
                        .where(EventRecord.plan_id == plan_id)
                    )
                    record = await db.get(PlanRecord, plan_id)
                assert record is not None
                assert record.plan is not None
                assert int(stored or 0) > 10  # the whole scenario, not just the start event
                # Every stored event exactly once, in order, from seq 0.
                assert seqs(received) == list(range(int(stored or 0)))
                titles = [UIEvent.model_validate_json(m.data or "").title for m in received]
                assert titles[0] == sessions.TITLE_PLAN_CREATED

                detail = (await http.get(f"/plans/{plan_id}")).json()
                assert detail["status"] == "ready"
                tracker = settings.triptracker_origin
                assert detail["import_url"] == f"{tracker}/import?plan={plan_id}"
                assert detail["budget_cents"] == settings.session_budget_cents
                assert detail["plan"] == record.plan
                assert len(detail["booking_links"]) == len(record.plan["bookings"])

                trip = await http.get(
                    f"/plans/{plan_id}/trip", headers={"Origin": settings.triptracker_origin}
                )
                assert trip.status_code == 200
                assert trip.json() == record.trip
                assert trip.headers["access-control-allow-origin"] == settings.triptracker_origin

                listed = (await http.get("/plans")).json()["plans"]
                assert [(p["id"], p["status"]) for p in listed] == [(str(plan_id), "ready")]
                assert listed[0]["title"] == record.plan["title"]
    finally:
        await fake.shutdown()
    assert not fake.mismatches
