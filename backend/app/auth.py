"""Who is calling: the Better Auth session behind the request, the roles, and the Origin check.

Spec: "Autenticazione e domini" ("Nel backend del planner"): `current_user()` reads Better Auth's
session cookie and decides who the user is; every state-changing request must carry
`Origin: FRONTEND_ORIGIN`, because the SameSite=Lax cookie is sent from any bellittim.com
subdomain. "Ambiente locale": with `AUTH_MODE=local` (development only, enforced by Settings)
the user is the first allowed email, with no I/O. Tests: tests/test_auth.py (no cookie 401,
email not allowed 403, wrong Origin 403; on the TripTracker path the cache expired after 60 s;
on the atlas path the session table, read on every request with no cache).

Two identity providers, both Better Auth, chosen by `AUTH_MODE` (`Settings.auth_origin` and
`Settings.auth_cookie_prefix`), verified in two different ways:

- `atlas`: the web app's own accounts (web/lib/auth.ts), cookie prefix `atlas`, so the cookie
  never collides with TripTracker's on the shared `bellittim.com` domain. The web app writes its
  sessions in the database this backend migrates (`auth_sessions`, `users`: app/db.py), so the
  check is one indexed query (`verify_atlas_session`): the cookie's token must be a session that
  has not expired, joined to its user. No HTTP call, no cache, no throttle: a sign-out is
  effective on the next request, and a web app outage does not touch the API. The provider's
  `user.id` is one of this backend's `users.id` and is stored with new plans
  (`Settings.plans_carry_user_id`). Access: every account may plan (the web app decided who could
  sign up, `AUTH_ALLOWED_EMAILS`); PLANNER_ALLOWED_EMAILS is not consulted
  (`Settings.may_use_planner`).
- `triptracker`: TripTracker's accounts at `TRIPTRACKER_ORIGIN`, cookie prefix `better-auth`
  (the spec's original design, one user). The cookie is forwarded to TripTracker's
  `/api/auth/get-session?disableRefresh=true` (`SessionVerifier`), the answer is cached 60
  seconds keyed by the token's hash (a revoked session stops working within a minute), and the
  email must be in `PLANNER_ALLOWED_EMAILS` (empty means nobody). Everything below about the
  budget, the stale window and the signed-out cache is this path's.

Roles: `require_admin` (`RequireAdmin`) guards the eval history: the user must be one of
`Settings.admins` (ADMIN_EMAILS; outside `atlas` mode the allowed users by default) and, in
`atlas` mode, have a verified email (`user_is_admin`), else 403 `admin_only`. `GET /me` tells
the web app whether to show that section.

Better Auth facts (docs/triptracker/schema-notes.md §6 and §8 C1-C5; the same library serves
both providers):

- Cookie names: `__Secure-<prefix>.session_token` when the provider runs on https, plain
  `<prefix>.session_token` in local http development. In production with an https provider
  only the `__Secure-` name is accepted (`Settings.secure_session_cookie_only`): the plain name
  has none of the prefix's guarantees, so a sibling `bellittim.com` host could plant one
  (cookie tossing). Elsewhere both are accepted, the `__Secure-` one first. The value is
  signed (`<token>.<hmac>`). On the TripTracker path it is hashed whole for the cache key and
  forwarded untouched; on the atlas path the token before the dot is looked up
  (`session_token`): Better Auth's own `getSession` checks the signature and then looks the
  token up, and the token alone (32 random alphanumerics) is the secret, so a forged signature
  with an unknown token finds no row.
- Only the provider's Better Auth cookies (names starting with `__Secure-<prefix>.` or
  `<prefix>.`) are forwarded, never the browser's other cookies, and never the other
  provider's. No `Set-Cookie` from the answer is relayed.
- `GET /api/auth/get-session` answers 200 with `{"session": {...}, "user": {"email", ...}}`, or
  200 with the JSON body `null` when signed out (not 401), or 503 when TripTracker's accounts
  are not configured. The body contains `session.token`: never log the body or the cookie.
- The planner always asks with `?disableRefresh=true` (`GET_SESSION_PARAMS`). Without it, a
  session older than `updateAge` (1 day in TripTracker) is extended by the check itself:
  Better Auth writes a new `expiresAt` and answers with a `Set-Cookie` that the planner drops,
  so the browser's cookie and the server's session would drift apart behind the browser's
  back. The flag exists in better-auth 1.7.3, the version TripTracker locks
  (`getSessionQuerySchema` in `dist/cookies/session-store.mjs`: `disableRefresh:
  z.coerce.boolean().optional()`; `dist/api/routes/session.mjs` answers before any refresh
  when it is set). Only the browser's own visits to TripTracker refresh the session. The atlas
  path never writes either: the web app's own visits refresh its sessions.
- `PLANNER_ALLOWED_EMAILS` has no `*` wildcard (unlike `EMAIL_AMMESSE`); emails compare trimmed
  and lower-cased (`Settings.is_email_allowed`).

Errors use FastAPI's `HTTPException` with `detail = {"code": <AuthErrorCode>, "message":
<Italian text>}`, the API's error envelope (`routes.ErrorBody`); the wording names TripTracker
only with AUTH_MODE=triptracker (`auth_messages`). A 401 makes the web app send the user to the
provider's login with `returnTo=<current page>`.

Unknown cookies cannot lock the real user out (decision 19). On the TripTracker path every
get-session call leaves from the planner's one egress IP, and Better Auth rate-limits it per IP
and path (100 requests in a burst whose requests are less than 10 s apart; `api/rate-limiter`
in better-auth 1.7.3). So, without throttling, random cookie values would exhaust that bucket
and every verification would get 429. The defences:

- `VerificationBudget` keeps outbound calls well under that limit. Unknown tokens may use only
  part of each burst; revalidating a user verified before may use the rest. Over budget means
  `auth_unavailable` without calling TripTracker. It is process-wide, never per client: the
  client IP is spoofable behind `FORWARDED_ALLOW_IPS="*"`.
- Stale-if-error: a verified user stays usable `STALE_USER_SECONDS` past the 60 s TTL. Only a
  failed or refused check uses it (429, 5xx, network, malformed body, no budget). A signed-out
  answer (200 `null`, 401) evicts the user at once, so revocation still works while
  TripTracker answers.
- Signed-out answers live in their own smaller cache, so junk tokens never evict a user.
- `plausible_session_token` turns away values that cannot be a Better Auth signed cookie
  (`<token>.<signature>`, bounded length, URL-safe characters) with 401 and no network call
  (and, on the atlas path, no query).
- Concurrent checks of one token share a single call (single-flight).
"""

from __future__ import annotations

import asyncio
import datetime as dt
import hashlib
import re
import time
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Annotated, Any, cast

import httpx
import structlog
from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from app import clock
from app.config import TRIPTRACKER_COOKIE_PREFIX, normalize_origin
from app.db import AuthSessionRecord, UserRecord

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from app.config import Settings

DEFAULT_COOKIE_PREFIX = TRIPTRACKER_COOKIE_PREFIX
"""Better Auth's default prefix; the pure helpers below assume it unless told otherwise."""


def session_cookie_names(
    prefix: str = DEFAULT_COOKIE_PREFIX, *, secure_only: bool = False
) -> tuple[str, ...]:
    """Accepted session cookie names for a Better Auth cookie `prefix`, in order of preference:
    the `__Secure-` one (https) first, then the plain one (local http development), unless
    `secure_only` (`Settings.secure_session_cookie_only`: production over https)."""
    secure = f"__Secure-{prefix}.session_token"
    return (secure,) if secure_only else (secure, f"{prefix}.session_token")


def forwarded_cookie_prefixes(prefix: str = DEFAULT_COOKIE_PREFIX) -> tuple[str, str]:
    """Name prefixes of the cookies forwarded to the provider: its Better Auth cookies only."""
    return (f"__Secure-{prefix}.", f"{prefix}.")


SESSION_COOKIE_NAMES: tuple[str, ...] = session_cookie_names()
"""TripTracker's session cookie names (the default prefix), in order of preference."""

FORWARDED_COOKIE_PREFIXES: tuple[str, ...] = forwarded_cookie_prefixes()
GET_SESSION_PATH = "/api/auth/get-session"
GET_SESSION_PARAMS: dict[str, str] = {"disableRefresh": "true"}
"""Query of every get-session call: check the session, never refresh it (module docstring)."""
SESSION_CACHE_TTL_SECONDS = 60.0
HTTP_TIMEOUT_SECONDS = 5.0
STATE_CHANGING_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})

STALE_USER_SECONDS = 15 * 60.0
"""How long past its TTL a verified user is still served when TripTracker cannot answer."""
USER_CACHE_MAX_ENTRIES = 1024
SIGNED_OUT_CACHE_MAX_ENTRIES = 256
"""Signed-out answers have their own, smaller FIFO: junk tokens never evict a user."""

VERIFY_BURST_LIMIT = 50
"""Outbound get-session calls per burst, half of Better Auth's default `max` (100)."""
VERIFY_BURST_MISS_LIMIT = 40
"""Of those, how many may check a token with no cached user; the rest are reserved for
revalidating users verified before, so a flood of unknown tokens never starves them."""
VERIFY_QUIET_SECONDS = 11.0
"""A burst ends after this long without a call: Better Auth's `window` (10 s) plus a margin for
network latency, so TripTracker has always reset its own count by then."""

MAX_SESSION_COOKIE_LENGTH = 512
"""Better Auth's value is a 32-character token, a dot and a URL-encoded 44-character base64
HMAC (at most 165 characters); anything much longer is not a session cookie."""
_PLAUSIBLE_SESSION_TOKEN = re.compile(r"[A-Za-z0-9_~.-]+\.[A-Za-z0-9%+/=_~-]+")

log = structlog.get_logger(__name__)


class AuthErrorCode(StrEnum):
    """Stable `detail.code` values of auth failures (the web app maps them)."""

    NOT_AUTHENTICATED = "not_authenticated"  # 401: no cookie, or TripTracker says signed out
    EMAIL_NOT_ALLOWED = "email_not_allowed"  # 403: signed in, but not in PLANNER_ALLOWED_EMAILS
    BAD_ORIGIN = "bad_origin"  # 403: state-changing request without Origin: FRONTEND_ORIGIN
    ADMIN_ONLY = "admin_only"  # 403: signed in, but not one of Settings.admins (the eval history)
    AUTH_UNAVAILABLE = "auth_unavailable"  # 503: the provider (or the session table) unreachable


AUTH_ERROR_MESSAGES: dict[AuthErrorCode, str] = {
    AuthErrorCode.NOT_AUTHENTICATED: "Accedi a TripTracker per usare il planner.",
    AuthErrorCode.EMAIL_NOT_ALLOWED: "Questo account non è abilitato al planner.",
    AuthErrorCode.BAD_ORIGIN: "Richiesta rifiutata: arriva da un'origine non consentita.",
    AuthErrorCode.ADMIN_ONLY: "Questa sezione è riservata a chi gestisce il planner.",
    AuthErrorCode.AUTH_UNAVAILABLE: (
        "Non riesco a verificare l'accesso con TripTracker. Riprova tra poco."
    ),
}
"""Italian messages shown by the web app (user-facing copy), AUTH_MODE=triptracker wording."""

ATLAS_AUTH_ERROR_MESSAGES: dict[AuthErrorCode, str] = {
    **AUTH_ERROR_MESSAGES,
    AuthErrorCode.NOT_AUTHENTICATED: "Accedi per usare il planner.",
    AuthErrorCode.AUTH_UNAVAILABLE: "Non riesco a verificare l'accesso. Riprova tra poco.",
}
"""The same, when the accounts are the web app's own (AUTH_MODE=atlas or local)."""


def auth_messages(settings: Settings) -> dict[AuthErrorCode, str]:
    """The error wording for the configured identity provider."""
    return AUTH_ERROR_MESSAGES if settings.auth_mode == "triptracker" else ATLAS_AUTH_ERROR_MESSAGES


AUTH_ERROR_STATUS: dict[AuthErrorCode, int] = {
    AuthErrorCode.NOT_AUTHENTICATED: 401,
    AuthErrorCode.EMAIL_NOT_ALLOWED: 403,
    AuthErrorCode.BAD_ORIGIN: 403,
    AuthErrorCode.ADMIN_ONLY: 403,
    AuthErrorCode.AUTH_UNAVAILABLE: 503,
}


@dataclass(frozen=True, slots=True)
class CurrentUser:
    """The signed-in user of a request (`sessions.plan_owner_filter` says which plans are
    theirs)."""

    email: str
    """Lower-cased and trimmed; in PLANNER_ALLOWED_EMAILS outside AUTH_MODE=atlas."""
    auth_user_id: str | None = None
    """The provider's Better Auth `user.id`; None in AUTH_MODE=local. It is one of this
    backend's `users.id` only with AUTH_MODE=atlas (`Settings.plans_carry_user_id`)."""
    email_verified: bool = False
    """`users.email_verified` (AUTH_MODE=atlas): the account proved it owns `email` (a magic
    link, or Google saying so). Only that mode consults it: without it the email grants neither
    the legacy plans stored by email (`sessions.plan_owner_filter`) nor the admin role
    (`user_is_admin`), though the plans stored with the user's id stay theirs."""


def auth_error(
    code: AuthErrorCode, messages: dict[AuthErrorCode, str] = AUTH_ERROR_MESSAGES
) -> HTTPException:
    """The `HTTPException` for `code`: status 401/403/503 and the error envelope as detail,
    worded from `messages` (`auth_messages(settings)`). 401 also carries
    `WWW-Authenticate: Cookie` for well-behaved clients."""
    status = AUTH_ERROR_STATUS[code]
    headers = {"WWW-Authenticate": "Cookie"} if status == 401 else None
    detail = {"code": code.value, "message": messages[code], "data": None}
    return HTTPException(status_code=status, detail=detail, headers=headers)


def _request_cookie_pairs(request: Request) -> list[tuple[str, str]]:
    """Every `name=value` pair of the request's Cookie header(s), in order, values untouched
    (no unquoting or decoding). Pieces without `=` are skipped."""
    pairs: list[tuple[str, str]] = []
    for header in request.headers.getlist("cookie"):
        for piece in header.split(";"):
            name, separator, value = piece.strip().partition("=")
            name = name.strip()
            if separator and name:
                pairs.append((name, value.strip()))
    return pairs


def session_cookie(
    request: Request, prefix: str = DEFAULT_COOKIE_PREFIX, *, secure_only: bool = False
) -> tuple[str, str] | None:
    """(cookie name, raw value) of the first present name in
    `session_cookie_names(prefix, secure_only=secure_only)`, or None.

    The value is read from the raw header (the first occurrence of the name), untouched; an
    empty value counts as absent."""
    pairs = _request_cookie_pairs(request)
    for name in session_cookie_names(prefix, secure_only=secure_only):
        for cookie_name, value in pairs:
            if cookie_name == name and value:
                return name, value
    return None


def forwarded_cookie_header(request: Request, prefix: str = DEFAULT_COOKIE_PREFIX) -> str:
    """The `Cookie` header sent to the provider: only its Better Auth cookies
    (`forwarded_cookie_prefixes(prefix)`), values untouched, in their original order."""
    prefixes = forwarded_cookie_prefixes(prefix)
    return "; ".join(
        f"{name}={value}"
        for name, value in _request_cookie_pairs(request)
        if name.startswith(prefixes)
    )


def token_cache_key(raw_cookie_value: str) -> str:
    """sha256 hex of the raw (signed) cookie value; the token itself is never kept in memory
    longer than the request."""
    return hashlib.sha256(raw_cookie_value.encode("utf-8")).hexdigest()


def plausible_session_token(raw_cookie_value: str) -> bool:
    """True when the value can be a Better Auth signed session cookie: `<token>.<signature>`,
    at most `MAX_SESSION_COOKIE_LENGTH` characters, URL-safe characters only (the signature is
    base64, URL-encoded or not). Anything else is answered 401 without asking TripTracker."""
    return len(raw_cookie_value) <= MAX_SESSION_COOKIE_LENGTH and bool(
        _PLAUSIBLE_SESSION_TOKEN.fullmatch(raw_cookie_value)
    )


class SessionCache:
    """Token hash -> what TripTracker said: a `CurrentUser`, or None for signed out.

    Two bounded FIFOs (oldest evicted first), timed with the injected monotonic `clock`
    (tests advance it instead of sleeping):

    - users: fresh for `ttl` seconds (`get` hits), then kept `stale_for` more seconds for
      `get_stale`, the fallback when TripTracker cannot answer. At most `max_entries`.
    - signed out: fresh for `ttl` seconds, then gone. At most `max_signed_out`, in their own
      FIFO, so a flood of junk tokens never evicts a user.

    Storing None for a key drops its user at once (revocation); storing a user drops its
    signed-out entry. Errors (network, 429, 5xx, 503) are never stored.
    """

    def __init__(
        self,
        *,
        ttl: float = SESSION_CACHE_TTL_SECONDS,
        stale_for: float = STALE_USER_SECONDS,
        clock: Callable[[], float] | None = None,
        max_entries: int = USER_CACHE_MAX_ENTRIES,
        max_signed_out: int = SIGNED_OUT_CACHE_MAX_ENTRIES,
    ) -> None:
        """`clock` defaults to `time.monotonic`."""
        if ttl <= 0:
            msg = f"ttl must be positive, got {ttl}"
            raise ValueError(msg)
        if stale_for < 0:
            msg = f"stale_for must not be negative, got {stale_for}"
            raise ValueError(msg)
        if max_entries < 1 or max_signed_out < 1:
            msg = f"cache sizes must be at least 1, got {max_entries} and {max_signed_out}"
            raise ValueError(msg)
        self._ttl = ttl
        self._stale_for = stale_for
        self._clock = clock or time.monotonic
        self._max_entries = max_entries
        self._max_signed_out = max_signed_out
        self._users: OrderedDict[str, tuple[float, CurrentUser]] = OrderedDict()
        """key -> (verified at, user)."""
        self._signed_out: OrderedDict[str, float] = OrderedDict()
        """key -> answered at."""

    def get(self, key: str) -> tuple[bool, CurrentUser | None]:
        """(hit, value) for a fresh entry. A hit with None means a cached "signed out"; a user
        past its TTL is a miss (but still available to `get_stale`)."""
        now = self._clock()
        answered_at = self._signed_out.get(key)
        if answered_at is not None:
            if now - answered_at < self._ttl:
                return True, None
            del self._signed_out[key]
        entry = self._user_entry(key, now)
        if entry is not None and now - entry[0] < self._ttl:
            return True, entry[1]
        return False, None

    def get_stale(self, key: str) -> CurrentUser | None:
        """The user stored for `key` if it was verified less than `ttl + stale_for` seconds
        ago (fresh or stale), else None."""
        entry = self._user_entry(key, self._clock())
        return entry[1] if entry is not None else None

    def put(self, key: str, value: CurrentUser | None) -> None:
        now = self._clock()
        if value is None:
            self._users.pop(key, None)
            self._signed_out.pop(key, None)
            self._signed_out[key] = now
            while len(self._signed_out) > self._max_signed_out:
                self._signed_out.popitem(last=False)
            return
        self._signed_out.pop(key, None)
        self._users.pop(key, None)
        self._users[key] = (now, value)
        while len(self._users) > self._max_entries:
            self._users.popitem(last=False)

    def clear(self) -> None:
        self._users.clear()
        self._signed_out.clear()

    def __len__(self) -> int:
        """Stored entries of both kinds, stale users included."""
        return len(self._users) + len(self._signed_out)

    def _user_entry(self, key: str, now: float) -> tuple[float, CurrentUser] | None:
        entry = self._users.get(key)
        if entry is not None and now - entry[0] >= self._ttl + self._stale_for:
            del self._users[key]
            return None
        return entry


class VerificationBudget:
    """Process-wide throttle on outbound get-session calls, shaped like Better Auth's limiter.

    Better Auth counts the requests of one IP and path until `window` (10 s) passes without
    one, and answers 429 past `max` (100). This class keeps the same kind of count over the
    planner's calls, with a lower cap: a burst is a run of calls each less than `quiet_seconds`
    after the previous one. Unknown tokens may use only `miss_limit` calls of a burst;
    revalidations of a user already in the cache (`known=True`) may use up to `limit`. A
    refused call is not counted and does not extend the burst, as in Better Auth. Never keyed
    on the client: its IP is spoofable.
    """

    def __init__(
        self,
        *,
        limit: int = VERIFY_BURST_LIMIT,
        miss_limit: int = VERIFY_BURST_MISS_LIMIT,
        quiet_seconds: float = VERIFY_QUIET_SECONDS,
        clock: Callable[[], float] | None = None,
    ) -> None:
        """`clock` defaults to `time.monotonic`."""
        if not 1 <= miss_limit <= limit:
            msg = f"need 1 <= miss_limit <= limit, got {miss_limit} and {limit}"
            raise ValueError(msg)
        if quiet_seconds <= 0:
            msg = f"quiet_seconds must be positive, got {quiet_seconds}"
            raise ValueError(msg)
        self._limit = limit
        self._miss_limit = miss_limit
        self._quiet = quiet_seconds
        self._clock = clock or time.monotonic
        self._count = 0
        self._last_call: float | None = None
        self.refused = 0
        """Calls refused in the current burst (the first one is logged)."""

    def try_acquire(self, *, known: bool) -> bool:
        """Count one call and return True, or return False when the burst is over its cap."""
        now = self._clock()
        if self._last_call is not None and now - self._last_call >= self._quiet:
            self._count = 0
            self.refused = 0
        if self._count >= (self._limit if known else self._miss_limit):
            self.refused += 1
            return False
        self._count += 1
        self._last_call = now
        return True


class _Unavailable:
    """The provider could not say who owns the cookie (error, or no budget)."""


_UNAVAILABLE = _Unavailable()
_Outcome = CurrentUser | None | _Unavailable


class SessionVerifier:
    """Asks the identity provider (`Settings.auth_origin`) who owns a session cookie. One per
    process (`app.state.session_verifier`, built by `sessions.start_planner`), sharing the
    application's httpx client."""

    def __init__(
        self,
        settings: Settings,
        http: httpx.AsyncClient,
        *,
        cache: SessionCache | None = None,
        budget: VerificationBudget | None = None,
    ) -> None:
        self._url = httpx.URL(
            f"{settings.auth_origin}{GET_SESSION_PATH}", params=GET_SESSION_PARAMS
        )
        self._messages = auth_messages(settings)
        self._require_user_id = settings.plans_carry_user_id
        self._http = http
        self.cache = cache if cache is not None else SessionCache()
        self.budget = budget if budget is not None else VerificationBudget()
        self._pending: dict[str, asyncio.Task[_Outcome]] = {}

    async def verify(self, cookie_header: str, cache_key: str) -> CurrentUser | None:
        """The user for this cookie, from the cache or from `GET {Settings.auth_origin}{
        GET_SESSION_PATH}?disableRefresh=true` with `Cookie: cookie_header`
        (`HTTP_TIMEOUT_SECONDS`, no redirects).

        Returns None for a 200 `null` body (signed out), and for a 401 (a signed-out answer in
        another form); both are cached like a user, and evict a user cached for the same key.
        When the call fails (network errors, timeouts, any other non-200 status, malformed
        bodies; logged with the status only, never cached) or `budget` refuses it, the user
        verified for this key within `STALE_USER_SECONDS` past the TTL is returned; without
        one, raises `auth_error(AUTH_UNAVAILABLE)`. Concurrent calls for one key share a single
        request. Does not check the allowlist: `current_user` does, on every request, so a
        change of PLANNER_ALLOWED_EMAILS applies immediately.
        """
        hit, cached = self.cache.get(cache_key)
        if hit:
            return cached
        pending = self._pending.get(cache_key)
        if pending is None:
            pending = asyncio.ensure_future(self._ask_provider(cookie_header, cache_key))
            self._pending[cache_key] = pending
            pending.add_done_callback(lambda task: self._forget(cache_key, task))
        # Shielded: a client that disconnects does not cancel the call other requests share.
        outcome = await asyncio.shield(pending)
        if not isinstance(outcome, _Unavailable):
            return outcome
        stale = self.cache.get_stale(cache_key)
        if stale is None:
            raise auth_error(AuthErrorCode.AUTH_UNAVAILABLE, self._messages)
        log.info("auth_stale_user_served")
        return stale

    def _forget(self, cache_key: str, task: asyncio.Task[_Outcome]) -> None:
        if self._pending.get(cache_key) is task:
            del self._pending[cache_key]
        if not task.cancelled():
            task.exception()  # retrieved, so a crash is never reported as "never retrieved"

    async def _ask_provider(self, cookie_header: str, cache_key: str) -> _Outcome:
        """One budgeted get-session call; caches what the provider said, or `_UNAVAILABLE`."""
        known = self.cache.get_stale(cache_key) is not None
        if not self.budget.try_acquire(known=known):
            if self.budget.refused == 1:
                log.warning(
                    "auth_verify_budget_exhausted",
                    limit=VERIFY_BURST_LIMIT,
                    miss_limit=VERIFY_BURST_MISS_LIMIT,
                    quiet_seconds=VERIFY_QUIET_SECONDS,
                )
            return _UNAVAILABLE
        try:
            response = await self._http.get(
                self._url,
                headers={"Cookie": cookie_header, "Accept": "application/json"},
                timeout=HTTP_TIMEOUT_SECONDS,
                follow_redirects=False,
            )
        except httpx.HTTPError as exc:
            log.warning("auth_get_session_failed", error=type(exc).__name__)
            return _UNAVAILABLE
        user: CurrentUser | None
        if response.status_code == 401:
            user = None
        elif response.status_code != 200:
            log.warning("auth_get_session_status", status=response.status_code)
            return _UNAVAILABLE
        else:
            try:
                user = parse_get_session(response.json(), require_user_id=self._require_user_id)
            except ValueError:  # json.JSONDecodeError included
                log.warning("auth_get_session_malformed", status=response.status_code)
                return _UNAVAILABLE
        self.cache.put(cache_key, user)
        return user


def session_token(raw_cookie_value: str) -> str:
    """The session token inside a Better Auth cookie value: the part before the first dot of
    `<token>.<signature>` (empty when the value starts with a dot)."""
    return raw_cookie_value.partition(".")[0]


async def verify_atlas_session(
    session_factory: async_sessionmaker[AsyncSession],
    raw_cookie_value: str,
    *,
    now: dt.datetime | None = None,
) -> CurrentUser | None:
    """The owner of an `atlas` session cookie, read from the shared database (AUTH_MODE=atlas).

    One query: the `auth_sessions` row whose `token` is the cookie's `session_token` and whose
    `expires_at` is after `now` (default `clock.now()`), joined to its `users` row (the id, the
    email and whether it is verified). None when
    there is no such row: signed out, revoked, expired, or a token that was never issued (a
    forged cookie). No cache, so a sign-out is effective on the next request. Never writes:
    Better Auth's `updateAge` refresh happens on the web app's own visits. Database errors
    propagate (`current_user` turns them into 503 `auth_unavailable`).
    """
    token = session_token(raw_cookie_value)
    if not token:
        return None
    moment = now if now is not None else clock.now()
    async with session_factory() as db:
        row = (
            await db.execute(
                select(UserRecord.id, UserRecord.email, UserRecord.email_verified)
                .join(AuthSessionRecord, AuthSessionRecord.user_id == UserRecord.id)
                .where(AuthSessionRecord.token == token, AuthSessionRecord.expires_at > moment)
            )
        ).first()
    if row is None:
        return None
    user_id, email, email_verified = row
    return CurrentUser(
        email=email.strip().lower(), auth_user_id=user_id, email_verified=bool(email_verified)
    )


def parse_get_session(body: Any, *, require_user_id: bool = False) -> CurrentUser | None:
    """Pure: Better Auth's get-session JSON -> `CurrentUser` (email lower-cased), None for a
    `null` body. Raises ValueError when a non-null body has no `user.email` string, and, with
    `require_user_id` (`Settings.plans_carry_user_id`: new plans store it in `plans.user_id`),
    when it has no non-empty `user.id` string: such an answer is malformed, never a user
    without an id."""
    if body is None:
        return None
    if not isinstance(body, dict):
        msg = "get-session body is neither null nor an object"
        raise ValueError(msg)
    user = cast(dict[str, Any], body).get("user")
    if not isinstance(user, dict):
        msg = "get-session body has no user object"
        raise ValueError(msg)
    fields = cast(dict[str, Any], user)
    email = fields.get("email")
    if not isinstance(email, str) or not email.strip():
        msg = "get-session user has no email"
        raise ValueError(msg)
    user_id = fields.get("id")
    if require_user_id and not (isinstance(user_id, str) and user_id):
        msg = "get-session user has no id"
        raise ValueError(msg)
    return CurrentUser(
        email=email.strip().lower(),
        auth_user_id=user_id if isinstance(user_id, str) and user_id else None,
    )


async def current_user(request: Request) -> CurrentUser:
    """FastAPI dependency for every endpoint except /health.

    Reads `Settings` from `request.app.state.settings`. With AUTH_MODE=local it returns
    `CurrentUser(settings.local_user_email)` without I/O. Otherwise: no session cookie of the
    configured provider (`settings.auth_cookie_prefix`; only the `__Secure-` name with
    `settings.secure_session_cookie_only`), or a value that cannot be one
    (`plausible_session_token`) -> 401 `not_authenticated` without asking anyone. Then the
    provider: AUTH_MODE=atlas looks the cookie's token up in the shared database
    (`verify_atlas_session`, through `request.app.state.session_factory`); AUTH_MODE=triptracker
    asks TripTracker (`SessionVerifier.verify`, from `request.app.state.session_verifier`).
    Nobody behind the cookie -> 401; an address that may not use the planner
    (`Settings.may_use_planner`: outside `atlas` mode, not in PLANNER_ALLOWED_EMAILS) -> 403
    `email_not_allowed`; a provider or database failure (or a service the lifespan did not
    set) -> 503 `auth_unavailable`. Binds `user_email` to nothing in the logs (the email is
    personal data).
    """
    settings: Settings = request.app.state.settings
    local_email = settings.local_user_email
    if local_email is not None:
        return CurrentUser(email=local_email)
    messages = auth_messages(settings)
    prefix = settings.auth_cookie_prefix
    cookie = session_cookie(request, prefix, secure_only=settings.secure_session_cookie_only)
    if cookie is None or not plausible_session_token(cookie[1]):
        raise auth_error(AuthErrorCode.NOT_AUTHENTICATED, messages)
    if settings.auth_mode == "atlas":
        session_factory: async_sessionmaker[AsyncSession] | None = getattr(
            request.app.state, "session_factory", None
        )
        if session_factory is None:
            log.error("auth_session_factory_missing")
            raise auth_error(AuthErrorCode.AUTH_UNAVAILABLE, messages)
        try:
            user = await verify_atlas_session(session_factory, cookie[1])
        except (SQLAlchemyError, OSError) as exc:
            # OSError: asyncpg's socket failures (connection refused, reset) are not wrapped.
            log.warning("auth_session_lookup_failed", error=type(exc).__name__)
            raise auth_error(AuthErrorCode.AUTH_UNAVAILABLE, messages) from None
    else:
        verifier: SessionVerifier | None = getattr(request.app.state, "session_verifier", None)
        if verifier is None:
            log.error("auth_verifier_missing")
            raise auth_error(AuthErrorCode.AUTH_UNAVAILABLE, messages)
        user = await verifier.verify(
            forwarded_cookie_header(request, prefix), token_cache_key(cookie[1])
        )
    if user is None:
        raise auth_error(AuthErrorCode.NOT_AUTHENTICATED, messages)
    if not settings.may_use_planner(user.email):
        raise auth_error(AuthErrorCode.EMAIL_NOT_ALLOWED, messages)
    return user


def origin_allowed(origin: str | None, frontend_origin: str) -> bool:
    """True when `origin` (an `Origin` header value) is exactly `frontend_origin` once
    normalized like `config.normalize_origin`; False when missing, `null` or malformed."""
    if origin is None or not origin.strip() or origin.strip().lower() == "null":
        return False
    try:
        return normalize_origin(origin) == frontend_origin
    except ValueError:
        return False


async def require_origin(request: Request) -> None:
    """FastAPI dependency for every state-changing endpoint (POST in this API).

    Passes when the `Origin` header, normalized like `config.normalize_origin`, equals
    `settings.frontend_origin`; a missing, `null` or different Origin -> 403 `bad_origin`.
    Applied in AUTH_MODE=local too. Safe methods (GET, HEAD, OPTIONS) are never checked.
    """
    if request.method.upper() not in STATE_CHANGING_METHODS:
        return
    settings: Settings = request.app.state.settings
    if not origin_allowed(request.headers.get("origin"), settings.frontend_origin):
        raise auth_error(AuthErrorCode.BAD_ORIGIN, auth_messages(settings))


CurrentUserDep = Annotated[CurrentUser, Depends(current_user)]
"""`user: CurrentUserDep` in a route signature."""

RequireOrigin = Depends(require_origin)
"""`dependencies=[RequireOrigin]` on state-changing routes."""


def user_is_admin(user: CurrentUser, settings: Settings) -> bool:
    """Whether `user` holds the admin role: their email is one of `Settings.admins` and, with
    AUTH_MODE=atlas, verified (`CurrentUser.email_verified`): an account that never proved it
    owns an admin's address is no admin. TripTracker's and the local mode's users are trusted
    by their allowlisted email, as before."""
    if settings.auth_mode == "atlas" and not user.email_verified:
        return False
    return settings.is_admin(user.email)


async def require_admin(request: Request, user: CurrentUserDep) -> None:
    """FastAPI dependency of the eval history (`GET /evals/runs*`): the signed-in user must be
    an admin (`user_is_admin`), else 403 `admin_only`. Runs after `current_user` (shared within
    the request by FastAPI's dependency cache), so a signed-out caller still gets its 401."""
    settings: Settings = request.app.state.settings
    if not user_is_admin(user, settings):
        raise auth_error(AuthErrorCode.ADMIN_ONLY, auth_messages(settings))


RequireAdmin = Depends(require_admin)
"""`dependencies=[RequireAdmin]` on the routes reserved to the admin role."""
