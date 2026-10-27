"""Backend settings, read from the environment and, locally, from backend/.env.

Every variable of the Railway table in the implementation doc lives here, plus ENVIRONMENT,
AUTH_MODE, ADMIN_EMAILS (the admin role: who reads the eval history), LOCKFILE_PATH,
TRIP_SCHEMA_URL, LOG_LEVEL, the backend's git sha (GIT_SHA or Railway's RAILWAY_GIT_COMMIT_SHA),
EVALS_INGEST_TOKEN (the eval upload endpoint) and the local demo's DEMO_MODE and DEMO_PACE
(development only: Settings refuses them in production).
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
AuthMode = Literal["triptracker", "atlas", "local"]

TRIPTRACKER_COOKIE_PREFIX = "better-auth"
"""Better Auth's default cookie prefix: TripTracker's session cookie is
`__Secure-better-auth.session_token`."""
ATLAS_COOKIE_PREFIX = "atlas"
"""The web app's own Better Auth cookie prefix (web/lib/auth.ts `advanced.cookiePrefix`):
`__Secure-atlas.session_token`. Distinct from TripTracker's, so the two never overwrite each
other on the shared `bellittim.com` cookie domain."""
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


def add_message_key(
    _logger: object, _method_name: str, event_dict: MutableMapping[str, Any]
) -> MutableMapping[str, Any]:
    """structlog processor, placed right before the JSON renderer: copies `event` into `message`.
    Railway reads a JSON log line's text from `message` (or `msg`), so without it every line of
    ours shows up blank in its log viewer and in exported logs. `event` stays for local tools."""
    if "message" not in event_dict and "event" in event_dict:
        event_dict["message"] = event_dict["event"]
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

    # Monthly spend ceiling across all plans, in cents (recorded cost plus the unspent budget of
    # the running plans, app/quota.py); POST /plans refuses a plan whose budget would not fit.
    monthly_limit_cents: int = Field(default=5000, gt=0)

    # Per-user monthly quota (calendar month in Europe/Rome): how many plans one account may
    # start and how many cents its plans may use, recorded cost plus the unspent budget of its
    # running plans. Admins (ADMIN_EMAILS) are exempt; the ceiling above still applies to them.
    user_monthly_plans: int = Field(default=10, gt=0)
    user_monthly_cents: int = Field(default=1500, gt=0)

    # How many times "Continua" may raise one plan's budget (each adds $2).
    max_continues_per_plan: int = Field(default=2, ge=0)

    # How many plans may be `running` at once, all users: past it POST /plans answers 503
    # planner_busy and nothing is spent.
    max_running_plans: int = Field(default=8, gt=0)

    # Rate limits, kept in the process (one replica; a redeploy starts them over): POST /plans
    # per user and per client IP in a sliding window of PLAN_CREATE_WINDOW_SECONDS, and how many
    # event streams (SSE) one user may hold open at once.
    plan_create_limit_per_user: int = Field(default=5, gt=0)
    plan_create_limit_per_ip: int = Field(default=20, gt=0)
    plan_create_window_seconds: int = Field(default=600, gt=0)
    max_streams_per_user: int = Field(default=4, gt=0)

    # Read the client IP from X-Forwarded-For (its last value, the one the proxy in front
    # appended) instead of request.client. Unset: on in production (Railway's proxy), off in
    # development. Never turn it on without a proxy, and never off behind Railway: the image's
    # uvicorn --proxy-headers with FORWARDED_ALLOW_IPS="*" puts the leftmost, client-chosen
    # X-Forwarded-For value in request.client (app/ratelimit.py). Either way a client could
    # then pick its own bucket.
    trust_proxy_headers: bool | None = None

    # Who may use the planner with AUTH_MODE=triptracker (and the user of AUTH_MODE=local). Comma
    # separated, case insensitive; empty means nobody. Not consulted with AUTH_MODE=atlas: there
    # the web app decides who may sign up (AUTH_ALLOWED_EMAILS), and every account may plan.
    planner_allowed_emails: Annotated[list[str], NoDecode] = Field(default_factory=list)

    # Who may read the eval history (GET /evals/runs*): the admin role, comma separated, case
    # insensitive. Empty: with AUTH_MODE=triptracker or local everyone in PLANNER_ALLOWED_EMAILS
    # (the one-user setup, where the user is the one running the evals); with AUTH_MODE=atlas
    # nobody.
    admin_emails: Annotated[list[str], NoDecode] = Field(default_factory=list)

    # The planner web app: CORS allow-origin and the Origin check on state-changing requests.
    frontend_origin: str = "https://atlas.bellittim.com"

    # TripTracker: session verification, trip.json schema and CORS for GET /plans/{id}/trip.
    triptracker_origin: str = "https://viaggi.bellittim.com"

    # Who says who the user is. triptracker: TripTracker's Better Auth cookie, verified at
    # TRIPTRACKER_ORIGIN. atlas: the web app's own Better Auth (web/lib/auth.ts), verified at
    # FRONTEND_ORIGIN; the user's id is stored with the plan (plans.user_id). local: development
    # only, the current user is the first PLANNER_ALLOWED_EMAILS entry.
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

    # Check every URL of a delivered plan (app/link_health.py): dead pages are replaced by their
    # site's homepage or shown as text. False skips the check (no request leaves the backend).
    link_check_enabled: bool = True

    # Free-licence Wikimedia photos for the choice cards (app/covers.py PlacePhotos). False = no
    # lookup, the cards go out without photos.
    choice_photos_enabled: bool = True

    # How long a choice (ask_traveller) waits for the traveller before Atlas picks. Keep it under
    # 300, the prompt cache's lifetime (probe P14): an answer within it resumes on a warm cache.
    choice_timeout_seconds: int = Field(default=240, ge=1, le=290)

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

    @field_validator("planner_allowed_emails", "admin_emails", mode="before")
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

    @field_validator("trust_proxy_headers", mode="before")
    @classmethod
    def _blank_proxy_flag_is_unset(cls, value: object) -> object:
        """`TRUST_PROXY_HEADERS=` (the example file's line) means "the environment's default"."""
        if isinstance(value, str) and not value.strip():
            return None
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
        if (
            self.environment == "production"
            and self.anthropic_api_key is None
            and not self.anthropic_federation_configured
        ):
            msg = (
                "ANTHROPIC_API_KEY, or a full Workload Identity Federation configuration "
                "(ANTHROPIC_FEDERATION_RULE_ID, ANTHROPIC_ORGANIZATION_ID and an identity token "
                "or ANTHROPIC_IDENTITY_TOKEN_FILE), is required when ENVIRONMENT=production"
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
        else Workload Identity Federation when it is fully configured. Federation now counts in
        production too (not only CI evals and local), so Railway can run on short-lived
        federated tokens with no stored key (docs/security-hardening.md). None: no credentials,
        so the planner is unavailable."""
        if self.anthropic_api_key is not None:
            return "api_key"
        if self.anthropic_federation_configured:
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
    def link_check_user_agent(self) -> str:
        """The User-Agent of the link check's requests: an honest one, naming Atlas's site."""
        return f"AtlasLinkCheck/1.0 (+{self.frontend_origin})"

    @property
    def local_user_email(self) -> str | None:
        """The fixed user for AUTH_MODE=local; None in any other mode."""
        if self.auth_mode != "local":
            return None
        return self.planner_allowed_emails[0]

    @property
    def auth_origin(self) -> str:
        """Where `GET /api/auth/get-session` is asked: the web app itself with AUTH_MODE=atlas,
        TripTracker otherwise (meaningless, but defined, with AUTH_MODE=local)."""
        return self.frontend_origin if self.auth_mode == "atlas" else self.triptracker_origin

    @property
    def auth_cookie_prefix(self) -> str:
        """The Better Auth cookie prefix the session cookie carries: `atlas` for the web app's
        own accounts, `better-auth` (the library default) for TripTracker's."""
        return ATLAS_COOKIE_PREFIX if self.auth_mode == "atlas" else TRIPTRACKER_COOKIE_PREFIX

    @property
    def secure_session_cookie_only(self) -> bool:
        """True in production when the provider runs on https: only the `__Secure-` session
        cookie name counts (`auth.session_cookie`). The plain `<prefix>.session_token` carries
        none of the `__Secure-` guarantees, so a sibling host of the shared cookie domain could
        plant one (cookie tossing); Better Auth over https never sets it. Development and an
        http provider keep accepting the plain name."""
        return self.is_production and self.auth_origin.startswith("https://")

    @property
    def plans_carry_user_id(self) -> bool:
        """True when the signed-in user's id is one of the web app's own `users.id`, so a new
        plan may store it in `plans.user_id` (a foreign key). TripTracker's ids never are."""
        return self.auth_mode == "atlas"

    def is_email_allowed(self, email: str | None) -> bool:
        """True only for an address listed in PLANNER_ALLOWED_EMAILS (an empty list allows none)."""
        if not email:
            return False
        return email.strip().lower() in self.planner_allowed_emails

    def may_use_planner(self, email: str | None) -> bool:
        """Whether the signed-in `email` may use the planner. With AUTH_MODE=atlas every account
        may: the web app already decided who could sign up (AUTH_ALLOWED_EMAILS,
        web/lib/auth-policy.ts), so PLANNER_ALLOWED_EMAILS is not a second gate. In the other
        modes the address must be listed (`is_email_allowed`)."""
        if self.auth_mode == "atlas":
            return bool(email and email.strip())
        return self.is_email_allowed(email)

    @property
    def admins(self) -> list[str]:
        """Who may read the eval history: ADMIN_EMAILS when set; else, outside AUTH_MODE=atlas,
        the planner's allowed users (the one-user setup); else nobody."""
        if self.admin_emails:
            return self.admin_emails
        return [] if self.auth_mode == "atlas" else self.planner_allowed_emails

    def is_admin(self, email: str | None) -> bool:
        """True when `email` is one of `admins` (trimmed, case insensitive). The role itself is
        `auth.user_is_admin`, which also wants a verified email with AUTH_MODE=atlas."""
        if not email:
            return False
        return email.strip().lower() in self.admins

    @property
    def trusts_proxy_headers(self) -> bool:
        """`TRUST_PROXY_HEADERS`, or the environment's default: production sits behind a proxy."""
        if self.trust_proxy_headers is not None:
            return self.trust_proxy_headers
        return self.environment == "production"


@lru_cache
def get_settings() -> Settings:
    """The process-wide settings, built once. Tests call `get_settings.cache_clear()`."""
    return Settings()  # pyright: ignore[reportCallIssue]  # fields are read from the environment
