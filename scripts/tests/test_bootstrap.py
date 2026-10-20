"""scripts/bootstrap.py, offline: ant's hashing and lockfile format, the loader, the dry run
(no network at all) and a full apply against an in-memory API over httpx2.MockTransport.

Keys are ant's: relative to the lockfile's directory (backend/), so `../profiles/...` and
`../skills/...` (anthropic-cli core/lock.go `Root()`, core/loader.go `keyFor`)."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any

import bootstrap as bs
import pytest
from scripts_testlib import REPO_ROOT, FakeAnthropicApi

DEV = "../profiles/development"
SUBAGENT_KEYS = [f"{DEV}/agents/{n}.md" for n in ("activities", "flights", "lodging", "transport")]
COORDINATOR_KEY = f"{DEV}/agents/coordinator.md"
ENVIRONMENT_KEY = f"{DEV}/environments/cloud.yaml"
SKILL_KEYS = [
    "../skills/booking-links",
    "../skills/travel-research-rules",
    "../skills/trip-tracker-schema",
]


def run(fake_repo: Path, *args: str, client: Any = None) -> tuple[int, str]:
    lines: list[str] = []
    code = bs.main(["--repo-root", str(fake_repo), *args], client=client, out=lines.append)
    return code, "\n".join(lines)


def lockfile(fake_repo: Path) -> dict[str, Any]:
    return json.loads(
        (fake_repo / "backend" / "claude-lock.development.json").read_text(encoding="utf-8")
    )


def legacy_form(document: dict[str, Any]) -> dict[str, Any]:
    """The lockfile as the first bootstrap.py keyed it: from the repository root."""
    resources = document["resources"]
    return {**document, "resources": {k.replace("../", "./", 1): v for k, v in resources.items()}}


def backend_lockfile_module() -> Any:
    backend = str(REPO_ROOT / "backend")
    if backend not in sys.path:
        sys.path.insert(0, backend)
    return pytest.importorskip("app.lockfile")


# --- ant's canonical JSON, hashes and lockfile text ---------------------------------------------


def test_canonical_json_matches_go() -> None:
    value = {"b": [1, 2.0, 0.5, True, None], "a": "<&> \u00e8 \n\t\b\f\x01\u2028", "c": {}}
    expected = (
        '{"a":"\\u003c\\u0026\\u003e \u00e8 '
        '\\n\\t\\b\\f\\u0001\\u2028","b":[1,2,0.5,true,null],"c":{}}'
    )
    assert bs.canonical_json(value) == expected


@pytest.mark.parametrize(
    ("value", "text"),
    [
        (4.0, "4"),
        (0.5, "0.5"),
        (1e-9, "1e-09"),
        (0.001234, "0.001234"),
        (1234567.5, "1.2345675e+06"),
        (-2.25, "-2.25"),
        (1e21, "1e+21"),
        (123456.75, "123456.75"),
    ],
)
def test_floats_are_spelled_like_go(value: float, text: str) -> None:
    assert bs.go_float(value) == text


def test_digest_is_length_prefixed_sha256() -> None:
    body = {"name": "x"}
    data = b'{"name":"x"}'
    expected = hashlib.sha256(b"12:" + data).hexdigest()[:32]
    assert bs.hash_body(body) == expected


def test_normalize_remote_drops_server_fields_and_empties() -> None:
    remote = {
        "id": "agent_1",
        "version": 3,
        "type": "agent",
        "created_at": "t",
        "archived_at": None,
        "name": "flights",
        "description": "",
        "mcp_servers": [],
        "metadata": {},
        "tools": [{"type": "x", "configs": [], "default_config": {"enabled": False}}],
    }
    assert bs.normalize_remote(bs.AGENT, remote) == {
        "name": "flights",
        "tools": [{"type": "x", "default_config": {"enabled": False}}],
    }


def test_lockfile_text_is_ants_marshal_indent(tmp_path: Path) -> None:
    lock = bs.Lockfile(path=tmp_path / "claude-lock.json")
    lock.origin = {"base_url": "https://api.anthropic.com", "workspace_id": "wrkspc_1"}
    lock.resources["./skills/b"] = bs.LockEntry(
        kind="skill", id="skill_1", version="skver_1", hash="h1"
    )
    lock.resources["./a.md"] = bs.LockEntry(
        kind="agent", id="agent_1", version="2", hash="h2", remote_hash="r2"
    )
    lock.resources["./env.yaml"] = bs.LockEntry(
        kind="environment", id="env_1", hash="h3", remote_hash="r3"
    )
    assert lock.render() == (
        "{\n"
        '  "version": 1,\n'
        '  "origin": {\n'
        '    "base_url": "https://api.anthropic.com",\n'
        '    "workspace_id": "wrkspc_1"\n'
        "  },\n"
        '  "resources": {\n'
        '    "./a.md": {\n'
        '      "kind": "agent",\n'
        '      "id": "agent_1",\n'
        '      "version": "2",\n'
        '      "hash": "h2",\n'
        '      "remote_hash": "r2"\n'
        "    },\n"
        '    "./env.yaml": {\n'
        '      "kind": "environment",\n'
        '      "id": "env_1",\n'
        '      "hash": "h3",\n'
        '      "remote_hash": "r3"\n'
        "    },\n"
        '    "./skills/b": {\n'
        '      "kind": "skill",\n'
        '      "id": "skill_1",\n'
        '      "version": "skver_1",\n'
        '      "hash": "h1"\n'
        "    }\n"
        "  }\n"
        "}\n"
    )
    lock.save()
    again = bs.Lockfile.load(lock.path)
    assert again.render() == lock.render()
    assert again.existed


def test_lockfile_keeps_fields_written_by_a_newer_ant(tmp_path: Path) -> None:
    path = tmp_path / "claude-lock.json"
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "resources": {
                    "./x.md": {
                        "kind": "agent",
                        "id": "agent_1",
                        "hash": "h",
                        "zeta": 1,
                        "alpha": "a",
                    }
                },
            }
        )
    )
    lock = bs.Lockfile.load(path)
    assert list(lock.resources["./x.md"].to_json()) == ["alpha", "hash", "id", "kind", "zeta"]
    path.write_text(json.dumps({"version": 2, "resources": {}}))
    with pytest.raises(bs.BootstrapError, match="newer ant"):
        bs.Lockfile.load(path)


# --- loading -------------------------------------------------------------------------------------


def load(fake_repo: Path, key_root: Path | None = None) -> bs.Loader:
    loader = bs.Loader(key_root or fake_repo / "backend")
    loader.add_dir(fake_repo / "profiles" / "development")
    return loader


def test_loader_finds_every_resource_with_ant_keys(fake_repo: Path) -> None:
    loader = load(fake_repo)
    assert sorted(loader.sources) == sorted(
        [*SKILL_KEYS, ENVIRONMENT_KEY, COORDINATOR_KEY, *SUBAGENT_KEYS]
    )
    assert {k: s.kind for k, s in loader.sources.items()}[ENVIRONMENT_KEY] == "environment"
    order = loader.topo_order()
    assert order[:3] == SKILL_KEYS
    assert order[3] == ENVIRONMENT_KEY
    assert order[-1] == COORDINATOR_KEY  # subagents first, so the coordinator pins fresh versions


def test_loader_builds_ants_request_bodies(fake_repo: Path) -> None:
    loader = load(fake_repo)
    coordinator = loader.sources[COORDINATOR_KEY].body
    assert coordinator["system"].startswith("# Role")
    assert coordinator["model"] == {"id": "claude-sonnet-5-5", "effort": "medium"}
    tool = coordinator["tools"][1]
    assert (tool["type"], tool["name"]) == ("custom", "submit_plan")
    assert "$ref" not in json.dumps(tool)
    env = loader.sources[ENVIRONMENT_KEY].body
    assert env["config"]["networking"] == {"type": "unrestricted"}
    assert env["name"] == "trip-planner-development"


def test_skill_bundle_skips_tests_caches_dotfiles_and_symlinks(fake_repo: Path) -> None:
    links = fake_repo / "skills" / "booking-links"
    (links / "tests").mkdir()
    (links / "tests" / "data.json").write_text("{}")
    (links / "link.py").symlink_to(links / "build_link.py")
    source = bs.Loader(fake_repo)._load(links, walked=False)
    assert source is not None
    bundle = source.payload
    assert bundle is not None
    assert [f.rel_path for f in bundle.files] == ["SKILL.md", "build_link.py"]
    assert bundle.upload_dir == "booking-links"
    assert next(f.upload_name(bundle.upload_dir) for f in bundle.files) == "booking-links/SKILL.md"


def test_keys_are_relative_to_the_lockfile_directory_like_ant(fake_repo: Path) -> None:
    """ant keys from `filepath.Dir(lockfile)`: `./` beside it, `../` above it."""
    at_root = load(fake_repo, key_root=fake_repo)
    assert "./profiles/development/agents/coordinator.md" in at_root.sources
    assert "./skills/booking-links" in at_root.sources
    nested = load(fake_repo, key_root=fake_repo / "backend" / "locks")
    assert "../../profiles/development/agents/coordinator.md" in nested.sources
    assert "../../skills/booking-links" in nested.sources


def test_the_key_root_option_is_gone() -> None:
    with pytest.raises(SystemExit):
        bs.parse_args(["--profile", "development", "--dry-run", "--key-root", "repo"])


def test_a_lockfile_elsewhere_is_keyed_from_its_own_directory(
    fake_repo: Path, fake_api: FakeAnthropicApi
) -> None:
    path = fake_repo / "claude-lock.json"
    code, out = run(
        fake_repo,
        "--profile",
        "development",
        "--yes",
        "--lock-file",
        str(path),
        client=fake_api.client(),
    )
    assert code == 0, out
    keys = json.loads(path.read_text(encoding="utf-8"))["resources"]
    assert "./profiles/development/agents/coordinator.md" in keys
    assert "./skills/booking-links" in keys


def test_a_data_file_in_a_kind_directory_is_refused(fake_repo: Path) -> None:
    agent = fake_repo / "profiles/development/agents/flights.md"
    agent.write_text(agent.read_text().replace("tools:\n", "tools:\n  - ./extra.json\n", 1))
    (fake_repo / "profiles/development/agents/extra.json").write_text(
        '{"type": "custom", "name": "x"}'
    )
    with pytest.raises(bs.BootstrapError, match="kind directory"):
        load(fake_repo)


# --- the CLI -------------------------------------------------------------------------------------


def test_profile_is_required_and_production_needs_the_flag(fake_repo: Path) -> None:
    with pytest.raises(SystemExit):
        bs.parse_args(["--dry-run"])
    with pytest.raises(SystemExit):
        bs.parse_args(["--profile", "production", "--dry-run"])
    args = bs.parse_args(["--profile", "production", "--i-know-this-is-production", "--dry-run"])
    assert args.production_ok


def test_dry_run_prints_payloads_without_network(
    fake_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import anthropic

    def no_client(*_: Any, **__: Any) -> None:
        raise AssertionError("a dry run must not build a client")

    monkeypatch.setattr(anthropic, "Anthropic", no_client)
    code, out = run(fake_repo, "--profile", "development", "--dry-run")
    assert code == 0
    assert "Plan: 9 to create, 0 to update, 0 unchanged." in out
    assert '"skill_id": "(known after apply)"' in out
    assert "booking-links/SKILL.md" in out
    assert "test_build_link.py" not in out
    assert not (fake_repo / "backend" / "claude-lock.development.json").exists()


def test_stale_profiles_are_refused(fake_repo: Path) -> None:
    (fake_repo / "profiles/development/agents/flights.md").write_text(
        "---\nname: flights\n---\nedited\n"
    )
    code, _ = run(fake_repo, "--profile", "development", "--dry-run")
    assert code == 1


def test_apply_creates_everything_and_writes_the_lockfile(
    fake_repo: Path, fake_api: FakeAnthropicApi
) -> None:
    code, out = run(fake_repo, "--profile", "development", "--yes", client=fake_api.client())
    assert code == 0, out
    writes = fake_api.writes()
    assert [path for _, path, _ in writes] == [
        "/v1/skills",
        "/v1/skills",
        "/v1/skills",
        "/v1/environments",
        "/v1/agents",
        "/v1/agents",
        "/v1/agents",
        "/v1/agents",
        "/v1/agents",
    ]
    assert writes[-1][2]["name"] == "coordinator"

    lock = lockfile(fake_repo)
    assert lock["version"] == 1
    assert all(key.startswith(("../profiles/", "../skills/")) for key in lock["resources"])
    assert lock["origin"] == {
        "base_url": "http://127.0.0.1:9",
        "organization_id": "org_test",
        "workspace_id": "wrkspc_test",
    }
    resources = lock["resources"]
    assert sorted(resources) == sorted(
        [*SKILL_KEYS, ENVIRONMENT_KEY, COORDINATOR_KEY, *SUBAGENT_KEYS]
    )
    for key in SKILL_KEYS:
        assert resources[key]["kind"] == "skill"
        assert resources[key]["version"].startswith("skver_")
        assert "remote_hash" not in resources[key]
    assert resources[ENVIRONMENT_KEY]["id"].startswith("env_")
    assert "version" not in resources[ENVIRONMENT_KEY]
    for key in [COORDINATOR_KEY, *SUBAGENT_KEYS]:
        assert resources[key]["kind"] == "agent"
        assert resources[key]["version"] == "1"
        assert len(resources[key]["hash"]) == 32
        assert len(resources[key]["remote_hash"]) == 32

    coordinator = writes[-1][2]
    pins = coordinator["multiagent"]["subagents"]["predefined_agents"]
    expected_pins = [
        {
            "type": "agent",
            "id": resources[f"{DEV}/agents/{n}.md"]["id"],
            "version": 1,
        }
        for n in ("flights", "lodging", "activities", "transport")
    ]
    assert pins == expected_pins
    assert coordinator["skills"] == [
        {"type": "custom", "skill_id": resources[k]["id"], "version": resources[k]["version"]}
        for k in ("../skills/trip-tracker-schema", "../skills/travel-research-rules")
    ]
    assert coordinator["tools"][1]["name"] == "submit_plan"
    assert coordinator["tools"][2]["name"] == "ask_traveller"
    uploads = fake_api.skill_uploads[resources["../skills/booking-links"]["id"]]
    assert uploads == ["booking-links/SKILL.md", "booking-links/build_link.py"]


def test_lockfile_is_what_the_backend_reads(fake_repo: Path, fake_api: FakeAnthropicApi) -> None:
    assert run(fake_repo, "--profile", "development", "--yes", client=fake_api.client())[0] == 0
    lockfile_module = backend_lockfile_module()
    path = fake_repo / "backend" / "claude-lock.development.json"
    parsed = lockfile_module.Lockfile.model_validate_json(path.read_bytes())
    assert parsed.resources[COORDINATOR_KEY].kind == "agent"
    roster = lockfile_module.resolve_roster(parsed, "development", path=path, sha256="0" * 64)
    assert roster.coordinator.id == parsed.resources[COORDINATOR_KEY].id
    assert lockfile_module.legacy_keys(parsed.resources, path.parent) == []  # no warning
    for name, pin in roster.skills.items():
        assert lockfile_module.skill_version_kind(pin.version) == "version_id", name
        entry = lockfile(fake_repo)["resources"][f"../skills/{name}"]
        assert sorted(entry) == ["hash", "id", "kind", "version"]  # ant's skill entry shape


def test_ant_skill_versions_are_read_by_the_backend_and_are_not_drift(
    fake_repo: Path, fake_api: FakeAnthropicApi
) -> None:
    """ant (Beta skills API) may record epoch strings: same entry shape, other version form."""
    client = fake_api.client()
    assert run(fake_repo, "--profile", "development", "--yes", client=client)[0] == 0
    path = fake_repo / "backend" / "claude-lock.development.json"
    document = lockfile(fake_repo)
    for index, key in enumerate(SKILL_KEYS):
        document["resources"][key]["version"] = f"175917801064112{index}"
    path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")

    lockfile_module = backend_lockfile_module()
    parsed = lockfile_module.Lockfile.model_validate_json(path.read_bytes())
    roster = lockfile_module.resolve_roster(parsed, "development", path=path, sha256="0" * 64)
    assert {lockfile_module.skill_version_kind(p.version) for p in roster.skills.values()} == {
        "epoch"
    }

    fake_api.requests.clear()
    code, out = run(fake_repo, "--profile", "development", "--yes", client=client)
    assert code == 0, out
    assert "BLOCKED" not in out
    assert "Nothing to do." in out
    assert fake_api.writes() == []


def test_a_real_skill_drift_still_blocks(fake_repo: Path, fake_api: FakeAnthropicApi) -> None:
    client = fake_api.client()
    assert run(fake_repo, "--profile", "development", "--yes", client=client)[0] == 0
    skill_id = lockfile(fake_repo)["resources"]["../skills/booking-links"]["id"]
    fake_api.skills[skill_id]["latest_version_id"] = "skver_uploaded_by_hand"
    code, out = run(fake_repo, "--profile", "development", "--yes", client=client)
    assert code == 1
    assert "BLOCKED" in out


def test_legacy_repository_root_keys_are_rewritten_not_duplicated(
    fake_repo: Path, fake_api: FakeAnthropicApi
) -> None:
    client = fake_api.client()
    assert run(fake_repo, "--profile", "development", "--yes", client=client)[0] == 0
    path = fake_repo / "backend" / "claude-lock.development.json"
    current = lockfile(fake_repo)
    path.write_text(json.dumps(legacy_form(current), indent=2) + "\n", encoding="utf-8")

    code, out = run(fake_repo, "--profile", "development", "--dry-run")
    assert code == 0, out
    assert f"rekey  ./profiles/development/agents/coordinator.md -> {COORDINATOR_KEY}" in out
    assert "Plan: 0 to create, 0 to update, 9 unchanged." in out
    assert lockfile(fake_repo) == legacy_form(current)  # a dry run writes nothing

    fake_api.requests.clear()
    code, out = run(fake_repo, "--profile", "development", "--yes", client=client)
    assert code == 0, out
    assert "Nothing to do." in out
    assert fake_api.writes() == []
    assert lockfile(fake_repo) == current  # ant's keys, same ids and versions


def test_second_apply_changes_nothing(fake_repo: Path, fake_api: FakeAnthropicApi) -> None:
    client = fake_api.client()
    assert run(fake_repo, "--profile", "development", "--yes", client=client)[0] == 0
    before = lockfile(fake_repo)
    fake_api.requests.clear()
    code, out = run(fake_repo, "--profile", "development", "--yes", client=client)
    assert code == 0, out
    assert "Nothing to do." in out
    assert fake_api.writes() == []
    assert lockfile(fake_repo) == before


def test_a_subagent_change_repins_the_coordinator(
    fake_repo: Path, fake_api: FakeAnthropicApi
) -> None:
    client = fake_api.client()
    assert run(fake_repo, "--profile", "development", "--yes", client=client)[0] == 0
    template = fake_repo / "agents" / "lodging.md"
    template.write_text(
        template.read_text(encoding="utf-8").replace("# Inputs", "# Inputs\n\nRead carefully.")
    )
    import render_profiles

    render_profiles.write_outputs(fake_repo)
    fake_api.requests.clear()

    code, out = run(fake_repo, "--profile", "development", client=client)
    assert code == 2
    assert "Re-run with --yes" in out
    assert fake_api.writes() == []

    code, out = run(fake_repo, "--profile", "development", "--yes", client=client)
    assert code == 0, out
    lodging_id = lockfile(fake_repo)["resources"][f"{DEV}/agents/lodging.md"]["id"]
    writes = fake_api.writes()
    assert next(path.rsplit("/", 1)[-1] for _, path, _ in writes) == lodging_id
    assert writes[0][2]["version"] == 1  # optimistic concurrency on the version read back
    coordinator_update = writes[1][2]
    assert coordinator_update["name"] == "coordinator"
    lodging_pin = coordinator_update["multiagent"]["subagents"]["predefined_agents"][1]
    assert lodging_pin == {"type": "agent", "id": lodging_id, "version": 2}
    assert len(writes) == 2
    resources = lockfile(fake_repo)["resources"]
    assert resources[f"{DEV}/agents/lodging.md"]["version"] == "2"
    assert resources[COORDINATOR_KEY]["version"] == "2"
    assert resources[f"{DEV}/agents/flights.md"]["version"] == "1"


def test_out_of_band_change_blocks_until_forced(
    fake_repo: Path, fake_api: FakeAnthropicApi
) -> None:
    client = fake_api.client()
    assert run(fake_repo, "--profile", "development", "--yes", client=client)[0] == 0
    flights_id = lockfile(fake_repo)["resources"][f"{DEV}/agents/flights.md"]["id"]
    fake_api.agents[flights_id]["version"] = 7  # someone edited it in the Console
    fake_api.agents[flights_id]["system"] = "changed by hand"
    code, out = run(fake_repo, "--profile", "development", "--yes", client=client)
    assert code == 1
    assert "BLOCKED" in out
    code, out = run(fake_repo, "--profile", "development", "--yes", "--force", client=client)
    assert code == 0, out
    assert lockfile(fake_repo)["resources"][f"{DEV}/agents/flights.md"]["version"] == "8"


def test_another_workspace_is_refused(fake_repo: Path, fake_api: FakeAnthropicApi) -> None:
    client = fake_api.client()
    assert run(fake_repo, "--profile", "development", "--yes", client=client)[0] == 0
    fake_api.workspace = "wrkspc_other"
    code, _ = run(fake_repo, "--profile", "development", "--yes", client=client)
    assert code == 1


def test_deleted_resources_are_not_silently_recreated(
    fake_repo: Path, fake_api: FakeAnthropicApi
) -> None:
    client = fake_api.client()
    assert run(fake_repo, "--profile", "development", "--yes", client=client)[0] == 0
    fake_api.agents.clear()
    fake_api.environments.clear()
    fake_api.skills.clear()
    code, _ = run(fake_repo, "--profile", "development", "--yes", client=client)
    assert code == 1


def test_an_api_error_halfway_keeps_what_was_written(
    fake_repo: Path, fake_api: FakeAnthropicApi, capsys: pytest.CaptureFixture[str]
) -> None:
    original = fake_api.handler

    def failing(request: Any) -> Any:
        if request.method == "POST" and request.url.path == "/v1/agents":
            import httpx2

            return httpx2.Response(
                400,
                json={"type": "error", "error": {"type": "invalid_request_error", "message": "no"}},
            )
        return original(request)

    fake_api.handler = failing  # type: ignore[method-assign]
    code, _ = run(fake_repo, "--profile", "development", "--yes", client=fake_api.client())
    assert code == 1
    assert "the API refused a call (400" in capsys.readouterr().err
    resources = lockfile(fake_repo)["resources"]
    assert sorted(resources) == sorted([*SKILL_KEYS, ENVIRONMENT_KEY])  # saved before the failure
