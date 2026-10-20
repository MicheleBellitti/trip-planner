"""UI events: the normalized form of what happens in a Managed Agents session.

The consumer turns every Managed Agents event into a `UIEvent` with a progressive `seq`, stores
it in the `events` table and publishes it to the browsers watching the plan, which receive it
over SSE (`id: <seq>`) and validate it with Zod against schema/ui_event.json.

What reaches the browser is a summary, never raw content: for a tool call, the tool name, its
main parameters and the duration; never the full text of a tool result or of a web page.

A `UIEvent` is always storable: U+0000, which Postgres `text` and `jsonb` reject, is removed
from `title` and, recursively, from `detail` (keys and values) when the event is built. Event
details echo third-party text (tool parameters, agent messages), so they are cleaned rather
than rejected: a rejected event would be a lost event.

`normalize()` (bottom of the module) builds the `UIEvent` of one raw Managed Agents event.
"""

from __future__ import annotations

import datetime as dt
import json
import math
import re
import shlex
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from enum import StrEnum
from typing import Any, cast
from urllib.parse import urlsplit

import structlog
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, NonNegativeInt, field_validator

MAX_TITLE_LENGTH = 200
SINGLE_LINE_PATTERN = r"^[^\r\n]*$"
NUL = "\x00"


def strip_nul(value: Any) -> Any:
    """`value` without U+0000: in a string, and recursively in the keys and values of dicts and
    the items of lists and tuples (returned as lists). Other values are returned unchanged."""
    if isinstance(value, str):
        return value.replace(NUL, "")
    if isinstance(value, dict):
        items = cast(dict[Any, Any], value).items()
        return {strip_nul(key): strip_nul(item) for key, item in items}
    if isinstance(value, list | tuple):
        return [strip_nul(item) for item in cast(list[Any], value)]
    return value


class AgentName(StrEnum):
    """The agents of a plan's session: the coordinator and its four subagents."""

    COORDINATOR = "coordinator"
    FLIGHTS = "flights"
    LODGING = "lodging"
    ACTIVITIES = "activities"
    TRANSPORT = "transport"


class EventKind(StrEnum):
    """What a UI event is about; the timeline draws each kind differently."""

    STATUS = "status"  # an agent or the plan changed state: started, working, idle, finished
    TOOL = "tool"  # a tool call: name, main parameters, duration (never the full result)
    MESSAGE = "message"  # a message between agents, e.g. the coordinator's brief to a subagent
    USAGE = "usage"  # token usage and cost update
    ERROR = "error"  # an agent or a source failed
    PLAN = "plan"  # submit_plan: plan accepted or rejected (with the validation errors)
    CHOICE = "choice"  # ask_traveller: a question put to the traveller, then its answer


class UIEvent(BaseModel):
    """One event of a plan's timeline, as stored in `events` and sent over SSE."""

    # Serialized events always carry every key (null when unset): say so in the schema.
    model_config = ConfigDict(extra="forbid", json_schema_serialization_defaults_required=True)

    seq: NonNegativeInt = Field(
        description=(
            "Progressive number of the event within its plan; the SSE id, used with "
            "Last-Event-ID to resume."
        ),
    )
    ts: AwareDatetime = Field(description="When the event happened, ISO 8601 with UTC offset.")
    agent: AgentName = Field(description="The agent whose lane shows the event.")
    kind: EventKind = Field(description="What the event is about.")
    title: str = Field(
        min_length=1,
        max_length=MAX_TITLE_LENGTH,
        pattern=SINGLE_LINE_PATTERN,
        description=(
            "One line for the timeline, at most 200 characters, e.g. "
            "'Expedia · voli MXP→LIS · 14–18 nov'."
        ),
    )
    detail: dict[str, Any] | None = Field(
        default=None,
        description=(
            "Optional structured detail: tool name, main parameters and duration, message "
            "sender, recipient and text, usage figures. Never the full text of a tool result."
        ),
    )
    cost_cents: NonNegativeInt | None = Field(
        default=None,
        description="Cumulative session cost in cents at this event, when known.",
    )

    @field_validator("title", "detail", mode="before")
    @classmethod
    def _storable(cls, value: Any) -> Any:
        return strip_nul(value)


def one_line(text: str, limit: int = MAX_TITLE_LENGTH) -> str:
    """Collapse all whitespace (newlines included) and cut to `limit` characters with "…",
    so any text can become a `UIEvent.title`."""
    collapsed = " ".join(text.split())
    if len(collapsed) <= limit:
        return collapsed
    return collapsed[: limit - 1].rstrip() + "…"


# ============================================================================================
# Managed Agents -> UIEvent normalization
#
# Contract: docs/backend-interfaces.md §7 ("events.py"); event shapes: docs/managed-agents-
# notes.md §2g and the SDK types (anthropic 1.13.0, types/beta/sessions). Spec: "Backend
# FastAPI" (the UIEvent paragraph) and "La timeline in diretta".
#
# `normalize()` is pure and stateless: the consumer decides the lane (`consumer.lane_for`), the
# cumulative cost and, for tool results, the duration (it pairs `*_tool_use` with
# `*_tool_result`). Titles are Italian, one line, at most `MAX_TITLE_LENGTH` characters.
#
# `detail` vocabulary (every key optional except `event_type`; the web app reads these):
#   event_type     the Managed Agents type (str, or null when the event had none)
#   tool, server   tool name; MCP server name           params   main tool parameters (bounded)
#   tool_use_id    pairs a tool use with its result     duration_ms, is_error, permission
#   sender, recipient, text                             messages (Italian labels, capped text)
#   lane_state     working | waiting | done | error     status changes of an agent's lane
#   stop_reason, event_ids, refusal_category, explanation       idle events
#   error_type, retry_status, severity (warning | error), message   errors
#   thread_id, agent_name                               thread lifecycle, cross-posted events
#   list_cost_cents, budget_cents, *_tokens, web_search_requests, active_seconds   usage
# Never in `detail`: tool results (`content` of `*_tool_result` and `user.custom_tool_result`),
# fetched pages, file contents written by `write`/`edit`, the `submit_plan` input.
# ============================================================================================

_log = structlog.get_logger(__name__)

AGENT_LABELS: dict[AgentName, str] = {
    AgentName.COORDINATOR: "coordinatore",
    AgentName.FLIGHTS: "voli",
    AgentName.LODGING: "alloggio",
    AgentName.ACTIVITIES: "attività",
    AgentName.TRANSPORT: "spostamenti",
}
"""Italian lane labels, as the timeline shows them ("coordinatore → voli: ...")."""

ACTION_EVENT_TYPES: frozenset[str] = frozenset(
    {
        "agent.custom_tool_use",
        "session.status_idle",
        "session.status_terminated",
        "session.error",
        "session.deleted",
        "session.thread_created",
    }
)
"""A copy of `consumer.ACTION_EVENT_TYPES` (events.py sits below consumer.py in the import
layers, so it can't import it; tests/test_events.py checks the two are equal). `normalize`
never returns None for these: the consumer stores them with the plan change they cause."""

NOISE_EVENT_TYPES: frozenset[str] = frozenset({"event_start", "event_delta"})
"""Stream-only previews (`event_deltas`), never persisted by the API: `normalize` returns None.
Every other type, known or not, becomes a UIEvent."""

LaneState = str
"""`working`, `waiting`, `done` or `error`: the spec's lane states (al lavoro, in attesa,
finito, errore)."""

MAX_TEXT_CHARS = 4000
"""Message text kept in `detail.text` (agent and inter-agent messages, the brief)."""
MAX_PARAM_CHARS = 200
"""A top-level string parameter in `detail.params`."""
MAX_NESTED_CHARS = 100
"""A string inside a nested parameter (dict or list)."""
MAX_PARAMS = 12
"""Top-level keys kept in `detail.params`."""
MAX_NESTED_ITEMS = 8
"""Items kept in a nested dict or list of `detail.params`."""
MAX_KEY_CHARS = 64
MAX_LABEL_CHARS = 40
"""An agent, server or provider name shown in a title."""
MAX_DETAIL_CHARS = 12_000
"""Upper bound on `json.dumps(detail)`: past it, nested parameters are dropped, then text."""
MAX_COMMAND_PARSE_CHARS = 4000
"""How much of a bash command is tokenized to find `build_link.py` calls."""

WORKSPACE_PREFIX = "/workspace/"
SUBMIT_PLAN_TOOL = "submit_plan"
"""The coordinator's custom tool (`consumer.SUBMIT_PLAN_TOOL`)."""
BUILD_LINK_SCRIPT = "build_link.py"
"""The booking-links skill's script: `build_link.py <provider> --param value ...`."""

_MONTHS = ("gen", "feb", "mar", "apr", "mag", "giu", "lug", "ago", "set", "ott", "nov", "dic")

_SERVER_LABELS: dict[str, str] = {
    "expedia": "Expedia",
    "kiwi": "Kiwi.com",
    "lastminute": "lastminute.com",
}
"""MCP server names (the agents' `mcp_servers[].name`) -> display names."""

_PROVIDER_LABELS: dict[str, str] = {
    "booking": "Booking.com",
    "airbnb": "Airbnb",
    "google_flights": "Google Flights",
    "expedia": "Expedia",
    "expedia_hotels": "Expedia hotel",
    "expedia_flights": "Expedia voli",
    "kiwi": "Kiwi.com",
    "lastminute": "lastminute.com",
    "trenitalia": "Trenitalia",
    "italo": "Italo",
    "omio": "Omio",
}
"""`build_link.py` providers (docs/research/integrations.md §1.11) -> display names."""

_IDLE: dict[str, tuple[str, LaneState]] = {
    "end_turn": ("Turno concluso", "done"),
    "requires_action": ("In attesa di una risposta", "waiting"),
    "budget_reached": ("Fermo: budget della sessione raggiunto", "waiting"),
    "retries_exhausted": ("Fermo: troppi errori, tentativi esauriti", "error"),
    "refusal": ("Fermo: il modello ha rifiutato di proseguire", "error"),
}
"""`stop_reason.type` of an idle event -> (title, lane state)."""

_ERROR_TITLES: dict[str, str] = {
    "unknown_error": "Errore imprevisto della sessione",
    "model_overloaded_error": "Modello sovraccarico",
    "model_rate_limited_error": "Troppe richieste al modello",
    "model_request_failed_error": "Richiesta al modello non riuscita",
    "billing_error": "Problema di fatturazione dell'account",
    "credential_host_unreachable_error": "Servizio delle credenziali non raggiungibile",
}
_RETRY_SUFFIXES: dict[str, str] = {
    "retrying": "nuovo tentativo in corso",
    "exhausted": "tentativi esauriti",
    "terminal": "la sessione si ferma",
}
_MCP_ERRORS: dict[str, str] = {
    "mcp_connection_failed_error": "non raggiungibile",
    "mcp_authentication_failed_error": "accesso rifiutato",
}

_OUTCOME_RESULTS: dict[str, str] = {
    "satisfied": "obiettivo raggiunto",
    "needs_revision": "da rivedere",
    "max_iterations_reached": "giri esauriti",
    "failed": "non riuscita",
    "interrupted": "interrotta",
}

_FIXED: dict[str, tuple[EventKind, str, LaneState | None]] = {
    "agent.thinking": (EventKind.STATUS, "Ragionamento in corso", None),
    "agent.thread_context_compacted": (
        EventKind.STATUS,
        "Memoria della conversazione compattata",
        None,
    ),
    "session.status_running": (EventKind.STATUS, "Al lavoro", "working"),
    "session.status_rescheduled": (
        EventKind.STATUS,
        "Errore temporaneo: la piattaforma riprova",
        "working",
    ),
    "session.status_terminated": (EventKind.STATUS, "Sessione chiusa", "done"),
    "session.deleted": (EventKind.STATUS, "Sessione eliminata", "done"),
    "session.thread_status_running": (EventKind.STATUS, "Al lavoro", "working"),
    "session.thread_status_rescheduled": (
        EventKind.STATUS,
        "Errore temporaneo: la piattaforma riprova",
        "working",
    ),
    "session.thread_status_terminated": (EventKind.STATUS, "Lavoro chiuso", "done"),
    "span.model_request_start": (EventKind.STATUS, "Richiesta al modello", None),
    "user.interrupt": (EventKind.STATUS, "Interruzione richiesta", None),
    "user.define_outcome": (EventKind.STATUS, "Obiettivo definito", None),
    "system.message": (EventKind.STATUS, "Messaggio di sistema", None),
    "workflow_run.created": (EventKind.STATUS, "Workflow avviato", None),
    "workflow_run.status_running": (EventKind.STATUS, "Workflow in corso", None),
    "workflow_run.status_idle": (EventKind.STATUS, "Workflow in pausa", None),
    "workflow_run.status_ended": (EventKind.STATUS, "Workflow concluso", None),
    "workflow_run.phase_started": (EventKind.STATUS, "Fase del workflow avviata", None),
    "workflow_run.phase_ended": (EventKind.STATUS, "Fase del workflow conclusa", None),
}
"""Types whose title doesn't depend on their payload."""


def _words(text: str) -> tuple[str, ...]:
    return tuple(text.split())


# Keys of tool inputs (normalized: lower case, letters and digits only). Route and date keys
# cover the public descriptions of the travel MCPs and build_link.py's parameters; the exact
# MCP input names are a day-1 probe (notes D3), so the lookup is by synonym, best effort.
_ORIGIN_KEYS = _words(
    "from origin flyfrom source fromiata originiata fromairport originairport departureairport "
    "fromcity origincity departurecity fromstation originstation departurestation fromcode "
    "fromslugen fromslugit fromslug originlocationcode departure"
)
_DESTINATION_KEYS = _words(
    "to destination flyto dest toiata destinationiata toairport destinationairport "
    "arrivalairport tocity destinationcity arrivalcity tostation destinationstation "
    "arrivalstation tocode toslugen toslugit toslug destinationlocationcode arrival"
)
_PLACE_KEYS = _words("location city place near area region where ss address")
_START_KEYS = _words(
    "departuredate departdate outbounddate startdate checkin checkindate datefrom fromdate "
    "date depart outbound start in departure"
)
_END_KEYS = _words(
    "returndate inbounddate enddate checkout checkoutdate dateto todate return inbound end out"
)
_PLACE_VALUE_KEYS = _words("code iata iatacode name city label")
_CONTENT_KEYS = frozenset(
    _words(
        "content text body html data oldstring newstring filetext message messages prompt result "
        "results output"
    )
)
"""Input keys never copied into `detail.params`: they carry content, not parameters."""
_SHELL_SEPARATORS = frozenset({"&&", "||", ";", "|", "&"})

_DATE_PATTERNS: tuple[tuple[re.Pattern[str], tuple[int, int, int]], ...] = (
    (re.compile(r"^(\d{4})-(\d{2})-(\d{2})(?:[T ].*)?$"), (1, 2, 3)),
    (re.compile(r"^(\d{4})/(\d{2})/(\d{2})$"), (1, 2, 3)),
    (re.compile(r"^(\d{4})(\d{2})(\d{2})$"), (1, 2, 3)),
    (re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{4})$"), (3, 2, 1)),
    (re.compile(r"^(\d{1,2})-(\d{1,2})-(\d{4})$"), (3, 2, 1)),
)
"""ISO dates (and datetimes), YYYY/MM/DD, YYYYMMDD, and the Italian/Kiwi DD/MM/YYYY."""


@dataclass(slots=True)
class _Built:
    """What a per-type builder produces; `normalize` adds the common keys."""

    kind: EventKind
    title: str
    detail: dict[str, Any] = field(default_factory=dict[str, Any])
    cost_cents: int | None = None
    """Set only by `session.usage`, whose own `list_cost` is the freshest figure."""


Builder = Callable[[Mapping[str, Any], AgentName], _Built]


def normalize(
    ma_event: Mapping[str, Any],
    *,
    seq: int,
    agent: AgentName,
    cost_cents: int | None = None,
    duration_ms: int | None = None,
) -> UIEvent | None:
    """The `UIEvent` of one raw Managed Agents event (`ma_client.RawEvent`), or None for noise.

    - `agent` is the lane, decided by `consumer.lane_for` (an unknown value falls back to the
      coordinator). `seq` is allocated by `EventSink.emit`.
    - `ts` is the event's `processed_at` (a naive one is read as UTC); the current time only
      when it is missing or unreadable (a queued echo).
    - `cost_cents` (cumulative US cents, from the consumer's state) is copied to the event; a
      `session.usage` event uses its own `usage.list_cost` instead when it carries one in USD.
      A negative value is dropped.
    - `duration_ms` (the consumer pairs a tool use with its result) goes to
      `detail.duration_ms` and into the title of tool results.
    - Titles are Italian and one line (`one_line`, `MAX_TITLE_LENGTH`). `detail` carries the
      tool name, its main parameters and the duration, or a message's sender, recipient and
      text: never tool results, fetched pages, written file contents or the `submit_plan`
      input. Sizes are bounded (`MAX_*`).
    - None only for `NOISE_EVENT_TYPES`, so never for `ACTION_EVENT_TYPES`. An unknown type, a
      missing type, missing optional keys, nulls and values of the wrong shape all give an
      event, never an exception: a payload that still breaks a builder is logged (type only)
      and becomes a generic `status` event.
    Pure, apart from reading the clock when `processed_at` is missing.
    """
    event: Mapping[str, Any] = (
        cast(Mapping[str, Any], ma_event) if isinstance(ma_event, Mapping) else {}
    )
    event_type = _text(event.get("type"), 100)
    if event_type in NOISE_EVENT_TYPES:
        return None
    lane = _lane(agent)

    builder = _BUILDERS.get(event_type) if event_type is not None else None
    try:
        built = builder(event, lane) if builder is not None else _generic(event_type, known=False)
    except Exception as exc:  # a payload no builder foresaw: never lose the event
        _log.warning("ui_event_normalize_failed", event_type=event_type, error=type(exc).__name__)
        built = _generic(event_type, known=True)

    detail: dict[str, Any] = {"event_type": event_type}
    detail.update(built.detail)
    detail.update(_thread_keys(event, event_type))
    duration = _non_negative_int(duration_ms)
    if duration is not None:
        detail["duration_ms"] = duration
        if event_type in _RESULT_TYPES:
            word = "dopo" if detail.get("is_error") else "in"
            built.title = f"{built.title} {word} {format_duration(duration)}"
    detail = {
        key: value for key, value in detail.items() if value is not None or key == "event_type"
    }

    cost = built.cost_cents if built.cost_cents is not None else _non_negative_int(cost_cents)
    return UIEvent(
        seq=seq,
        ts=_event_ts(event),
        agent=lane,
        kind=built.kind,
        title=_title(built.title),
        detail=_bounded(detail),
        cost_cents=cost,
    )


def agent_label(name: str | None) -> str:
    """The Italian label of an agent name as the API reports it (`agent_name`,
    `to_agent_name`...): the five lanes by name, the platform advisor as "consulente", any
    other name as written (capped); "agente" when missing."""
    known = _agent_from_name(name)
    if known is not None:
        return AGENT_LABELS[known]
    text = _text(name, MAX_LABEL_CHARS)
    if text is None:
        return "agente"
    if text.lower() == "anthropic.advisor":
        return "consulente"
    return text


def format_duration(ms: int) -> str:
    """`850 ms`, `2,1 s`, `1 min 5 s` (Italian decimal comma)."""
    if ms < 1000:
        return f"{ms} ms"
    if ms < 59_950:
        return f"{ms / 1000:.1f} s".replace(".", ",")
    minutes, seconds = divmod(round(ms / 1000), 60)
    return f"{minutes} min {seconds} s" if seconds else f"{minutes} min"


def format_usd(cents: int) -> str:
    """US cents as the UI writes dollars: `0,41 $`, `4,00 $`."""
    return f"{cents // 100},{cents % 100:02d} $"


def format_date_range(start: dt.date | None, end: dt.date | None) -> str | None:
    """`14–18 nov`, `28 nov–3 dic`, `28 dic 2026–3 gen 2027`, `14 nov`; None without dates."""
    if start is None and end is None:
        return None
    if start is None or end is None:
        only = cast(dt.date, start or end)
        return f"{only.day} {_MONTHS[only.month - 1]}"
    if start.year != end.year:
        return (
            f"{start.day} {_MONTHS[start.month - 1]} {start.year}–"
            f"{end.day} {_MONTHS[end.month - 1]} {end.year}"
        )
    if start.month != end.month:
        return f"{start.day} {_MONTHS[start.month - 1]}–{end.day} {_MONTHS[end.month - 1]}"
    return f"{start.day}–{end.day} {_MONTHS[start.month - 1]}"


# --- per-type builders ----------------------------------------------------------------------


def _generic(event_type: str | None, *, known: bool) -> _Built:
    if event_type is None:
        return _Built(EventKind.STATUS, "Evento senza tipo")
    if known:
        return _Built(EventKind.STATUS, f"Evento {event_type}")
    return _Built(EventKind.STATUS, f"Evento non riconosciuto: {event_type}")


def _fixed(event_type: str) -> Builder:
    kind, title, lane_state = _FIXED[event_type]

    def build(event: Mapping[str, Any], agent: AgentName) -> _Built:
        return _Built(kind, title, {"lane_state": lane_state})

    return build


def _tool_use(event: Mapping[str, Any], agent: AgentName) -> _Built:
    """`agent.tool_use`: a built-in tool (agent_toolset_20260401) or a delegation tool."""
    name = _text(event.get("name"), 128) or ""
    tool_input = _mapping(event.get("input"))
    title, params = _builtin_title(name, tool_input)
    detail: dict[str, Any] = {
        "tool": name or None,
        "params": _pruned(params),
        "tool_use_id": _id(event),
    }
    return _with_permission(_Built(EventKind.TOOL, title, detail), event)


def _builtin_title(name: str, tool_input: Mapping[str, Any]) -> tuple[str, dict[str, Any]]:
    if name == "web_search":
        query = _inline(tool_input.get("query"), 150)
        return (f"Ricerca web: {query}" if query else "Ricerca web"), {"query": query}
    if name == "web_fetch":
        host = _host(tool_input.get("url"))
        return (f"Legge la pagina {host}" if host else "Legge una pagina web"), {"host": host}
    if name == "bash":
        return _bash_title(tool_input)
    if name in ("read", "write", "edit"):
        verb = {"read": "Legge", "write": "Scrive", "edit": "Modifica"}[name]
        path = _inline(tool_input.get("file_path"), 300)
        short = _short_path(path)
        params: dict[str, Any] = {"file_path": path}
        if name == "edit" and isinstance(tool_input.get("replace_all"), bool):
            params["replace_all"] = tool_input["replace_all"]
        return (f"{verb} {short}" if short else f"{verb} un file"), params
    if name in ("glob", "grep"):
        pattern = _inline(tool_input.get("pattern"), 120)
        what = "Cerca file" if name == "glob" else "Cerca nei file"
        params = {"pattern": pattern, "path": _inline(tool_input.get("path"), 300)}
        return (f"{what}: {pattern}" if pattern else what), params
    if name == "send_to_agent":
        target = _first_text(tool_input, ("agent_name", "agent", "name", "to", "recipient"))
        label = agent_label(target) if target else None
        title = f"Messaggio {_to(label)}" if label else "Messaggio a un agente"
        return title, {"agent": label}
    if name == "list_agents":
        return "Elenco degli agenti", {}
    tool = _inline(name, 60)
    return (f"Strumento {tool}" if tool else "Strumento"), _params(tool_input)


def _bash_title(tool_input: Mapping[str, Any]) -> tuple[str, dict[str, Any]]:
    command = tool_input.get("command")
    if not isinstance(command, str) or not command.strip():
        if tool_input.get("restart") is True:
            return "Riavvia la shell", {"restart": True}
        return "Comando", {}
    first = _first_line(command)
    params: dict[str, Any] = {"command": _clip(first, 300) if first else None}
    calls = _build_link_calls(command[:MAX_COMMAND_PARSE_CHARS])
    if not calls:
        return (f"Comando: {_clip(first, 120)}" if first else "Comando"), params
    providers = [provider for provider, _ in calls if provider]
    args = calls[0][1]
    params["provider"] = providers[0] if providers else None
    if len(providers) > 1:
        params["providers"] = providers[:MAX_NESTED_ITEMS]
    params["args"] = _params(args) or None
    labels = list(dict.fromkeys(_provider_label(p) for p in providers))
    parts = ["Link di prenotazione"]
    if labels:
        parts.append(", ".join(labels[:3]))
    where = _route(args, partial=False) or _place(args)
    if where:
        parts.append(where)
    dates = _dates(args)
    if dates:
        parts.append(dates)
    return " · ".join(parts), params


def _mcp_tool_use(event: Mapping[str, Any], agent: AgentName) -> _Built:
    """`agent.mcp_tool_use`: "Expedia · voli MXP→LIS · 14–18 nov"."""
    server = _text(event.get("mcp_server_name"), 128)
    name = _text(event.get("name"), 128)
    tool_input = _mapping(event.get("input"))
    kind = _search_kind(name or "")
    if kind in ("hotel", "offerte hotel"):
        where = _place(tool_input)
    else:
        where = _route(tool_input) or _place(tool_input)
    head = " ".join(part for part in (kind or _inline(name, 60) or "strumento", where) if part)
    parts = [_server_label(server), head]
    dates = _dates(tool_input)
    if dates:
        parts.append(dates)
    detail: dict[str, Any] = {
        "tool": name,
        "server": server,
        "params": _pruned(_params(tool_input)),
        "tool_use_id": _id(event),
    }
    return _with_permission(_Built(EventKind.TOOL, " · ".join(parts), detail), event)


def _custom_tool_use(event: Mapping[str, Any], agent: AgentName) -> _Built:
    """`agent.custom_tool_use`: `submit_plan` is a `plan` event; its input (the whole plan)
    never goes to `detail`."""
    name = _text(event.get("name"), 128)
    if name == SUBMIT_PLAN_TOOL:
        detail = {"tool": SUBMIT_PLAN_TOOL, "tool_use_id": _id(event)}
        return _Built(EventKind.PLAN, "Piano inviato per la verifica", detail)
    tool = _inline(name, 60)
    detail = {
        "tool": name,
        "params": _pruned(_params(_mapping(event.get("input")))),
        "tool_use_id": _id(event),
    }
    return _Built(
        EventKind.TOOL, f"Strumento {tool}" if tool else "Strumento personalizzato", detail
    )


def _tool_result(id_key: str, ok: str, failed: str) -> Builder:
    """`agent.tool_result` / `agent.mcp_tool_result`: whether it failed and how long it took;
    never its `content`."""

    def build(event: Mapping[str, Any], agent: AgentName) -> _Built:
        is_error = event.get("is_error") is True
        detail = {"tool_use_id": _text(event.get(id_key), 100), "is_error": is_error}
        return _Built(EventKind.TOOL, failed if is_error else ok, detail)

    return build


def _agent_message(event: Mapping[str, Any], agent: AgentName) -> _Built:
    """`agent.message`: the agent's text to its conversation partner, the user for the
    coordinator's primary thread and the coordinator for a subagent's thread."""
    sender = AGENT_LABELS[agent]
    recipient = "utente" if agent is AgentName.COORDINATOR else AGENT_LABELS[AgentName.COORDINATOR]
    return _message(sender, recipient, _content_text(event.get("content")))


def _thread_message(*, sent: bool) -> Builder:
    """`agent.thread_message_sent` / `_received`. On the session stream (where the consumer
    persists them) "sent" is coordinator -> subagent and "received" is subagent -> coordinator;
    the direction is relative to the stream, so a copy from a subagent's thread (counterpart:
    the coordinator) is read from the lane's side instead."""

    def build(event: Mapping[str, Any], agent: AgentName) -> _Built:
        other_name = _text(event.get("to_agent_name" if sent else "from_agent_name"), 128)
        other = _agent_from_name(other_name)
        lane_side = AGENT_LABELS[agent] if agent is not AgentName.COORDINATOR else "subagente"
        other_label = agent_label(other_name) if other_name is not None else lane_side
        this_side = lane_side if other is AgentName.COORDINATOR else "coordinatore"
        sender, recipient = (this_side, other_label) if sent else (other_label, this_side)
        return _message(sender, recipient, _content_text(event.get("content")))

    return build


def _user_message(event: Mapping[str, Any], agent: AgentName) -> _Built:
    """`user.message`: the brief (`sessions.build_brief`, first line "Today is ...") or a later
    backend message. Its first line is English, so the title names it instead of quoting it."""
    text = _content_text(event.get("content"))
    what = "richiesta di viaggio" if text.lstrip().startswith("Today is ") else "nuovo messaggio"
    recipient = AGENT_LABELS[agent]
    detail = {"sender": "utente", "recipient": recipient, "text": _clip(text, MAX_TEXT_CHARS)}
    return _Built(EventKind.MESSAGE, f"utente → {recipient}: {what}", detail)


def _custom_tool_result(event: Mapping[str, Any], agent: AgentName) -> _Built:
    """`user.custom_tool_result`: the backend's answer to `submit_plan` (its text is a tool
    result: never copied). The plan event with the outcome is the backend's own."""
    is_error = event.get("is_error") is True
    title = "Esito inviato all'agente: da correggere" if is_error else "Esito inviato all'agente"
    detail = {"tool_use_id": _text(event.get("custom_tool_use_id"), 100), "is_error": is_error}
    return _Built(EventKind.TOOL, title, detail)


def _user_tool_result(event: Mapping[str, Any], agent: AgentName) -> _Built:
    is_error = event.get("is_error") is True
    detail = {"tool_use_id": _text(event.get("tool_use_id"), 100), "is_error": is_error}
    return _Built(EventKind.TOOL, "Risultato dello strumento inviato", detail)


def _tool_confirmation(event: Mapping[str, Any], agent: AgentName) -> _Built:
    result = _text(event.get("result"), 16)
    title = {"allow": "Permesso concesso", "deny": "Permesso negato"}.get(result or "")
    detail = {"tool_use_id": _text(event.get("tool_use_id"), 100), "result": result}
    return _Built(EventKind.STATUS, title or "Conferma inviata", detail)


def _idle(event: Mapping[str, Any], agent: AgentName) -> _Built:
    """`session.status_idle` / `session.thread_status_idle`, with the stop reason in Italian.
    The plan decision (`consumer.decide_idle`) is the consumer's: the title only says why the
    agent stopped."""
    stop = event.get("stop_reason")
    stop_reason = _mapping(stop)
    reason = _text(stop_reason.get("type") if stop_reason else stop, 64)
    if reason is None:
        title, lane_state = "In pausa", "waiting"
    elif reason in _IDLE:
        title, lane_state = _IDLE[reason]
    else:
        title, lane_state = f"In pausa: motivo non riconosciuto ({reason})", "waiting"
    detail: dict[str, Any] = {"stop_reason": reason, "lane_state": lane_state}
    event_ids = stop_reason.get("event_ids")
    if isinstance(event_ids, list):
        ids = [_text(item, 100) for item in cast(list[Any], event_ids)[:20]]
        detail["event_ids"] = [item for item in ids if item]
    details = _mapping(event.get("stop_details"))
    detail["refusal_category"] = _text(details.get("category"), 64)
    detail["explanation"] = _inline(details.get("explanation"), 300)
    return _Built(EventKind.STATUS, title, detail)


def _thread_created(event: Mapping[str, Any], agent: AgentName) -> _Built:
    """`session.thread_created`: "Incarico a voli" (the coordinator delegated)."""
    name = _text(event.get("agent_name"), 128)
    if name is not None:
        label = agent_label(name)
    elif agent is not AgentName.COORDINATOR:
        label = AGENT_LABELS[agent]
    else:
        label = "un agente"
    return _Built(EventKind.STATUS, f"Incarico {_to(label)}", {"lane_state": "working"})


def _usage(event: Mapping[str, Any], agent: AgentName) -> _Built:
    """`session.usage`: the cumulative list cost (US cents) and the session budget."""
    usage = _mapping(event.get("usage"))
    cost = _usd_cents(usage.get("list_cost"))
    budget = _budget_cents(event.get("budget"))
    if cost is None:
        title = "Consumo aggiornato: costo non ancora disponibile"
    elif budget is not None:
        title = f"Costo finora: {format_usd(cost)} su {format_usd(budget)}"
    else:
        title = f"Costo finora: {format_usd(cost)}"
    server_tool_use = _mapping(usage.get("server_tool_use"))
    detail: dict[str, Any] = {
        "list_cost_cents": cost,
        "budget_cents": budget,
        "input_tokens": _non_negative_int(usage.get("input_tokens")),
        "output_tokens": _non_negative_int(usage.get("output_tokens")),
        "cache_read_input_tokens": _non_negative_int(usage.get("cache_read_input_tokens")),
        "web_search_requests": _non_negative_int(server_tool_use.get("web_search_requests")),
        "active_seconds": _finite_number(usage.get("active_seconds")),
    }
    return _Built(EventKind.USAGE, title, detail, cost_cents=cost)


def _session_updated(event: Mapping[str, Any], agent: AgentName) -> _Built:
    changed = [key for key in ("agent", "budget", "metadata", "title") if key in event]
    detail: dict[str, Any] = {"changed": changed}
    if "budget" not in event:
        return _Built(EventKind.STATUS, "Sessione aggiornata", detail)
    budget = _budget_cents(event.get("budget"))
    detail["budget_cents"] = budget
    if budget is not None:
        title = f"Budget della sessione portato a {format_usd(budget)}"
    elif event.get("budget") is None:
        title = "Budget della sessione rimosso"
    else:
        title = "Budget della sessione aggiornato"
    return _Built(EventKind.STATUS, title, detail)


def _session_error(event: Mapping[str, Any], agent: AgentName) -> _Built:
    """`session.error`. An MCP failure is a source warning ("Fonte Expedia non raggiungibile:
    il piano prosegue con le altre fonti"), never worded as a plan failure; whether the plan
    fails is the consumer's decision (`is_terminal_error`)."""
    error = _mapping(event.get("error"))
    error_type = _text(error.get("type") if error else event.get("error"), 64)
    retry = error.get("retry_status")
    retry_status = _text(_mapping(retry).get("type") if isinstance(retry, Mapping) else retry, 32)
    detail: dict[str, Any] = {
        "error_type": error_type,
        "retry_status": retry_status,
        "message": _inline(error.get("message"), 300),
    }
    if error_type in _MCP_ERRORS:
        server = _text(error.get("mcp_server_name"), 128)
        detail["server"] = server
        detail["severity"] = "warning"
        source = f"Fonte {_server_label(server)}"
        outcome = (
            "nuovo tentativo in corso"
            if retry_status == "retrying"
            else "il piano prosegue con le altre fonti"
        )
        return _Built(EventKind.ERROR, f"{source} {_MCP_ERRORS[error_type]}: {outcome}", detail)
    if error_type is None:
        title = "Errore della sessione"
    elif error_type.startswith("repository_"):
        title = "Errore del repository"
    else:
        title = _ERROR_TITLES.get(error_type, f"Errore della sessione ({error_type})")
    suffix = _RETRY_SUFFIXES.get(retry_status or "")
    if suffix:
        title = f"{title}: {suffix}"
    detail["severity"] = "warning" if retry_status == "retrying" else "error"
    if retry_status in ("exhausted", "terminal"):
        detail["lane_state"] = "error"
    return _Built(EventKind.ERROR, title, detail)


def _workflow_error(event: Mapping[str, Any], agent: AgentName) -> _Built:
    error = _mapping(event.get("error"))
    detail = {"error_type": _text(error.get("type"), 64), "severity": "error"}
    return _Built(EventKind.ERROR, "Errore del workflow", detail)


def _model_request_end(event: Mapping[str, Any], agent: AgentName) -> _Built:
    usage = _mapping(event.get("model_usage"))
    is_error = event.get("is_error") is True
    detail: dict[str, Any] = {
        "is_error": is_error,
        "input_tokens": _non_negative_int(usage.get("input_tokens")),
        "output_tokens": _non_negative_int(usage.get("output_tokens")),
        "cache_read_input_tokens": _non_negative_int(usage.get("cache_read_input_tokens")),
        "cache_creation_input_tokens": _non_negative_int(usage.get("cache_creation_input_tokens")),
    }
    title = "Risposta del modello con errore" if is_error else "Risposta del modello"
    return _Built(EventKind.STATUS, title, detail)


def _outcome_evaluation(event_type: str) -> Builder:
    def build(event: Mapping[str, Any], agent: AgentName) -> _Built:
        iteration = _non_negative_int(event.get("iteration"))
        detail: dict[str, Any] = {"iteration": iteration}
        if event_type == "span.outcome_evaluation_end":
            result = _text(event.get("result"), 64)
            detail["result"] = result
            label = _OUTCOME_RESULTS.get(result or "", result or "esito sconosciuto")
            return _Built(EventKind.STATUS, f"Verifica del risultato: {label}", detail)
        verb = "in corso" if event_type == "span.outcome_evaluation_ongoing" else "avviata"
        round_ = f", giro {iteration}" if iteration is not None else ""
        return _Built(EventKind.STATUS, f"Verifica del risultato {verb}{round_}", detail)

    return build


_BUILDERS: dict[str, Builder] = {
    **{event_type: _fixed(event_type) for event_type in _FIXED},
    "agent.message": _agent_message,
    "agent.tool_use": _tool_use,
    "agent.tool_result": _tool_result(
        "tool_use_id", "Risultato ricevuto", "Lo strumento ha restituito un errore"
    ),
    "agent.mcp_tool_use": _mcp_tool_use,
    "agent.mcp_tool_result": _tool_result(
        "mcp_tool_use_id", "Risposta della fonte ricevuta", "La fonte ha restituito un errore"
    ),
    "agent.custom_tool_use": _custom_tool_use,
    "agent.thread_message_sent": _thread_message(sent=True),
    "agent.thread_message_received": _thread_message(sent=False),
    "session.status_idle": _idle,
    "session.thread_status_idle": _idle,
    "session.thread_created": _thread_created,
    "session.updated": _session_updated,
    "session.usage": _usage,
    "session.error": _session_error,
    "span.model_request_end": _model_request_end,
    "span.outcome_evaluation_start": _outcome_evaluation("span.outcome_evaluation_start"),
    "span.outcome_evaluation_ongoing": _outcome_evaluation("span.outcome_evaluation_ongoing"),
    "span.outcome_evaluation_end": _outcome_evaluation("span.outcome_evaluation_end"),
    "user.message": _user_message,
    "user.custom_tool_result": _custom_tool_result,
    "user.tool_result": _user_tool_result,
    "user.tool_confirmation": _tool_confirmation,
    "workflow_run.error": _workflow_error,
}

_RESULT_TYPES = frozenset({"agent.tool_result", "agent.mcp_tool_result"})
"""Tool results: their title gets the duration the consumer measured."""

KNOWN_EVENT_TYPES: frozenset[str] = frozenset(_BUILDERS) | NOISE_EVENT_TYPES
"""Every type `normalize` knows (notes §2g); any other type becomes a generic status event."""


# --- shared pieces ----------------------------------------------------------------------------


def _message(sender: str, recipient: str, text: str) -> _Built:
    """A message row: "coordinatore → voli: <first line>", the text in `detail.text`."""
    first = _first_line(text)
    title = f"{sender} → {recipient}: {first or '(nessun testo)'}"
    detail = {"sender": sender, "recipient": recipient, "text": _clip(text, MAX_TEXT_CHARS)}
    return _Built(EventKind.MESSAGE, title, detail)


def _pruned(params: dict[str, Any]) -> dict[str, Any] | None:
    """`params` without None values; None when nothing is left."""
    kept = {key: value for key, value in params.items() if value is not None}
    return kept or None


def _to(label: str) -> str:
    """The preposition before an agent label: "a voli", "ad alloggio" (euphonic d before a)."""
    return f"ad {label}" if label[:1].lower() == "a" else f"a {label}"


def _with_permission(built: _Built, event: Mapping[str, Any]) -> _Built:
    """A tool use the platform will hold for confirmation (`ask`) or refused (`deny`)."""
    permission = _text(event.get("evaluated_permission"), 16)
    if permission == "ask":
        built.title += " (attende conferma)"
        built.detail["permission"] = permission
    elif permission == "deny":
        built.title += " (negato)"
        built.detail["permission"] = permission
    return built


def _thread_keys(event: Mapping[str, Any], event_type: str | None) -> dict[str, Any]:
    """`thread_id` (and the raw `agent_name` of thread lifecycle events): the thread the event
    belongs to, a cross-posted copy's origin, or a thread message's counterpart."""
    keys: dict[str, Any] = {}
    for key in ("session_thread_id", "to_session_thread_id", "from_session_thread_id"):
        thread_id = _text(event.get(key), 100)
        if thread_id:
            keys["thread_id"] = thread_id
            break
    if event_type is not None and event_type.startswith("session.thread_"):
        keys["agent_name"] = _text(event.get("agent_name"), MAX_KEY_CHARS)
    return keys


def _content_text(content: Any) -> str:
    """The text blocks of a message's `content`, joined by blank lines. Redacted, image and
    document blocks are skipped."""
    if isinstance(content, str):
        return _clean(content)
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for block in cast(list[Any], content):
        if isinstance(block, str):
            parts.append(_clean(block))
        elif isinstance(block, Mapping):
            block_map = cast(Mapping[str, Any], block)
            text = block_map.get("text")
            if block_map.get("type", "text") == "text" and isinstance(text, str):
                parts.append(_clean(text))
    return "\n\n".join(part for part in parts if part.strip())


def _first_line(text: str) -> str:
    """The first non-blank line, without leading Markdown heading or quote marks."""
    for line in text.splitlines():
        stripped = line.strip().lstrip("#>").strip()
        if stripped:
            return stripped
    return ""


def _title(text: str) -> str:
    return one_line(_clean(text)) or "Evento"


def _clean(text: str) -> str:
    """No U+0000 (Postgres rejects it) and no lone surrogates (not encodable as UTF-8)."""
    return text.replace(NUL, "").encode("utf-8", "replace").decode("utf-8")


def _clip(text: str, limit: int) -> str:
    text = _clean(text)
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _text(value: Any, limit: int) -> str | None:
    """A non-blank string, cleaned and capped; None for anything else."""
    if not isinstance(value, str):
        return None
    text = _clean(value).strip()
    return _clip(text, limit) if text else None


def _inline(value: Any, limit: int) -> str | None:
    """`_text` collapsed to one line."""
    if not isinstance(value, str):
        return None
    text = one_line(_clean(value), limit)
    return text or None


def _first_text(mapping: Mapping[str, Any], keys: Sequence[str]) -> str | None:
    for key in keys:
        text = _text(mapping.get(key), 128)
        if text:
            return text
    return None


def _mapping(value: Any) -> Mapping[str, Any]:
    return cast(Mapping[str, Any], value) if isinstance(value, Mapping) else {}


def _id(event: Mapping[str, Any]) -> str | None:
    return _text(event.get("id"), 100)


def _non_negative_int(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def _finite_number(value: Any) -> float | int | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return value if math.isfinite(value) else None


def _lane(agent: Any) -> AgentName:
    try:
        return AgentName(agent)
    except ValueError:
        return AgentName.COORDINATOR


def _agent_from_name(name: Any) -> AgentName | None:
    text = _text(name, 128)
    if text is None:
        return None
    try:
        return AgentName(text.lower())
    except ValueError:
        return None


def _server_label(server: str | None) -> str:
    if server is None:
        return "MCP"
    lowered = server.lower()
    for key, label in _SERVER_LABELS.items():
        if lowered == key or lowered.startswith(key):
            return label
    return _clip(server, MAX_LABEL_CHARS)


def _provider_label(provider: str) -> str:
    key = provider.strip().lower().replace("-", "_")
    return _PROVIDER_LABELS.get(key) or _clip(provider, MAX_LABEL_CHARS)


def _search_kind(tool_name: str) -> str | None:
    """What a travel MCP tool searches, from its name: voli, hotel, offerte hotel, treni."""
    name = tool_name.lower()
    if "flight" in name or "volo" in name or "voli" in name:
        return "voli"
    if any(word in name for word in ("hotel", "lodging", "accommodation", "stay")):
        return "offerte hotel" if "offer" in name else "hotel"
    if "train" in name or "rail" in name:
        return "treni"
    return None


def _short_path(path: str | None) -> str | None:
    """A file path for a title: relative to /workspace when inside it."""
    if path is None:
        return None
    if path.startswith(WORKSPACE_PREFIX) and len(path) > len(WORKSPACE_PREFIX):
        path = path[len(WORKSPACE_PREFIX) :]
    return _clip(path, 120)


def _host(url: Any) -> str | None:
    """The host of a URL (no path, query or credentials)."""
    text = _text(url, 2000)
    if text is None:
        return None
    try:
        host = urlsplit(text if "//" in text else "//" + text).hostname
    except ValueError:
        return None
    return _clip(host, 100) if host else None


def _norm_key(key: str) -> str:
    return re.sub(r"[^a-z0-9]", "", key.lower())


def _normalized_keys(mapping: Mapping[str, Any]) -> dict[str, Any]:
    keys: dict[str, Any] = {}
    for key, value in mapping.items():
        if isinstance(key, str):
            keys.setdefault(_norm_key(key), value)
    return keys


def _lookup(
    mapping: Mapping[str, Any],
    keys: Sequence[str],
    read: Callable[[Any], Any],
    *,
    depth: int = 0,
) -> Any:
    """The first value under one of `keys` (in priority order) that `read` accepts; then the
    same search one level down (nested objects, the first item of a list of objects)."""
    normalized = _normalized_keys(mapping)
    for key in keys:
        if key in normalized:
            value = read(normalized[key])
            if value is not None:
                return value
    if depth >= 1:
        return None
    for value in mapping.values():
        nested = value
        if isinstance(nested, list) and nested:
            nested = cast(list[Any], nested)[0]
        if isinstance(nested, Mapping):
            found = _lookup(cast(Mapping[str, Any], nested), keys, read, depth=depth + 1)
            if found is not None:
                return found
    return None


def _place_value(value: Any) -> str | None:
    """A place for a title: a string that is not a date, or the code/name of an object."""
    if isinstance(value, str):
        if _parse_date(value) is not None:
            return None
        return _inline(value, MAX_LABEL_CHARS)
    if isinstance(value, Mapping):
        normalized = _normalized_keys(cast(Mapping[str, Any], value))
        for key in _PLACE_VALUE_KEYS:
            found = _place_value(normalized.get(key))
            if found:
                return found
        return None
    if isinstance(value, list) and value:
        return _place_value(cast(list[Any], value)[0])
    return None


def _route(tool_input: Mapping[str, Any], *, partial: bool = True) -> str | None:
    """A route for a title: "MXP→LIS"; with `partial`, also "da MXP" or "per LIS"."""
    origin = _lookup(tool_input, _ORIGIN_KEYS, _place_value)
    destination = _lookup(tool_input, _DESTINATION_KEYS, _place_value)
    if origin and destination:
        return f"{origin}→{destination}"
    if not partial:
        return None
    if origin:
        return f"da {origin}"
    if destination:
        return f"per {destination}"
    return None


def _place(tool_input: Mapping[str, Any]) -> str | None:
    return _lookup(tool_input, _DESTINATION_KEYS, _place_value) or _lookup(
        tool_input, _PLACE_KEYS, _place_value
    )


def _dates(tool_input: Mapping[str, Any]) -> str | None:
    start = _lookup(tool_input, _START_KEYS, _parse_date)
    end = _lookup(tool_input, _END_KEYS, _parse_date)
    return format_date_range(start, end)


def _parse_date(value: Any) -> dt.date | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    for pattern, (year, month, day) in _DATE_PATTERNS:
        match = pattern.match(text)
        if match is None:
            continue
        try:
            return dt.date(int(match[year]), int(match[month]), int(match[day]))
        except ValueError:
            return None
    return None


def _shell_tokens(command: str) -> list[str]:
    try:
        return shlex.split(command)
    except ValueError:  # unbalanced quotes (e.g. a command cut at MAX_COMMAND_PARSE_CHARS)
        return command.split()


def _build_link_calls(command: str) -> list[tuple[str | None, dict[str, str]]]:
    """Each `build_link.py <provider> --key value --key=value ...` in a bash command, as
    (provider, args). `--provider X` is accepted too."""
    tokens = _shell_tokens(command)
    calls: list[tuple[str | None, dict[str, str]]] = []
    index = 0
    while index < len(tokens):
        if tokens[index].rsplit("/", 1)[-1] != BUILD_LINK_SCRIPT:
            index += 1
            continue
        provider: str | None = None
        args: dict[str, str] = {}
        index += 1
        while index < len(tokens):
            token = tokens[index]
            if token in _SHELL_SEPARATORS or token.rsplit("/", 1)[-1] == BUILD_LINK_SCRIPT:
                break
            if token.startswith("--"):
                key, has_value, value = token[2:].partition("=")
                if not has_value and index + 1 < len(tokens):
                    following = tokens[index + 1]
                    if not following.startswith("--") and following not in _SHELL_SEPARATORS:
                        value = following
                        index += 1
                if key == "provider" and provider is None:
                    provider = value or None
                elif key and len(args) < MAX_PARAMS:
                    args[key] = value
            elif provider is None and not token.startswith("-"):
                provider = token
            index += 1
        calls.append((_text(provider, MAX_LABEL_CHARS), args))
    return calls


def _params(tool_input: Mapping[str, Any]) -> dict[str, Any]:
    """The main parameters of a tool input: scalars and small nested values, capped; keys that
    carry content (`_CONTENT_KEYS`) are dropped."""
    params: dict[str, Any] = {}
    for key, value in tool_input.items():
        if len(params) >= MAX_PARAMS:
            break
        if not isinstance(key, str) or _norm_key(key) in _CONTENT_KEYS:
            continue
        kept = _param_value(value, depth=0)
        if kept is not None:
            params[_clip(key, MAX_KEY_CHARS)] = kept
    return params


def _param_value(value: Any, *, depth: int) -> Any:
    if value is None:
        return None
    if isinstance(value, bool | int):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, str):
        return _clip(value, MAX_PARAM_CHARS if depth == 0 else MAX_NESTED_CHARS)
    if depth >= 2:
        return None
    if isinstance(value, Mapping):
        nested: dict[str, Any] = {}
        for key, item in cast(Mapping[Any, Any], value).items():
            if len(nested) >= MAX_NESTED_ITEMS:
                break
            if not isinstance(key, str) or _norm_key(key) in _CONTENT_KEYS:
                continue
            kept = _param_value(item, depth=depth + 1)
            if kept is not None:
                nested[_clip(key, MAX_KEY_CHARS)] = kept
        return nested or None
    if isinstance(value, list | tuple):
        items = cast(Sequence[Any], value)[:MAX_NESTED_ITEMS]
        kept_items = [_param_value(item, depth=depth + 1) for item in items]
        return [kept for kept in kept_items if kept is not None] or None
    return None


def _usd_cents(amount: Any) -> int | None:
    """`{"amount": "41", "currency": "USD"}` -> 41 (US cents); None otherwise (another
    currency is never converted or guessed)."""
    money = _mapping(amount)
    currency = money.get("currency")
    if not isinstance(currency, str) or currency.upper() != "USD":
        return None
    raw = money.get("amount")
    if isinstance(raw, bool) or not isinstance(raw, str | int):
        return None
    try:
        cents = Decimal(str(raw).strip()).quantize(Decimal(1), rounding=ROUND_HALF_UP)
    except InvalidOperation:
        return None
    if not cents.is_finite() or cents < 0:
        return None
    return int(cents)


def _budget_cents(budget: Any) -> int | None:
    """`{"type": "limit", "max_list_cost": {"amount": "60", "currency": "USD"}}` -> 60."""
    return _usd_cents(_mapping(budget).get("max_list_cost"))


def _event_ts(event: Mapping[str, Any]) -> dt.datetime:
    value = event.get("processed_at")
    parsed: dt.datetime | None = None
    if isinstance(value, dt.datetime):
        parsed = value
    elif isinstance(value, str) and value.strip():
        try:
            parsed = dt.datetime.fromisoformat(value.strip())
        except ValueError:
            parsed = None
    if parsed is None:
        return dt.datetime.now(dt.UTC)
    if parsed.utcoffset() is None:
        parsed = parsed.replace(tzinfo=dt.UTC)
    return parsed


def _json_size(value: Any) -> int:
    return len(json.dumps(value, ensure_ascii=False, default=str))


def _bounded(detail: dict[str, Any]) -> dict[str, Any]:
    """`detail` within `MAX_DETAIL_CHARS`: nested parameters go first, then the text is cut,
    then the parameters go."""
    if _json_size(detail) <= MAX_DETAIL_CHARS:
        return detail
    params = detail.get("params")
    if isinstance(params, dict):
        scalars = cast(dict[str, Any], params)
        detail["params"] = {k: v for k, v in scalars.items() if not isinstance(v, dict | list)}
        detail["params_truncated"] = True
    text = detail.get("text")
    if _json_size(detail) > MAX_DETAIL_CHARS and isinstance(text, str):
        detail["text"] = _clip(text, MAX_DETAIL_CHARS // 2)
    if _json_size(detail) > MAX_DETAIL_CHARS:
        detail.pop("params", None)
        detail["params_truncated"] = True
    return detail
