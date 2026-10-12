"""Who is calling: the TripTracker session behind the request, and the Origin check.

Spec: "Autenticazione e domini" ("Nel backend del planner"): `current_user()` reads Better Auth's
session cookie (`__Secure-better-auth.session_token` in production), forwards it to
`TRIPTRACKER_ORIGIN/api/auth/get-session?disableRefresh=true`, caches the answer 60 seconds
keyed by the token's hash (a revoked session stops working within a minute); the email must be
in `PLANNER_ALLOWED_EMAILS` (empty means nobody); every state-changing request must carry
`Origin: FRONTEND_ORIGIN`, because the SameSite=Lax cookie is sent from any bellittim.com
subdomain. "Ambiente locale": with `AUTH_MODE=local` (development only, enforced by Settings)
the user is the first allowed email, with no network call. Tests: tests/test_auth.py (no cookie
401, email not allowed 403, wrong Origin 403, cache expired after 60 s).

Better Auth facts (docs/triptracker/schema-notes.md §6 and §8 C1-C5):

- Cookie names: `__Secure-better-auth.session_token` when TripTracker runs on https, plain
  `better-auth.session_token` in local http development. Both are accepted, the `__Secure-`
  one first. The value is signed (`<token>.<hmac>`): it is hashed whole for the cache key and
  forwarded untouched.
- Only Better Auth cookies (names starting with `__Secure-better-auth.` or `better-auth.`) are
  forwarded, never the browser's other cookies. No `Set-Cookie` from the answer is relayed.
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
  when it is set). Only the browser's own visits to TripTracker refresh the session.
- `PLANNER_ALLOWED_EMAILS` has no `*` wildcard (unlike `EMAIL_AMMESSE`); emails compare trimmed
  and lower-cased (`Settings.is_email_allowed`).

Errors use FastAPI's `HTTPException` with `detail = {"code": <AuthErrorCode>, "message":
<Italian text>}`, the API's error envelope (`routes.ErrorBody`). A 401 makes the web app send the
user to `TRIPTRACKER_ORIGIN/accedi?returnTo=<current page>`.

Unknown cookies cannot lock the real user out (decision 19). Every get-session call leaves from
the planner's one egress IP, and TripTracker's Better Auth rate-limits it per IP and path (100
requests in a burst whose requests are less than 10 s apart; `api/rate-limiter` in better-auth
1.7.3). So, without throttling, random cookie values would exhaust that bucket and every
verification would get 429. The defences:

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
  (`<token>.<signature>`, bounded length, URL-safe characters) with 401 and no network call.
- Concurrent checks of one token share a single call (single-flight).
"""

from __future__ import annotations

import asyncio
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

from app.config import normalize_origin

if TYPE_CHECKING:
    from app.config import Settings

SESSION_COOKIE_NAMES: tuple[str, ...] = (
    "__Secure-better-auth.session_token",
    "better-auth.session_token",
)
"""Accepted session cookie names, in order of preference."""

FORWARDED_COOKIE_PREFIXES: tuple[str, ...] = ("__Secure-better-auth.", "better-auth.")
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
    AUTH_UNAVAILABLE = "auth_unavailable"  # 503: TripTracker unreachable, 5xx or unconfigured


AUTH_ERROR_MESSAGES: dict[AuthErrorCode, str] = {
    AuthErrorCode.NOT_AUTHENTICATED: "Accedi a TripTracker per usare il planner.",
    AuthErrorCode.EMAIL_NOT_ALLOWED: "Questo account non è abilitato al planner.",
    AuthErrorCode.BAD_ORIGIN: "Richiesta rifiutata: arriva da un'origine non consentita.",
    AuthErrorCode.AUTH_UNAVAILABLE: (
        "Non riesco a verificare l'accesso con TripTracker. Riprova tra poco."
    ),
}
"""Italian messages shown by the web app (user-facing copy)."""

AUTH_ERROR_STATUS: dict[AuthErrorCode, int] = {
    AuthErrorCode.NOT_AUTHENTICATED: 401,
    AuthErrorCode.EMAIL_NOT_ALLOWED: 403,
    AuthErrorCode.BAD_ORIGIN: 403,
    AuthErrorCode.AUTH_UNAVAILABLE: 503,
}


@dataclass(frozen=True, slots=True)
class CurrentUser:
    """The signed-in user of a request. Only the email is stored with plans (`user_email`)."""

    email: str
    """Lower-cased and trimmed; always in PLANNER_ALLOWED_EMAILS."""
    triptracker_user_id: str | None = None
    """Better Auth's `user.id`; None in AUTH_MODE=local."""


def auth_error(code: AuthErrorCode) -> HTTPException:
    """The `HTTPException` for `code`: status 401/403/503 and the error envelope as detail.
    401 also carries `WWW-Authenticate: Cookie` for well-behaved clients."""
    status = AUTH_ERROR_STATUS[code]
    headers = {"WWW-Authenticate": "Cookie"} if status == 401 else None
    detail = {"code": code.value, "message": AUTH_ERROR_MESSAGES[code], "data": None}
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


def session_cookie(request: Request) -> tuple[str, str] | None:
    """(cookie name, raw value) of the first present name in `SESSION_COOKIE_NAMES`, or None.

    The value is read from the raw header (the first occurrence of the name), untouched; an
    empty value counts as absent."""
    pairs = _request_cookie_pairs(request)
    for name in SESSION_COOKIE_NAMES:
        for cookie_name, value in pairs:
            if cookie_name == name and value:
                return name, value
    return None


def forwarded_cookie_header(request: Request) -> str:
    """The `Cookie` header sent to TripTracker: only the Better Auth cookies of the request,
    values untouched, in their original order."""
    return "; ".join(
        f"{name}={value}"
        for name, value in _request_cookie_pairs(request)
        if name.startswith(FORWARDED_COOKIE_PREFIXES)
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
    """TripTracker could not say who owns the cookie (error, or no budget)."""


_UNAVAILABLE = _Unavailable()
_Outcome = CurrentUser | None | _Unavailable


class SessionVerifier:
    """Asks TripTracker who owns a session cookie. One per process (`app.state.session_verifier`,
    built by `sessions.start_planner`), sharing the application's httpx client."""

    def __init__(
        self,
        settings: Settings,
        http: httpx.AsyncClient,
        *,
        cache: SessionCache | None = None,
        budget: VerificationBudget | None = None,
    ) -> None:
        self._url = httpx.URL(
            f"{settings.triptracker_origin}{GET_SESSION_PATH}", params=GET_SESSION_PARAMS
        )
        self._http = http
        self.cache = cache if cache is not None else SessionCache()
        self.budget = budget if budget is not None else VerificationBudget()
        self._pending: dict[str, asyncio.Task[_Outcome]] = {}

    async def verify(self, cookie_header: str, cache_key: str) -> CurrentUser | None:
        """The user for this cookie, from the cache or from `GET {TRIPTRACKER_ORIGIN}{
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
            pending = asyncio.ensure_future(self._ask_triptracker(cookie_header, cache_key))
            self._pending[cache_key] = pending
            pending.add_done_callback(lambda task: self._forget(cache_key, task))
        # Shielded: a client that disconnects does not cancel the call other requests share.
        outcome = await asyncio.shield(pending)
        if not isinstance(outcome, _Unavailable):
            return outcome
        stale = self.cache.get_stale(cache_key)
        if stale is None:
            raise auth_error(AuthErrorCode.AUTH_UNAVAILABLE)
        log.info("auth_stale_user_served")
        return stale

    def _forget(self, cache_key: str, task: asyncio.Task[_Outcome]) -> None:
        if self._pending.get(cache_key) is task:
            del self._pending[cache_key]
        if not task.cancelled():
            task.exception()  # retrieved, so a crash is never reported as "never retrieved"

    async def _ask_triptracker(self, cookie_header: str, cache_key: str) -> _Outcome:
        """One budgeted get-session call; caches what TripTracker said, or `_UNAVAILABLE`."""
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
                user = parse_get_session(response.json())
            except ValueError:  # json.JSONDecodeError included
                log.warning("auth_get_session_malformed", status=response.status_code)
                return _UNAVAILABLE
        self.cache.put(cache_key, user)
        return user


def parse_get_session(body: Any) -> CurrentUser | None:
    """Pure: Better Auth's get-session JSON -> `CurrentUser` (email lower-cased), None for a
    `null` body. Raises ValueError when a non-null body has no `user.email` string."""
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
    return CurrentUser(
        email=email.strip().lower(),
        triptracker_user_id=user_id if isinstance(user_id, str) and user_id else None,
    )


async def current_user(request: Request) -> CurrentUser:
    """FastAPI dependency for every endpoint except /health.

    Reads `Settings` from `request.app.state.settings`. With AUTH_MODE=local it returns
    `CurrentUser(settings.local_user_email)` without I/O. Otherwise: no session cookie, or a
    value that cannot be one (`plausible_session_token`) -> 401 `not_authenticated` without
    asking TripTracker; `SessionVerifier.verify` (from `request.app.state.session_verifier`)
    None -> 401; email not allowed -> 403 `email_not_allowed`; TripTracker failure with no
    recently verified user for the cookie (or no verifier because the lifespan did not run)
    -> 503. Binds `user_email` to nothing in the logs (the email is personal data).
    """
    settings: Settings = request.app.state.settings
    local_email = settings.local_user_email
    if local_email is not None:
        return CurrentUser(email=local_email)
    cookie = session_cookie(request)
    if cookie is None or not plausible_session_token(cookie[1]):
        raise auth_error(AuthErrorCode.NOT_AUTHENTICATED)
    verifier: SessionVerifier | None = getattr(request.app.state, "session_verifier", None)
    if verifier is None:
        log.error("auth_verifier_missing")
        raise auth_error(AuthErrorCode.AUTH_UNAVAILABLE)
    user = await verifier.verify(forwarded_cookie_header(request), token_cache_key(cookie[1]))
    if user is None:
        raise auth_error(AuthErrorCode.NOT_AUTHENTICATED)
    if not settings.is_email_allowed(user.email):
        raise auth_error(AuthErrorCode.EMAIL_NOT_ALLOWED)
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
        raise auth_error(AuthErrorCode.BAD_ORIGIN)


CurrentUserDep = Annotated[CurrentUser, Depends(current_user)]
"""`user: CurrentUserDep` in a route signature."""

RequireOrigin = Depends(require_origin)
"""`dependencies=[RequireOrigin]` on state-changing routes."""
