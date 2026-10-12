"""The local demo's Managed Agents client: the shipped scenarios, replayed at a watchable pace.

`DEMO_MODE=true` (development only, `app.config.Settings`) makes `sessions.start_planner` build
`DemoManagedAgentsClient`, imported lazily from here like `app.cli replay` imports the fake: the
web app can then be developed against every plan state without an API key, a lockfile, the
network or any cost. Each `create_session` starts a fresh `PacedFakeClient` playing the
scenario named in the session's metadata (`sessions.DEMO_SCENARIO_METADATA`, set from
`POST /plans?demo_scenario=...`, default `happy_path`), under a session id of its own
(`sessions.DEMO_SESSION_PREFIX` + a fresh id namespace), so any number of demo plans can run
side by side and be replayed into the same database.

Pacing: `PacedFakeClient` waits, before each scripted event, the gap between that event's
recorded `processed_at` and the previous one (at most `MAX_GAP_SECONDS`), times `pace`
(DEMO_PACE): happy_path takes about 75 s at 1.0. Events are re-stamped with the wall clock, so
the timeline shows when the demo ran.

The scenarios that wait for the user react to the real endpoints:

- `budget_reached` pauses (`budget_paused`) until POST /plans/{id}/continue raises the budget
  (its `await_call update_budget` step), then resumes;
- `interrupt` works until POST /plans/{id}/interrupt: the interrupt releases the script's
  checkpoint and the agents stop (`interrupted`).

An interrupt in any other scenario stops the script and idles every working thread and the
session with `end_turn`, like the real API, so "Interrompi" works everywhere. Steps that wait
for the user get `WAIT_FOR_USER_SECONDS` instead of their scripted timeout.

`restart_resume` is not offered: it needs the process to die halfway through a call.
"""

from __future__ import annotations

import asyncio
import contextlib
import datetime as dt
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping, Sequence
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from types import MappingProxyType
from typing import Any

from app import clock
from app.ma_client import (
    DEFAULT_LIST_LIMIT,
    PRIMARY_SCOPE,
    AgentPin,
    ApiRejectedError,
    EventPage,
    EventStream,
    ManagedAgentsClient,
    SessionInfo,
    SessionNotFoundError,
    ThreadInfo,
)
from app.sessions import DEFAULT_DEMO_SCENARIO, DEMO_SCENARIO_METADATA, DEMO_SESSION_PREFIX
from tests.fakes import (
    AUTO_STAMP_STEP,
    FIXTURES_DIR,
    FakeManagedAgentsClient,
    ScriptStep,
    _parse_instant,  # pyright: ignore[reportPrivateUsage]
    _Session,  # pyright: ignore[reportPrivateUsage]
    format_instant,
    load_jsonl,
)

EXCLUDED_SCENARIOS: frozenset[str] = frozenset({"restart_resume"})
"""Shipped scenarios the demo does not offer (see the module docstring)."""

MAX_GAP_SECONDS = 6.0
"""Longest wait between two scripted events at pace 1.0 (a recorded pause, such as the
minute `budget_reached` spends waiting for "Continua", is not replayed in full)."""

WAIT_FOR_USER_SECONDS = 3600.0
"""How long a script waits at a blocking step (the user's "Continua", the user's interrupt)."""

WIND_DOWN_STEP_SECONDS = 0.4
"""Pause between the idles of an interrupt's wind-down (times `pace`)."""

_BLOCKING_OPS = frozenset({"await", "await_call", "await_stream", "checkpoint"})
_USER_ACTION_OPS = frozenset({"await_call", "checkpoint"})


def demo_scenarios() -> tuple[str, ...]:
    """The scenario names `POST /plans?demo_scenario=` accepts: every shipped script in
    backend/tests/fixtures/ma except `EXCLUDED_SCENARIOS`, sorted."""
    return tuple(
        sorted(
            path.stem
            for path in FIXTURES_DIR.glob("*.jsonl")
            if path.stem not in EXCLUDED_SCENARIOS
        )
    )


class PacedFakeClient(FakeManagedAgentsClient):
    """One demo session: a `FakeManagedAgentsClient` whose script runs at the recorded pace
    (times `pace`), with wall-clock timestamps, and that reacts to the user's interrupt."""

    def __init__(
        self,
        script: Sequence[ScriptStep] = (),
        *,
        pace: float = 1.0,
        max_gap_seconds: float = MAX_GAP_SECONDS,
        now: Callable[[], dt.datetime] = clock.now,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        **kwargs: Any,
    ) -> None:
        """`pace` multiplies every recorded gap (capped at `max_gap_seconds`); `now` stamps the
        events; `sleep` waits (tests record it)."""
        super().__init__(script, **kwargs)
        if pace <= 0:
            msg = f"pace must be > 0, got {pace}"
            raise ValueError(msg)
        self.pace = pace
        self.max_gap_seconds = max_gap_seconds
        self._now = now
        self._sleep = sleep
        self._last_scripted: dt.datetime | None = None
        self._wind_down: asyncio.Task[None] | None = None
        self.wound_down = False
        """True once an interrupt stopped the script (`_stop_and_idle`)."""

    # --- pacing ---------------------------------------------------------------------------

    async def _run_step(self, step: Mapping[str, Any]) -> None:
        op = step["op"]
        if op in ("emit", "usage"):
            step = await self._paced(step)
        elif op in _BLOCKING_OPS and "timeout" in step:
            step = {key: value for key, value in step.items() if key != "timeout"}
        await super()._run_step(step)
        if op in _USER_ACTION_OPS:
            self._last_scripted = None  # what follows the user's action comes at once

    async def _paced(self, step: Mapping[str, Any]) -> dict[str, Any]:
        """Wait the recorded gap before `step`, then return it stamped with the wall clock."""
        event: Mapping[str, Any] = step.get("event") or {}
        recorded = event.get("processed_at") if step["op"] == "emit" else step.get("processed_at")
        scripted = _parse_instant(recorded)
        if scripted is not None:
            if self._last_scripted is not None:
                gap = (scripted - self._last_scripted).total_seconds()
                delay = min(max(gap, 0.0), self.max_gap_seconds) * self.pace
                if delay > 0:
                    await self._sleep(delay)
            self._last_scripted = scripted
        stamp = format_instant(self._live_stamp(self._session))
        if step["op"] == "emit":
            return {**step, "event": {**event, "processed_at": stamp}}
        return {**step, "processed_at": stamp}

    def _live_stamp(self, session: _Session) -> dt.datetime:
        now = self._now().astimezone(dt.UTC)
        if session.latest is not None and now <= session.latest:
            return session.latest + AUTO_STAMP_STEP
        return now

    def _next_stamp(self, session: _Session) -> dt.datetime:
        stamp = self._live_stamp(session)
        session.latest = stamp
        return stamp

    # --- the user's interrupt ---------------------------------------------------------------

    async def send_interrupt(self, session_id: str, thread_id: str | None = None) -> None:
        await super().send_interrupt(session_id, thread_id)
        if session_id != self.session_id or thread_id is not None:
            return
        checkpoint = self.at_checkpoint
        if checkpoint is not None:
            self.release(checkpoint)  # the script waits for this interrupt (interrupt.jsonl)
            return
        if self.done or self.mismatches or self._wind_down is not None:
            return
        self._wind_down = asyncio.get_running_loop().create_task(
            self._stop_and_idle(), name=f"demo-interrupt-{self.session_id}"
        )

    async def _stop_and_idle(self) -> None:
        """Stop the script where it is, then idle every working thread and the session with
        `end_turn` (thread scope first, then the copy cross-posted on the session stream)."""
        driver = self._driver
        if driver is not None and not driver.done():
            driver.cancel()
            await asyncio.gather(driver, return_exceptions=True)
        self.wound_down = True
        session = self._session
        for thread in list(session.threads.values()):
            if thread.archived or thread.status != "running":
                continue
            await self._sleep(WIND_DOWN_STEP_SECONDS * self.pace)
            idle = {
                "type": "session.thread_status_idle",
                "session_thread_id": thread.id,
                "agent_name": thread.agent_name,
                "stop_reason": {"type": "end_turn"},
            }
            self._emit(session, idle, thread.id)
            self._emit(session, idle, PRIMARY_SCOPE)
        await self._sleep(WIND_DOWN_STEP_SECONDS * self.pace)
        self._emit(session, {"type": "session.status_idle", "stop_reason": {"type": "end_turn"}})

    async def shutdown(self) -> None:
        task = self._wind_down
        if task is not None and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        await super().shutdown()


class DemoManagedAgentsClient:
    """The `ManagedAgentsClient` of `DEMO_MODE`: one `PacedFakeClient` per created session,
    every call routed to the session's own fake (an unknown session id is a 404, as for a
    session the platform no longer has: demo sessions live only as long as the process)."""

    def __init__(self, *, pace: float = 1.0, await_timeout: float = WAIT_FOR_USER_SECONDS) -> None:
        self.pace = pace
        self.await_timeout = await_timeout
        self._sessions: dict[str, PacedFakeClient] = {}
        self._scenarios: dict[str, str] = {}
        self.closed = False

    @property
    def sessions(self) -> Mapping[str, PacedFakeClient]:
        """Session id -> its fake, in creation order."""
        return MappingProxyType(self._sessions)

    @property
    def scenarios(self) -> Mapping[str, str]:
        """Session id -> the scenario it plays."""
        return MappingProxyType(self._scenarios)

    def _fake(self, session_id: str) -> PacedFakeClient:
        fake = self._sessions.get(session_id)
        if fake is None:
            msg = f"demo session {session_id} not found"
            raise SessionNotFoundError(msg, status_code=404, error_type="not_found_error")
        return fake

    async def create_session(
        self,
        *,
        agent: AgentPin,
        environment_id: str,
        budget_cents: int,
        metadata: Mapping[str, str],
        title: str | None = None,
    ) -> SessionInfo:
        name = metadata.get(DEMO_SCENARIO_METADATA) or DEFAULT_DEMO_SCENARIO
        if name not in demo_scenarios():
            msg = f"unknown demo scenario {name!r}"
            raise ApiRejectedError(msg, status_code=400, error_type="invalid_request_error")
        namespace = uuid.uuid4().hex[:12]
        path = FIXTURES_DIR / f"{name}.jsonl"
        steps, lines = load_jsonl(path)
        fake = PacedFakeClient(
            steps,
            step_lines=lines,
            source=path.name,
            session_id=f"{DEMO_SESSION_PREFIX}{namespace}",
            id_namespace=namespace,
            pace=self.pace,
            await_timeout=self.await_timeout,
        )
        info = await fake.create_session(
            agent=agent,
            environment_id=environment_id,
            budget_cents=budget_cents,
            metadata=metadata,
            title=title,
        )
        self._sessions[info.id] = fake
        self._scenarios[info.id] = name
        return info

    async def send_user_message(self, session_id: str, text: str) -> None:
        await self._fake(session_id).send_user_message(session_id, text)

    async def send_custom_tool_result(
        self, session_id: str, tool_use_id: str, content: str, is_error: bool
    ) -> None:
        await self._fake(session_id).send_custom_tool_result(
            session_id, tool_use_id, content, is_error
        )

    async def send_interrupt(self, session_id: str, thread_id: str | None = None) -> None:
        await self._fake(session_id).send_interrupt(session_id, thread_id)

    def stream_session(self, session_id: str) -> AbstractAsyncContextManager[EventStream]:
        fake = self._sessions.get(session_id)
        if fake is None:
            return self._missing(session_id)
        return fake.stream_session(session_id)

    def stream_thread(
        self, session_id: str, thread_id: str
    ) -> AbstractAsyncContextManager[EventStream]:
        fake = self._sessions.get(session_id)
        if fake is None:
            return self._missing(session_id)
        return fake.stream_thread(session_id, thread_id)

    @asynccontextmanager
    async def _missing(self, session_id: str) -> AsyncIterator[EventStream]:
        self._fake(session_id)  # raises SessionNotFoundError
        raise AssertionError("unreachable")  # pragma: no cover
        yield  # pragma: no cover

    async def list_events(
        self,
        session_id: str,
        *,
        since: dt.datetime | None = None,
        page: str | None = None,
        limit: int = DEFAULT_LIST_LIMIT,
    ) -> EventPage:
        return await self._fake(session_id).list_events(
            session_id, since=since, page=page, limit=limit
        )

    async def list_thread_events(
        self,
        session_id: str,
        thread_id: str,
        *,
        page: str | None = None,
        limit: int = DEFAULT_LIST_LIMIT,
    ) -> EventPage:
        return await self._fake(session_id).list_thread_events(
            session_id, thread_id, page=page, limit=limit
        )

    async def list_threads(self, session_id: str) -> list[ThreadInfo]:
        return await self._fake(session_id).list_threads(session_id)

    async def archive_thread(self, session_id: str, thread_id: str) -> None:
        await self._fake(session_id).archive_thread(session_id, thread_id)

    async def retrieve_session(self, session_id: str) -> SessionInfo:
        return await self._fake(session_id).retrieve_session(session_id)

    async def update_budget(self, session_id: str, budget_cents: int) -> SessionInfo:
        return await self._fake(session_id).update_budget(session_id, budget_cents)

    async def archive_session(self, session_id: str) -> None:
        await self._fake(session_id).archive_session(session_id)

    async def delete_session(self, session_id: str) -> None:
        await self._fake(session_id).delete_session(session_id)

    async def list_sessions(
        self, *, created_before: dt.datetime, include_archived: bool = True
    ) -> list[SessionInfo]:
        """No workspace to sweep: demo sessions never reach the platform."""
        del created_before, include_archived
        return []

    async def aclose(self) -> None:
        """Stop every demo script (planner shutdown)."""
        self.closed = True
        for fake in list(self._sessions.values()):
            with contextlib.suppress(Exception):
                await fake.shutdown()
                await fake.aclose()


def _conforms(client: DemoManagedAgentsClient) -> ManagedAgentsClient:
    """Static check only: pyright fails here if the demo client drifts from the Protocol."""
    return client


__all__ = [
    "EXCLUDED_SCENARIOS",
    "MAX_GAP_SECONDS",
    "WAIT_FOR_USER_SECONDS",
    "DemoManagedAgentsClient",
    "PacedFakeClient",
    "demo_scenarios",
]
