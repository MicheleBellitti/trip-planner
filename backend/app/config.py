"""Backend settings, read from the environment and, locally, from backend/.env.

Every variable of the Railway table in the implementation doc lives here, plus ENVIRONMENT,
AUTH_MODE, LOCKFILE_PATH, TRIP_SCHEMA_URL, LOG_LEVEL, the backend's git sha (GIT_SHA or
Railway's RAILWAY_GIT_COMMIT_SHA), EVALS_INGEST_TOKEN (the eval upload endpoint) and the local
demo's DEMO_MODE and DEMO_PACE (development only: Settings refuses them in production).
Defaults are the production-safe choice (ENVIRONMENT=production, AUTH_MODE=triptracker).
AGENT_PROFILE defaults to the cheap development roster, but production refuses to start unless
it is set explicitly; SESSION_BUDGET_CENTS and LOCKFILE_PATH default per profile. Secrets are
`SecretStr`, so they never show up in reprs, logs or tracebacks.

Everything the backend reads at runtime lives inside backend/: Railway deploys the service from
the root directory `backend/` and pulls only that directory, so the lockfiles are
backend/claude-lock.<profile>.json (written there by `ant apply --lock-file`), and a pinned
`TRIP_SCHEMA_URL=file://...` copy must also live under backend/.
"""

from __future__ import annotations

from collections.abc import Mapping, MutableMapping
from functools import lru_cache
from pathlib import Path
from types import MappingProxyType
from typing import Annotated, Any, Literal, Self, cast
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from pydantic import (
    AliasChoices,
    Field,
    SecretStr,
    ValidationInfo,
    field_validator,
    model_validator,
)
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[1]
TRIP_SCHEMA_PATH = "/schema/trip.json"

Environment = Literal["development", "production"]
AgentProfile = Literal["development", "production"]
AuthMode = Literal["triptracker", "local"]
LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]

PLAN_LOG_KEYS: tuple[str, ...] = ("plan_id", "session_id", "agent", "event_type")
"""Keys on every log line (spec "Log e resilienza"; CLAUDE.md "Secrets, auth, config")."""


def add_plan_log_keys(
    _logger: object, _method_name: str, event_dict: MutableMapping[str, Any]
) -> MutableMapping[str, Any]:
    """structlog processor, placed right after `merge_contextvars`: every `PLAN_LOG_KEYS` key
    is present on every line, None when neither the call nor the context bound it. Explicit
    keyword arguments win over context-bound values, which win over the None default."""
    for key in PLAN_LOG_KEYS:
        event_dict.setdefault(key, None)
    return event_dict


DEFAULT_AGENT_PROFILE: AgentProfile = "development"

DEFAULT_DEMO_PACE = 1.0
"""DEMO_PACE unset: the scenarios' recorded pace."""

DEFAULT_SESSION_BUDGET_CENTS: Mapping[AgentProfile, int] = MappingProxyType(
    {"production": 400, "development": 100}
)
"""Spec "Tre livelli di controllo": `max_list_cost` "400" ($4) in production. Development was the
spec's "60", raised to 100 on 2026-10-12: all five development evals paused at 60 before
finishing, and the estimate after the cost cuts is ~55-85 (docs/managed-agents-notes.md §5)."""


def default_lockfile_path(profile: AgentProfile) -> Path:
    """backend/claude-lock.<profile>.json: one lockfile per profile (a lockfile is bound to one
    workspace, notes §2h), inside backend/ so that Railway ships it with the service."""
    return BACKEND_DIR / f"claude-lock.{profile}.json"


def _is_blank(value: object) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _profile_of(value: object) -> AgentProfile:
    """The profile a raw AGENT_PROFILE value selects, for the per-profile defaults only; an
    invalid value falls back to the default here and is reported by the field's validation."""
    text = value.strip().lower() if isinstance(value, str) else ""
    if text in DEFAULT_SESSION_BUDGET_CENTS:
        return cast(AgentProfile, text)
    return DEFAULT_AGENT_PROFILE


_POSTGRES_SCHEMES = {"postgres", "postgresql", "postgresql+asyncpg"}
_ASYNC_POSTGRES_SCHEME = "postgresql+asyncpg"


def normalize_database_url(url: str) -> str:
    """Return a SQLAlchemy URL that uses the asyncpg driver.

    Railway (and most hosts) hand out `postgres://` or `postgresql://` URLs; SQLAlchemy's async
    engine needs `postgresql+asyncpg://`. libpq's `sslmode` query parameter is renamed to the
    `ssl` parameter that asyncpg understands.
    """
    url = url.strip()
    parts = urlsplit(url)
    scheme = parts.scheme.lower()
    if scheme not in _POSTGRES_SCHEMES:
        msg = f"DATABASE_URL must be a PostgreSQL URL, got scheme {parts.scheme!r}"
        raise ValueError(msg)
    query = [("ssl" if key == "sslmode" else key, value) for key, value in parse_qsl(parts.query)]
    return urlunsplit(
        (_ASYNC_POSTGRES_SCHEME, parts.netloc, parts.path, urlencode(query), parts.fragment)
    )


def normalize_origin(origin: str) -> str:
    """Validate a browser origin (`scheme://host[:port]`) and drop any trailing slash."""
    value = origin.strip().rstrip("/")
    parts = urlsplit(value)
    if parts.scheme not in {"http", "https"} or not parts.netloc:
        msg = f"origin must look like https://host[:port], got {origin!r}"
        raise ValueError(msg)
    if parts.path or parts.query or parts.fragment:
        msg = f"origin must not contain a path, query or fragment, got {origin!r}"
        raise ValueError(msg)
    return f"{parts.scheme}://{parts.netloc.lower()}"


class Settings(BaseSettings):
    """All backend configuration. Construct through `get_settings()` in application code."""

    model_config = SettingsConfigDict(
        env_file=BACKEND_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # Where the process runs. Defaults to production so a forgotten variable never relaxes a check.
    environment: Environment = "production"

    # Anthropic API key: production key on Railway, development key locally. Never logged.
    anthropic_api_key: SecretStr | None = None

    # Anthropic Workload Identity Federation (CI evals, development only; docs/deploy.md). With no
    # API key the SDK exchanges the identity token itself, reading these same variables from the
    # process environment: Settings only decides whether credentials exist. Never logged.
    anthropic_identity_token_file: str | None = None
    anthropic_identity_token: SecretStr | None = None
    anthropic_federation_rule_id: str | None = None
    anthropic_organization_id: str | None = None
    anthropic_workspace_id: str | None = None

    # PostgreSQL URL; postgres:// and postgresql:// are normalized to postgresql+asyncpg://.
    database_url: SecretStr

    # Which roster of agents (and lockfile) the backend drives. Must be set explicitly when
    # ENVIRONMENT=production: a forgotten variable must not silently run the other roster.
    agent_profile: AgentProfile = DEFAULT_AGENT_PROFILE

    # Per-session Managed Agents budget in US cents; unset = 400 ($4) for the production profile,
    # 100 for development.
    session_budget_cents: int = Field(gt=0)

    # Monthly spend ceiling across all plans, in cents; POST /plans refuses past it.
    monthly_limit_cents: int = Field(default=5000, gt=0)

    # Who may use the planner. Comma separated, case insensitive; empty means nobody.
    planner_allowed_emails: Annotated[list[str], NoDecode] = Field(default_factory=list)

    # The planner web app: CORS allow-origin and the Origin check on state-changing requests.
    frontend_origin: str = "https://pianifica.bellittim.com"

    # TripTracker: session verification, trip.json schema and CORS for GET /plans/{id}/trip.
    triptracker_origin: str = "https://viaggi.bellittim.com"

    # triptracker: verify the Better Auth cookie with TripTracker. local: development only, the
    # current user is the first PLANNER_ALLOWED_EMAILS entry.
    auth_mode: AuthMode = "triptracker"

    # The profile's lockfile written by `ant apply --lock-file`: agent, environment and skill IDs.
    # Unset = backend/claude-lock.<AGENT_PROFILE>.json.
    lockfile_path: Path

    # The backend's git sha, recorded in plans.agent_versions. Railway sets
    # RAILWAY_GIT_COMMIT_SHA; GIT_SHA wins when both are set. Unset locally: `git rev-parse`.
    git_sha: str | None = Field(
        default=None, validation_alias=AliasChoices("git_sha", "railway_git_commit_sha")
    )

    # TripTracker's exported Trip JSON Schema; defaults to TRIPTRACKER_ORIGIN/schema/trip.json.
    trip_schema_url: str = ""

    log_level: LogLevel = "INFO"

    # Bearer token of the machine endpoint POST /evals/runs (the CI eval job uploads its results
    # there, app/evals_store.py). Empty (the default) disables the endpoint: 404. Never logged.
    evals_ingest_token: SecretStr = SecretStr("")

    # Contact for Wikimedia's User-Agent policy (destination cover photos, app/covers.py): an
    # https:// page or a mailto: address where Wikimedia can reach whoever runs Atlas. Empty =
    # FRONTEND_ORIGIN, which is a page of this deployment.
    wikimedia_contact_url: str = ""

    # Local demo for UI work (development only): POST /plans replays a scripted session from
    # backend/tests/fixtures/ma through the fake Managed Agents client, offline and free.
    demo_mode: bool = False

    # Demo pacing: 1.0 replays a scenario with the gaps between its recorded events (about
    # 75 s for happy_path), 2.0 twice as slow, 0.1 ten times faster. Read only in demo mode.
    demo_pace: float = Field(default=DEFAULT_DEMO_PACE, gt=0, le=100, allow_inf_nan=False)

    @model_validator(mode="before")
    @classmethod
    def _profile_defaults(cls, data: Any) -> Any:
        """Fill SESSION_BUDGET_CENTS and LOCKFILE_PATH from the profile when unset or blank."""
        if not isinstance(data, Mapping):
            return data
        values = dict(cast(Mapping[str, Any], data))
        profile = _profile_of(values.get("agent_profile"))
        if _is_blank(values.get("session_budget_cents")):
            values["session_budget_cents"] = DEFAULT_SESSION_BUDGET_CENTS[profile]
        if _is_blank(values.get("lockfile_path")):
            values["lockfile_path"] = default_lockfile_path(profile)
        return values

    @field_validator("anthropic_api_key", mode="before")
    @classmethod
    def _blank_key_is_missing(cls, value: object) -> object:
        if isinstance(value, SecretStr):
            value = value.get_secret_value()
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator(
        "anthropic_identity_token_file",
        "anthropic_identity_token",
        "anthropic_federation_rule_id",
        "anthropic_organization_id",
        "anthropic_workspace_id",
        mode="before",
    )
    @classmethod
    def _blank_federation_value_is_missing(cls, value: object) -> object:
        if isinstance(value, SecretStr):
            value = value.get_secret_value()
        if isinstance(value, str):
            return value.strip() or None
        return value

    @field_validator("database_url", mode="before")
    @classmethod
    def _normalize_database_url(cls, value: object) -> object:
        if isinstance(value, SecretStr):
            value = value.get_secret_value()
        if isinstance(value, str):
            return normalize_database_url(value)
        return value

    @field_validator("planner_allowed_emails", mode="before")
    @classmethod
    def _split_emails(cls, value: object) -> object:
        if value is None:
            return []
        if isinstance(value, str):
            value = value.split(",")
        if isinstance(value, list | tuple | set | frozenset):
            emails = (str(item).strip().lower() for item in value)
            return list(dict.fromkeys(email for email in emails if email))
        return value

    @field_validator("frontend_origin", "triptracker_origin", mode="before")
    @classmethod
    def _normalize_origin(cls, value: object) -> object:
        return normalize_origin(value) if isinstance(value, str) else value

    @field_validator("evals_ingest_token", mode="before")
    @classmethod
    def _strip_ingest_token(cls, value: object) -> object:
        if isinstance(value, SecretStr):
            value = value.get_secret_value()
        return value.strip() if isinstance(value, str) else value

    @field_validator("git_sha", mode="before")
    @classmethod
    def _blank_sha_is_missing(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip() or None
        return value

    @field_validator("trip_schema_url", mode="before")
    @classmethod
    def _strip_schema_url(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @field_validator("wikimedia_contact_url", mode="before")
    @classmethod
    def _check_contact_url(cls, value: object) -> object:
        if not isinstance(value, str):
            return value
        contact = value.strip()
        if contact and not contact.startswith(("https://", "http://", "mailto:")):
            msg = (
                f"WIKIMEDIA_CONTACT_URL must be an http(s) URL or a mailto: address, got {value!r}"
            )
            raise ValueError(msg)
        return contact

    @field_validator("log_level", mode="before")
    @classmethod
    def _upper_log_level(cls, value: object) -> object:
        return value.strip().upper() if isinstance(value, str) else value

    @field_validator("demo_mode", "demo_pace", mode="before")
    @classmethod
    def _blank_demo_is_default(cls, value: object, info: ValidationInfo) -> object:
        """`DEMO_MODE=` / `DEMO_PACE=` (left empty in backend/.env) mean the default."""
        if isinstance(value, str) and not value.strip():
            return False if info.field_name == "demo_mode" else DEFAULT_DEMO_PACE
        return value

    @model_validator(mode="after")
    def _check_consistency(self) -> Self:
        if self.auth_mode == "local":
            if self.environment != "development":
                msg = "AUTH_MODE=local is only allowed when ENVIRONMENT=development"
                raise ValueError(msg)
            if not self.planner_allowed_emails:
                msg = "AUTH_MODE=local needs PLANNER_ALLOWED_EMAILS: its first entry is the user"
                raise ValueError(msg)
        if self.environment != "development" and (
            self.demo_mode or self.demo_pace != DEFAULT_DEMO_PACE
        ):
            msg = "DEMO_MODE and DEMO_PACE are only allowed when ENVIRONMENT=development"
            raise ValueError(msg)
        if self.environment == "production" and self.anthropic_api_key is None:
            msg = "ANTHROPIC_API_KEY is required when ENVIRONMENT=production"
            if self.anthropic_federation_configured:
                msg += (
                    " (Workload Identity Federation is only allowed when ENVIRONMENT=development)"
                )
            raise ValueError(msg)
        if self.environment == "production" and "agent_profile" not in self.model_fields_set:
            msg = (
                "AGENT_PROFILE must be set explicitly (production or development) when "
                "ENVIRONMENT=production"
            )
            raise ValueError(msg)
        if not self.trip_schema_url:
            self.trip_schema_url = f"{self.triptracker_origin}{TRIP_SCHEMA_PATH}"
        return self

    @property
    def anthropic_federation_configured(self) -> bool:
        """The variables the SDK needs for env-var federation are all present (the token itself
        is never read here). The SDK's own rule: rule id + organization id + a token or its file."""
        return bool(
            self.anthropic_federation_rule_id
            and self.anthropic_organization_id
            and (self.anthropic_identity_token_file or self.anthropic_identity_token)
        )

    @property
    def anthropic_auth_mode(self) -> Literal["api_key", "federation"] | None:
        """How Anthropic clients authenticate: the API key if set (the SDK's precedence too),
        else federation, which only ever counts in development (CI evals, local). None: no
        credentials, so the planner is unavailable."""
        if self.anthropic_api_key is not None:
            return "api_key"
        if self.environment == "development" and self.anthropic_federation_configured:
            return "federation"
        return None

    @property
    def anthropic_credentials_available(self) -> bool:
        return self.anthropic_auth_mode is not None

    @property
    def evals_ingest_enabled(self) -> bool:
        """POST /evals/runs answers only when EVALS_INGEST_TOKEN is set."""
        return bool(self.evals_ingest_token.get_secret_value())

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @property
    def wikimedia_user_agent(self) -> str:
        """The User-Agent sent to the Wikimedia APIs (their policy asks for a descriptive one
        with a way to reach the operator)."""
        contact = self.wikimedia_contact_url or self.frontend_origin
        return f"AtlasTripPlanner/1.0 ({contact}; personal trip planner)"

    @property
    def local_user_email(self) -> str | None:
        """The fixed user for AUTH_MODE=local; None in any other mode."""
        if self.auth_mode != "local":
            return None
        return self.planner_allowed_emails[0]

    def is_email_allowed(self, email: str | None) -> bool:
        """True only for an address listed in PLANNER_ALLOWED_EMAILS (an empty list allows none)."""
        if not email:
            return False
        return email.strip().lower() in self.planner_allowed_emails


@lru_cache
def get_settings() -> Settings:
    """The process-wide settings, built once. Tests call `get_settings.cache_clear()`."""
    return Settings()  # pyright: ignore[reportCallIssue]  # fields are read from the environment
