"""One consumer per plan across processes: the plan's lease (`consumer.PlanLease`, a Postgres
session-level advisory lock) and the takeover during a Railway redeploy.

Two processes are two `ConsumerRegistry`s with their own engine on the same test database and
the same `FakeManagedAgentsClient` (one remote session). Every Managed Agents call a consumer
makes goes through a `GuardedClient`, which records any call made while that consumer did not
hold the plan's lease: there must be none.
"""

from __future__ import annotations

import asyncio
import dataclasses
import uuid
from collections.abc import AsyncIterator, Callable, Mapping
from typing import Any, cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app import consumer as consumer_module
from app.config import Settings
from app.consumer import (
    ConsumerRegistry,
    EventSink,
    PlanConsumer,
    PlanLease,
    PlanUpdate,
    StatusChange,
    backend_event,
    backend_event_id,
    plan_lease_key,
    set_plan_status,
)
from app.db import PlanStatus, create_session_factory
from app.events import EventKind
from app.ma_client import ManagedAgentsClient
from tests.fakes import FIXTURES_DIR, PROTOCOL_METHODS, FakeManagedAgentsClient, load_jsonl
from tests.test_consumer import (
    BRIEF,
    NOW,
    RUN_TIMEOUT,
    SID,
    Harness,
    HarnessFactory,
    api_keys,
    harness_factory,
    offline_http,
    owned_keys,
)

RETRY_SECONDS = 0.05
"""`consumer.LEASE_RETRY_SECONDS` in these tests."""


@pytest.fixture(autouse=True)
def fast_lease_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(consumer_module, "LEASE_RETRY_SECONDS", RETRY_SECONDS)


@pytest.fixture
async def other_process_factory(
    test_database_url: str, db_session_factory: async_sessionmaker[AsyncSession]
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """A second engine on the (already emptied) test database: the other process."""
    del db_session_factory  # requested for the emptied tables
    engine = create_async_engine(test_database_url, poolclass=NullPool)
    try:
        yield create_session_factory(engine)
    finally:
        await engine.dispose()


@pytest.fixture
async def two_processes(
    db_session_factory: async_sessionmaker[AsyncSession],
    other_process_factory: async_sessionmaker[AsyncSession],
    make_settings: Callable[..., Settings],
) -> AsyncIterator[tuple[HarnessFactory, HarnessFactory]]:
    async with offline_http() as http:
        yield (
            harness_factory(db_session_factory, make_settings, http),
            harness_factory(other_process_factory, make_settings, http),
        )


class GuardedClient:
    """The shared fake, as one process sees it: records every Protocol call, and as a
    violation every call made while `allowed()` is False (the consumer had no lease)."""

    def __init__(self, inner: FakeManagedAgentsClient, allowed: Callable[[], bool]) -> None:
        self._inner = inner
        self._allowed = allowed
        self.calls: list[str] = []
        self.violations: list[str] = []

    def __getattr__(self, name: str) -> Any:
        attribute = getattr(self._inner, name)
        if name not in PROTOCOL_METHODS:
            return attribute

        def call(*args: Any, **kwargs: Any) -> Any:
            self.calls.append(name)
            if not self._allowed():
                self.violations.append(name)
            return attribute(*args, **kwargs)

        return call


@dataclasses.dataclass
class Process:
    """One process: its registry, its guarded view of the fake and its consumer of the plan."""

    harness: Harness
    registry: ConsumerRegistry
    client: GuardedClient
    consumer: PlanConsumer | None = None

    def start(self, plan_id: uuid.UUID, *, first_message: str | None = None) -> PlanConsumer:
        self.consumer = self.registry.start(plan_id, SID, first_message=first_message)
        return self.consumer


def process(build: HarnessFactory, fake: FakeManagedAgentsClient) -> Process:
    """A process on `fake`: its own harness (engine, hub) and a guarded view of the fake that
    allows a call only while this process's consumer holds the plan's lease."""
    harness = build(fake)
    proc: Process | None = None

    def leased() -> bool:
        consumer = proc.consumer if proc is not None else None
        return consumer is not None and consumer.leased

    client = GuardedClient(fake, leased)
    deps = dataclasses.replace(harness.deps, client=cast(ManagedAgentsClient, client))
    proc = Process(harness, ConsumerRegistry(deps), client)
    return proc


def with_checkpoint(
    name: str, checkpoint: str, before: Callable[[Mapping[str, Any]], bool]
) -> FakeManagedAgentsClient:
    """The scenario with a `checkpoint` step before the first step matching `before`."""
    steps, _ = load_jsonl(FIXTURES_DIR / f"{name}.jsonl")
    index = next(i for i, step in enumerate(steps) if before(step))
    steps.insert(index, {"op": "checkpoint", "name": checkpoint})
    return FakeManagedAgentsClient(steps, await_timeout=10, source=f"{name}.jsonl")


def is_submit_plan(step: Mapping[str, Any]) -> bool:
    event = step.get("event") or {}
    return event.get("type") == "agent.custom_tool_use" and event.get("name") == "submit_plan"


HOLD_SCRIPT: list[dict[str, Any]] = [
    {"op": "emit", "event": {"type": "session.status_running"}},
    {"op": "checkpoint", "name": "hold"},
    {"op": "usage", "list_cost_cents": 5},
    {"op": "emit", "event": {"type": "session.status_idle", "stop_reason": {"type": "end_turn"}}},
]
"""A running session that waits at `hold`, then ends its turn without a plan (`failed`)."""


async def until(predicate: Callable[[], bool], *, within: float = RUN_TIMEOUT) -> None:
    """Poll `predicate` (a consumer property: nothing to await on) until it holds."""
    async with asyncio.timeout(within):
        while not predicate():  # noqa: ASYNC110
            await asyncio.sleep(0.01)


class OverlapSampler:
    """Samples, until stopped, whether both consumers held the lease at the same instant."""

    def __init__(self, first: Process, second: Process) -> None:
        self.overlaps = 0
        self._processes = (first, second)
        self._task = asyncio.create_task(self._run())

    async def _run(self) -> None:
        while True:
            if all(p.consumer is not None and p.consumer.leased for p in self._processes):
                self.overlaps += 1
            await asyncio.sleep(0.002)

    async def stop(self) -> int:
        self._task.cancel()
        await asyncio.gather(self._task, return_exceptions=True)
        return self.overlaps


# --- the lease itself ---------------------------------------------------------------------------


def test_the_lease_key_is_stable_across_processes_and_versions() -> None:
    """A deploy's old and new process must compute the same key: pinned."""
    plan_id = uuid.UUID("7f3c0000-0000-4000-8000-000000000001")
    assert plan_lease_key(plan_id) == 5581235110831437305
    assert plan_lease_key(uuid.UUID("7f3c0000-0000-4000-8000-000000000002")) == (613539366889244074)
    keys = {plan_lease_key(uuid.uuid4()) for _ in range(1000)}
    assert len(keys) == 1000
    assert all(-(2**63) <= key < 2**63 for key in keys)  # a Postgres bigint


async def test_a_lease_is_exclusive_per_plan_and_released_on_release(
    db_session_factory: async_sessionmaker[AsyncSession],
    other_process_factory: async_sessionmaker[AsyncSession],
) -> None:
    plan_id, other_plan = uuid.uuid4(), uuid.uuid4()
    first = PlanLease(plan_id, db_session_factory)
    second = PlanLease(plan_id, other_process_factory)
    unrelated = PlanLease(other_plan, other_process_factory)
    try:
        assert await first.try_acquire()
        assert await first.try_acquire()  # already held: still True, no second lock
        assert first.held
        assert not await second.try_acquire()
        assert not second.held
        assert await unrelated.try_acquire()  # another plan: no contention

        await first.release()
        assert not first.held
        await first.release()  # idempotent
        assert await second.try_acquire()
        assert not await first.try_acquire()
    finally:
        for lease in (first, second, unrelated):
            await lease.release()


# --- consumers in two processes -----------------------------------------------------------------


async def test_two_processes_never_follow_a_plan_together_and_the_new_one_takes_over(
    two_processes: tuple[HarnessFactory, HarnessFactory],
) -> None:
    """A redeploy: the old process follows the plan; the new one starts its consumer (resume)
    while the old one still runs. The new consumer opens nothing until the old process shuts
    down, then resumes from the history and finishes the plan; nothing is stored twice."""
    fake = with_checkpoint("happy_path", "handover", is_submit_plan)
    build_old, build_new = two_processes
    old, new = process(build_old, fake), process(build_new, fake)
    plan_id = await old.harness.create_plan()

    sampler = OverlapSampler(old, new)
    try:
        old_consumer = old.start(plan_id, first_message=BRIEF)
        await fake.reached("handover")
        assert old_consumer.leased

        new_consumer = new.start(plan_id)  # the new process resumes the running plans
        await asyncio.sleep(RETRY_SECONDS * 6)  # several retries
        assert not new_consumer.leased
        assert not new_consumer.done
        assert new.client.calls == []  # no stream, no listing: it does not follow the plan

        await old.registry.aclose()  # the old process shuts down (SIGTERM)
        assert old_consumer.done
        await until(lambda: new_consumer.leased)
        fake.release("handover")
        await until(lambda: new_consumer.done)
        await fake.wait_until_done()
        fake.assert_script_done()
    finally:
        overlaps = await sampler.stop()
        await old.registry.aclose()
        await new.registry.aclose()
        await fake.shutdown()

    assert overlaps == 0
    assert old.client.violations == []
    assert new.client.violations == []
    assert "stream_session" in new.client.calls
    record = await new.harness.plan(plan_id)
    assert record.status == PlanStatus.READY
    rows = await new.harness.events(plan_id)
    keys = api_keys(rows)
    assert len(keys) == len(set(keys))
    # Archiving after `ready` emits `session.status_terminated`, which nobody follows any more.
    assert set(keys) == owned_keys(fake, plan_id, skip_types=["session.status_terminated"])
    assert [row.seq for row in rows] == list(range(len(rows)))
    assert fake.archived == [SID]


async def test_two_processes_resuming_together_elect_one_consumer(
    two_processes: tuple[HarnessFactory, HarnessFactory],
) -> None:
    """Both processes resume the same running plan at the same time: exactly one follows it;
    the other takes over only when the first stops."""
    fake = FakeManagedAgentsClient(HOLD_SCRIPT, await_timeout=10)
    build_a, build_b = two_processes
    a, b = process(build_a, fake), process(build_b, fake)
    plan_id = await a.harness.create_plan()

    sampler = OverlapSampler(a, b)
    try:
        first, second = a.start(plan_id), b.start(plan_id)
        await until(lambda: first.leased or second.leased)
        await fake.reached("hold")
        leader, follower = (a, b) if first.leased else (b, a)
        assert leader.consumer is not None
        assert follower.consumer is not None
        await asyncio.sleep(RETRY_SECONDS * 4)
        assert not follower.consumer.leased
        assert follower.client.calls == []

        await leader.registry.aclose()
        await until(lambda: follower.consumer is not None and follower.consumer.leased)
        fake.release("hold")
        await until(lambda: follower.consumer is not None and follower.consumer.done)
        fake.assert_script_done()
    finally:
        overlaps = await sampler.stop()
        await a.registry.aclose()
        await b.registry.aclose()
        await fake.shutdown()

    assert overlaps == 0
    assert a.client.violations == []
    assert b.client.violations == []
    record = await a.harness.plan(plan_id)
    assert record.status == PlanStatus.FAILED  # end_turn without a plan, decided once
    rows = await a.harness.events(plan_id)
    keys = api_keys(rows)
    assert len(keys) == len(set(keys))


async def test_a_waiting_consumer_stops_when_the_plan_ends_in_the_other_process(
    two_processes: tuple[HarnessFactory, HarnessFactory],
) -> None:
    """It stops waiting, and relays what the other process stored to its own hub (the latest
    event, then the end), so a browser connected to this process follows the plan too."""
    fake = FakeManagedAgentsClient(HOLD_SCRIPT, await_timeout=10)
    build_a, build_b = two_processes
    a, b = process(build_a, fake), process(build_b, fake)
    plan_id = await a.harness.create_plan()
    try:
        leader = a.start(plan_id)
        await fake.reached("hold")
        assert leader.leased
        waiting = b.start(plan_id)
        await asyncio.sleep(RETRY_SECONDS * 3)
        assert not waiting.done

        # The other process decides the plan (here: as if the user interrupted a paused plan).
        await set_plan_status(
            a.harness.factory,
            a.harness.hub,
            plan_id,
            StatusChange(PlanStatus.INTERRUPTED, reason="Interrotto da te."),
            title="Piano interrotto",
            event_key="interrupted:elsewhere",
        )
        await until(lambda: waiting.done, within=RETRY_SECONDS * 40)
        await asyncio.wait_for(waiting.wait_settled(), timeout=1)
        await asyncio.wait_for(waiting.wait_started(), timeout=1)  # never raises
        assert b.client.calls == []
        assert not waiting.leased
        assert leader.leased  # the leader is untouched

        stored = await b.harness.events(plan_id)
        relayed = b.harness.hub.published
        assert relayed  # the latest event, at every period it grew
        assert relayed[-1].seq == stored[-1].seq
        assert relayed[-1].title == "Piano interrotto"
        assert b.harness.hub.ended == [(plan_id, PlanStatus.INTERRUPTED)]
    finally:
        await a.registry.aclose()
        await b.registry.aclose()
        await fake.shutdown()


async def test_the_lease_is_free_again_once_the_consumer_finished(
    two_processes: tuple[HarnessFactory, HarnessFactory],
) -> None:
    build, _ = two_processes
    fake = FakeManagedAgentsClient.from_scenario("happy_path", await_timeout=10)
    h = build(fake)
    plan_id = await h.create_plan()
    consumer = h.consumer(plan_id)
    async with asyncio.timeout(RUN_TIMEOUT):
        assert await consumer.run() is PlanStatus.READY
    assert not consumer.leased
    lease = PlanLease(plan_id, h.factory)
    try:
        assert await lease.try_acquire()
    finally:
        await lease.release()


async def test_an_interrupt_asked_through_the_other_process_reaches_the_consumer(
    two_processes: tuple[HarnessFactory, HarnessFactory],
) -> None:
    """During a redeploy the user's interrupt may reach the process that does not follow the
    plan: it stores `interrupt_requested_at` and sends `user.interrupt`, but can't tell the
    consumer in memory. The consumer re-reads the row before deciding: `interrupted`, never
    `failed`."""
    build, _ = two_processes
    fake = FakeManagedAgentsClient.from_scenario("interrupt", await_timeout=10)
    h = build(fake)
    plan_id = await h.create_plan()
    consumer = h.consumer(plan_id)
    task = asyncio.create_task(consumer.run())
    try:
        await fake.reached("working")
        # What sessions.request_interrupt does in the other process (no live consumer there).
        await EventSink(plan_id, session_factory=h.factory, hub=h.hub).emit(
            backend_event(EventKind.STATUS, "Interruzione richiesta", ts=NOW),
            ma_event_id=backend_event_id(plan_id, "status", "interrupt-requested:elsewhere"),
            update=PlanUpdate(interrupt_requested_at=NOW),
        )
        await fake.send_interrupt(SID)
        fake.release("working")
        async with asyncio.timeout(RUN_TIMEOUT):
            status = await task
    finally:
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        await fake.shutdown()
    assert status is PlanStatus.INTERRUPTED
    record = await h.plan(plan_id)
    assert record.failure_reason == consumer_module.REASON_INTERRUPTED
    fake.assert_script_done()
