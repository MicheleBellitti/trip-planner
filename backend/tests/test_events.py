"""events.normalize (app/events.py): every Managed Agents event becomes a UIEvent.

Spec row (test e verifica): "ogni tipo di evento Managed Agents noto diventa un UIEvent; un
tipo sconosciuto diventa un evento generico, non un'eccezione". Contract:
docs/backend-interfaces.md §7. The sample events below are validated against the SDK's own
event union (anthropic 1.13.0), so they can't drift from the real shapes; the scenario scripts
in tests/fixtures/ma/*.jsonl, when present, are normalized too.
"""

from __future__ import annotations

import copy
import datetime as dt
import json
import typing
from pathlib import Path
from typing import Any

import pytest
import time_machine
from anthropic.types.beta.sessions.beta_managed_agents_stream_session_events import (
    BetaManagedAgentsStreamSessionEvents,
)
from pydantic import TypeAdapter

from app import consumer
from app.events import (
    ACTION_EVENT_TYPES,
    AGENT_LABELS,
    KNOWN_EVENT_TYPES,
    MAX_DETAIL_CHARS,
    MAX_TEXT_CHARS,
    MAX_TITLE_LENGTH,
    NOISE_EVENT_TYPES,
    AgentName,
    EventKind,
    UIEvent,
    agent_label,
    format_date_range,
    format_duration,
    format_usd,
    normalize,
)

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "ma"
TS = "2026-10-12T10:00:00.123Z"
SECRET = "TOOL-RESULT-SECRET"
"""Marker placed in tool results, fetched pages and written files: it must never come out."""

SDK_EVENT = TypeAdapter(BetaManagedAgentsStreamSessionEvents)


def ev(event_type: str, **fields: Any) -> dict[str, Any]:
    """A raw event as the API sends it (`id`, `type`, `processed_at` plus the type's keys)."""
    return {
        "id": f"sevt_{event_type.replace('.', '_')}",
        "type": event_type,
        "processed_at": TS,
    } | (fields)


def text(value: str) -> list[dict[str, Any]]:
    return [{"type": "text", "text": value}]


def norm(
    raw: dict[str, Any],
    agent: AgentName = AgentName.COORDINATOR,
    **kwargs: Any,
) -> UIEvent:
    event = normalize(raw, seq=7, agent=agent, **kwargs)
    assert event is not None
    return event


def dumped(event: UIEvent) -> str:
    return event.model_dump_json()


# --- one sample per known type ------------------------------------------------------------------

# (raw event, lane, expected kind, expected title)
SAMPLES: dict[str, tuple[dict[str, Any], AgentName, EventKind, str]] = {
    "user.message": (
        ev("user.message", content=text("Today is 2026-10-12 (Europe/Rome).\nAll text...")),
        AgentName.COORDINATOR,
        EventKind.MESSAGE,
        "utente → coordinatore: richiesta di viaggio",
    ),
    "user.interrupt": (
        ev("user.interrupt", id=""),
        AgentName.COORDINATOR,
        EventKind.STATUS,
        "Interruzione richiesta",
    ),
    "user.tool_confirmation": (
        ev("user.tool_confirmation", tool_use_id="sevt_tool", result="allow"),
        AgentName.FLIGHTS,
        EventKind.STATUS,
        "Permesso concesso",
    ),
    "user.custom_tool_result": (
        ev(
            "user.custom_tool_result",
            custom_tool_use_id="sevt_submit",
            content=text(SECRET),
            is_error=True,
        ),
        AgentName.COORDINATOR,
        EventKind.TOOL,
        "Esito inviato all'agente: da correggere",
    ),
    "user.tool_result": (
        ev("user.tool_result", tool_use_id="sevt_tool", content=text(SECRET)),
        AgentName.FLIGHTS,
        EventKind.TOOL,
        "Risultato dello strumento inviato",
    ),
    "user.define_outcome": (
        ev(
            "user.define_outcome",
            description="d",
            outcome_id="out_1",
            rubric={"type": "text", "content": "r"},
        ),
        AgentName.COORDINATOR,
        EventKind.STATUS,
        "Obiettivo definito",
    ),
    "system.message": (
        ev("system.message", content=text("note")),
        AgentName.COORDINATOR,
        EventKind.STATUS,
        "Messaggio di sistema",
    ),
    "agent.custom_tool_use": (
        ev("agent.custom_tool_use", name="submit_plan", input={"title": SECRET}),
        AgentName.COORDINATOR,
        EventKind.PLAN,
        "Piano inviato per la verifica",
    ),
    "agent.message": (
        ev("agent.message", content=text("Ho trovato 3 voli diretti.\nDettagli nel file.")),
        AgentName.FLIGHTS,
        EventKind.MESSAGE,
        "voli → coordinatore: Ho trovato 3 voli diretti.",
    ),
    "agent.thinking": (
        ev("agent.thinking"),
        AgentName.LODGING,
        EventKind.STATUS,
        "Ragionamento in corso",
    ),
    "agent.mcp_tool_use": (
        ev(
            "agent.mcp_tool_use",
            mcp_server_name="expedia",
            name="search_flights",
            input={
                "origin": "MXP",
                "destination": "LIS",
                "departure_date": "2026-11-14",
                "return_date": "2026-11-18",
                "adults": 2,
            },
            evaluated_permission="allow",
        ),
        AgentName.FLIGHTS,
        EventKind.TOOL,
        "Expedia · voli MXP→LIS · 14–18 nov",
    ),
    "agent.mcp_tool_result": (
        ev("agent.mcp_tool_result", mcp_tool_use_id="sevt_mcp", content=text(SECRET)),
        AgentName.FLIGHTS,
        EventKind.TOOL,
        "Risposta della fonte ricevuta",
    ),
    "agent.tool_use": (
        ev("agent.tool_use", name="web_search", input={"query": "tram 28 Lisbona orari"}),
        AgentName.ACTIVITIES,
        EventKind.TOOL,
        "Ricerca web: tram 28 Lisbona orari",
    ),
    "agent.tool_result": (
        ev("agent.tool_result", tool_use_id="sevt_tool", content=text(SECRET), is_error=False),
        AgentName.ACTIVITIES,
        EventKind.TOOL,
        "Risultato ricevuto",
    ),
    "agent.thread_message_received": (
        ev(
            "agent.thread_message_received",
            from_session_thread_id="sthr_lodging",
            from_agent_name="lodging",
            content=text("Tre alloggi in results/lodging.json.\nVersione 2."),
        ),
        AgentName.LODGING,
        EventKind.MESSAGE,
        "alloggio → coordinatore: Tre alloggi in results/lodging.json.",
    ),
    "agent.thread_message_sent": (
        ev(
            "agent.thread_message_sent",
            to_session_thread_id="sthr_flights",
            to_agent_name="flights",
            content=text("Find flights MXP to LIS, 14-18 Nov, 2 adults.\nWrite results."),
        ),
        AgentName.FLIGHTS,
        EventKind.MESSAGE,
        "coordinatore → voli: Find flights MXP to LIS, 14-18 Nov, 2 adults.",
    ),
    "agent.thread_context_compacted": (
        ev("agent.thread_context_compacted"),
        AgentName.COORDINATOR,
        EventKind.STATUS,
        "Memoria della conversazione compattata",
    ),
    "session.error": (
        ev(
            "session.error",
            error={
                "type": "mcp_connection_failed_error",
                "mcp_server_name": "kiwi",
                "message": "Connection refused",
                "retry_status": {"type": "exhausted"},
            },
        ),
        AgentName.FLIGHTS,
        EventKind.ERROR,
        "Fonte Kiwi.com non raggiungibile: il piano prosegue con le altre fonti",
    ),
    "session.status_rescheduled": (
        ev("session.status_rescheduled"),
        AgentName.COORDINATOR,
        EventKind.STATUS,
        "Errore temporaneo: la piattaforma riprova",
    ),
    "session.status_running": (
        ev("session.status_running"),
        AgentName.COORDINATOR,
        EventKind.STATUS,
        "Al lavoro",
    ),
    "session.status_idle": (
        ev("session.status_idle", stop_reason={"type": "end_turn"}),
        AgentName.COORDINATOR,
        EventKind.STATUS,
        "Turno concluso",
    ),
    "session.status_terminated": (
        ev("session.status_terminated"),
        AgentName.COORDINATOR,
        EventKind.STATUS,
        "Sessione chiusa",
    ),
    "session.thread_created": (
        ev("session.thread_created", session_thread_id="sthr_flights", agent_name="flights"),
        AgentName.FLIGHTS,
        EventKind.STATUS,
        "Incarico a voli",
    ),
    "span.outcome_evaluation_start": (
        ev("span.outcome_evaluation_start", outcome_id="out_1", iteration=1),
        AgentName.COORDINATOR,
        EventKind.STATUS,
        "Verifica del risultato avviata, giro 1",
    ),
    "span.outcome_evaluation_end": (
        ev(
            "span.outcome_evaluation_end",
            outcome_id="out_1",
            outcome_evaluation_start_id="sevt_start",
            iteration=1,
            result="needs_revision",
            explanation=SECRET,
            usage={
                "input_tokens": 1,
                "output_tokens": 1,
                "cache_creation_input_tokens": 0,
                "cache_read_input_tokens": 0,
            },
        ),
        AgentName.COORDINATOR,
        EventKind.STATUS,
        "Verifica del risultato: da rivedere",
    ),
    "span.model_request_start": (
        ev("span.model_request_start"),
        AgentName.TRANSPORT,
        EventKind.STATUS,
        "Richiesta al modello",
    ),
    "span.model_request_end": (
        ev(
            "span.model_request_end",
            model_request_start_id="sevt_start",
            model_usage={
                "input_tokens": 1200,
                "output_tokens": 340,
                "cache_creation_input_tokens": 0,
                "cache_read_input_tokens": 800,
            },
        ),
        AgentName.TRANSPORT,
        EventKind.STATUS,
        "Risposta del modello",
    ),
    "span.outcome_evaluation_ongoing": (
        ev("span.outcome_evaluation_ongoing", outcome_id="out_1", iteration=2),
        AgentName.COORDINATOR,
        EventKind.STATUS,
        "Verifica del risultato in corso, giro 2",
    ),
    "session.deleted": (
        ev("session.deleted"),
        AgentName.COORDINATOR,
        EventKind.STATUS,
        "Sessione eliminata",
    ),
    "session.thread_status_running": (
        ev("session.thread_status_running", session_thread_id="sthr_l", agent_name="lodging"),
        AgentName.LODGING,
        EventKind.STATUS,
        "Al lavoro",
    ),
    "session.thread_status_idle": (
        ev(
            "session.thread_status_idle",
            session_thread_id="sthr_l",
            agent_name="lodging",
            stop_reason={"type": "end_turn"},
        ),
        AgentName.LODGING,
        EventKind.STATUS,
        "Turno concluso",
    ),
    "session.thread_status_terminated": (
        ev("session.thread_status_terminated", session_thread_id="sthr_l", agent_name="lodging"),
        AgentName.LODGING,
        EventKind.STATUS,
        "Lavoro chiuso",
    ),
    "session.thread_status_rescheduled": (
        ev("session.thread_status_rescheduled", session_thread_id="sthr_l", agent_name="lodging"),
        AgentName.LODGING,
        EventKind.STATUS,
        "Errore temporaneo: la piattaforma riprova",
    ),
    "session.updated": (
        ev(
            "session.updated",
            budget={"type": "limit", "max_list_cost": {"amount": "260", "currency": "USD"}},
        ),
        AgentName.COORDINATOR,
        EventKind.STATUS,
        "Budget della sessione portato a 2,60 $",
    ),
    "session.usage": (
        ev(
            "session.usage",
            usage={
                "list_cost": {"amount": "41", "currency": "USD"},
                "input_tokens": 120_000,
                "output_tokens": 9_000,
                "cache_read_input_tokens": 50_000,
                "server_tool_use": {"web_search_requests": 4, "web_fetch_requests": 0},
                "active_seconds": 312.5,
            },
            budget={"type": "limit", "max_list_cost": {"amount": "60", "currency": "USD"}},
        ),
        AgentName.COORDINATOR,
        EventKind.USAGE,
        "Costo finora: 0,41 $ su 0,60 $",
    ),
    "workflow_run.created": (
        ev(
            "workflow_run.created",
            name="wf",
            phases=[{"id": "ph_1", "name": "one"}],
            workflow_run_id="wfr_1",
        ),
        AgentName.COORDINATOR,
        EventKind.STATUS,
        "Workflow avviato",
    ),
    "workflow_run.status_ended": (
        ev("workflow_run.status_ended", workflow_run_id="wfr_1", result={"type": "completed"}),
        AgentName.COORDINATOR,
        EventKind.STATUS,
        "Workflow concluso",
    ),
    "workflow_run.phase_started": (
        ev("workflow_run.phase_started", workflow_run_id="wfr_1", workflow_run_phase_id="ph_1"),
        AgentName.COORDINATOR,
        EventKind.STATUS,
        "Fase del workflow avviata",
    ),
    "workflow_run.phase_ended": (
        ev(
            "workflow_run.phase_ended",
            workflow_run_id="wfr_1",
            workflow_run_phase_id="ph_1",
            phase_started_id="sevt_ps",
        ),
        AgentName.COORDINATOR,
        EventKind.STATUS,
        "Fase del workflow conclusa",
    ),
    "workflow_run.status_running": (
        ev("workflow_run.status_running", workflow_run_id="wfr_1"),
        AgentName.COORDINATOR,
        EventKind.STATUS,
        "Workflow in corso",
    ),
    "workflow_run.status_idle": (
        ev("workflow_run.status_idle", workflow_run_id="wfr_1"),
        AgentName.COORDINATOR,
        EventKind.STATUS,
        "Workflow in pausa",
    ),
    "workflow_run.error": (
        ev(
            "workflow_run.error",
            workflow_run_id="wfr_1",
            error={"type": "unknown_error", "message": "boom"},
        ),
        AgentName.COORDINATOR,
        EventKind.ERROR,
        "Errore del workflow",
    ),
}
PERSISTED_TYPES = sorted(SAMPLES)


def sdk_event_types() -> set[str]:
    """Every `type` literal of the SDK's stream event union (persisted + stream-only)."""
    union = typing.get_args(typing.get_args(BetaManagedAgentsStreamSessionEvents)[0])
    literals: set[str] = set()
    for model in union:
        literals.update(typing.get_args(model.model_fields["type"].annotation))
    return literals


def test_the_catalog_covers_every_sdk_event_type() -> None:
    assert sdk_event_types() == KNOWN_EVENT_TYPES
    assert set(SAMPLES) | NOISE_EVENT_TYPES == KNOWN_EVENT_TYPES


@pytest.mark.parametrize("event_type", PERSISTED_TYPES)
def test_samples_are_real_sdk_shapes(event_type: str) -> None:
    raw = SAMPLES[event_type][0]

    assert SDK_EVENT.validate_python(raw).type == event_type


@pytest.mark.parametrize("event_type", PERSISTED_TYPES)
def test_every_known_type_becomes_a_ui_event(event_type: str) -> None:
    raw, lane, kind, title = SAMPLES[event_type]

    event = norm(raw, lane, cost_cents=12)

    assert (event.seq, event.agent, event.kind, event.title) == (7, lane, kind, title)
    assert event.ts == dt.datetime(2026, 10, 12, 10, 0, 0, 123000, tzinfo=dt.UTC)
    assert event.detail is not None
    assert event.detail["event_type"] == event_type
    assert SECRET not in dumped(event)
    expected_cost = 41 if event_type == "session.usage" else 12
    assert event.cost_cents == expected_cost
    UIEvent.model_validate_json(event.model_dump_json())


@pytest.mark.parametrize("event_type", sorted(NOISE_EVENT_TYPES))
def test_stream_previews_are_noise(event_type: str) -> None:
    raw: dict[str, Any] = {
        "event_start": {"type": "event_start", "event": {"type": "agent.message", "id": "e1"}},
        "event_delta": {
            "type": "event_delta",
            "event_id": "e1",
            "delta": {"type": "content_delta", "index": 0, "content": text("Ci")[0]},
        },
    }[event_type]
    assert SDK_EVENT.validate_python(raw).type == event_type

    assert normalize(raw, seq=0, agent=AgentName.COORDINATOR) is None


def test_action_event_types_match_the_consumer() -> None:
    assert ACTION_EVENT_TYPES == consumer.ACTION_EVENT_TYPES
    assert ACTION_EVENT_TYPES <= KNOWN_EVENT_TYPES
    assert not ACTION_EVENT_TYPES & NOISE_EVENT_TYPES


@pytest.mark.parametrize("event_type", sorted(ACTION_EVENT_TYPES))
def test_action_types_are_never_none_even_when_bare(event_type: str) -> None:
    assert normalize({"type": event_type}, seq=0, agent=AgentName.COORDINATOR) is not None
    assert normalize({"type": event_type, "id": ""}, seq=0, agent=AgentName.FLIGHTS) is not None


# --- unknown types, missing keys, nulls, wrong shapes ------------------------------------------


def test_unknown_type_becomes_a_generic_status_event() -> None:
    event = norm({"id": "sevt_x", "type": "session.teleported", "processed_at": TS, "x": SECRET})

    assert event.kind is EventKind.STATUS
    assert event.title == "Evento non riconosciuto: session.teleported"
    assert event.detail == {"event_type": "session.teleported"}


@pytest.mark.parametrize("raw", [{}, {"type": None}, {"type": 42}, {"type": "   "}])
def test_missing_or_bad_type_becomes_a_generic_event(raw: dict[str, Any]) -> None:
    event = norm(raw)

    assert (event.kind, event.title) == (EventKind.STATUS, "Evento senza tipo")
    assert event.detail == {"event_type": None}


def test_a_non_mapping_event_is_a_generic_event() -> None:
    event = normalize(None, seq=1, agent=AgentName.COORDINATOR)  # pyright: ignore[reportArgumentType]

    assert event is not None
    assert event.title == "Evento senza tipo"


@pytest.mark.parametrize("event_type", PERSISTED_TYPES)
def test_only_the_type_is_enough(event_type: str) -> None:
    event = norm({"type": event_type}, AgentName.FLIGHTS)

    assert event.title
    assert event.detail is not None
    assert event.detail["event_type"] == event_type


@pytest.mark.parametrize("event_type", PERSISTED_TYPES)
def test_optional_keys_set_to_null(event_type: str) -> None:
    raw = dict.fromkeys(SAMPLES[event_type][0]) | {"type": event_type}

    event = norm(raw, AgentName.LODGING)

    assert event.title
    assert event.detail is not None
    assert all(value is not None for key, value in event.detail.items() if key != "event_type")


WRONG_SHAPES: list[Any] = ["x", 3, 2.5, True, [], ["a", 1], {"nested": {"deep": [None]}}]


@pytest.mark.parametrize("event_type", PERSISTED_TYPES)
@pytest.mark.parametrize("value", WRONG_SHAPES, ids=repr)
def test_values_of_the_wrong_shape_never_raise(event_type: str, value: Any) -> None:
    raw = dict.fromkeys(SAMPLES[event_type][0], value) | {"type": event_type}

    event = norm(raw, AgentName.TRANSPORT)

    assert event.title


def test_a_builder_failure_still_gives_an_event(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(event: Any, agent: AgentName) -> Any:
        raise RuntimeError(SECRET)

    from app import events

    monkeypatch.setitem(events._BUILDERS, "session.status_idle", boom)  # pyright: ignore[reportPrivateUsage]

    event = norm(SAMPLES["session.status_idle"][0])

    assert (event.kind, event.title) == (EventKind.STATUS, "Evento session.status_idle")
    assert SECRET not in dumped(event)


def test_unknown_lane_falls_back_to_the_coordinator() -> None:
    event = normalize({"type": "agent.thinking"}, seq=0, agent="planner")  # pyright: ignore[reportArgumentType]

    assert event is not None
    assert event.agent is AgentName.COORDINATOR


# --- timestamps, cost, duration -------------------------------------------------------------


@pytest.mark.parametrize(
    ("processed_at", "expected"),
    [
        ("2026-10-12T10:00:00Z", dt.datetime(2026, 10, 12, 10, tzinfo=dt.UTC)),
        (
            "2026-10-12T12:00:00.5+02:00",
            dt.datetime(2026, 10, 12, 10, 0, 0, 500000, tzinfo=dt.UTC),
        ),
        ("2026-10-12T10:00:00.123456789Z", dt.datetime(2026, 10, 12, 10, 0, 0, 123456, dt.UTC)),
        ("2026-10-12T10:00:00", dt.datetime(2026, 10, 12, 10, tzinfo=dt.UTC)),
    ],
)
def test_ts_comes_from_processed_at(processed_at: str, expected: dt.datetime) -> None:
    event = norm(ev("session.status_running", processed_at=processed_at))

    assert event.ts == expected
    assert event.ts.utcoffset() is not None


@pytest.mark.parametrize("processed_at", [None, "", "yesterday", 17])
def test_ts_falls_back_to_now(processed_at: Any) -> None:
    now = dt.datetime(2026, 10, 12, 9, 30, tzinfo=dt.UTC)
    with time_machine.travel(now, tick=False):
        event = norm(ev("user.interrupt", id="", processed_at=processed_at))

    assert event.ts == now


@pytest.mark.parametrize(("cost", "expected"), [(None, None), (0, 0), (37, 37), (-1, None)])
def test_cost_cents_is_copied(cost: int | None, expected: int | None) -> None:
    assert norm(ev("agent.thinking"), cost_cents=cost).cost_cents == expected


def test_usage_without_list_cost_keeps_the_consumers_cost() -> None:
    event = norm(ev("session.usage", usage={"input_tokens": 10}), cost_cents=33)

    assert event.kind is EventKind.USAGE
    assert event.title == "Consumo aggiornato: costo non ancora disponibile"
    assert event.cost_cents == 33


@pytest.mark.parametrize(
    "list_cost",
    [{"amount": "41", "currency": "EUR"}, {"amount": "x", "currency": "USD"}, {"amount": "-3"}],
)
def test_usage_ignores_a_cost_it_cannot_read(list_cost: dict[str, Any]) -> None:
    event = norm(ev("session.usage", usage={"list_cost": list_cost}), cost_cents=5)

    assert event.cost_cents == 5
    assert event.detail is not None
    assert "list_cost_cents" not in event.detail


def test_usage_detail_figures() -> None:
    event = norm(SAMPLES["session.usage"][0])

    assert event.detail == {
        "event_type": "session.usage",
        "list_cost_cents": 41,
        "budget_cents": 60,
        "input_tokens": 120_000,
        "output_tokens": 9_000,
        "cache_read_input_tokens": 50_000,
        "web_search_requests": 4,
        "active_seconds": 312.5,
    }


def test_tool_result_carries_the_duration() -> None:
    raw = SAMPLES["agent.tool_result"][0]

    event = norm(raw, AgentName.ACTIVITIES, duration_ms=2140)

    assert event.title == "Risultato ricevuto in 2,1 s"
    assert event.detail == {
        "event_type": "agent.tool_result",
        "tool_use_id": "sevt_tool",
        "is_error": False,
        "duration_ms": 2140,
    }


def test_failed_mcp_result_carries_the_duration() -> None:
    raw = ev("agent.mcp_tool_result", mcp_tool_use_id="sevt_mcp", content=text(SECRET))
    raw["is_error"] = True

    event = norm(raw, AgentName.FLIGHTS, duration_ms=850)

    assert event.title == "La fonte ha restituito un errore dopo 850 ms"
    assert event.detail is not None
    assert event.detail["is_error"] is True
    assert event.detail["tool_use_id"] == "sevt_mcp"


@pytest.mark.parametrize("duration", [-5, True, "12"])
def test_bad_durations_are_ignored(duration: Any) -> None:
    event = norm(SAMPLES["agent.tool_result"][0], duration_ms=duration)

    assert event.title == "Risultato ricevuto"
    assert event.detail is not None
    assert "duration_ms" not in event.detail


# --- tool calls: titles and main parameters -------------------------------------------------


def mcp(server: str, name: str, tool_input: dict[str, Any]) -> dict[str, Any]:
    return ev("agent.mcp_tool_use", mcp_server_name=server, name=name, input=tool_input)


def tool(name: str, tool_input: dict[str, Any]) -> dict[str, Any]:
    return ev("agent.tool_use", name=name, input=tool_input)


def test_spec_example_title() -> None:
    event = norm(SAMPLES["agent.mcp_tool_use"][0], AgentName.FLIGHTS)

    assert event.title == "Expedia · voli MXP→LIS · 14–18 nov"
    assert event.detail == {
        "event_type": "agent.mcp_tool_use",
        "tool": "search_flights",
        "server": "expedia",
        "params": {
            "origin": "MXP",
            "destination": "LIS",
            "departure_date": "2026-11-14",
            "return_date": "2026-11-18",
            "adults": 2,
        },
        "tool_use_id": "sevt_agent_mcp_tool_use",
    }


@pytest.mark.parametrize(
    ("raw", "title"),
    [
        (
            mcp(
                "kiwi",
                "search-flight",
                {
                    "flyFrom": "Milano",
                    "flyTo": "Lisbona",
                    "departureDate": "28/11/2026",
                    "returnDate": "03/12/2026",
                    "passengers": {"adults": 2, "children": 1},
                },
            ),
            "Kiwi.com · voli Milano→Lisbona · 28 nov–3 dic",
        ),
        (
            mcp("lastminute", "search_flights", {"from": "MXP", "date": "2026-12-28"}),
            "lastminute.com · voli da MXP · 28 dic",
        ),
        (
            mcp(
                "expedia",
                "search_hotels",
                {"destination": "Lisbona", "check_in": "2026-11-14", "check_out": "2026-11-18"},
            ),
            "Expedia · hotel Lisbona · 14–18 nov",
        ),
        (
            mcp(
                "expedia",
                "get_hotel_pdp_offers",
                {"hotel_id": "123", "checkIn": "2026-12-30", "checkOut": "2027-01-02"},
            ),
            "Expedia · offerte hotel · 30 dic 2026–2 gen 2027",
        ),
        (
            mcp(
                "expedia",
                "search_flights",
                {"legs": [{"origin": {"code": "FCO", "name": "Roma"}, "destination": "OPO"}]},
            ),
            "Expedia · voli FCO→OPO",
        ),
        (mcp("kiwi", "feedback-to-devs", {}), "Kiwi.com · feedback-to-devs"),
        (mcp("acme", "lookup", {"q": "x"}), "acme · lookup"),
        (ev("agent.mcp_tool_use"), "MCP · strumento"),
    ],
)
def test_mcp_titles(raw: dict[str, Any], title: str) -> None:
    assert norm(raw, AgentName.FLIGHTS).title == title


@pytest.mark.parametrize(
    ("raw", "title", "params"),
    [
        (
            tool("web_search", {"query": "musei  Lisbona\nlunedì"}),
            "Ricerca web: musei Lisbona lunedì",
            {"query": "musei Lisbona lunedì"},
        ),
        (
            tool("web_fetch", {"url": "https://www.visitlisboa.com/it/eventi?id=9#x"}),
            "Legge la pagina www.visitlisboa.com",
            {"host": "www.visitlisboa.com"},
        ),
        (
            tool("web_fetch", {"url": "photon.komoot.io/api?q=Lisboa"}),
            "Legge la pagina photon.komoot.io",
            {"host": "photon.komoot.io"},
        ),
        (tool("web_fetch", {}), "Legge una pagina web", None),
        (
            tool("read", {"file_path": "/workspace/shared/request.json"}),
            "Legge shared/request.json",
            {"file_path": "/workspace/shared/request.json"},
        ),
        (
            tool("write", {"file_path": "/workspace/results/flights.json", "content": SECRET}),
            "Scrive results/flights.json",
            {"file_path": "/workspace/results/flights.json"},
        ),
        (
            tool(
                "edit",
                {
                    "file_path": "/workspace/shared/constraints.json",
                    "old_string": SECRET,
                    "new_string": SECRET,
                    "replace_all": False,
                },
            ),
            "Modifica shared/constraints.json",
            {"file_path": "/workspace/shared/constraints.json", "replace_all": False},
        ),
        (
            tool("read", {"file_path": "/tmp/notes.txt"}),
            "Legge /tmp/notes.txt",
            {"file_path": "/tmp/notes.txt"},
        ),
        (
            tool("glob", {"pattern": "results/*.json"}),
            "Cerca file: results/*.json",
            {"pattern": "results/*.json"},
        ),
        (
            tool("grep", {"pattern": "book_by", "path": "/workspace/results"}),
            "Cerca nei file: book_by",
            {"pattern": "book_by", "path": "/workspace/results"},
        ),
        (
            tool("send_to_agent", {"agent": "activities", "message": SECRET}),
            "Messaggio ad attività",
            {"agent": "attività"},
        ),
        (tool("list_agents", {}), "Elenco degli agenti", None),
        (tool("bash", {"restart": True}), "Riavvia la shell", {"restart": True}),
        (
            tool("bash", {"command": "ls -la /workspace/results\necho done"}),
            "Comando: ls -la /workspace/results",
            {"command": "ls -la /workspace/results"},
        ),
        (
            tool("mystery", {"alpha": "b", "content": SECRET, "n": 0, "ok": False}),
            "Strumento mystery",
            {"alpha": "b", "n": 0, "ok": False},
        ),
    ],
)
def test_builtin_tool_titles_and_params(
    raw: dict[str, Any], title: str, params: dict[str, Any] | None
) -> None:
    event = norm(raw, AgentName.ACTIVITIES)

    assert event.kind is EventKind.TOOL
    assert event.title == title
    assert event.detail is not None
    assert event.detail.get("params") == params
    assert SECRET not in dumped(event)


def test_build_link_call_names_the_provider() -> None:
    command = (
        "cd /workspace/skills/booking-links && python3 scripts/build_link.py booking "
        '--dest "Lisbona, Portogallo" --checkin 2026-11-14 --checkout=2026-11-18 --adults 2'
    )

    event = norm(tool("bash", {"command": command}), AgentName.LODGING)

    assert event.title == "Link di prenotazione · Booking.com · Lisbona, Portogallo · 14–18 nov"
    assert event.detail is not None
    assert event.detail["params"] == {
        "command": command,
        "provider": "booking",
        "args": {
            "dest": "Lisbona, Portogallo",
            "checkin": "2026-11-14",
            "checkout": "2026-11-18",
            "adults": "2",
        },
    }


def test_build_link_flights_and_several_providers() -> None:
    command = (
        "python build_link.py google_flights --from MXP --to LIS --depart 2026-11-14 "
        "--return 2026-11-18 && python build_link.py --provider=kiwi --from milano --to lisbona"
    )

    event = norm(tool("bash", {"command": command}), AgentName.FLIGHTS)

    assert event.title == "Link di prenotazione · Google Flights, Kiwi.com · MXP→LIS · 14–18 nov"
    assert event.detail is not None
    assert event.detail["params"]["providers"] == ["google_flights", "kiwi"]


def test_build_link_with_unbalanced_quotes() -> None:
    event = norm(tool("bash", {"command": "build_link.py omio --from 'Roma --to Napoli"}))

    assert event.title.startswith("Link di prenotazione · Omio")


def test_a_tool_waiting_for_confirmation_says_so() -> None:
    raw = mcp("expedia", "search_hotels", {"destination": "Porto"})
    raw["evaluated_permission"] = "ask"

    event = norm(raw, AgentName.LODGING)

    assert event.title == "Expedia · hotel Porto (attende conferma)"
    assert event.detail is not None
    assert event.detail["permission"] == "ask"


def test_a_denied_tool_says_so() -> None:
    raw = tool("bash", {"command": "rm -rf /workspace"})
    raw["evaluated_permission"] = "deny"

    assert norm(raw).title == "Comando: rm -rf /workspace (negato)"


def test_submit_plan_input_never_reaches_detail() -> None:
    raw = ev(
        "agent.custom_tool_use",
        name="submit_plan",
        input={"title": SECRET, "bookings": [{"notes": SECRET}]},
        session_thread_id=None,
    )

    event = norm(raw)

    assert event.kind is EventKind.PLAN
    assert event.detail == {
        "event_type": "agent.custom_tool_use",
        "tool": "submit_plan",
        "tool_use_id": "sevt_agent_custom_tool_use",
    }


def test_other_custom_tool() -> None:
    event = norm(ev("agent.custom_tool_use", name="get_weather", input={"city": "Porto"}))

    assert (event.kind, event.title) == (EventKind.TOOL, "Strumento get_weather")
    assert event.detail is not None
    assert event.detail["params"] == {"city": "Porto"}


def test_cross_posted_tool_use_names_its_thread() -> None:
    raw = tool("web_search", {"query": "Porto"})
    raw["session_thread_id"] = "sthr_activities"

    event = norm(raw, AgentName.ACTIVITIES)

    assert event.detail is not None
    assert event.detail["thread_id"] == "sthr_activities"


# --- no tool-result or page leakage ---------------------------------------------------------


@pytest.mark.parametrize(
    "raw",
    [
        ev("agent.tool_result", tool_use_id="t", content=text(SECRET), is_error=True),
        ev(
            "agent.mcp_tool_result",
            mcp_tool_use_id="t",
            content=[{"type": "text", "text": json.dumps({"itineraries": [SECRET]})}],
        ),
        ev("user.custom_tool_result", custom_tool_use_id="t", content=text(SECRET)),
        ev("user.tool_result", tool_use_id="t", content=text(SECRET), is_error=False),
        tool("web_fetch", {"url": f"https://example.org/{SECRET}?q={SECRET}"}),
        tool("write", {"file_path": "/workspace/results/x.json", "content": SECRET}),
        tool("bash", {"command": f"cat > /workspace/results/x.json <<'EOF'\n{SECRET}\nEOF"}),
        mcp("expedia", "search_flights", {"origin": "MXP", "content": SECRET, "text": SECRET}),
        ev("span.outcome_evaluation_end", result="satisfied", explanation=SECRET),
    ],
)
def test_tool_results_and_contents_never_leak(raw: dict[str, Any]) -> None:
    event = norm(raw, AgentName.FLIGHTS)

    assert SECRET not in dumped(event)


# --- messages and Italian labels ------------------------------------------------------------


def test_italian_agent_labels() -> None:
    assert AGENT_LABELS == {
        AgentName.COORDINATOR: "coordinatore",
        AgentName.FLIGHTS: "voli",
        AgentName.LODGING: "alloggio",
        AgentName.ACTIVITIES: "attività",
        AgentName.TRANSPORT: "spostamenti",
    }
    assert agent_label("Transport") == "spostamenti"
    assert agent_label("anthropic.advisor") == "consulente"
    assert agent_label("scout") == "scout"
    assert agent_label(None) == "agente"


@pytest.mark.parametrize(
    ("agent_name", "title"),
    [
        ("coordinator", "Incarico a coordinatore"),
        ("flights", "Incarico a voli"),
        ("lodging", "Incarico ad alloggio"),
        ("activities", "Incarico ad attività"),
        ("transport", "Incarico a spostamenti"),
    ],
)
def test_thread_created_titles(agent_name: str, title: str) -> None:
    raw = ev("session.thread_created", session_thread_id="sthr_x", agent_name=agent_name)

    event = norm(raw)

    assert event.title == title
    assert event.detail == {
        "event_type": "session.thread_created",
        "lane_state": "working",
        "thread_id": "sthr_x",
        "agent_name": agent_name,
    }


def test_thread_created_without_a_name_uses_the_lane() -> None:
    assert norm({"type": "session.thread_created"}, AgentName.TRANSPORT).title == (
        "Incarico a spostamenti"
    )
    assert norm({"type": "session.thread_created"}).title == "Incarico a un agente"


def test_coordinator_brief_to_a_subagent() -> None:
    raw = SAMPLES["agent.thread_message_sent"][0]

    event = norm(raw, AgentName.FLIGHTS)

    assert event.detail == {
        "event_type": "agent.thread_message_sent",
        "sender": "coordinatore",
        "recipient": "voli",
        "text": "Find flights MXP to LIS, 14-18 Nov, 2 adults.\nWrite results.",
        "thread_id": "sthr_flights",
    }


@pytest.mark.parametrize(
    ("raw", "lane", "title"),
    [
        (
            ev(
                "agent.thread_message_received",
                from_session_thread_id="sthr_t",
                from_agent_name="transport",
                content=text("## Fatto\n\nTransfer in results/transport.json"),
            ),
            AgentName.TRANSPORT,
            "spostamenti → coordinatore: Fatto",
        ),
        (
            ev(
                "agent.thread_message_received",
                from_session_thread_id="sthr_a",
                content=text("Report"),
            ),
            AgentName.ACTIVITIES,
            "attività → coordinatore: Report",
        ),
        (
            ev(
                "agent.thread_message_sent",
                to_session_thread_id="sthr_c",
                to_agent_name="coordinator",
                content=text("Question: budget?"),
            ),
            AgentName.LODGING,
            "alloggio → coordinatore: Question: budget?",
        ),
        (
            ev(
                "agent.thread_message_received",
                from_session_thread_id="sthr_adv",
                from_agent_name="anthropic.advisor",
                content=text("Advice"),
            ),
            AgentName.COORDINATOR,
            "consulente → coordinatore: Advice",
        ),
        (
            ev("agent.thread_message_sent", to_session_thread_id="sthr_x", content=[]),
            AgentName.COORDINATOR,
            "coordinatore → subagente: (nessun testo)",
        ),
        (
            ev("agent.message", content=[{"type": "redacted"}, *text("Piano pronto.")]),
            AgentName.COORDINATOR,
            "coordinatore → utente: Piano pronto.",
        ),
        (
            ev("user.message", content=text("Continue: the budget was raised.")),
            AgentName.COORDINATOR,
            "utente → coordinatore: nuovo messaggio",
        ),
    ],
)
def test_message_titles(raw: dict[str, Any], lane: AgentName, title: str) -> None:
    event = norm(raw, lane)

    assert event.kind is EventKind.MESSAGE
    assert event.title == title


def test_message_text_is_capped() -> None:
    long_text = "Riga uno\n" + "x" * (MAX_TEXT_CHARS * 2)

    event = norm(ev("agent.message", content=text(long_text)), AgentName.FLIGHTS)

    assert event.detail is not None
    assert len(event.detail["text"]) == MAX_TEXT_CHARS
    assert event.detail["text"].endswith("…")
    assert event.title == "voli → coordinatore: Riga uno"


# --- status and errors in plain Italian -----------------------------------------------------


@pytest.mark.parametrize(
    ("stop_reason", "stop_details", "title", "lane_state"),
    [
        ({"type": "end_turn"}, None, "Turno concluso", "done"),
        (
            {"type": "requires_action", "event_ids": ["sevt_1", "sevt_2"]},
            None,
            "In attesa di una risposta",
            "waiting",
        ),
        ({"type": "budget_reached"}, None, "Fermo: budget della sessione esaurito", "waiting"),
        (
            {"type": "retries_exhausted"},
            None,
            "Fermo: troppi errori, tentativi esauriti",
            "error",
        ),
        (
            {"type": "refusal"},
            {"type": "refusal", "category": "cyber", "explanation": "Policy."},
            "Fermo: il modello ha rifiutato di proseguire",
            "error",
        ),
        ({"type": "nap_time"}, None, "In pausa: motivo non riconosciuto (nap_time)", "waiting"),
        (None, None, "In pausa", "waiting"),
        ("end_turn", None, "Turno concluso", "done"),
    ],
)
def test_idle_stop_reasons(
    stop_reason: Any, stop_details: Any, title: str, lane_state: str
) -> None:
    raw = ev("session.status_idle", stop_reason=stop_reason, stop_details=stop_details)

    event = norm(raw)

    assert (event.kind, event.title) == (EventKind.STATUS, title)
    assert event.detail is not None
    assert event.detail["lane_state"] == lane_state


def test_idle_detail() -> None:
    raw = ev(
        "session.status_idle",
        stop_reason={"type": "refusal"},
        stop_details={"type": "refusal", "category": "general_harms", "explanation": "No.\nOk"},
    )
    assert SDK_EVENT.validate_python(raw).type == "session.status_idle"

    assert norm(raw).detail == {
        "event_type": "session.status_idle",
        "stop_reason": "refusal",
        "lane_state": "error",
        "refusal_category": "general_harms",
        "explanation": "No. Ok",
    }
    requires_action = ev(
        "session.status_idle", stop_reason={"type": "requires_action", "event_ids": ["sevt_9"]}
    )
    detail = norm(requires_action).detail
    assert detail is not None
    assert detail["event_ids"] == ["sevt_9"]


@pytest.mark.parametrize(
    ("error", "title", "severity"),
    [
        (
            {
                "type": "mcp_connection_failed_error",
                "mcp_server_name": "expedia",
                "message": "refused",
                "retry_status": {"type": "retrying"},
            },
            "Fonte Expedia non raggiungibile: nuovo tentativo in corso",
            "warning",
        ),
        (
            {
                "type": "mcp_connection_failed_error",
                "mcp_server_name": "lastminute",
                "message": "refused",
                "retry_status": {"type": "terminal"},
            },
            "Fonte lastminute.com non raggiungibile: il piano prosegue con le altre fonti",
            "warning",
        ),
        (
            {
                "type": "mcp_authentication_failed_error",
                "mcp_server_name": "expedia",
                "message": "401",
                "retry_status": {"type": "exhausted"},
            },
            "Fonte Expedia accesso rifiutato: il piano prosegue con le altre fonti",
            "warning",
        ),
        (
            {
                "type": "model_overloaded_error",
                "message": "overloaded",
                "retry_status": {"type": "retrying"},
            },
            "Modello sovraccarico: nuovo tentativo in corso",
            "warning",
        ),
        (
            {
                "type": "model_request_failed_error",
                "message": "failed",
                "retry_status": {"type": "terminal"},
            },
            "Richiesta al modello non riuscita: la sessione si ferma",
            "error",
        ),
        (
            {"type": "billing_error", "message": "x", "retry_status": {"type": "exhausted"}},
            "Problema di fatturazione dell'account: tentativi esauriti",
            "error",
        ),
        (
            {
                "type": "repository_clone_error",
                "message": "x",
                "retry_status": {"type": "terminal"},
            },
            "Errore del repository: la sessione si ferma",
            "error",
        ),
    ],
)
def test_session_errors(error: dict[str, Any], title: str, severity: str) -> None:
    raw = ev("session.error", error=error)
    assert SDK_EVENT.validate_python(raw).type == "session.error"

    event = norm(raw, AgentName.FLIGHTS)

    assert (event.kind, event.title) == (EventKind.ERROR, title)
    assert event.detail is not None
    assert event.detail["severity"] == severity
    assert event.detail["error_type"] == error["type"]
    assert "piano non" not in event.title.lower()


def test_mcp_failure_is_a_source_warning_not_a_lane_error() -> None:
    event = norm(SAMPLES["session.error"][0], AgentName.FLIGHTS)

    assert event.detail == {
        "event_type": "session.error",
        "error_type": "mcp_connection_failed_error",
        "retry_status": "exhausted",
        "message": "Connection refused",
        "server": "kiwi",
        "severity": "warning",
    }


@pytest.mark.parametrize(
    ("error", "title"),
    [
        (
            {"type": "brand_new_error", "retry_status": {"type": "retrying"}},
            ("Errore della sessione (brand_new_error): nuovo tentativo in corso"),
        ),
        ({}, "Errore della sessione"),
        ("overloaded", "Errore della sessione (overloaded)"),
    ],
)
def test_unknown_session_errors(error: Any, title: str) -> None:
    assert norm(ev("session.error", error=error)).title == title


@pytest.mark.parametrize(
    ("budget", "title", "budget_cents"),
    [
        (None, "Budget della sessione rimosso", None),
        ({"type": "limit"}, "Budget della sessione aggiornato", None),
    ],
)
def test_session_updated_budget(budget: Any, title: str, budget_cents: int | None) -> None:
    event = norm(ev("session.updated", budget=budget))

    assert event.title == title
    assert event.detail is not None
    assert event.detail.get("budget_cents") == budget_cents
    assert event.detail["changed"] == ["budget"]


def test_session_updated_without_budget() -> None:
    event = norm(ev("session.updated", title="plan 1", metadata={"plan_id": "1"}))

    assert event.title == "Sessione aggiornata"
    assert event.detail is not None
    assert event.detail["changed"] == ["metadata", "title"]


def test_tool_confirmation_deny() -> None:
    raw = ev("user.tool_confirmation", tool_use_id="t", result="deny", deny_message=SECRET)

    event = norm(raw)

    assert event.title == "Permesso negato"
    assert SECRET not in dumped(event)


# --- caps and storability -------------------------------------------------------------------


def test_titles_are_capped() -> None:
    query = "parola " * 100

    event = norm(tool("web_search", {"query": query}))

    assert len(event.title) <= MAX_TITLE_LENGTH
    assert event.title.endswith("…")
    assert "\n" not in event.title


def test_long_message_title_is_capped_to_one_line() -> None:
    first_line = "lungo " * 80

    event = norm(ev("agent.message", content=text(first_line + "\nseconda")), AgentName.FLIGHTS)

    assert len(event.title) == MAX_TITLE_LENGTH
    assert event.title.startswith("voli → coordinatore: lungo")
    assert event.title.endswith("…")


def test_params_are_bounded() -> None:
    huge = {
        f"key{i}": {f"k{j}": ["v" * 500] * 20 for j in range(20)} | {"code": "x" * 500}
        for i in range(40)
    }

    event = norm(mcp("expedia", "search_flights", huge), AgentName.FLIGHTS)

    assert event.detail is not None
    assert len(json.dumps(event.detail, ensure_ascii=False)) <= MAX_DETAIL_CHARS
    params = event.detail["params"]
    assert len(params) <= 12
    assert all(len(value) <= 200 for value in json.dumps(params).split('"') if value.strip())


def test_detail_size_guard_drops_nested_params() -> None:
    wide = {f"k{i}": [{"a": "v" * 100, "b": "w" * 100}] * 8 for i in range(12)}

    event = norm(mcp("expedia", "search_flights", wide))

    assert event.detail is not None
    assert len(json.dumps(event.detail, ensure_ascii=False)) <= MAX_DETAIL_CHARS
    assert event.detail.get("params_truncated") is True


def test_nul_and_lone_surrogates_are_removed() -> None:
    raw = tool("web_search", {"query": "Lis\x00bona \ud800tram"})
    raw["id"] = "sevt\x00_1"

    event = norm(raw)

    assert event.title == "Ricerca web: Lisbona ?tram"
    assert "\x00" not in dumped(event)
    assert event.detail is not None
    assert event.detail["tool_use_id"] == "sevt_1"
    dumped(event).encode("utf-8")


def test_a_title_of_only_nul_still_validates() -> None:
    event = norm(ev("agent.message", content=text("\x00\x00")), AgentName.FLIGHTS)

    assert event.title == "voli → coordinatore: (nessun testo)"


def test_non_finite_numbers_are_dropped() -> None:
    raw = mcp("expedia", "search_hotels", {"destination": "Porto", "max_price": float("nan")})

    event = norm(raw)

    assert event.detail is not None
    assert event.detail["params"] == {"destination": "Porto"}
    json.dumps(event.detail, allow_nan=False)


def test_the_raw_event_is_not_modified() -> None:
    raw = SAMPLES["agent.mcp_tool_use"][0]
    before = copy.deepcopy(raw)

    norm(raw, AgentName.FLIGHTS)

    assert raw == before


# --- formatting helpers ---------------------------------------------------------------------


@pytest.mark.parametrize(
    ("ms", "text_"),
    [(0, "0 ms"), (850, "850 ms"), (2140, "2,1 s"), (59_940, "59,9 s"), (65_000, "1 min 5 s")],
)
def test_format_duration(ms: int, text_: str) -> None:
    assert format_duration(ms) == text_


def test_format_usd_and_dates() -> None:
    assert format_usd(41) == "0,41 $"
    assert format_usd(400) == "4,00 $"
    d = dt.date
    assert format_date_range(d(2026, 11, 14), d(2026, 11, 18)) == "14–18 nov"
    assert format_date_range(d(2026, 11, 28), d(2026, 12, 3)) == "28 nov–3 dic"
    assert format_date_range(None, d(2026, 8, 1)) == "1 ago"
    assert format_date_range(None, None) is None


# --- scenario scripts (tests/fixtures/ma), when present --------------------------------------


def fixture_events() -> list[Any]:
    cases: list[Any] = []
    for path in sorted(FIXTURES_DIR.glob("*.jsonl")) if FIXTURES_DIR.is_dir() else []:
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            step = json.loads(line)
            if step.get("op") == "emit" and isinstance(step.get("event"), dict):
                cases.append(pytest.param(step["event"], id=f"{path.stem}:{number}"))
    return cases


FIXTURE_EVENTS = fixture_events()


@pytest.mark.skipif(not FIXTURE_EVENTS, reason="no tests/fixtures/ma/*.jsonl scenario yet")
@pytest.mark.parametrize("raw", FIXTURE_EVENTS or [None])
def test_scenario_events_normalize(raw: dict[str, Any]) -> None:
    event_type = raw.get("type")

    event = normalize(raw, seq=0, agent=AgentName.FLIGHTS, cost_cents=1)

    if event_type in NOISE_EVENT_TYPES:
        assert event is None
        return
    assert event is not None
    assert event.detail is not None
    assert event.detail["event_type"] == event_type
    if event_type in KNOWN_EVENT_TYPES:
        assert not event.title.startswith("Evento non riconosciuto")
    results: list[str] = []
    content = raw.get("content")
    if isinstance(content, list):
        for block in typing.cast(list[Any], content):
            if isinstance(block, dict) and isinstance(block.get("text"), str):
                results.append(typing.cast(str, block["text"]))
    if event_type in ("agent.tool_result", "agent.mcp_tool_result", "user.custom_tool_result"):
        for result in results:
            if len(result) > 20:
                assert result not in dumped(event)
