"""The Managed Agents scenario fixtures (tests/fixtures/ma) cannot drift from the real API.

- Every scripted event parses with the SDK's own persisted-event union
  (`BetaManagedAgentsSessionEvent`, anthropic 1.13.0), except the deliberately unknown types of
  `unknown_event_type.jsonl`, which must NOT parse.
- Ids are unique `sevt_...`, timestamps carry an offset and grow, thread scopes exist.
- Every `submit_plan` input validates as `app.plan.Plan` when the script expects it accepted and
  fails when it expects a rejection; accepted plans have no deadline in the past.
- Every results file a subagent writes is a valid results envelope.
- The coordinator works in waves (spec "Il lavoro a ondate"): transport is tasked only after
  the choice (constraints.json), and happy_path, the demo's default, shows the whole shape.
"""

from __future__ import annotations

import datetime as dt
import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any, cast

import pytest
from anthropic.types.beta.sessions import BetaManagedAgentsSessionEvent
from jsonschema import Draft202012Validator
from pydantic import TypeAdapter, ValidationError

from app.ma_client import PRIMARY_SCOPE
from app.plan import Plan
from app.request import PlanRequest
from app.results import RESULTS_DIR, SUBAGENTS, parse_result
from tests.fakes import (
    FAKE_EPOCH,
    FIXTURES_DIR,
    FIXTURES_ROOT,
    FakeManagedAgentsClient,
    build_usage_event,
    load_jsonl,
    resolve_fixtures,
)

SCENARIOS = sorted(FIXTURES_DIR.glob("*.jsonl"))
REQUIRED_SCENARIOS = {
    "happy_path",
    "rejected_then_accepted",
    "three_rejections_failed",
    "budget_reached",
    "requires_action_blocked",
    "end_turn_without_plan",
    "mcp_failure",
    "restart_resume",
    "interrupt",
    "unknown_event_type",
}
UNKNOWN_TYPES = {
    "session.checkpoint_created": "unknown_event_type",
    "agent.tool_progress": "unknown_event_type",
}
"""Event types the SDK does not know, and the only scenario allowed to use them."""

SESSION_EVENT = TypeAdapter[Any](BetaManagedAgentsSessionEvent)


def scenario_id(path: Path) -> str:
    return path.stem


def emitted(path: Path) -> Iterator[tuple[str, dict[str, Any], int]]:
    """(scope, event, line) of every event a script emits, `$fixture` values resolved."""
    steps, lines = load_jsonl(path)
    for step, line in zip(steps, lines, strict=True):
        resolved = cast(dict[str, Any], resolve_fixtures(step))
        if resolved["op"] == "emit":
            yield str(resolved.get("scope", PRIMARY_SCOPE)), resolved["event"], line
        elif resolved["op"] == "usage":
            yield PRIMARY_SCOPE, build_usage_event(resolved, budget_cents=60), line


def submit_expectations(path: Path) -> list[tuple[dict[str, Any], bool, int]]:
    """(submit_plan input, is_error expected by the script's await, line) for every call."""
    steps, lines = load_jsonl(path)
    uses: dict[str, tuple[dict[str, Any], int]] = {}
    found: list[tuple[dict[str, Any], bool, int]] = []
    for step, line in zip(steps, lines, strict=True):
        if step["op"] == "emit" and step["event"]["type"] == "agent.custom_tool_use":
            event = step["event"]
            assert event["name"] == "submit_plan", f"{path.name}:{line}"
            uses[event["id"]] = (cast(dict[str, Any], resolve_fixtures(event["input"])), line)
        elif step["op"] == "await":
            match = step["match"]
            use_id = match.get("custom_tool_use_id")
            if match.get("type") == "user.custom_tool_result" and use_id in uses:
                tool_input, use_line = uses[use_id]
                found.append((tool_input, bool(match["is_error"]), use_line))
    return found


def test_every_required_scenario_ships() -> None:
    assert {path.stem for path in SCENARIOS} >= REQUIRED_SCENARIOS


@pytest.mark.parametrize("path", SCENARIOS, ids=scenario_id)
def test_scenario_loads_and_carries_a_valid_request(path: Path) -> None:
    fake = FakeManagedAgentsClient.from_jsonl(path)
    assert fake.meta["description"]
    request = PlanRequest.from_stored(fake.meta["request"])
    assert request.adults == 2
    assert fake.primary_thread_id.startswith("sthr_")
    assert fake.script[0]["op"] == "meta"


@pytest.mark.parametrize("path", SCENARIOS, ids=scenario_id)
def test_every_event_parses_with_the_sdk_union(path: Path) -> None:
    for _, event, line in emitted(path):
        if event["type"] in UNKNOWN_TYPES:
            assert UNKNOWN_TYPES[event["type"]] == path.stem, f"{path.name}:{line}"
            with pytest.raises(ValidationError):
                SESSION_EVENT.validate_python(event)
            continue
        try:
            SESSION_EVENT.validate_python(event)
        except ValidationError as exc:  # pragma: no cover - the message is the diagnosis
            pytest.fail(f"{path.name}:{line} {event['type']}: {exc.errors()[:3]}")


@pytest.mark.parametrize("path", SCENARIOS, ids=scenario_id)
def test_ids_timestamps_and_scopes_are_realistic(path: Path) -> None:
    seen_ids: set[str] = set()
    threads: set[str] = set()
    previous: dt.datetime | None = None
    for scope, event, line in emitted(path):
        where = f"{path.name}:{line}"
        assert event["id"].startswith("sevt_"), where
        assert event["id"] not in seen_ids, where
        seen_ids.add(event["id"])
        stamp = dt.datetime.fromisoformat(event["processed_at"])
        assert stamp.tzinfo is not None, f"{where}: naive processed_at"
        assert stamp > FAKE_EPOCH, where
        assert previous is None or stamp > previous, f"{where}: processed_at goes back"
        previous = stamp
        if scope != PRIMARY_SCOPE:
            assert scope in threads, f"{where}: emit on {scope} before its thread_created"
        if event["type"] == "session.thread_created":
            assert scope == PRIMARY_SCOPE, where
            assert event["session_thread_id"].startswith("sthr_"), where
            threads.add(event["session_thread_id"])


@pytest.mark.parametrize("path", SCENARIOS, ids=scenario_id)
def test_submit_plan_inputs_match_the_expected_verdict(path: Path) -> None:
    for tool_input, is_error, line in submit_expectations(path):
        where = f"{path.name}:{line}"
        if is_error:
            with pytest.raises(ValidationError):
                Plan.model_validate(tool_input)
            continue
        plan = Plan.model_validate(tool_input)
        assert plan.destination == "Lisbona, Portogallo", where
        assert plan.travelers == 4, where
        assert (plan.start_date, plan.end_date) == (dt.date(2027, 4, 14), dt.date(2027, 4, 18))
        for booking in plan.bookings:
            assert booking.book_by is None or booking.book_by > FAKE_EPOCH, where
            assert booking.price is not None, where
            assert booking.scheduled_for is not None, where


def test_scenarios_cover_accepted_and_rejected_submissions() -> None:
    verdicts = [is_error for path in SCENARIOS for _, is_error, _ in submit_expectations(path)]
    assert True in verdicts
    assert False in verdicts


@pytest.mark.parametrize("path", SCENARIOS, ids=scenario_id)
def test_result_files_written_by_subagents_are_valid(path: Path) -> None:
    for _, event, line in emitted(path):
        if event["type"] != "agent.tool_use" or event["name"] != "write":
            continue
        file_path: str = event["input"]["file_path"]
        if not file_path.startswith(f"{RESULTS_DIR}/"):
            continue
        agent = next(name for name in SUBAGENTS if file_path.startswith(f"{RESULTS_DIR}/{name}."))
        parse_result(agent, event["input"]["content"])
        assert line > 0


def test_accepted_plans_translate_within_triptracker_caps() -> None:
    """Once `mapping.plan_to_trip` and `fx.FxRates` are implemented, every accepted plan maps
    to a Trip that passes TripTracker's own trip.json."""
    from app.fx import FxRates
    from app.mapping import SeededTripIds, plan_to_trip

    schema = json.loads((FIXTURES_ROOT / "triptracker" / "trip.schema.json").read_text())
    validator = Draft202012Validator(schema)
    accepted = [
        tool_input
        for path in SCENARIOS
        for tool_input, is_error, _ in submit_expectations(path)
        if not is_error
    ]
    for tool_input in accepted:
        plan = Plan.model_validate(tool_input)
        try:
            mapping = plan_to_trip(plan, now=FAKE_EPOCH, fx=FxRates(), ids=SeededTripIds(7))
        except NotImplementedError:
            pytest.skip("mapping/fx not implemented yet")
        trip = cast(dict[str, Any], mapping.trip)
        errors = [error.message for error in validator.iter_errors(trip)]
        assert errors == []
        assert mapping.trip["endDate"] >= mapping.trip["startDate"]


# --- the waves -----------------------------------------------------------------------------------

CONSTRAINTS_PATH = "/workspace/shared/constraints.json"
WAVE_STATIONS = ("Ondata 1", "Scelta", "Ondata 2")
"""How the coordinator's Italian status messages open at each stage of the run: the live screen
draws them as named stations on the coordinator's line (web/DESIGN.md, borrowing 2)."""

Milestone = tuple[str, str]


def coordinator_milestones(path: Path) -> list[Milestone]:
    """The coordinator's own steps on the session stream, in order: its wave messages, the tasks
    it sends, the reports it receives, its constraints.json writes and its submit_plan calls."""
    found: list[Milestone] = []
    for scope, event, _ in emitted(path):
        if scope != PRIMARY_SCOPE or event.get("session_thread_id"):
            continue  # a subagent's event, or a subagent's copy cross-posted to the session
        match event["type"]:
            case "agent.message":
                text = event["content"][0]["text"]
                found += [("station", name) for name in WAVE_STATIONS if text.startswith(name)]
            case "agent.thread_message_sent":
                found.append(("task", event["to_agent_name"]))
            case "agent.thread_message_received":
                found.append(("report", event["from_agent_name"]))
            case "agent.tool_use" if event["input"].get("file_path") == CONSTRAINTS_PATH:
                found.append((event["name"], "constraints.json"))
            case "agent.custom_tool_use":
                found.append(("submit", event["name"]))
            case _:
                pass
    return found


@pytest.mark.parametrize("path", SCENARIOS, ids=scenario_id)
def test_transport_is_tasked_only_after_the_choice(path: Path) -> None:
    """Wave 2 starts transport, once the coordinator has chosen the journey and the lodging and
    written constraints.json. Only a train trip (no flights thread) tasks it in wave 1."""
    events = list(emitted(path))
    created = [e["agent_name"] for _, e, _ in events if e["type"] == "session.thread_created"]
    if "transport" in created and "flights" not in created:
        return  # a train trip: transport finds the main journey in wave 1
    chosen = False
    for scope, event, line in events:
        if (
            event["type"] == "agent.tool_use"
            and event["name"] in ("write", "edit")
            and event["input"].get("file_path") == CONSTRAINTS_PATH
        ):
            assert scope == PRIMARY_SCOPE, f"{path.name}:{line}: only the coordinator writes it"
            chosen = True
        if event["type"] == "session.thread_created" and event["agent_name"] == "transport":
            assert chosen, f"{path.name}:{line}: transport tasked before constraints.json"


def test_happy_path_runs_in_waves() -> None:
    """happy_path, the demo's default, follows the spec's run shape: "Ondata 1" tasks flights,
    lodging and activities (the city, no days yet), all three report; "Scelta" writes
    constraints.json; "Ondata 2" sends activities a follow-up on its own thread and tasks
    transport for the first time; both report; then submit_plan."""
    path = FIXTURES_DIR / "happy_path.jsonl"
    milestones = coordinator_milestones(path)
    stations = [i for i, (kind, _) in enumerate(milestones) if kind == "station"]
    assert [milestones[i][1] for i in stations] == list(WAVE_STATIONS)
    wave_1, choice, wave_2 = stations

    assert milestones[:wave_1] == []  # nothing is delegated before "Ondata 1"
    first = milestones[wave_1 + 1 : choice]
    tasks = [agent for kind, agent in first if kind == "task"]
    assert tasks == ["flights", "lodging", "activities"]
    assert sorted(agent for kind, agent in first if kind == "report") == [
        "activities",
        "flights",
        "lodging",
    ]
    assert milestones[choice + 1 : wave_2] == [("write", "constraints.json")]
    second = milestones[wave_2 + 1 :]
    assert sorted(agent for kind, agent in second if kind == "task") == ["activities", "transport"]
    assert sorted(agent for kind, agent in second if kind == "report") == [
        "activities",
        "transport",
    ]
    assert second[-1] == ("submit", "submit_plan")

    # Wave 2 follows up on the threads already open: one thread per subagent.
    created = [
        event["agent_name"]
        for _, event, _ in emitted(path)
        if event["type"] == "session.thread_created"
    ]
    assert created == ["flights", "lodging", "activities", "transport"]

    # activities.json: the city in general first (no days, no times), then the days.
    versions = [
        json.loads(event["input"]["content"])
        for _, event, _ in emitted(path)
        if event["type"] == "agent.tool_use"
        and event["name"] == "write"
        and event["input"]["file_path"].startswith(f"{RESULTS_DIR}/activities.json")
    ]
    assert [version["version"] for version in versions] == [1, 2]
    assert all(o["suggested_day"] is None for o in versions[0]["options"])
    assert all(o["start_time"] is None for o in versions[0]["options"])
    assert all(o["suggested_day"] and o["start_time"] for o in versions[1]["options"])
