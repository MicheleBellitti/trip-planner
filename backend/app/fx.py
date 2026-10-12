"""Currency conversion to euro cents for TripTracker's `costCents`.

Spec: "Contratto del piano" -> "Conversione delle valute" and decision 1 of "Decisioni aperte":
`to_eur_cents(amount_cents, currency, on_date)`; primary source the Banca d'Italia daily
reference rate, fallback the European Commission's monthly InforEuro accounting rate; rates are
units of currency per 1 EUR, so `eur_cents = round(amount_cents / rate)`; cached in `fx_rates`
(`date`, `currency`, `rate`, `source`), one rate per currency per day per source (the source is
part of the primary key: a Banca d'Italia daily rate and the InforEuro monthly rate dated the
first of the month may share a date, and neither hides the other); if both sources fail the
amount is not converted, the original stays in the booking notes and the plan gets a warning.
Endpoints, payloads, edge cases and test vectors: docs/research/integrations.md §2 (fixtures in
backend/tests/fixtures/fx/).

Algorithm of `FxConverter.quote(currency, on_date)` (integrations.md §2.3); `on_date` is first
clamped to today, since no source publishes future rates:

1. `EUR` -> rate 1, no I/O.
2. Daily cache: the newest `source = 'bdi_daily'` row for `currency` with `on_date -
   LOOKBACK_DAYS <= date <= on_date`. Only daily rows: a cached monthly InforEuro rate must
   never count as a daily hit, or Banca d'Italia would not be asked again for that week. The
   row is a hit when no publication day (`is_publication_day`: Monday to Friday except the
   TARGET holidays) falls after its date, up to `on_date`: Friday's rate answers for Saturday
   and Sunday, but a row cached on Monday morning never answers for Tuesday. An older row is
   kept as the fallback of step 3.
3. Banca d'Italia `dailyTimeSeries` over `[on_date - LOOKBACK_DAYS, on_date]` (covers weekends,
   TARGET holidays and "today before publication"): the last row with a numeric `avgRate` and
   `exchangeConventionCode == "C"` (invert on "I"), cached under its own `referenceDate`. When
   the call fails or has no usable row, the older daily row of step 2 is used if there is one
   (still a Banca d'Italia rate, and newer than any monthly one).
4. InforEuro, only when step 3 found nothing, for `on_date`'s month: the cached `source =
   'inforeuro_monthly'` row dated the first of that month, else `monthly-rates` for it; on
   `code 5` ("No rates published") the same two steps for the previous month. Cached as
   `inforeuro_monthly`, dated the first of the month it applies to.
5. Otherwise `FxUnavailable`.

Offline (`offline=True`): no request at all. The newest cached daily row of the window is used
whatever its age, then the cached InforEuro row of `on_date`'s month, then of the month before.

Rules: `Decimal` throughout (`json.loads(..., parse_float=Decimal)` for InforEuro, `Decimal(str)`
for Banca d'Italia's string rates); rounding is `ROUND_HALF_UP` to whole cents, computed exactly
(`convert_cents`); upper-case ISO codes in requests (`usd` is a 400 at Banca d'Italia);
`Accept: application/json` is mandatory at Banca d'Italia. Cache writes use `INSERT ... ON
CONFLICT (date, currency, source) DO NOTHING`. The cache is best-effort: a database error is
logged and the rate is fetched (or returned) anyway.

Timeouts and retries: every request is bounded by `HTTP_TIMEOUT_SECONDS`, and each source as a
whole (attempts and pauses) by `SOURCE_DEADLINE_SECONDS`. Network errors, timeouts, 408, 429
and 5xx are retried at most `SOURCE_RETRIES` times per source with a short backoff
(`RETRY_BACKOFF_SECONDS`); other 4xx answers and malformed bodies are not retried, and neither
is InforEuro's `code 5`. No personal data is ever sent: only a currency code and dates.

Logs: structlog events named `fx_*` carrying the currency, dates, source, HTTP status or
exception class and attempt number; never a response body. The consumer's bound context adds
`plan_id` and `session_id`.

Which date: `price_fx_date(price)` = the price's `retrieved_at` date in Europe/Rome (travel dates
are in the future and have no published rate yet).

`mapping.plan_to_trip` is a pure function, so it never calls this module's network code: the
consumer runs `await converter.prefetch(fx_keys(plan))` first and passes the resulting
`FxRates` (an immutable lookup) to it.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import functools
import json
import re
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Final, Literal

import httpx
import structlog
from sqlalchemy import Select, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import SQLAlchemyError

from app import clock
from app.db import FxRateRecord

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from app.plan import Plan, Price

FxSource = Literal["bdi_daily", "inforeuro_monthly"]
"""Values of `fx_rates.source`."""

EUR = "EUR"

BDI_BASE_URL = "https://tassidicambio.bancaditalia.it/terzevalute-wf-web/rest/v1.0"
BDI_TIMESERIES_PATH = "/dailyTimeSeries"
"""`?startDate=&endDate=&baseCurrencyIsoCode=<X>&currencyIsoCode=EUR&lang=en`."""

INFOREURO_MONTHLY_URL = "https://ec.europa.eu/budg/inforeuro/api/public/monthly-rates"
"""`?year=YYYY&month=M` -> a bare JSON array, one row per currency (`isoA3Code`, `value`)."""

INFOREURO_NO_DATA_CODE = 5
"""InforEuro's error `code` for "No rates published for period": not retried."""

LOOKBACK_DAYS = 7
"""How far back a daily rate may come from (weekends, holidays, not yet published today)."""

HTTP_TIMEOUT_SECONDS = 10.0
SOURCE_RETRIES = 2

RETRY_BACKOFF_SECONDS: tuple[float, ...] = (0.5, 1.5)
"""Pause before the first and the second retry of a source (the last value repeats)."""

SOURCE_DEADLINE_SECONDS = 20.0
"""Upper bound for one source, every attempt and pause included, so a quote that falls back to
InforEuro still answers within about a minute even when both hosts hang."""

FxKey = tuple[str, dt.date]
"""(ISO currency code, the date the rate must refer to)."""

log = structlog.get_logger(__name__)

_CURRENCY_RE: Final = re.compile(r"[A-Z]{3}")
_JSON_HEADERS: Final = {"Accept": "application/json"}
_RETRYABLE_STATUSES: Final = frozenset({408, 429})
_ONE_DAY: Final = dt.timedelta(days=1)


class FxUnavailable(Exception):  # noqa: N818 - the spec's name
    """Neither source has a usable rate for `currency` around `on_date`.

    `reasons` lists what was tried, one short English line per source (logs only, never shown
    to the user). The mapping turns this into an Italian booking note and a plan warning.
    """

    def __init__(self, currency: str, on_date: dt.date, reasons: list[str]) -> None:
        super().__init__(f"no EUR rate for {currency} on {on_date.isoformat()}")
        self.currency = currency
        self.on_date = on_date
        self.reasons = reasons


@dataclass(frozen=True, slots=True)
class FxQuote:
    """A usable rate: `rate` units of `currency` per 1 EUR, published for `rate_date`."""

    currency: str
    rate: Decimal
    rate_date: dt.date
    """The date the rate refers to: the Banca d'Italia reference date, or the first day of
    the month for InforEuro."""
    source: FxSource

    def to_eur_cents(self, amount_cents: int) -> int:
        """`convert_cents(amount_cents, self.rate)`."""
        return convert_cents(amount_cents, self.rate)


@dataclass(frozen=True, slots=True)
class FxRates:
    """Pre-fetched conversions for one plan: what `mapping.plan_to_trip` reads. Immutable."""

    quotes: Mapping[FxKey, FxQuote] = field(default_factory=dict[FxKey, FxQuote])
    missing: Mapping[FxKey, FxUnavailable] = field(default_factory=dict[FxKey, FxUnavailable])

    def get(self, currency: str, on_date: dt.date) -> FxQuote | None:
        """The quote for (currency, on_date); None when it is missing or was never requested.
        EUR always resolves to an identity quote (rate 1)."""
        if currency == EUR:
            return _identity_quote(on_date)
        return self.quotes.get((currency, on_date))


def convert_cents(amount_cents: int, rate: Decimal) -> int:
    """`amount_cents / rate` rounded half up to an int. Pure. Raises ValueError for a rate
    <= 0. Test vectors: 10000 USD cents at 1.1206 -> 8924; 12345 at 0.84763 -> 14564.

    Exact rational arithmetic: the Decimal rate is an exact fraction `num / den`, so the result
    is `amount * den / num` rounded half away from zero, with no intermediate precision loss.
    """
    if not rate.is_finite() or rate <= 0:
        msg = f"rate must be a finite number above zero, got {rate}"
        raise ValueError(msg)
    numerator, denominator = rate.as_integer_ratio()
    quotient, remainder = divmod(abs(amount_cents) * denominator, numerator)
    if 2 * remainder >= numerator:
        quotient += 1
    return quotient if amount_cents >= 0 else -quotient


def price_fx_date(price: Price) -> dt.date:
    """The date whose rate converts `price`: `price.retrieved_at` in Europe/Rome."""
    return price.retrieved_at.astimezone(clock.HOME_TIMEZONE).date()


def fx_keys(plan: Plan) -> set[FxKey]:
    """The non-EUR conversions `plan_to_trip` will need: one key per priced booking in
    `plan.bookings` (alternatives never reach TripTracker, so they are not converted)."""
    return {
        (booking.price.currency, price_fx_date(booking.price))
        for booking in plan.bookings
        if booking.price is not None and booking.price.currency != EUR
    }


def parse_bdi_timeseries(payload: Mapping[str, Any], currency: str) -> FxQuote | None:
    """The latest usable row of a Banca d'Italia `dailyTimeSeries` response: numeric `avgRate`
    ("N.A." is skipped), convention "C" taken as is and "I" inverted. None when no row is
    usable. Pure.

    The convention code is read from the row, else from `resultsInfo` (where
    `dailyTimeSeries` puts it); a row without a known code is skipped. Rows that name another
    currency (`isoCode`, as in a `dailyRates` answer) are skipped too.
    """
    info: Mapping[str, Any] = payload.get("resultsInfo") or {}
    if not isinstance(info, Mapping):
        info = {}
    info_iso = info.get("isoCode")
    if isinstance(info_iso, str) and info_iso.strip().upper() != currency:
        return None
    rows = payload.get("rates")
    if not isinstance(rows, list):
        return None
    best: FxQuote | None = None
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        quote = _bdi_row_quote(row, currency, default_code=info.get("exchangeConventionCode"))
        if quote is not None and (best is None or quote.rate_date >= best.rate_date):
            best = quote
    return best


def parse_inforeuro_monthly(
    payload: list[Mapping[str, Any]], currency: str, *, year: int, month: int
) -> FxQuote | None:
    """The `currency` row of an InforEuro `monthly-rates` array (parsed with Decimal floats),
    dated `year-month-01`. None when the currency is absent. Pure."""
    for row in payload:
        if not isinstance(row, Mapping) or row.get("isoA3Code") != currency:
            continue
        rate = _positive_decimal(row.get("value"))
        if rate is not None:
            return FxQuote(currency, rate, dt.date(year, month, 1), "inforeuro_monthly")
    return None


def is_publication_day(day: dt.date) -> bool:
    """True when Banca d'Italia publishes reference rates for `day`: Monday to Friday except the
    TARGET holidays (1 January, Good Friday, Easter Monday, 1 May, 25 and 26 December).
    Italian-only holidays such as 2 June do have rates (integrations.md §2.1). Pure."""
    return day.weekday() < 5 and day not in _target_holidays(day.year)


class FxConverter:
    """Rates from the cache, Banca d'Italia or InforEuro, in that order (module docstring).

    One instance per process (`sessions.PlannerServices.fx`). `offline=True` skips both
    network sources (cache only), for `app.cli replay` and tests that must not touch respx.
    """

    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        http: httpx.AsyncClient,
        offline: bool = False,
        today: Callable[[], dt.date] | None = None,
    ) -> None:
        """`http` is the application's shared client (its own timeout is not relied on:
        requests pass `HTTP_TIMEOUT_SECONDS`). `today` defaults to `clock.today`; a date in the
        future is clamped to it, since no source publishes future rates."""
        self._session_factory = session_factory
        self._http = http
        self._offline = offline
        self._today = today or clock.today

    @property
    def offline(self) -> bool:
        """True when no network source is ever asked (cache only)."""
        return self._offline

    async def quote(self, currency: str, on_date: dt.date) -> FxQuote:
        """The rate for `currency` on `on_date` (module algorithm). Writes newly fetched rates
        to `fx_rates` in its own short transaction. Raises `FxUnavailable` when both sources
        fail, ValueError for a malformed currency code."""
        _check_currency(currency)
        if currency == EUR:
            return _identity_quote(on_date)
        rate_day = min(on_date, self._today())
        reasons: list[str] = []

        cached = await self._cached_daily(currency, rate_day)
        if cached is not None and (self._offline or _is_latest(cached.rate_date, rate_day)):
            log.debug(
                "fx_cache_hit",
                currency=currency,
                on_date=rate_day.isoformat(),
                source=cached.source,
                rate_date=cached.rate_date.isoformat(),
            )
            return cached

        if self._offline:
            reasons.append("bdi_daily: offline and no cached daily rate")
        else:
            fetched = await self._fetch_bdi(currency, rate_day, reasons)
            if fetched is not None:
                if cached is not None and cached.rate_date > fetched.rate_date:
                    return cached
                await self._store(fetched)
                return fetched
        if cached is not None:
            log.info(
                "fx_older_daily_rate_used",
                currency=currency,
                on_date=rate_day.isoformat(),
                rate_date=cached.rate_date.isoformat(),
            )
            return cached

        monthly = await self._monthly(currency, rate_day, reasons)
        if monthly is not None:
            return monthly

        log.warning(
            "fx_rate_unavailable",
            currency=currency,
            on_date=on_date.isoformat(),
            reasons=reasons,
        )
        raise FxUnavailable(currency, on_date, reasons)

    async def to_eur_cents(self, amount_cents: int, currency: str, on_date: dt.date) -> int:
        """`(await self.quote(currency, on_date)).to_eur_cents(amount_cents)`; EUR amounts are
        returned unchanged. Raises `FxUnavailable`."""
        if currency == EUR:
            return amount_cents
        return (await self.quote(currency, on_date)).to_eur_cents(amount_cents)

    async def prefetch(self, keys: Iterable[FxKey]) -> FxRates:
        """Resolve every key concurrently (one `quote` per distinct key). Never raises
        `FxUnavailable`: failures are collected in `FxRates.missing`.

        Nothing else escapes either (a malformed code, an unexpected error: logged, and the key
        is missing), so a conversion problem never fails the plan. Cancellation propagates."""
        unique = list(dict.fromkeys(keys))
        outcomes = await asyncio.gather(*(self._resolve(key) for key in unique))
        quotes: dict[FxKey, FxQuote] = {}
        missing: dict[FxKey, FxUnavailable] = {}
        for key, outcome in zip(unique, outcomes, strict=True):
            if isinstance(outcome, FxQuote):
                quotes[key] = outcome
            else:
                missing[key] = outcome
        return FxRates(quotes=MappingProxyType(quotes), missing=MappingProxyType(missing))

    # --- internals ------------------------------------------------------------------------

    async def _resolve(self, key: FxKey) -> FxQuote | FxUnavailable:
        currency, on_date = key
        try:
            return await self.quote(currency, on_date)
        except FxUnavailable as exc:
            return exc
        except ValueError as exc:
            log.warning("fx_invalid_currency", currency=currency[:8], on_date=on_date.isoformat())
            return FxUnavailable(currency, on_date, [str(exc)])
        except Exception as exc:
            log.exception("fx_quote_failed", currency=currency[:8], on_date=on_date.isoformat())
            return FxUnavailable(currency, on_date, [f"unexpected {type(exc).__name__}"])

    async def _monthly(
        self, currency: str, rate_day: dt.date, reasons: list[str]
    ) -> FxQuote | None:
        """Step 4: InforEuro for `rate_day`'s month, then the month before on "no rates"."""
        year, month = rate_day.year, rate_day.month
        for _ in range(2):
            period = f"{year:04d}-{month:02d}"
            cached = await self._cached_monthly(currency, dt.date(year, month, 1))
            if cached is not None:
                log.debug("fx_cache_hit", currency=currency, source=cached.source, period=period)
                return cached
            if self._offline:
                reasons.append(f"inforeuro_monthly {period}: offline and not cached")
            else:
                fetched = await self._fetch_inforeuro(currency, year, month, reasons)
                if isinstance(fetched, FxQuote):
                    await self._store(fetched)
                    return fetched
                if fetched is not _NO_DATA:
                    return None
            year, month = _previous_month(year, month)
        return None

    async def _fetch_bdi(
        self, currency: str, rate_day: dt.date, reasons: list[str]
    ) -> FxQuote | None:
        start = rate_day - dt.timedelta(days=LOOKBACK_DAYS)
        params = {
            "startDate": start.isoformat(),
            "endDate": rate_day.isoformat(),
            "baseCurrencyIsoCode": currency,
            "currencyIsoCode": EUR,
            "lang": "en",
        }
        try:
            reply = await self._get_json("bdi_daily", BDI_BASE_URL + BDI_TIMESERIES_PATH, params)
        except _SourceError as exc:
            reasons.append(f"bdi_daily: {exc.reason}")
            return None
        if reply.status != httpx.codes.OK or not isinstance(reply.payload, Mapping):
            reasons.append(f"bdi_daily: {reply.describe()}")
            _log_source_failed("bdi_daily", currency, reply)
            return None
        quote = parse_bdi_timeseries(reply.payload, currency)
        if quote is None:
            reasons.append(f"bdi_daily: no usable rate from {start} to {rate_day}")
            log.info(
                "fx_no_rate_published",
                source="bdi_daily",
                currency=currency,
                start_date=start.isoformat(),
                end_date=rate_day.isoformat(),
            )
            return None
        _log_fetched(quote, on_date=rate_day)
        return quote

    async def _fetch_inforeuro(
        self, currency: str, year: int, month: int, reasons: list[str]
    ) -> FxQuote | _NoData | None:
        period = f"{year:04d}-{month:02d}"
        params = {"year": str(year), "month": str(month)}
        try:
            reply = await self._get_json("inforeuro_monthly", INFOREURO_MONTHLY_URL, params)
        except _SourceError as exc:
            reasons.append(f"inforeuro_monthly {period}: {exc.reason}")
            return None
        if _inforeuro_error_code(reply.payload) == INFOREURO_NO_DATA_CODE:
            reasons.append(f"inforeuro_monthly {period}: no rates published")
            log.info("fx_no_rate_published", source="inforeuro_monthly", period=period)
            return _NO_DATA
        if reply.status != httpx.codes.OK or not isinstance(reply.payload, list):
            reasons.append(f"inforeuro_monthly {period}: {reply.describe()}")
            _log_source_failed("inforeuro_monthly", currency, reply)
            return None
        quote = parse_inforeuro_monthly(reply.payload, currency, year=year, month=month)
        if quote is None:
            reasons.append(f"inforeuro_monthly {period}: {currency} not listed")
            log.info("fx_currency_not_listed", source="inforeuro_monthly", currency=currency)
            return None
        _log_fetched(quote, on_date=quote.rate_date)
        return quote

    async def _get_json(self, source: FxSource, url: str, params: Mapping[str, str]) -> _Reply:
        """GET with retries. Returns the first final reply: a 200, a 4xx other than 408/429,
        InforEuro's "no rates" answer, or the last 5xx once the retries are spent. Raises
        `_SourceError` when every attempt failed at the network level, or at the deadline."""
        attempts = 1 + SOURCE_RETRIES
        made = 0
        failure = "no attempt"
        try:
            async with asyncio.timeout(SOURCE_DEADLINE_SECONDS):
                while made < attempts:
                    if made:
                        await asyncio.sleep(_backoff(made))
                    made += 1
                    try:
                        response = await self._http.get(
                            url, params=params, headers=_JSON_HEADERS, timeout=HTTP_TIMEOUT_SECONDS
                        )
                    except httpx.HTTPError as exc:
                        failure = type(exc).__name__
                        retry = isinstance(exc, httpx.TransportError) and made < attempts
                        log.warning(
                            "fx_request_failed",
                            source=source,
                            attempt=made,
                            error=failure,
                            will_retry=retry,
                        )
                        if not retry:
                            break
                        continue
                    reply = _Reply(response.status_code, _json_body(response), made)
                    if not _should_retry(source, reply) or made == attempts:
                        return reply
                    failure = f"HTTP {reply.status}"
                    log.warning(
                        "fx_request_failed",
                        source=source,
                        attempt=made,
                        status=reply.status,
                        will_retry=True,
                    )
        except TimeoutError:
            failure = f"no answer within {SOURCE_DEADLINE_SECONDS:g} s"
            log.warning("fx_source_deadline", source=source, attempts=made)
        raise _SourceError(f"{failure} ({_attempts(made)})")

    async def _cached_daily(self, currency: str, rate_day: dt.date) -> FxQuote | None:
        statement = (
            select(FxRateRecord)
            .where(
                FxRateRecord.currency == currency,
                FxRateRecord.source == "bdi_daily",
                FxRateRecord.date >= rate_day - dt.timedelta(days=LOOKBACK_DAYS),
                FxRateRecord.date <= rate_day,
            )
            .order_by(FxRateRecord.date.desc())
            .limit(1)
        )
        return await self._read(statement, currency, "bdi_daily")

    async def _cached_monthly(self, currency: str, first_day: dt.date) -> FxQuote | None:
        statement = select(FxRateRecord).where(
            FxRateRecord.currency == currency,
            FxRateRecord.source == "inforeuro_monthly",
            FxRateRecord.date == first_day,
        )
        return await self._read(statement, currency, "inforeuro_monthly")

    async def _read(
        self, statement: Select[FxRateRecord], currency: str, source: FxSource
    ) -> FxQuote | None:
        try:
            async with self._session_factory() as session:
                record = await session.scalar(statement)
        except (SQLAlchemyError, OSError) as exc:
            log.warning("fx_cache_read_failed", source=source, error=type(exc).__name__)
            return None
        if record is None:
            return None
        rate = _positive_decimal(record.rate)
        if rate is None:
            log.warning("fx_cache_bad_rate", source=source, currency=currency)
            return None
        return FxQuote(currency, rate, record.date, source)

    async def _store(self, quote: FxQuote) -> None:
        statement = (
            pg_insert(FxRateRecord)
            .values(
                date=quote.rate_date,
                currency=quote.currency,
                source=quote.source,
                rate=quote.rate,
            )
            .on_conflict_do_nothing(index_elements=["date", "currency", "source"])
        )
        try:
            async with self._session_factory.begin() as session:
                await session.execute(statement)
        except (SQLAlchemyError, OSError) as exc:
            log.warning("fx_cache_write_failed", source=quote.source, error=type(exc).__name__)


async def to_eur_cents(
    amount_cents: int, currency: str, on_date: dt.date, *, converter: FxConverter
) -> int:
    """The spec's entry point: `converter.to_eur_cents(amount_cents, currency, on_date)`.
    Raises `FxUnavailable` when no source has a rate."""
    return await converter.to_eur_cents(amount_cents, currency, on_date)


# --- helpers --------------------------------------------------------------------------------


class _NoData:
    """InforEuro answered "No rates published for period" (`code 5`)."""


_NO_DATA: Final = _NoData()


class _SourceError(Exception):
    """A source gave no answer worth reading (network errors, deadline)."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True, slots=True)
class _Reply:
    status: int
    payload: Any
    """The JSON body (floats as Decimal), or None when the body is not JSON."""
    attempts: int = 1

    def describe(self) -> str:
        what = (
            "HTTP 200 with an unexpected body"
            if self.status == httpx.codes.OK
            else f"HTTP {self.status}"
        )
        return f"{what} ({_attempts(self.attempts)})"


def _identity_quote(on_date: dt.date) -> FxQuote:
    return FxQuote(EUR, Decimal(1), on_date, "bdi_daily")


def _check_currency(currency: str) -> None:
    if not isinstance(currency, str) or not _CURRENCY_RE.fullmatch(currency):
        msg = f"currency must be an upper-case ISO 4217 code such as USD, got {currency!r:.20}"
        raise ValueError(msg)


def _positive_decimal(value: object) -> Decimal | None:
    """A finite Decimal above zero from a JSON value (string, int, Decimal), else None."""
    if isinstance(value, bool):
        return None
    if isinstance(value, Decimal):
        number = value
    elif isinstance(value, int):
        number = Decimal(value)
    elif isinstance(value, float):
        number = Decimal(repr(value))
    elif isinstance(value, str):
        try:
            number = Decimal(value.strip())
        except InvalidOperation:
            return None
    else:
        return None
    if not number.is_finite() or number <= 0:
        return None
    return number


def _bdi_row_quote(
    row: Mapping[str, Any], currency: str, *, default_code: object
) -> FxQuote | None:
    iso = row.get("isoCode")
    if iso is not None and iso != currency:
        return None
    reference = row.get("referenceDate")
    if not isinstance(reference, str):
        return None
    try:
        rate_date = dt.date.fromisoformat(reference)
    except ValueError:
        return None
    rate = _positive_decimal(row.get("avgRate"))
    if rate is None:
        return None
    code = row.get("exchangeConventionCode", default_code)
    if code == "I":
        rate = Decimal(1) / rate
    elif code != "C":
        return None
    return FxQuote(currency, rate, rate_date, "bdi_daily")


def _inforeuro_error_code(payload: Any) -> int | None:
    if not isinstance(payload, Mapping):
        return None
    code = payload.get("code")
    return code if isinstance(code, int) and not isinstance(code, bool) else None


def _json_body(response: httpx.Response) -> Any:
    try:
        return json.loads(response.content, parse_float=Decimal)
    except ValueError:
        return None


def _should_retry(source: FxSource, reply: _Reply) -> bool:
    if reply.status == httpx.codes.OK:
        return False
    if source == "inforeuro_monthly" and (
        _inforeuro_error_code(reply.payload) == INFOREURO_NO_DATA_CODE
    ):
        return False
    return reply.status >= 500 or reply.status in _RETRYABLE_STATUSES


def _backoff(retry: int) -> float:
    """Seconds to wait before retry number `retry` (1-based)."""
    if not RETRY_BACKOFF_SECONDS:
        return 0.0
    return RETRY_BACKOFF_SECONDS[min(retry, len(RETRY_BACKOFF_SECONDS)) - 1]


def _attempts(count: int) -> str:
    return f"{count} attempt" if count == 1 else f"{count} attempts"


def _previous_month(year: int, month: int) -> tuple[int, int]:
    return (year - 1, 12) if month == 1 else (year, month - 1)


def _easter_sunday(year: int) -> dt.date:
    """Gregorian Easter Sunday (anonymous Gregorian algorithm, Meeus/Jones/Butcher)."""
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    weekday_shift = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * weekday_shift) // 451
    month, day = divmod(h + weekday_shift - 7 * m + 114, 31)
    return dt.date(year, month, day + 1)


@functools.cache
def _target_holidays(year: int) -> frozenset[dt.date]:
    easter = _easter_sunday(year)
    return frozenset(
        {
            dt.date(year, 1, 1),
            easter - dt.timedelta(days=2),
            easter + _ONE_DAY,
            dt.date(year, 5, 1),
            dt.date(year, 12, 25),
            dt.date(year, 12, 26),
        }
    )


def _is_latest(rate_date: dt.date, on_date: dt.date) -> bool:
    """True when no publication day falls in `(rate_date, on_date]`: nothing newer can exist."""
    day = rate_date + _ONE_DAY
    while day <= on_date:
        if is_publication_day(day):
            return False
        day += _ONE_DAY
    return True


def _log_fetched(quote: FxQuote, *, on_date: dt.date) -> None:
    log.info(
        "fx_rate_fetched",
        source=quote.source,
        currency=quote.currency,
        on_date=on_date.isoformat(),
        rate_date=quote.rate_date.isoformat(),
        rate=str(quote.rate),
    )


def _log_source_failed(source: FxSource, currency: str, reply: _Reply) -> None:
    log.warning("fx_source_failed", source=source, currency=currency, status=reply.status)
