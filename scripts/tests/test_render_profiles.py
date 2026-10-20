"""scripts/render_profiles.py: the generated profiles match the templates and the spec's
agent table, the submit_plan schema is fully inlined, and --check catches drift."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import jsonschema
import pytest
import render_profiles as rp
import yaml
from scripts_testlib import REPO_ROOT

SPEC_TOOLS = {
    "coordinator": {"read", "write", "glob"},
    "flights": {"web_search", "web_fetch", "bash", "read", "write"},
    "lodging": {"web_search", "web_fetch", "bash", "read", "write"},
    "activities": {"web_search", "web_fetch", "bash", "read", "write"},
    "transport": {"web_search", "web_fetch", "bash", "read", "write"},
}
SPEC_SKILLS = {
    "coordinator": {"trip-tracker-schema", "travel-research-rules"},
    "flights": {"booking-links", "travel-research-rules"},
    "lodging": {"booking-links", "travel-research-rules"},
    "activities": {"travel-research-rules"},
    "transport": {"booking-links", "travel-research-rules"},
}
SPEC_MCP = {
    "coordinator": {},
    "flights": {
        "expedia": {"search_flights"},
        "kiwi": {"search-flight"},
        "lastminute": {"search_flights"},
    },
    "lodging": {"expedia": {"search_hotels", "get_hotel_pdp_offers"}},
    "activities": {},
    "transport": {},
}
MODELS = {
    "development": ("claude-sonnet-5-5", "claude-haiku-5-5"),
    "production": ("claude-opus-5-5", "claude-sonnet-5-5"),
}
NUMBERS = {"development": (100, 3, 4, 3000, 2), "production": (400, 12, 8, 6000, 2)}
"""session budget (cents), web_search cap, web_fetch cap, web_fetch max_content_tokens,
follow-ups: the "Cost levers" values of docs/managed-agents-notes.md."""
EFFORTS = {
    "development": {
        "coordinator": "medium",
        "flights": "low",
        "lodging": "low",
        "activities": "low",
        "transport": "low",
    },
    "production": dict.fromkeys(
        ("coordinator", "flights", "lodging", "activities", "transport"), "medium"
    ),
}


def agent_file(profile: str, agent: str) -> tuple[dict[str, Any], str]:
    path = Path("profiles") / profile / "agents" / f"{agent}.md"
    text = (REPO_ROOT / path).read_text(encoding="utf-8")
    return rp.parse_agent_file(text, source=str(path))


# --- the committed output -------------------------------------------------------------------------


def test_generated_files_are_up_to_date() -> None:
    assert rp.stale_files(REPO_ROOT) == []


def test_rendering_is_deterministic() -> None:
    assert rp.build_outputs(REPO_ROOT).files == rp.build_outputs(REPO_ROOT).files


def test_check_cli_passes_on_the_repository(capsys: pytest.CaptureFixture[str]) -> None:
    assert rp.main(["--check"]) == 0
    assert "up to date" in capsys.readouterr().out


# --- agents against the spec's agent table -------------------------------------------------------


@pytest.mark.parametrize("profile", rp.PROFILE_NAMES)
@pytest.mark.parametrize("agent", rp.AGENTS)
def test_agent_matches_the_spec_table(profile: str, agent: str) -> None:
    fields, system = agent_file(profile, agent)
    coordinator_model, subagent_model = MODELS[profile]
    assert fields["name"] == agent
    assert fields["model"] == {
        "id": coordinator_model if agent == "coordinator" else subagent_model,
        "effort": EFFORTS[profile][agent],
    }
    assert fields["metadata"] == {"app": "trip-planner", "profile": profile}
    assert system
    assert "{{" not in system

    toolsets = [
        t for t in fields["tools"] if isinstance(t, dict) and t["type"] == "agent_toolset_20260401"
    ]
    assert len(toolsets) == 1
    assert toolsets[0]["default_config"] == {"enabled": False}
    enabled = {c["name"] for c in toolsets[0]["configs"] if c["enabled"]}
    assert enabled == SPEC_TOOLS[agent]
    # web_fetch caps the page text it puts in the context; web_search has no such knob.
    fetch = [c for c in toolsets[0]["configs"] if c["name"] == "web_fetch"]
    assert [c["max_content_tokens"] for c in fetch] == (
        [NUMBERS[profile][3]] if "web_fetch" in SPEC_TOOLS[agent] else []
    )

    skills = {Path(s).name for s in fields["skills"]}
    assert skills == SPEC_SKILLS[agent]
    assert all(s.startswith("../../../skills/") for s in fields["skills"])

    servers = {s["name"]: s for s in fields.get("mcp_servers", [])}
    assert set(servers) == set(SPEC_MCP[agent])
    for toolset in (
        t for t in fields["tools"] if isinstance(t, dict) and t["type"] == "mcp_toolset"
    ):
        assert toolset["default_config"] == {"enabled": False}
        names = set()
        for config in toolset["configs"]:
            assert config["enabled"] is True
            assert config["permission_policy"] == {"type": "always_allow"}
            names.add(config["name"])
        assert names == SPEC_MCP[agent][toolset["mcp_server_name"]]
    if agent == "flights":
        assert servers["kiwi"]["url"] == "https://mcp.kiwi.com"
        assert servers["expedia"]["url"] == "https://www.expedia.com/mcp"
        assert servers["lastminute"]["url"] == "https://mcp.lastminute.com/mcp"


@pytest.mark.parametrize("profile", rp.PROFILE_NAMES)
def test_coordinator_roster_and_custom_tool(profile: str) -> None:
    fields, _ = agent_file(profile, "coordinator")
    assert fields["tools"][-2:] == ["./tools/submit_plan.json", "./tools/ask_traveller.json"]
    assert fields["multiagent"] == {
        "type": "multiagent_20261001",
        "subagents": {
            "type": "enabled",
            "inline_agents": {"type": "disabled"},
            "predefined_agents": [
                "./flights.md",
                "./lodging.md",
                "./activities.md",
                "./transport.md",
            ],
        },
        "workflows": {"type": "disabled"},
        "advisor": {"type": "disabled"},
    }
    for agent in rp.SUBAGENTS:
        sub, _ = agent_file(profile, agent)
        assert "multiagent" not in sub  # one level of delegation only


def test_mcp_tool_names_are_marked_pending_probe_p4() -> None:
    for agent in ("flights", "lodging"):
        text = (REPO_ROOT / "profiles/development/agents" / f"{agent}.md").read_text(
            encoding="utf-8"
        )
        for line in text.splitlines():
            if "permission_policy" in line:
                assert "pending probe P4" in line


@pytest.mark.parametrize("profile", rp.PROFILE_NAMES)
def test_prompts_carry_the_profile_numbers(profile: str) -> None:
    budget_cents, search_cap, fetch_cap, _, follow_ups = NUMBERS[profile]
    _, coordinator = agent_file(profile, "coordinator")
    assert f"At most {follow_ups} follow-ups per subagent" in coordinator
    assert (
        f"${budget_cents // 100}.{budget_cents % 100:02d} ({budget_cents} US cents)" in coordinator
    )
    for agent in rp.SUBAGENTS:
        _, system = agent_file(profile, agent)
        assert f"At most {search_cap} `web_search` calls" in system or (
            f"use at most {search_cap} `web_search` calls" in system
        )
        assert f"at most {fetch_cap} `web_fetch` calls" in system


def test_prompt_bodies_template_only_numbers() -> None:
    """Only numbers vary in the prompt text between profiles (models live in the frontmatter)."""
    allowed = {
        "web_search_cap",
        "web_fetch_cap",
        "max_follow_ups",
        "session_budget_usd",
        "session_budget_cents",
    }
    for agent in rp.AGENTS:
        text = (REPO_ROOT / "agents" / f"{agent}.md").read_text(encoding="utf-8")
        _, body = rp.split_frontmatter(text, source=agent)
        assert set(rp.PLACEHOLDER.findall(body)) <= allowed


def test_coordinator_prompt_honours_the_brief_contract() -> None:
    _, system = agent_file("development", "coordinator")
    assert "Today is YYYY-MM-DD." in system
    assert "save that JSON verbatim to `/workspace/shared/request.json`" in system
    assert "Italian" in system
    assert "at most three candidates" in system
    for path in ("shared/constraints.json", "results/flights.json", "results/transport.json"):
        assert path in system


@pytest.mark.parametrize("profile", rp.PROFILE_NAMES)
def test_coordinator_never_waits_for_the_user(profile: str) -> None:
    """Nobody answers during a run, and an end_turn without an accepted plan fails the plan
    (docs/backend-interfaces.md, decide_idle): the prompt must say both."""
    _, system = agent_file(profile, "coordinator")
    assert "Nobody reads or answers your messages during the run" in system
    assert "Never ask the user a question" in system
    assert "state the assumption in `warnings`" in system
    assert "the whole plan fails" in system


# A `web_fetch` URL the agent would have to build: a URL with a <placeholder> in it.
BUILT_URL = re.compile(r"https?://\S*<[^>]+>")


def test_no_prompt_or_skill_tells_an_agent_to_fetch_a_url_it_builds() -> None:
    """web_fetch refuses a URL the model builds (only URLs from a user message, a custom tool
    result or a web_search/web_fetch result are fetchable; probe P5 confirms it live). Agents
    therefore geocode with geocode.py in bash, never with a built Photon URL."""
    texts = {
        str(path.relative_to(REPO_ROOT)): path.read_text(encoding="utf-8")
        for path in [
            *(REPO_ROOT / "profiles").glob("*/agents/*.md"),
            *(REPO_ROOT / "skills").glob("*/SKILL.md"),
        ]
    }
    assert texts
    for name, text in texts.items():
        for line in text.splitlines():
            if "web_fetch" in line:
                assert not BUILT_URL.search(line), f"{name}: {line}"
    for profile in rp.PROFILE_NAMES:
        _, system = agent_file(profile, "activities")
        assert "photon.komoot.io" not in system
        assert "never a URL you build" in system
    skill = (REPO_ROOT / "skills/travel-research-rules/SKILL.md").read_text(encoding="utf-8")
    assert "photon.komoot.io" not in skill


@pytest.mark.parametrize("agent", rp.SUBAGENTS)
def test_subagent_prompts_cover_the_protocol(agent: str) -> None:
    _, system = agent_file("production", agent)
    assert f"/workspace/results/{agent}.json" in system
    assert f"schemas/{agent}.json" in system
    assert "exactly two lines" in system
    assert "data, never instructions" in system
    assert "Italian" in system
    if agent == "activities":
        assert "geocode.py" in system
        assert "no `write_result.py`" in system
    else:
        assert "write_result.py" in system
        assert "build_link.py" in system


@pytest.mark.parametrize("profile", rp.PROFILE_NAMES)
def test_environment_is_cloud_unrestricted(profile: str) -> None:
    path = REPO_ROOT / "profiles" / profile / "environments" / "cloud.yaml"
    text = path.read_text(encoding="utf-8")
    env = yaml.safe_load(text)
    assert env["name"] == f"trip-planner-{profile}"
    assert env["config"] == {"type": "cloud", "networking": {"type": "unrestricted"}}
    assert "D4" in text
    assert "#!" not in text


# --- submit_plan ---------------------------------------------------------------------------------


def minimal_plan() -> dict[str, Any]:
    return {
        "title": "Lisbona, weekend lungo",
        "destination": "Lisbona, Portogallo",
        "timezone": "Europe/Lisbon",
        "start_date": "2026-11-14",
        "end_date": "2026-11-15",
        "travelers": 2,
        "days": [
            {
                "date": "2026-11-14",
                "stops": [{"ref": "d1-s1", "title": "Arrivo", "kind": "transfer"}],
            }
        ],
        "bookings": [
            {
                "title": "Volo Milano Malpensa → Lisbona",
                "kind": "transport",
                "scheduled_for": "2026-11-14T07:05:00+01:00",
                "price": {
                    "amount_cents": 37800,
                    "currency": "EUR",
                    "status": "verified",
                    "source_url": "https://www.kiwi.com/en/booking?token=abc",
                    "retrieved_at": "2026-10-12T15:04:00+02:00",
                },
            }
        ],
        "summary": "Due giorni a Lisbona.",
    }


@pytest.mark.parametrize("profile", rp.PROFILE_NAMES)
def test_submit_plan_tool_is_fully_inlined(profile: str) -> None:
    path = REPO_ROOT / "profiles" / profile / "agents" / "tools" / "submit_plan.json"
    tool = json.loads(path.read_text(encoding="utf-8"))
    assert set(tool) == {"type", "name", "description", "input_schema"}
    assert (tool["type"], tool["name"]) == ("custom", "submit_plan")
    text = json.dumps(tool["input_schema"])
    assert "$ref" not in text
    assert "$defs" not in text
    assert tool["input_schema"]["type"] == "object"
    raw = json.loads((REPO_ROOT / "schema" / "plan.json").read_text(encoding="utf-8"))
    assert tool["input_schema"]["required"] == raw["required"]
    price = tool["input_schema"]["properties"]["bookings"]["items"]["properties"]["price"]["anyOf"][
        0
    ]
    assert price["properties"]["status"]["enum"] == ["verified", "estimated"]
    assert price["description"]  # descriptions kept


def test_inlined_schema_validates_like_the_original() -> None:
    raw = json.loads((REPO_ROOT / "schema" / "plan.json").read_text(encoding="utf-8"))
    inlined = rp.inline_refs(raw)
    good = minimal_plan()
    bad = minimal_plan()
    bad["title"] = "x" * 121
    worse = minimal_plan()
    worse["bookings"][0]["price"]["status"] = "guessed"
    for schema in (raw, inlined):
        jsonschema.validate(good, schema)
        for instance in (bad, worse):
            with pytest.raises(jsonschema.ValidationError):
                jsonschema.validate(instance, schema)


@pytest.mark.parametrize("profile", rp.PROFILE_NAMES)
def test_ask_traveller_tool_is_fully_inlined(profile: str) -> None:
    path = REPO_ROOT / "profiles" / profile / "agents" / "tools" / "ask_traveller.json"
    tool = json.loads(path.read_text(encoding="utf-8"))
    assert set(tool) == {"type", "name", "description", "input_schema"}
    assert (tool["type"], tool["name"]) == ("custom", "ask_traveller")
    text = json.dumps(tool)
    assert "$ref" not in text
    assert "$defs" not in text
    raw = json.loads((REPO_ROOT / "schema/ask_traveller.json").read_text(encoding="utf-8"))
    assert tool["input_schema"]["required"] == raw["required"]
    option = tool["input_schema"]["properties"]["options"]["items"]
    assert "Bacalhau" in option["properties"]["place"]["description"]


def test_inline_refs_names_its_source() -> None:
    bad = {"type": "object", "properties": {"a": {"$ref": "#/$defs/B"}}}
    with pytest.raises(rp.RenderError, match=r"ask_traveller\.json"):
        rp.inline_refs(bad, source="ask_traveller.json")


def test_inline_refs_keeps_sibling_keys_and_rejects_bad_refs() -> None:
    schema = {
        "type": "object",
        "$defs": {"A": {"type": "string", "description": "generic"}},
        "properties": {"a": {"$ref": "#/$defs/A", "description": "specific"}},
    }
    assert rp.inline_refs(schema) == {
        "type": "object",
        "properties": {"a": {"type": "string", "description": "specific"}},
    }
    with pytest.raises(rp.RenderError, match="no matching entry"):
        rp.inline_refs({"type": "object", "properties": {"a": {"$ref": "#/$defs/B"}}})
    with pytest.raises(rp.RenderError, match="non-local"):
        rp.inline_refs({"type": "object", "properties": {"a": {"$ref": "other.json#/x"}}})
    recursive = {
        "type": "object",
        "$defs": {"N": {"type": "object", "properties": {"next": {"$ref": "#/$defs/N"}}}},
        "properties": {"n": {"$ref": "#/$defs/N"}},
    }
    with pytest.raises(rp.RenderError, match="recursive"):
        rp.inline_refs(recursive)


# --- templating and --check ----------------------------------------------------------------------


def test_unknown_placeholder_is_an_error() -> None:
    with pytest.raises(rp.RenderError, match="unknown placeholder"):
        rp.substitute("model: {{ models.pilot }}", {"models.flights": "x"}, source="t")
    with pytest.raises(rp.RenderError, match="malformed"):
        rp.substitute("cap: {{ web search }}", {}, source="t")
    assert rp.substitute("a {{x}} b {{ x }}", {"x": "1"}, source="t") == "a 1 b 1"


def test_template_notes_are_dropped_and_comments_kept() -> None:
    text = "#! note\n# kept\nname: x  # inline kept\n"
    assert rp.drop_template_notes(text) == "# kept\nname: x  # inline kept\n"


def test_budget_dollars_are_rendered_from_cents() -> None:
    values = {
        "environment_name": "e",
        "models": {},
        "efforts": {},
        "session_budget_cents": 5,
        "web_search_cap": 1,
        "web_fetch_cap": 1,
        "web_fetch_max_content_tokens": 1000,
        "max_follow_ups": 1,
    }
    assert rp.template_context("development", values)["session_budget_usd"] == "0.05"


def test_check_reports_stale_missing_and_unexpected(fake_repo: Path) -> None:
    assert rp.stale_files(fake_repo) == []
    coordinator = fake_repo / "profiles/development/agents/coordinator.md"
    coordinator.write_text(
        coordinator.read_text(encoding="utf-8") + "\nhand edit\n", encoding="utf-8"
    )
    (fake_repo / "profiles/production/environments/cloud.yaml").unlink()
    (fake_repo / "profiles/development/agents/pilot.md").write_text("---\nname: pilot\n---\nx\n")
    (fake_repo / "skills/travel-research-rules/schemas/old.json").write_text("{}")
    problems = rp.stale_files(fake_repo)
    assert "stale: profiles/development/agents/coordinator.md" in problems
    assert "missing: profiles/production/environments/cloud.yaml" in problems
    assert "unexpected: profiles/development/agents/pilot.md" in problems
    assert "unexpected: skills/travel-research-rules/schemas/old.json" in problems
    assert rp.main(["--check", "--repo-root", str(fake_repo)]) == 1
    assert rp.main(["--repo-root", str(fake_repo)]) == 0
    assert rp.stale_files(fake_repo) == []
    assert not (fake_repo / "profiles/development/agents/pilot.md").exists()


def test_a_template_change_reaches_both_profiles(fake_repo: Path) -> None:
    template = fake_repo / "agents" / "lodging.md"
    template.write_text(
        template.read_text(encoding="utf-8").replace("# Role", "# Role\n\nNew line.")
    )
    stale = rp.stale_files(fake_repo)
    assert stale == [
        "stale: profiles/development/agents/lodging.md",
        "stale: profiles/production/agents/lodging.md",
    ]


def test_profiles_yaml_is_validated(fake_repo: Path) -> None:
    path = fake_repo / "agents" / "profiles.yaml"
    path.write_text(
        path.read_text(encoding="utf-8").replace("web_search_cap: 3", "web_search_cap: 0")
    )
    with pytest.raises(rp.RenderError, match="web_search_cap"):
        rp.build_outputs(fake_repo)


def test_profiles_yaml_rejects_an_unknown_effort(fake_repo: Path) -> None:
    path = fake_repo / "agents" / "profiles.yaml"
    path.write_text(path.read_text(encoding="utf-8").replace("flights: low", "flights: off"))
    with pytest.raises(rp.RenderError, match=r"efforts\.flights"):
        rp.build_outputs(fake_repo)


def test_validation_requires_a_web_fetch_content_cap(fake_repo: Path) -> None:
    template = fake_repo / "agents" / "activities.md"
    text = template.read_text(encoding="utf-8")
    text = text.replace(", max_content_tokens: {{ web_fetch_max_content_tokens }}", "")
    template.write_text(text, encoding="utf-8")
    with pytest.raises(rp.RenderError, match="max_content_tokens"):
        rp.build_outputs(fake_repo)


def test_validation_rejects_an_mcp_server_without_toolset(fake_repo: Path) -> None:
    template = fake_repo / "agents" / "transport.md"
    text = template.read_text(encoding="utf-8")
    text = text.replace(
        "tools:\n", 'mcp_servers:\n  - {type: url, name: x, url: "https://x.example"}\ntools:\n', 1
    )
    template.write_text(text, encoding="utf-8")
    with pytest.raises(rp.RenderError, match="mcp_toolset"):
        rp.build_outputs(fake_repo)


def test_skill_schemas_are_copies_of_schema_results() -> None:
    for path in sorted((REPO_ROOT / "schema" / "results").glob("*.json")):
        copy = REPO_ROOT / "skills" / "travel-research-rules" / "schemas" / path.name
        assert copy.read_bytes() == path.read_bytes()


def test_generated_header_marks_every_text_file() -> None:
    for path in (REPO_ROOT / "profiles").rglob("*"):
        if path.suffix in (".md", ".yaml"):
            text = path.read_text(encoding="utf-8")
            assert re.search(r"^# Generated by scripts/render_profiles.py", text, re.MULTILINE)


@pytest.mark.parametrize("profile", rp.PROFILE_NAMES)
@pytest.mark.parametrize("agent", rp.SUBAGENTS)
def test_subagent_prompts_carry_the_cost_rules(profile: str, agent: str) -> None:
    """The cost levers of docs/managed-agents-notes.md that live in the prompts."""
    _, system = agent_file(profile, agent)
    assert "# Cost rules" in system
    assert "reword" in system  # no repeated or reworded searches
    assert "do not use the rest of the" in system
    assert "read the file back" in system
    if agent != "activities":
        assert "write_result.py" in system


@pytest.mark.parametrize("profile", rp.PROFILE_NAMES)
def test_coordinator_prompt_forbids_re_delegation(profile: str) -> None:
    _, system = agent_file(profile, "coordinator")
    assert "No re-delegation" in system
    assert "read each file once" in system
