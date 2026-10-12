"""UIEvent (app/events.py): the event shape the timeline stores and streams."""

from __future__ import annotations

import datetime as dt
import json
from typing import Any

import pytest
from pydantic import ValidationError
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import EventRecord, PlanRecord
from app.events import MAX_TITLE_LENGTH, AgentName, EventKind, UIEvent, one_line, strip_nul


def make_event(**overrides: Any) -> dict[str, Any]:
    return {
        "seq": 12,
        "ts": "2026-10-12T15:04:05.123000+02:00",
        "agent": "flights",
        "kind": "tool",
        "title": "Expedia · voli MXP→LIS · 14–18 nov",
        "detail": {"tool": "search_flights", "params": {"from": "MXP", "to": "LIS"}, "ms": 2140},
        "cost_cents": 37,
        **overrides,
    }


def error_types(data: dict[str, Any]) -> set[tuple[tuple[str | int, ...], str]]:
    with pytest.raises(ValidationError) as caught:
        UIEvent.model_validate(data)
    return {(tuple(e["loc"]), e["type"]) for e in caught.value.errors()}


def test_event_parses() -> None:
    event = UIEvent.model_validate(make_event())

    assert event.agent is AgentName.FLIGHTS
    assert event.kind is EventKind.TOOL
    assert event.ts.utcoffset() == dt.timedelta(hours=2)
    assert event.detail == {
        "tool": "search_flights",
        "params": {"from": "MXP", "to": "LIS"},
        "ms": 2140,
    }


def test_optional_fields_default_to_none() -> None:
    event = UIEvent.model_validate(make_event(detail=None, cost_cents=None))
    minimal = make_event()
    del minimal["detail"], minimal["cost_cents"]

    assert UIEvent.model_validate(minimal) == event


def test_json_round_trip_is_lossless() -> None:
    event = UIEvent.model_validate(make_event())

    assert UIEvent.model_validate_json(event.model_dump_json()) == event
    dumped = json.loads(event.model_dump_json())
    assert dumped["ts"] == "2026-10-12T15:04:05.123000+02:00"
    assert dumped["agent"] == "flights"
    assert dumped["kind"] == "tool"


def test_serialized_events_carry_every_key() -> None:
    dumped = UIEvent.model_validate(make_event(detail=None, cost_cents=None)).model_dump(
        mode="json"
    )

    assert set(dumped) == {"seq", "ts", "agent", "kind", "title", "detail", "cost_cents"}
    assert dumped["detail"] is None


def test_built_from_python_values() -> None:
    event = UIEvent(
        seq=0,
        ts=dt.datetime(2026, 10, 12, 13, 0, tzinfo=dt.UTC),
        agent=AgentName.COORDINATOR,
        kind=EventKind.STATUS,
        title="Piano avviato",
    )

    assert event.model_dump(mode="json")["ts"] == "2026-10-12T13:00:00Z"


def test_agent_and_kind_values() -> None:
    assert [a.value for a in AgentName] == [
        "coordinator",
        "flights",
        "lodging",
        "activities",
        "transport",
    ]
    assert [k.value for k in EventKind] == ["status", "tool", "message", "usage", "error", "plan"]


@pytest.mark.parametrize("agent", [a.value for a in AgentName])
@pytest.mark.parametrize("kind", [k.value for k in EventKind])
def test_every_agent_and_kind_is_accepted(agent: str, kind: str) -> None:
    event = UIEvent.model_validate(make_event(agent=agent, kind=kind))

    assert (event.agent.value, event.kind.value) == (agent, kind)


@pytest.mark.parametrize(
    ("field", "value", "error"),
    [
        ("agent", "planner", "enum"),
        ("kind", "progress", "enum"),
        ("seq", -1, "greater_than_equal"),
        ("cost_cents", -5, "greater_than_equal"),
        ("ts", "2026-10-12T15:04:05", "timezone_aware"),
        ("title", "", "string_too_short"),
        ("title", "x" * (MAX_TITLE_LENGTH + 1), "string_too_long"),
        ("title", "prima riga\nseconda riga", "string_pattern_mismatch"),
        ("title", "ritorno a capo\r", "string_pattern_mismatch"),
        ("detail", ["not", "an", "object"], "dict_type"),
    ],
)
def test_bad_values_are_rejected(field: str, value: Any, error: str) -> None:
    assert error_types(make_event(**{field: value})) == {((field,), error)}


def test_title_of_max_length_is_accepted() -> None:
    UIEvent.model_validate(make_event(title="x" * MAX_TITLE_LENGTH))


def test_unknown_fields_are_rejected() -> None:
    assert error_types(make_event(plan_id="p1")) == {(("plan_id",), "extra_forbidden")}


@pytest.mark.parametrize("field", ["seq", "ts", "agent", "kind", "title"])
def test_required_fields(field: str) -> None:
    data = make_event()
    del data[field]

    assert error_types(data) == {((field,), "missing")}


def test_one_line_collapses_whitespace() -> None:
    assert one_line("  coordinatore →\n voli:\t incarico \r\n") == "coordinatore → voli: incarico"


def test_one_line_keeps_short_text() -> None:
    assert one_line("x" * MAX_TITLE_LENGTH) == "x" * MAX_TITLE_LENGTH


def test_one_line_truncates_with_an_ellipsis() -> None:
    title = one_line("parola " * 100)

    assert len(title) == MAX_TITLE_LENGTH
    assert title.endswith("par…")
    UIEvent.model_validate(make_event(title=title))


def test_one_line_custom_limit() -> None:
    assert one_line("abcdefghij", limit=5) == "abcd…"


# --- U+0000 (Postgres can't store it) ------------------------------------------------------


def test_strip_nul_cleans_nested_values() -> None:
    value = {"a\x00": ["x\x00y", ("z\x00",), 3, None], "n": {"m": "\x00"}}

    assert strip_nul(value) == {"a": ["xy", ["z"], 3, None], "n": {"m": ""}}
    assert strip_nul(7) == 7


def test_nul_is_removed_from_title_and_detail() -> None:
    event = UIEvent.model_validate(
        make_event(title="Pagina\x00 letta", detail={"text\x00": "da una\x00 pagina"})
    )

    assert event.title == "Pagina letta"
    assert event.detail == {"text": "da una pagina"}


def test_a_title_made_only_of_nul_is_still_rejected() -> None:
    assert error_types(make_event(title="\x00")) == {(("title",), "string_too_short")}


async def test_an_event_with_nul_in_its_input_can_be_stored(db_session: AsyncSession) -> None:
    plan = PlanRecord(
        user_email="test@example.com",
        agent_profile="development",
        request={"preferences": "cucina locale"},
    )
    db_session.add(plan)
    await db_session.flush()
    event = UIEvent.model_validate(
        make_event(title="Risultato\x00", detail={"params": {"query": "Lisbona\x00 tram"}})
    )
    db_session.add(
        EventRecord(
            plan_id=plan.id,
            seq=event.seq,
            ts=event.ts,
            agent=event.agent.value,
            kind=event.kind.value,
            title=event.title,
            detail=event.model_dump(mode="json")["detail"],
            ma_event_id="sevt_nul",
        )
    )
    await db_session.commit()
    db_session.expunge_all()

    stored = await db_session.get_one(EventRecord, (plan.id, event.seq))
    assert stored.title == "Risultato"
    assert stored.detail == {"params": {"query": "Lisbona tram"}}


async def test_postgres_rejects_nul_that_was_not_removed(db_session: AsyncSession) -> None:
    """Why the models reject or strip U+0000: jsonb refuses it outright."""
    db_session.add(
        PlanRecord(
            user_email="test@example.com",
            agent_profile="development",
            request={"preferences": "cucina\x00locale"},
        )
    )

    with pytest.raises(DBAPIError, match="Unicode"):
        await db_session.commit()
