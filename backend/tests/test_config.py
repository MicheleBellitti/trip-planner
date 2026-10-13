from collections.abc import Callable
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.config import (
    BACKEND_DIR,
    Settings,
    default_lockfile_path,
    get_settings,
    normalize_database_url,
)

MakeSettings = Callable[..., Settings]

ALL_VARIABLES = (
    "ENVIRONMENT",
    "AUTH_MODE",
    "ANTHROPIC_API_KEY",
    "DATABASE_URL",
    "AGENT_PROFILE",
    "SESSION_BUDGET_CENTS",
    "MONTHLY_LIMIT_CENTS",
    "PLANNER_ALLOWED_EMAILS",
    "FRONTEND_ORIGIN",
    "TRIPTRACKER_ORIGIN",
    "LOCKFILE_PATH",
    "TRIP_SCHEMA_URL",
    "LOG_LEVEL",
    "GIT_SHA",
    "EVALS_INGEST_TOKEN",
    "RAILWAY_GIT_COMMIT_SHA",
)


@pytest.fixture
def bare_env(monkeypatch: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    """No backend variable set: only what a test sets explicitly."""
    for name in ALL_VARIABLES:
        monkeypatch.delenv(name, raising=False)
    return monkeypatch


# --- environment and auth mode ----------------------------------------------------------------


def test_local_auth_is_refused_in_production(make_settings: MakeSettings) -> None:
    with pytest.raises(ValidationError, match="AUTH_MODE=local is only allowed"):
        make_settings(environment="production", auth_mode="local", anthropic_api_key="sk-test")


def test_local_auth_is_refused_when_environment_is_unset(bare_env: pytest.MonkeyPatch) -> None:
    bare_env.setenv("DATABASE_URL", "postgresql://localhost/trip_planner_dev")
    bare_env.setenv("ANTHROPIC_API_KEY", "sk-test")
    bare_env.setenv("AUTH_MODE", "local")
    bare_env.setenv("PLANNER_ALLOWED_EMAILS", "me@example.com")

    with pytest.raises(ValidationError, match="AUTH_MODE=local is only allowed"):
        Settings(_env_file=None)  # pyright: ignore[reportCallIssue]


def test_local_auth_is_allowed_in_development(make_settings: MakeSettings) -> None:
    settings = make_settings(planner_allowed_emails="Me@Example.com, other@example.com")

    assert settings.auth_mode == "local"
    assert settings.local_user_email == "me@example.com"


def test_local_auth_needs_an_allowed_email(make_settings: MakeSettings) -> None:
    with pytest.raises(ValidationError, match="needs PLANNER_ALLOWED_EMAILS"):
        make_settings(planner_allowed_emails="")


def test_defaults_are_production_safe(bare_env: pytest.MonkeyPatch) -> None:
    bare_env.setenv("DATABASE_URL", "postgresql://db.internal:5432/railway")
    bare_env.setenv("ANTHROPIC_API_KEY", "sk-test")
    bare_env.setenv("AGENT_PROFILE", "production")

    settings = Settings(_env_file=None)  # pyright: ignore[reportCallIssue]

    assert settings.environment == "production"
    assert settings.is_production
    assert settings.auth_mode == "triptracker"
    assert settings.local_user_email is None
    assert settings.agent_profile == "production"
    assert settings.session_budget_cents == 400
    assert settings.monthly_limit_cents == 5000
    assert settings.planner_allowed_emails == []
    assert settings.frontend_origin == "https://atlas.bellittim.com"
    assert settings.triptracker_origin == "https://viaggi.bellittim.com"
    assert settings.trip_schema_url == "https://viaggi.bellittim.com/schema/trip.json"
    assert settings.lockfile_path == BACKEND_DIR / "claude-lock.production.json"
    assert settings.git_sha is None
    assert settings.log_level == "INFO"


def test_production_needs_an_explicit_agent_profile(bare_env: pytest.MonkeyPatch) -> None:
    bare_env.setenv("DATABASE_URL", "postgresql://db.internal:5432/railway")
    bare_env.setenv("ANTHROPIC_API_KEY", "sk-test")

    with pytest.raises(ValidationError, match="AGENT_PROFILE must be set explicitly"):
        Settings(_env_file=None)  # pyright: ignore[reportCallIssue]


def test_development_may_leave_the_agent_profile_unset(bare_env: pytest.MonkeyPatch) -> None:
    bare_env.setenv("DATABASE_URL", "postgresql://localhost:5432/trip_planner_dev")
    bare_env.setenv("ENVIRONMENT", "development")

    settings = Settings(_env_file=None)  # pyright: ignore[reportCallIssue]

    assert settings.agent_profile == "development"
    assert settings.session_budget_cents == 100
    assert settings.lockfile_path == BACKEND_DIR / "claude-lock.development.json"


@pytest.mark.parametrize(("profile", "budget"), [("development", 100), ("production", 400)])
@pytest.mark.parametrize("raw", [None, "", "  "])
def test_session_budget_defaults_per_profile(
    make_settings: MakeSettings, profile: str, budget: int, raw: str | None
) -> None:
    settings = make_settings(agent_profile=profile, session_budget_cents=raw)

    assert settings.session_budget_cents == budget


def test_session_budget_can_be_overridden(make_settings: MakeSettings) -> None:
    assert (
        make_settings(agent_profile="production", session_budget_cents="250").session_budget_cents
        == 250
    )


def test_production_requires_the_api_key(make_settings: MakeSettings) -> None:
    with pytest.raises(ValidationError, match="ANTHROPIC_API_KEY is required"):
        make_settings(environment="production", auth_mode="triptracker", anthropic_api_key="")


def test_database_url_is_required(bare_env: pytest.MonkeyPatch) -> None:
    bare_env.setenv("ENVIRONMENT", "development")

    with pytest.raises(ValidationError, match="database_url"):
        Settings(_env_file=None)  # pyright: ignore[reportCallIssue]


@pytest.mark.parametrize("name", ["environment", "agent_profile", "auth_mode"])
def test_enumerated_values_are_checked(make_settings: MakeSettings, name: str) -> None:
    with pytest.raises(ValidationError):
        make_settings(**{name: "staging"})


# --- DATABASE_URL -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (
            "postgres://user:secret@db.railway.internal:5432/railway",
            "postgresql+asyncpg://user:secret@db.railway.internal:5432/railway",
        ),
        (
            "postgresql://user:secret@localhost:5432/trip_planner_dev",
            "postgresql+asyncpg://user:secret@localhost:5432/trip_planner_dev",
        ),
        (
            "postgresql+asyncpg://localhost:5432/trip_planner_dev",
            "postgresql+asyncpg://localhost:5432/trip_planner_dev",
        ),
        (
            "postgresql://user:secret@host:5432/db?sslmode=require",
            "postgresql+asyncpg://user:secret@host:5432/db?ssl=require",
        ),
        ("  postgres://localhost/db  ", "postgresql+asyncpg://localhost/db"),
    ],
)
def test_database_url_is_normalized_to_asyncpg(
    make_settings: MakeSettings, raw: str, expected: str
) -> None:
    assert normalize_database_url(raw) == expected
    assert make_settings(database_url=raw).database_url.get_secret_value() == expected


def test_database_url_from_the_environment_is_normalized(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgres://u:p@railway:5432/railway")
    settings = Settings(_env_file=None)  # pyright: ignore[reportCallIssue]

    assert (
        settings.database_url.get_secret_value() == "postgresql+asyncpg://u:p@railway:5432/railway"
    )


@pytest.mark.parametrize("raw", ["mysql://localhost/db", "sqlite:///trip.db", "localhost:5432"])
def test_non_postgres_database_url_is_rejected(make_settings: MakeSettings, raw: str) -> None:
    with pytest.raises(ValidationError, match="must be a PostgreSQL URL"):
        make_settings(database_url=raw)


# --- PLANNER_ALLOWED_EMAILS -------------------------------------------------------------------


@pytest.mark.parametrize("raw", ["", " ", ",", " , ,"])
def test_empty_allowlist_means_nobody(make_settings: MakeSettings, raw: str) -> None:
    settings = make_settings(auth_mode="triptracker", planner_allowed_emails=raw)

    assert settings.planner_allowed_emails == []
    assert not settings.is_email_allowed("test@example.com")
    assert not settings.is_email_allowed("")
    assert not settings.is_email_allowed(None)


def test_allowlist_is_a_comma_list_read_from_the_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PLANNER_ALLOWED_EMAILS", " Michele@Example.com,friend@example.com ,, ")
    settings = Settings(_env_file=None)  # pyright: ignore[reportCallIssue]

    assert settings.planner_allowed_emails == ["michele@example.com", "friend@example.com"]
    assert settings.is_email_allowed("MICHELE@example.com ")
    assert settings.is_email_allowed("friend@example.com")
    assert not settings.is_email_allowed("someone@example.com")


# --- origins, schema URL, lockfile, log level -------------------------------------------------


def test_origins_lose_the_trailing_slash(make_settings: MakeSettings) -> None:
    settings = make_settings(
        frontend_origin="http://localhost:3000/", triptracker_origin="https://Viaggi.Bellittim.com/"
    )

    assert settings.frontend_origin == "http://localhost:3000"
    assert settings.triptracker_origin == "https://viaggi.bellittim.com"


@pytest.mark.parametrize(
    "origin", ["atlas.bellittim.com", "ftp://host", "https://host/path", "https://host?x=1"]
)
def test_invalid_origins_are_rejected(make_settings: MakeSettings, origin: str) -> None:
    with pytest.raises(ValidationError, match="origin"):
        make_settings(frontend_origin=origin)


def test_trip_schema_url_follows_the_triptracker_origin(make_settings: MakeSettings) -> None:
    settings = make_settings(triptracker_origin="http://localhost:3001", trip_schema_url="")

    assert settings.trip_schema_url == "http://localhost:3001/schema/trip.json"


def test_trip_schema_url_can_be_overridden(make_settings: MakeSettings) -> None:
    settings = make_settings(trip_schema_url="https://cdn.example.com/trip.json")

    assert settings.trip_schema_url == "https://cdn.example.com/trip.json"


@pytest.mark.parametrize("profile", ["development", "production"])
def test_lockfile_defaults_to_the_profiles_file_inside_backend(
    make_settings: MakeSettings, profile: str
) -> None:
    settings = make_settings(agent_profile=profile, lockfile_path="")

    assert settings.lockfile_path == default_lockfile_path(profile)  # pyright: ignore[reportArgumentType]
    assert settings.lockfile_path.name == f"claude-lock.{profile}.json"
    # Railway deploys the root directory backend/ only: the lockfile must live inside it.
    assert (settings.lockfile_path.parent / "pyproject.toml").is_file()


def test_lockfile_path_can_be_overridden(make_settings: MakeSettings, tmp_path: Path) -> None:
    lockfile = tmp_path / "claude-lock.json"

    assert make_settings(lockfile_path=str(lockfile)).lockfile_path == lockfile


def test_blank_lockfile_path_means_the_default(make_settings: MakeSettings) -> None:
    assert make_settings(lockfile_path="").lockfile_path == default_lockfile_path("development")


def test_example_env_file_is_valid(bare_env: pytest.MonkeyPatch) -> None:
    example = Path(__file__).resolve().parents[1] / ".env.example"

    settings = Settings(_env_file=example)  # pyright: ignore[reportCallIssue]

    assert settings.environment == "development"
    assert settings.auth_mode == "local"
    assert settings.lockfile_path == default_lockfile_path("development")
    assert settings.session_budget_cents == 100
    assert settings.trip_schema_url == "https://viaggi.bellittim.com/schema/trip.json"
    assert settings.anthropic_api_key is None
    assert settings.git_sha is None


def test_log_level_is_case_insensitive(make_settings: MakeSettings) -> None:
    assert make_settings(log_level="debug").log_level == "DEBUG"


# --- git sha ----------------------------------------------------------------------------------


def test_git_sha_comes_from_railway(bare_env: pytest.MonkeyPatch) -> None:
    bare_env.setenv("DATABASE_URL", "postgresql://localhost:5432/trip_planner_dev")
    bare_env.setenv("ENVIRONMENT", "development")
    bare_env.setenv("RAILWAY_GIT_COMMIT_SHA", "0123abc")

    assert Settings(_env_file=None).git_sha == "0123abc"  # pyright: ignore[reportCallIssue]


def test_git_sha_wins_over_railway(bare_env: pytest.MonkeyPatch) -> None:
    bare_env.setenv("DATABASE_URL", "postgresql://localhost:5432/trip_planner_dev")
    bare_env.setenv("ENVIRONMENT", "development")
    bare_env.setenv("GIT_SHA", "fedcba9")
    bare_env.setenv("RAILWAY_GIT_COMMIT_SHA", "0123abc")

    assert Settings(_env_file=None).git_sha == "fedcba9"  # pyright: ignore[reportCallIssue]


@pytest.mark.parametrize("raw", ["", "  "])
def test_blank_git_sha_counts_as_missing(make_settings: MakeSettings, raw: str) -> None:
    assert make_settings(git_sha=raw).git_sha is None


# --- secrets ----------------------------------------------------------------------------------


def test_secrets_never_appear_in_reprs_or_dumps(make_settings: MakeSettings) -> None:
    settings = make_settings(
        anthropic_api_key="sk-ant-super-secret",
        database_url="postgres://planner:db-password@db:5432/railway",
    )

    for rendered in (repr(settings), str(settings), settings.model_dump_json()):
        assert "sk-ant-super-secret" not in rendered
        assert "db-password" not in rendered
    assert settings.anthropic_api_key is not None
    assert settings.anthropic_api_key.get_secret_value() == "sk-ant-super-secret"


def test_blank_api_key_counts_as_missing(make_settings: MakeSettings) -> None:
    assert make_settings(anthropic_api_key="  ").anthropic_api_key is None


# --- get_settings -----------------------------------------------------------------------------


def test_get_settings_is_cached(settings: Settings) -> None:
    assert get_settings() is settings
    assert get_settings() is get_settings()


def test_test_settings_match_the_test_environment(settings: Settings) -> None:
    assert settings.environment == "development"
    assert settings.auth_mode == "local"
    assert settings.local_user_email == "test@example.com"
    assert settings.frontend_origin == "https://atlas.bellittim.com"
    assert settings.triptracker_origin == "https://viaggi.bellittim.com"
    assert settings.anthropic_api_key is None


# --- EVALS_INGEST_TOKEN -----------------------------------------------------------------------


def test_the_eval_upload_is_disabled_by_default(make_settings: MakeSettings) -> None:
    for settings in (
        make_settings(),
        make_settings(evals_ingest_token=""),
        make_settings(evals_ingest_token="  "),
    ):
        assert settings.evals_ingest_enabled is False
        assert settings.evals_ingest_token.get_secret_value() == ""


def test_the_eval_upload_token_is_trimmed_and_never_shown(make_settings: MakeSettings) -> None:
    settings = make_settings(evals_ingest_token="  s3cret-token \n")

    assert settings.evals_ingest_enabled is True
    assert settings.evals_ingest_token.get_secret_value() == "s3cret-token"
    assert "s3cret-token" not in repr(settings)
    assert "s3cret-token" not in str(settings.model_dump())


def test_the_eval_upload_token_is_read_from_the_environment(
    bare_env: pytest.MonkeyPatch,
) -> None:
    bare_env.setenv("DATABASE_URL", "postgresql://localhost/x")
    bare_env.setenv("ENVIRONMENT", "development")
    bare_env.setenv("EVALS_INGEST_TOKEN", "from-env")

    assert Settings(_env_file=None).evals_ingest_token.get_secret_value() == "from-env"  # pyright: ignore[reportCallIssue]


def test_log_lines_carry_the_event_as_message_for_railway() -> None:
    """Railway shows a JSON line's `message`: without it every line of ours is blank there."""
    from app.config import add_message_key

    line = add_message_key(None, "info", {"event": "session_create_failed", "status_code": 404})
    assert line["message"] == "session_create_failed"
    assert line["event"] == "session_create_failed"
    kept = add_message_key(None, "info", {"event": "x", "message": "already set"})
    assert kept["message"] == "already set"
