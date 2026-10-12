"""TripTracker's trip.json (app/triptracker_schema.py): download, development fallback, the
production refusal to fall back, the 30-second retry, the periodic refresh, and the validation
messages that go back to the coordinator. HTTP is mocked with respx; nothing leaves the
machine."""

from __future__ import annotations

import asyncio
import copy
import datetime as dt
import fnmatch
import hashlib
import json
import logging
from collections.abc import Callable
from pathlib import Path
from types import MappingProxyType
from typing import Any

import httpx
import pytest
import respx
import structlog
from structlog.testing import LogCapture
from structlog.typing import EventDict

from app import triptracker_schema
from app.config import BACKEND_DIR, Settings
from app.triptracker_schema import (
    DEV_FALLBACK_SCHEMA_PATH,
    HTTP_TIMEOUT_SECONDS,
    JSON_SCHEMA_DIALECT,
    MAX_REPORTED_ERRORS,
    MAX_SCHEMA_BYTES,
    PINNED_SCHEMA_PATH,
    PINNED_SCHEMA_URL,
    REFRESH_SECONDS,
    RETRY_INTERVAL_SECONDS,
    TripSchema,
    TripSchemaError,
    TripSchemaStore,
    TripSchemaUnavailableError,
    canonical_json,
    fetch_trip_schema,
    load_dev_fallback_schema,
    validate_trip,
)

SCHEMA_URL = "https://viaggi.bellittim.com/schema/trip.json"  # conftest's TRIP_SCHEMA_URL
FIXTURE_SCHEMA_PATH = BACKEND_DIR / "tests" / "fixtures" / "triptracker" / "trip.schema.json"
VALID_TRIP_PATH = BACKEND_DIR / "tests" / "fixtures" / "triptracker" / "valid_trip.json"
T0 = dt.datetime(2026, 10, 12, 8, 0, tzinfo=dt.UTC)

MakeSettings = Callable[..., Settings]


class FakeClock:
    """A `now` callable the test moves by hand."""

    def __init__(self, start: dt.datetime = T0) -> None:
        self.value = start

    def __call__(self) -> dt.datetime:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += dt.timedelta(seconds=seconds)


@pytest.fixture
def document() -> dict[str, Any]:
    return json.loads(FIXTURE_SCHEMA_PATH.read_text(encoding="utf-8"))


@pytest.fixture
def schema(document: dict[str, Any]) -> TripSchema:
    return TripSchema.from_document(document, source="remote", url=SCHEMA_URL, loaded_at=T0)


@pytest.fixture
def valid_trip() -> dict[str, Any]:
    return json.loads(VALID_TRIP_PATH.read_text(encoding="utf-8"))


@pytest.fixture
def production(make_settings: MakeSettings) -> Settings:
    return make_settings(
        environment="production",
        auth_mode="triptracker",
        anthropic_api_key="test-placeholder-not-a-key",
    )


@pytest.fixture
def development(make_settings: MakeSettings) -> Settings:
    return make_settings()


# --- TripSchema.from_document ----------------------------------------------------------------


def test_from_document_wraps_a_valid_schema(document: dict[str, Any]) -> None:
    schema = TripSchema.from_document(document, source="file", url="file:///x.json", loaded_at=T0)

    assert schema.document == document
    assert (schema.source, schema.url, schema.loaded_at) == ("file", "file:///x.json", T0)
    expected = hashlib.sha256(canonical_json(document).encode("utf-8")).hexdigest()
    assert schema.sha256 == expected


def test_the_sha256_ignores_key_order_and_whitespace(document: dict[str, Any]) -> None:
    reordered = json.loads(json.dumps(dict(reversed(list(document.items())))))
    raw_text = FIXTURE_SCHEMA_PATH.read_text(encoding="utf-8")

    first = TripSchema.from_document(document, source="remote", url="a", loaded_at=T0)
    second = TripSchema.from_document(reordered, source="file", url="b", loaded_at=T0)

    assert first.sha256 == second.sha256
    assert first.sha256 != hashlib.sha256(raw_text.encode()).hexdigest()  # canonical, not raw
    changed = copy.deepcopy(document)
    changed["properties"]["title"]["maxLength"] = 121
    third = TripSchema.from_document(changed, source="remote", url="a", loaded_at=T0)
    assert third.sha256 != first.sha256


def test_the_wrapped_document_is_a_copy(document: dict[str, Any]) -> None:
    schema = TripSchema.from_document(document, source="remote", url="a", loaded_at=T0)

    document["properties"]["title"]["maxLength"] = 5

    assert schema.document["properties"]["title"]["maxLength"] == 120


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"$schema": "http://json-schema.org/draft-07/schema#"}, "draft-07"),
        ({"$schema": None}, "expected https://json-schema.org/draft/2020-12/schema"),
        ({"type": "array"}, "does not describe an object"),
        ({"properties": {"title": {"type": 5}}}, "not a valid Draft 2020-12 schema"),
        ({"required": "title"}, "not a valid Draft 2020-12 schema"),
        ({"maxProperties": float("nan")}, "not plain JSON"),
    ],
)
def test_from_document_refuses_anything_else(
    document: dict[str, Any], change: dict[str, Any], message: str
) -> None:
    document.update(change)

    with pytest.raises(TripSchemaUnavailableError, match=message):
        TripSchema.from_document(document, source="remote", url=SCHEMA_URL, loaded_at=T0)


def test_the_dialect_constant_is_draft_2020_12(document: dict[str, Any]) -> None:
    assert document["$schema"] == JSON_SCHEMA_DIALECT


# --- validate_trip ---------------------------------------------------------------------------


def test_a_valid_trip_has_no_errors(schema: TripSchema, valid_trip: dict[str, Any]) -> None:
    assert validate_trip(valid_trip, schema=schema) == []
    assert schema.validate(valid_trip) == []
    assert validate_trip(MappingProxyType(valid_trip), schema=schema) == []


def test_errors_are_sorted_by_path_with_numeric_indexes(
    schema: TripSchema, valid_trip: dict[str, Any]
) -> None:
    template = valid_trip["days"][-1]
    valid_trip["days"] = [{**template, "dayIndex": i} for i in range(12)]
    valid_trip["days"][10]["title"] = "x" * 121
    valid_trip["days"][2]["title"] = "x" * 121
    valid_trip["title"] = ""
    valid_trip["bookings"][0]["status"] = "done"

    errors = validate_trip(valid_trip, schema=schema)

    assert [error.path for error in errors] == [
        "bookings[0].status",
        "days[2].title",
        "days[10].title",
        "title",
    ]


def test_at_most_fifty_errors_then_a_count(schema: TripSchema, valid_trip: dict[str, Any]) -> None:
    template = {**valid_trip["bookings"][0], "status": "maybe"}
    valid_trip["bookings"] = [dict(template) for _ in range(MAX_REPORTED_ERRORS + 10)]

    errors = validate_trip(valid_trip, schema=schema)

    assert len(errors) == MAX_REPORTED_ERRORS + 1
    assert errors[-1] == TripSchemaError(path="(trip)", message="... and 10 more errors")


def test_long_values_are_never_quoted_whole(schema: TripSchema, valid_trip: dict[str, Any]) -> None:
    long_date = "2" * 500
    long_status = "s" * 61
    valid_trip["days"][0]["date"] = long_date
    valid_trip["bookings"][0]["status"] = long_status
    valid_trip["bookings"][1]["notes"] = "n" * 4001

    errors = validate_trip(valid_trip, schema=schema)
    messages = {error.path: error.message for error in errors}

    assert len(errors) == 3
    assert "500 characters" in messages["days[0].date"]
    assert long_date not in messages["days[0].date"]
    assert long_status not in messages["bookings[0].status"]
    assert "61 characters" in messages["bookings[0].status"]
    assert messages["bookings[1].notes"] == "must be at most 4000 characters (got 4001)"
    assert all(len(error.message) < 300 for error in errors)


def test_short_values_are_quoted(schema: TripSchema, valid_trip: dict[str, Any]) -> None:
    valid_trip["bookings"][0]["kind"] = "flight"

    (error,) = validate_trip(valid_trip, schema=schema)

    assert error.path == "bookings[0].kind"
    assert error.message.startswith('must be one of "restaurant", "wellness"')
    assert error.message.endswith('(got "flight")')


def test_null_and_missing_and_unknown_keys(schema: TripSchema, valid_trip: dict[str, Any]) -> None:
    valid_trip["baseName"] = None
    del valid_trip["days"][0]["stops"][0]["state"]
    valid_trip["days"][0]["stops"][0]["ref"] = "d1"
    valid_trip["summary"] = "Tre giorni."

    errors = validate_trip(valid_trip, schema=schema)

    assert errors == [
        TripSchemaError("baseName", "must be a string, not null: omit the key instead"),
        TripSchemaError("days[0].stops[0].ref", "is not a TripTracker field: remove this key"),
        TripSchemaError("days[0].stops[0].state", "is required"),
        TripSchemaError("summary", "is not a TripTracker field: remove this key"),
    ]


def test_wrong_types_name_both_types(schema: TripSchema, valid_trip: dict[str, Any]) -> None:
    valid_trip["coverSeed"] = "12"
    valid_trip["days"] = {}

    errors = validate_trip(valid_trip, schema=schema)

    assert errors == [
        TripSchemaError("coverSeed", "must be an integer (got string)"),
        TripSchemaError("days", "must be an array (got object)"),
    ]


def test_the_zod_refine_on_the_date_range_is_enforced(
    schema: TripSchema, valid_trip: dict[str, Any]
) -> None:
    valid_trip["endDate"] = "2026-11-13"

    assert validate_trip(valid_trip, schema=schema) == [
        TripSchemaError("endDate", 'must be on or after startDate "2026-11-14" (got "2026-11-13")')
    ]
    valid_trip["endDate"] = valid_trip["startDate"]
    assert validate_trip(valid_trip, schema=schema) == []


def test_a_non_object_trip_is_reported_not_raised(schema: TripSchema) -> None:
    errors = validate_trip(MappingProxyType({}), schema=schema)

    assert TripSchemaError("title", "is required") in errors


def test_patterns_follow_javascript_semantics() -> None:
    document = {
        "$schema": JSON_SCHEMA_DIALECT,
        "type": "object",
        "properties": {
            "escaped": {"type": "string", "pattern": "^a\\$b$"},
            "in_class": {"type": "string", "pattern": "^[$]+$"},
            "digits": {"type": "string", "pattern": "^\\d+$"},
        },
    }
    schema = TripSchema.from_document(document, source="remote", url="x", loaded_at=T0)

    assert validate_trip({"escaped": "a$b", "in_class": "$$", "digits": "42"}, schema=schema) == []
    paths = [
        error.path
        for error in validate_trip(
            {"escaped": "a$b\n", "in_class": "$$\n", "digits": "\u0664\u0662"}, schema=schema
        )
    ]
    assert paths == ["digits", "escaped", "in_class"]


# --- fetch_trip_schema -----------------------------------------------------------------------


async def test_fetch_downloads_json_without_cookies(document: dict[str, Any]) -> None:
    async with httpx.AsyncClient() as http:
        http.cookies.set(
            "__Secure-better-auth.session_token", "secret", domain="viaggi.bellittim.com"
        )
        with respx.mock() as router:
            route = router.get(SCHEMA_URL).mock(return_value=httpx.Response(200, json=document))

            fetched = await fetch_trip_schema(http, SCHEMA_URL)

    assert fetched == document
    request = route.calls.last.request
    assert request.headers["accept"] == "application/json"
    assert "cookie" not in request.headers
    assert request.extensions["timeout"]["read"] == HTTP_TIMEOUT_SECONDS


async def test_fetch_accepts_a_local_http_origin(document: dict[str, Any]) -> None:
    url = "http://localhost:3001/schema/trip.json"
    async with httpx.AsyncClient() as http:
        with respx.mock() as router:
            router.get(url).mock(return_value=httpx.Response(200, json=document))

            assert await fetch_trip_schema(http, url) == document


@pytest.mark.parametrize(
    ("response", "message"),
    [
        (httpx.Response(404, text="Not Found"), "answered HTTP 404"),
        (httpx.Response(503, json={"error": "down"}), "answered HTTP 503"),
        (httpx.Response(301, headers={"Location": "https://example.org/"}), "answered HTTP 301"),
        (httpx.Response(200, text="<html>"), "not valid JSON"),
        (httpx.Response(200, json=[1, 2]), "not a JSON object"),
        (httpx.Response(200, content=b" " * (MAX_SCHEMA_BYTES + 1)), "larger than"),
    ],
)
async def test_fetch_refuses_bad_answers(response: httpx.Response, message: str) -> None:
    async with httpx.AsyncClient() as http:
        with respx.mock() as router:
            router.get(SCHEMA_URL).mock(return_value=response)

            with pytest.raises(TripSchemaUnavailableError, match=message):
                await fetch_trip_schema(http, SCHEMA_URL)


async def test_fetch_maps_network_errors() -> None:
    async with httpx.AsyncClient() as http:
        with respx.mock() as router:
            router.get(SCHEMA_URL).mock(side_effect=httpx.ConnectError("connection refused"))

            with pytest.raises(TripSchemaUnavailableError, match="ConnectError"):
                await fetch_trip_schema(http, SCHEMA_URL)


async def test_fetch_reads_an_absolute_file_url(tmp_path: Path, document: dict[str, Any]) -> None:
    pinned = tmp_path / "pinned trip.json"
    pinned.write_text(json.dumps(document), encoding="utf-8")

    async with httpx.AsyncClient() as http:
        assert await fetch_trip_schema(http, pinned.as_uri()) == document


async def test_fetch_reads_a_file_url_relative_to_backend(document: dict[str, Any]) -> None:
    url = "file:tests/fixtures/triptracker/trip.schema.json"

    async with httpx.AsyncClient() as http:
        assert await fetch_trip_schema(http, url) == document


@pytest.mark.parametrize(
    ("url", "message"),
    [
        ("file:///nonexistent/trip-planner/trip.json", "cannot read"),
        ("file://files.example.org/trip.json", "remote host"),
        ("ftp://viaggi.bellittim.com/schema/trip.json", "must be an https:// or file:// URL"),
        ("viaggi.bellittim.com/schema/trip.json", "must be an https:// or file:// URL"),
        ("https://[::1/trip.json", "not a URL"),
    ],
)
async def test_fetch_refuses_unusable_urls(url: str, message: str) -> None:
    async with httpx.AsyncClient() as http:
        with pytest.raises(TripSchemaUnavailableError, match=message):
            await fetch_trip_schema(http, url)


async def test_a_file_that_is_not_json_is_refused(tmp_path: Path) -> None:
    pinned = tmp_path / "trip.json"
    pinned.write_text("not json", encoding="utf-8")

    async with httpx.AsyncClient() as http:
        with pytest.raises(TripSchemaUnavailableError, match="not valid JSON"):
            await fetch_trip_schema(http, pinned.as_uri())


def test_the_dev_fallback_is_the_vendored_fixture(document: dict[str, Any]) -> None:
    assert DEV_FALLBACK_SCHEMA_PATH == FIXTURE_SCHEMA_PATH
    assert load_dev_fallback_schema() == document


# --- the pinned production copy (TripTracker does not serve trip.json yet) --------------------


def test_the_pinned_copy_equals_the_fixture() -> None:
    """backend/pinned/trip.schema.json is what production validates with until TripTracker
    serves /schema/trip.json: byte for byte the fixture development and the tests use. Update
    both together (or neither)."""
    assert PINNED_SCHEMA_PATH == BACKEND_DIR / "pinned" / "trip.schema.json"
    assert PINNED_SCHEMA_PATH.read_bytes() == FIXTURE_SCHEMA_PATH.read_bytes()


async def test_the_pinned_url_names_the_pinned_copy_inside_the_image(
    document: dict[str, Any],
) -> None:
    """The image's WORKDIR /app is backend/, so file:///app/<p> is backend/<p>."""
    relative = PINNED_SCHEMA_PATH.relative_to(BACKEND_DIR).as_posix()
    assert f"file:///app/{relative}" == PINNED_SCHEMA_URL
    async with httpx.AsyncClient() as http:
        assert await fetch_trip_schema(http, f"file:{relative}") == document


def test_the_image_ships_the_pinned_copy() -> None:
    """backend/Dockerfile copies the build context to /app and checks the file is there;
    .dockerignore (which keeps tests/ out) must not exclude it."""
    relative = PINNED_SCHEMA_PATH.relative_to(BACKEND_DIR).as_posix()
    dockerfile = (BACKEND_DIR / "Dockerfile").read_text(encoding="utf-8").splitlines()
    assert "WORKDIR /app" in dockerfile
    assert "COPY . /app" in dockerfile
    assert f"RUN test -s /app/{relative}" in dockerfile
    patterns = [
        line.strip().rstrip("/")
        for line in (BACKEND_DIR / ".dockerignore").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith(("#", "!"))
    ]
    assert "tests" in patterns  # the fixture itself stays out of the image
    parents = [relative, *(str(parent) for parent in Path(relative).parents if str(parent) != ".")]
    for pattern in patterns:
        for candidate in parents:
            assert not fnmatch.fnmatch(candidate, pattern.removeprefix("**/")), (pattern, candidate)


# --- TripSchemaStore -------------------------------------------------------------------------


async def test_the_store_loads_the_remote_schema_once(
    development: Settings, document: dict[str, Any]
) -> None:
    async with httpx.AsyncClient() as http:
        with respx.mock() as router:
            route = router.get(SCHEMA_URL).mock(return_value=httpx.Response(200, json=document))
            store = TripSchemaStore(development, http, now=FakeClock())

            assert store.current() is None
            loaded = await store.load()
            required = await store.require()

    assert loaded is not None
    assert required is loaded
    assert store.current() is loaded
    assert (loaded.source, loaded.url, loaded.loaded_at) == ("remote", SCHEMA_URL, T0)
    assert store.last_error is None
    assert route.call_count == 1


async def test_development_falls_back_to_the_vendored_schema(
    development: Settings, document: dict[str, Any]
) -> None:
    async with httpx.AsyncClient() as http:
        with respx.mock() as router:
            router.get(SCHEMA_URL).mock(return_value=httpx.Response(404))
            store = TripSchemaStore(development, http, now=FakeClock())

            loaded = await store.load()

    assert loaded is not None
    assert loaded.source == "dev_fallback"
    assert loaded.url == DEV_FALLBACK_SCHEMA_PATH.as_uri()
    assert loaded.document == document
    assert await store.require() is loaded


async def test_development_without_a_fallback_file_has_no_schema(
    development: Settings, tmp_path: Path
) -> None:
    async with httpx.AsyncClient() as http:
        with respx.mock() as router:
            router.get(SCHEMA_URL).mock(return_value=httpx.Response(404))
            store = TripSchemaStore(
                development, http, now=FakeClock(), fallback_path=tmp_path / "missing.json"
            )

            assert await store.load() is None
            with pytest.raises(TripSchemaUnavailableError, match="fallback failed too"):
                await store.require()


async def test_production_never_falls_back(production: Settings) -> None:
    assert DEV_FALLBACK_SCHEMA_PATH.exists()
    async with httpx.AsyncClient() as http:
        with respx.mock() as router:
            route = router.get(SCHEMA_URL).mock(return_value=httpx.Response(404))
            store = TripSchemaStore(production, http, now=FakeClock())

            assert await store.load() is None

    assert store.current() is None
    assert store.last_error is not None
    assert SCHEMA_URL in store.last_error
    assert route.call_count == 1


async def test_production_retries_at_most_every_thirty_seconds(
    production: Settings, document: dict[str, Any]
) -> None:
    clock = FakeClock()
    async with httpx.AsyncClient() as http:
        with respx.mock() as router:
            route = router.get(SCHEMA_URL).mock(
                side_effect=[httpx.Response(503), httpx.Response(200, json=document)]
            )
            store = TripSchemaStore(production, http, now=clock)
            assert await store.load() is None

            clock.advance(RETRY_INTERVAL_SECONDS - 1)
            with pytest.raises(TripSchemaUnavailableError, match="answered HTTP 503"):
                await store.require()
            assert route.call_count == 1  # too early: no new request

            clock.advance(1)
            schema = await store.require()

    assert route.call_count == 2
    assert schema.source == "remote"
    assert store.current() is schema
    assert store.last_error is None


async def test_concurrent_requires_share_one_download(
    production: Settings, document: dict[str, Any]
) -> None:
    async with httpx.AsyncClient() as http:
        with respx.mock() as router:
            route = router.get(SCHEMA_URL).mock(return_value=httpx.Response(200, json=document))
            store = TripSchemaStore(production, http, now=FakeClock())

            schemas = await asyncio.gather(*(store.require() for _ in range(5)))

    assert route.call_count == 1
    assert len({id(schema) for schema in schemas}) == 1


async def test_production_can_pin_a_file_copy(
    make_settings: MakeSettings, tmp_path: Path, document: dict[str, Any]
) -> None:
    pinned = tmp_path / "trip.json"
    pinned.write_text(json.dumps(document), encoding="utf-8")
    settings = make_settings(
        environment="production",
        auth_mode="triptracker",
        anthropic_api_key="test-placeholder-not-a-key",
        trip_schema_url=pinned.as_uri(),
    )

    async with httpx.AsyncClient() as http:
        loaded = await TripSchemaStore(settings, http, now=FakeClock()).load()

    assert loaded is not None
    assert (loaded.source, loaded.url) == ("file", pinned.as_uri())


async def test_production_refuses_an_invalid_schema(
    production: Settings, document: dict[str, Any]
) -> None:
    document["$schema"] = "http://json-schema.org/draft-07/schema#"
    async with httpx.AsyncClient() as http:
        with respx.mock() as router:
            router.get(SCHEMA_URL).mock(return_value=httpx.Response(200, json=document))
            store = TripSchemaStore(production, http, now=FakeClock())

            assert await store.load() is None

    assert store.last_error is not None
    assert "draft-07" in store.last_error


async def test_the_background_retry_returns_once_loaded(
    production: Settings, document: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(triptracker_schema, "RETRY_INTERVAL_SECONDS", 0.0)
    async with httpx.AsyncClient() as http:
        with respx.mock() as router:
            route = router.get(SCHEMA_URL).mock(
                side_effect=[
                    httpx.Response(503),
                    httpx.Response(503),
                    httpx.Response(200, json=document),
                ]
            )
            store = TripSchemaStore(production, http, now=FakeClock())
            assert await store.load() is None

            schema = await asyncio.wait_for(store.retry_until_loaded(), timeout=5)
            again = await store.retry_until_loaded()

    assert route.call_count == 3
    assert again is schema is store.current()


async def test_load_never_raises(production: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    async def broken(http: httpx.AsyncClient, url: str) -> dict[str, Any]:
        raise RuntimeError("bug")

    monkeypatch.setattr(triptracker_schema, "fetch_trip_schema", broken)
    async with httpx.AsyncClient() as http:
        store = TripSchemaStore(production, http, now=FakeClock())

        assert await store.load() is None

    assert store.last_error is not None
    assert "RuntimeError" in store.last_error


async def test_the_store_defaults_to_the_clock(
    development: Settings, document: dict[str, Any]
) -> None:
    async with httpx.AsyncClient() as http:
        with respx.mock() as router:
            router.get(SCHEMA_URL).mock(return_value=httpx.Response(200, json=document))
            loaded = await TripSchemaStore(development, http).load()

    assert loaded is not None
    assert loaded.loaded_at.tzinfo is not None
    assert loaded.loaded_at.utcoffset() is not None


# --- refresh (TripTracker regenerates trip.json on every build) ---------------------------------


@pytest.fixture
def logs(monkeypatch: pytest.MonkeyPatch) -> list[EventDict]:
    """Every log entry of the module, independent of the global structlog configuration (other
    tests reconfigure it, and the module's logger may be cached on an older chain)."""
    capture = LogCapture()
    logger = structlog.wrap_logger(
        None,
        processors=[capture],
        wrapper_class=structlog.make_filtering_bound_logger(logging.DEBUG),
    )
    monkeypatch.setattr(triptracker_schema, "log", logger)
    return capture.entries


def tightened(document: dict[str, Any], *, title_max: int) -> dict[str, Any]:
    changed = copy.deepcopy(document)
    changed["properties"]["title"]["maxLength"] = title_max
    return changed


async def test_require_refreshes_the_schema_and_enforces_a_new_cap(
    production: Settings,
    document: dict[str, Any],
    valid_trip: dict[str, Any],
    logs: list[EventDict],
) -> None:
    """Reviewer's scenario: TripTracker tightens a cap after the planner started. Within
    `REFRESH_SECONDS` the next plan is validated against the new schema."""
    clock = FakeClock()
    newer = tightened(document, title_max=5)
    async with httpx.AsyncClient() as http:
        with respx.mock() as router:
            route = router.get(SCHEMA_URL).mock(
                side_effect=[
                    httpx.Response(200, json=document),
                    httpx.Response(200, json=newer),
                ]
            )
            store = TripSchemaStore(production, http, now=clock)
            first = await store.load()
            assert first is not None
            assert first.validate(valid_trip) == []

            clock.advance(REFRESH_SECONDS - 1)
            assert await store.require() is first
            assert route.call_count == 1  # still fresh: no download

            clock.advance(1)
            second = await store.require()

    assert route.call_count == 2
    assert second is not first
    assert second.sha256 != first.sha256
    assert second.loaded_at == T0 + dt.timedelta(seconds=REFRESH_SECONDS)
    assert store.current() is second
    errors = second.validate(valid_trip)
    assert [(error.path, error.message) for error in errors] == [
        ("title", "must be at most 5 characters (got 17)")
    ]
    changed = [entry for entry in logs if entry["event"] == "trip_schema_changed"]
    assert len(changed) == 1
    assert changed[0]["log_level"] == "warning"
    assert (changed[0]["old_sha256"], changed[0]["new_sha256"]) == (first.sha256, second.sha256)


async def test_an_unchanged_refresh_keeps_the_same_schema(
    production: Settings, document: dict[str, Any]
) -> None:
    clock = FakeClock()
    async with httpx.AsyncClient() as http:
        with respx.mock() as router:
            route = router.get(SCHEMA_URL).mock(return_value=httpx.Response(200, json=document))
            store = TripSchemaStore(production, http, now=clock)
            first = await store.load()

            for _ in range(3):
                clock.advance(REFRESH_SECONDS)
                assert await store.require() is first

    assert route.call_count == 4
    assert first is not None
    assert first.loaded_at == T0


async def test_a_failed_refresh_keeps_the_last_good_copy_and_retries_sooner(
    production: Settings, document: dict[str, Any], logs: list[EventDict]
) -> None:
    clock = FakeClock()
    newer = tightened(document, title_max=60)
    async with httpx.AsyncClient() as http:
        with respx.mock() as router:
            route = router.get(SCHEMA_URL).mock(
                side_effect=[
                    httpx.Response(200, json=document),
                    httpx.Response(503),
                    httpx.ConnectError("refused"),
                    httpx.Response(200, json=newer),
                ]
            )
            store = TripSchemaStore(production, http, now=clock)
            first = await store.load()
            assert first is not None

            clock.advance(REFRESH_SECONDS)
            logs.clear()
            assert await store.require() is first  # 503: the last good copy stays
            assert store.last_error is not None
            assert "answered HTTP 503" in store.last_error
            assert [entry["event"] for entry in logs] == ["trip_schema_refresh_failed"]
            assert logs[0]["kept_sha256"] == first.sha256

            clock.advance(RETRY_INTERVAL_SECONDS - 1)
            assert await store.require() is first
            assert route.call_count == 2  # failed refreshes retry after 30 s, not every call

            clock.advance(1)
            assert await store.require() is first  # network error: still the last good copy
            assert route.call_count == 3

            clock.advance(RETRY_INTERVAL_SECONDS)
            refreshed = await store.require()

    assert route.call_count == 4
    assert refreshed is not first
    assert refreshed.document["properties"]["title"]["maxLength"] == 60
    assert store.last_error is None


async def test_an_unexpected_refresh_error_keeps_the_schema(
    production: Settings, document: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    clock = FakeClock()
    async with httpx.AsyncClient() as http:
        with respx.mock() as router:
            router.get(SCHEMA_URL).mock(return_value=httpx.Response(200, json=document))
            store = TripSchemaStore(production, http, now=clock)
            first = await store.load()

        async def broken(http: httpx.AsyncClient, url: str) -> dict[str, Any]:
            raise RuntimeError("bug")

        monkeypatch.setattr(triptracker_schema, "fetch_trip_schema", broken)
        clock.advance(REFRESH_SECONDS)
        assert await store.require() is first

    assert store.last_error is not None
    assert "RuntimeError" in store.last_error


async def test_development_never_swaps_the_fallback_in_for_a_downloaded_schema(
    development: Settings, document: dict[str, Any]
) -> None:
    clock = FakeClock()
    changed = tightened(document, title_max=100)
    async with httpx.AsyncClient() as http:
        with respx.mock() as router:
            router.get(SCHEMA_URL).mock(
                side_effect=[httpx.Response(200, json=changed), httpx.Response(404)]
            )
            store = TripSchemaStore(development, http, now=clock)
            first = await store.load()
            clock.advance(REFRESH_SECONDS)

            kept = await store.require()

    assert first is not None
    assert kept is first
    assert kept.source == "remote"


async def test_a_dev_fallback_gives_way_once_the_url_answers(
    development: Settings, document: dict[str, Any]
) -> None:
    clock = FakeClock()
    async with httpx.AsyncClient() as http:
        with respx.mock() as router:
            router.get(SCHEMA_URL).mock(
                side_effect=[httpx.Response(404), httpx.Response(200, json=document)]
            )
            store = TripSchemaStore(development, http, now=clock)
            fallback = await store.load()
            clock.advance(REFRESH_SECONDS)

            downloaded = await store.require()

    assert fallback is not None
    assert fallback.source == "dev_fallback"
    assert downloaded.source == "remote"
    assert downloaded.sha256 == fallback.sha256  # same document, now from TripTracker
