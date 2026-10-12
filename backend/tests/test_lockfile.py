"""app.lockfile: the ant lockfile format (notes §2h) and the roster of each profile.

The fixtures are keyed the way ant keys backend/claude-lock.<profile>.json: relative to the
lockfile's directory (`../profiles/<profile>/...`, `../skills/<name>`). The development one
records GA skill version ids (`skver_...`, what scripts/bootstrap.py writes), the production
one Beta epoch strings (what ant may write)."""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
import structlog
from structlog.testing import LogCapture
from structlog.typing import EventDict

from app import lockfile as lockfile_module
from app.config import Settings
from app.events import AgentName
from app.lockfile import (
    REQUIRED_AGENTS,
    Lockfile,
    LockfileError,
    key_profile,
    legacy_keys,
    load_roster,
    normalize_key,
    read_lockfile,
    resolve_roster,
    skill_version_kind,
)
from app.ma_client import AgentPin

FIXTURES = Path(__file__).parent / "fixtures" / "lockfile"
DEVELOPMENT_LOCK = FIXTURES / "claude-lock.development.json"
PRODUCTION_LOCK = FIXTURES / "claude-lock.production.json"
SUBAGENTS = ("flights", "lodging", "activities", "transport")
SKILLS = ("booking-links", "travel-research-rules", "trip-tracker-schema")
DEV = "../profiles/development"


def fixture_document(path: Path = DEVELOPMENT_LOCK) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write(tmp_path: Path, document: dict[str, Any], name: str = "claude-lock.json") -> Path:
    path = tmp_path / name
    path.write_text(json.dumps(document, indent=2), encoding="utf-8")
    return path


def resolve(document: dict[str, Any], profile: str = "development") -> Any:
    lockfile = Lockfile.model_validate(document)
    return resolve_roster(lockfile, profile, path=Path("lock.json"), sha256="0" * 64)  # pyright: ignore[reportArgumentType]


@pytest.fixture
def logs(monkeypatch: pytest.MonkeyPatch) -> list[EventDict]:
    """Every log entry of app.lockfile, independent of the global structlog configuration."""
    capture = LogCapture()
    logger = structlog.wrap_logger(
        None,
        processors=[capture],
        wrapper_class=structlog.make_filtering_bound_logger(logging.DEBUG),
    )
    monkeypatch.setattr(lockfile_module, "log", logger)
    return capture.entries


# --- keys ---------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("key", "expected"),
    [
        ("agents/coordinator.md", "./agents/coordinator.md"),
        ("agents\\coordinator.md", "./agents/coordinator.md"),
        ("./agents/coordinator.md", "./agents/coordinator.md"),
        (".//profiles/development/agents/x.md", "./profiles/development/agents/x.md"),
        ("../profiles/production/agents/x.md", "../profiles/production/agents/x.md"),
        ("..\\profiles\\production\\agents\\x.md", "../profiles/production/agents/x.md"),
        ("../profiles/x/../development/./agents/c.md", "../profiles/development/agents/c.md"),
        ("../skills/booking-links/", "../skills/booking-links"),
        ("skills/booking-links/", "./skills/booking-links"),
        (
            "https://github.com/org/repo/tree/main/skills/x",
            "https://github.com/org/repo/tree/main/skills/x",
        ),
    ],
)
def test_normalize_key(key: str, expected: str) -> None:
    assert normalize_key(key) == expected


@pytest.mark.parametrize(
    ("key", "expected"),
    [
        ("./profiles/production/agents/x.md", "production"),
        ("profiles/development/environments/cloud.yaml", "development"),
        ("../profiles/development/agents/coordinator.md", "development"),
        ("./agents/coordinator.md", None),
        ("./skills/booking-links", None),
        ("./profiles/x.md", None),  # `profiles/<name>/` needs a path below the profile
        ("https://example.com/profiles/development/skills/x", None),
    ],
)
def test_key_profile(key: str, expected: str | None) -> None:
    assert key_profile(key) == expected


# --- reading ------------------------------------------------------------------------------------


def test_read_lockfile_parses_the_ant_format() -> None:
    lockfile = read_lockfile(DEVELOPMENT_LOCK)
    assert lockfile.version == 1
    assert lockfile.origin.workspace_id == "wrkspc_development_fixture"
    coordinator = lockfile.resources[f"{DEV}/agents/coordinator.md"]
    assert (coordinator.kind, coordinator.version) == ("agent", "4")
    assert lockfile.resources[f"{DEV}/environments/cloud.yaml"].version is None


@pytest.mark.parametrize("path", [DEVELOPMENT_LOCK, PRODUCTION_LOCK])
def test_fixtures_are_keyed_like_ant_from_backend(path: Path) -> None:
    """`ant apply --lock-file backend/claude-lock.<p>.json profiles/<p>` from the repository
    root keys every file relative to backend/ (anthropic-cli core/lock.go `Root()`)."""
    keys = list(fixture_document(path)["resources"])
    assert keys
    assert all(key.startswith(("../profiles/", "../skills/")) for key in keys), keys
    assert keys == sorted(keys)  # Go's encoding/json sorts map keys


def test_missing_lockfile_is_a_lockfile_error(tmp_path: Path) -> None:
    with pytest.raises(LockfileError, match="does not exist"):
        read_lockfile(tmp_path / "claude-lock.development.json")


@pytest.mark.parametrize(
    ("content", "match"),
    [
        ("{not json", "not valid JSON"),
        ("[1, 2]", "not a JSON object"),
        ('{"version": 2, "origin": {}, "resources": {}}', "version 2"),
        ('{"version": true, "origin": {}, "resources": {}}', "version True"),
        ('{"version": 1, "origin": {}}', "no `resources`"),
        ('{"version": 1, "resources": {"./a.md": {"kind": "agent"}}}', "expected shape"),
    ],
)
def test_malformed_lockfiles_are_lockfile_errors(tmp_path: Path, content: str, match: str) -> None:
    path = tmp_path / "claude-lock.json"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(LockfileError, match=match):
        read_lockfile(path)


def test_missing_origin_and_integer_versions_are_accepted(tmp_path: Path) -> None:
    document = fixture_document()
    del document["origin"]
    document["resources"][f"{DEV}/agents/coordinator.md"]["version"] = 7
    lockfile = read_lockfile(write(tmp_path, document))
    assert lockfile.origin.workspace_id is None
    roster = resolve_roster(lockfile, "development", path=tmp_path, sha256="x")
    assert roster.coordinator.version == 7
    assert roster.workspace_id is None


def test_unknown_keys_written_by_a_newer_ant_are_kept(tmp_path: Path) -> None:
    document = fixture_document()
    document["generator"] = "ant 1.41"
    document["resources"]["../skills/booking-links"]["revision"] = "abc"
    lockfile = read_lockfile(write(tmp_path, document))
    assert lockfile.model_extra == {"generator": "ant 1.41"}
    assert lockfile.resources["../skills/booking-links"].model_extra == {"revision": "abc"}


# --- resolving ----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("profile", "path", "prefix", "coordinator_version", "skill_version_kind_"),
    [
        ("development", DEVELOPMENT_LOCK, "dev", 4, "version_id"),
        ("production", PRODUCTION_LOCK, "pro", 4, "epoch"),
    ],
)
def test_load_roster_for_each_profile(
    make_settings: Callable[..., Settings],
    logs: list[EventDict],
    profile: str,
    path: Path,
    prefix: str,
    coordinator_version: int,
    skill_version_kind_: str,
) -> None:
    settings = make_settings(agent_profile=profile, lockfile_path=path)
    roster = load_roster(settings)
    assert roster.profile == profile
    assert roster.coordinator == AgentPin(
        id=f"agent_{prefix}coordinator0{1 if profile == 'development' else 2}",
        version=coordinator_version,
    )
    assert set(roster.subagents) == {AgentName(name) for name in SUBAGENTS}
    assert AgentName.COORDINATOR not in roster.subagents
    assert roster.environment_id.startswith(f"env_{prefix}cloud")
    assert sorted(roster.skills) == list(SKILLS)
    assert {skill_version_kind(pin.version) for pin in roster.skills.values()} == {
        skill_version_kind_
    }
    assert roster.lockfile_path == path
    assert roster.lockfile_sha256 == hashlib.sha256(path.read_bytes()).hexdigest()
    assert roster.workspace_id == f"wrkspc_{profile}_fixture"
    assert logs == []  # ant's keys, recognized skill versions: nothing to warn about


def test_roster_is_immutable() -> None:
    roster = resolve(fixture_document())
    with pytest.raises(TypeError):
        roster.subagents[AgentName.FLIGHTS] = AgentPin(id="agent_x", version=1)  # pyright: ignore[reportIndexIssue]
    with pytest.raises(AttributeError):
        roster.environment_id = "env_other"  # pyright: ignore[reportAttributeAccessIssue]


def test_lockfile_of_the_other_profile_fails_loudly(make_settings: Callable[..., Settings]) -> None:
    settings = make_settings(agent_profile="production", lockfile_path=DEVELOPMENT_LOCK)
    with pytest.raises(LockfileError) as caught:
        load_roster(settings)
    message = str(caught.value)
    assert "applied for another profile" in message
    assert str(DEVELOPMENT_LOCK) in message
    assert "agent_dev" not in message  # never another workspace's resource ids


def test_two_profile_lockfile_resolves_each_profile_from_its_own_keys() -> None:
    merged = fixture_document()
    merged["resources"].update(fixture_document(PRODUCTION_LOCK)["resources"])
    # An unprofiled agent left over from a flat tree is ignored in a two-profile lockfile.
    merged["resources"]["./agents/coordinator.md"] = {
        "kind": "agent",
        "id": "agent_flat",
        "version": "1",
    }
    development = resolve(merged, "development")
    production = resolve(merged, "production")
    assert development.coordinator.id == "agent_devcoordinator01"
    assert production.coordinator.id == "agent_procoordinator02"
    assert development.environment_id != production.environment_id
    assert development.skills == production.skills  # shared, never profiled


def test_single_profile_lockfile_uses_every_key() -> None:
    document = fixture_document()
    flat = {key.replace(f"{DEV}/", "./"): value for key, value in document["resources"].items()}
    document["resources"] = flat
    for profile in ("development", "production"):
        roster = resolve(document, profile)
        assert roster.coordinator.id == "agent_devcoordinator01"
        assert roster.profile == profile


def test_legacy_repository_root_keys_still_resolve() -> None:
    """The first bootstrap.py keyed from the repository root (`./profiles/...`)."""
    document = fixture_document()
    document["resources"] = {
        key.replace("../", "./", 1): value for key, value in document["resources"].items()
    }
    roster = resolve(document)
    assert roster.coordinator.id == "agent_devcoordinator01"
    assert sorted(roster.skills) == list(SKILLS)
    assert roster.agent_versions(git_sha=None, trip_schema_sha256=None) == resolve(
        fixture_document()
    ).agent_versions(git_sha=None, trip_schema_sha256=None)


def test_legacy_keys_are_only_those_without_a_directory_beside_the_lockfile(
    tmp_path: Path,
) -> None:
    keys = [
        "./profiles/development/agents/coordinator.md",
        "profiles\\development\\agents\\flights.md",
        "./skills/booking-links/",
        "../profiles/development/agents/lodging.md",
        "../skills/trip-tracker-schema",
        "./agents/coordinator.md",  # a flat tree, not the old bootstrap form
        "./profiles",
        "https://github.com/org/repo/tree/main/skills/x",
    ]
    assert legacy_keys(keys, tmp_path) == [
        "./profiles/development/agents/coordinator.md",
        "./profiles/development/agents/flights.md",
        "./skills/booking-links",
    ]
    # A lockfile kept next to profiles/ and skills/ (the evals scratch apply): ant's own keys.
    (tmp_path / "profiles").mkdir()
    (tmp_path / "skills").mkdir()
    assert legacy_keys(keys, tmp_path) == []


def test_load_roster_warns_about_legacy_keys(
    make_settings: Callable[..., Settings], tmp_path: Path, logs: list[EventDict]
) -> None:
    document = fixture_document()
    document["resources"] = {
        key.replace("../", "./", 1): value for key, value in document["resources"].items()
    }
    path = write(tmp_path, document, "claude-lock.development.json")
    roster = load_roster(make_settings(lockfile_path=path))
    assert roster.coordinator.id == "agent_devcoordinator01"
    [entry] = logs
    assert entry["event"] == "lockfile_legacy_keys"
    assert entry["log_level"] == "warning"
    assert entry["count"] == len(document["resources"])
    assert entry["example"] == "./profiles/development/agents/activities.md"
    assert entry["expected"] == "../profiles/development/agents/activities.md"
    assert "agent_dev" not in json.dumps(entry)  # never resource ids


def test_every_problem_is_listed_at_once() -> None:
    document = fixture_document()
    resources = document["resources"]
    del resources[f"{DEV}/agents/flights.md"]
    resources[f"{DEV}/agents/lodging.md"]["version"] = "latest"
    resources[f"{DEV}/environments/other.yaml"] = {
        "kind": "environment",
        "id": "env_other",
    }
    resources[f"{DEV}/agents/team/transport.md"] = {
        "kind": "agent",
        "id": "agent_dup",
        "version": "1",
    }
    resources["../skills/booking-links"]["version"] = "not a version"
    with pytest.raises(LockfileError) as caught:
        resolve(document)
    message = str(caught.value)
    assert "agent 'flights': no `kind: agent` entry" in message
    assert "../profiles/development/agents/flights.md, relative to the lockfile's" in message
    assert "agent 'lodging'" in message
    assert "'latest'" in message
    assert "agent 'transport': 2 entries match" in message
    assert "environment: 2 entries match" in message
    assert "skill" not in message  # a skill version never blocks
    assert "env_other" not in message
    assert "agent_dup" not in message


def test_missing_environment_is_reported() -> None:
    document = fixture_document()
    del document["resources"][f"{DEV}/environments/cloud.yaml"]
    with pytest.raises(LockfileError, match="environment: no `kind: environment` entry"):
        resolve(document)


@pytest.mark.parametrize(
    ("version", "expected"),
    [
        ("skver_01JABCDEF", "version_id"),  # GA skills API (bootstrap.py)
        ("1759178010641129", "epoch"),  # Beta skills API (ant)
        ("latest", "other"),
        ("v2.1", "other"),
        ("skver_", "other"),
        ("", "invalid"),
        (None, "invalid"),
        (3, "invalid"),
        ("two words", "invalid"),
        ("line\nbreak", "invalid"),
        ("nul\u0000", "invalid"),
        ("x" * 129, "invalid"),
    ],
)
def test_skill_version_kind(version: object, expected: str) -> None:
    assert skill_version_kind(version) == expected


@pytest.mark.parametrize(
    ("raw", "recorded", "warned"),
    [
        ("skver_bookinglinks09", "skver_bookinglinks09", None),
        ("1759178010641129", "1759178010641129", None),
        (1759178010641129, "1759178010641129", None),  # a number: ant writes strings
        ("latest", "latest", "other"),
        ("bad version", None, "invalid"),
        ("x" * 300, None, "invalid"),
        (1.5, None, "invalid"),
        ({"id": "skver_1"}, None, "invalid"),
        (True, None, "invalid"),
        (None, None, "invalid"),
        ("", None, "invalid"),
    ],
)
def test_a_skill_version_never_makes_the_planner_unavailable(
    make_settings: Callable[..., Settings],
    tmp_path: Path,
    logs: list[EventDict],
    raw: object,
    recorded: str | None,
    warned: str | None,
) -> None:
    document = fixture_document()
    document["resources"]["../skills/booking-links"]["version"] = raw
    path = write(tmp_path, document, "claude-lock.development.json")
    roster = load_roster(make_settings(lockfile_path=path))
    assert roster.skills["booking-links"].version == recorded
    versions = roster.agent_versions(git_sha=None, trip_schema_sha256=None)
    assert versions["skills"]["booking-links"] == {
        "id": "skill_bookinglinks01",
        "version": recorded,
    }
    json.dumps(versions)
    if warned is None:
        assert logs == []
    else:
        [entry] = logs
        assert entry["event"] == "lockfile_skill_version_unrecognized"
        assert entry["skills"] == {"booking-links": warned}


def test_a_missing_skill_version_key_never_blocks(
    make_settings: Callable[..., Settings], tmp_path: Path, logs: list[EventDict]
) -> None:
    document = fixture_document()
    del document["resources"]["../skills/trip-tracker-schema"]["version"]
    path = write(tmp_path, document, "claude-lock.development.json")
    roster = load_roster(make_settings(lockfile_path=path))
    assert roster.skills["trip-tracker-schema"].version is None
    assert [entry["event"] for entry in logs] == ["lockfile_skill_version_unrecognized"]


def test_other_kinds_and_unknown_agents_are_ignored() -> None:
    document = fixture_document()
    document["resources"][f"{DEV}/agents/reviewer.md"] = {
        "kind": "agent",
        "id": "agent_reviewer",
        "version": "1",
    }
    document["resources"][f"{DEV}/memory_stores/notes.yaml"] = {
        "kind": "memory_store",
        "id": "memstore_1",
    }
    roster = resolve(document)
    assert {pin.id for pin in roster.subagents.values()} == {
        f"agent_dev{name}01" for name in SUBAGENTS
    }


def test_agent_versions_json_for_plans() -> None:
    roster = resolve(fixture_document())
    versions = roster.agent_versions(git_sha="abc123", trip_schema_sha256="f" * 64)
    assert versions == {
        "profile": "development",
        "coordinator": {"id": "agent_devcoordinator01", "version": 4},
        "subagents": {name: {"id": f"agent_dev{name}01", "version": 2} for name in SUBAGENTS},
        "skills": {
            name: {
                "id": f"skill_{name.replace('-', '')}01",
                "version": f"skver_{name.replace('-', '')}01",
            }
            for name in SKILLS
        },
        "environment_id": "env_devcloud01",
        "lockfile_sha256": "0" * 64,
        "trip_schema_sha256": "f" * 64,
        "git_sha": "abc123",
    }
    assert list(versions["subagents"]) == [name.value for name in REQUIRED_AGENTS[1:]]
    json.dumps(versions)  # stored as jsonb


def test_agent_versions_allow_unknown_sha() -> None:
    versions = resolve(fixture_document()).agent_versions(git_sha=None, trip_schema_sha256=None)
    assert versions["git_sha"] is None
    assert versions["trip_schema_sha256"] is None
