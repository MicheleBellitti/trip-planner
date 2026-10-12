"""`plan_to_trip()`: translate an accepted `Plan` into a TripTracker `Trip` (pure function).

Spec: "Contratto del piano" (the mapping table, "Gli ID ... UUID v4; coverSeed e' casuale",
"Conversione delle valute") and CLAUDE.md contract rules 1-4. TripTracker's real shapes and
every gap of the table: docs/triptracker/schema-notes.md §3, §4 and §8 (A1-A15). The field names
below are TripTracker's (`lib/schema.ts` at 71be320), camelCase, exactly as `/import` expects.

Rules, field by field (Plan -> Trip):

- Trip: `id` = `ids.new_id()`; `title`, `destinationName` (= destination), `timezone`,
  `startDate`/`endDate` (`YYYY-MM-DD`), `baseName` (= lodging_name), `baseAddress`
  (= lodging_address) copied; `coverSeed` = `ids.cover_seed()` in [0, 9999]. Never set:
  `notes` (summary stays in the planner), `baseLat`/`baseLon`, `icsSequence`.
- Days: one Day per date of `plan.trip_dates()`, in date order, even dates without stops
  (`stops: []`); `dayIndex` = position; `tripId` = trip id; `title` from the PlanDay of that
  date when present. Never `notes`.
- Stops (per day, in the given order): `id` = `ids.new_id()`, `dayId`, `title`, `kind`,
  `startTime` (= start_time), `durationMin` (= duration_min), `locationName` (= location_name),
  `address`, `url`, `notes` copied; `lat`/`lon` only when both are present; `sortOrder` =
  1000, 2000, 3000... restarting at every day; `state: "planned"`. `url` is copied as is:
  `Plan` already guarantees an absolute `https://` URL with a host and no user info
  (`plan.check_https_url`), which closes `javascript:` and similar schemes. Stop URLs are
  informational (official site, map) and not domain-checked: no allowlist of official sites
  exists, and they never lead to a payment (residual risk accepted, decision 13).
- Bookings (plan.bookings only; alternatives, warnings and summary stay in the planner):
  `id`, `tripId`, `title`, `kind`, `vendor`, `phone` copied; `status: "to_book"`; `sortOrder` =
  1000, 2000... in plan order; `stopId` = the Stop id of `stop_ref` (Plan validation already
  guarantees it exists); `url` = `link` only when `links.check_link(link).allowed`, otherwise
  the link goes to `notes` as text (spec "Sicurezza e privacy").
- `scheduledFor` = `scheduled_for`; `dueAt` = `book_by`. Both are rendered in the trip time zone
  with `format_instant()`. `dueAt` and `scheduledFor` are never derived from each other
  except by the documented fallback (`fallback_due_at`). A `book_by` in the past never gets
  here: `consumer.translate_submission` rejects it back to the agent first. Never set:
  `leadDays`, `confirmationRef`.
- `costCents`: EUR prices copied; other currencies converted with the pre-fetched `fx` quote
  for (`currency`, `fx.price_fx_date(price)`); when no quote exists `costCents` is omitted, the
  original amount goes to the notes and a warning is returned. No clamp is needed:
  `Price.amount_cents <= plan.MAX_AMOUNT_CENTS` (10**11) and no currency is worth 10 euro, so a
  converted amount stays below 10**12, far under TripTracker's cap (2**53 - 1).
- Booking notes = the plan's `notes` followed by one provenance line each (Italian copy below):
  price status, price source URL, `book_by_reason`, the conversion details (original amount and
  currency, rate, source and its date) or the missing conversion, an unchecked link, the
  "book now" hint. Hard budget of `MAX_NOTES` (4000) code points, always met (schema-notes
  A10): (1) everything in full if it fits; (2) else the plan's free-text notes are shortened
  (with "…", dropped entirely if no room is left); (3) if the provenance lines alone are still
  too long (two URLs of up to 2000 characters each), the URL inside `NOTE_UNCHECKED_LINK`,
  then the one inside `NOTE_PRICE_SOURCE`, is cut to its first `NOTE_URL_KEEP` characters
  plus "…", and the room a cut frees goes back to the plan's notes as in (2). The notes are
  plain text in TripTracker, so a cut URL is only a hint; the full one stays in the planner's
  stored plan. Every other line is bounded by the contract (`book_by_reason` <=
  `plan.MAX_REASON`), so (3) always lands under the cap (tests/test_mapping_budget.py checks
  the arithmetic); a final hard cut keeps the cap even if a contract cap is raised carelessly.
- Optional fields are omitted, never null (A14): the result has no `None` anywhere. Empty
  optional strings are omitted too (they carry nothing).

The result must pass `triptracker_schema.validate_trip`; the consumer checks it. The same stored
Trip is served by every GET /plans/{id}/trip, so its ids never change after acceptance (A1).
"""

from __future__ import annotations

import datetime as dt
import random
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from types import MappingProxyType
from typing import Any, Literal, NotRequired, Protocol, TypedDict, cast
from zoneinfo import ZoneInfo

from app.fx import EUR, FxQuote, FxRates, price_fx_date
from app.links import LinkVerdict, check_link
from app.plan import BookingKind, Plan, PlanBooking, PlanDay, PlanStop, StopKind

SORT_ORDER_STEP = 1000
"""TripTracker's `SORT_ORDER_STEP` (lib/stops.ts); also used for bookings, like `addBooking`."""

COVER_SEED_RANGE = 10_000
"""TripTracker draws `coverSeed` with `Math.floor(Math.random() * 10000)`."""

MAX_NOTES = 4000
"""TripTracker's `LIMITE.note`, in code points (zod 4.5.4 and Python agree)."""

DEFAULT_LEAD_DAYS: Mapping[BookingKind, int] = MappingProxyType(
    {
        "restaurant": 2,
        "wellness": 3,
        "ticket": 3,
        "parking": 1,
        "transport": 1,
        "lodging": 7,
        "activity": 2,
        "other": 2,
    }
)
"""Copy of TripTracker's module-private `DEFAULT_LEAD_DAYS` (lib/bookings.ts at 71be320). It
is not exported in trip.json, so a change there goes unnoticed here (schema-notes A8)."""

# --- Italian copy of the provenance lines (user-facing; tests import these) ---------------------

NOTE_PRICE_VERIFIED = "Prezzo verificato"
NOTE_PRICE_ESTIMATED = "Prezzo stimato"
NOTE_PRICE_SOURCE = "Fonte del prezzo: {url}"
NOTE_BOOK_BY_REASON = "Perché entro questa data: {reason}"
NOTE_FX_CONVERTED = (
    "Prezzo originale: {amount} {currency}, cambio {rate} {currency} per 1 EUR ({source}, {date})"
)
NOTE_FX_MISSING = "Prezzo: {amount} {currency}, non convertito in euro (cambio non disponibile)"
NOTE_UNCHECKED_LINK = "Link da verificare prima di usarlo: {url}"
NOTE_BOOK_NOW = "Da prenotare subito: la data è troppo vicina per una scadenza"
NOTE_ELLIPSIS = "…"
NOTE_URL_KEEP = 200
"""How many characters of a URL survive in the notes when the budget forces a cut (step 3 of
the module's notes rule)."""
FX_SOURCE_LABELS: Mapping[str, str] = MappingProxyType(
    {"bdi_daily": "Banca d'Italia", "inforeuro_monthly": "InforEuro"}
)
WARNING_FX_MISSING = (
    "Cambio non disponibile per {currency}: il prezzo di «{title}» è rimasto in {currency}"
)
WARNING_BOOK_NOW = "«{title}» è troppo vicina per una scadenza: va prenotata subito"

# --- TripTracker shapes (functional syntax: the keys are TripTracker's camelCase names) -------

TripTrackerStop = TypedDict(  # noqa: UP013
    "TripTrackerStop",
    {
        "id": str,
        "dayId": str,
        "title": str,
        "kind": StopKind,
        "startTime": NotRequired[str],
        "durationMin": NotRequired[int],
        "locationName": NotRequired[str],
        "address": NotRequired[str],
        "lat": NotRequired[float],
        "lon": NotRequired[float],
        "url": NotRequired[str],
        "notes": NotRequired[str],
        "sortOrder": float,
        "state": Literal["planned", "done", "skipped"],
    },
)

TripTrackerDay = TypedDict(  # noqa: UP013
    "TripTrackerDay",
    {
        "id": str,
        "tripId": str,
        "date": str,
        "dayIndex": int,
        "title": NotRequired[str],
        "notes": NotRequired[str],
        "stops": list[TripTrackerStop],
    },
)

TripTrackerBooking = TypedDict(  # noqa: UP013
    "TripTrackerBooking",
    {
        "id": str,
        "tripId": str,
        "stopId": NotRequired[str],
        "title": str,
        "vendor": NotRequired[str],
        "kind": BookingKind,
        "status": Literal["to_book", "booked", "confirmed", "cancelled"],
        "dueAt": NotRequired[str],
        "scheduledFor": NotRequired[str],
        "leadDays": NotRequired[int],
        "confirmationRef": NotRequired[str],
        "phone": NotRequired[str],
        "url": NotRequired[str],
        "costCents": NotRequired[int],
        "notes": NotRequired[str],
        "sortOrder": float,
    },
)

TripTrackerTrip = TypedDict(  # noqa: UP013
    "TripTrackerTrip",
    {
        "id": str,
        "title": str,
        "destinationName": str,
        "timezone": str,
        "startDate": str,
        "endDate": str,
        "baseName": NotRequired[str],
        "baseAddress": NotRequired[str],
        "baseLat": NotRequired[float],
        "baseLon": NotRequired[float],
        "notes": NotRequired[str],
        "coverSeed": int,
        "icsSequence": NotRequired[int],
        "days": list[TripTrackerDay],
        "bookings": list[TripTrackerBooking],
    },
)


# --- ids --------------------------------------------------------------------------------------


class TripIds(Protocol):
    """Where the Trip's ids and cover seed come from (injected so tests are deterministic)."""

    def new_id(self) -> str:
        """A fresh id: a UUID v4 string (`str(uuid.uuid4())`, no prefix, per the spec)."""
        ...

    def cover_seed(self) -> int:
        """An int in [0, COVER_SEED_RANGE)."""
        ...


class RandomTripIds:
    """Production ids: `uuid.uuid4()` and `random.randrange(COVER_SEED_RANGE)`."""

    def new_id(self) -> str:
        return str(uuid.uuid4())

    def cover_seed(self) -> int:
        return random.randrange(COVER_SEED_RANGE)


class SeededTripIds:
    """Deterministic ids for tests and replays: valid UUID v4 strings from `random.Random(seed)`
    (`uuid.UUID(int=rng.getrandbits(128), version=4)`), the same sequence for the same seed."""

    def __init__(self, seed: int) -> None:
        self._rng = random.Random(seed)

    def new_id(self) -> str:
        return str(uuid.UUID(int=self._rng.getrandbits(128), version=4))

    def cover_seed(self) -> int:
        return self._rng.randrange(COVER_SEED_RANGE)


# --- result -----------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TripMapping:
    """What `plan_to_trip` returns."""

    trip: TripTrackerTrip
    """JSON-ready (only str/int/float/list/dict), no None values: stored as `plans.trip`."""
    warnings: list[str] = field(default_factory=list[str])
    """New Italian warning lines (missing FX, "book now") to append to the stored plan's
    `warnings`, without duplicates. Empty in the common case."""
    stop_ids: Mapping[str, str] = field(default_factory=dict[str, str])
    """PlanStop.ref -> Stop.id, for tests and logs."""


# --- the mapping ------------------------------------------------------------------------------


def plan_to_trip(plan: Plan, *, now: dt.datetime, fx: FxRates, ids: TripIds) -> TripMapping:
    """Translate `plan` (already validated) into a TripTracker Trip by the module's rules.

    `now` (timezone-aware) anchors the "never before tomorrow" fallback; `fx` holds the
    pre-fetched quotes (`FxConverter.prefetch(fx_keys(plan))`); `ids` supplies every id and the
    cover seed. Pure: no I/O, no clock, no randomness of its own. Raises ValueError only for a
    naive `now` (a programming error); every plan that passed `Plan` validation maps.
    """
    _require_aware(now, "now")
    tz = ZoneInfo(plan.timezone)
    trip_id = ids.new_id()
    cover_seed = ids.cover_seed()
    stop_ids: dict[str, str] = {}
    days = [
        _map_day(plan_day, date, index, trip_id=trip_id, ids=ids, stop_ids=stop_ids)
        for index, (date, plan_day) in enumerate(_days_by_date(plan))
    ]
    warnings: list[str] = []
    bookings = [
        _map_booking(
            booking,
            position=position,
            trip_id=trip_id,
            tz=tz,
            now=now,
            fx=fx,
            ids=ids,
            stop_ids=stop_ids,
            warnings=warnings,
        )
        for position, booking in enumerate(plan.bookings, start=1)
    ]
    trip: dict[str, Any] = {
        "id": trip_id,
        "title": plan.title,
        "destinationName": plan.destination,
        "timezone": plan.timezone,
        "startDate": plan.start_date.isoformat(),
        "endDate": plan.end_date.isoformat(),
    }
    _put(trip, "baseName", plan.lodging_name)
    _put(trip, "baseAddress", plan.lodging_address)
    trip["coverSeed"] = cover_seed
    trip["days"] = days
    trip["bookings"] = bookings
    return TripMapping(trip=cast(TripTrackerTrip, trip), warnings=warnings, stop_ids=stop_ids)


def fallback_due_at(
    scheduled_for: dt.datetime, kind: BookingKind, *, tz: ZoneInfo, now: dt.datetime
) -> dt.datetime | None:
    """`dueAt` for a booking without `book_by` (CLAUDE.md rule 1, schema-notes A8-A9).

    1. candidate = `scheduled_for` in `tz` minus `DEFAULT_LEAD_DAYS[kind]` calendar days, at the
       same wall-clock time (re-localized, so the offset follows the date across DST).
    2. floor = `now` in `tz` plus one calendar day, truncated to the minute ("mai prima di
       domani", with "tomorrow" in the trip's zone, not the server's).
    3. due = max(candidate, floor). If due is not strictly before `scheduled_for` the booking is
       too close for a deadline: return None (the caller adds `NOTE_BOOK_NOW` and
       `WARNING_BOOK_NOW`), because `dueAt >= scheduledFor` would break rule 1.

    A wall-clock time that does not exist on the target date (the spring-forward gap) moves
    forward by the gap; an ambiguous one (the autumn fold) takes its first, earlier occurrence.
    The result is expressed in `tz`.
    """
    _require_aware(scheduled_for, "scheduled_for")
    _require_aware(now, "now")
    lead = dt.timedelta(days=DEFAULT_LEAD_DAYS[kind])
    candidate = _localize(_wall_clock(scheduled_for, tz) - lead, tz)
    floor = _localize(_wall_clock(now, tz).replace(second=0, microsecond=0) + _ONE_DAY, tz)
    due = max(candidate, floor)
    if due >= scheduled_for:
        return None
    return due


def format_instant(value: dt.datetime, tz: ZoneInfo) -> str:
    """ISO 8601 with offset in `tz`, seconds precision: `2026-11-14T15:00:00+00:00`. Matches
    TripTracker's `instant` regex (an offset is mandatory; `+00:00` and `Z` both pass)."""
    _require_aware(value, "value")
    return value.astimezone(tz).isoformat(timespec="seconds")


def format_amount(amount_cents: int) -> str:
    """Cents as an Italian decimal for the notes: 12345 -> "123,45"."""
    sign = "-" if amount_cents < 0 else ""
    units, cents = divmod(abs(amount_cents), 100)
    return f"{sign}{units},{cents:02d}"


def booking_notes(
    booking: PlanBooking,
    *,
    quote: FxQuote | None,
    link: LinkVerdict | None,
    book_now: bool,
) -> str | None:
    """The booking's TripTracker `notes`: the plan's notes, then the provenance lines (module
    docstring), joined with newlines, always at most `MAX_NOTES` code points: the plan's notes
    are shortened first, then the URLs inside `NOTE_UNCHECKED_LINK` and `NOTE_PRICE_SOURCE` are
    cut to `NOTE_URL_KEEP` characters plus `NOTE_ELLIPSIS`. `quote` is the conversion used (None
    for EUR or when missing; a non-EUR price with `quote=None` gets `NOTE_FX_MISSING`); `link`
    is the verdict on `booking.link` (None when there is no link). None when there is nothing
    to write."""
    source = str(booking.price.source_url) if booking.price is not None else None
    unchecked = booking.link if link is not None and not link.allowed and booking.link else None
    free = booking.notes or ""
    attempts = (
        (source, unchecked),
        (source, _cut_url(unchecked)),
        (_cut_url(source), _cut_url(unchecked)),
    )
    lines: list[str] = []
    for source_text, link_text in attempts:
        lines = _provenance_lines(
            booking, quote=quote, source=source_text, unchecked=link_text, book_now=book_now
        )
        text = _fit_notes(free, lines)
        if text is not None:
            return text or None
    # Unreachable while the contract bounds every other line (tests/test_mapping_budget.py);
    # kept so that the cap holds even if a cap is raised without updating the budget.
    tail = "\n".join(lines)
    return tail[: MAX_NOTES - len(NOTE_ELLIPSIS)] + NOTE_ELLIPSIS


# --- helpers ----------------------------------------------------------------------------------

_ONE_DAY = dt.timedelta(days=1)
_RATE_DECIMALS = 6
"""Decimals of a rate shown in the notes; the conversion itself uses the exact rate."""


def _require_aware(value: dt.datetime, name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        msg = f"{name} must be a timezone-aware datetime, got {value.isoformat()}"
        raise ValueError(msg)


def _wall_clock(value: dt.datetime, tz: ZoneInfo) -> dt.datetime:
    """The local date and time of `value` in `tz`, without the zone (for calendar arithmetic)."""
    return value.astimezone(tz).replace(tzinfo=None)


def _localize(wall: dt.datetime, tz: ZoneInfo) -> dt.datetime:
    """Attach `tz` to a wall-clock time and normalize it through UTC, so a time inside a DST
    gap becomes a real instant and the offset is the one in force at that instant."""
    return wall.replace(tzinfo=tz).astimezone(dt.UTC).astimezone(tz)


def _put(target: dict[str, Any], key: str, value: object) -> None:
    """Set an optional TripTracker key only when there is a value: TripTracker rejects `null`
    (schema-notes A14), and an empty string carries nothing."""
    if value is None or value == "":
        return
    target[key] = value


def _days_by_date(plan: Plan) -> list[tuple[dt.date, PlanDay | None]]:
    """Every date of the trip with its PlanDay, if the plan has one (one Day per date, A2)."""
    by_date = {day.date: day for day in plan.days}
    return [(date, by_date.get(date)) for date in plan.trip_dates()]


def _map_day(
    plan_day: PlanDay | None,
    date: dt.date,
    index: int,
    *,
    trip_id: str,
    ids: TripIds,
    stop_ids: dict[str, str],
) -> TripTrackerDay:
    day_id = ids.new_id()
    day: dict[str, Any] = {
        "id": day_id,
        "tripId": trip_id,
        "date": date.isoformat(),
        "dayIndex": index,
    }
    stops: list[TripTrackerStop] = []
    if plan_day is not None:
        _put(day, "title", plan_day.title)
        for position, stop in enumerate(plan_day.stops, start=1):
            mapped = _map_stop(stop, position=position, day_id=day_id, ids=ids)
            stop_ids[stop.ref] = mapped["id"]
            stops.append(mapped)
    day["stops"] = stops
    return cast(TripTrackerDay, day)


def _map_stop(stop: PlanStop, *, position: int, day_id: str, ids: TripIds) -> TripTrackerStop:
    mapped: dict[str, Any] = {
        "id": ids.new_id(),
        "dayId": day_id,
        "title": stop.title,
        "kind": stop.kind,
    }
    _put(mapped, "startTime", stop.start_time)
    _put(mapped, "durationMin", stop.duration_min)
    _put(mapped, "locationName", stop.location_name)
    _put(mapped, "address", stop.address)
    if stop.lat is not None and stop.lon is not None:
        mapped["lat"] = stop.lat
        mapped["lon"] = stop.lon
    _put(mapped, "url", stop.url)
    _put(mapped, "notes", stop.notes)
    mapped["sortOrder"] = position * SORT_ORDER_STEP
    mapped["state"] = "planned"
    return cast(TripTrackerStop, mapped)


def _map_booking(
    booking: PlanBooking,
    *,
    position: int,
    trip_id: str,
    tz: ZoneInfo,
    now: dt.datetime,
    fx: FxRates,
    ids: TripIds,
    stop_ids: Mapping[str, str],
    warnings: list[str],
) -> TripTrackerBooking:
    mapped: dict[str, Any] = {"id": ids.new_id(), "tripId": trip_id}
    if booking.stop_ref is not None:
        mapped["stopId"] = stop_ids[booking.stop_ref]
    mapped["title"] = booking.title
    _put(mapped, "vendor", booking.vendor)
    mapped["kind"] = booking.kind
    mapped["status"] = "to_book"

    book_now = False
    if booking.book_by is not None:
        mapped["dueAt"] = format_instant(booking.book_by, tz)
    elif booking.scheduled_for is not None:
        due = fallback_due_at(booking.scheduled_for, booking.kind, tz=tz, now=now)
        if due is None:
            book_now = True
            _warn(warnings, WARNING_BOOK_NOW.format(title=booking.title))
        else:
            mapped["dueAt"] = format_instant(due, tz)
    if booking.scheduled_for is not None:
        mapped["scheduledFor"] = format_instant(booking.scheduled_for, tz)

    _put(mapped, "phone", booking.phone)
    verdict = check_link(booking.link) if booking.link else None
    if verdict is not None and verdict.allowed:
        mapped["url"] = booking.link

    quote: FxQuote | None = None
    price = booking.price
    if price is not None:
        if price.currency == EUR:
            mapped["costCents"] = price.amount_cents
        else:
            quote = fx.get(price.currency, price_fx_date(price))
            if quote is None:
                _warn(
                    warnings,
                    WARNING_FX_MISSING.format(currency=price.currency, title=booking.title),
                )
            else:
                mapped["costCents"] = quote.to_eur_cents(price.amount_cents)

    _put(mapped, "notes", booking_notes(booking, quote=quote, link=verdict, book_now=book_now))
    mapped["sortOrder"] = position * SORT_ORDER_STEP
    return cast(TripTrackerBooking, mapped)


def _warn(warnings: list[str], line: str) -> None:
    if line not in warnings:
        warnings.append(line)


def _format_rate(rate: Decimal) -> str:
    """A rate for the notes, Italian decimal comma, at most `_RATE_DECIMALS` decimals and no
    exponent: Decimal("1.1206") -> "1,1206", Decimal("162.5") -> "162,5"."""
    if not rate.is_finite():
        return str(rate)
    exponent = rate.as_tuple().exponent
    shown = rate
    if isinstance(exponent, int) and -exponent > _RATE_DECIMALS:
        try:
            shown = rate.quantize(Decimal(1).scaleb(-_RATE_DECIMALS), rounding=ROUND_HALF_UP)
        except InvalidOperation:
            shown = rate
    return format(shown.normalize(), "f").replace(".", ",")


def _format_date(value: dt.date) -> str:
    return value.strftime("%d/%m/%Y")


def _provenance_lines(
    booking: PlanBooking,
    *,
    quote: FxQuote | None,
    source: str | None,
    unchecked: str | None,
    book_now: bool,
) -> list[str]:
    """The provenance lines in their fixed order, with `source` and `unchecked` (the price
    source URL and the link that failed the allowlist) as given, possibly already cut."""
    lines: list[str] = []
    price = booking.price
    if price is not None:
        lines.append(NOTE_PRICE_VERIFIED if price.status == "verified" else NOTE_PRICE_ESTIMATED)
        lines.append(NOTE_PRICE_SOURCE.format(url=source))
    if booking.book_by_reason:
        lines.append(NOTE_BOOK_BY_REASON.format(reason=booking.book_by_reason))
    if price is not None and price.currency != EUR:
        amount = format_amount(price.amount_cents)
        if quote is not None:
            lines.append(
                NOTE_FX_CONVERTED.format(
                    amount=amount,
                    currency=price.currency,
                    rate=_format_rate(quote.rate),
                    source=FX_SOURCE_LABELS.get(quote.source, quote.source),
                    date=_format_date(quote.rate_date),
                )
            )
        else:
            lines.append(NOTE_FX_MISSING.format(amount=amount, currency=price.currency))
    if unchecked is not None:
        lines.append(NOTE_UNCHECKED_LINK.format(url=unchecked))
    if book_now:
        lines.append(NOTE_BOOK_NOW)
    return lines


def _cut_url(url: str | None) -> str | None:
    """The first `NOTE_URL_KEEP` characters of a long URL plus `NOTE_ELLIPSIS`."""
    if url is None or len(url) <= NOTE_URL_KEEP:
        return url
    return url[:NOTE_URL_KEEP] + NOTE_ELLIPSIS


def _fit_notes(free: str, lines: list[str]) -> str | None:
    """`free` then `lines`, newline-joined, within `MAX_NOTES`: `free` is shortened (or
    dropped) to make room. None when the provenance lines alone are too long."""
    tail = "\n".join(lines)
    if len(tail) > MAX_NOTES:
        return None
    if not free:
        return tail
    if not lines:
        return free if len(free) <= MAX_NOTES else _shorten(free, MAX_NOTES)
    room = MAX_NOTES - len(tail) - 1
    if len(free) <= room:
        return f"{free}\n{tail}"
    shortened = _shorten(free, room)
    return f"{shortened}\n{tail}" if shortened else tail


def _shorten(text: str, room: int) -> str:
    """`text` cut to fit `room` code points with `NOTE_ELLIPSIS`; empty when nothing fits."""
    keep = room - len(NOTE_ELLIPSIS)
    if keep < 1:
        return ""
    cut = text[:keep].rstrip()
    return cut + NOTE_ELLIPSIS if cut else ""
