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
def test_coordinator_reaches_the_traveller_only_through_ask_traveller(profile: str) -> None:
    """The traveller answers only `ask_traveller`; messages reach nobody, and an end_turn without
    an accepted plan fails the plan (docs/backend-interfaces.md, decide_idle)."""
    _, system = agent_file(profile, "coordinator")
    for phrase in (
        "only through `ask_traveller`",
        "at most three times per plan",
        "Never ask what the request already says",
        "never ask a question in a message",
        "Nobody reads or answers your messages during the run",
        "state the assumption in `warnings`",
        "the whole plan fails",
    ):
        assert phrase in system


def test_coordinator_prompt_covers_the_pauses() -> None:
    _, system = agent_file("development", "coordinator")
    for kind in ("destination", "journey", "activities", "food", "other"):
        assert f"`{kind}`" in system
    for phrase in (
        "the result file's ids",
        "skip this pause",
        "never in the same turn as a delegation",
        "Bacalhau à Brás",
        "Torre de Belém, Lisboa",
        "leave out a2, a5",
        "even when the preferences touch them",  # "Cucina locale" still gets the food pause
        "with `multiple` true (false for the others)",
    ):
        assert phrase in system


def test_coordinator_keeps_unpicked_options_out_of_stops_and_bookings() -> None:
    """An offered option left unpicked is never a stop, booking or alternative, though the
    summary may name the destination candidates not taken; a refused option never sends a
    subagent after a cheaper one."""
    _, system = agent_file("development", "coordinator")
    for phrase in (
        "is never a stop, a booking or an alternative",
        "may still name the destination candidates not taken",
        "or by you when they let you choose",
        "never a follow-up",
        "asking for a cheaper one, unless the traveller turned a cheaper one down",  # step 5
    ):
        assert phrase in system
    assert "never appear in the plan" not in system


def test_coordinator_waits_for_pending_reports_after_an_answer() -> None:
    """Probe P14: a report that arrives during a pause reaches the coordinator only after its
    first turn on the answer has ended, so that turn must not chase a subagent."""
    _, system = agent_file("development", "coordinator")
    assert "end your turn without a message and wait for its report" in system
    assert "because it seems slow" in system


def test_coordinator_always_runs_the_food_pause_and_wave_2() -> None:
    """Evals run 1 (train-trip-florence): transport had answered in wave 1, and the coordinator
    went from its reply straight to submit_plan: no food pause, no days, no local legs. Steps 6
    and 7 run for every mode, and their follow-ups are not re-delegation."""
    _, system = agent_file("development", "coordinator")
    for phrase in (
        "6. **The `food` pause**, always, whatever the mode",
        "always, whatever the mode and whatever wave 1 already answered",  # step 7
        "it researches only the main journey now, the local legs in wave 2",  # step 3
        "**Close**, only once activities and transport have answered wave 2",
        "Step 7's wave-2 tasks (the activities days, transport's legs, lodging when needed) are "
        "planned work, not re-delegation",
        "wave 2 takes one for activities, and one for transport when it researched the main "
        "journey",
        "skip follow-ups you don't need (wave 2 is always needed)",
        "Wave 2 ran: the `food` pause was asked; activities.json gives the kept options a "
        "`suggested_day`; transport.json answers the arrival, departure and far-stop legs.",
    ):
        assert phrase in system
    assert "activities and transport usually need one each" not in system


def test_coordinator_never_offers_what_the_request_asks_for() -> None:
    """Evals run 1 (train-trip-florence): the requested day trip was offered as activity cards,
    the picks went elsewhere and the plan dropped it. What the request asks for is never a card;
    one of several is the coordinator's choice or the `other` pause."""
    _, system = agent_file("development", "coordinator")
    for phrase in (
        "only what the request leaves open: what it explicitly asks for (a day trip, a named "
        "museum or show) is never a card and stays in the plan whatever the picks",
        "when it asks for one of several (a day trip: Sintra or Cascais), choose yourself, or ask "
        "the `other` pause among them when the third pause is free",
        "or for the one of several the request asks for (a day trip: Sintra or Cascais)",  # table
        "most different options (kinds and areas) among those the request leaves open",  # step 4
        "Add what the request asks for to the picks",  # step 7
        "what the request explicitly asks for is in the plan, whatever the picks",  # the check
    ):
        assert phrase in system
    assert "Siena" not in system  # an example from the train-trip-florence request leaks it


def test_coordinator_titles_food_cards_by_style_and_meals_say_local_cuisine() -> None:
    """Evals run 1 (suggest-direct-flight-solo): food cards titled by dish gave meal stops that
    never said the food was local, against "cibo locale sublime"."""
    _, system = agent_file("development", "coordinator")
    for phrase in (
        'each `title` a style ("Tascas di quartiere"), never a single dish, which goes in `place`',
        "a `meal` from a food pick names its style and calls it local cuisine or a specialty",
        "Pranzo in una tasca di quartiere, cucina locale",
    ):
        assert phrase in system


def test_coordinator_candidates_meet_the_idea_hard_constraints() -> None:
    """Evals run 1 (suggest-direct-flight-solo): with "Volo diretto" in the idea, Madeira came
    first, and Bologna has no direct flight there."""
    _, system = agent_file("development", "coordinator")
    for phrase in (
        "offering only places you are sure meet the hard constraints of `destination_idea` and "
        "the preferences from the origin (a direct flight, reachable by train, a budget)",
        "your leading candidate first, the one that meets them best",
        "a destination's city and its country (`<città>, <paese>`)",  # names no real place
    ):
        assert phrase in system
    assert "Funchal" not in system  # the old `place` example primed Madeira as a candidate


def test_coordinator_prompt_handles_every_refusal() -> None:
    """The prompt quotes the refusals `ask_traveller` answers with (backend/app/choices.py).
    "One question at a time" comes only for two calls in one request, whose results arrive
    together: ending the turn on it would leave nothing pending, an end_turn that fails the
    plan (decide_idle)."""
    _, system = agent_file("development", "coordinator")
    for phrase in (
        "ask_traveller rejected",
        "after two rejections of the same question skip that pause",
        "No more questions: choose yourself.",
        "One question at a time",
        "you made two calls at once; act on the other call's answer",
    ):
        assert phrase in system
    assert "wait for the open answer" not in system


def test_coordinator_prompt_covers_the_journey_modes() -> None:
    _, system = agent_file("development", "coordinator")
    for phrase in (
        "`journey_mode`",
        "feasibility first, before any delegation",
        "Circa 3 h 30 con scalo",
        "the easier mode",
        "foot passengers",
        # transport's ferry fare may come from an aggregator: the stop's url is that page
        "the page the fare was read on (its price's `source_url`) as the stop's `url`",
        "the party's own car",
        "car ferr",
        "under about five hours",
        # step 1 settles the mode; no later fork offers an unresearched one
        "never reopened by a pause",
        "wave 1 finds no service at all for it",  # the one switch, for a mode the agent chose
        "If only one mode works",  # the journey pause needs two options
        # no mainland ferry reaches the Azores; ferries do reach Tenerife (Huelva, Cádiz)
        "a train to Ponta Delgada, in the Azores, leaves only the plane",
        "a train to Tenerife cannot",
        "no warning unless you switch (above)",  # the one switch has its warning line
        "the main journey uses the mode settled in step 1",
        "the last leg's arrival",  # a car ferry's journey arrives with its last drive
    ):
        assert phrase in system
    assert "compare the two in wave 2" not in system
    assert "Tenerife leaves only the plane" not in system
    assert "the operator's page (its price's" not in system
    assert "the operator's page in the stop's `url`" not in system
    assert "No pause and no warning about the mode" not in system
    assert "or the mode the traveller picked" not in system
    # Only the picked destination is researched: constraints.json no longer lists candidates
    # (step 2 still offers "at most three candidates", through `ask_traveller`).
    blocks = re.findall(r"```json\n(.*?)```", system, re.DOTALL)
    examples = [block for block in blocks if '"journey"' in block]
    assert len(examples) == 1
    assert "candidates" not in examples[0]
    assert json.loads(examples[0])["journey"]["mode"] == "flight"


def test_coordinator_counts_and_paces_the_drives() -> None:
    """A drive is not a booking, but its fuel and tolls count against the budget and the
    summary compares the sum with it; a drive that transport split takes two days, with the
    night between them unbooked; a far stop's null drive price is not free."""
    _, system = agent_file("development", "coordinator")
    for phrase in (
        "Compare `budget_eur` with that total plus the drives' estimated fuel and tolls",
        "the budget check counts it",
        "the summary names its cost apart from the bookings' total and compares the sum with "
        "the budget",
        "total plus the drives' fuel and tolls within `budget_eur`",
        "A drive transport split in two takes consecutive days",
        "the night there is not booked (no lodging research for it)",
        "a split drive's night aside",
        "a far stop's null `price` is not free",
    ):
        assert phrase in system
    assert "the summary names it apart from the total" not in system
    assert "the summary may name its cost" not in system


def test_coordinator_tasks_lodging_after_transport_for_a_long_drive() -> None:
    """Only transport knows whether a drive splits (route time plus stops), so for a long drive
    the lodging's dates come from its options, never from the coordinator's own estimate."""
    _, system = agent_file("development", "coordinator")
    for phrase in (
        "for a main journey by car you expect over about 7 hours, task `transport` and "
        "`activities` first, and `lodging` only after transport replies",
        "with check-in and check-out from transport's options",
        "a split drive arrives the day after it leaves",
    ):
        assert phrase in system
    assert "task lodging from the day after the start date" not in system
    assert "A drive you expect over about 9 hours" not in system


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


@pytest.mark.parametrize("agent", ["transport", "activities"])
@pytest.mark.parametrize("profile", rp.PROFILE_NAMES)
def test_research_prompts_cite_only_pages_they_saw(agent: str, profile: str) -> None:
    """Spec §3, the root cause of dead links: a source URL is a page the agent opened or a
    search result it saw, never one it composed from a site's structure. A fetch that failed
    returned no page, so it does not count."""
    _, system = agent_file(profile, agent)
    assert "a page `web_fetch` returned or a URL you saw as a search result" in system
    assert "you opened with `web_fetch`" not in system
    assert "never one composed from a site's structure" in system
    assert "cites that result's URL" in system


def test_transport_prompt_covers_every_main_journey() -> None:
    """Spec §1, delegation by mode: transport researches every main journey but a flight."""
    fields, system = agent_file("development", "transport")
    assert "the main journey when it is not a flight" in fields["description"]
    for phrase in (
        "train or coach",
        "mode `bus`",  # a coach is `bus` (plan decision 4)
        "foot passengers",
        "the party's own car",
        "`distance_km`",
        "`car_rental` is a rented one",
        "car ferry",
        "parking",  # an `other` option near the lodging (plan decision 3)
        "out <id> <mode>",  # the main-journey reply line
        "the party is not travelling in its own car",  # a car rental is not for a car trip
        # a day's driving is capped: the coordinator puts the two legs on consecutive days
        "A drive over about 9 hours is split at a town roughly halfway, once",
        "two legs, even when each is still long",  # Milano to Lisbona: no third leg
        "about 15 minutes per 2 hours of driving",  # route planners leave the stops out
    ):
        assert phrase in system


def test_transport_prompt_states_its_estimates() -> None:
    """A ferry fare cites the page it was read on; a drive's fuel and a far-stop drive come from
    stated assumptions, never from memory; a distance comes only from a route planner; a null
    price is free or not priced."""
    _, system = agent_file("development", "transport")
    for phrase in (
        "the page where you read the fare (the operator's, when you can)",
        "7 L/100 km",
        "a fuel price shown by a fetched page or a search result",
        "Never a figure from memory",
        "about 60 km/h outside cities",
        "never from memory; null when no route planner gave it",
        "null when free or not priced (a far-stop drive: fuel in the warning line)",
    ):
        assert phrase in system
    assert "the operator's page is the price's `source_url`" not in system


def test_activities_prompt_builds_the_days_around_the_picks() -> None:
    """The coordinator's wave-2 task names the picks (the traveller's or its own, worded the
    same way) and the food styles (step 7); a pick is never dropped silently, and the food
    styles may add options."""
    _, system = agent_file("development", "activities")
    for phrase in (
        "the traveller picked",
        "whether the traveller picked them or the coordinator did",
        "keep every picked option",
        "if a pick cannot fit, say so in `warnings`",
        "food styles",
        "add new ones only where a day is empty or for the task's food styles",
        "names the style and the area, never a venue from memory",  # no search left
    ):
        assert phrase in system


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
    # step 5 reads only the files step 4 has not (activities.json is read for its pause)
    assert "read each result file you have not read yet" in system
