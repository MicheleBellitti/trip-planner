"""Timeline fixtures for the web app, made by the backend's own normalizer.

The web reducer (web/lib/plan-events/) reads `UIEvent.detail`, whose keys only the backend
defines (backend/app/events.py, "`detail` vocabulary"). Hand-written fixtures drift from it, so
these are generated: each scripted Managed Agents session in backend/tests/fixtures/ma/ is
played the way the consumer stores it (stream ownership, dedupe, lanes, tool durations, the
cumulative cost) through `app.events.normalize`, plus the events the backend makes itself (the
plan start, the brief's echo, the submit_plan outcome, "Continua"). The result is the list of
UIEvents a browser receives, with the plan status GET /plans/{id} would answer after each one.

Run from backend/ (it imports the backend; no database, no network):

    uv run python ../web/scripts/gen-backend-fixtures.py           # rewrite the fixtures
    uv run python ../web/scripts/gen-backend-fixtures.py --check   # fail when they are stale

ci-backend.yml runs --check, so a change to the backend's event vocabulary fails CI until the
fixtures (and the web tests that read them) follow.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import uuid
from collections.abc import Callable, Iterator, Mapping
from pathlib import Path
from typing import Any

WEB_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = WEB_DIR.parent
BACKEND_DIR = REPO_ROOT / "backend"
MA_FIXTURES = BACKEND_DIR / "tests" / "fixtures" / "ma"
OUT_DIR = WEB_DIR / "lib" / "plan-events" / "__fixtures__" / "backend"

if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app import consumer, sessions  # noqa: E402
from app.choices import (  # noqa: E402
    ASK_TRAVELLER_TOOL,
    ChoiceRequest,
    answer_text,
    auto_pick,
    choice_payload,
    request_of,
)
from app.config import Settings  # noqa: E402
from app.covers import Cover  # noqa: E402
from app.db import ChoiceRecord, PlanStatus  # noqa: E402
from app.events import AgentName, EventKind, UIEvent, normalize  # noqa: E402
from app.ma_client import PRIMARY_SCOPE, usage_from_event  # noqa: E402
from app.request import PlanRequest  # noqa: E402
from tests.fakes import build_usage_event  # noqa: E402

PLAN_ID = uuid.UUID("7d1f3c1e-2a4b-4c5d-8e6f-0a1b2c3d4e5f")
TODAY = dt.date(2026, 10, 12)
SESSION_BUDGET_CENTS = 60
"""The development profile's session budget: what the fake session starts with."""

CHOICE_PHOTOS = WEB_DIR / "lib" / "demo" / "choice-photos.json"
"""The photos of the `choices` recording's options (capture-choice-photos.py); missing: none."""
CHOICE_TIMEOUT = dt.timedelta(
    seconds=Settings.model_fields["choice_timeout_seconds"].get_default(call_default_factory=True)
)
"""The window a question is open: the Settings default."""
TRAVELLER_THINKS = dt.timedelta(seconds=9)
"""How long after the question's pause the recorded traveller answers."""

SCENARIOS = {
    "happy-path": "happy_path.jsonl",
    "budget-reached": "budget_reached.jsonl",
    "mcp-failure": "mcp_failure.jsonl",
    "choices": "choices.jsonl",
}

IDLE_TARGETS = {
    consumer.IdleDecision.READY: PlanStatus.READY,
    consumer.IdleDecision.INTERRUPTED: PlanStatus.INTERRUPTED,
    consumer.IdleDecision.BUDGET_PAUSED: PlanStatus.BUDGET_PAUSED,
    consumer.IdleDecision.BLOCKED: PlanStatus.BLOCKED,
    consumer.IdleDecision.FAILED: PlanStatus.FAILED,
}
TERMINAL = {PlanStatus.READY, PlanStatus.FAILED, PlanStatus.BLOCKED, PlanStatus.INTERRUPTED}


def _instant(value: str) -> dt.datetime:
    return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))


def _api_time(value: dt.datetime) -> str:
    """The API's format: `2026-10-12T10:00:00.000Z`."""
    return value.astimezone(dt.UTC).strftime("%Y-%m-%dT%H:%M:%S.") + (
        f"{value.microsecond // 1000:03d}Z"
    )


def _choice_photos() -> dict[str, Cover]:
    if not CHOICE_PHOTOS.exists():
        return {}
    data = json.loads(CHOICE_PHOTOS.read_text(encoding="utf-8"))
    return {key: Cover.model_validate(value) for key, value in data["photos"].items()}


def _steps(path: Path) -> Iterator[dict[str, Any]]:
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip() and not line.lstrip().startswith("#"):
            yield json.loads(line)


class Timeline:
    """What the consumer would store for one scripted session."""

    def __init__(self, request: PlanRequest) -> None:
        self.request = request
        self.state = consumer.ConsumerState(status=PlanStatus.RUNNING)
        self.events: list[UIEvent] = []
        self.statuses: list[dict[str, Any]] = []
        self.status = PlanStatus.RUNNING
        self.budget_cents = SESSION_BUDGET_CENTS
        self.keys: set[str] = set()
        self.tool_started: dict[str, dt.datetime] = {}
        self.last_ts: dt.datetime | None = None
        self.echoes = 0
        self.photos = _choice_photos()
        self.choices: dict[str, ChoiceRecord] = {}

    @property
    def over(self) -> bool:
        return self.status in TERMINAL

    def _store(self, build: Callable[[int], UIEvent | None]) -> UIEvent | None:
        event = build(len(self.events))
        if event is not None:
            self.events.append(event)
            self.last_ts = event.ts
        return event

    def _set_status(self, status: PlanStatus) -> None:
        if status is not self.status:
            self.status = status
            self.statuses.append({"after_seq": len(self.events) - 1, "status": status.value})

    def backend_event(
        self,
        kind: EventKind,
        title: str,
        *,
        ts: dt.datetime,
        detail: Mapping[str, Any] | None,
        cost: bool = False,
    ) -> None:
        build = consumer.backend_event(
            kind,
            title,
            ts=ts,
            detail=detail,
            cost_cents=self.state.cost_cents if cost else None,
        )
        self._store(build)

    def receive(self, raw: dict[str, Any], scope: str = PRIMARY_SCOPE) -> None:
        """`PlanConsumer._handle` without the I/O: ownership, dedupe, lane, duration, cost."""
        if self.over or not consumer.stream_owns(scope, raw):
            return
        key = consumer.dedupe_key(raw, plan_id=PLAN_ID, scope=scope)
        if key is None or key in self.keys:
            return
        self.keys.add(key)
        self._observe(raw)
        lane = consumer.lane_for(raw, scope=scope, state=self.state)
        duration = self._duration_ms(raw)
        cost = self.state.cost_cents
        event = self._store(
            lambda seq: normalize(raw, seq=seq, agent=lane, cost_cents=cost, duration_ms=duration)
        )
        if event is None:
            return
        event_type = raw.get("type")
        if event_type == "agent.custom_tool_use" and raw.get("name") == ASK_TRAVELLER_TOOL:
            self.ask(raw, event)
        elif event_type == "session.status_idle":
            target = IDLE_TARGETS.get(consumer.decide_idle(raw, self.state).decision)
            if target is not None:
                self._set_status(target)
        elif event_type in ("session.status_terminated", "session.deleted"):
            self._set_status(PlanStatus.READY if self.state.accepted else PlanStatus.FAILED)

    def _observe(self, raw: Mapping[str, Any]) -> None:
        event_type = raw.get("type")
        if event_type == "agent.custom_tool_use" and isinstance(raw.get("id"), str):
            self.state.custom_tool_use_ids.add(raw["id"])
        elif event_type == "session.thread_created":
            thread_id, name = raw.get("session_thread_id"), raw.get("agent_name")
            if isinstance(thread_id, str) and thread_id not in self.state.threads:
                try:
                    self.state.threads[thread_id] = AgentName(str(name))
                except ValueError:
                    self.state.threads[thread_id] = AgentName.COORDINATOR
        elif event_type == "session.usage":
            usage = usage_from_event(raw)
            if usage is not None and usage.list_cost_cents is not None:
                self.state.cost_cents = max(self.state.cost_cents or 0, usage.list_cost_cents)
        elif (
            event_type in ("agent.tool_use", "agent.mcp_tool_use")
            and isinstance(raw.get("id"), str)
            and isinstance(raw.get("processed_at"), str)
        ):
            self.tool_started[raw["id"]] = _instant(raw["processed_at"])

    def _duration_ms(self, raw: Mapping[str, Any]) -> int | None:
        id_key = {"agent.tool_result": "tool_use_id", "agent.mcp_tool_result": "mcp_tool_use_id"}
        key = id_key.get(str(raw.get("type")))
        started = self.tool_started.pop(str(raw.get(key)), None) if key else None
        ended = raw.get("processed_at")
        if started is None or not isinstance(ended, str):
            return None
        return max(0, int((_instant(ended) - started).total_seconds() * 1000))

    def echo(self, raw: dict[str, Any]) -> None:
        """A message the backend sent, as the API echoes it on the session stream."""
        self.echoes += 1
        assert self.last_ts is not None
        echoed = {
            "id": f"sevt_echo_{self.echoes:04d}",
            "processed_at": _api_time(self.last_ts + dt.timedelta(milliseconds=40)),
            **raw,
        }
        self.receive(echoed)

    def brief(self) -> None:
        text = sessions.build_brief(self.request, today=TODAY)
        self.echo({"type": "user.message", "content": [{"type": "text", "text": text}]})

    def ask(self, raw: Mapping[str, Any], tool_event: UIEvent) -> None:
        """`PlanConsumer._ask_traveller`: the question's row and its `asked` event, right after
        the raw tool use. The row is only built, never stored."""
        request = ChoiceRequest.model_validate(raw["input"])
        asked_at = tool_event.ts + dt.timedelta(milliseconds=20)
        photos = {o.id: self.photos[o.id] for o in request.options if o.id in self.photos}
        record = ChoiceRecord(
            id=raw["id"],
            plan_id=PLAN_ID,
            kind=request.kind,
            payload=choice_payload(request, photos),
            asked_at=asked_at,
            deadline_at=asked_at + CHOICE_TIMEOUT,
        )
        self.choices[record.id] = record
        self._store(consumer.choice_asked_event(record, cost_cents=self.state.cost_cents))

    def answer_choice(self, choice_id: str) -> None:
        """The traveller picks the CLI's and the evals' picks: the answered event, then the
        tool result's echo (`sessions.answer_choice`)."""
        assert self.last_ts is not None
        request = request_of(self.choices[choice_id])
        selected = auto_pick(request)
        self._store(
            consumer.choice_answered_event(
                choice_id=choice_id,
                request=request,
                answered_by="traveller",
                selected=selected,
                now=self.last_ts + TRAVELLER_THINKS,
                cost_cents=self.state.cost_cents,
            )
        )
        self.echo(
            {
                "type": "user.custom_tool_result",
                "custom_tool_use_id": choice_id,
                "is_error": False,
                "content": [{"type": "text", "text": answer_text(request, "traveller", selected)}],
            }
        )

    def answer_submit(self, tool_use_id: str, *, accepted: bool, warnings: int) -> None:
        """`PlanConsumer._answer_tool_use`: the outcome event, then the tool result's echo."""
        if not accepted:
            msg = "rejections are not generated: their errors come from the full evaluation"
            raise NotImplementedError(msg)
        assert self.last_ts is not None
        self.backend_event(
            EventKind.PLAN,
            consumer.TITLE_PLAN_ACCEPTED,
            ts=self.last_ts + dt.timedelta(milliseconds=20),
            detail={
                "event_type": "backend.submit_plan",
                "tool_use_id": tool_use_id,
                "outcome": "accepted",
                "attempt": self.state.submit_attempts + 1,
                "warnings": warnings,
                "is_error": False,
                "answer": consumer.PLAN_ACCEPTED_TEXT,
            },
            cost=True,
        )
        self.state.accepted = True
        self.state.submit_attempts += 1
        self.echo(
            {
                "type": "user.custom_tool_result",
                "custom_tool_use_id": tool_use_id,
                "is_error": False,
                "content": [{"type": "text", "text": consumer.PLAN_ACCEPTED_TEXT}],
            }
        )

    def continue_plan(self) -> None:
        """'Continua con 2 $ in più' (`sessions.continue_plan`), then the API's
        `session.updated` with the new budget."""
        assert self.last_ts is not None
        consumed = self.state.cost_cents or 0
        new_budget = max(self.budget_cents, consumed) + sessions.CONTINUE_INCREMENT_CENTS
        ts = self.last_ts + dt.timedelta(seconds=20)
        self.backend_event(
            EventKind.STATUS,
            sessions.TITLE_CONTINUED,
            ts=ts,
            detail={"event_type": "backend.status", "plan_status": PlanStatus.RUNNING.value},
        )
        self._set_status(PlanStatus.RUNNING)
        self.budget_cents = new_budget
        self.echo(
            {
                "type": "session.updated",
                "budget": {
                    "type": "limit",
                    "max_list_cost": {"amount": str(new_budget), "currency": "USD"},
                },
            }
        )


def _plan_warnings(tool_input: Mapping[str, Any]) -> int:
    ref = tool_input.get("$fixture")
    plan: Any = tool_input
    if isinstance(ref, str):
        plan = json.loads((BACKEND_DIR / "tests" / "fixtures" / ref).read_text(encoding="utf-8"))
    warnings = plan.get("warnings") if isinstance(plan, Mapping) else None
    return len(warnings) if isinstance(warnings, list) else 0


def build_scenario(file_name: str) -> dict[str, Any]:
    steps = list(_steps(MA_FIXTURES / file_name))
    meta = next(step for step in steps if step["op"] == "meta")
    request = PlanRequest.model_validate(meta["request"])
    timeline = Timeline(request)
    first = next(
        _instant(step["event"]["processed_at"])
        for step in steps
        if step["op"] == "emit" and "processed_at" in step["event"]
    )
    timeline.backend_event(
        EventKind.STATUS,
        sessions.TITLE_PLAN_CREATED,
        ts=first - dt.timedelta(seconds=3),
        detail=None,
    )
    timeline.last_ts = first - dt.timedelta(seconds=1)
    submits: dict[str, int] = {}
    for step in steps:
        if timeline.over:
            break
        op = step["op"]
        if op == "emit":
            event = step["event"]
            if event.get("type") == "agent.custom_tool_use" and event.get("name") == "submit_plan":
                submits[event["id"]] = _plan_warnings(event.get("input") or {})
            timeline.receive(event, step.get("scope", PRIMARY_SCOPE))
        elif op == "usage":
            timeline.receive(build_usage_event(step, budget_cents=timeline.budget_cents))
        elif op == "await":
            match = step["match"]
            if match.get("type") == "user.message":
                timeline.brief()
            elif match.get("type") == "user.custom_tool_result":
                tool_use_id = match["custom_tool_use_id"]
                if tool_use_id in timeline.choices:
                    timeline.answer_choice(tool_use_id)
                else:
                    timeline.answer_submit(
                        tool_use_id,
                        accepted=not match.get("is_error"),
                        warnings=submits[tool_use_id],
                    )
        elif op == "await_call" and step.get("method") == "update_budget":
            timeline.continue_plan()
    return {
        "source": f"backend/tests/fixtures/ma/{file_name}",
        "generated_by": "web/scripts/gen-backend-fixtures.py (do not edit by hand)",
        "description": meta.get("description", ""),
        "plan_id": str(PLAN_ID),
        "events": [event.model_dump(mode="json") for event in timeline.events],
        "statuses": timeline.statuses,
        "end": timeline.status.value if timeline.over else None,
    }


def build_samples() -> dict[str, Any]:
    """Single events a scenario doesn't contain, normalized the same way."""
    ts = "2026-10-12T10:05:00.000Z"
    samples = {
        "thread_terminated": (
            {
                "type": "session.thread_status_terminated",
                "id": "sevt_sample_0001",
                "session_thread_id": "sthr_sample_flights",
                "agent_name": "flights",
                "processed_at": ts,
            },
            AgentName.FLIGHTS,
        ),
        "session_terminated": (
            {"type": "session.status_terminated", "id": "sevt_sample_0002", "processed_at": ts},
            AgentName.COORDINATOR,
        ),
        "submit_result_rejected": (
            {
                "type": "user.custom_tool_result",
                "id": "sevt_sample_0003",
                "custom_tool_use_id": "sevt_sample_submit",
                "is_error": True,
                "processed_at": ts,
            },
            AgentName.COORDINATOR,
        ),
        "requires_action": (
            {
                "type": "session.status_idle",
                "id": "sevt_sample_0004",
                "stop_reason": {"type": "requires_action", "event_ids": ["sevt_sample_submit"]},
                "processed_at": ts,
            },
            AgentName.COORDINATOR,
        ),
    }
    out: dict[str, Any] = {}
    for name, (raw, agent) in samples.items():
        event = normalize(raw, seq=0, agent=agent)
        assert event is not None
        out[name] = event.model_dump(mode="json")
    return {
        "generated_by": "web/scripts/gen-backend-fixtures.py (do not edit by hand)",
        "events": out,
    }


def render(data: Mapping[str, Any]) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2) + "\n"


def outputs() -> dict[Path, str]:
    files = {
        OUT_DIR / f"{name}.json": render(build_scenario(src)) for name, src in SCENARIOS.items()
    }
    files[OUT_DIR / "samples.json"] = render(build_samples())
    return files


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Timeline fixtures for the web app.")
    parser.add_argument("--check", action="store_true", help="fail when a fixture is stale")
    args = parser.parse_args(argv)
    stale: list[Path] = []
    for path, text in outputs().items():
        current = path.read_text(encoding="utf-8") if path.exists() else None
        if current == text:
            continue
        if args.check:
            stale.append(path)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
            print(f"wrote {path.relative_to(REPO_ROOT)}")
    if stale:
        for path in stale:
            print(f"stale: {path.relative_to(REPO_ROOT)}", file=sys.stderr)
        print(
            "The backend's UI events changed: run `uv run python ../web/scripts/"
            "gen-backend-fixtures.py` from backend/ and update the web tests.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
