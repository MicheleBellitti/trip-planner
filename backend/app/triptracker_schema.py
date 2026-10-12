"""TripTracker's own Trip JSON Schema: fetch it, keep it, validate every produced Trip with it.

Spec: "Contratto del piano" -> "Una sola fonte di verita' per lo schema": TripTracker exports
`tripSchema` with `z.toJSONSchema` as `public/schema/trip.json`; the backend downloads it at
startup and validates every Trip with `jsonschema`, so a changed cap or field is noticed at the
first plan, not silently; `/import` revalidates with Zod and has the last word. Facts:
docs/triptracker/schema-notes.md §7 and §8 A16-A17.

Where the schema comes from (`TripSchemaStore.load`):

- `Settings.trip_schema_url` (TRIP_SCHEMA_URL, default `TRIPTRACKER_ORIGIN/schema/trip.json`).
  An `https://` URL is downloaded with the shared httpx client; a `file://` URL reads a pinned
  copy and is the explicit way to run production before TripTracker publishes the file. The
  pinned copy must live under backend/ (Railway deploys and ships only that directory).
- DECISION: when the URL fails, **development** falls back to `DEV_FALLBACK_SCHEMA_PATH` (the
  vendored zod 4.5.4 output, the test fixture) with a warning log; **production never falls
  back**. It logs an error, keeps running (`/health` stays green) and `require()` raises
  `TripSchemaUnavailableError`, which makes POST /plans answer 503 before any money is spent.
  `require()` retries the download at most every `RETRY_INTERVAL_SECONDS`, and
  `retry_until_loaded()` is the background task that retries on that same period until the
  schema loads, so the planner recovers by itself once TripTracker serves the file. Failing
  loudly beats validating against a stale copy: a silently stale schema is exactly the drift
  the spec wants to catch.
- Refresh: TripTracker regenerates trip.json on every build, while the planner may run for
  weeks. So `require()` (awaited by POST /plans and by every `submit_plan` evaluation)
  downloads the schema again once the copy in use is `REFRESH_SECONDS` old. A changed sha256
  is logged as a warning and takes over at once, so a tightened cap is enforced on the next
  plan. A failed refresh keeps the last good copy (the dev fallback is never swapped in for
  a downloaded one) and is retried after `RETRY_INTERVAL_SECONDS`.
- At schema-notes.md's commit 71be320 TripTracker does not serve the file yet (A16): until its
  PR lands, production runs with `TRIP_SCHEMA_URL=PINNED_SCHEMA_URL`
  (`file:///app/pinned/trip.schema.json`, docs/deploy.md), the copy at `PINNED_SCHEMA_PATH`
  (backend/pinned/, which the image ships, unlike tests/). It is byte-identical to the
  development fallback (tests/test_triptracker_schema.py checks it), so a pinned production
  and a development run validate against the same schema. Once TripTracker serves the file,
  TRIP_SCHEMA_URL is unset again and the pinned copy can go.

What `validate_trip` checks: the JSON Schema (Draft 2020-12; `additionalProperties: false`
rejects unknown keys that Zod would strip) plus the Zod refinement the export loses
(`endDate >= startDate`). It deliberately does not re-check referential integrity, calendar
validity or day coverage: those are guaranteed by `Plan` validation and `plan_to_trip`.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import functools
import hashlib
import json
import re
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal
from urllib.parse import urlsplit
from urllib.request import url2pathname

import httpx
import structlog
from jsonschema import Draft202012Validator, validators
from jsonschema.exceptions import SchemaError
from jsonschema.exceptions import ValidationError as JsonSchemaError

from app import clock
from app.config import BACKEND_DIR

if TYPE_CHECKING:
    from app.config import Settings

DEV_FALLBACK_SCHEMA_PATH = BACKEND_DIR / "tests" / "fixtures" / "triptracker" / "trip.schema.json"
"""Vendored `z.toJSONSchema(tripSchema)` (zod 4.5.4, TripTracker 71be320). Development only."""
PINNED_SCHEMA_PATH = BACKEND_DIR / "pinned" / "trip.schema.json"
"""The same document for production, outside tests/ so the image ships it (backend/Dockerfile)."""
PINNED_SCHEMA_URL = "file:///app/pinned/trip.schema.json"
"""TRIP_SCHEMA_URL of the interim production setting: `PINNED_SCHEMA_PATH` inside the image,
whose WORKDIR is /app. Never a default: production must opt into a pinned copy explicitly."""

RETRY_INTERVAL_SECONDS = 30.0
REFRESH_SECONDS = 600.0
"""`require()` downloads the schema again when the copy in use was last checked this long ago."""
HTTP_TIMEOUT_SECONDS = 10.0
JSON_SCHEMA_DIALECT = "https://json-schema.org/draft/2020-12/schema"

MAX_SCHEMA_BYTES = 1_000_000
"""A trip.json larger than this is refused (today's export is about 7 KB)."""
MAX_REPORTED_ERRORS = 50
"""`validate_trip` lists at most this many problems, then one "... and N more" line."""
MAX_SHOWN_VALUE = 60
"""Longer string values are never quoted whole in an error message."""

SchemaSource = Literal["remote", "file", "dev_fallback"]

log = structlog.get_logger(__name__)


class TripSchemaUnavailableError(Exception):
    """No usable trip.json: the download failed (production) or the document is not a valid
    Draft 2020-12 schema. The message says which URL and why, in English, for the logs."""


@dataclass(frozen=True, slots=True)
class TripSchemaError:
    """One validation problem of a Trip, in TripTracker's field names.

    `path` is a JSON path into the Trip (`days[2].stops[0].title`, `(trip)` for the root);
    `message` is English and goes to the coordinator inside the `submit_plan` tool result.
    """

    path: str
    message: str


@dataclass(frozen=True, slots=True)
class TripSchema:
    """A loaded, checked schema document and its provenance."""

    document: Mapping[str, Any]
    source: SchemaSource
    url: str
    sha256: str
    """sha256 of the canonical JSON (sorted keys): recorded in `plans.agent_versions`."""
    loaded_at: dt.datetime

    @classmethod
    def from_document(
        cls,
        document: Mapping[str, Any],
        *,
        source: SchemaSource,
        url: str,
        loaded_at: dt.datetime,
    ) -> TripSchema:
        """Check the document (`Draft202012Validator.check_schema`, `$schema` must be the
        2020-12 dialect, root `type: object`) and wrap it. Raises
        `TripSchemaUnavailableError` for anything else."""
        if not isinstance(document, Mapping):
            msg = f"trip.json from {url} is not a JSON object"
            raise TripSchemaUnavailableError(msg)
        try:
            canonical = canonical_json(document)
        except (TypeError, ValueError) as exc:
            msg = f"trip.json from {url} is not plain JSON: {exc}"
            raise TripSchemaUnavailableError(msg) from exc
        copy: dict[str, Any] = json.loads(canonical)
        dialect = copy.get("$schema")
        if dialect != JSON_SCHEMA_DIALECT:
            msg = (
                f"trip.json from {url} declares $schema {dialect!r}, expected {JSON_SCHEMA_DIALECT}"
            )
            raise TripSchemaUnavailableError(msg)
        if copy.get("type") != "object":
            msg = f"trip.json from {url} does not describe an object (type {copy.get('type')!r})"
            raise TripSchemaUnavailableError(msg)
        try:
            Draft202012Validator.check_schema(copy)
        except SchemaError as exc:
            msg = f"trip.json from {url} is not a valid Draft 2020-12 schema: {exc.message}"
            raise TripSchemaUnavailableError(msg) from exc
        digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        return cls(document=copy, source=source, url=url, sha256=digest, loaded_at=loaded_at)

    def validate(self, trip: Mapping[str, Any]) -> list[TripSchemaError]:
        """`validate_trip(trip, schema=self)`."""
        return validate_trip(trip, schema=self)


def canonical_json(document: Mapping[str, Any]) -> str:
    """The JSON text whose sha256 identifies a schema: sorted keys, no insignificant
    whitespace, UTF-8 characters kept as they are. Raises TypeError/ValueError for values that
    are not plain JSON (NaN included)."""
    return json.dumps(
        document, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    )


# --- validation -------------------------------------------------------------------------------


def validate_trip(trip: Mapping[str, Any], *, schema: TripSchema) -> list[TripSchemaError]:
    """Every problem of `trip` against `schema`, plus `endDate >= startDate`; empty when valid.

    Sorted by path for stable messages; at most 50 entries (then one "... and N more"). Never
    raises for an invalid trip. Error messages never include whole field values longer than 60
    characters.

    String patterns are matched as Zod (JavaScript) matches them: `\\d` is ASCII only and `$`
    is the very end of the string, so a value that `/import` would reject is not accepted here
    because of Python's wider `re` semantics (schema-notes §7).
    """
    instance: Any = trip if isinstance(trip, dict) else dict(trip)
    problems: list[tuple[tuple[str | int, ...], str]] = []
    for error in _validator_for(schema).iter_errors(instance):
        problems.extend(_describe(error))
    problems.extend(_date_order_problems(instance))
    problems.sort(key=lambda item: (_path_sort_key(item[0]), item[1]))
    errors = [TripSchemaError(path=_format_path(path), message=text) for path, text in problems]
    if len(errors) > MAX_REPORTED_ERRORS:
        extra = len(errors) - MAX_REPORTED_ERRORS
        errors = [
            *errors[:MAX_REPORTED_ERRORS],
            TripSchemaError(path="(trip)", message=f"... and {extra} more errors"),
        ]
    return errors


def _js_pattern(pattern: str) -> str:
    """`pattern` with every `$` anchor (unescaped, outside a character class) replaced by `\\Z`:
    in JavaScript without the `m` flag `$` matches only at the end, while Python's `$` also
    matches before a final newline."""
    out: list[str] = []
    escaped = in_class = False
    for char in pattern:
        if escaped:
            escaped = False
        elif char == "\\":
            escaped = True
        elif in_class:
            in_class = char != "]"
        elif char == "[":
            in_class = True
        elif char == "$":
            out.append(r"\Z")
            continue
        out.append(char)
    return "".join(out)


@functools.lru_cache(maxsize=64)
def _compile_js_pattern(pattern: str) -> re.Pattern[str]:
    return re.compile(_js_pattern(pattern), re.ASCII)


def _js_pattern_keyword(
    validator: Any, pattern: str, instance: Any, _schema: Mapping[str, Any]
) -> Iterator[JsonSchemaError]:
    """The `pattern` keyword with JavaScript semantics (see `validate_trip`)."""
    if validator.is_type(instance, "string") and not _compile_js_pattern(pattern).search(instance):
        yield JsonSchemaError(f"does not match {pattern!r}")


_TripValidator: Any = validators.extend(Draft202012Validator, {"pattern": _js_pattern_keyword})

_VALIDATORS: dict[str, Any] = {}
"""Compiled validators by schema sha256 (equal hashes mean equal documents)."""


def _validator_for(schema: TripSchema) -> Any:
    validator = _VALIDATORS.get(schema.sha256)
    if validator is None:
        if len(_VALIDATORS) >= 8:
            _VALIDATORS.clear()
        validator = _TripValidator(dict(schema.document))
        _VALIDATORS[schema.sha256] = validator
    return validator


_JsonPath = tuple[str | int, ...]


def _describe(error: JsonSchemaError) -> list[tuple[_JsonPath, str]]:
    """English messages for one jsonschema error, at the path of the offending key. The
    instance is never quoted whole when it is long (`_show`)."""
    path: _JsonPath = tuple(error.absolute_path)
    keyword = str(error.validator)
    expected: Any = error.validator_value
    value: Any = error.instance
    if keyword == "required":
        match = re.fullmatch(r"'(.+)' is a required property", error.message)
        key = match.group(1) if match else None
        if key is None:
            return [(path, "a required key is missing")]
        return [((*path, key), "is required")]
    if keyword == "additionalProperties":
        known = error.schema.get("properties", {}) if isinstance(error.schema, Mapping) else {}
        extras = [key for key in value if key not in known] if isinstance(value, dict) else []
        if not extras:
            return [(path, "has keys TripTracker's schema does not allow")]
        return [
            ((*path, str(key)), "is not a TripTracker field: remove this key") for key in extras
        ]
    if keyword == "type":
        if value is None:
            return [(path, f"must be {_type_name(expected)}, not null: omit the key instead")]
        return [(path, f"must be {_type_name(expected)} (got {_json_type(value)})")]
    return [(path, _constraint_message(keyword, expected, value))]


def _constraint_message(keyword: str, expected: Any, value: Any) -> str:
    size = len(value) if isinstance(value, str | list | dict) else None
    match keyword:
        case "maxLength":
            return f"must be at most {expected} characters (got {size})"
        case "minLength":
            if expected == 1:
                return "must not be empty"
            return f"must be at least {expected} characters (got {size})"
        case "pattern":
            return f"must match the pattern {expected} (got {_show(value)})"
        case "enum":
            allowed = ", ".join(json.dumps(item) for item in expected)
            return f"must be one of {allowed} (got {_show(value)})"
        case "const":
            return f"must be {json.dumps(expected)} (got {_show(value)})"
        case "minimum":
            return f"must be at least {expected} (got {_show(value)})"
        case "maximum":
            return f"must be at most {expected} (got {_show(value)})"
        case "exclusiveMinimum":
            return f"must be greater than {expected} (got {_show(value)})"
        case "exclusiveMaximum":
            return f"must be less than {expected} (got {_show(value)})"
        case "maxItems":
            return f"must have at most {expected} items (got {size})"
        case "minItems":
            return f"must have at least {expected} items (got {size})"
        case _:
            return f"fails the {keyword!r} rule of TripTracker's schema"


def _date_order_problems(trip: Any) -> list[tuple[_JsonPath, str]]:
    """Zod's `.refine(endDate >= startDate)` (a string comparison, error on `endDate`), which
    `z.toJSONSchema` drops."""
    if not isinstance(trip, dict):
        return []
    start: Any = trip.get("startDate")
    end: Any = trip.get("endDate")
    if isinstance(start, str) and isinstance(end, str) and end < start:
        return [(("endDate",), f"must be on or after startDate {_show(start)} (got {_show(end)})")]
    return []


def _show(value: Any) -> str:
    """A value for an error message: strings longer than `MAX_SHOWN_VALUE` are cut."""
    if isinstance(value, str):
        if len(value) > MAX_SHOWN_VALUE:
            return f"{len(value)} characters: {json.dumps(value[:50] + '…', ensure_ascii=False)}"
        return json.dumps(value, ensure_ascii=False)
    if value is None or isinstance(value, bool | int | float):
        return json.dumps(value)
    return _json_type(value)


def _json_type(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list | tuple):
        return "array"
    if isinstance(value, Mapping):
        return "object"
    return type(value).__name__


def _type_name(expected: Any) -> str:
    if isinstance(expected, list):
        return " or ".join(str(item) for item in expected)
    return f"a {expected}" if expected in {"string", "number", "boolean"} else f"an {expected}"


def _format_path(path: _JsonPath) -> str:
    """`("days", 2, "stops", 0, "title")` -> `days[2].stops[0].title`; the root is `(trip)`."""
    text = ""
    for part in path:
        if isinstance(part, int):
            text += f"[{part}]"
        else:
            text += f".{part}" if text else str(part)
    return text or "(trip)"


def _path_sort_key(path: _JsonPath) -> tuple[tuple[int, int, str], ...]:
    """Array indexes sort numerically (`days[2]` before `days[10]`)."""
    return tuple((0, part, "") if isinstance(part, int) else (1, 0, part) for part in path)


# --- loading ----------------------------------------------------------------------------------


async def fetch_trip_schema(http: httpx.AsyncClient, url: str) -> dict[str, Any]:
    """GET `url` (`Accept: application/json`, `HTTP_TIMEOUT_SECONDS`, no cookies) and return the
    decoded JSON object; `file://` URLs are read from disk instead. Raises
    `TripSchemaUnavailableError` on network errors, non-200 statuses or non-object JSON.

    A `file:` URL may be absolute (`PINNED_SCHEMA_URL`, `file:///app/pinned/trip.schema.json`)
    or relative to backend/ (`file:pinned/trip.schema.json`), the directory Railway ships. The
    shared client's cookie jar is never sent: the request is built, stripped of its `Cookie`
    header, then sent.
    """
    try:
        scheme = urlsplit(url).scheme.lower()
    except ValueError as exc:
        msg = f"TRIP_SCHEMA_URL {url!r} is not a URL: {exc}"
        raise TripSchemaUnavailableError(msg) from exc
    if scheme == "file":
        path = _file_url_path(url)
        return await asyncio.to_thread(_read_json_file, path, url)
    if scheme not in {"http", "https"}:
        msg = f"TRIP_SCHEMA_URL {url!r} must be an https:// or file:// URL"
        raise TripSchemaUnavailableError(msg)
    try:
        request = http.build_request(
            "GET", url, headers={"Accept": "application/json"}, timeout=HTTP_TIMEOUT_SECONDS
        )
        request.headers.pop("Cookie", None)
        response = await http.send(request)
    except (httpx.HTTPError, httpx.InvalidURL) as exc:
        msg = f"GET {url} failed: {type(exc).__name__}: {exc}"
        raise TripSchemaUnavailableError(msg) from exc
    if response.status_code != httpx.codes.OK:
        msg = f"GET {url} answered HTTP {response.status_code}"
        raise TripSchemaUnavailableError(msg)
    return _decode_object(response.content, url)


def load_dev_fallback_schema() -> dict[str, Any]:
    """Read `DEV_FALLBACK_SCHEMA_PATH`. Raises `TripSchemaUnavailableError` if it is missing."""
    return _read_json_file(DEV_FALLBACK_SCHEMA_PATH, DEV_FALLBACK_SCHEMA_PATH.as_uri())


def _file_url_path(url: str) -> Path:
    parts = urlsplit(url)
    if parts.netloc not in {"", "localhost"}:
        msg = f"TRIP_SCHEMA_URL {url!r} names a remote host; use file:///absolute/path"
        raise TripSchemaUnavailableError(msg)
    path = Path(url2pathname(parts.path))
    return path if path.is_absolute() else BACKEND_DIR / path


def _read_json_file(path: Path, url: str) -> dict[str, Any]:
    try:
        content = path.read_bytes()
    except OSError as exc:
        msg = f"cannot read {url}: {exc.strerror or exc}"
        raise TripSchemaUnavailableError(msg) from exc
    return _decode_object(content, url)


def _decode_object(content: bytes, url: str) -> dict[str, Any]:
    if len(content) > MAX_SCHEMA_BYTES:
        msg = f"trip.json from {url} is larger than {MAX_SCHEMA_BYTES} bytes"
        raise TripSchemaUnavailableError(msg)
    try:
        data: Any = json.loads(content)
    except ValueError as exc:
        msg = f"trip.json from {url} is not valid JSON: {exc}"
        raise TripSchemaUnavailableError(msg) from exc
    if not isinstance(data, dict):
        msg = f"trip.json from {url} is not a JSON object"
        raise TripSchemaUnavailableError(msg)
    return data


class TripSchemaStore:
    """Holds the current `TripSchema` for the process (`sessions.PlannerServices.trip_schema`).

    Attempts are serialized by a lock, so concurrent `require()` calls trigger one download.
    Besides the lazy retry in `require()`, `retry_until_loaded()` is a ready-made background
    task that keeps trying every `RETRY_INTERVAL_SECONDS` until the schema loads. Once loaded,
    `require()` refreshes the schema every `REFRESH_SECONDS` (module docstring).
    """

    def __init__(
        self,
        settings: Settings,
        http: httpx.AsyncClient,
        *,
        now: Callable[[], dt.datetime] | None = None,
        fallback_path: Path = DEV_FALLBACK_SCHEMA_PATH,
    ) -> None:
        """`now` defaults to `clock.now`, `fallback_path` is overridable for tests."""
        self._settings = settings
        self._http = http
        self._now = now or clock.now
        self._fallback_path = fallback_path
        self._schema: TripSchema | None = None
        self._last_attempt: dt.datetime | None = None
        self._last_error: str | None = None
        self._refresh_failed = False
        self._lock = asyncio.Lock()

    @property
    def url(self) -> str:
        """`Settings.trip_schema_url`, where the schema is downloaded from."""
        return self._settings.trip_schema_url

    @property
    def last_error(self) -> str | None:
        """Why the last attempt failed (English, for logs and 503 details); None after a load
        or a successful refresh. After a failed refresh the last good schema stays in use."""
        return self._last_error

    async def load(self) -> TripSchema | None:
        """Startup: fetch `settings.trip_schema_url`, falling back as the module docstring says.
        Returns the schema, or None in production when the download failed (logged as an error
        with the URL and reason). Never raises: startup must not depend on TripTracker."""
        try:
            async with self._lock:
                await self._attempt()
        except Exception as exc:  # startup must survive anything, but say so loudly
            self._last_error = f"unexpected {type(exc).__name__} while loading {self.url}"
            log.exception("trip_schema_load_crashed", url=self.url)
        return self._schema

    def current(self) -> TripSchema | None:
        """The schema loaded so far, without I/O."""
        return self._schema

    async def require(self) -> TripSchema:
        """The current schema. If there is none, try the download again (at most once per
        `RETRY_INTERVAL_SECONDS`); raises `TripSchemaUnavailableError` when still missing. If
        the copy in use was last checked `REFRESH_SECONDS` ago (`RETRY_INTERVAL_SECONDS` after
        a failed refresh), download it again first (`_refresh`): never raises for that."""
        schema = self._schema
        if schema is not None and not self._refresh_due():
            return schema
        async with self._lock:
            if self._schema is None:
                if self._retry_due():
                    await self._attempt()
            elif self._refresh_due():
                await self._refresh()
            schema = self._schema
        if schema is None:
            msg = f"trip.json is not available from {self.url}: {self._last_error}"
            raise TripSchemaUnavailableError(msg)
        return schema

    async def retry_until_loaded(self) -> TripSchema:
        """Background retry: every `RETRY_INTERVAL_SECONDS`, try again until a schema is loaded,
        then return it. Meant to run as a task next to the planner (cancel it on shutdown)."""
        while True:
            async with self._lock:
                if self._schema is None and self._retry_due():
                    await self._attempt()
                schema = self._schema
            if schema is not None:
                return schema
            await asyncio.sleep(RETRY_INTERVAL_SECONDS)

    def _retry_due(self) -> bool:
        if self._last_attempt is None:
            return True
        elapsed = (self._now() - self._last_attempt).total_seconds()
        return elapsed >= RETRY_INTERVAL_SECONDS

    def _refresh_due(self) -> bool:
        """True when the loaded schema should be downloaded again."""
        if self._last_attempt is None:
            return True
        interval = RETRY_INTERVAL_SECONDS if self._refresh_failed else REFRESH_SECONDS
        return (self._now() - self._last_attempt).total_seconds() >= interval

    async def _refresh(self) -> None:
        """Download the configured URL again while a schema is loaded. A new document replaces
        the current one (a changed sha256 is logged as a warning); a failure keeps the current
        one, logged, and is retried after `RETRY_INTERVAL_SECONDS`. Never raises."""
        current = self._schema
        if current is None:
            return
        self._last_attempt = self._now()
        url = self.url
        source: SchemaSource = "file" if url.lower().startswith("file:") else "remote"
        try:
            document = await fetch_trip_schema(self._http, url)
            fresh = TripSchema.from_document(
                document, source=source, url=url, loaded_at=self._now()
            )
        except Exception as exc:  # any failure: keep validating with the last good copy
            if isinstance(exc, TripSchemaUnavailableError):
                reason = str(exc)
            else:
                reason = f"unexpected {type(exc).__name__} while refreshing {url}"
            self._last_error = reason
            self._refresh_failed = True
            log.warning(
                "trip_schema_refresh_failed",
                url=url,
                reason=reason,
                kept_sha256=current.sha256,
                kept_source=current.source,
                retry_seconds=RETRY_INTERVAL_SECONDS,
            )
            return
        self._last_error = None
        self._refresh_failed = False
        if fresh.sha256 != current.sha256:
            log.warning(
                "trip_schema_changed",
                url=url,
                old_sha256=current.sha256,
                new_sha256=fresh.sha256,
                old_source=current.source,
            )
        elif (fresh.source, fresh.url) == (current.source, current.url):
            return  # unchanged: keep the same object (and its compiled validator)
        else:
            log.info("trip_schema_loaded", url=url, source=source, sha256=fresh.sha256)
        self._schema = fresh

    async def _attempt(self) -> None:
        """One try: the configured URL, then (development only) the vendored fallback."""
        self._last_attempt = self._now()
        url = self.url
        source: SchemaSource = "file" if url.lower().startswith("file:") else "remote"
        try:
            document = await fetch_trip_schema(self._http, url)
            schema = TripSchema.from_document(
                document, source=source, url=url, loaded_at=self._now()
            )
        except TripSchemaUnavailableError as exc:
            self._last_error = str(exc)
            if self._settings.is_production:
                log.error(
                    "trip_schema_unavailable",
                    url=url,
                    reason=str(exc),
                    retry_seconds=RETRY_INTERVAL_SECONDS,
                )
                return
            fallback = await self._load_fallback(reason=str(exc))
            if fallback is None:
                return
            schema = fallback
        else:
            log.info("trip_schema_loaded", url=url, source=source, sha256=schema.sha256)
        self._schema = schema
        self._last_error = None

    async def _load_fallback(self, *, reason: str) -> TripSchema | None:
        """Development only: the vendored copy, with a warning that names the failed URL."""
        path = self._fallback_path
        fallback_url = path.as_uri()
        try:
            document = await asyncio.to_thread(_read_json_file, path, fallback_url)
            schema = TripSchema.from_document(
                document, source="dev_fallback", url=fallback_url, loaded_at=self._now()
            )
        except TripSchemaUnavailableError as exc:
            self._last_error = f"{reason}; development fallback failed too: {exc}"
            log.error("trip_schema_unavailable", url=self.url, reason=self._last_error)
            return None
        log.warning(
            "trip_schema_dev_fallback",
            url=self.url,
            reason=reason,
            fallback=str(path),
            sha256=schema.sha256,
        )
        return schema
