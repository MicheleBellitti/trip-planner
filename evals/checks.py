"""Deterministic eval checks over one finished plan: zero cost, no network, no clock.

Spec: "Eval sui piani" and "Eval strutturate e versioning dei prompt" (the "Controlli
deterministici" row). Every check is a pure function over the same four inputs:

- `request`: the `app.request.PlanRequest` that started the plan;
- `plan`: the accepted Plan as stored in `plans.plan` (JSON), or None when none was accepted;
- `trip`: the TripTracker Trip stored in `plans.trip` (JSON), or None;
- `metadata`: what the run measured (`RunMetadata`: final status, submit attempts, cost, web
  searches, profile).

Some take keyword-only extras that keep them pure and testable: the link checker (default:
the backend's `app.links.check_link`), the TripTracker JSON Schema (default: the vendored
trip.json the backend falls back to in development) and the request's expectations from
evals/requests.yaml.

Each returns a `CheckResult`. Statuses: `pass`; `warn` (worth reading, never blocks); `fail`;
`error` (the check itself could not run, e.g. a backend function is not implemented yet);
`skip` (nothing to check, e.g. no plan for a plan-content check: the run is already blocked by
`schema_valid` and `submit_plan_attempts`). A check *blocks* (evals/compare.py) when it is
`blocking` and its status is `fail` or `error`. Every check is blocking except
`cost_and_searches_vs_estimate`, which records cost and web searches against the spec's
estimate; cost regressions are gated by compare.py's +30% rule instead.

Check names are stable keys: results files and compare.py use them.
"""

from __future__ import annotations

import datetime as dt
import json
import re
import sys
import unicodedata
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field, replace
from functools import cache
from pathlib import Path
from typing import Any, Literal, Protocol, cast
from urllib.parse import urlsplit

EVALS_DIR = Path(__file__).resolve().parent
REPO_DIR = EVALS_DIR.parent
BACKEND_DIR = REPO_DIR / "backend"
if str(BACKEND_DIR) not in sys.path:  # `app` lives in backend/; evals run from anywhere
    sys.path.insert(0, str(BACKEND_DIR))

from pydantic import ValidationError  # noqa: E402

from app.plan import Plan, describe_validation_errors  # noqa: E402
from app.request import PlanRequest  # noqa: E402

TRIP_SCHEMA_PATH = BACKEND_DIR / "tests" / "fixtures" / "triptracker" / "trip.schema.json"
"""TripTracker's exported trip.json as vendored in the backend (its development fallback,
`app.triptracker_schema.DEV_FALLBACK_SCHEMA_PATH`)."""

CheckStatus = Literal["pass", "warn", "fail", "error", "skip"]
Profile = Literal["development", "production"]

# Stable check names.
SCHEMA_VALID = "schema_valid"
BOOK_BY_BEFORE_SCHEDULED = "book_by_before_scheduled_for"
WITHIN_BUDGET = "within_budget_or_warned"
PRICES_HAVE_SOURCE = "prices_have_source"
LINKS_ALLOWED = "links_on_allowed_domains"
NO_EMPTY_DAYS = "no_empty_days"
SUBMIT_ATTEMPTS = "submit_plan_attempts"
COST_VS_ESTIMATE = "cost_and_searches_vs_estimate"
MATCHES_REQUEST = "matches_request"
DEAD_LINKS = "dead_links"
CHOICES_ASKED = "choices_asked"

CHECK_NAMES: tuple[str, ...] = (
    SCHEMA_VALID,
    BOOK_BY_BEFORE_SCHEDULED,
    WITHIN_BUDGET,
    PRICES_HAVE_SOURCE,
    LINKS_ALLOWED,
    NO_EMPTY_DAYS,
    SUBMIT_ATTEMPTS,
    COST_VS_ESTIMATE,
    MATCHES_REQUEST,
    DEAD_LINKS,
    CHOICES_ASKED,
)

MAX_SUBMIT_ATTEMPTS = 2
"""Spec: "il piano passa la validazione al primo o al secondo tentativo"."""

MAX_DETAILS = 20
"""Detail lines kept per check (the rest is counted), so results files stay readable."""

BUDGET_WARNING = re.compile(r"(?<!\w)budget(?!\w)")
"""A plan warning that mentions the budget (accent- and case-folded text). The coordinator
writes "budget" in the warning that says the total is over it (spec: "oppure c'e' un avviso in
warnings che lo dice")."""


# --- results ------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CheckResult:
    """The outcome of one check on one plan."""

    name: str
    status: CheckStatus
    blocking: bool
    message: str
    details: list[str] = field(default_factory=list[str])

    @property
    def blocks(self) -> bool:
        """True when this result must block the PR (compare.py)."""
        return self.blocking and self.status in ("fail", "error")

    def to_json(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status,
            "blocking": self.blocking,
            "message": self.message,
            "details": list(self.details),
        }


@dataclass(frozen=True, slots=True)
class CostEstimate:
    """The spec's per-plan estimate ("Costi e controlli di spesa"), in US cents."""

    cost_cents: int
    web_search_requests: int
    session_budget_cents: int


COST_ESTIMATES: Mapping[Profile, CostEstimate] = {
    # The spec said "~0,55 $" with 20 searches and a "60" budget; the 2026-10-12 Lisbon session
    # cost 62¢ without finishing. After the cost cuts (3 searches per agent, effort, a fetch
    # page cap) the estimate is ~55-85¢, ~71¢ central (docs/managed-agents-notes.md §5), with a
    # 100¢ session budget.
    "development": CostEstimate(cost_cents=71, web_search_requests=15, session_budget_cents=100),
    # Opus 5.5 ~0.52 $ + Sonnet 5.5 subagents ~1.34 $ + 60 searches 0.60 $ + runtime 0.02 $ =
    # "~2,5 $"; session budget "400".
    "production": CostEstimate(cost_cents=250, web_search_requests=60, session_budget_cents=400),
}


@dataclass(frozen=True, slots=True)
class RunMetadata:
    """What evals/run.py measured for one plan."""

    profile: Profile = "development"
    status: str | None = None
    """`plans.status` when the run stopped following the plan (ready, failed, ...)."""
    submit_attempts: int | None = None
    """`plans.submit_attempts`: calls to submit_plan the backend evaluated."""
    cost_cents: int | None = None
    """Session list cost in US cents (`session.usage.list_cost`), None when unknown."""
    web_search_requests: int | None = None
    """`usage.server_tool_use.web_search_requests` of the session, None when unknown."""
    link_health: Mapping[str, Any] | None = None
    """`plans.link_health` (URL to verdict); None (a plan stored before the check) or `{}`
    (the checks did not run) when the links were not checked."""
    choice_kinds: tuple[str, ...] | None = None
    """The kinds of the questions the plan asked the traveller (`choices.kind`); None when
    they were not collected."""


@dataclass(frozen=True, slots=True)
class Expectations:
    """The `expect` block of an evals/requests.yaml entry."""

    travelers: int | None = None
    budget_eur: int | None = None
    start: dt.date | None = None
    end: dt.date | None = None
    month: str | None = None
    nights: int | None = None
    destination_any: tuple[str, ...] = ()
    must_mention: tuple[tuple[str, ...], ...] = ()
    must_not_book: tuple[str, ...] = ()

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> Expectations:
        dates = cast(Mapping[str, Any], data.get("dates") or {})
        return cls(
            travelers=_optional_int(data.get("travelers")),
            budget_eur=_optional_int(data.get("budget_eur")),
            start=_optional_date(dates.get("start")),
            end=_optional_date(dates.get("end")),
            month=None if dates.get("month") is None else str(dates["month"]),
            nights=_optional_int(dates.get("nights")),
            destination_any=tuple(str(k) for k in data.get("destination_any") or ()),
            must_mention=tuple(
                tuple(str(k) for k in group) for group in data.get("must_mention") or ()
            ),
            must_not_book=tuple(str(k) for k in data.get("must_not_book") or ()),
        )


def _optional_int(value: Any) -> int | None:
    return None if value is None else int(value)


def _optional_date(value: Any) -> dt.date | None:
    if value is None or isinstance(value, dt.date):
        return value
    return dt.date.fromisoformat(str(value))


class LinkVerdictLike(Protocol):
    """The part of `app.links.LinkVerdict` the link check reads."""

    @property
    def allowed(self) -> bool: ...
    @property
    def host(self) -> str | None: ...
    @property
    def reason(self) -> str | None: ...


LinkChecker = Callable[[str], LinkVerdictLike]


def default_link_checker(url: str) -> LinkVerdictLike:
    """The backend's allowlist (`app.links.check_link`), every provider."""
    from app.links import check_link

    return check_link(url)


@cache
def load_trip_schema(path: Path = TRIP_SCHEMA_PATH) -> dict[str, Any] | None:
    """The vendored TripTracker trip.json, or None when the file is missing."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None


# --- helpers ------------------------------------------------------------------------------------


def _result(
    name: str,
    status: CheckStatus,
    message: str,
    details: Sequence[str] = (),
    *,
    blocking: bool = True,
) -> CheckResult:
    lines = list(details)
    if len(lines) > MAX_DETAILS:
        lines = [*lines[:MAX_DETAILS], f"... and {len(lines) - MAX_DETAILS} more"]
    return CheckResult(name=name, status=status, blocking=blocking, message=message, details=lines)


def _no_plan(name: str, metadata: RunMetadata) -> CheckResult:
    return _result(name, "skip", f"no accepted plan (status {metadata.status or 'unknown'})")


def _mappings(value: Any) -> list[Mapping[str, Any]]:
    """The dict items of a JSON list (anything else is ignored: schema_valid reports it)."""
    if not isinstance(value, list):
        return []
    return [cast(Mapping[str, Any], item) for item in value if isinstance(item, Mapping)]


def _plan_bookings(plan: Mapping[str, Any]) -> Iterator[tuple[str, Mapping[str, Any]]]:
    """Every booking and alternative of the plan with its JSON path."""
    for list_name in ("bookings", "alternatives"):
        for index, booking in enumerate(_mappings(plan.get(list_name))):
            yield f"{list_name}[{index}]", booking


def parse_instant(value: Any) -> dt.datetime | None:
    """An ISO 8601 instant, or None when it is not a string or not parseable."""
    if not isinstance(value, str):
        return None
    try:
        return dt.datetime.fromisoformat(value)
    except ValueError:
        return None


def parse_date(value: Any) -> dt.date | None:
    if not isinstance(value, str):
        return None
    try:
        return dt.date.fromisoformat(value)
    except ValueError:
        return None


def fold(text: str) -> str:
    """Lower-case, accent-free text for keyword matching ("Città" -> "citta")."""
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch)).casefold()


def mentions(folded_text: str, keyword: str) -> bool:
    """True when `keyword` starts a word of `folded_text` (already `fold`ed): "bambin" matches
    "bambini", "volo" does not match "tavolo"."""
    return re.search(r"(?<!\w)" + re.escape(fold(keyword)), folded_text) is not None


def plan_text(plan: Mapping[str, Any]) -> str:
    """Every user-facing text of the plan, folded: titles, notes, summary, warnings, names."""
    parts: list[str] = []
    for key in ("title", "destination", "summary", "lodging_name", "lodging_address"):
        if isinstance(plan.get(key), str):
            parts.append(plan[key])
    parts.extend(w for w in plan.get("warnings") or () if isinstance(w, str))
    for day in _mappings(plan.get("days")):
        if isinstance(day.get("title"), str):
            parts.append(day["title"])
        for stop in _mappings(day.get("stops")):
            parts.extend(
                stop[key]
                for key in ("title", "location_name", "address", "notes")
                if isinstance(stop.get(key), str)
            )
    for _, booking in _plan_bookings(plan):
        parts.extend(
            booking[key]
            for key in ("title", "vendor", "notes", "book_by_reason")
            if isinstance(booking.get(key), str)
        )
    return fold("\n".join(parts))


def booking_total_eur_cents(
    plan: Mapping[str, Any], trip: Mapping[str, Any] | None
) -> tuple[int, int]:
    """(known total in EUR cents, number of priced bookings whose EUR amount is unknown).

    The chosen bookings only (alternatives are not part of the plan's cost). EUR amounts come
    from the Trip's `costCents` (the backend already converted other currencies with fx.py),
    matched to the plan's bookings by position (plan_to_trip keeps the order); without a Trip,
    or when the lists don't line up, from EUR prices of the plan itself."""
    plan_bookings = _mappings(plan.get("bookings"))
    trip_bookings = _mappings(trip.get("bookings")) if trip is not None else []
    aligned = trip is not None and len(trip_bookings) == len(plan_bookings)
    total = 0
    unknown = 0
    for index, booking in enumerate(plan_bookings):
        cost = trip_bookings[index].get("costCents") if aligned else None
        if isinstance(cost, int) and not isinstance(cost, bool):
            total += cost
            continue
        price = booking.get("price")
        if not isinstance(price, Mapping):
            continue
        price = cast(Mapping[str, Any], price)
        amount = price.get("amount_cents")
        if price.get("currency") == "EUR" and isinstance(amount, int):
            total += amount
        else:
            unknown += 1
    return total, unknown


def _euro(cents: int) -> str:
    return f"{cents / 100:.2f} EUR"


# --- the checks -------------------------------------------------------------------------------


def check_schema_valid(
    request: PlanRequest,
    plan: Mapping[str, Any] | None,
    trip: Mapping[str, Any] | None,
    metadata: RunMetadata,
    *,
    trip_schema: Mapping[str, Any] | None = None,
) -> CheckResult:
    """The plan validates against the Plan contract (`app.plan.Plan`, the source of
    schema/plan.json) and its Trip against TripTracker's trip.json, plus the `endDate >=
    startDate` refine the JSON Schema export loses."""
    if plan is None:
        return _result(
            SCHEMA_VALID, "fail", f"no plan was accepted (status {metadata.status or 'unknown'})"
        )
    details: list[str] = []
    fields = {key: value for key, value in plan.items() if key in Plan.model_fields}
    extra = sorted(set(plan) - set(fields))
    try:
        Plan.model_validate(fields)
    except ValidationError as error:
        details.extend(f"plan: {line}" for line in describe_validation_errors(error))
    if trip is None:
        details.append("trip: missing (an accepted plan always stores its TripTracker Trip)")
    else:
        schema = trip_schema if trip_schema is not None else load_trip_schema()
        if schema is None:
            return _result(SCHEMA_VALID, "error", f"trip.json not found at {TRIP_SCHEMA_PATH}")
        details.extend(f"trip: {line}" for line in validate_trip_document(trip, schema))
    if details:
        return _result(SCHEMA_VALID, "fail", f"{len(details)} schema problem(s)", details)
    note = f" (stored plan also has {', '.join(extra)}: ignored)" if extra else ""
    return _result(SCHEMA_VALID, "pass", f"plan and trip are valid{note}")


def validate_trip_document(trip: Mapping[str, Any], schema: Mapping[str, Any]) -> list[str]:
    """Error lines of `trip` against TripTracker's JSON Schema (draft 2020-12), plus the Zod
    refine `endDate >= startDate`."""
    from jsonschema import Draft202012Validator

    validator = Draft202012Validator(schema)
    lines = [
        f"{'/'.join(str(part) for part in error.absolute_path) or '(trip)'}: {error.message}"
        for error in sorted(validator.iter_errors(trip), key=lambda e: list(e.absolute_path))
    ]
    start, end = trip.get("startDate"), trip.get("endDate")
    if isinstance(start, str) and isinstance(end, str) and end < start:
        lines.append(f"endDate: {end} is before startDate {start}")
    return lines


def check_book_by_before_scheduled_for(
    request: PlanRequest,
    plan: Mapping[str, Any] | None,
    trip: Mapping[str, Any] | None,
    metadata: RunMetadata,
) -> CheckResult:
    """No booking has `book_by` equal to or after `scheduled_for` (contract rule 1), in the
    plan (bookings and alternatives) and in the Trip (`dueAt` < `scheduledFor`, where the
    backend's fallback `dueAt` also lands). Instants must carry a UTC offset."""
    if plan is None:
        return _no_plan(BOOK_BY_BEFORE_SCHEDULED, metadata)
    problems: list[str] = []
    pairs = 0
    entries: list[tuple[str, Any, Any, str, str]] = [
        (path, b.get("book_by"), b.get("scheduled_for"), "book_by", "scheduled_for")
        for path, b in _plan_bookings(plan)
    ]
    if trip is not None:
        entries.extend(
            (f"trip.bookings[{i}]", b.get("dueAt"), b.get("scheduledFor"), "dueAt", "scheduledFor")
            for i, b in enumerate(_mappings(trip.get("bookings")))
        )
    for path, due_raw, when_raw, due_name, when_name in entries:
        due, when = parse_instant(due_raw), parse_instant(when_raw)
        for name, raw, value in ((due_name, due_raw, due), (when_name, when_raw, when)):
            if raw is None:
                continue
            if value is None:
                problems.append(f"{path}.{name}: not an ISO 8601 instant ({raw!r})")
            elif value.utcoffset() is None:
                problems.append(f"{path}.{name}: no UTC offset ({raw})")
        if due is None or when is None or due.utcoffset() is None or when.utcoffset() is None:
            continue
        pairs += 1
        if due >= when:
            problems.append(f"{path}: {due_name} {due_raw} is not before {when_name} {when_raw}")
    if problems:
        return _result(BOOK_BY_BEFORE_SCHEDULED, "fail", f"{len(problems)} problem(s)", problems)
    return _result(
        BOOK_BY_BEFORE_SCHEDULED, "pass", f"{pairs} deadline(s) strictly before their event"
    )


def check_within_budget(
    request: PlanRequest,
    plan: Mapping[str, Any] | None,
    trip: Mapping[str, Any] | None,
    metadata: RunMetadata,
) -> CheckResult:
    """The estimated total of the chosen bookings is within `budget_eur`, or a plan warning
    says it is not (one that mentions "budget")."""
    if plan is None:
        return _no_plan(WITHIN_BUDGET, metadata)
    budget_cents = request.budget_eur * 100
    total, unknown = booking_total_eur_cents(plan, trip)
    warnings = [w for w in plan.get("warnings") or () if isinstance(w, str)]
    budget_warnings = [w for w in warnings if BUDGET_WARNING.search(fold(w))]
    details = [f"bookings total {_euro(total)}, budget {_euro(budget_cents)}"]
    if unknown:
        details.append(f"{unknown} priced booking(s) without an EUR amount, not counted")
    details.extend(f"warning: {w}" for w in budget_warnings)
    if total > budget_cents:
        if budget_warnings:
            return _result(WITHIN_BUDGET, "pass", "over budget, with an explicit warning", details)
        return _result(WITHIN_BUDGET, "fail", "over budget and no warning says so", details)
    if unknown and not budget_warnings:
        return _result(
            WITHIN_BUDGET, "warn", "within budget, but some prices have no EUR amount", details
        )
    return _result(WITHIN_BUDGET, "pass", "within budget", details)


def check_prices_have_source(
    request: PlanRequest,
    plan: Mapping[str, Any] | None,
    trip: Mapping[str, Any] | None,
    metadata: RunMetadata,
) -> CheckResult:
    """Every price (bookings and alternatives) has an http(s) `source_url` and a
    `retrieved_at` instant with a UTC offset (contract rule 5)."""
    if plan is None:
        return _no_plan(PRICES_HAVE_SOURCE, metadata)
    problems: list[str] = []
    prices = 0
    for path, booking in _plan_bookings(plan):
        price = booking.get("price")
        if price is None:
            continue
        prices += 1
        if not isinstance(price, Mapping):
            problems.append(f"{path}.price: not an object")
            continue
        price = cast(Mapping[str, Any], price)
        source = price.get("source_url")
        if not isinstance(source, str) or not re.match(r"https?://[^\s/]+", source):
            problems.append(f"{path}.price.source_url: missing or not an http(s) URL")
        retrieved = parse_instant(price.get("retrieved_at"))
        if retrieved is None or retrieved.utcoffset() is None:
            problems.append(f"{path}.price.retrieved_at: missing or without a UTC offset")
    if problems:
        return _result(PRICES_HAVE_SOURCE, "fail", f"{len(problems)} problem(s)", problems)
    return _result(PRICES_HAVE_SOURCE, "pass", f"{prices} price(s), each with source and time")


def check_links_allowed(
    request: PlanRequest,
    plan: Mapping[str, Any] | None,
    trip: Mapping[str, Any] | None,
    metadata: RunMetadata,
    *,
    link_checker: LinkChecker | None = None,
) -> CheckResult:
    """Every booking link (plan bookings and alternatives, Trip booking URLs) is on an
    allowed domain according to the backend's allowlist (`app.links.check_link`). Stop URLs
    are informational and not domain-checked (backend decision 13)."""
    if plan is None:
        return _no_plan(LINKS_ALLOWED, metadata)
    checker = link_checker or default_link_checker
    links = [(f"{path}.link", b.get("link")) for path, b in _plan_bookings(plan)]
    if trip is not None:
        links.extend(
            (f"trip.bookings[{i}].url", b.get("url"))
            for i, b in enumerate(_mappings(trip.get("bookings")))
        )
    problems: list[str] = []
    checked = 0
    for path, url in links:
        if url is None:
            continue
        if not isinstance(url, str) or not url:
            problems.append(f"{path}: not a URL")
            continue
        try:
            verdict = checker(url)
        except NotImplementedError:
            return _result(
                LINKS_ALLOWED, "error", "app.links.check_link is not implemented yet: cannot check"
            )
        checked += 1
        if not verdict.allowed:
            problems.append(
                f"{path}: {verdict.host or 'unparseable host'} not allowed ({verdict.reason})"
            )
    if problems:
        return _result(LINKS_ALLOWED, "fail", f"{len(problems)} link(s) not allowed", problems)
    return _result(LINKS_ALLOWED, "pass", f"{checked} link(s), all on allowed domains")


def check_no_empty_days(
    request: PlanRequest,
    plan: Mapping[str, Any] | None,
    trip: Mapping[str, Any] | None,
    metadata: RunMetadata,
) -> CheckResult:
    """Every day strictly between the arrival day (`start_date`) and the departure day
    (`end_date`) has at least one stop. An empty arrival or departure day is only a warning."""
    if plan is None:
        return _no_plan(NO_EMPTY_DAYS, metadata)
    start, end = parse_date(plan.get("start_date")), parse_date(plan.get("end_date"))
    if start is None or end is None or end < start:
        return _result(NO_EMPTY_DAYS, "fail", "start_date/end_date missing or inconsistent")
    stops_by_date: dict[dt.date, int] = {}
    for day in _mappings(plan.get("days")):
        date = parse_date(day.get("date"))
        if date is not None:
            stops = day.get("stops")
            stops_by_date[date] = stops_by_date.get(date, 0) + (
                len(stops) if isinstance(stops, list) else 0
            )
    empty: list[dt.date] = []
    edge_empty: list[dt.date] = []
    current = start
    while current <= end:
        if not stops_by_date.get(current):
            (edge_empty if current in (start, end) else empty).append(current)
        current += dt.timedelta(days=1)
    if empty:
        return _result(
            NO_EMPTY_DAYS,
            "fail",
            f"{len(empty)} day(s) without stops between arrival and departure",
            [f"{date.isoformat()}: no stops" for date in empty],
        )
    if edge_empty:
        return _result(
            NO_EMPTY_DAYS,
            "warn",
            "arrival or departure day without stops",
            [f"{date.isoformat()}: no stops" for date in edge_empty],
        )
    days = (end - start).days + 1
    return _result(NO_EMPTY_DAYS, "pass", f"all {days} day(s) have stops")


def check_submit_attempts(
    request: PlanRequest,
    plan: Mapping[str, Any] | None,
    trip: Mapping[str, Any] | None,
    metadata: RunMetadata,
) -> CheckResult:
    """The plan was accepted (status `ready`) at the first or second `submit_plan` call."""
    attempts = metadata.submit_attempts
    if metadata.status != "ready" or plan is None:
        return _result(
            SUBMIT_ATTEMPTS,
            "fail",
            f"plan not accepted: status {metadata.status or 'unknown'}, "
            f"{attempts if attempts is not None else 'unknown'} attempt(s)",
        )
    if attempts is None:
        return _result(SUBMIT_ATTEMPTS, "fail", "submit_plan attempts not recorded")
    if 1 <= attempts <= MAX_SUBMIT_ATTEMPTS:
        return _result(SUBMIT_ATTEMPTS, "pass", f"accepted at attempt {attempts}")
    return _result(
        SUBMIT_ATTEMPTS,
        "fail",
        f"accepted after {attempts} attempts (at most {MAX_SUBMIT_ATTEMPTS} allowed)",
    )


def check_cost_vs_estimate(
    request: PlanRequest,
    plan: Mapping[str, Any] | None,
    trip: Mapping[str, Any] | None,
    metadata: RunMetadata,
) -> CheckResult:
    """Session cost and web searches recorded and compared with the spec's estimate for the
    profile. Never blocking: a warning to read (compare.py gates cost regressions)."""
    estimate = COST_ESTIMATES[metadata.profile]
    details: list[str] = []
    over: list[str] = []
    if metadata.cost_cents is None:
        over.append("session cost not recorded (usage.list_cost absent)")
    else:
        details.append(
            f"cost {metadata.cost_cents}¢, estimate {estimate.cost_cents}¢, "
            f"session budget {estimate.session_budget_cents}¢ ({metadata.profile})"
        )
        if metadata.cost_cents > estimate.cost_cents:
            over.append(f"cost {metadata.cost_cents}¢ above the estimate {estimate.cost_cents}¢")
    if metadata.web_search_requests is None:
        over.append("web search count not recorded")
    else:
        details.append(
            f"web searches {metadata.web_search_requests}, estimate {estimate.web_search_requests}"
        )
        if metadata.web_search_requests > estimate.web_search_requests:
            over.append(
                f"{metadata.web_search_requests} web searches, above the estimate "
                f"{estimate.web_search_requests}"
            )
    if over:
        return _result(COST_VS_ESTIMATE, "warn", "; ".join(over), details, blocking=False)
    return _result(COST_VS_ESTIMATE, "pass", "within the spec's estimate", details, blocking=False)


def check_matches_request(
    request: PlanRequest,
    plan: Mapping[str, Any] | None,
    trip: Mapping[str, Any] | None,
    metadata: RunMetadata,
    *,
    expect: Expectations | None = None,
) -> CheckResult:
    """The plan respects the request's expected constraints (evals/requests.yaml `expect`):
    number of travellers, dates (exact, or a start in the flexible month with the asked
    nights), destination, keyword groups that must appear in the plan, keywords that must not
    appear in any booking's title or vendor. The budget is `within_budget_or_warned`."""
    if expect is None:
        return _result(MATCHES_REQUEST, "skip", "no expectations for this request")
    if plan is None:
        return _no_plan(MATCHES_REQUEST, metadata)
    problems: list[str] = []
    travelers = plan.get("travelers")
    expected_travelers = (
        expect.travelers if expect.travelers is not None else len(request.travelers)
    )
    if travelers != expected_travelers:
        problems.append(f"travelers: {travelers}, expected {expected_travelers}")
    start, end = parse_date(plan.get("start_date")), parse_date(plan.get("end_date"))
    problems.extend(_date_problems(expect, start, end))
    destination = plan.get("destination")
    if expect.destination_any and not (
        isinstance(destination, str)
        and any(mentions(fold(destination), k) for k in expect.destination_any)
    ):
        problems.append(
            f"destination {destination!r} matches none of {list(expect.destination_any)}"
        )
    text = plan_text(plan)
    for group in expect.must_mention:
        if not any(mentions(text, keyword) for keyword in group):
            problems.append(f"the plan mentions none of {list(group)}")
    for path, booking in _plan_bookings(plan):
        if not path.startswith("bookings"):
            continue
        booking_text = fold(" ".join(str(booking.get(k) or "") for k in ("title", "vendor")))
        problems.extend(
            f"{path} mentions forbidden {keyword!r}: {booking.get('title')!r}"
            for keyword in expect.must_not_book
            if mentions(booking_text, keyword)
        )
    if problems:
        return _result(MATCHES_REQUEST, "fail", f"{len(problems)} mismatch(es)", problems)
    return _result(MATCHES_REQUEST, "pass", "travellers, dates, destination and preferences")


def _date_problems(expect: Expectations, start: dt.date | None, end: dt.date | None) -> list[str]:
    if start is None or end is None:
        return ["start_date/end_date missing"]
    problems: list[str] = []
    if expect.start is not None and start != expect.start:
        problems.append(f"start_date {start}, expected {expect.start}")
    if expect.end is not None and end != expect.end:
        problems.append(f"end_date {end}, expected {expect.end}")
    if expect.month is not None and start.strftime("%Y-%m") != expect.month:
        problems.append(f"start_date {start} is not in {expect.month}")
    if expect.nights is not None and (end - start).days != expect.nights:
        problems.append(f"{(end - start).days} night(s), expected {expect.nights}")
    return problems


def check_dead_links(
    request: PlanRequest,
    plan: Mapping[str, Any] | None,
    trip: Mapping[str, Any] | None,
    metadata: RunMetadata,
) -> CheckResult:
    """Counts the links the backend found dead when it accepted the plan. Never blocks: a
    dead link is a warning (the web app shows a fallback), not a failed plan. No verdicts
    (None, or `{}`: the checks did not run) is a skip. "homepage" says whether the dead page has
    a homepage to show (`fallback`), whatever the booking allowlist says about it
    (`fallback_allowed`)."""
    if plan is None:
        return replace(_no_plan(DEAD_LINKS, metadata), blocking=False)
    if not metadata.link_health:
        return _result(DEAD_LINKS, "skip", "links were not checked", blocking=False)
    lines: list[str] = []
    for url, verdict in metadata.link_health.items():
        if not isinstance(verdict, Mapping) or verdict.get("status") != "dead":
            continue
        try:
            host = (urlsplit(url).hostname or "?").lower().removeprefix("www.")
        except ValueError:  # e.g. https://ex[ample.com/x, which httpx accepted
            host = "?"
        fallback = verdict.get("fallback")
        homepage = "yes" if isinstance(fallback, str) and fallback else "no"
        lines.append(f"{host} {verdict.get('reason') or 'dead'} (homepage: {homepage})")
    if lines:
        return _result(
            DEAD_LINKS,
            "warn",
            f"{len(lines)} of {len(metadata.link_health)} link(s) dead",
            lines,
            blocking=False,
        )
    return _result(
        DEAD_LINKS,
        "pass",
        f"{len(metadata.link_health)} link(s) checked, none dead",
        blocking=False,
    )


CHOICE_KIND_ORDER: tuple[str, ...] = ("destination", "journey", "activities", "food", "other")
"""`app.choices.ChoiceKind`, in the order the kinds are printed."""


def _kinds_in_order(kinds: Iterable[str]) -> list[str]:
    known = set(kinds)
    ordered = [kind for kind in CHOICE_KIND_ORDER if kind in known]
    return ordered + sorted(known - set(CHOICE_KIND_ORDER))


def check_choices_asked(
    request: PlanRequest,
    plan: Mapping[str, Any] | None,
    trip: Mapping[str, Any] | None,
    metadata: RunMetadata,
) -> CheckResult:
    """The coordinator pauses with `ask_traveller` about the activities and the food, and about
    the destination when the request says "Suggeriscimi tu". The kinds are a set (the order
    they were asked in is not recorded). Never blocks: a missing pause is a warning."""
    if plan is None:
        return replace(_no_plan(CHOICES_ASKED, metadata), blocking=False)
    if metadata.choice_kinds is None:
        return _result(CHOICES_ASKED, "skip", "choices were not collected", blocking=False)
    expected = {"activities", "food"}
    if request.suggest_destination:
        expected.add("destination")
    asked = _kinds_in_order(metadata.choice_kinds)
    missing = _kinds_in_order(expected - set(asked))
    if missing:
        return _result(
            CHOICES_ASKED,
            "warn",
            f"missing: {', '.join(missing)}",
            [f"asked: {', '.join(asked) or 'none'}"],
            blocking=False,
        )
    return _result(CHOICES_ASKED, "pass", f"asked: {', '.join(asked)}", blocking=False)


# --- running them all ---------------------------------------------------------------------------


Check = Callable[..., CheckResult]

CHECKS: Mapping[str, Check] = {
    SCHEMA_VALID: check_schema_valid,
    BOOK_BY_BEFORE_SCHEDULED: check_book_by_before_scheduled_for,
    WITHIN_BUDGET: check_within_budget,
    PRICES_HAVE_SOURCE: check_prices_have_source,
    LINKS_ALLOWED: check_links_allowed,
    NO_EMPTY_DAYS: check_no_empty_days,
    SUBMIT_ATTEMPTS: check_submit_attempts,
    COST_VS_ESTIMATE: check_cost_vs_estimate,
    MATCHES_REQUEST: check_matches_request,
    DEAD_LINKS: check_dead_links,
    CHOICES_ASKED: check_choices_asked,
}


def run_checks(
    request: PlanRequest,
    plan: Mapping[str, Any] | None,
    trip: Mapping[str, Any] | None,
    metadata: RunMetadata,
    *,
    expect: Expectations | None = None,
    link_checker: LinkChecker | None = None,
    trip_schema: Mapping[str, Any] | None = None,
) -> list[CheckResult]:
    """Every check, in `CHECK_NAMES` order. A check that raises becomes an `error` result
    (blocking), so one malformed plan never stops an eval run."""
    extras: dict[str, dict[str, Any]] = {
        SCHEMA_VALID: {"trip_schema": trip_schema},
        LINKS_ALLOWED: {"link_checker": link_checker},
        MATCHES_REQUEST: {"expect": expect},
    }
    results: list[CheckResult] = []
    for name in CHECK_NAMES:
        check = CHECKS[name]
        try:
            results.append(check(request, plan, trip, metadata, **extras.get(name, {})))
        except Exception as error:  # a malformed plan must not crash the run
            results.append(
                _result(
                    name,
                    "error",
                    f"check crashed: {type(error).__name__}: {error}",
                    blocking=name not in (COST_VS_ESTIMATE, DEAD_LINKS, CHOICES_ASKED),
                )
            )
    return results


def blocking_failures(results: Iterable[CheckResult]) -> list[CheckResult]:
    """The results that block a PR."""
    return [result for result in results if result.blocks]
