"""In-memory, per-plan pub/sub of UI events for the browsers watching a plan live.

Spec: "Backend FastAPI", consumer step 3 ("si pubblica su un canale in memoria a cui sono
iscritti i browser connessi"), "SSE verso il browser" and "Un solo processo": the live channel
lives in this process, so Railway runs a single replica (Postgres LISTEN/NOTIFY would be needed
with more; not for one user). During a redeploy two processes overlap briefly: consumer.PlanLease
keeps one consumer per plan, and a waiting consumer relays stored events to its own hub
(docs/backend-interfaces.md, decision 31).

Contract:

- The consumer persists a `UIEvent` first, commits, then `publish()`es it. Postgres is the
  source of truth; the hub only shortens the path to an open SSE connection. Nothing published
  here is ever lost for good: a subscriber that misses events re-reads them from `events`.
- `publish()` never blocks and never raises because of a slow subscriber: each subscription has
  a bounded queue, and a subscriber whose queue overflows is marked lagged and ends with
  `SubscriptionLaggedError`; the SSE route then replays from Postgres after the last `seq` it
  sent and subscribes again.
- `end()` tells subscribers the plan reached a terminal status (ready, failed, blocked,
  interrupted): their iteration yields one `PlanEnded` and stops. It is published when the
  status commits; the consumer may store a few already-received events after it, which the SSE
  route picks up from Postgres before its `end` (`PlanConsumer.wait_settled`). `budget_paused`
  is not terminal (the user can continue), so it is published as a normal status event only.

- Order is per publisher, not global: the consumer, sessions and jobs each publish after their
  own commit, so a subscriber can receive seq N+1 before seq N. Subscribers detect the gap and
  fill it from Postgres (below).

SSE route pattern that never loses or duplicates an event (routes.event_stream):

    with hub.subscribe(plan_id) as live:           # 1. subscribe first
        backlog = await load_events_after(...)     # 2. read Postgres after Last-Event-ID
        send(backlog); last = backlog[-1].seq      # 3. send the backlog
        async for item in live:                    # 4. then live:
            if item.seq <= last: continue          #    already sent
            if item.seq > last + 1:                #    a gap: an earlier event is committed
                send(load_events_after(last))      #    but not published yet -> Postgres
            else: send(item)                       #    (`last` follows what was sent)

Single event loop, no locks: all methods are called from the loop's thread.
"""

from __future__ import annotations

import asyncio
import uuid
from collections import deque
from collections.abc import AsyncIterator, Iterator
from contextlib import contextmanager
from dataclasses import dataclass

import structlog

from app.db import PlanStatus
from app.events import UIEvent

DEFAULT_QUEUE_SIZE = 1000
"""Per-subscriber buffer. A plan produces a few hundred events; overflow means a stuck client."""

log = structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class PlanEnded:
    """Last item of a subscription: the plan reached terminal `status`. A consumer winding down
    may still store the events its streams had already delivered: the SSE route waits for it
    to settle and catches up from Postgres before sending `end` (routes.event_stream)."""

    plan_id: uuid.UUID
    status: PlanStatus


HubMessage = UIEvent | PlanEnded


class SubscriptionLaggedError(Exception):
    """Raised by a subscription's iterator when its queue overflowed and events were dropped.
    The SSE route catches it, replays from Postgres and subscribes again."""


class Subscription:
    """One subscriber's view of one plan: `async for message in subscription`.

    Yields `UIEvent`s in publish order, then at most one `PlanEnded` after which iteration
    stops. Raises `SubscriptionLaggedError` once if it fell behind. Obtained only through
    `PlanHub.subscribe()`, which also unregisters it.

    The buffer holds at most `maxsize` events. On overflow the buffered events are dropped
    (the subscriber re-reads them from Postgres) and the next `__anext__` raises
    `SubscriptionLaggedError`; after that the subscription yields nothing more. `PlanEnded` is
    kept apart from the buffer, so a full buffer never hides the end of a plan.
    """

    plan_id: uuid.UUID

    def __init__(self, plan_id: uuid.UUID, *, maxsize: int = DEFAULT_QUEUE_SIZE) -> None:
        if maxsize < 1:
            msg = f"maxsize must be at least 1, got {maxsize}"
            raise ValueError(msg)
        self.plan_id = plan_id
        self._maxsize = maxsize
        self._buffer: deque[UIEvent] = deque()
        self._ended: PlanEnded | None = None
        self._lagged = False
        self._closed = False
        self._finished = False
        self._wakeup = asyncio.Event()

    def __aiter__(self) -> AsyncIterator[HubMessage]:
        return self

    async def __anext__(self) -> HubMessage:
        """Wait for the next message. Raises `StopAsyncIteration` after `PlanEnded` was yielded
        or after `close()`; `SubscriptionLaggedError` after an overflow."""
        while True:
            if self._closed or self._finished:
                raise StopAsyncIteration
            if self._lagged:
                self._finished = True
                raise SubscriptionLaggedError(
                    f"subscriber of plan {self.plan_id} fell more than {self._maxsize} "
                    "events behind"
                )
            if self._buffer:
                return self._buffer.popleft()
            if self._ended is not None:
                self._finished = True
                return self._ended
            self._wakeup.clear()
            await self._wakeup.wait()

    def close(self) -> None:
        """Stop the iteration (client disconnected). Idempotent."""
        if self._closed:
            return
        self._closed = True
        self._buffer.clear()
        self._wakeup.set()

    @property
    def lagged(self) -> bool:
        """True once the buffer overflowed (tests, logs)."""
        return self._lagged

    # Called by PlanHub only (same event loop, no locks needed).

    def _deliver(self, event: UIEvent) -> None:
        if self._closed or self._lagged or self._ended is not None:
            return
        if len(self._buffer) >= self._maxsize:
            self._lagged = True
            self._buffer.clear()
            log.warning("hub_subscriber_lagged", plan_id=str(self.plan_id), limit=self._maxsize)
        else:
            self._buffer.append(event)
        self._wakeup.set()

    def _deliver_end(self, ended: PlanEnded) -> None:
        if self._closed or self._ended is not None:
            return
        self._ended = ended
        self._wakeup.set()


class PlanHub:
    """The process-wide hub, created once in the application lifespan (`app.state.hub`, also
    held by `sessions.PlannerServices`)."""

    def __init__(self, *, queue_size: int = DEFAULT_QUEUE_SIZE) -> None:
        if queue_size < 1:
            msg = f"queue_size must be at least 1, got {queue_size}"
            raise ValueError(msg)
        self._queue_size = queue_size
        self._subscribers: dict[uuid.UUID, list[Subscription]] = {}

    def publish(self, plan_id: uuid.UUID, event: UIEvent) -> None:
        """Deliver `event` to every current subscriber of `plan_id` (no-op without
        subscribers). Call only after the event is committed to `events`."""
        for subscription in tuple(self._subscribers.get(plan_id, ())):
            subscription._deliver(event)

    def end(self, plan_id: uuid.UUID, status: PlanStatus) -> None:
        """Deliver `PlanEnded(plan_id, status)` to every current subscriber of `plan_id` (their
        iteration stops after it). Call after the terminal status is committed. A later
        subscriber learns the status from Postgres, not from the hub."""
        ended = PlanEnded(plan_id=plan_id, status=status)
        for subscription in tuple(self._subscribers.get(plan_id, ())):
            subscription._deliver_end(ended)

    @contextmanager
    def subscribe(self, plan_id: uuid.UUID) -> Iterator[Subscription]:
        """Register a subscription for `plan_id` for the duration of the `with` block, then
        close and unregister it (also on exceptions and client disconnects)."""
        subscription = Subscription(plan_id, maxsize=self._queue_size)
        self._subscribers.setdefault(plan_id, []).append(subscription)
        try:
            yield subscription
        finally:
            subscription.close()
            subscribers = self._subscribers.get(plan_id)
            if subscribers is not None:
                if subscription in subscribers:
                    subscribers.remove(subscription)
                if not subscribers:
                    del self._subscribers[plan_id]

    def subscriber_count(self, plan_id: uuid.UUID) -> int:
        """How many subscriptions are open for `plan_id` (tests, logs)."""
        return len(self._subscribers.get(plan_id, ()))
