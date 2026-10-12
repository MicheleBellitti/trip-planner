"""The plan contract: what the coordinator submits with the `submit_plan` custom tool.

These models are the single source of truth for the plan ("Contratto del piano" in the spec):
`python -m app.schemas` exports `Plan` as schema/plan.json, which is pasted as the
`input_schema` of `submit_plan`. Every field therefore carries an English description written
for the coordinator model, and every validation error is written so that the model can fix its
own output: the consumer returns `plan_rejection_message(error)` as the tool result.

Beyond the field constraints of the spec, the models enforce what TripTracker needs to accept
the translated Trip (non-empty titles, coordinate ranges, at most 120 days) and the contract
rules that must never break:

- every instant carries a UTC offset (`AwareDatetime`);
- `book_by` is strictly before `scheduled_for` when both are set (`book_by != scheduled_for`);
- days fall inside [start_date, end_date], one entry per date;
- stop refs are unique across the plan and every `stop_ref` points at an existing stop;
- `timezone` is an IANA zone name;
- amounts and durations stay far below TripTracker's integer cap (JS `MAX_SAFE_INTEGER`), and
  every text that is copied into a booking's notes is capped, so the notes always fit;
- no string carries a control character other than tab, line feed or carriage return
  (`ContractModel`): Postgres `jsonb` cannot store U+0000, and the others are never meant.

Cross-field problems are all reported at once, each at its own location (see `Problems`), so a
single rejection lists everything the model has to fix.
"""

from __future__ import annotations

import datetime as dt
import json
import re
from collections.abc import Iterator
from functools import cache
from typing import Annotated, Any, Literal, LiteralString, Self, cast
from urllib.parse import urlsplit
from zoneinfo import available_timezones

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    HttpUrl,
    PositiveInt,
    UrlConstraints,
    ValidationError,
    field_validator,
    model_validator,
)
from pydantic_core import InitErrorDetails, PydanticCustomError

# TripTracker's caps (lib/schema.ts, LIMITE). The plan meets them before submit_plan is called.
MAX_TITLE = 120
MAX_NAME = 200
MAX_ADDRESS = 300
MAX_PHONE = 40
MAX_URL = 2000
MAX_NOTES = 4000
MAX_TRIP_DAYS = 120

# Caps of our own (not TripTracker's), so that whatever the plan says still fits TripTracker.
MAX_REASON = 300
"""`book_by_reason`: one line, copied into the booking notes (see mapping.booking_notes)."""
MAX_AMOUNT_CENTS = 10**11
"""1 billion in the currency's main unit. Far below TripTracker's `costCents` cap (2**53 - 1)
even after converting from a currency worth more than the euro (rates per 1 EUR are > 0.1)."""
MAX_DURATION_MIN = 10_080
"""One week in minutes. TripTracker's `durationMin` cap is 2**53 - 1."""

LOCAL_TIME_PATTERN = r"^([01]\d|2[0-3]):[0-5]\d$"
CURRENCY_PATTERN = r"^[A-Z]{3}$"

StopKind = Literal["activity", "meal", "transfer", "rest"]
BookingKind = Literal[
    "restaurant", "wellness", "ticket", "parking", "transport", "lodging", "activity", "other"
]

CONTRACT_CONFIG = ConfigDict(
    # Unknown keys are mistakes (a misspelt field would silently vanish): reject them.
    extra="forbid",
    # Leading/trailing whitespace is never meaningful and must not count against the caps.
    str_strip_whitespace=True,
)

# C0 control characters except tab (\x09), line feed (\x0a) and carriage return (\x0d).
CONTROL_CHARACTER = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


# --- validation errors ----------------------------------------------------------------------

Location = tuple[str | int, ...]


class Problems:
    """Collects cross-field validation problems and raises them as one `ValidationError`.

    Each problem keeps its own location (`("days", 2, "date")`) and a stable error type, so a
    model validator can report every inconsistency at once instead of stopping at the first.
    Pydantic re-roots the locations when the model is nested (`bookings.3.book_by`).
    """

    def __init__(self, title: str) -> None:
        self._title = title
        self._errors: list[InitErrorDetails] = []

    def __bool__(self) -> bool:
        return bool(self._errors)

    def add(self, loc: Location, code: str, message: str, value: Any, **context: Any) -> None:
        """Record a problem. `message` is a template whose `{name}` fields come from `context`."""
        ctx = {key: _context_value(item) for key, item in context.items()}
        self._errors.append(
            InitErrorDetails(
                # Templates are trusted code, never user input: the LiteralString cast is safe.
                type=PydanticCustomError(
                    cast(LiteralString, code), cast(LiteralString, message), ctx or None
                ),
                loc=loc,
                input=value,
            )
        )

    def raise_if_any(self) -> None:
        if self._errors:
            raise ValidationError.from_exception_data(self._title, self._errors)


def _context_value(value: Any) -> Any:
    """Context values stay JSON friendly (ValidationError.json(), the frontend, the logs)."""
    if isinstance(value, dt.date | dt.datetime | dt.time):
        return value.isoformat()
    return value


def format_location(loc: Location) -> str:
    """`("days", 2, "stops", 0, "ref")` -> `days[2].stops[0].ref`; the root is `(plan)`."""
    text = ""
    for part in loc:
        if isinstance(part, int):
            text += f"[{part}]"
        else:
            text += f".{part}" if text else str(part)
    return text or "(plan)"


def _describe_input(value: Any) -> str:
    if isinstance(value, str):
        if len(value) > 60:
            return f"{len(value)} characters: {json.dumps(value[:50] + '…', ensure_ascii=False)}"
        return json.dumps(value, ensure_ascii=False)
    if value is None or isinstance(value, bool | int | float):
        return json.dumps(value)
    if isinstance(value, dt.date | dt.datetime | dt.time):
        return value.isoformat()
    return ""


# How to fix pydantic's built-in errors whose message alone doesn't say it.
_FIX_HINTS: dict[str, str] = {
    "timezone_aware": ("add the UTC offset of the local time, e.g. 2026-11-14T07:05:00+01:00"),
    "extra_forbidden": "remove this key: it is not part of the schema",
}


def describe_validation_errors(error: ValidationError, *, limit: int = 40) -> list[str]:
    """One line per error: `path: message[; hint] (got <value>)`, at most `limit` lines."""
    lines: list[str] = []
    errors = error.errors(include_url=False)
    for item in errors[:limit]:
        line = f"{format_location(item['loc'])}: {item['msg']}"
        if hint := _FIX_HINTS.get(item["type"]):
            line += f"; {hint}"
        shown = "" if item["type"] == "missing" else _describe_input(item.get("input"))
        if shown:
            line += f" (got {shown})"
        lines.append(line)
    if len(errors) > limit:
        lines.append(f"... and {len(errors) - limit} more errors")
    return lines


def plan_rejection_message(error: ValidationError) -> str:
    """The `submit_plan` tool result for a plan that failed validation."""
    count = error.error_count()
    noun = "error" if count == 1 else "errors"
    header = (
        f"Plan rejected: {count} validation {noun}. Fix every one and call submit_plan again "
        "with the complete corrected plan. Paths are JSON paths into your input "
        "(days[2].stops[0].start_time is the first stop of the third day)."
    )
    return "\n".join([header, *(f"- {line}" for line in describe_validation_errors(error))])


# --- control characters ---------------------------------------------------------------------


def _control_character_error(text: str, index: int | None) -> PydanticCustomError | None:
    match = CONTROL_CHARACTER.search(text)
    if match is None:
        return None
    context = {"char": f"U+{ord(match.group()):04X}", "position": match.start()}
    if index is None:
        return PydanticCustomError(
            "control_character",
            "contains the control character {char} at position {position}; remove it (only "
            "tab, line feed and carriage return are allowed)",
            context,
        )
    return PydanticCustomError(
        "control_character",
        "item {index} contains the control character {char} at position {position}; remove "
        "it (only tab, line feed and carriage return are allowed)",
        {**context, "index": index},
    )


def check_no_control_characters(value: Any) -> Any:
    """Reject a string, or a list of strings, that holds a C0 control character other than tab,
    line feed or carriage return (`CONTROL_CHARACTER`). Anything else passes unchanged: nested
    objects are checked by their own model. Postgres `jsonb` and `text` cannot store U+0000,
    so a plan or request carrying one would fail only when it is saved."""
    if isinstance(value, str):
        error = _control_character_error(value, None)
        if error is not None:
            raise error
    elif isinstance(value, list | tuple):
        for index, item in enumerate(cast(list[Any], value)):
            if isinstance(item, str) and (error := _control_character_error(item, index)):
                raise error
    return value


class ContractModel(BaseModel):
    """Base of every contract model (Plan, the subagent results, PlanRequest): unknown keys and
    control characters are rejected, surrounding whitespace is stripped."""

    model_config = CONTRACT_CONFIG

    @field_validator("*", mode="before")
    @classmethod
    def _no_control_characters(cls, value: Any) -> Any:
        return check_no_control_characters(value)


# --- time zones -----------------------------------------------------------------------------


@cache
def _iana_zones() -> dict[str, str]:
    """Known IANA zone names, keyed by their lower-case form (for "did you mean" hints)."""
    zones = available_timezones() - {"Factory", "localtime"}
    return {name.lower(): name for name in zones}


def is_iana_timezone(name: str) -> bool:
    """True for an exact IANA zone name (case-sensitive, as on Linux)."""
    return _iana_zones().get(name.lower()) == name


def check_iana_timezone(value: str) -> str:
    if is_iana_timezone(value):
        return value
    suggestion = _iana_zones().get(value.strip().lower())
    if suggestion:
        raise PydanticCustomError(
            "invalid_timezone",
            "'{timezone}' is not an IANA time zone name; did you mean '{suggestion}'?",
            {"timezone": value, "suggestion": suggestion},
        )
    raise PydanticCustomError(
        "invalid_timezone",
        "'{timezone}' is not an IANA time zone name; use the destination's zone, "
        "e.g. 'Europe/Lisbon' or 'America/New_York'",
        {"timezone": value},
    )


def check_https_url(value: str) -> str:
    """An absolute `https://` URL with a host and no user info (a stop's informational link)."""
    try:
        parts = urlsplit(value)
        valid = (
            parts.scheme == "https"
            and bool(parts.hostname)
            and parts.username is None
            and parts.password is None
        )
    except ValueError:
        valid = False
    if not valid:
        raise PydanticCustomError(
            "https_url_required",
            "url must be an absolute https:// URL of an informational page (official site, "
            "map), e.g. https://www.museu.pt/; null if there is none",
        )
    return value


# --- the contract ---------------------------------------------------------------------------

SourceUrl = Annotated[HttpUrl, UrlConstraints(max_length=MAX_URL)]
"""An http(s) URL of at most `MAX_URL` characters, TripTracker's URL cap."""


class Price(ContractModel):
    """A price with its provenance. Every price says where it was read and when."""

    amount_cents: int = Field(
        ge=0,
        le=MAX_AMOUNT_CENTS,
        description=(
            "Total amount times 100, as an integer, for the whole party: 12.50 EUR is 1250, "
            "3000 JPY is 300000. The backend converts non-EUR amounts to euro."
        ),
    )
    currency: str = Field(
        pattern=CURRENCY_PATTERN,
        description="ISO 4217 currency code in upper case, e.g. EUR, USD, GBP.",
    )
    status: Literal["verified", "estimated"] = Field(
        description=(
            "'verified' only when the price comes from an MCP response (Expedia, Kiwi, "
            "lastminute.com); a price read on a web page or estimated is 'estimated'."
        ),
    )
    source_url: SourceUrl = Field(
        description="Where the price was read: the MCP offer link or the web page URL.",
    )
    retrieved_at: AwareDatetime = Field(
        description=(
            "When the price was read: ISO 8601 with UTC offset, e.g. 2026-10-12T15:04:00+02:00."
        ),
    )


class PlanStop(ContractModel):
    """One stop of a day, in TripTracker's terms: something that happens at a place."""

    ref: str = Field(
        min_length=1,
        description=(
            "Local key of this stop, unique across the whole plan (e.g. 'd1-s2'). "
            "PlanBooking.stop_ref points here. Not shown to the user."
        ),
    )
    title: str = Field(
        min_length=1,
        max_length=MAX_TITLE,
        description="Short title in Italian, e.g. 'Visita al Mosteiro dos Jerónimos'.",
    )
    kind: StopKind = Field(
        description=(
            "activity: something to do or see; meal: breakfast, lunch or dinner; "
            "transfer: moving between places (flight, train, taxi, walk); rest: free time."
        ),
    )
    start_time: str | None = Field(
        default=None,
        pattern=LOCAL_TIME_PATTERN,
        description="Local start time HH:MM (24h, trip time zone), e.g. '09:30'; null if open.",
    )
    duration_min: PositiveInt | None = Field(
        default=None, le=MAX_DURATION_MIN, description="Expected duration in minutes."
    )
    location_name: str | None = Field(
        default=None,
        max_length=MAX_NAME,
        description="Name of the place as the source writes it, e.g. 'Time Out Market'.",
    )
    address: str | None = Field(
        default=None, max_length=MAX_ADDRESS, description="Street address as the source writes it."
    )
    lat: float | None = Field(
        default=None,
        ge=-90,
        le=90,
        description="Latitude in decimal degrees (WGS 84). Coordinates are kept only in pairs.",
    )
    lon: float | None = Field(
        default=None,
        ge=-180,
        le=180,
        description="Longitude in decimal degrees (WGS 84). Coordinates are kept only in pairs.",
    )
    url: str | None = Field(
        default=None,
        max_length=MAX_URL,
        description=(
            "Informational page about the place (official site, map): an absolute https:// "
            "URL. Booking links go in PlanBooking.link instead."
        ),
    )
    notes: str | None = Field(
        default=None, max_length=MAX_NOTES, description="Practical notes for the user, in Italian."
    )

    @field_validator("url")
    @classmethod
    def _https_url(cls, value: str | None) -> str | None:
        return None if value is None else check_https_url(value)


class PlanDay(ContractModel):
    """One calendar day of the trip and its stops."""

    date: dt.date = Field(
        description=(
            "The day, YYYY-MM-DD, between start_date and end_date. At most one entry per date; "
            "dates without stops may be omitted (TripTracker gets an empty day for them)."
        ),
    )
    title: str | None = Field(
        default=None,
        max_length=MAX_TITLE,
        description="Theme of the day in Italian, e.g. 'Arrivo e Alfama'.",
    )
    stops: list[PlanStop] = Field(description="The day's stops, in the order they happen.")


class PlanBooking(ContractModel):
    """Something the user has to book, with two separate dates: when to book it (`book_by`)
    and when it happens (`scheduled_for`)."""

    title: str = Field(
        min_length=1,
        max_length=MAX_TITLE,
        description="What to book, in Italian, e.g. 'Volo Milano Malpensa → Lisbona'.",
    )
    kind: BookingKind = Field(description="Kind of booking (TripTracker's booking kinds).")
    vendor: str | None = Field(
        default=None,
        max_length=MAX_NAME,
        description="Who sells it: airline, hotel, restaurant, operator, e.g. 'TAP Air Portugal'.",
    )
    book_by: AwareDatetime | None = Field(
        default=None,
        description=(
            "Deadline to book ('Prenota entro'): ISO 8601 with UTC offset in the trip's time "
            "zone, e.g. 2026-11-07T18:00:00+01:00. Must be strictly before scheduled_for and "
            "not in the past; never copy scheduled_for here. Null lets the backend derive it "
            "from scheduled_for minus TripTracker's default lead time for this kind."
        ),
    )
    book_by_reason: str | None = Field(
        default=None,
        max_length=MAX_REASON,
        description=(
            "Why this deadline, one line in Italian, e.g. 'Tariffa rimborsabile fino al "
            "7 novembre' or 'I posti finiscono presto nel weekend'."
        ),
    )
    scheduled_for: AwareDatetime | None = Field(
        default=None,
        description=(
            "When the booked thing happens ('Quando'): ISO 8601 with UTC offset in the trip's "
            "time zone, e.g. 2026-11-14T07:05:00+01:00 for a departure."
        ),
    )
    link: str | None = Field(
        default=None,
        max_length=MAX_URL,
        description=(
            "Booking URL exactly as returned by an MCP, or as printed by build_link.py. Never "
            "write or edit a URL by hand."
        ),
    )
    phone: str | None = Field(
        default=None, max_length=MAX_PHONE, description="Phone number to book, with country code."
    )
    price: Price | None = Field(default=None, description="Price of this booking, if known.")
    stop_ref: str | None = Field(
        default=None,
        description=(
            "ref of the stop this booking belongs to (e.g. the dinner stop of a restaurant "
            "booking). Must match a stop ref in days; null if none."
        ),
    )
    notes: str | None = Field(
        default=None,
        max_length=MAX_NOTES,
        description="Practical notes in Italian: fare conditions, what is included.",
    )

    @model_validator(mode="after")
    def _book_before_it_happens(self) -> Self:
        if (
            self.book_by is not None
            and self.scheduled_for is not None
            and self.book_by >= self.scheduled_for
        ):
            problems = Problems(type(self).__name__)
            problems.add(
                ("book_by",),
                "book_by_not_before_scheduled_for",
                "book_by ({book_by}) must be strictly before scheduled_for ({scheduled_for}). "
                "book_by is the deadline to book ('Prenota entro'), scheduled_for is when it "
                "happens ('Quando'): set an earlier deadline, or null to let the backend derive "
                "it",
                self.book_by,
                book_by=self.book_by,
                scheduled_for=self.scheduled_for,
            )
            problems.raise_if_any()
        return self


class Plan(ContractModel):
    """The final trip plan, the input of submit_plan. Call submit_plan once, when research is
    complete. Text the user reads (titles, notes, summary, warnings) is in Italian; proper
    names and addresses stay as the source writes them. Instants always carry a UTC offset,
    dates are YYYY-MM-DD and local times HH:MM."""

    title: str = Field(
        min_length=1,
        max_length=MAX_TITLE,
        description="Trip title in Italian, e.g. 'Lisbona, weekend lungo di novembre'.",
    )
    destination: str = Field(
        min_length=1,
        max_length=MAX_NAME,
        description="Main destination as the user reads it, e.g. 'Lisbona, Portogallo'.",
    )
    timezone: str = Field(
        description="IANA time zone of the destination, e.g. 'Europe/Lisbon'.",
    )
    start_date: dt.date = Field(description="First day of the trip, YYYY-MM-DD.")
    end_date: dt.date = Field(
        description=(
            f"Last day of the trip, YYYY-MM-DD, on or after start_date; the trip spans at most "
            f"{MAX_TRIP_DAYS} days."
        ),
    )
    travelers: PositiveInt = Field(description="Number of people travelling, children included.")
    lodging_name: str | None = Field(
        default=None,
        max_length=MAX_NAME,
        description="Name of the main lodging (the trip's base in TripTracker).",
    )
    lodging_address: str | None = Field(
        default=None, max_length=MAX_ADDRESS, description="Street address of the main lodging."
    )
    days: list[PlanDay] = Field(
        max_length=MAX_TRIP_DAYS,
        description="The itinerary, one entry per date with stops.",
    )
    bookings: list[PlanBooking] = Field(
        description="Everything the user has to book for the chosen plan.",
    )
    alternatives: list[PlanBooking] = Field(
        default_factory=list,
        description=(
            "Valid options that were not chosen (another flight, another hotel), shown in the "
            "planner only; they do not go to TripTracker."
        ),
    )
    warnings: list[str] = Field(
        default_factory=list,
        description=(
            "One line each, in Italian: sources that failed, prices that are only estimated, "
            "a total over budget, risks the user should know about."
        ),
    )
    summary: str = Field(
        min_length=1,
        max_length=MAX_NOTES,
        description="Three-line summary of the plan in Italian, with the estimated total cost.",
    )

    @field_validator("timezone")
    @classmethod
    def _iana_timezone(cls, value: str) -> str:
        return check_iana_timezone(value)

    @model_validator(mode="after")
    def _check_consistency(self) -> Self:
        problems = Problems(type(self).__name__)
        range_ok = self._check_date_range(problems)
        self._check_days(problems, range_ok=range_ok)
        refs = self._check_stop_refs(problems)
        self._check_booking_refs(problems, refs)
        problems.raise_if_any()
        return self

    def _check_date_range(self, problems: Problems) -> bool:
        if self.end_date < self.start_date:
            problems.add(
                ("end_date",),
                "end_before_start",
                "end_date {end_date} is before start_date {start_date}; the trip ends on or "
                "after the day it starts",
                self.end_date,
                start_date=self.start_date,
                end_date=self.end_date,
            )
            return False
        length = (self.end_date - self.start_date).days + 1
        if length > MAX_TRIP_DAYS:
            problems.add(
                ("end_date",),
                "trip_too_long",
                "the trip spans {days} days ({start_date} to {end_date}); TripTracker accepts "
                "at most {max_days}",
                self.end_date,
                days=length,
                start_date=self.start_date,
                end_date=self.end_date,
                max_days=MAX_TRIP_DAYS,
            )
            return False
        return True

    def _check_days(self, problems: Problems, *, range_ok: bool) -> None:
        first_index: dict[dt.date, int] = {}
        for index, day in enumerate(self.days):
            loc = ("days", index, "date")
            if range_ok and not self.start_date <= day.date <= self.end_date:
                problems.add(
                    loc,
                    "day_out_of_range",
                    "day {date} is outside the trip ({start_date} to {end_date}); move its "
                    "stops to a date in range or change start_date/end_date",
                    day.date,
                    date=day.date,
                    start_date=self.start_date,
                    end_date=self.end_date,
                )
            if day.date in first_index:
                problems.add(
                    loc,
                    "duplicate_day",
                    "date {date} already appears at days[{first}]; merge both entries into one day",
                    day.date,
                    date=day.date,
                    first=first_index[day.date],
                )
            else:
                first_index[day.date] = index

    def _check_stop_refs(self, problems: Problems) -> set[str]:
        first_path: dict[str, str] = {}
        for day_index, stop_index, stop in self.iter_stops():
            path = f"days[{day_index}].stops[{stop_index}]"
            if stop.ref in first_path:
                problems.add(
                    ("days", day_index, "stops", stop_index, "ref"),
                    "duplicate_stop_ref",
                    "ref '{ref}' is already used by {first}; every stop needs its own ref",
                    stop.ref,
                    ref=stop.ref,
                    first=first_path[stop.ref],
                )
            else:
                first_path[stop.ref] = path
        return set(first_path)

    def _check_booking_refs(self, problems: Problems, refs: set[str]) -> None:
        known = ", ".join(sorted(refs)[:30]) or "none"
        for field in ("bookings", "alternatives"):
            bookings: list[PlanBooking] = getattr(self, field)
            for index, booking in enumerate(bookings):
                if booking.stop_ref is not None and booking.stop_ref not in refs:
                    problems.add(
                        (field, index, "stop_ref"),
                        "unknown_stop_ref",
                        "stop_ref '{stop_ref}' matches no stop ref in days (known refs: "
                        "{known}); use the ref of an existing stop, or null",
                        booking.stop_ref,
                        stop_ref=booking.stop_ref,
                        known=known,
                    )

    def iter_stops(self) -> Iterator[tuple[int, int, PlanStop]]:
        """Every stop with its day index and position in the day, in plan order."""
        for day_index, day in enumerate(self.days):
            for stop_index, stop in enumerate(day.stops):
                yield day_index, stop_index, stop

    def trip_dates(self) -> list[dt.date]:
        """Every date from start_date to end_date (TripTracker has one Day for each)."""
        length = (self.end_date - self.start_date).days + 1
        return [self.start_date + dt.timedelta(days=offset) for offset in range(length)]
