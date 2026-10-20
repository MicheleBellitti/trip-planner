"""The `choices` table, the `choice` event kind and closing a choice exactly once."""

from __future__ import annotations

import asyncio
import datetime as dt
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.choices import (
    PendingChoice,
    answered_choices,
    asked_kinds,
    get_choice,
    insert_choice,
    pending_choice,
    request_of,
)
from app.consumer import (
    EventSink,
    backend_event,
    backend_event_id,
    choice_asked_event,
    close_choice,
)
from app.covers import Cover
from app.db import ChoiceRecord, EventRecord
from app.events import EventKind, UIEvent
from app.hub import PlanHub
from tests.conftest import PlanRows
from tests.test_choices import ACTIVITIES, FOOD, JOURNEY

NOW = dt.datetime(2026, 10, 20, 10, 0, tzinfo=dt.UTC)
DEADLINE = NOW + dt.timedelta(seconds=240)

type Factory = async_sessionmaker[AsyncSession]


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


async def add(
    factory: Factory,
    plan_id: uuid.UUID,
    choice_id: str = "sevt_q1",
    *,
    request: Any = ACTIVITIES,
    photos: dict[str, Cover] | None = None,
    asked_at: dt.datetime = NOW,
) -> ChoiceRecord:
    async with factory() as db, db.begin():
        return await insert_choice(
            db,
            choice_id=choice_id,
            plan_id=plan_id,
            request=request,
            photos=photos or {},
            asked_at=asked_at,
            deadline_at=asked_at + dt.timedelta(seconds=240),
        )


async def choice_events(factory: Factory, plan_id: uuid.UUID) -> list[EventRecord]:
    async with factory() as db:
        rows = await db.scalars(
            select(EventRecord)
            .where(EventRecord.plan_id == plan_id, EventRecord.kind == "choice")
            .order_by(EventRecord.seq)
        )
        return list(rows)


async def setup(db_session_factory: Factory, plan_rows: PlanRows) -> tuple[uuid.UUID, EventSink]:
    plan = await plan_rows.add_plan()
    return plan.id, EventSink(plan.id, session_factory=db_session_factory, hub=PlanHub())


async def test_insert_choice_is_idempotent(
    db_session_factory: Factory, plan_rows: PlanRows
) -> None:
    plan_id, _ = await setup(db_session_factory, plan_rows)
    first = await add(db_session_factory, plan_id, photos={"a1": cover("Belem")})
    second = await add(
        db_session_factory, plan_id, request=FOOD, photos={"a2": cover("Altra")}, asked_at=DEADLINE
    )
    assert second.payload == first.payload
    assert second.kind == "activities"
    assert request_of(second) == ACTIVITIES
    assert list(second.payload["photos"]) == ["a1"]
    assert second.asked_at == NOW


async def test_pending_choice_is_the_open_one(
    db_session_factory: Factory, plan_rows: PlanRows
) -> None:
    plan_id, sink = await setup(db_session_factory, plan_rows)
    assert await _pending(db_session_factory, plan_id) is None
    await add(db_session_factory, plan_id, "sevt_q1")
    await add(db_session_factory, plan_id, "sevt_q2", request=FOOD, asked_at=DEADLINE)
    latest = await _pending(db_session_factory, plan_id)
    assert latest is not None
    assert latest.id == "sevt_q2"
    assert await close_choice(sink, "sevt_q2", answered_by="skip", selected=[], now=NOW)
    reopened = await _pending(db_session_factory, plan_id)
    assert reopened is not None
    assert reopened.id == "sevt_q1"
    view = PendingChoice.from_record(reopened)
    assert view.kind == "activities"
    assert view.multiple is True
    assert [o.id for o in view.options] == ["a1", "a2", "a3", "a4"]
    assert view.deadline_at == NOW + dt.timedelta(seconds=240)
    assert await close_choice(sink, "sevt_q1", answered_by="traveller", selected=["a1"], now=NOW)
    assert await _pending(db_session_factory, plan_id) is None
    async with db_session_factory() as db:
        answered = await answered_choices(db, plan_id)
    assert [c.id for c in answered] == ["sevt_q1", "sevt_q2"]


async def _pending(factory: Factory, plan_id: uuid.UUID) -> ChoiceRecord | None:
    async with factory() as db:
        return await pending_choice(db, plan_id)


async def test_pending_view_carries_photos_but_not_the_place(
    db_session_factory: Factory, plan_rows: PlanRows
) -> None:
    plan_id, _ = await setup(db_session_factory, plan_rows)
    record = await add(db_session_factory, plan_id, photos={"a2": cover("Castelo")})
    view = PendingChoice.from_record(record)
    by_id = {o.id: o for o in view.options}
    assert by_id["a2"].photo == cover("Castelo")
    assert by_id["a1"].photo is None
    assert "place" not in by_id["a2"].model_dump()
    assert by_id["a2"].price is not None
    assert by_id["a2"].area == "Alfama"


async def test_asked_kinds(db_session_factory: Factory, plan_rows: PlanRows) -> None:
    plan_id, sink = await setup(db_session_factory, plan_rows)
    await add(db_session_factory, plan_id, "sevt_q1", request=FOOD)
    await add(db_session_factory, plan_id, "sevt_q2", request=JOURNEY)
    await close_choice(sink, "sevt_q1", answered_by="skip", selected=[], now=NOW)
    async with db_session_factory() as db:
        assert sorted(await asked_kinds(db, plan_id)) == ["food", "journey"]
        assert await get_choice(db, plan_id, "sevt_q1") is not None
        assert await get_choice(db, plan_id, "nope") is None
        assert await get_choice(db, uuid.uuid4(), "sevt_q1") is None


async def test_close_choice_once(db_session_factory: Factory, plan_rows: PlanRows) -> None:
    plan_id, sink = await setup(db_session_factory, plan_rows)
    await add(db_session_factory, plan_id)
    first = await close_choice(sink, "sevt_q1", answered_by="traveller", selected=["a1"], now=NOW)
    second = await close_choice(sink, "sevt_q1", answered_by="timeout", selected=[], now=NOW)
    assert first is not None
    assert first.answered_by == "traveller"
    assert second is None
    assert first.answer == ["a1"]
    assert first.answered_at == NOW
    events = await choice_events(db_session_factory, plan_id)
    assert [e.title for e in events] == ["Hai scelto: Torre di Belém"]
    assert events[0].ma_event_id == backend_event_id(plan_id, "choice", "sevt_q1:closed")
    assert events[0].detail == {
        "event_type": "backend.choice",
        "phase": "answered",
        "choice_id": "sevt_q1",
        "kind": "activities",
        "answered_by": "traveller",
        "selected": ["a1"],
        "answered_at": NOW.isoformat(),
    }
    async with db_session_factory() as db:
        row = await get_choice(db, plan_id, "sevt_q1")
    assert row is not None
    assert row.answered_by == "traveller"


async def test_close_choice_concurrent_one_wins(
    db_session_factory: Factory, plan_rows: PlanRows
) -> None:
    plan_id, sink = await setup(db_session_factory, plan_rows)
    await add(db_session_factory, plan_id)
    results = await asyncio.gather(
        close_choice(sink, "sevt_q1", answered_by="traveller", selected=["a1"], now=NOW),
        close_choice(sink, "sevt_q1", answered_by="timeout", selected=[], now=NOW),
    )
    winners = [r for r in results if r is not None]
    assert len(winners) == 1
    assert len(await choice_events(db_session_factory, plan_id)) == 1
    async with db_session_factory() as db:
        row = await get_choice(db, plan_id, "sevt_q1")
    assert row is not None
    assert row.answered_by == winners[0].answered_by


async def test_close_choice_of_an_unknown_id_stores_nothing(
    db_session_factory: Factory, plan_rows: PlanRows
) -> None:
    plan_id, sink = await setup(db_session_factory, plan_rows)
    result = await close_choice(sink, "sevt_nope", answered_by="skip", selected=[], now=NOW)
    assert result is None
    assert await choice_events(db_session_factory, plan_id) == []


async def test_close_choice_of_another_plans_choice_stores_nothing(
    db_session_factory: Factory, plan_rows: PlanRows
) -> None:
    plan_id, _ = await setup(db_session_factory, plan_rows)
    other = await plan_rows.add_plan()
    await add(db_session_factory, plan_id)
    other_sink = EventSink(other.id, session_factory=db_session_factory, hub=PlanHub())
    assert (
        await close_choice(other_sink, "sevt_q1", answered_by="skip", selected=[], now=NOW) is None
    )
    async with db_session_factory() as db:
        row = await get_choice(db, plan_id, "sevt_q1")
    assert row is not None
    assert row.answered_by is None


async def test_choice_asked_event(db_session_factory: Factory, plan_rows: PlanRows) -> None:
    plan_id, sink = await setup(db_session_factory, plan_rows)
    record = await add(db_session_factory, plan_id)
    result = await sink.emit(
        choice_asked_event(record, cost_cents=12),
        ma_event_id=backend_event_id(plan_id, "choice", "sevt_q1:asked"),
    )
    assert result.event is not None
    assert result.event.kind is EventKind.CHOICE
    assert result.event.title == "Tocca a te: scegli cosa vedere"
    assert result.event.cost_cents == 12
    detail = result.event.detail
    assert detail is not None
    assert (detail["event_type"], detail["phase"]) == ("backend.choice", "asked")
    assert detail["choice"] == PendingChoice.from_record(record).model_dump(mode="json")


async def test_emit_guard_false_stores_nothing(
    db_session_factory: Factory, plan_rows: PlanRows
) -> None:
    from app.consumer import PlanUpdate

    plan_id, sink = await setup(db_session_factory, plan_rows)

    async def deny(_db: AsyncSession) -> bool:
        return False

    result = await sink.emit(
        backend_event(EventKind.CHOICE, "x", ts=NOW),
        ma_event_id="sevt_guarded",
        update=PlanUpdate(cost_cents=99),
        guard=deny,
    )
    assert result.refused
    assert result.event is None
    assert (result.duplicate, result.status_applied) == (False, False)
    assert await choice_events(db_session_factory, plan_id) == []
    async with db_session_factory() as db:
        plan = await db.get(type(await _plan(db_session_factory, plan_id)), plan_id)
    assert plan is not None
    assert plan.cost_cents == 0

    async def allow(_db: AsyncSession) -> bool:
        return True

    ok = await sink.emit(
        backend_event(EventKind.CHOICE, "x", ts=NOW), ma_event_id="sevt_guarded", guard=allow
    )
    assert ok.event is not None
    assert not ok.refused


async def _plan(factory: Factory, plan_id: uuid.UUID) -> Any:
    from app.db import PlanRecord

    async with factory() as db:
        return await db.get(PlanRecord, plan_id)


async def test_choices_are_deleted_with_their_plan(
    db_session_factory: Factory, plan_rows: PlanRows
) -> None:
    plan_id, _ = await setup(db_session_factory, plan_rows)
    await add(db_session_factory, plan_id)
    async with db_session_factory() as db, db.begin():
        await db.delete(await db.get(type(await _plan(db_session_factory, plan_id)), plan_id))
    async with db_session_factory() as db:
        assert list(await db.scalars(select(ChoiceRecord))) == []


def test_ui_event_kind_includes_choice() -> None:
    event = UIEvent.model_validate(
        {
            "seq": 0,
            "ts": NOW.isoformat(),
            "agent": "coordinator",
            "kind": "choice",
            "title": "Tocca a te",
            "detail": None,
            "cost_cents": None,
        }
    )
    assert event.kind is EventKind.CHOICE
