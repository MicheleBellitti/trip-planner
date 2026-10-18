"""Auth (app/auth.py): TripTracker session check, its 60 s cache, the allowlist, the Origin check.

Spec row "Unit, backend - auth.py": no cookie 401, email not allowed 403, wrong Origin 403,
cache expired after 60 seconds. TripTracker's get-session is mocked with respx; the cache clock
is moved with time-machine (which drives `time.time`, injected as the cache's clock) or a fake.
Also decision 19's flood defences: the verification budget, stale-if-error, the separate
signed-out cache, the cookie pre-filter and single-flight.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from collections.abc import AsyncIterator, Callable, Iterator
from typing import Any

import httpx
import pytest
import respx
import time_machine
from fastapi import FastAPI, HTTPException, Request

from app.auth import (
    ATLAS_AUTH_ERROR_MESSAGES,
    AUTH_ERROR_MESSAGES,
    GET_SESSION_PARAMS,
    GET_SESSION_PATH,
    MAX_SESSION_COOKIE_LENGTH,
    SESSION_CACHE_TTL_SECONDS,
    STALE_USER_SECONDS,
    VERIFY_BURST_LIMIT,
    VERIFY_BURST_MISS_LIMIT,
    VERIFY_QUIET_SECONDS,
    AuthErrorCode,
    CurrentUser,
    CurrentUserDep,
    RequireOrigin,
    SessionCache,
    SessionVerifier,
    VerificationBudget,
    auth_error,
    auth_messages,
    current_user,
    forwarded_cookie_header,
    forwarded_cookie_prefixes,
    origin_allowed,
    parse_get_session,
    plausible_session_token,
    session_cookie,
    session_cookie_names,
    token_cache_key,
)
from app.config import Settings

TRIPTRACKER = "https://viaggi.bellittim.com"
FRONTEND = "https://atlas.bellittim.com"
GET_SESSION_URL = f"{TRIPTRACKER}{GET_SESSION_PATH}?disableRefresh=true"
SECURE_COOKIE = "__Secure-better-auth.session_token"
PLAIN_COOKIE = "better-auth.session_token"
SIGNED_TOKEN = "tok3n-abc.SiGnAtUrE%2Bx%3D"  # `<token>.<hmac>`, URL-encoded, as Better Auth sets it


def session_body(email: str = "test@example.com", user_id: str = "usr_1") -> dict[str, Any]:
    """A get-session answer for a signed-in user (Better Auth 1.7 shape)."""
    return {
        "session": {"id": "ses_1", "token": "secret-token", "userId": user_id},
        "user": {"id": user_id, "email": email, "name": "Michele", "emailVerified": True},
    }


def make_request(headers: list[tuple[str, str]], method: str = "GET") -> Request:
    scope: dict[str, Any] = {
        "type": "http",
        "method": method,
        "path": "/plans",
        "headers": [(name.lower().encode(), value.encode()) for name, value in headers],
    }
    return Request(scope)


@pytest.fixture
def mock_tt() -> Iterator[respx.MockRouter]:
    """respx over every httpx request; unmatched requests fail the test."""
    with respx.mock(assert_all_called=False, assert_all_mocked=True) as router:
        yield router


@pytest.fixture
def triptracker_settings(make_settings: Callable[..., Settings]) -> Settings:
    return make_settings(auth_mode="triptracker")


# --- pure helpers -------------------------------------------------------------------------------


def test_session_cookie_prefers_the_secure_name() -> None:
    request = make_request(
        [("Cookie", f"{PLAIN_COOKIE}=plain; theme=dark; {SECURE_COOKIE}={SIGNED_TOKEN}")]
    )

    assert session_cookie(request) == (SECURE_COOKIE, SIGNED_TOKEN)


def test_session_cookie_accepts_the_local_http_name_and_ignores_empty_values() -> None:
    assert session_cookie(make_request([("Cookie", f"{PLAIN_COOKIE}=abc.def")])) == (
        PLAIN_COOKIE,
        "abc.def",
    )
    assert session_cookie(make_request([("Cookie", f"{SECURE_COOKIE}=; theme=dark")])) is None
    assert session_cookie(make_request([("Cookie", "theme=dark")])) is None
    assert session_cookie(make_request([])) is None


def test_only_better_auth_cookies_are_forwarded_untouched_and_in_order() -> None:
    request = make_request(
        [
            ("Cookie", f"_ga=GA1.2.3; {SECURE_COOKIE}={SIGNED_TOKEN}; csrftoken=x"),
            ("Cookie", "better-auth.dont_remember=true; other=1"),
        ]
    )

    assert forwarded_cookie_header(request) == (
        f"{SECURE_COOKIE}={SIGNED_TOKEN}; better-auth.dont_remember=true"
    )


BETTER_AUTH_TOKEN = "Q2xhdWRlQ29kZVNlc3Npb25Ub2tlbjEy"
RAW_HMAC = "Z+2gzCIkOtax4IFuLyHtehCZ2pB9vkgi8UDv60tlwFg="
REAL_SHAPED_TOKEN = f"{BETTER_AUTH_TOKEN}.Z%2B2gzCIkOtax4IFuLyHtehCZ2pB9vkgi8UDv60tlwFg%3D"
"""A 32-character token, a dot, a URL-encoded 44-character base64 HMAC (Better Auth)."""


@pytest.mark.parametrize(
    "value",
    [
        SIGNED_TOKEN,
        REAL_SHAPED_TOKEN,
        "abc.def",
        f"{BETTER_AUTH_TOKEN}.{RAW_HMAC}",  # signature not URL-encoded
        "a" * 200 + "." + "b" * (MAX_SESSION_COOKIE_LENGTH - 201),
    ],
)
def test_plausible_session_tokens(value: str) -> None:
    assert plausible_session_token(value)


@pytest.mark.parametrize(
    "value",
    [
        "x",
        "",
        "nodot",
        "abc.",
        ".def",
        "abc.def ghi",
        'abc."def"',
        "abc.d;ef",
        "abc.dèf",
        "abc.d\\ef",
        "a" * 200 + "." + "b" * (MAX_SESSION_COOKIE_LENGTH - 200),
    ],
)
def test_implausible_session_tokens(value: str) -> None:
    assert not plausible_session_token(value)


def test_cache_key_is_the_sha256_of_the_raw_signed_value() -> None:
    assert token_cache_key(SIGNED_TOKEN) == hashlib.sha256(SIGNED_TOKEN.encode()).hexdigest()
    assert SIGNED_TOKEN not in token_cache_key(SIGNED_TOKEN)


def test_parse_get_session() -> None:
    assert parse_get_session(None) is None
    assert parse_get_session(session_body(email="  Test@Example.COM ")) == CurrentUser(
        email="test@example.com", auth_user_id="usr_1"
    )
    for malformed in ({}, {"user": None}, {"user": {"email": ""}}, {"user": {"email": 3}}, []):
        with pytest.raises(ValueError, match="get-session"):
            parse_get_session(malformed)
    # Without `require_user_id` (TripTracker's provider) a missing id is tolerated.
    assert parse_get_session({"user": {"email": "a@example.com"}}) == CurrentUser("a@example.com")


def test_parse_get_session_requires_the_id_when_plans_store_it() -> None:
    assert parse_get_session(session_body(), require_user_id=True) == CurrentUser(
        email="test@example.com", auth_user_id="usr_1"
    )
    assert parse_get_session(None, require_user_id=True) is None  # signed out stays signed out
    for user_id in (None, "", 7, ["usr_1"]):
        body = {"user": {"email": "a@example.com", "id": user_id}}
        with pytest.raises(ValueError, match="get-session user has no id"):
            parse_get_session(body, require_user_id=True)
    with pytest.raises(ValueError, match="get-session user has no id"):
        parse_get_session({"user": {"email": "a@example.com"}}, require_user_id=True)


def test_auth_errors_use_the_api_envelope() -> None:
    expected = {
        AuthErrorCode.NOT_AUTHENTICATED: 401,
        AuthErrorCode.EMAIL_NOT_ALLOWED: 403,
        AuthErrorCode.BAD_ORIGIN: 403,
        AuthErrorCode.AUTH_UNAVAILABLE: 503,
    }
    for code, status in expected.items():
        error = auth_error(code)
        assert error.status_code == status
        assert error.detail == {
            "code": code.value,
            "message": AUTH_ERROR_MESSAGES[code],
            "data": None,
        }
    assert auth_error(AuthErrorCode.NOT_AUTHENTICATED).headers == {"WWW-Authenticate": "Cookie"}
    assert auth_error(AuthErrorCode.BAD_ORIGIN).headers is None


@pytest.mark.parametrize(
    ("origin", "allowed"),
    [
        (FRONTEND, True),
        (f"{FRONTEND}/", True),  # normalized like config.normalize_origin
        ("https://ATLAS.bellittim.com", True),
        (None, False),
        ("", False),
        ("null", False),
        ("http://atlas.bellittim.com", False),
        ("https://atlas.bellittim.com:8443", False),
        ("https://evil.bellittim.com", False),
        (TRIPTRACKER, False),
        ("https://atlas.bellittim.com.evil.example", False),
        ("https://atlas.bellittim.com/path", False),
        ("not an origin", False),
    ],
)
def test_origin_must_be_exactly_the_frontend(origin: str | None, allowed: bool) -> None:
    assert origin_allowed(origin, FRONTEND) is allowed


# --- the cache ----------------------------------------------------------------------------------


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def test_cache_entries_expire_after_the_ttl() -> None:
    clock = FakeClock()
    cache = SessionCache(clock=clock)
    user = CurrentUser("test@example.com")
    cache.put("user", user)
    cache.put("signed-out", None)

    clock.now += 59.9
    assert cache.get("user") == (True, user)
    assert cache.get("signed-out") == (True, None)

    clock.now += 0.1  # exactly 60 s
    assert cache.get("user") == (False, None)
    assert cache.get("signed-out") == (False, None)
    assert len(cache) == 1  # the user stays, stale, for get_stale only


def test_a_verified_user_stays_available_as_stale_for_the_grace_period() -> None:
    clock = FakeClock()
    cache = SessionCache(clock=clock)
    user = CurrentUser("test@example.com")
    cache.put("user", user)

    assert cache.get_stale("user") == user  # fresh counts too
    clock.now += SESSION_CACHE_TTL_SECONDS + STALE_USER_SECONDS - 0.1
    assert cache.get("user") == (False, None)
    assert cache.get_stale("user") == user

    clock.now += 0.1
    assert cache.get_stale("user") is None
    assert cache.get_stale("never-seen") is None
    assert len(cache) == 0


def test_signed_out_evicts_the_user_at_once_and_a_user_replaces_signed_out() -> None:
    cache = SessionCache(clock=FakeClock())
    user = CurrentUser("test@example.com")
    cache.put("k", user)

    cache.put("k", None)  # revoked in TripTracker

    assert cache.get("k") == (True, None)
    assert cache.get_stale("k") is None
    cache.put("k", user)  # signed in again
    assert cache.get("k") == (True, user)
    assert len(cache) == 1


def test_junk_signed_out_entries_never_evict_a_user() -> None:
    cache = SessionCache(clock=FakeClock(), max_entries=2, max_signed_out=3)
    user = CurrentUser("test@example.com")
    cache.put("user", user)

    for index in range(100):
        cache.put(f"junk-{index}", None)

    assert cache.get("user") == (True, user)
    assert cache.get("junk-99") == (True, None)
    assert cache.get("junk-96") == (False, None)  # oldest junk evicted first
    assert len(cache) == 1 + 3


def test_cache_is_bounded_oldest_first() -> None:
    cache = SessionCache(clock=FakeClock(), max_entries=2)
    cache.put("a", CurrentUser("a@example.com"))
    cache.put("b", CurrentUser("b@example.com"))
    cache.put("a", CurrentUser("a@example.com"))  # refreshed: now the newest
    cache.put("c", CurrentUser("c@example.com"))

    assert cache.get("b") == (False, None)
    assert cache.get("a")[0]
    assert cache.get("c")[0]
    cache.clear()
    assert len(cache) == 0


def test_cache_defaults_to_the_monotonic_clock() -> None:
    cache = SessionCache()
    cache.put("k", None)
    assert cache.get("k") == (True, None)
    with pytest.raises(ValueError, match="ttl"):
        SessionCache(ttl=0)
    with pytest.raises(ValueError, match="stale_for"):
        SessionCache(stale_for=-1)
    with pytest.raises(ValueError, match="cache sizes"):
        SessionCache(max_signed_out=0)


# --- the verification budget --------------------------------------------------------------------


def test_budget_caps_a_burst_and_reserves_room_for_known_users() -> None:
    clock = FakeClock()
    budget = VerificationBudget(limit=5, miss_limit=3, quiet_seconds=10, clock=clock)

    assert [budget.try_acquire(known=False) for _ in range(4)] == [True, True, True, False]
    assert budget.refused == 1
    assert [budget.try_acquire(known=True) for _ in range(3)] == [True, True, False]
    assert budget.try_acquire(known=False) is False
    assert budget.refused == 3


def test_budget_resets_only_after_a_quiet_period_without_calls() -> None:
    clock = FakeClock()
    budget = VerificationBudget(limit=2, miss_limit=2, quiet_seconds=10, clock=clock)
    assert budget.try_acquire(known=False)
    clock.now += 9
    assert budget.try_acquire(known=False)  # 9 s after the first: same burst
    clock.now += 9.9
    assert budget.try_acquire(known=False) is False  # refusals don't extend the burst
    clock.now += 0.1  # 10 s after the last call that went out
    assert budget.try_acquire(known=False)
    assert budget.refused == 0


def test_budget_defaults_stay_under_better_auths_limit() -> None:
    """Better Auth 1.7.3 (schema-notes §6): 100 requests per IP and path until 10 s pass without
    one. The planner's burst stays at half of that, and ends only after more than 10 s."""
    assert VERIFY_BURST_MISS_LIMIT < VERIFY_BURST_LIMIT <= 100 // 2
    assert VERIFY_QUIET_SECONDS > 10
    budget = VerificationBudget()
    assert sum(budget.try_acquire(known=False) for _ in range(100)) == VERIFY_BURST_MISS_LIMIT
    with pytest.raises(ValueError, match="miss_limit"):
        VerificationBudget(limit=2, miss_limit=3)
    with pytest.raises(ValueError, match="quiet_seconds"):
        VerificationBudget(quiet_seconds=0)


# --- SessionVerifier against a mocked TripTracker ----------------------------------------------


@pytest.fixture
async def http() -> AsyncIterator[httpx.AsyncClient]:
    async with httpx.AsyncClient(follow_redirects=False) as client:
        yield client


async def test_verify_asks_get_session_once_and_caches_the_user(
    triptracker_settings: Settings, http: httpx.AsyncClient, mock_tt: respx.MockRouter
) -> None:
    route = mock_tt.get(GET_SESSION_URL).respond(200, json=session_body())
    verifier = SessionVerifier(triptracker_settings, http)
    cookie = f"{SECURE_COOKIE}={SIGNED_TOKEN}"

    first = await verifier.verify(cookie, token_cache_key(SIGNED_TOKEN))
    second = await verifier.verify(cookie, token_cache_key(SIGNED_TOKEN))

    assert first == second == CurrentUser("test@example.com", "usr_1")
    assert route.call_count == 1
    assert route.calls[0].request.headers["cookie"] == cookie


async def test_verify_caches_signed_out_too(
    triptracker_settings: Settings, http: httpx.AsyncClient, mock_tt: respx.MockRouter
) -> None:
    route = mock_tt.get(GET_SESSION_URL).respond(200, content=b"null")
    verifier = SessionVerifier(triptracker_settings, http)

    assert await verifier.verify("c=1", "key") is None
    assert await verifier.verify("c=1", "key") is None
    assert route.call_count == 1


async def test_verify_maps_a_401_to_signed_out(
    triptracker_settings: Settings, http: httpx.AsyncClient, mock_tt: respx.MockRouter
) -> None:
    mock_tt.get(GET_SESSION_URL).respond(401, json={"message": "Unauthorized"})

    assert await SessionVerifier(triptracker_settings, http).verify("c=1", "key") is None


@pytest.mark.parametrize(
    "answer",
    [
        httpx.Response(503, json={"message": "Gli account non sono configurati su questo server."}),
        httpx.Response(500, text="boom"),
        httpx.Response(429, text="slow down"),
        httpx.Response(302, headers={"Location": "https://evil.example/"}),
        httpx.Response(200, text="<html>not json</html>"),
        httpx.Response(200, json={"user": {"name": "no email"}}),
    ],
    ids=["503", "500", "429", "redirect", "not-json", "no-email"],
)
async def test_verify_failures_are_503_and_never_cached(
    triptracker_settings: Settings,
    http: httpx.AsyncClient,
    mock_tt: respx.MockRouter,
    answer: httpx.Response,
) -> None:
    route = mock_tt.get(GET_SESSION_URL)
    route.side_effect = [answer, httpx.Response(200, json=session_body())]
    verifier = SessionVerifier(triptracker_settings, http)

    with pytest.raises(HTTPException) as caught:
        await verifier.verify("c=1", "key")

    assert caught.value.status_code == 503
    error_detail: Any = caught.value.detail
    assert error_detail["code"] == "auth_unavailable"
    # Not cached: the next call asks again and gets the user.
    assert await verifier.verify("c=1", "key") == CurrentUser("test@example.com", "usr_1")
    assert route.call_count == 2


async def test_verify_network_errors_are_503(
    triptracker_settings: Settings, http: httpx.AsyncClient, mock_tt: respx.MockRouter
) -> None:
    mock_tt.get(GET_SESSION_URL).side_effect = httpx.ConnectTimeout("timed out")

    with pytest.raises(HTTPException) as caught:
        await SessionVerifier(triptracker_settings, http).verify("c=1", "key")

    assert caught.value.status_code == 503


async def test_cache_expires_after_60_seconds_with_time_machine(
    triptracker_settings: Settings, http: httpx.AsyncClient, mock_tt: respx.MockRouter
) -> None:
    """Spec row: a revoked session stops working within a minute."""
    route = mock_tt.get(GET_SESSION_URL)
    route.side_effect = [
        httpx.Response(200, json=session_body()),
        httpx.Response(200, content=b"null"),  # revoked in TripTracker meanwhile
    ]
    with time_machine.travel("2026-10-12 10:00:00+02:00", tick=False) as traveller:
        verifier = SessionVerifier(triptracker_settings, http, cache=SessionCache(clock=time.time))
        assert await verifier.verify("c=1", "key") == CurrentUser("test@example.com", "usr_1")

        traveller.shift(59)
        assert await verifier.verify("c=1", "key") == CurrentUser("test@example.com", "usr_1")
        assert route.call_count == 1

        traveller.shift(2)  # 61 s after the first answer
        assert await verifier.verify("c=1", "key") is None
        assert route.call_count == 2


# --- the dependencies inside an app ---------------------------------------------------------------


def auth_app(settings: Settings, verifier: SessionVerifier | None) -> FastAPI:
    """A minimal app with one read and one state-changing route guarded like the real ones."""
    app = FastAPI()
    app.state.settings = settings
    if verifier is not None:
        app.state.session_verifier = verifier

    @app.get("/me")
    async def me(user: CurrentUserDep) -> dict[str, str | None]:
        return {"email": user.email, "id": user.auth_user_id}

    @app.post("/change", dependencies=[RequireOrigin])
    async def change(user: CurrentUserDep) -> dict[str, str]:
        return {"email": user.email}

    return app


def asgi_client(app: FastAPI) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver")


async def test_no_cookie_is_401_without_asking_triptracker(
    triptracker_settings: Settings, http: httpx.AsyncClient, mock_tt: respx.MockRouter
) -> None:
    route = mock_tt.get(GET_SESSION_URL).respond(200, json=session_body())
    app = auth_app(triptracker_settings, SessionVerifier(triptracker_settings, http))

    async with asgi_client(app) as client:
        response = await client.get("/me", headers={"Cookie": "theme=dark"})

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Cookie"
    assert response.json() == {
        "detail": {
            "code": "not_authenticated",
            "message": AUTH_ERROR_MESSAGES[AuthErrorCode.NOT_AUTHENTICATED],
            "data": None,
        }
    }
    assert route.call_count == 0


async def test_signed_out_cookie_is_401(
    triptracker_settings: Settings, http: httpx.AsyncClient, mock_tt: respx.MockRouter
) -> None:
    mock_tt.get(GET_SESSION_URL).respond(200, content=b"null")
    app = auth_app(triptracker_settings, SessionVerifier(triptracker_settings, http))

    async with asgi_client(app) as client:
        response = await client.get("/me", headers={"Cookie": f"{SECURE_COOKIE}={SIGNED_TOKEN}"})

    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "not_authenticated"


async def test_email_not_allowed_is_403(
    triptracker_settings: Settings, http: httpx.AsyncClient, mock_tt: respx.MockRouter
) -> None:
    mock_tt.get(GET_SESSION_URL).respond(200, json=session_body(email="someone@else.com"))
    app = auth_app(triptracker_settings, SessionVerifier(triptracker_settings, http))

    async with asgi_client(app) as client:
        response = await client.get("/me", headers={"Cookie": f"{SECURE_COOKIE}={SIGNED_TOKEN}"})

    assert response.status_code == 403
    assert response.json()["detail"] == {
        "code": "email_not_allowed",
        "message": AUTH_ERROR_MESSAGES[AuthErrorCode.EMAIL_NOT_ALLOWED],
        "data": None,
    }


async def test_allowed_user_passes_case_insensitively_and_only_auth_cookies_travel(
    triptracker_settings: Settings, http: httpx.AsyncClient, mock_tt: respx.MockRouter
) -> None:
    route = mock_tt.get(GET_SESSION_URL).respond(200, json=session_body(email="Test@Example.com"))
    app = auth_app(triptracker_settings, SessionVerifier(triptracker_settings, http))

    async with asgi_client(app) as client:
        response = await client.get(
            "/me", headers={"Cookie": f"_ga=1; {PLAIN_COOKIE}={SIGNED_TOKEN}; theme=dark"}
        )

    assert response.status_code == 200
    assert response.json() == {"email": "test@example.com", "id": "usr_1"}
    sent = route.calls[0].request
    assert sent.headers["cookie"] == f"{PLAIN_COOKIE}={SIGNED_TOKEN}"
    assert sent.url == GET_SESSION_URL


async def test_the_session_check_never_refreshes_the_session(
    triptracker_settings: Settings, http: httpx.AsyncClient, mock_tt: respx.MockRouter
) -> None:
    """Better Auth 1.7.3 extends a session older than `updateAge` on get-session and answers
    with a Set-Cookie the planner drops; `disableRefresh=true` makes the check read-only."""
    assert GET_SESSION_PARAMS == {"disableRefresh": "true"}
    route = mock_tt.get(f"{TRIPTRACKER}{GET_SESSION_PATH}").respond(200, json=session_body())
    verifier = SessionVerifier(triptracker_settings, http)

    user = await verifier.verify(f"{SECURE_COOKIE}={SIGNED_TOKEN}", "key-1")

    assert user is not None
    assert user.email == "test@example.com"
    [call] = route.calls
    assert call.request.method == "GET"  # POST would be refused without deferSessionRefresh
    assert call.request.url.path == GET_SESSION_PATH
    assert dict(call.request.url.params) == {"disableRefresh": "true"}


async def test_triptracker_down_is_503(
    triptracker_settings: Settings, http: httpx.AsyncClient, mock_tt: respx.MockRouter
) -> None:
    mock_tt.get(GET_SESSION_URL).side_effect = httpx.ConnectError("refused")
    app = auth_app(triptracker_settings, SessionVerifier(triptracker_settings, http))

    async with asgi_client(app) as client:
        response = await client.get("/me", headers={"Cookie": f"{SECURE_COOKIE}={SIGNED_TOKEN}"})

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "auth_unavailable"


async def test_no_verifier_is_503(triptracker_settings: Settings) -> None:
    async with asgi_client(auth_app(triptracker_settings, None)) as client:
        response = await client.get("/me", headers={"Cookie": f"{SECURE_COOKIE}={SIGNED_TOKEN}"})

    assert response.status_code == 503


async def test_allowlist_changes_apply_at_once_even_with_a_cached_user(
    make_settings: Callable[..., Settings], http: httpx.AsyncClient, mock_tt: respx.MockRouter
) -> None:
    route = mock_tt.get(GET_SESSION_URL).respond(200, json=session_body())
    before = make_settings(auth_mode="triptracker")
    verifier = SessionVerifier(before, http)
    app = auth_app(before, verifier)
    cookie = {"Cookie": f"{SECURE_COOKIE}={SIGNED_TOKEN}"}

    async with asgi_client(app) as client:
        assert (await client.get("/me", headers=cookie)).status_code == 200
        app.state.settings = make_settings(
            auth_mode="triptracker", planner_allowed_emails="other@example.com"
        )
        assert (await client.get("/me", headers=cookie)).status_code == 403

    assert route.call_count == 1  # the second answer came from the cache


@pytest.mark.parametrize("allowed", ["", "*", "*@example.com"])
async def test_empty_allowlist_lets_nobody_in_and_there_is_no_wildcard(
    make_settings: Callable[..., Settings],
    http: httpx.AsyncClient,
    mock_tt: respx.MockRouter,
    allowed: str,
) -> None:
    mock_tt.get(GET_SESSION_URL).respond(200, json=session_body())
    settings = make_settings(auth_mode="triptracker", planner_allowed_emails=allowed)
    app = auth_app(settings, SessionVerifier(settings, http))

    async with asgi_client(app) as client:
        response = await client.get("/me", headers={"Cookie": f"{SECURE_COOKIE}={SIGNED_TOKEN}"})

    assert response.status_code == 403


async def test_cache_expired_after_60_seconds_through_the_dependency(
    triptracker_settings: Settings, http: httpx.AsyncClient, mock_tt: respx.MockRouter
) -> None:
    route = mock_tt.get(GET_SESSION_URL)
    route.side_effect = [
        httpx.Response(200, json=session_body()),
        httpx.Response(200, content=b"null"),
    ]
    cookie = {"Cookie": f"{SECURE_COOKIE}={SIGNED_TOKEN}"}
    with time_machine.travel("2026-10-12 10:00:00+02:00", tick=False) as traveller:
        verifier = SessionVerifier(triptracker_settings, http, cache=SessionCache(clock=time.time))
        async with asgi_client(auth_app(triptracker_settings, verifier)) as client:
            assert (await client.get("/me", headers=cookie)).status_code == 200
            traveller.shift(30)
            assert (await client.get("/me", headers=cookie)).status_code == 200
            traveller.shift(31)
            assert (await client.get("/me", headers=cookie)).status_code == 401

    assert route.call_count == 2


async def test_local_mode_is_the_first_allowed_email_without_network(
    make_settings: Callable[..., Settings], mock_tt: respx.MockRouter
) -> None:
    settings = make_settings(planner_allowed_emails="Dev@Example.com, other@example.com")
    assert settings.auth_mode == "local"

    async with asgi_client(auth_app(settings, None)) as client:
        response = await client.get("/me")

    assert response.status_code == 200
    assert response.json() == {"email": "dev@example.com", "id": None}
    assert not mock_tt.calls


async def test_current_user_reads_the_apps_settings(make_settings: Callable[..., Settings]) -> None:
    app = auth_app(make_settings(), None)
    request = Request({"type": "http", "method": "GET", "headers": [], "app": app})

    assert await current_user(request) == CurrentUser("test@example.com")


# --- the Origin check -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("headers", "status"),
    [
        ({"Origin": FRONTEND}, 200),
        ({"Origin": "https://evil.bellittim.com"}, 403),
        ({"Origin": TRIPTRACKER}, 403),
        ({"Origin": "null"}, 403),
        ({}, 403),
    ],
    ids=["frontend", "sibling-subdomain", "triptracker", "null", "missing"],
)
async def test_state_changing_requests_need_the_frontend_origin(
    make_settings: Callable[..., Settings], headers: dict[str, str], status: int
) -> None:
    async with asgi_client(auth_app(make_settings(), None)) as client:
        response = await client.post("/change", headers=headers)

    assert response.status_code == status
    if status == 403:
        assert response.json()["detail"] == {
            "code": "bad_origin",
            "message": AUTH_ERROR_MESSAGES[AuthErrorCode.BAD_ORIGIN],
            "data": None,
        }


async def test_wrong_origin_is_refused_before_asking_triptracker(
    triptracker_settings: Settings, http: httpx.AsyncClient, mock_tt: respx.MockRouter
) -> None:
    route = mock_tt.get(GET_SESSION_URL).respond(200, json=session_body())
    app = auth_app(triptracker_settings, SessionVerifier(triptracker_settings, http))

    async with asgi_client(app) as client:
        response = await client.post(
            "/change",
            headers={"Origin": "https://evil.example", "Cookie": f"{SECURE_COOKIE}={SIGNED_TOKEN}"},
        )

    assert response.status_code == 403
    assert route.call_count == 0


async def test_safe_methods_are_never_origin_checked(
    make_settings: Callable[..., Settings],
) -> None:
    async with asgi_client(auth_app(make_settings(), None)) as client:
        response = await client.get("/me", headers={"Origin": "https://evil.example"})

    assert response.status_code == 200


def test_error_bodies_are_json_serializable() -> None:
    for code in AuthErrorCode:
        json.dumps(auth_error(code).detail)


# --- flood defences (decision 19) ------------------------------------------------------------


class BetterAuthLimiter:
    """Better Auth 1.7.3's rate limiter for one IP and path (`decideConsume`): a request more
    than `window` seconds after the last allowed one starts a new count; past `max` it is 429
    and does not move the count's start."""

    def __init__(self, clock: Callable[[], float], *, window: float = 10, limit: int = 100) -> None:
        self._clock = clock
        self._window = window
        self._limit = limit
        self._count = 0
        self._last: float | None = None
        self.limited = 0

    def allow(self) -> bool:
        now = self._clock()
        if self._last is None or now - self._last >= self._window:
            self._count, self._last = 1, now
            return True
        if self._count >= self._limit:
            self.limited += 1
            return False
        self._count += 1
        self._last = now
        return True


def junk_cookie(index: int) -> str:
    """A random-looking but well-formed signed cookie value nobody owns."""
    return f"junk{index:028d}.c2lnbmF0dXJlLW9mLWEtZm9yZ2VkLWNvb2tpZS0xMjM0%3D"


async def test_a_flood_of_unknown_cookies_never_locks_the_real_user_out(
    triptracker_settings: Settings, http: httpx.AsyncClient, mock_tt: respx.MockRouter
) -> None:
    """Reviewer's scenario: an attacker sends ~10 requests a second with random session cookies
    for 70 s. The planner's calls stay under TripTracker's rate limit, junk tokens beyond the
    budget get 503 without a call, and the real user is revalidated after the TTL."""
    clock = FakeClock()
    limiter = BetterAuthLimiter(clock)
    user_cookie = f"{SECURE_COOKIE}={SIGNED_TOKEN}"

    def get_session(request: httpx.Request) -> httpx.Response:
        if not limiter.allow():
            return httpx.Response(429, json={"message": "Too many requests."})
        if request.headers["cookie"] == user_cookie:
            return httpx.Response(200, json=session_body())
        return httpx.Response(200, content=b"null")

    route = mock_tt.get(GET_SESSION_URL).mock(side_effect=get_session)
    verifier = SessionVerifier(
        triptracker_settings,
        http,
        cache=SessionCache(clock=clock),
        budget=VerificationBudget(clock=clock),
    )
    statuses: dict[int, int] = {}
    async with asgi_client(auth_app(triptracker_settings, verifier)) as client:
        assert (await client.get("/me", headers={"Cookie": user_cookie})).status_code == 200

        for index in range(700):  # 70 s at 10 requests a second
            clock.now += 0.1
            cookie = {"Cookie": f"{SECURE_COOKIE}={junk_cookie(index)}"}
            status = (await client.get("/me", headers=cookie)).status_code
            statuses[status] = statuses.get(status, 0) + 1
            if index == 650:  # 65 s: past the user's 60 s TTL, mid-flood
                user = await client.get("/me", headers={"Cookie": user_cookie})
                assert user.status_code == 200

    assert limiter.limited == 0  # TripTracker never had to answer 429
    assert set(statuses) == {401, 503}
    junk_calls = route.call_count - 2  # minus the user's two verifications
    assert junk_calls == statuses[401]
    # Each burst ends with VERIFY_QUIET_SECONDS of silence: at most one burst per quiet period.
    assert junk_calls <= VERIFY_BURST_MISS_LIMIT * (1 + int(70 // VERIFY_QUIET_SECONDS))


async def test_a_verified_user_is_served_stale_while_triptracker_fails(
    triptracker_settings: Settings, http: httpx.AsyncClient, mock_tt: respx.MockRouter
) -> None:
    clock = FakeClock()
    route = mock_tt.get(GET_SESSION_URL)
    route.side_effect = [
        httpx.Response(200, json=session_body()),
        httpx.Response(429, json={"message": "Too many requests."}),
        httpx.Response(503, json={"message": "down"}),
        httpx.ConnectError("refused"),
        httpx.Response(429, json={"message": "Too many requests."}),
    ]
    verifier = SessionVerifier(triptracker_settings, http, cache=SessionCache(clock=clock))
    key = token_cache_key(SIGNED_TOKEN)
    user = CurrentUser("test@example.com", "usr_1")

    assert await verifier.verify("c=1", key) == user
    for _ in range(3):  # 429, 503, network error: the last good answer stands
        clock.now += SESSION_CACHE_TTL_SECONDS
        assert await verifier.verify("c=1", key) == user
    assert route.call_count == 4

    # Past the grace period the failure shows again.
    clock.now += STALE_USER_SECONDS
    with pytest.raises(HTTPException) as caught:
        await verifier.verify("c=1", key)
    assert caught.value.status_code == 503
    assert route.call_count == 5


async def test_revocation_still_wins_over_a_stale_user(
    triptracker_settings: Settings, http: httpx.AsyncClient, mock_tt: respx.MockRouter
) -> None:
    """A 200 `null` (or 401) evicts the user at once: a later TripTracker failure cannot bring
    the revoked session back."""
    clock = FakeClock()
    route = mock_tt.get(GET_SESSION_URL)
    route.side_effect = [
        httpx.Response(200, json=session_body()),
        httpx.Response(200, content=b"null"),
        httpx.Response(503, json={"message": "down"}),
    ]
    verifier = SessionVerifier(triptracker_settings, http, cache=SessionCache(clock=clock))
    key = token_cache_key(SIGNED_TOKEN)

    assert await verifier.verify("c=1", key) is not None
    clock.now += SESSION_CACHE_TTL_SECONDS
    assert await verifier.verify("c=1", key) is None
    clock.now += SESSION_CACHE_TTL_SECONDS
    with pytest.raises(HTTPException) as caught:
        await verifier.verify("c=1", key)
    assert caught.value.status_code == 503


async def test_an_empty_budget_refuses_unknown_tokens_but_not_known_users(
    triptracker_settings: Settings, http: httpx.AsyncClient, mock_tt: respx.MockRouter
) -> None:
    clock = FakeClock()
    route = mock_tt.get(GET_SESSION_URL).respond(200, json=session_body())
    budget = VerificationBudget(limit=2, miss_limit=1, quiet_seconds=10, clock=clock)
    verifier = SessionVerifier(
        triptracker_settings, http, cache=SessionCache(ttl=5, clock=clock), budget=budget
    )

    assert await verifier.verify("c=1", "known") is not None  # the burst's only miss
    with pytest.raises(HTTPException) as caught:
        await verifier.verify("c=2", "unknown")
    assert caught.value.status_code == 503
    assert route.call_count == 1  # refused without calling TripTracker

    clock.now += 5  # the user's entry is past its TTL; the burst is still open
    assert await verifier.verify("c=1", "known") is not None
    assert route.call_count == 2  # a revalidation, from the room reserved for known users


async def test_concurrent_checks_of_one_cookie_share_one_call(
    triptracker_settings: Settings,
) -> None:
    release = asyncio.Event()
    calls: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        await release.wait()
        return httpx.Response(200, json=session_body())

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as mocked:
        verifier = SessionVerifier(triptracker_settings, mocked)
        waiting = [asyncio.create_task(verifier.verify("c=1", "key")) for _ in range(5)]
        other = asyncio.create_task(verifier.verify("c=2", "other"))
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        release.set()
        users = await asyncio.gather(*waiting, other)

    assert len(calls) == 2  # one per distinct cookie
    assert all(user == CurrentUser("test@example.com", "usr_1") for user in users)


async def test_an_implausible_cookie_is_401_without_asking_triptracker(
    triptracker_settings: Settings, http: httpx.AsyncClient, mock_tt: respx.MockRouter
) -> None:
    route = mock_tt.get(GET_SESSION_URL).respond(200, json=session_body())
    app = auth_app(triptracker_settings, SessionVerifier(triptracker_settings, http))

    async with asgi_client(app) as client:
        for value in ("x", "a" * (MAX_SESSION_COOKIE_LENGTH + 1), "no-signature"):
            response = await client.get("/me", headers={"Cookie": f"{SECURE_COOKIE}={value}"})
            assert response.status_code == 401
            assert response.json()["detail"]["code"] == "not_authenticated"

    assert route.call_count == 0


# --- AUTH_MODE=atlas: the web app's own accounts ------------------------------------------------

ATLAS_GET_SESSION_URL = f"{FRONTEND}{GET_SESSION_PATH}?disableRefresh=true"
ATLAS_SECURE_COOKIE = "__Secure-atlas.session_token"
ATLAS_PLAIN_COOKIE = "atlas.session_token"


@pytest.fixture
def atlas_settings(make_settings: Callable[..., Settings]) -> Settings:
    return make_settings(auth_mode="atlas")


def test_cookie_names_follow_the_prefix() -> None:
    assert session_cookie_names() == (SECURE_COOKIE, PLAIN_COOKIE)
    assert session_cookie_names("atlas") == (ATLAS_SECURE_COOKIE, ATLAS_PLAIN_COOKIE)
    assert forwarded_cookie_prefixes() == ("__Secure-better-auth.", "better-auth.")
    assert forwarded_cookie_prefixes("atlas") == ("__Secure-atlas.", "atlas.")


def test_the_mode_decides_the_provider(make_settings: Callable[..., Settings]) -> None:
    atlas = make_settings(auth_mode="atlas")
    assert atlas.auth_origin == FRONTEND
    assert atlas.auth_cookie_prefix == "atlas"
    assert atlas.plans_carry_user_id is True

    triptracker = make_settings(auth_mode="triptracker")
    assert triptracker.auth_origin == TRIPTRACKER
    assert triptracker.auth_cookie_prefix == "better-auth"
    assert triptracker.plans_carry_user_id is False

    local = make_settings(auth_mode="local")
    assert local.plans_carry_user_id is False


def test_messages_name_triptracker_only_in_its_mode(make_settings: Callable[..., Settings]) -> None:
    assert auth_messages(make_settings(auth_mode="triptracker")) is AUTH_ERROR_MESSAGES
    assert auth_messages(make_settings(auth_mode="atlas")) is ATLAS_AUTH_ERROR_MESSAGES
    assert auth_messages(make_settings(auth_mode="local")) is ATLAS_AUTH_ERROR_MESSAGES
    assert set(ATLAS_AUTH_ERROR_MESSAGES) == set(AuthErrorCode)
    assert all("TripTracker" not in text for text in ATLAS_AUTH_ERROR_MESSAGES.values())
    assert "TripTracker" in AUTH_ERROR_MESSAGES[AuthErrorCode.NOT_AUTHENTICATED]
    error = auth_error(AuthErrorCode.NOT_AUTHENTICATED, ATLAS_AUTH_ERROR_MESSAGES)
    assert error.detail == {
        "code": "not_authenticated",
        "message": "Accedi per usare il planner.",
        "data": None,
    }


def test_pure_helpers_take_the_prefix() -> None:
    request = make_request(
        [
            (
                "cookie",
                f"theme=dark; {SECURE_COOKIE}=tt.sig; {ATLAS_PLAIN_COOKIE}=at.sig; atlas.other=x",
            )
        ]
    )
    assert session_cookie(request) == (SECURE_COOKIE, "tt.sig")
    assert session_cookie(request, "atlas") == (ATLAS_PLAIN_COOKIE, "at.sig")
    assert forwarded_cookie_header(request) == f"{SECURE_COOKIE}=tt.sig"
    assert (
        forwarded_cookie_header(request, "atlas") == f"{ATLAS_PLAIN_COOKIE}=at.sig; atlas.other=x"
    )


async def test_atlas_mode_asks_the_web_app_and_forwards_only_its_cookies(
    atlas_settings: Settings, http: httpx.AsyncClient, mock_tt: respx.MockRouter
) -> None:
    route = mock_tt.get(ATLAS_GET_SESSION_URL).respond(200, json=session_body())
    app = auth_app(atlas_settings, SessionVerifier(atlas_settings, http))
    cookie = f"{SECURE_COOKIE}={SIGNED_TOKEN}; {ATLAS_SECURE_COOKIE}={SIGNED_TOKEN}; theme=dark"

    async with asgi_client(app) as client:
        response = await client.get("/me", headers={"Cookie": cookie})

    assert response.status_code == 200
    assert response.json() == {"email": "test@example.com", "id": "usr_1"}
    assert route.call_count == 1
    assert route.calls.last.request.headers["cookie"] == f"{ATLAS_SECURE_COOKIE}={SIGNED_TOKEN}"
    assert str(route.calls.last.request.url) == ATLAS_GET_SESSION_URL


async def test_atlas_mode_ignores_triptrackers_cookie(
    atlas_settings: Settings, http: httpx.AsyncClient, mock_tt: respx.MockRouter
) -> None:
    route = mock_tt.get(ATLAS_GET_SESSION_URL).respond(200, json=session_body())
    app = auth_app(atlas_settings, SessionVerifier(atlas_settings, http))

    async with asgi_client(app) as client:
        response = await client.get("/me", headers={"Cookie": f"{SECURE_COOKIE}={SIGNED_TOKEN}"})

    assert response.status_code == 401
    assert response.json()["detail"] == {
        "code": "not_authenticated",
        "message": ATLAS_AUTH_ERROR_MESSAGES[AuthErrorCode.NOT_AUTHENTICATED],
        "data": None,
    }
    assert route.call_count == 0


async def test_atlas_mode_failures_do_not_name_triptracker(
    atlas_settings: Settings, http: httpx.AsyncClient, mock_tt: respx.MockRouter
) -> None:
    mock_tt.get(ATLAS_GET_SESSION_URL).respond(503)
    app = auth_app(atlas_settings, SessionVerifier(atlas_settings, http))

    async with asgi_client(app) as client:
        response = await client.get(
            "/me", headers={"Cookie": f"{ATLAS_PLAIN_COOKIE}={SIGNED_TOKEN}"}
        )

    assert response.status_code == 503
    assert (
        response.json()["detail"]["message"]
        == "Non riesco a verificare l'accesso. Riprova tra poco."
    )


async def test_atlas_mode_treats_a_user_without_an_id_as_a_malformed_answer(
    atlas_settings: Settings, http: httpx.AsyncClient, mock_tt: respx.MockRouter
) -> None:
    # New plans store the id in plans.user_id: a user without one is never let through as NULL.
    body = session_body()
    del body["user"]["id"]
    route = mock_tt.get(ATLAS_GET_SESSION_URL).respond(200, json=body)
    verifier = SessionVerifier(atlas_settings, http)
    app = auth_app(atlas_settings, verifier)

    async with asgi_client(app) as client:
        response = await client.get(
            "/me", headers={"Cookie": f"{ATLAS_PLAIN_COOKIE}={SIGNED_TOKEN}"}
        )

    assert response.status_code == 503
    assert response.json()["detail"] == {
        "code": "auth_unavailable",
        "message": ATLAS_AUTH_ERROR_MESSAGES[AuthErrorCode.AUTH_UNAVAILABLE],
        "data": None,
    }
    assert route.call_count == 1
    assert len(verifier.cache) == 0  # a malformed answer is never cached


async def test_triptracker_mode_still_accepts_a_user_without_an_id(
    triptracker_settings: Settings, http: httpx.AsyncClient, mock_tt: respx.MockRouter
) -> None:
    assert triptracker_settings.plans_carry_user_id is False
    route = mock_tt.get(GET_SESSION_URL).respond(200, json={"user": {"email": "test@example.com"}})
    app = auth_app(triptracker_settings, SessionVerifier(triptracker_settings, http))

    async with asgi_client(app) as client:
        response = await client.get("/me", headers={"Cookie": f"{SECURE_COOKIE}={SIGNED_TOKEN}"})

    assert response.status_code == 200
    assert response.json() == {"email": "test@example.com", "id": None}
    assert route.call_count == 1
