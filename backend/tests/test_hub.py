"""The in-memory per-plan hub (app/hub.py): delivery, end of plan, overflow, cleanup."""

from __future__ import annotations

import asyncio
import datetime as dt
import uuid

import pytest

from app.db import PlanStatus
from app.events import AgentName, EventKind, UIEvent
from app.hub import PlanEnded, PlanHub, Subscription, SubscriptionLaggedError


def event(seq: int) -> UIEvent:
    return UIEvent(
        seq=seq,
        ts=dt.datetime(2026, 10, 12, 10, 0, tzinfo=dt.UTC),
        agent=AgentName.COORDINATOR,
        kind=EventKind.STATUS,
        title=f"Evento {seq}",
    )


async def drain(subscription: Subscription) -> list[object]:
    """Everything the subscription yields until it stops (with a timeout guard)."""

    async def collect() -> list[object]:
        return [message async for message in subscription]

    return await asyncio.wait_for(collect(), timeout=2)


async def test_publish_without_subscribers_is_a_no_op() -> None:
    hub = PlanHub()

    hub.publish(uuid.uuid4(), event(0))
    hub.end(uuid.uuid4(), PlanStatus.READY)


async def test_subscriber_gets_events_in_publish_order_then_the_end() -> None:
    hub = PlanHub()
    plan_id = uuid.uuid4()
    with hub.subscribe(plan_id) as live:
        hub.publish(plan_id, event(1))
        hub.publish(plan_id, event(0))  # out of order: the hub keeps publish order
        hub.end(plan_id, PlanStatus.READY)

        messages = await drain(live)

    assert messages == [event(1), event(0), PlanEnded(plan_id, PlanStatus.READY)]


async def test_a_waiting_subscriber_is_woken_by_publish() -> None:
    hub = PlanHub()
    plan_id = uuid.uuid4()
    with hub.subscribe(plan_id) as live:
        pending = asyncio.ensure_future(anext(live))
        await asyncio.sleep(0)
        assert not pending.done()

        hub.publish(plan_id, event(0))

        assert await asyncio.wait_for(pending, timeout=1) == event(0)


async def test_every_subscriber_of_a_plan_gets_each_event_and_other_plans_none() -> None:
    hub = PlanHub()
    plan_id, other_plan = uuid.uuid4(), uuid.uuid4()
    with (
        hub.subscribe(plan_id) as first,
        hub.subscribe(plan_id) as second,
        hub.subscribe(other_plan) as unrelated,
    ):
        hub.publish(plan_id, event(0))
        hub.end(plan_id, PlanStatus.FAILED)

        assert await drain(first) == [event(0), PlanEnded(plan_id, PlanStatus.FAILED)]
        assert await drain(second) == [event(0), PlanEnded(plan_id, PlanStatus.FAILED)]
        unrelated.close()
        assert await drain(unrelated) == []


async def test_events_published_after_the_end_are_dropped() -> None:
    hub = PlanHub()
    plan_id = uuid.uuid4()
    with hub.subscribe(plan_id) as live:
        hub.end(plan_id, PlanStatus.INTERRUPTED)
        hub.publish(plan_id, event(7))
        hub.end(plan_id, PlanStatus.READY)  # a second end is ignored too

        assert await drain(live) == [PlanEnded(plan_id, PlanStatus.INTERRUPTED)]


async def test_overflow_raises_lagged_once_without_blocking_the_publisher() -> None:
    hub = PlanHub(queue_size=2)
    plan_id = uuid.uuid4()
    with hub.subscribe(plan_id) as slow, hub.subscribe(plan_id) as fast:
        hub.publish(plan_id, event(0))
        assert await anext(fast) == event(0)
        hub.publish(plan_id, event(1))
        hub.publish(plan_id, event(2))  # `slow` now holds 3 > 2 events: lagged
        assert await anext(fast) == event(1)
        assert await anext(fast) == event(2)

        assert slow.lagged
        with pytest.raises(SubscriptionLaggedError):
            await anext(slow)
        assert await drain(slow) == []  # once lagged, nothing more (the route resubscribes)
        assert not fast.lagged


async def test_a_full_but_not_overflowing_buffer_still_ends() -> None:
    hub = PlanHub(queue_size=2)
    plan_id = uuid.uuid4()
    with hub.subscribe(plan_id) as live:
        hub.publish(plan_id, event(0))
        hub.publish(plan_id, event(1))
        hub.end(plan_id, PlanStatus.READY)  # PlanEnded is kept apart from the buffer

        assert await drain(live) == [event(0), event(1), PlanEnded(plan_id, PlanStatus.READY)]


async def test_close_stops_a_waiting_iteration() -> None:
    hub = PlanHub()
    plan_id = uuid.uuid4()
    with hub.subscribe(plan_id) as live:
        pending = asyncio.ensure_future(anext(live))
        await asyncio.sleep(0)

        live.close()
        live.close()  # idempotent

        with pytest.raises(StopAsyncIteration):
            await asyncio.wait_for(pending, timeout=1)


async def test_subscribe_unregisters_on_exit_and_on_errors() -> None:
    hub = PlanHub()
    plan_id = uuid.uuid4()
    assert hub.subscriber_count(plan_id) == 0

    with hub.subscribe(plan_id) as first:
        with hub.subscribe(plan_id):
            assert hub.subscriber_count(plan_id) == 2
        assert hub.subscriber_count(plan_id) == 1
    assert hub.subscriber_count(plan_id) == 0
    assert await drain(first) == []  # closed by the context manager

    def fail_inside() -> None:
        with hub.subscribe(plan_id):
            assert hub.subscriber_count(plan_id) == 1
            raise RuntimeError("client went away")

    with pytest.raises(RuntimeError):
        fail_inside()
    assert hub.subscriber_count(plan_id) == 0


async def test_a_cancelled_reader_unregisters_its_subscription() -> None:
    hub = PlanHub()
    plan_id = uuid.uuid4()

    async def reader() -> None:
        with hub.subscribe(plan_id) as live:
            async for _ in live:
                pass

    task = asyncio.create_task(reader())
    await asyncio.sleep(0)
    assert hub.subscriber_count(plan_id) == 1

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert hub.subscriber_count(plan_id) == 0


def test_sizes_must_be_positive() -> None:
    with pytest.raises(ValueError, match="queue_size"):
        PlanHub(queue_size=0)
    with pytest.raises(ValueError, match="maxsize"):
        Subscription(uuid.uuid4(), maxsize=0)
