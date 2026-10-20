"""`ask_traveller` in the consumer (app/consumer.py `_ask_traveller`) and the traveller's answer
(app/sessions.py `answer_choice`), played through `FakeManagedAgentsClient`: the `choices`
scenario (an `activities` pause with places, a `food` pause without), `choice_interrupt` (an
interrupt while a question waits) and small inline scripts for validation, the limits, a plan
already accepted, the deadline, resume and a budget pause during a question.

The consumer stores the question and waits; the test answers it through `answer_choice` or
`answer_pending_choice`, the functions the endpoint, the CLI and the evals call, or lets its
deadline pass (`Deadlines`, the harness's `sleep_until`: a deadline passes only when the test
says so). Everything is offline, like test_consumer.py, whose harness this file reuses. A
restart is a consumer task cancelled (the process dies) and a new one started in resume mode on
the same fake, as in test_consumer_resume.py.
"""

from __future__ import annotations

import asyncio
import contextlib
import dataclasses
import datetime as dt
import functools
import logging
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any, cast

import httpx
import pytest
import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from structlog.testing import LogCapture
from structlog.typing import EventDict
from time_machine import TimeMachineFixture

from app import clock, sessions
from app import consumer as consumer_module
from app.auth import CurrentUser, SessionVerifier
from app.choices import (
    NO_MORE_QUESTIONS_TEXT,
    ChoiceAnswer,
    ChoiceRequest,
    get_choice,
    insert_choice,
)
from app.config import Settings
from app.consumer import (
    ConsumerRegistry,
    ConsumerState,
    EventSink,
    IdleDecision,
    PlanUpdate,
    backend_event,
    backend_event_id,
    close_choice,
    decide_idle,
)
from app.covers import Cover
from app.db import ChoiceRecord, EventRecord, PlanStatus
from app.events import EventKind
from app.ma_client import ManagedAgentsClient
from app.sessions import (
    CONTINUE_MESSAGE,
    AnsweredChoice,
    ChoiceClosedError,
    PlannerServices,
    answer_choice,
    answer_pending_choice,
    continue_plan,
    interrupt_plan,
)
from tests.fakes import FakeManagedAgentsClient
from tests.test_consumer import (
    BRIEF,
    NOW,
    RUN_TIMEOUT,
    SID,
    Deadlines,
    Harness,
    HarnessFactory,
    by_key,
    harness_factory,
    offline_http,
    scenario,
    tool_results,
)

USER = CurrentUser(email="test@example.com")

ACTIVITIES_ID = "sevt_022CZchoiceActivitiesPa1"
ACTIVITIES_IDLE = "sevt_022CZchoiceActivitiesIdl"
FOOD_ID = "sevt_022CZchoiceFoodPause0001"

PICKS_TEXT = (
    'The traveller chose: a1 "Oceanário de Lisboa", a3 "Torre di Belém e Mosteiro dos '
    'Jerónimos". Build the plan around these and drop the other options you offered.'
)
FOOD_PICKS_TEXT = (
    'The traveller chose: c1 "Tascas di quartiere", c2 "Pesce alla griglia". Build the plan '
    "around these and drop the other options you offered."
)
LET_YOU_CHOOSE_TEXT = (
    "The traveller let you choose. Pick what fits the request best and go on; do not mention "
    "it in the warnings."
)
JOURNEY_PICK_TEXT = (
    'The traveller chose: c1 "Volo". Build the plan around it and drop the other options you '
    "offered."
)
NO_MODE_TEXT = (
    "The traveller did not choose a mode. Take the most sensible one and say so in one warning "
    "line."
)
LEADING_CANDIDATE_TEXT = "The traveller let you choose. Take your leading candidate and go on."

DEADLINE = NOW + dt.timedelta(seconds=240)
"""The deadline of a question asked at `NOW` (`CHOICE_TIMEOUT_SECONDS` 240)."""

INTERRUPT_CHOICE_ID = "sevt_033CZ0000000000000000008"
INTERRUPT_CHOICE_IDLE = "sevt_033CZ0000000000000000010"
"""`choice_interrupt`: the `food` question and the `requires_action` idle that waits on it."""


# --- harness --------------------------------------------------------------------------------------


def cover(name: str) -> Cover:
    return Cover(
        url=f"https://upload.wikimedia.org/wikipedia/commons/a/ab/{name}.jpg",
        width=1920,
        height=1080,
        author="Autore",
        license="CC BY-SA 4.0",
        license_url="https://creativecommons.org/licenses/by-sa/4.0/",
        source_page=f"https://commons.wikimedia.org/wiki/File:{name}.jpg",
        title=name,
    )


class StubPhotos:
    """A `ChoicePhotos` that records what it was asked and finds the photos it was given."""

    def __init__(self, found: Mapping[str, Cover] | None = None) -> None:
        self.calls: list[dict[str, str]] = []
        self._found = dict(found or {})

    async def photos_for(self, places: Mapping[str, str]) -> dict[str, Cover]:
        self.calls.append(dict(places))
        return {key: value for key, value in self._found.items() if key in places}


@dataclass
class Env:
    build: HarnessFactory
    http: httpx.AsyncClient

    def harness(self, fake: FakeManagedAgentsClient, **kwargs: Any) -> Harness:
        return self.build(fake, **kwargs)

    def planner(self, h: Harness, *, client: ManagedAgentsClient | None = None) -> PlannerServices:
        """The process's services around the harness's consumer deps, as `start_planner`
        builds them: what `answer_choice`, `interrupt_plan` and `continue_plan` need (the
        client, the database, the hub, a registry). `client` replaces the fake for the
        endpoint's own calls (the consumer keeps the harness's)."""
        deps = h.deps
        return PlannerServices(
            settings=deps.settings,
            http=self.http,
            session_factory=h.factory,
            hub=h.hub,
            trip_schema=deps.trip_schema,
            fx=deps.fx,
            session_verifier=SessionVerifier(deps.settings, self.http),
            client=client or h.fake,
            roster=sessions.demo_roster("development"),
            registry=ConsumerRegistry(deps),
        )


@pytest.fixture
async def env(
    db_session_factory: async_sessionmaker[AsyncSession],
    make_settings: Callable[..., Settings],
) -> AsyncIterator[Env]:
    async with offline_http() as http:
        yield Env(harness_factory(db_session_factory, make_settings, http), http)


@contextlib.asynccontextmanager
async def running(h: Harness, plan_id: uuid.UUID) -> AsyncIterator[asyncio.Task[PlanStatus]]:
    """The consumer as a task; cancelled (and the fake's driver stopped) if the test leaves it
    running."""
    task = asyncio.create_task(h.run(plan_id))
    try:
        yield task
    finally:
        if not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        await h.fake.shutdown()


async def finish(task: asyncio.Task[PlanStatus]) -> PlanStatus:
    async with asyncio.timeout(RUN_TIMEOUT):
        return await task


async def wait_for(check: Callable[[], Awaitable[bool]]) -> None:
    async with asyncio.timeout(RUN_TIMEOUT):
        while not await check():  # noqa: ASYNC110
            await asyncio.sleep(0.01)


async def stored(h: Harness, key: str) -> bool:
    async with h.factory() as db:
        found = await db.scalar(select(EventRecord.seq).where(EventRecord.ma_event_id == key))
    return found is not None


async def wait_stored(h: Harness, key: str) -> None:
    await wait_for(lambda: stored(h, key))


def asked_key(plan_id: uuid.UUID, choice_id: str) -> str:
    return backend_event_id(plan_id, "choice", f"{choice_id}:asked")


async def wait_asked(h: Harness, plan_id: uuid.UUID, choice_id: str) -> None:
    """Until the question's `choice` event is stored: the traveller can see it."""
    await wait_stored(h, asked_key(plan_id, choice_id))


async def choice_rows(h: Harness, plan_id: uuid.UUID) -> list[ChoiceRecord]:
    async with h.factory() as db:
        rows = await db.scalars(
            select(ChoiceRecord).where(ChoiceRecord.plan_id == plan_id).order_by(ChoiceRecord.id)
        )
        return list(rows)


async def choice_titles(h: Harness, plan_id: uuid.UUID) -> list[str]:
    return [row.title for row in await h.events(plan_id) if row.kind == EventKind.CHOICE.value]


def results_by_id(fake: FakeManagedAgentsClient) -> dict[str, list[tuple[str, bool]]]:
    """Tool use id -> every result sent for it (text, is_error), in order."""
    found: dict[str, list[tuple[str, bool]]] = {}
    for result in tool_results(fake):
        found.setdefault(result["custom_tool_use_id"], []).append(
            (result["content"][0]["text"], result["is_error"])
        )
    return found


async def answer_next(
    h: Harness, planner: PlannerServices, plan_id: uuid.UUID, choice_id: str
) -> AnsweredChoice:
    """Wait for the question, then answer it with `auto_pick`."""
    await wait_asked(h, plan_id, choice_id)
    answered = await answer_pending_choice(plan_id, USER, services=planner)
    assert answered is not None
    assert answered.id == choice_id
    return answered


async def until(check: Callable[[], bool]) -> None:
    """Wait (bounded) until `check()` holds."""
    async with asyncio.timeout(RUN_TIMEOUT):
        while not check():  # noqa: ASYNC110
            await asyncio.sleep(0.01)


async def choice_row(h: Harness, plan_id: uuid.UUID, choice_id: str) -> ChoiceRecord:
    async with h.factory() as db:
        row = await get_choice(db, plan_id, choice_id)
    assert row is not None
    return row


async def closed_row(h: Harness, plan_id: uuid.UUID, choice_id: str) -> bool:
    return (await choice_row(h, plan_id, choice_id)).answered_by is not None


def at(h: Harness, instant: dt.datetime, **changes: Any) -> Harness:
    """The same harness with its clock at `instant` (and `changes` to its deps): the process
    that resumes the plan later."""
    deps = dataclasses.replace(h.deps, now=lambda: instant, **changes)
    return dataclasses.replace(h, deps=deps)


Start = Callable[..., asyncio.Task[PlanStatus]]


@contextlib.asynccontextmanager
async def consumers(h: Harness) -> AsyncIterator[Start]:
    """`start(plan_id, fresh=True, harness=h)` runs a consumer as a task; every task still
    running at the end is cancelled and the fake's driver stopped."""
    started: list[asyncio.Task[PlanStatus]] = []

    def start(
        plan_id: uuid.UUID, *, fresh: bool = True, harness: Harness | None = None
    ) -> asyncio.Task[PlanStatus]:
        task = asyncio.create_task((harness or h).run(plan_id, fresh=fresh))
        started.append(task)
        return task

    try:
        yield start
    finally:
        for task in started:
            if not task.done():
                await stop(task)
        await h.fake.shutdown()


async def stop(task: asyncio.Task[PlanStatus]) -> None:
    """The process dies: the consumer task is cancelled, nothing more reaches the database."""
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task


async def note_interrupt(h: Harness, plan_id: uuid.UUID) -> None:
    """`sessions.request_interrupt`'s write: the request stored with its event."""
    await EventSink(plan_id, session_factory=h.factory, hub=h.hub).emit(
        backend_event(EventKind.STATUS, "Interruzione richiesta", ts=NOW),
        ma_event_id=backend_event_id(plan_id, "status", "interrupt-requested:1"),
        update=PlanUpdate(interrupt_requested_at=NOW),
    )


def logged(entries: list[EventDict], name: str, *keys: str) -> list[dict[str, Any]]:
    """The `keys` of every log entry named `name`."""
    return [
        {key: entry[key] for key in keys if key in entry}
        for entry in entries
        if entry["event"] == name
    ]


# --- inline scripts -------------------------------------------------------------------------------

OPTIONS_3 = [
    {"id": "a1", "title": "Torre di Belém", "reason": "Il simbolo della città."},
    {"id": "a2", "title": "Castelo de São Jorge", "reason": "Vista su tutta Lisbona."},
    {"id": "a3", "title": "Alfama e i miradouros", "reason": "Si gira a piedi."},
]
OPTIONS_2 = [
    {"id": "c1", "title": "Volo", "reason": "Il più veloce."},
    {"id": "c2", "title": "Treno", "reason": "Dal centro al centro."},
]


def request(
    kind: str, options: list[dict[str, Any]] | None = None, **change: Any
) -> dict[str, Any]:
    """A valid `ask_traveller` input of `kind` (three options when several can be picked, else
    two), with `change` applied."""
    multiple = kind in ("activities", "food")
    chosen = options if options is not None else (OPTIONS_3 if multiple else OPTIONS_2)
    data = {"kind": kind, "question": f"Domanda {kind}?", "multiple": multiple, "options": chosen}
    return data | change


def pause(
    tool_use_id: str, tool_input: Mapping[str, Any], *, results: int = 1, **match: Any
) -> list[dict[str, Any]]:
    """An `ask_traveller` call, the `requires_action` idle waiting on it, the wait for its
    result (`results` of them, each matching `match` too) and the session running again."""
    return [
        {
            "op": "emit",
            "event": {
                "type": "agent.custom_tool_use",
                "id": tool_use_id,
                "name": "ask_traveller",
                "input": dict(tool_input),
            },
        },
        {
            "op": "emit",
            "event": {
                "type": "session.status_idle",
                "id": f"{tool_use_id}_idle",
                "stop_reason": {"type": "requires_action", "event_ids": [tool_use_id]},
            },
        },
        {
            "op": "await",
            "match": {"type": "user.custom_tool_result", "custom_tool_use_id": tool_use_id} | match,
            "count": results,
        },
        {"op": "emit", "event": {"type": "session.status_running", "id": f"{tool_use_id}_run"}},
    ]


SUBMIT_ID = "sevt_submit"


def submit_accepted() -> list[dict[str, Any]]:
    return [
        {
            "op": "emit",
            "event": {
                "type": "agent.custom_tool_use",
                "id": SUBMIT_ID,
                "name": "submit_plan",
                "input": {"$fixture": "ma/plans/lisbon_valid.json"},
            },
        },
        {
            "op": "emit",
            "event": {
                "type": "session.status_idle",
                "id": f"{SUBMIT_ID}_idle",
                "stop_reason": {"type": "requires_action", "event_ids": [SUBMIT_ID]},
            },
        },
        {
            "op": "await",
            "match": {
                "type": "user.custom_tool_result",
                "custom_tool_use_id": SUBMIT_ID,
                "is_error": False,
            },
        },
        {"op": "emit", "event": {"type": "session.status_running", "id": f"{SUBMIT_ID}_run"}},
    ]


END_TURN: dict[str, Any] = {
    "op": "emit",
    "event": {"type": "session.status_idle", "id": "sevt_end", "stop_reason": {"type": "end_turn"}},
}


def script(*parts: list[dict[str, Any]], end: bool = True) -> FakeManagedAgentsClient:
    """The brief, the given parts, then (with `end`) an accepted plan and `end_turn`."""
    steps: list[dict[str, Any]] = [{"op": "await", "match": {"type": "user.message"}}]
    for part in parts:
        steps += part
    if end:
        steps += [*submit_accepted(), END_TURN]
    return FakeManagedAgentsClient(steps, await_timeout=10)


# --- pure decisions -------------------------------------------------------------------------------


def test_requires_action_on_ask_traveller_is_a_wait() -> None:
    idle = {
        "type": "session.status_idle",
        "stop_reason": {"type": "requires_action", "event_ids": [ACTIVITIES_ID]},
    }
    for accepted in (False, True):
        state = ConsumerState(
            status=PlanStatus.RUNNING, accepted=accepted, custom_tool_use_ids={ACTIVITIES_ID}
        )
        outcome = decide_idle(idle, state)
        assert outcome.decision is IdleDecision.WAIT
        assert outcome.log_reason == "requires_action:custom_tool"


# --- asking ---------------------------------------------------------------------------------------


async def test_ask_traveller_stores_the_choice_and_waits(env: Env) -> None:
    photos = StubPhotos({"a1": cover("Oceanario")})
    h = env.harness(scenario("choices"), photos=photos)
    plan_id = await h.create_plan()

    async with running(h, plan_id) as task:
        await wait_stored(h, ACTIVITIES_IDLE)  # the session idles, waiting on the question

        [row] = await choice_rows(h, plan_id)
        assert (row.id, row.kind, row.answered_by, row.answer) == (
            ACTIVITIES_ID,
            "activities",
            None,
            None,
        )
        assert row.asked_at == NOW
        assert row.deadline_at == row.asked_at + dt.timedelta(seconds=240)

        events = await h.events(plan_id)
        [asked] = [event for event in events if event.kind == EventKind.CHOICE.value]
        assert asked.title == "Tocca a te: scegli cosa vedere"
        assert asked.ma_event_id == asked_key(plan_id, ACTIVITIES_ID)
        assert asked.detail is not None
        assert asked.detail["phase"] == "asked"
        choice = asked.detail["choice"]
        assert choice["id"] == ACTIVITIES_ID
        assert choice["question"] == "Cosa ti va di vedere?"
        assert dt.datetime.fromisoformat(choice["deadline_at"]) == row.deadline_at
        options = choice["options"]
        assert [option["id"] for option in options] == ["a1", "a2", "a3"]
        assert options[0]["photo"]["url"] == cover("Oceanario").url
        assert [option["photo"] for option in options[1:]] == [None, None]
        assert all("place" not in option for option in options)
        # The stored question comes before the idle that waits on it.
        keys = [event.ma_event_id for event in events]
        assert keys.index(asked.ma_event_id) < keys.index(ACTIVITIES_IDLE)
        # The raw tool use shows as a question, without its input.
        tool_use = by_key(events)[ACTIVITIES_ID]
        assert (tool_use.kind, tool_use.title) == ("tool", "Domanda al viaggiatore")
        assert tool_use.detail is not None
        assert "params" not in tool_use.detail
        assert [e.kind for e in h.hub.published].count(EventKind.CHOICE) == 1

        assert (await h.plan(plan_id)).status == PlanStatus.RUNNING
        assert tool_results(h.fake) == []  # nothing answers for the traveller
        assert not task.done()


async def test_traveller_answer_reaches_the_agent(env: Env) -> None:
    h = env.harness(scenario("choices"))
    planner = env.planner(h)
    plan_id = await h.create_plan()

    async with running(h, plan_id) as task:
        await wait_asked(h, plan_id, ACTIVITIES_ID)
        answered = await answer_choice(
            plan_id,
            ACTIVITIES_ID,
            ChoiceAnswer(selected=["a3", "a1"]),
            USER,
            services=planner,
        )
        # The picks are kept in the order they were offered.
        assert answered == AnsweredChoice(
            id=ACTIVITIES_ID, answered_by="traveller", selected=["a1", "a3"]
        )
        await wait_asked(h, plan_id, FOOD_ID)
        skipped = await answer_choice(
            plan_id, FOOD_ID, ChoiceAnswer(skip=True), USER, services=planner
        )
        assert skipped == AnsweredChoice(id=FOOD_ID, answered_by="skip", selected=[])

        assert await finish(task) is PlanStatus.READY
    h.fake.assert_script_done()

    sent = results_by_id(h.fake)
    assert sent[ACTIVITIES_ID] == [(PICKS_TEXT, False)]
    assert sent[FOOD_ID] == [(LET_YOU_CHOOSE_TEXT, False)]
    rows = {row.id: row for row in await choice_rows(h, plan_id)}
    assert (rows[ACTIVITIES_ID].answered_by, rows[ACTIVITIES_ID].answer) == (
        "traveller",
        ["a1", "a3"],
    )
    assert (rows[FOOD_ID].answered_by, rows[FOOD_ID].answer) == ("skip", [])
    assert rows[ACTIVITIES_ID].answered_at == NOW
    assert await choice_titles(h, plan_id) == [
        "Tocca a te: scegli cosa vedere",
        "Hai scelto: Oceanário de Lisboa, Torre di Belém e Mosteiro dos Jerónimos",
        "Tocca a te: scegli cosa mangiare",
        "Hai lasciato scegliere ad Atlas",
    ]


async def test_skip_sends_let_you_choose(env: Env) -> None:
    h = env.harness(scenario("choices"))
    planner = env.planner(h)
    plan_id = await h.create_plan()

    async with running(h, plan_id) as task:
        await wait_asked(h, plan_id, ACTIVITIES_ID)
        skipped = await answer_choice(
            plan_id, ACTIVITIES_ID, ChoiceAnswer(skip=True), USER, services=planner
        )
        assert skipped == AnsweredChoice(id=ACTIVITIES_ID, answered_by="skip", selected=[])
        food = await answer_next(h, planner, plan_id, FOOD_ID)
        assert food == AnsweredChoice(id=FOOD_ID, answered_by="traveller", selected=["c1", "c2"])
        assert await finish(task) is PlanStatus.READY
    h.fake.assert_script_done()

    sent = results_by_id(h.fake)
    assert sent[ACTIVITIES_ID] == [(LET_YOU_CHOOSE_TEXT, False)]
    assert sent[FOOD_ID] == [(FOOD_PICKS_TEXT, False)]
    titles = await choice_titles(h, plan_id)
    assert titles[1] == "Hai lasciato scegliere ad Atlas"
    assert titles[3] == "Hai scelto: Tascas di quartiere, Pesce alla griglia"


async def test_invalid_input_is_an_error_not_a_pause(env: Env) -> None:
    invalid = request("activities", options=OPTIONS_3[:2], question="x" * 121)
    fake = script(
        pause("sevt_q_bad", invalid, is_error=True),
        pause("sevt_q_good", request("activities")),
    )
    h = env.harness(fake)
    planner = env.planner(h)
    plan_id = await h.create_plan()

    async with running(h, plan_id) as task:
        await answer_next(h, planner, plan_id, "sevt_q_good")
        assert await finish(task) is PlanStatus.READY
    fake.assert_script_done()

    [(text, is_error)] = results_by_id(fake)["sevt_q_bad"]
    assert is_error is True
    lines = text.splitlines()
    assert lines[0] == (
        "ask_traveller rejected: 2 validation error(s). Nothing was shown to the traveller. "
        "Fix every one and call ask_traveller again."
    )
    assert len(lines) == 3
    assert all(line.startswith("- ") for line in lines[1:])
    # Nothing was stored for the rejected call but the raw tool use and its idle: no row, no
    # question, no backend outcome (it is re-evaluated identically on resume).
    assert [row.id for row in await choice_rows(h, plan_id)] == ["sevt_q_good"]
    keys = {event.ma_event_id or "" for event in await h.events(plan_id)}
    assert not any("sevt_q_bad" in key for key in keys if key.startswith("backend:"))
    assert "sevt_q_bad" in keys
    assert await choice_titles(h, plan_id) == [
        "Tocca a te: scegli cosa vedere",
        "Hai scelto: Torre di Belém, Castelo de São Jorge",
    ]
    assert (await h.plan(plan_id)).submit_attempts == 1


async def test_limits_refuse_a_fourth_pause_and_a_repeated_kind(env: Env) -> None:
    refused = {"is_error": True}
    fake = script(
        pause("sevt_q1", request("activities")),
        pause("sevt_q2", request("food")),
        pause("sevt_q3", request("other")),
        pause("sevt_q4", request("destination"), **refused),
        pause("sevt_q5", request("food"), **refused),
    )
    h = env.harness(fake)
    planner = env.planner(h)
    plan_id = await h.create_plan()

    async with running(h, plan_id) as task:
        for choice_id in ("sevt_q1", "sevt_q2", "sevt_q3"):
            await answer_next(h, planner, plan_id, choice_id)
        assert await finish(task) is PlanStatus.READY
    fake.assert_script_done()

    sent = results_by_id(fake)
    assert sent["sevt_q4"] == [(NO_MORE_QUESTIONS_TEXT, True)]
    assert sent["sevt_q5"] == [(NO_MORE_QUESTIONS_TEXT, True)]
    rows = await choice_rows(h, plan_id)
    assert [(row.id, row.kind) for row in rows] == [
        ("sevt_q1", "activities"),
        ("sevt_q2", "food"),
        ("sevt_q3", "other"),
    ]
    assert len(await choice_titles(h, plan_id)) == 6  # three asked, three answered


async def test_a_repeated_kind_is_refused_before_the_limit(env: Env) -> None:
    fake = script(
        pause("sevt_q1", request("activities")),
        pause("sevt_q2", request("activities"), is_error=True),
        pause("sevt_q3", request("journey")),
        pause("sevt_q4", request("other"), is_error=True),
    )
    h = env.harness(fake)
    planner = env.planner(h)
    plan_id = await h.create_plan()

    async with running(h, plan_id) as task:
        await answer_next(h, planner, plan_id, "sevt_q1")
        await answer_next(h, planner, plan_id, "sevt_q3")
        assert await finish(task) is PlanStatus.READY
    fake.assert_script_done()

    sent = results_by_id(fake)
    assert sent["sevt_q2"] == [(NO_MORE_QUESTIONS_TEXT, True)]  # activities twice
    assert sent["sevt_q4"] == [(NO_MORE_QUESTIONS_TEXT, True)]  # journey's shared slot taken
    assert [row.id for row in await choice_rows(h, plan_id)] == ["sevt_q1", "sevt_q3"]


async def test_ask_after_acceptance_is_refused(env: Env) -> None:
    fake = script(
        submit_accepted(),
        pause("sevt_late", request("food"), is_error=True),
        [END_TURN],
        end=False,
    )
    h = env.harness(fake)
    plan_id = await h.create_plan()

    async with running(h, plan_id) as task:
        assert await finish(task) is PlanStatus.READY
    fake.assert_script_done()

    assert results_by_id(fake)["sevt_late"] == [(NO_MORE_QUESTIONS_TEXT, True)]
    assert await choice_rows(h, plan_id) == []
    assert await choice_titles(h, plan_id) == []


async def test_photos_get_only_the_place_names(env: Env) -> None:
    photos = StubPhotos()
    h = env.harness(scenario("choices"), photos=photos)
    planner = env.planner(h)
    plan_id = await h.create_plan()

    async with running(h, plan_id) as task:
        await answer_next(h, planner, plan_id, ACTIVITIES_ID)
        await answer_next(h, planner, plan_id, FOOD_ID)
        assert await finish(task) is PlanStatus.READY
    h.fake.assert_script_done()

    # One lookup for the activities, with the place names only; the food options have no place,
    # so no lookup at all.
    assert photos.calls == [
        {
            "a1": "Oceanário de Lisboa, Lisboa",
            "a2": "Parque e Palácio Nacional da Pena, Sintra",
            "a3": "Belém, Lisboa",
        }
    ]
    rows = await choice_rows(h, plan_id)
    assert [row.payload["photos"] for row in rows] == [{}, {}]


async def test_only_the_options_with_a_place_are_looked_up(env: Env) -> None:
    options = [
        OPTIONS_3[0],
        OPTIONS_3[1] | {"place": "Castelo de São Jorge, Lisboa"},
        OPTIONS_3[2],
    ]
    photos = StubPhotos({"a2": cover("Castelo")})
    h = env.harness(script(pause("sevt_q1", request("activities", options=options))), photos=photos)
    planner = env.planner(h)
    plan_id = await h.create_plan()

    async with running(h, plan_id) as task:
        await answer_next(h, planner, plan_id, "sevt_q1")
        assert await finish(task) is PlanStatus.READY

    assert photos.calls == [{"a2": "Castelo de São Jorge, Lisboa"}]
    [row] = await choice_rows(h, plan_id)
    assert list(row.payload["photos"]) == ["a2"]


@pytest.fixture
def choice_logs(monkeypatch: pytest.MonkeyPatch) -> list[EventDict]:
    """Every log entry of the consumer and of sessions, independent of the global
    configuration."""
    capture = LogCapture()
    logger = structlog.wrap_logger(
        structlog.PrintLogger(),
        processors=[capture],
        wrapper_class=structlog.make_filtering_bound_logger(logging.DEBUG),
    )
    monkeypatch.setattr(consumer_module, "log", logger)
    monkeypatch.setattr(sessions, "log", logger)
    return capture.entries


async def test_choice_logs_carry_no_card_text(env: Env, choice_logs: list[EventDict]) -> None:
    places = [
        OPTIONS_3[0] | {"place": "Torre de Belém, Lisboa", "area": "Belém"},
        *OPTIONS_3[1:],
    ]
    invalid = request("activities", options=places[:2])
    fake = script(
        pause("sevt_q0", invalid, is_error=True),
        pause("sevt_q1", request("activities", options=places)),
        pause("sevt_q2", request("activities"), is_error=True),
    )
    photos = StubPhotos({"a1": cover("Torre_de_Belem")})
    h = env.harness(fake, photos=photos)
    planner = env.planner(h)
    plan_id = await h.create_plan()

    async with running(h, plan_id) as task:
        await wait_asked(h, plan_id, "sevt_q1")
        await answer_choice(
            plan_id, "sevt_q1", ChoiceAnswer(selected=["a2"]), USER, services=planner
        )
        assert await finish(task) is PlanStatus.READY
    fake.assert_script_done()

    def named(name: str) -> list[EventDict]:
        return [entry for entry in choice_logs if entry["event"] == name]

    keys = ("kind", "options", "photos", "answered_by", "selected", "latency_ms", "errors")

    def fields(entry: EventDict) -> dict[str, Any]:
        return {key: entry[key] for key in (*keys, "reason") if key in entry}

    assert [fields(entry) for entry in named("choice_rejected")] == [{"errors": 1}]
    assert [fields(entry) for entry in named("choice_asked")] == [
        {"kind": "activities", "options": 3, "photos": 1}
    ]
    assert [fields(entry) for entry in named("choice_answered")] == [
        {
            "kind": "activities",
            "options": 3,
            "answered_by": "traveller",
            "selected": 1,
            "latency_ms": 0,
        }
    ]
    assert [fields(entry) for entry in named("choice_refused")] == [{"reason": "same_kind"}]
    [answered] = named("choice_answered")
    assert (answered["plan_id"], answered["session_id"]) == (str(plan_id), h.fake.session_id)
    assert named("choice_asked")[0]["plan_id"] == str(plan_id)

    text = repr(choice_logs)
    card_text = [
        "Domanda activities?",
        "Torre de Belém",
        "Torre di Belém",
        "Castelo de São Jorge",
        "Alfama",
        "Il simbolo della città.",
        "Vista su tutta Lisbona.",
        "upload.wikimedia.org",
        "commons.wikimedia.org",
    ]
    assert [snippet for snippet in card_text if snippet in text] == []


# --- the deadline ---------------------------------------------------------------------------------


async def test_timeout_answers_for_the_traveller(env: Env, choice_logs: list[EventDict]) -> None:
    h = env.harness(scenario("choices"), deadlines=Deadlines(immediate=True))
    plan_id = await h.create_plan()

    async with running(h, plan_id) as task:
        assert await finish(task) is PlanStatus.READY
    h.fake.assert_script_done()

    # Each question waited for its own deadline, 240 s after it was asked.
    assert h.deadlines.requested == [DEADLINE, DEADLINE]
    sent = results_by_id(h.fake)
    assert sent[ACTIVITIES_ID] == [(LET_YOU_CHOOSE_TEXT, False)]
    assert sent[FOOD_ID] == [(LET_YOU_CHOOSE_TEXT, False)]
    rows = await choice_rows(h, plan_id)
    assert [(row.id, row.answered_by, row.answer, row.answered_at) for row in rows] == [
        (ACTIVITIES_ID, "timeout", [], NOW),
        (FOOD_ID, "timeout", [], NOW),
    ]
    assert await choice_titles(h, plan_id) == [
        "Tocca a te: scegli cosa vedere",
        "Tempo scaduto: sceglie Atlas",
        "Tocca a te: scegli cosa mangiare",
        "Tempo scaduto: sceglie Atlas",
    ]
    keys = ("kind", "answered_by", "options", "selected", "latency_ms")
    assert logged(choice_logs, "choice_answered", *keys) == [
        {
            "kind": "activities",
            "answered_by": "timeout",
            "options": 3,
            "selected": 0,
            "latency_ms": 0,
        },
        {"kind": "food", "answered_by": "timeout", "options": 3, "selected": 0, "latency_ms": 0},
    ]


@pytest.mark.parametrize(
    ("kind", "text"),
    [
        ("journey", NO_MODE_TEXT),
        ("destination", LEADING_CANDIDATE_TEXT),
        ("other", LET_YOU_CHOOSE_TEXT),
    ],
)
async def test_timeout_text_follows_the_kind(env: Env, kind: str, text: str) -> None:
    fake = script(pause("sevt_q1", request(kind), is_error=False))
    h = env.harness(fake, deadlines=Deadlines(immediate=True))
    plan_id = await h.create_plan()

    async with running(h, plan_id) as task:
        assert await finish(task) is PlanStatus.READY
    fake.assert_script_done()

    assert results_by_id(fake)["sevt_q1"] == [(text, False)]
    assert (await choice_row(h, plan_id, "sevt_q1")).answered_by == "timeout"


async def test_timeout_under_time_machine(env: Env, time_machine: TimeMachineFixture) -> None:
    time_machine.move_to(NOW, tick=False)
    fake = script(pause("sevt_q1", request("food")))
    # The production clock and timer, polling every 10 ms instead of every second.
    timer = functools.partial(clock.sleep_until, step_seconds=0.01)
    h = env.harness(fake, now=clock.now, sleep_until=timer)
    plan_id = await h.create_plan()

    async with running(h, plan_id) as task:
        await wait_asked(h, plan_id, "sevt_q1")
        await asyncio.sleep(0.1)  # ten polls of a clock that has not moved
        assert not await closed_row(h, plan_id, "sevt_q1")
        time_machine.shift(241)
        assert await finish(task) is PlanStatus.READY
    fake.assert_script_done()

    row = await choice_row(h, plan_id, "sevt_q1")
    assert (row.answered_by, row.deadline_at) == ("timeout", DEADLINE)
    assert row.answered_at == NOW + dt.timedelta(seconds=241)
    assert results_by_id(fake)["sevt_q1"] == [(LET_YOU_CHOOSE_TEXT, False)]


async def test_answer_before_the_deadline_cancels_the_timer(env: Env) -> None:
    h = env.harness(scenario("choices"))
    planner = env.planner(h)
    plan_id = await h.create_plan()

    async with running(h, plan_id) as task:
        await wait_asked(h, plan_id, ACTIVITIES_ID)
        await until(lambda: h.deadlines.waiting == 1)
        await answer_choice(
            plan_id, ACTIVITIES_ID, ChoiceAnswer(selected=["a1", "a3"]), USER, services=planner
        )
        # The answer's echo disarms the timer: when the deadline comes, nothing waits for it.
        await until(lambda: h.deadlines.cancelled == [DEADLINE])
        assert h.deadlines.expire() == 0
        await answer_next(h, planner, plan_id, FOOD_ID)
        assert await finish(task) is PlanStatus.READY
    h.fake.assert_script_done()

    assert results_by_id(h.fake)[ACTIVITIES_ID] == [(PICKS_TEXT, False)]
    assert (await choice_row(h, plan_id, ACTIVITIES_ID)).answered_by == "traveller"
    titles = await choice_titles(h, plan_id)
    assert "Tempo scaduto: sceglie Atlas" not in titles
    assert titles[1] == "Hai scelto: Oceanário de Lisboa, Torre di Belém e Mosteiro dos Jerónimos"


class GatedResults:
    """The endpoint's client: the fake, but its tool results wait for `gate` (the answer is
    still on the wire)."""

    def __init__(self, fake: FakeManagedAgentsClient) -> None:
        self._fake = fake
        self.gate = asyncio.Event()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._fake, name)

    async def send_custom_tool_result(
        self, session_id: str, tool_use_id: str, content: str, is_error: bool
    ) -> None:
        await self.gate.wait()
        await self._fake.send_custom_tool_result(session_id, tool_use_id, content, is_error)


async def test_a_deadline_during_the_answer_sends_only_the_travellers_answer(env: Env) -> None:
    fake = script(pause("sevt_q1", request("activities"), results=2))
    h = env.harness(fake)
    gated = GatedResults(fake)
    planner = env.planner(h, client=cast(ManagedAgentsClient, gated))
    plan_id = await h.create_plan()
    text = (
        'The traveller chose: a2 "Castelo de São Jorge". Build the plan around it and drop the '
        "other options you offered."
    )

    async with running(h, plan_id) as task:
        await wait_asked(h, plan_id, "sevt_q1")
        await until(lambda: h.deadlines.waiting == 1)
        answering = asyncio.create_task(
            answer_choice(plan_id, "sevt_q1", ChoiceAnswer(selected=["a2"]), USER, services=planner)
        )
        await wait_for(lambda: closed_row(h, plan_id, "sevt_q1"))  # stored, still on the wire
        assert h.deadlines.expire() == 1  # the deadline comes in that very second
        await until(lambda: len(results_by_id(fake).get("sevt_q1", [])) == 1)
        gated.gate.set()
        assert (await answering).answered_by == "traveller"
        assert await finish(task) is PlanStatus.READY
    fake.assert_script_done()

    # The deadline lost to the traveller: both results carry the traveller's answer, and the
    # platform keeps the first (one echo); the row and the timeline say the same.
    assert results_by_id(fake)["sevt_q1"] == [(text, False), (text, False)]
    echoes = [
        event
        for event in fake.history
        if event["type"] == "user.custom_tool_result" and event["custom_tool_use_id"] == "sevt_q1"
    ]
    assert len(echoes) == 1
    assert (await choice_row(h, plan_id, "sevt_q1")).answered_by == "traveller"
    assert await choice_titles(h, plan_id) == [
        "Tocca a te: scegli cosa vedere",
        "Hai scelto: Castelo de São Jorge",
    ]


async def test_timer_resends_an_answer_whose_send_failed(
    env: Env, choice_logs: list[EventDict]
) -> None:
    h = env.harness(scenario("choices"))
    planner = env.planner(h)
    plan_id = await h.create_plan()

    async with running(h, plan_id) as task:
        await wait_asked(h, plan_id, ACTIVITIES_ID)
        await until(lambda: h.deadlines.waiting == 1)
        h.fake.fail_next("send_custom_tool_result", "api_unavailable")
        answered = await answer_choice(
            plan_id, ACTIVITIES_ID, ChoiceAnswer(selected=["a3", "a1"]), USER, services=planner
        )
        assert answered.answered_by == "traveller"  # the answer stands
        assert ACTIVITIES_ID not in results_by_id(h.fake)  # but it never reached the session
        assert h.deadlines.expire() == 1  # the deadline passes with no result echoed
        await answer_next(h, planner, plan_id, FOOD_ID)
        assert await finish(task) is PlanStatus.READY
    h.fake.assert_script_done()

    assert results_by_id(h.fake)[ACTIVITIES_ID] == [(PICKS_TEXT, False)]  # resent exactly once
    calls = [
        call
        for call in h.fake.calls_of("send_custom_tool_result")
        if call.args["tool_use_id"] == ACTIVITIES_ID
    ]
    assert [call.error is not None for call in calls] == [True, False]
    row = await choice_row(h, plan_id, ACTIVITIES_ID)
    assert (row.answered_by, row.answer) == ("traveller", ["a1", "a3"])
    assert "Tempo scaduto: sceglie Atlas" not in await choice_titles(h, plan_id)
    assert len(logged(choice_logs, "choice_answer_send_failed")) == 1
    assert logged(choice_logs, "choice_answer_resent", "kind", "answered_by") == [
        {"kind": "activities", "answered_by": "traveller"}
    ]


# --- the platform's closure -----------------------------------------------------------------------


async def test_interrupt_while_waiting_closes_the_choice(env: Env) -> None:
    h = env.harness(scenario("choice_interrupt"))
    planner = env.planner(h)
    registry = planner.registry
    assert registry is not None
    plan_id = await h.create_plan()

    consumer = registry.start(plan_id, SID, first_message=BRIEF)
    try:
        await wait_stored(h, INTERRUPT_CHOICE_IDLE)
        await until(lambda: h.deadlines.waiting == 1)
        assert await interrupt_plan(plan_id, USER, services=planner) is PlanStatus.RUNNING
        await until(lambda: consumer.done)
    finally:
        await registry.aclose()
        await h.fake.shutdown()
    h.fake.assert_script_done()

    assert (await h.plan(plan_id)).status == PlanStatus.INTERRUPTED
    assert h.fake.archived == [SID]
    assert tool_results(h.fake) == []  # the platform closed the call: the backend sent nothing
    row = await choice_row(h, plan_id, INTERRUPT_CHOICE_ID)
    assert (row.answered_by, row.answer, row.answered_at) == ("closed", [], NOW)
    assert await choice_titles(h, plan_id) == [
        "Tocca a te: scegli cosa mangiare",
        "Domanda chiusa: piano interrotto",
    ]
    assert h.deadlines.cancelled == [DEADLINE]  # the platform's result disarmed the timer
    with pytest.raises(ChoiceClosedError):
        await answer_choice(
            plan_id, INTERRUPT_CHOICE_ID, ChoiceAnswer(skip=True), USER, services=planner
        )


async def test_no_timeout_once_an_interrupt_was_asked(
    env: Env, choice_logs: list[EventDict]
) -> None:
    asked, waiting, _, _ = pause("sevt_q1", request("food"))
    interrupted = {"op": "await", "match": {"type": "user.interrupt"}}
    fake = script([asked, waiting, interrupted, END_TURN], end=False)
    h = env.harness(fake)
    plan_id = await h.create_plan()

    async with running(h, plan_id) as task:
        await wait_asked(h, plan_id, "sevt_q1")
        await until(lambda: h.deadlines.waiting == 1)
        # Asked through the other process of a redeploy's overlap: only the row knows it.
        await note_interrupt(h, plan_id)
        assert h.deadlines.expire() == 1
        await until(lambda: bool(logged(choice_logs, "choice_deadline_skipped")))
        assert tool_results(fake) == []  # the deadline answers nothing: the interrupt closes it
        assert not await closed_row(h, plan_id, "sevt_q1")
        await fake.send_interrupt(SID)
        assert await finish(task) is PlanStatus.INTERRUPTED
    fake.assert_script_done()

    assert tool_results(fake) == []
    assert (await choice_row(h, plan_id, "sevt_q1")).answered_by == "closed"
    assert await choice_titles(h, plan_id) == [
        "Tocca a te: scegli cosa mangiare",
        "Domanda chiusa: piano interrotto",
    ]


# --- resume ---------------------------------------------------------------------------------------


async def test_resume_rearms_with_the_original_deadline(env: Env) -> None:
    h = env.harness(scenario("choices"))
    later = at(h, NOW + dt.timedelta(seconds=100))  # the process that resumes, 100 s later
    planner = env.planner(later)
    plan_id = await h.create_plan()

    async with consumers(h) as start:
        first = start(plan_id)
        await wait_stored(h, ACTIVITIES_IDLE)
        await until(lambda: h.deadlines.waiting == 1)
        await stop(first)  # the process dies mid-pause
        assert h.deadlines.cancelled == [DEADLINE]

        resumed = start(plan_id, fresh=False, harness=later)
        await until(lambda: h.deadlines.waiting == 1)
        # The row's deadline, not 240 s from the resume.
        assert h.deadlines.requested == [DEADLINE, DEADLINE]
        await answer_choice(
            plan_id, ACTIVITIES_ID, ChoiceAnswer(selected=["a1", "a3"]), USER, services=planner
        )
        await answer_next(h, planner, plan_id, FOOD_ID)
        assert await finish(resumed) is PlanStatus.READY
    h.fake.assert_script_done()

    # The next question, asked by the resumed process, gets a fresh deadline from its clock.
    assert h.deadlines.requested[2] == NOW + dt.timedelta(seconds=340)
    assert results_by_id(h.fake)[ACTIVITIES_ID] == [(PICKS_TEXT, False)]
    titles = await choice_titles(h, plan_id)
    assert titles.count("Tocca a te: scegli cosa vedere") == 1  # asked once, not again
    assert len(await choice_rows(h, plan_id)) == 2


async def test_resume_past_the_deadline_times_out(env: Env) -> None:
    h = env.harness(scenario("choices"))
    later = at(h, NOW + dt.timedelta(seconds=241))
    planner = env.planner(later)
    plan_id = await h.create_plan()

    async with consumers(h) as start:
        first = start(plan_id)
        await wait_stored(h, ACTIVITIES_IDLE)
        await until(lambda: h.deadlines.waiting == 1)
        await stop(first)

        resumed = start(plan_id, fresh=False, harness=later)
        # The activities question timed out at once, so the run went on to the next one.
        await answer_next(h, planner, plan_id, FOOD_ID)
        assert await finish(resumed) is PlanStatus.READY
    h.fake.assert_script_done()

    # No wait for a deadline already passed; the food question's is 240 s after it was asked.
    assert h.deadlines.requested == [DEADLINE, NOW + dt.timedelta(seconds=481)]
    assert results_by_id(h.fake)[ACTIVITIES_ID] == [(LET_YOU_CHOOSE_TEXT, False)]
    row = await choice_row(h, plan_id, ACTIVITIES_ID)
    assert (row.answered_by, row.answered_at) == ("timeout", NOW + dt.timedelta(seconds=241))
    assert await choice_titles(h, plan_id) == [
        "Tocca a te: scegli cosa vedere",
        "Tempo scaduto: sceglie Atlas",
        "Tocca a te: scegli cosa mangiare",
        "Hai scelto: Tascas di quartiere, Pesce alla griglia",
    ]


JOURNEY_ID = "sevt_q_journey"
JOURNEY_IDLE = f"{JOURNEY_ID}_idle"


def journey_paused(*after: dict[str, Any]) -> FakeManagedAgentsClient:
    """A `journey` question, the idle waiting on it, a checkpoint `paused`, then `after`."""
    asked, waiting, _, _ = pause(JOURNEY_ID, request("journey"))
    steps: list[dict[str, Any]] = [
        {"op": "await", "match": {"type": "user.message"}},
        asked,
        waiting,
        {"op": "checkpoint", "name": "paused"},
        *after,
    ]
    return FakeManagedAgentsClient(steps, await_timeout=10)


@pytest.mark.parametrize(
    ("answered_by", "selected", "text", "title"),
    [
        ("traveller", ["c1"], JOURNEY_PICK_TEXT, "Hai scelto: Volo"),
        ("skip", [], NO_MODE_TEXT, "Hai lasciato scegliere ad Atlas"),
        ("timeout", [], NO_MODE_TEXT, "Tempo scaduto: sceglie Atlas"),
    ],
)
async def test_resume_answers_from_an_answered_row(
    env: Env,
    choice_logs: list[EventDict],
    *,
    answered_by: Any,
    selected: list[str],
    text: str,
    title: str,
) -> None:
    _, _, answered, run_again = pause(JOURNEY_ID, request("journey"), is_error=False)
    fake = journey_paused(answered, run_again, *submit_accepted(), END_TURN)
    h = env.harness(fake)
    plan_id = await h.create_plan()

    async with consumers(h) as start:
        first = start(plan_id)
        await wait_stored(h, JOURNEY_IDLE)
        await fake.reached("paused")
        await stop(first)
        # Closed while no consumer ran: the traveller's answer whose send was lost, or the
        # deadline of a process that died before sending.
        sink = EventSink(plan_id, session_factory=h.factory, hub=h.hub)
        assert await close_choice(
            sink, JOURNEY_ID, answered_by=answered_by, selected=selected, now=NOW
        )

        resumed = start(plan_id, fresh=False)
        fake.release("paused")
        assert await finish(resumed) is PlanStatus.READY
    fake.assert_script_done()

    assert results_by_id(fake)[JOURNEY_ID] == [(text, False)]
    assert h.deadlines.requested == [DEADLINE]  # only the first consumer armed it
    assert await choice_titles(h, plan_id) == ["Tocca a te: scegli come viaggiare", title]
    assert logged(choice_logs, "choice_answer_resent", "kind", "answered_by") == [
        {"kind": "journey", "answered_by": answered_by}
    ]


async def test_resume_sends_nothing_for_a_closed_row(env: Env) -> None:
    fake = journey_paused(END_TURN)
    h = env.harness(fake)
    plan_id = await h.create_plan()

    async with consumers(h) as start:
        first = start(plan_id)
        await wait_stored(h, JOURNEY_IDLE)
        await fake.reached("paused")
        await stop(first)
        await note_interrupt(h, plan_id)
        sink = EventSink(plan_id, session_factory=h.factory, hub=h.hub)
        assert await close_choice(sink, JOURNEY_ID, answered_by="closed", selected=[], now=NOW)

        resumed = start(plan_id, fresh=False)
        fake.release("paused")
        assert await finish(resumed) is PlanStatus.INTERRUPTED
    fake.assert_script_done()

    assert tool_results(fake) == []  # `closed`: the platform answers the call, never the backend
    assert h.deadlines.requested == [DEADLINE]


class BlockingPhotos:
    """A photo lookup that never returns (the process dies while it waits)."""

    def __init__(self) -> None:
        self.entered = asyncio.Event()

    async def photos_for(self, places: Mapping[str, str]) -> dict[str, Cover]:
        self.entered.set()
        await asyncio.Event().wait()
        return {}


async def test_resume_without_a_row_stores_and_asks(env: Env) -> None:
    blocking = BlockingPhotos()
    h = env.harness(scenario("choices"), photos=blocking)
    resumed_at = NOW + dt.timedelta(seconds=100)
    later = at(h, resumed_at, photos=StubPhotos({"a1": cover("Oceanario")}))
    planner = env.planner(later)
    plan_id = await h.create_plan()

    async with consumers(h) as start:
        first = start(plan_id)
        async with asyncio.timeout(RUN_TIMEOUT):
            await blocking.entered.wait()
        await stop(first)  # the process dies between the tool use and its row
        assert await choice_rows(h, plan_id) == []
        assert await stored(h, ACTIVITIES_ID)  # the raw tool use is in the timeline
        assert not await stored(h, asked_key(plan_id, ACTIVITIES_ID))

        resumed = start(plan_id, fresh=False, harness=later)
        await wait_asked(h, plan_id, ACTIVITIES_ID)
        await until(lambda: h.deadlines.waiting == 1)
        [row] = await choice_rows(h, plan_id)
        fresh = resumed_at + dt.timedelta(seconds=240)
        assert (row.asked_at, row.deadline_at) == (resumed_at, fresh)
        assert h.deadlines.requested == [fresh]
        assert list(row.payload["photos"]) == ["a1"]
        await answer_choice(
            plan_id, ACTIVITIES_ID, ChoiceAnswer(selected=["a1", "a3"]), USER, services=planner
        )
        await answer_next(h, planner, plan_id, FOOD_ID)
        assert await finish(resumed) is PlanStatus.READY
    h.fake.assert_script_done()

    assert results_by_id(h.fake)[ACTIVITIES_ID] == [(PICKS_TEXT, False)]
    titles = await choice_titles(h, plan_id)
    assert titles.count("Tocca a te: scegli cosa vedere") == 1


async def test_resume_counts_the_platforms_closure(env: Env) -> None:
    fake = scenario("choice_interrupt")
    h = env.harness(fake)
    plan_id = await h.create_plan()

    async with consumers(h) as start:
        first = start(plan_id)
        await wait_stored(h, INTERRUPT_CHOICE_IDLE)
        await until(lambda: h.deadlines.waiting == 1)
        await stop(first)
        # "Interrompi" while no consumer follows the plan: the request is stored, and the
        # platform closes the waiting call itself (an `agent.tool_result` in the history).
        await note_interrupt(h, plan_id)
        await fake.send_interrupt(SID)
        await fake.wait_until_done()

        resumed = start(plan_id, fresh=False)
        assert await finish(resumed) is PlanStatus.INTERRUPTED
    fake.assert_script_done()

    assert tool_results(fake) == []  # not answered again
    assert h.deadlines.requested == [DEADLINE]  # not re-armed
    row = await choice_row(h, plan_id, INTERRUPT_CHOICE_ID)
    assert row.answered_by == "closed"
    assert await choice_titles(h, plan_id) == [
        "Tocca a te: scegli cosa mangiare",
        "Domanda chiusa: piano interrotto",
    ]


async def test_the_question_and_its_row_are_stored_together(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(record: ChoiceRecord, *, cost_cents: int | None) -> Callable[[int], Any]:
        def build(seq: int) -> Any:
            raise RuntimeError("the process dies while storing the question")

        return build

    monkeypatch.setattr(consumer_module, "choice_asked_event", broken)
    fake = script(pause("sevt_q1", request("food")), end=False)
    h = env.harness(fake)
    plan_id = await h.create_plan()

    async with running(h, plan_id) as task:
        assert await finish(task) is PlanStatus.FAILED

    # One transaction: no row without its question on the timeline.
    assert await choice_rows(h, plan_id) == []
    assert not await stored(h, asked_key(plan_id, "sevt_q1"))


async def test_an_existing_row_is_the_truth(env: Env) -> None:
    # The row was stored from this call under an earlier rule that its raw input fails today.
    fake = script(pause("sevt_q1", request("food", question="x" * 121), is_error=False))
    h = env.harness(fake)
    planner = env.planner(h)
    plan_id = await h.create_plan()
    async with h.factory() as db, db.begin():
        await insert_choice(
            db,
            choice_id="sevt_q1",
            plan_id=plan_id,
            request=ChoiceRequest.model_validate(request("food")),
            photos={},
            asked_at=NOW,
            deadline_at=DEADLINE,
        )

    async with running(h, plan_id) as task:
        await answer_next(h, planner, plan_id, "sevt_q1")
        assert await finish(task) is PlanStatus.READY
    fake.assert_script_done()

    text = (
        'The traveller chose: a1 "Torre di Belém", a2 "Castelo de São Jorge". Build the plan '
        "around these and drop the other options you offered."
    )
    assert results_by_id(fake)["sevt_q1"] == [(text, False)]  # no rejection: the row's question
    assert h.deadlines.requested == [DEADLINE]


# --- a budget pause during a question -------------------------------------------------------------


async def test_budget_reached_during_a_pause_then_continue(
    env: Env, choice_logs: list[EventDict], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sessions, "CONTINUE_RESUME_WAIT_SECONDS", 0.0)
    asked, waiting, answered, run_again = pause("sevt_q1", request("activities"), is_error=False)
    budget_reached = {
        "op": "emit",
        "event": {
            "type": "session.status_idle",
            "id": "sevt_budget",
            "stop_reason": {"type": "budget_reached"},
        },
    }
    # The subagents keep working (and spending) while the coordinator waits.
    spent = {"op": "usage", "list_cost_cents": 61}
    raised = {"op": "await_call", "method": "update_budget"}
    fake = script([asked, waiting, spent, budget_reached, raised, answered, run_again])
    h = env.harness(fake)
    planner = env.planner(h)
    registry = planner.registry
    assert registry is not None
    plan_id = await h.create_plan()

    try:
        first = registry.start(plan_id, SID, first_message=BRIEF)
        await until(lambda: first.done)
        assert (await h.plan(plan_id)).status == PlanStatus.BUDGET_PAUSED
        assert h.deadlines.cancelled == [DEADLINE]  # the paused consumer disarmed its timer
        with pytest.raises(ChoiceClosedError) as refused:
            await answer_choice(
                plan_id, "sevt_q1", ChoiceAnswer(selected=["a1"]), USER, services=planner
            )
        assert refused.value.answered_by is None  # the plan waits for "Continua", not for it
        assert not await closed_row(h, plan_id, "sevt_q1")

        assert await continue_plan(plan_id, USER, services=planner) == 261
        nudges = list(planner.background_tasks)
        resumed = registry.get(plan_id)
        assert resumed is not None
        await until(lambda: h.deadlines.waiting == 1)
        assert h.deadlines.requested == [DEADLINE, DEADLINE]  # re-armed with the row's deadline
        await asyncio.gather(*nudges)  # the question is pending: no CONTINUE_MESSAGE
        await answer_choice(
            plan_id, "sevt_q1", ChoiceAnswer(selected=["a1"]), USER, services=planner
        )
        await until(lambda: resumed.done)
    finally:
        await registry.aclose()
        await fake.shutdown()
    fake.assert_script_done()

    assert (await h.plan(plan_id)).status == PlanStatus.READY
    messages = [sent.payload for sent in fake.sent if sent.payload["type"] == "user.message"]
    assert len(messages) == 1  # the brief only
    assert CONTINUE_MESSAGE not in repr(messages)
    assert logged(choice_logs, "continue_message_skipped", "reason") == [
        {"reason": "choice_pending"}
    ]
    text = (
        'The traveller chose: a1 "Torre di Belém". Build the plan around it and drop the other '
        "options you offered."
    )
    assert results_by_id(fake)["sevt_q1"] == [(text, False)]
