"""evals/judge.py with a fake Anthropic client: request shape, parsing, cost accounting and
the hard per-run cap. Nothing here reaches the network."""

from __future__ import annotations

import asyncio
import datetime as dt
import json
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import judge

FIXTURES = Path(__file__).resolve().parent / "fixtures"
TODAY = dt.date(2026, 10, 12)
REQUEST = {
    "origin": "Milano",
    "destination": "Lisbona",
    "dates": {"exact_start": "2027-11-12", "exact_end": "2027-11-14"},
    "travelers": [{"kind": "adult"}, {"kind": "adult"}],
    "budget_eur": 900,
}


def plan() -> dict[str, Any]:
    return json.loads((FIXTURES / "plan_lisbon_ok.json").read_text(encoding="utf-8"))


def scores_json(**overrides: int) -> str:
    return json.dumps(
        {
            name: {"reason": f"{name} looks fine.", "score": overrides.get(name, 4)}
            for name in judge.CRITERIA
        }
    )


def response(
    text: str | None,
    *,
    input_tokens: int = 10_000,
    output_tokens: int = 1_500,
    stop_reason: str = "end_turn",
    stop_details: Any = None,
) -> SimpleNamespace:
    content = [] if text is None else [SimpleNamespace(type="text", text=text)]
    return SimpleNamespace(
        content=content,
        stop_reason=stop_reason,
        stop_details=stop_details,
        usage=SimpleNamespace(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_creation_input_tokens=0,
            cache_read_input_tokens=0,
        ),
    )


@dataclass
class FakeMessages:
    replies: list[Any]
    counted_tokens: int | Exception = 9_000
    created: list[dict[str, Any]] = field(default_factory=list[dict[str, Any]])
    counted: list[dict[str, Any]] = field(default_factory=list[dict[str, Any]])

    async def create(self, **kwargs: Any) -> Any:
        self.created.append(kwargs)
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply

    async def count_tokens(self, **kwargs: Any) -> Any:
        self.counted.append(kwargs)
        if isinstance(self.counted_tokens, Exception):
            raise self.counted_tokens
        return SimpleNamespace(input_tokens=self.counted_tokens)


@dataclass
class FakeClient:
    messages: FakeMessages


def run_judge(
    client: FakeClient, budget: judge.JudgeBudget | None = None, **kwargs: Any
) -> judge.JudgeResult:
    return asyncio.run(
        judge.judge_plan(
            client,
            request=REQUEST,
            plan=plan(),
            today=TODAY,
            budget=budget or judge.JudgeBudget(),
            **kwargs,
        )
    )


def test_scores_a_plan() -> None:
    client = FakeClient(FakeMessages([response(scores_json(summary_clarity=5))]))
    result = run_judge(client)
    assert result.status == "ok"
    assert result.scores is not None
    assert set(result.scores) == set(judge.CRITERIA)
    assert result.score("summary_clarity") == 5
    assert result.score("time_coherence") == 4
    assert result.scores["time_coherence"]["reason"] == "time_coherence looks fine."
    # 10k input at $2/MTok + 1.5k output at $10/MTok = 2 + 1.5 = 3.5 cents
    assert result.cost_cents == pytest.approx(3.5)
    assert result.input_tokens == 10_000
    assert result.output_tokens == 1_500
    json.dumps(result.to_json())


def test_request_shape() -> None:
    client = FakeClient(FakeMessages([response(scores_json())]))
    run_judge(client, rubric="RUBRIC TEXT")
    [params] = client.messages.created
    assert params["model"] == "claude-sonnet-5-5"
    assert params["system"] == "RUBRIC TEXT"
    assert params["max_tokens"] == judge.JUDGE_MAX_TOKENS
    assert "temperature" not in params
    assert "thinking" not in params
    output_format = params["output_config"]["format"]
    assert output_format["type"] == "json_schema"
    schema = output_format["schema"]
    assert schema["required"] == list(judge.CRITERIA)
    assert schema["additionalProperties"] is False
    criterion = schema["properties"]["time_coherence"]
    assert criterion["properties"]["score"]["enum"] == [1, 2, 3, 4, 5]
    assert criterion["required"] == ["reason", "score"]
    [message] = params["messages"]
    assert message["role"] == "user"
    assert "Today is 2026-10-12" in message["content"]
    assert "<plan>" in message["content"]
    assert "<request>" in message["content"]
    assert "Taberna Sal Grosso" in message["content"]
    # The count uses the same input (without effort, which only affects the output).
    [counted] = client.messages.counted
    assert counted["messages"] == params["messages"]
    assert counted["output_config"] == {"format": output_format}


def test_the_default_rubric_is_evals_rubric_md() -> None:
    client = FakeClient(FakeMessages([response(scores_json())]))
    run_judge(client)
    rubric = (Path(judge.EVALS_DIR) / "rubric.md").read_text(encoding="utf-8")
    assert client.messages.created[0]["system"] == rubric
    for criterion in judge.CRITERIA:
        assert f"### {criterion}" in rubric


def test_cap_stops_before_the_call() -> None:
    client = FakeClient(FakeMessages([response(scores_json())], counted_tokens=50_000))
    budget = judge.JudgeBudget(cap_cents=5.0)  # worst case: 55k*2 + 6k*10 per M = 17 cents
    result = run_judge(client, budget)
    assert result.status == "skipped"
    assert "judge cap" in (result.error or "")
    assert client.messages.created == []
    assert budget.exhausted
    assert budget.spent_cents == 0
    # Once exhausted, the run stops judging: no count, no call.
    again = run_judge(client, budget)
    assert again.status == "skipped"
    assert len(client.messages.counted) == 1


def test_never_exceeds_the_cap_over_a_run() -> None:
    """Calls go on while their worst case fits; the real spend stays under the cap."""
    replies = [response(scores_json(), input_tokens=9_000, output_tokens=6_000) for _ in range(20)]
    client = FakeClient(FakeMessages(replies, counted_tokens=9_000))
    budget = judge.JudgeBudget()  # 100 cents
    statuses = [run_judge(client, budget).status for _ in range(20)]
    # worst case per call: ceil(9000*1.1)*2/1e4... = 1.98 + 6 = 7.98 cents; real 1.8 + 6 = 7.8
    assert statuses.count("ok") == 12
    assert statuses[12:] == ["skipped"] * 8
    assert budget.spent_cents <= budget.cap_cents
    assert budget.spent_cents == pytest.approx(12 * 7.8)


def test_concurrent_calls_reserve_their_worst_case() -> None:
    gate = asyncio.Event()

    class SlowMessages(FakeMessages):
        async def create(self, **kwargs: Any) -> Any:
            await gate.wait()
            return await super().create(**kwargs)

    client = FakeClient(
        SlowMessages([response(scores_json()) for _ in range(5)], counted_tokens=9_000)
    )
    budget = judge.JudgeBudget(cap_cents=20.0)  # room for two worst cases of 7.98 cents

    async def scenario() -> list[judge.JudgeResult]:
        tasks = [
            asyncio.create_task(
                judge.judge_plan(client, request=REQUEST, plan=plan(), today=TODAY, budget=budget)
            )
            for _ in range(4)
        ]
        await asyncio.sleep(0.01)
        gate.set()
        return await asyncio.gather(*tasks)

    results = asyncio.run(scenario())
    assert [r.status for r in results].count("ok") == 2
    assert budget.reserved_cents == 0
    assert budget.spent_cents <= budget.cap_cents


def test_count_tokens_failure_falls_back_to_a_pessimistic_estimate() -> None:
    client = FakeClient(FakeMessages([response(scores_json())], counted_tokens=RuntimeError("x")))
    result = run_judge(client)
    assert result.status == "ok"
    assert result.estimate_source == "characters"
    params = client.messages.created[0]
    estimated = result.estimated_input_tokens
    assert estimated is not None
    assert estimated == judge.fallback_input_tokens(params)
    assert estimated > len(params["messages"][0]["content"]) / 4


def test_refusal_is_an_error_and_is_charged() -> None:
    reply = response(
        None,
        output_tokens=10,
        stop_reason="refusal",
        stop_details=SimpleNamespace(category="cyber"),
    )
    budget = judge.JudgeBudget()
    result = run_judge(FakeClient(FakeMessages([reply])), budget)
    assert result.status == "error"
    assert result.error == "refusal (cyber)"
    assert result.scores is None
    assert budget.spent_cents == pytest.approx(result.cost_cents)
    assert result.cost_cents > 0


def test_max_tokens_is_an_error() -> None:
    reply = response('{"time_coherence": {"reason": "cut', stop_reason="max_tokens")
    result = run_judge(FakeClient(FakeMessages([reply])))
    assert result.status == "error"
    assert "max_tokens" in (result.error or "")


@pytest.mark.parametrize(
    "text",
    [
        "not json",
        json.dumps({"time_coherence": {"reason": "ok", "score": 4}}),  # criteria missing
        scores_json(time_coherence=7),  # out of range
        json.dumps(
            {
                **json.loads(scores_json()),
                "extra_criterion": {"reason": "x", "score": 3},
            }
        ),
    ],
)
def test_invalid_replies_are_errors(text: str) -> None:
    result = run_judge(FakeClient(FakeMessages([response(text)])))
    assert result.status == "error"
    assert (result.error or "").startswith("invalid reply")


def test_api_error_is_recorded_with_its_worst_case_charged() -> None:
    budget = judge.JudgeBudget()
    result = run_judge(FakeClient(FakeMessages([ConnectionError("refused")])), budget)
    assert result.status == "error"
    assert result.error == "ConnectionError: refused"
    assert result.projected_cents is not None
    assert budget.spent_cents == pytest.approx(result.projected_cents)
    assert budget.reserved_cents == 0


def test_usage_cost_includes_cache_tokens() -> None:
    usage = SimpleNamespace(
        input_tokens=1_000_000,
        output_tokens=100_000,
        cache_creation_input_tokens=100_000,
        cache_read_input_tokens=1_000_000,
    )
    # 200 + 100 + 25 + 20 cents
    assert judge.usage_cost_cents(usage) == pytest.approx(345.0)
    assert judge.usage_cost_cents(None) == 0.0


def test_worst_case_uses_every_output_token() -> None:
    assert judge.worst_case_cents(10_000, 6_000) == pytest.approx(
        (11_000 * 200 + 6_000 * 1000) / 1e6
    )


def test_full_run_of_six_plans_fits_the_spec_cap() -> None:
    """Six plans of ~20k input tokens with the default max_tokens fit in 1 $."""
    assert 6 * judge.worst_case_cents(20_000, judge.JUDGE_MAX_TOKENS) <= judge.JUDGE_CAP_CENTS


# --- the real client: the backend's credential rule ---------------------------------------------


def _settings(**overrides: Any) -> Any:
    from app.config import Settings

    values: dict[str, Any] = {
        "_env_file": None,
        "environment": "development",
        "auth_mode": "local",
        "planner_allowed_emails": "evals@example.com",
        "database_url": "postgresql://localhost:5432/trip_planner_evals_test",
    }
    values.update(overrides)
    return Settings(**values)


def test_make_client_uses_the_key_when_set() -> None:
    client: Any = judge.make_client(_settings(anthropic_api_key="sk-ant-test-not-a-real-key"))

    assert client.api_key == "sk-ant-test-not-a-real-key"
    assert client.max_retries == 2


def test_make_client_federates_without_a_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Same rule as the backend (`app.ma_client.anthropic_client_kwargs`): no api_key, the SDK
    resolves federation from the environment. Nothing is exchanged: the token is never read."""
    token_file = tmp_path / "identity-token"
    token_file.write_text("fake.identity.token-not-a-secret", encoding="utf-8")
    monkeypatch.delenv("ANTHROPIC_CONFIG_DIR")  # a profile would outrank federation in the SDK
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("ANTHROPIC_IDENTITY_TOKEN_FILE", str(token_file))
    monkeypatch.setenv("ANTHROPIC_FEDERATION_RULE_ID", "fdrl_fake")
    monkeypatch.setenv("ANTHROPIC_ORGANIZATION_ID", "org-fake")
    settings = _settings(
        anthropic_identity_token_file=str(token_file),
        anthropic_federation_rule_id="fdrl_fake",
        anthropic_organization_id="org-fake",
    )

    client: Any = judge.make_client(settings)

    assert client.api_key is None
    assert client.credentials is not None
    assert client.max_retries == 2


def test_make_client_refuses_without_credentials() -> None:
    with pytest.raises(ValueError, match="ANTHROPIC_API_KEY"):
        judge.make_client(_settings())
