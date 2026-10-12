"""Currency conversion (app/fx.py): the rounding vectors of docs/research/integrations.md §2.3,
the parsers on the real fixtures in tests/fixtures/fx/, and `FxConverter` against respx-mocked
Banca d'Italia and InforEuro endpoints with the `fx_rates` cache on Postgres.

Everything is offline: respx runs with `assert_all_mocked`, so an unexpected request fails the
test instead of reaching the network.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import json
import logging
from collections.abc import AsyncIterator, Iterator
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

import httpx
import pytest
import respx
import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool
from structlog.testing import LogCapture
from structlog.typing import EventDict

from app import fx
from app.config import PLAN_LOG_KEYS, add_plan_log_keys
from app.db import FxRateRecord, create_session_factory
from app.fx import (
    EUR,
    FxConverter,
    FxQuote,
    FxRates,
    FxUnavailable,
    convert_cents,
    fx_keys,
    is_publication_day,
    parse_bdi_timeseries,
    parse_inforeuro_monthly,
    price_fx_date,
    to_eur_cents,
)
from app.plan import Plan, Price

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "fx"
BDI_URL = fx.BDI_BASE_URL + fx.BDI_TIMESERIES_PATH
INFOREURO_URL = fx.INFOREURO_MONTHLY_URL

TODAY = dt.date(2026, 10, 12)  # a Monday; Banca d'Italia's latest rate is Friday 2026-10-09
FRIDAY = dt.date(2026, 10, 9)
SATURDAY = dt.date(2026, 10, 10)
SUNDAY = dt.date(2026, 10, 11)
OCTOBER = dt.date(2026, 10, 1)

SessionFactory = async_sessionmaker[AsyncSession]


# --- helpers ----------------------------------------------------------------------------------


def fixture_bytes(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def json_reply(body: bytes | Any, status: int = 200) -> httpx.Response:
    content = body if isinstance(body, bytes) else json.dumps(body).encode()
    return httpx.Response(status, content=content, headers={"content-type": "application/json"})


BDI_SERIES_USD = fixture_bytes("bdi_timeseries_USD_2026-10-03_2026-10-12.json")
BDI_DAILY_FRIDAY = fixture_bytes("bdi_daily_2026-10-09.json")
BDI_DAILY_SATURDAY = fixture_bytes("bdi_daily_2026-10-10.json")
INFOREURO_OCTOBER = fixture_bytes("inforeuro_2026-10.json")
INFOREURO_NOVEMBER_ERROR = fixture_bytes("inforeuro_2026-11_error.json")


def series(currency: str, *rows: tuple[str, str], code: str = "C") -> dict[str, Any]:
    """A `dailyTimeSeries` body in Banca d'Italia's shape (the code lives in resultsInfo)."""
    return {
        "resultsInfo": {
            "totalRecords": len(rows),
            "isoCode": currency,
            "exchangeConventionCode": code,
        },
        "rates": [
            {
                "referenceDate": day,
                "avgRate": rate,
                "exchangeConvention": "Foreign currency amount for 1 Euro.",
            }
            for day, rate in rows
        ],
    }


EMPTY_SERIES: dict[str, Any] = {"resultsInfo": {"totalRecords": 0}, "rates": []}


async def seed(factory: SessionFactory, *rows: tuple[dt.date, str, str, str]) -> None:
    async with factory.begin() as session:
        session.add_all(
            FxRateRecord(date=day, currency=currency, source=source, rate=Decimal(rate))
            for day, currency, source, rate in rows
        )


async def stored(factory: SessionFactory) -> list[tuple[dt.date, str, str, Decimal]]:
    async with factory() as session:
        records = await session.scalars(
            select(FxRateRecord).order_by(
                FxRateRecord.date, FxRateRecord.currency, FxRateRecord.source
            )
        )
        return [(r.date, r.currency, r.source, r.rate) for r in records]


def make_price(currency: str, retrieved_at: str, amount_cents: int = 10000) -> dict[str, Any]:
    return {
        "amount_cents": amount_cents,
        "currency": currency,
        "status": "verified",
        "source_url": "https://www.expedia.it/Hotel-Search",
        "retrieved_at": retrieved_at,
    }


def make_booking(title: str, price: dict[str, Any] | None) -> dict[str, Any]:
    booking: dict[str, Any] = {
        "title": title,
        "kind": "lodging",
        "scheduled_for": "2026-11-14T15:00:00+00:00",
    }
    if price is not None:
        booking["price"] = price
    return booking


# --- fixtures ---------------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _no_backoff(monkeypatch: pytest.MonkeyPatch) -> None:
    """Retries without pauses, so the retry tests stay fast."""
    monkeypatch.setattr(fx, "RETRY_BACKOFF_SECONDS", (0.0,))


@pytest.fixture
def router() -> Iterator[respx.MockRouter]:
    with respx.mock(assert_all_called=False, assert_all_mocked=True) as mock:
        yield mock


@pytest.fixture
async def http() -> AsyncIterator[httpx.AsyncClient]:
    async with httpx.AsyncClient(follow_redirects=False) as client:
        yield client


@pytest.fixture
def converter(db_session_factory: SessionFactory, http: httpx.AsyncClient) -> FxConverter:
    return FxConverter(session_factory=db_session_factory, http=http, today=lambda: TODAY)


@pytest.fixture
def logs(monkeypatch: pytest.MonkeyPatch) -> list[EventDict]:
    """Every fx log entry at any level, independent of the global structlog configuration."""
    capture = LogCapture()
    logger = structlog.wrap_logger(
        structlog.PrintLogger(),
        processors=[capture],
        wrapper_class=structlog.make_filtering_bound_logger(logging.DEBUG),
    )
    monkeypatch.setattr(fx, "log", logger)
    return capture.entries


def unreachable_session_factory() -> SessionFactory:
    """A session factory whose database refuses connections (port 1 on localhost)."""
    engine = create_async_engine(
        "postgresql+asyncpg://localhost:1/trip_planner_test_unreachable", poolclass=NullPool
    )
    return create_session_factory(engine)


def no_database() -> SessionFactory:
    def refuse() -> AsyncSession:
        raise AssertionError("EUR must not touch the database")

    return cast(SessionFactory, refuse)


# --- pure: rounding ---------------------------------------------------------------------------

VECTORS = [
    # (rate, 10000 ->, 12345 ->): integrations.md §2.3
    ("1.1206", 8924, 11016),  # BdI 2026-10-09 USD
    ("0.84763", 11798, 14564),  # BdI 2026-10-09 GBP
    ("0.9313", 10738, 13256),  # BdI 2026-10-09 CHF
    ("1.1355", 8807, 10872),  # InforEuro 2026-10 USD
    ("0.85718", 11666, 14402),  # InforEuro 2026-10 GBP
    ("0.9461", 10570, 13048),  # InforEuro 2026-10 CHF
]


@pytest.mark.parametrize(("rate", "eur_10000", "eur_12345"), VECTORS)
def test_convert_cents_matches_the_research_vectors(
    rate: str, eur_10000: int, eur_12345: int
) -> None:
    assert convert_cents(10000, Decimal(rate)) == eur_10000
    assert convert_cents(12345, Decimal(rate)) == eur_12345


@pytest.mark.parametrize(
    ("amount", "rate", "expected"),
    [
        (5, "2", 3),  # 2.5 -> 3 (Python's round() would give 2)
        (25, "10", 3),  # 2.5 -> 3
        (1, "0.4", 3),  # exactly 2.5 -> 3, no binary float error
        (7, "2", 4),  # 3.5 -> 4
        (4, "3", 1),  # 1.33 -> 1
        (5, "3", 2),  # 1.67 -> 2
        (0, "1.1206", 0),
        (-5, "2", -3),  # half away from zero
        (10**11, "0.1", 10**12),  # the contract's largest amount stays exact
    ],
)
def test_convert_cents_rounds_half_up(amount: int, rate: str, expected: int) -> None:
    assert convert_cents(amount, Decimal(rate)) == expected


@pytest.mark.parametrize("rate", ["0", "-1.1206", "NaN", "Infinity", "-0"])
def test_convert_cents_rejects_unusable_rates(rate: str) -> None:
    with pytest.raises(ValueError, match="rate"):
        convert_cents(10000, Decimal(rate))


def test_quote_converts_with_its_rate() -> None:
    quote = FxQuote("GBP", Decimal("0.84763"), FRIDAY, "bdi_daily")

    assert quote.to_eur_cents(12345) == 14564


# --- pure: parsers ----------------------------------------------------------------------------


def test_parse_bdi_timeseries_takes_the_latest_row_of_the_fixture() -> None:
    payload = json.loads(BDI_SERIES_USD)

    quote = parse_bdi_timeseries(payload, "USD")

    assert quote == FxQuote("USD", Decimal("1.1206"), FRIDAY, "bdi_daily")
    assert quote is not None
    assert str(quote.rate) == "1.1206"


def test_parse_bdi_timeseries_skips_not_available_and_unknown_conventions() -> None:
    payload = series("USD", ("2026-10-07", "1.1177"), ("2026-10-08", "1.1186"))
    payload["rates"].append(
        {"referenceDate": "2026-10-09", "avgRate": "1.2", "exchangeConventionCode": "X"}
    )
    payload["rates"].append({"referenceDate": "2026-10-10", "avgRate": "N.A."})
    payload["rates"].append({"referenceDate": "not a date", "avgRate": "1.3"})

    quote = parse_bdi_timeseries(payload, "USD")

    assert quote == FxQuote("USD", Decimal("1.1186"), dt.date(2026, 10, 8), "bdi_daily")


def test_parse_bdi_timeseries_inverts_the_inverse_convention() -> None:
    # "I": EUR per 1 unit of the currency, so 1.25 EUR per GBP is 0.8 GBP per EUR.
    payload = series("GBP", ("2026-10-09", "1.25"), code="I")

    quote = parse_bdi_timeseries(payload, "GBP")

    assert quote == FxQuote("GBP", Decimal("0.8"), FRIDAY, "bdi_daily")
    assert quote is not None
    assert quote.to_eur_cents(10000) == 12500


def test_parse_bdi_timeseries_reads_the_daily_rates_shape() -> None:
    payload = json.loads(BDI_DAILY_FRIDAY)

    assert parse_bdi_timeseries(payload, "GBP") == FxQuote(
        "GBP", Decimal("0.84763"), FRIDAY, "bdi_daily"
    )
    assert parse_bdi_timeseries(payload, "CHF") == FxQuote(
        "CHF", Decimal("0.9313"), FRIDAY, "bdi_daily"
    )
    assert parse_bdi_timeseries(payload, "JPY") is None


def test_parse_bdi_timeseries_without_rows_is_none() -> None:
    assert parse_bdi_timeseries(json.loads(BDI_DAILY_SATURDAY), "USD") is None
    assert parse_bdi_timeseries(EMPTY_SERIES, "USD") is None
    assert parse_bdi_timeseries({}, "USD") is None


def test_parse_bdi_timeseries_of_another_currency_is_none() -> None:
    assert parse_bdi_timeseries(json.loads(BDI_SERIES_USD), "GBP") is None


@pytest.mark.parametrize(
    ("currency", "rate"), [("USD", "1.1355"), ("GBP", "0.85718"), ("CHF", "0.9461")]
)
def test_parse_inforeuro_monthly_reads_the_fixture_exactly(currency: str, rate: str) -> None:
    payload = json.loads(INFOREURO_OCTOBER, parse_float=Decimal)

    quote = parse_inforeuro_monthly(payload, currency, year=2026, month=10)

    assert quote == FxQuote(currency, Decimal(rate), OCTOBER, "inforeuro_monthly")
    assert quote is not None
    assert str(quote.rate) == rate


def test_parse_inforeuro_monthly_without_the_currency_is_none() -> None:
    payload = json.loads(INFOREURO_OCTOBER, parse_float=Decimal)

    assert parse_inforeuro_monthly(payload, "ZZZ", year=2026, month=10) is None
    assert parse_inforeuro_monthly([], "USD", year=2026, month=10) is None


@pytest.mark.parametrize(
    ("day", "published"),
    [
        (FRIDAY, True),
        (SATURDAY, False),
        (SUNDAY, False),
        (TODAY, True),
        (dt.date(2025, 12, 25), False),
        (dt.date(2025, 12, 26), False),
        (dt.date(2026, 1, 1), False),
        (dt.date(2026, 4, 3), False),  # Good Friday
        (dt.date(2026, 4, 6), False),  # Easter Monday
        (dt.date(2026, 5, 1), False),
        (dt.date(2026, 6, 2), True),  # Italian-only holiday: rates are published
        (dt.date(2027, 3, 26), False),  # Good Friday 2027
        (dt.date(2027, 3, 29), False),  # Easter Monday 2027
    ],
)
def test_publication_days_follow_the_target_calendar(day: dt.date, published: bool) -> None:
    assert is_publication_day(day) is published


# --- pure: dates, keys, lookup ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("retrieved_at", "expected"),
    [
        ("2026-10-11T23:30:00+00:00", dt.date(2026, 10, 12)),  # already Monday in Rome
        ("2026-10-12T00:30:00+02:00", dt.date(2026, 10, 12)),
        ("2026-10-12T23:30:00-04:00", dt.date(2026, 10, 13)),
        ("2026-12-31T23:30:00+00:00", dt.date(2027, 1, 1)),  # CET, UTC+1
    ],
)
def test_price_fx_date_is_the_retrieval_date_in_rome(retrieved_at: str, expected: dt.date) -> None:
    price = Price.model_validate(make_price("USD", retrieved_at))

    assert price_fx_date(price) == expected


def test_fx_keys_lists_the_non_eur_booking_prices_only() -> None:
    plan = Plan.model_validate(
        {
            "title": "Londra e New York",
            "destination": "Londra, Regno Unito",
            "timezone": "Europe/London",
            "start_date": "2026-11-14",
            "end_date": "2026-11-17",
            "travelers": 2,
            "days": [],
            "bookings": [
                make_booking("Hotel a Londra", make_price("GBP", "2026-10-12T10:00:00+02:00")),
                make_booking("Volo", make_price("USD", "2026-10-11T23:30:00+00:00")),
                make_booking("Altro volo", make_price("USD", "2026-10-12T08:00:00+02:00")),
                make_booking("Treno", make_price("EUR", "2026-10-12T10:00:00+02:00")),
                make_booking("Cena", None),
            ],
            "alternatives": [
                make_booking("Hotel a Tokyo", make_price("JPY", "2026-10-12T10:00:00+02:00")),
            ],
            "summary": "Quattro giorni tra Londra e New York.",
        }
    )

    assert fx_keys(plan) == {("GBP", TODAY), ("USD", TODAY)}


def test_fx_rates_lookup() -> None:
    usd = FxQuote("USD", Decimal("1.1206"), FRIDAY, "bdi_daily")
    rates = FxRates(
        quotes={("USD", TODAY): usd},
        missing={("ZZZ", TODAY): FxUnavailable("ZZZ", TODAY, ["not listed"])},
    )

    assert rates.get("USD", TODAY) is usd
    assert rates.get("USD", SUNDAY) is None  # never requested
    assert rates.get("ZZZ", TODAY) is None  # missing
    identity = rates.get(EUR, dt.date(2030, 1, 1))
    assert identity is not None
    assert identity.rate == 1
    assert identity.to_eur_cents(12345) == 12345
    assert FxRates().get(EUR, TODAY) is not None


# --- converter: EUR ---------------------------------------------------------------------------


async def test_eur_is_passed_through_without_any_io(
    router: respx.MockRouter, http: httpx.AsyncClient
) -> None:
    converter = FxConverter(session_factory=no_database(), http=http, today=lambda: TODAY)

    assert await converter.to_eur_cents(31480, EUR, TODAY) == 31480
    assert await to_eur_cents(31480, EUR, TODAY, converter=converter) == 31480
    quote = await converter.quote(EUR, TODAY)
    assert (quote.currency, quote.rate) == (EUR, Decimal(1))
    rates = await converter.prefetch([(EUR, TODAY)])
    assert rates.missing == {}
    assert rates.get(EUR, TODAY) is not None
    assert not router.calls


# --- converter: Banca d'Italia and the daily cache --------------------------------------------


async def test_bdi_miss_fetches_the_series_and_caches_the_reference_date(
    router: respx.MockRouter, converter: FxConverter, db_session_factory: SessionFactory
) -> None:
    route = router.get(BDI_URL).mock(return_value=json_reply(BDI_SERIES_USD))

    quote = await converter.quote("USD", TODAY)

    assert quote == FxQuote("USD", Decimal("1.1206"), FRIDAY, "bdi_daily")
    request = route.calls.last.request
    assert dict(request.url.params) == {
        "startDate": "2026-10-05",
        "endDate": "2026-10-12",
        "baseCurrencyIsoCode": "USD",
        "currencyIsoCode": "EUR",
        "lang": "en",
    }
    assert request.headers["accept"] == "application/json"
    assert await stored(db_session_factory) == [(FRIDAY, "USD", "bdi_daily", Decimal("1.1206"))]
    assert await converter.to_eur_cents(10000, "USD", TODAY) == 8924
    assert await to_eur_cents(12345, "USD", TODAY, converter=converter) == 11016


async def test_weekend_walks_back_to_friday_then_hits_the_cache(
    router: respx.MockRouter, converter: FxConverter
) -> None:
    route = router.get(BDI_URL).mock(return_value=json_reply(BDI_SERIES_USD))

    first = await converter.quote("USD", SUNDAY)
    again = await converter.quote("USD", SUNDAY)
    saturday = await converter.quote("USD", SATURDAY)

    assert first.rate_date == FRIDAY
    assert again == first
    assert saturday == first
    assert route.call_count == 1
    params = route.calls.last.request.url.params
    assert (params["startDate"], params["endDate"]) == ("2026-10-04", "2026-10-11")


async def test_cached_friday_rate_answers_for_the_weekend_without_network(
    router: respx.MockRouter, converter: FxConverter, db_session_factory: SessionFactory
) -> None:
    await seed(db_session_factory, (FRIDAY, "USD", "bdi_daily", "1.1206"))

    for day in (FRIDAY, SATURDAY, SUNDAY):
        assert await converter.quote("USD", day) == FxQuote(
            "USD", Decimal("1.1206"), FRIDAY, "bdi_daily"
        )
    assert not router.calls


@pytest.mark.parametrize(
    ("cached_day", "on_date"),
    [
        (dt.date(2025, 12, 24), dt.date(2025, 12, 28)),  # Christmas, Santo Stefano, weekend
        (dt.date(2026, 4, 2), dt.date(2026, 4, 6)),  # Good Friday to Easter Monday
        (dt.date(2025, 12, 31), dt.date(2026, 1, 1)),  # New Year's Day
    ],
)
async def test_cached_rate_answers_across_target_holidays(
    router: respx.MockRouter,
    converter: FxConverter,
    db_session_factory: SessionFactory,
    cached_day: dt.date,
    on_date: dt.date,
) -> None:
    await seed(db_session_factory, (cached_day, "USD", "bdi_daily", "1.1000"))

    quote = await converter.quote("USD", on_date)

    assert quote.rate_date == cached_day
    assert not router.calls


async def test_an_older_cached_rate_is_refreshed_from_bdi(
    router: respx.MockRouter, converter: FxConverter, db_session_factory: SessionFactory
) -> None:
    await seed(db_session_factory, (dt.date(2026, 10, 7), "USD", "bdi_daily", "1.1177"))
    route = router.get(BDI_URL).mock(return_value=json_reply(BDI_SERIES_USD))

    quote = await converter.quote("USD", TODAY)

    assert route.call_count == 1
    assert quote == FxQuote("USD", Decimal("1.1206"), FRIDAY, "bdi_daily")
    assert await stored(db_session_factory) == [
        (dt.date(2026, 10, 7), "USD", "bdi_daily", Decimal("1.1177")),
        (FRIDAY, "USD", "bdi_daily", Decimal("1.1206")),
    ]


async def test_an_older_cached_rate_is_used_when_bdi_fails(
    router: respx.MockRouter, converter: FxConverter, db_session_factory: SessionFactory
) -> None:
    await seed(db_session_factory, (dt.date(2026, 10, 8), "USD", "bdi_daily", "1.1186"))
    bdi = router.get(BDI_URL).mock(return_value=httpx.Response(503))
    inforeuro = router.get(INFOREURO_URL).mock(return_value=json_reply(INFOREURO_OCTOBER))

    quote = await converter.quote("USD", TODAY)

    assert quote == FxQuote("USD", Decimal("1.1186"), dt.date(2026, 10, 8), "bdi_daily")
    assert bdi.call_count == 1 + fx.SOURCE_RETRIES
    assert not inforeuro.called


async def test_a_monthly_row_never_counts_as_a_daily_hit(
    router: respx.MockRouter, converter: FxConverter, db_session_factory: SessionFactory
) -> None:
    await seed(db_session_factory, (OCTOBER, "USD", "inforeuro_monthly", "1.1355"))
    route = router.get(BDI_URL).mock(
        return_value=json_reply(series("USD", ("2026-09-30", "1.1340"), ("2026-10-01", "1.1350")))
    )

    quote = await converter.quote("USD", OCTOBER)

    assert route.call_count == 1
    assert quote == FxQuote("USD", Decimal("1.1350"), OCTOBER, "bdi_daily")
    # Same date, different sources: both rows live side by side.
    assert await stored(db_session_factory) == [
        (OCTOBER, "USD", "bdi_daily", Decimal("1.1350")),
        (OCTOBER, "USD", "inforeuro_monthly", Decimal("1.1355")),
    ]


async def test_a_future_date_is_clamped_to_today(
    router: respx.MockRouter, converter: FxConverter
) -> None:
    route = router.get(BDI_URL).mock(return_value=json_reply(BDI_SERIES_USD))
    travel_day = dt.date(2026, 11, 20)

    rates = await converter.prefetch([("USD", travel_day)])

    params = route.calls.last.request.url.params
    assert (params["startDate"], params["endDate"]) == ("2026-10-05", "2026-10-12")
    quote = rates.get("USD", travel_day)
    assert quote is not None
    assert quote.rate_date == FRIDAY


async def test_concurrent_keys_of_one_currency_store_the_rate_once(
    router: respx.MockRouter, converter: FxConverter, db_session_factory: SessionFactory
) -> None:
    router.get(BDI_URL).mock(return_value=json_reply(BDI_SERIES_USD))

    rates = await converter.prefetch([("USD", TODAY), ("USD", SUNDAY), ("USD", SATURDAY)])

    assert rates.missing == {}
    assert {quote.rate_date for quote in rates.quotes.values()} == {FRIDAY}
    assert await stored(db_session_factory) == [(FRIDAY, "USD", "bdi_daily", Decimal("1.1206"))]


# --- converter: falling back to InforEuro -----------------------------------------------------


@pytest.mark.parametrize(
    ("reply", "attempts"),
    [
        (httpx.Response(503), 1 + fx.SOURCE_RETRIES),
        (httpx.Response(500, text="Internal Server Error"), 1 + fx.SOURCE_RETRIES),
        (httpx.ConnectError("connection refused"), 1 + fx.SOURCE_RETRIES),
        (httpx.ReadTimeout("timed out"), 1 + fx.SOURCE_RETRIES),
        (
            httpx.Response(400, text="WARNING! Parameter baseCurrencyIsoCode: Incorrect format"),
            1,
        ),
        (json_reply(EMPTY_SERIES), 1),  # nothing published in the window
        (httpx.Response(200, text="Date,Rate\n# DISCLAIMER"), 1),  # CSV instead of JSON
    ],
    ids=["503", "500", "connect-error", "read-timeout", "400", "empty-series", "not-json"],
)
async def test_bdi_failure_falls_back_to_inforeuro(
    router: respx.MockRouter,
    converter: FxConverter,
    db_session_factory: SessionFactory,
    reply: httpx.Response | Exception,
    attempts: int,
) -> None:
    bdi = router.get(BDI_URL)
    if isinstance(reply, Exception):
        bdi.mock(side_effect=reply)
    else:
        bdi.mock(return_value=reply)
    inforeuro = router.get(INFOREURO_URL).mock(return_value=json_reply(INFOREURO_OCTOBER))

    quote = await converter.quote("USD", TODAY)

    assert bdi.call_count == attempts
    assert quote == FxQuote("USD", Decimal("1.1355"), OCTOBER, "inforeuro_monthly")
    assert dict(inforeuro.calls.last.request.url.params) == {"year": "2026", "month": "10"}
    assert await stored(db_session_factory) == [
        (OCTOBER, "USD", "inforeuro_monthly", Decimal("1.1355"))
    ]
    assert quote.to_eur_cents(10000) == 8807


async def test_cached_inforeuro_month_is_used_without_asking_again(
    router: respx.MockRouter, converter: FxConverter, db_session_factory: SessionFactory
) -> None:
    await seed(db_session_factory, (OCTOBER, "GBP", "inforeuro_monthly", "0.85718"))
    router.get(BDI_URL).mock(side_effect=httpx.ConnectError("down"))
    inforeuro = router.get(INFOREURO_URL).mock(return_value=json_reply(INFOREURO_OCTOBER))

    quote = await converter.quote("GBP", TODAY)

    assert quote == FxQuote("GBP", Decimal("0.85718"), OCTOBER, "inforeuro_monthly")
    assert not inforeuro.called
    assert quote.to_eur_cents(12345) == 14402


async def test_inforeuro_without_rates_for_the_month_uses_the_previous_month(
    router: respx.MockRouter,
    http: httpx.AsyncClient,
    db_session_factory: SessionFactory,
) -> None:
    first_of_november = dt.date(2026, 11, 2)
    converter = FxConverter(
        session_factory=db_session_factory, http=http, today=lambda: first_of_november
    )
    router.get(BDI_URL).mock(return_value=httpx.Response(503))
    november = router.get(INFOREURO_URL, params={"month": "11"}).mock(
        return_value=json_reply(INFOREURO_NOVEMBER_ERROR, status=500)
    )
    october = router.get(INFOREURO_URL, params={"month": "10"}).mock(
        return_value=json_reply(INFOREURO_OCTOBER)
    )

    quote = await converter.quote("CHF", first_of_november)

    assert november.call_count == 1  # code 5 is never retried
    assert october.call_count == 1
    assert quote == FxQuote("CHF", Decimal("0.9461"), OCTOBER, "inforeuro_monthly")
    assert quote.to_eur_cents(10000) == 10570


async def test_inforeuro_server_errors_are_retried(
    router: respx.MockRouter, converter: FxConverter
) -> None:
    router.get(BDI_URL).mock(return_value=json_reply(EMPTY_SERIES))
    inforeuro = router.get(INFOREURO_URL).mock(
        return_value=json_reply(
            {"code": 1, "exception": "Exception", "message": "Wrong input"}, 500
        )
    )

    with pytest.raises(FxUnavailable):
        await converter.quote("USD", TODAY)

    assert inforeuro.call_count == 1 + fx.SOURCE_RETRIES


# --- converter: nothing usable ----------------------------------------------------------------


async def test_both_sources_failing_raise_fx_unavailable(
    router: respx.MockRouter, converter: FxConverter, db_session_factory: SessionFactory
) -> None:
    router.get(BDI_URL).mock(side_effect=httpx.ConnectError("down"))
    router.get(INFOREURO_URL).mock(return_value=httpx.Response(503))

    with pytest.raises(FxUnavailable) as caught:
        await converter.quote("USD", TODAY)

    error = caught.value
    assert (error.currency, error.on_date) == ("USD", TODAY)
    assert len(error.reasons) == 2
    assert error.reasons[0].startswith("bdi_daily: ConnectError")
    assert error.reasons[1].startswith("inforeuro_monthly 2026-10: HTTP 503")
    with pytest.raises(FxUnavailable):
        await converter.to_eur_cents(10000, "USD", TODAY)
    with pytest.raises(FxUnavailable):
        await to_eur_cents(10000, "USD", TODAY, converter=converter)
    assert await stored(db_session_factory) == []


async def test_unknown_currency_ends_up_missing(
    router: respx.MockRouter, converter: FxConverter
) -> None:
    bdi = router.get(BDI_URL).mock(return_value=json_reply(EMPTY_SERIES))
    router.get(INFOREURO_URL).mock(return_value=json_reply(INFOREURO_OCTOBER))

    with pytest.raises(FxUnavailable) as caught:
        await converter.quote("ZZZ", TODAY)
    rates = await converter.prefetch([("ZZZ", TODAY)])

    assert caught.value.reasons == [
        "bdi_daily: no usable rate from 2026-10-05 to 2026-10-12",
        "inforeuro_monthly 2026-10: ZZZ not listed",
    ]
    assert bdi.calls.last.request.url.params["baseCurrencyIsoCode"] == "ZZZ"
    assert rates.quotes == {}
    assert set(rates.missing) == {("ZZZ", TODAY)}
    assert rates.get("ZZZ", TODAY) is None


@pytest.mark.parametrize("currency", ["usd", "US", "USDX", "", "U$D", "USD\n"])
async def test_malformed_currency_is_rejected_before_any_io(
    router: respx.MockRouter, http: httpx.AsyncClient, currency: str
) -> None:
    converter = FxConverter(session_factory=no_database(), http=http, today=lambda: TODAY)

    with pytest.raises(ValueError, match="ISO 4217"):
        await converter.quote(currency, TODAY)
    rates = await converter.prefetch([(currency, TODAY)])

    assert set(rates.missing) == {(currency, TODAY)}
    assert not router.calls


# --- converter: prefetch ----------------------------------------------------------------------


async def test_prefetch_resolves_every_distinct_key_and_collects_failures(
    router: respx.MockRouter, converter: FxConverter
) -> None:
    usd = router.get(BDI_URL, params={"baseCurrencyIsoCode": "USD"}).mock(
        return_value=json_reply(BDI_SERIES_USD)
    )
    router.get(BDI_URL, params={"baseCurrencyIsoCode": "GBP"}).mock(
        return_value=json_reply(series("GBP", ("2026-10-09", "0.84763")))
    )
    router.get(BDI_URL, params={"baseCurrencyIsoCode": "CHF"}).mock(
        return_value=httpx.Response(503)
    )
    router.get(BDI_URL, params={"baseCurrencyIsoCode": "ZZZ"}).mock(
        return_value=json_reply(EMPTY_SERIES)
    )
    router.get(INFOREURO_URL).mock(return_value=json_reply(INFOREURO_OCTOBER))
    keys = [("USD", TODAY), ("GBP", TODAY), ("CHF", TODAY), ("ZZZ", TODAY), ("USD", TODAY)]

    rates = await converter.prefetch(keys)

    assert usd.call_count == 1  # the duplicate key is resolved once
    assert set(rates.quotes) == {("USD", TODAY), ("GBP", TODAY), ("CHF", TODAY)}
    assert set(rates.missing) == {("ZZZ", TODAY)}
    usd_quote, gbp_quote, chf_quote = (rates.get(c, TODAY) for c in ("USD", "GBP", "CHF"))
    assert usd_quote is not None
    assert usd_quote.to_eur_cents(10000) == 8924
    assert gbp_quote is not None
    assert gbp_quote.to_eur_cents(10000) == 11798
    assert chf_quote == FxQuote("CHF", Decimal("0.9461"), OCTOBER, "inforeuro_monthly")
    with pytest.raises(TypeError):
        rates.quotes[("JPY", TODAY)] = usd_quote  # pyright: ignore[reportIndexIssue]


async def test_prefetch_turns_unexpected_errors_into_missing_quotes(
    router: respx.MockRouter,
    converter: FxConverter,
    monkeypatch: pytest.MonkeyPatch,
    logs: list[EventDict],
) -> None:
    async def broken(currency: str, on_date: dt.date) -> FxQuote:
        raise RuntimeError("bug")

    monkeypatch.setattr(converter, "quote", broken)

    rates = await converter.prefetch([("USD", TODAY)])

    assert rates.missing[("USD", TODAY)].reasons == ["unexpected RuntimeError"]
    assert [entry["event"] for entry in logs] == ["fx_quote_failed"]
    assert not router.calls


async def test_prefetch_of_nothing_is_empty(converter: FxConverter) -> None:
    rates = await converter.prefetch([])

    assert (dict(rates.quotes), dict(rates.missing)) == ({}, {})


# --- converter: offline -----------------------------------------------------------------------


async def test_offline_reads_the_cache_only(
    router: respx.MockRouter, http: httpx.AsyncClient, db_session_factory: SessionFactory
) -> None:
    converter = FxConverter(
        session_factory=db_session_factory, http=http, offline=True, today=lambda: TODAY
    )
    await seed(
        db_session_factory,
        (dt.date(2026, 10, 6), "USD", "bdi_daily", "1.1269"),  # old, but offline takes it
        (dt.date(2026, 9, 1), "GBP", "inforeuro_monthly", "0.86000"),  # previous month
    )

    rates = await converter.prefetch([("USD", TODAY), ("GBP", TODAY), ("CHF", TODAY)])

    assert converter.offline
    assert rates.get("USD", TODAY) == FxQuote(
        "USD", Decimal("1.1269"), dt.date(2026, 10, 6), "bdi_daily"
    )
    assert rates.get("GBP", TODAY) == FxQuote(
        "GBP", Decimal("0.86000"), dt.date(2026, 9, 1), "inforeuro_monthly"
    )
    assert rates.missing[("CHF", TODAY)].reasons == [
        "bdi_daily: offline and no cached daily rate",
        "inforeuro_monthly 2026-10: offline and not cached",
        "inforeuro_monthly 2026-09: offline and not cached",
    ]
    assert not router.calls


# --- converter: resilience and logs -----------------------------------------------------------


async def test_a_database_outage_does_not_stop_the_conversion(
    router: respx.MockRouter, http: httpx.AsyncClient, logs: list[EventDict]
) -> None:
    converter = FxConverter(
        session_factory=unreachable_session_factory(), http=http, today=lambda: TODAY
    )
    router.get(BDI_URL).mock(return_value=json_reply(BDI_SERIES_USD))

    assert await converter.to_eur_cents(10000, "USD", TODAY) == 8924

    events = [entry["event"] for entry in logs if entry["log_level"] == "warning"]
    assert events == ["fx_cache_read_failed", "fx_cache_write_failed"]


async def test_logs_name_the_source_and_status_but_never_the_body(
    router: respx.MockRouter, converter: FxConverter, logs: list[EventDict]
) -> None:
    marker = "BODY-MUST-NOT-BE-LOGGED"
    router.get(BDI_URL).mock(return_value=httpx.Response(503, text=marker))
    router.get(INFOREURO_URL).mock(
        return_value=json_reply({"code": 5, "message": marker}, status=500)
    )

    rates = await converter.prefetch([("USD", TODAY)])

    assert set(rates.missing) == {("USD", TODAY)}
    retries = [entry for entry in logs if entry["event"] == "fx_request_failed"]
    assert [(entry["source"], entry["status"], entry["attempt"]) for entry in retries] == [
        ("bdi_daily", 503, 1),
        ("bdi_daily", 503, 2),
    ]
    failed = [entry for entry in logs if entry["event"] == "fx_source_failed"]
    assert [(entry["source"], entry["status"]) for entry in failed] == [("bdi_daily", 503)]
    unavailable = [entry for entry in logs if entry["event"] == "fx_rate_unavailable"]
    assert len(unavailable) == 1
    assert unavailable[0]["currency"] == "USD"
    assert unavailable[0]["reasons"] == [
        "bdi_daily: HTTP 503 (3 attempts)",
        "inforeuro_monthly 2026-10: no rates published",
        "inforeuro_monthly 2026-09: no rates published",
    ]
    assert marker not in repr(logs)


async def test_fx_lines_carry_the_plan_keys_bound_by_the_caller(
    router: respx.MockRouter, converter: FxConverter, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Spec "Log e resilienza": plan_id, session_id, agent and event_type on every line. The
    converter knows no plan; its lines take what the caller bound in structlog's contextvars
    (main.configure_logging's chain), also from the tasks `prefetch` gathers."""
    capture = LogCapture()
    logger = structlog.wrap_logger(
        structlog.PrintLogger(),
        processors=[structlog.contextvars.merge_contextvars, add_plan_log_keys, capture],
        wrapper_class=structlog.make_filtering_bound_logger(logging.DEBUG),
    )
    monkeypatch.setattr(fx, "log", logger)
    router.get(BDI_URL).mock(return_value=httpx.Response(503))
    router.get(INFOREURO_URL).mock(return_value=json_reply(INFOREURO_NOVEMBER_ERROR))
    bound = {
        "plan_id": "6f0c1e3a-1111-4222-8333-944455556666",
        "session_id": "sesn_test",
        "agent": "coordinator",
        "event_type": "agent.custom_tool_use",
    }

    with structlog.contextvars.bound_contextvars(**bound):
        rates = await converter.prefetch([("USD", TODAY), ("GBP", TODAY)])

    assert set(rates.missing) == {("USD", TODAY), ("GBP", TODAY)}
    unavailable = [entry for entry in capture.entries if entry["event"] == "fx_rate_unavailable"]
    assert len(unavailable) == 2
    assert capture.entries
    for entry in capture.entries:
        assert {key: entry[key] for key in PLAN_LOG_KEYS} == bound, entry["event"]


async def test_a_source_that_hangs_is_cut_at_its_deadline(
    router: respx.MockRouter, converter: FxConverter, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(fx, "SOURCE_DEADLINE_SECONDS", 0.05)

    async def hang(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(5)
        return httpx.Response(200)

    router.get(BDI_URL).mock(side_effect=hang)
    router.get(INFOREURO_URL).mock(return_value=json_reply(INFOREURO_OCTOBER))

    quote = await converter.quote("USD", TODAY)

    assert quote.source == "inforeuro_monthly"
