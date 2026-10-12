"""The booking-notes budget of mapping.py (module docstring, "Booking notes") is reachable.

`mapping.booking_notes` keeps every booking's notes within TripTracker's 4000 code points by
shortening the plan's notes, then cutting the two URLs to `NOTE_URL_KEEP` characters. That only
works if every other provenance line is bounded by the contract: this test sums the worst case
from the real caps and templates, so raising a cap (e.g. `MAX_REASON`) past the budget fails here
instead of costing the agent a submit attempt on a Trip that fails trip.json. The last tests run
the real `booking_notes` on a booking at every cap, so the arithmetic and the code agree.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

from app import mapping, plan
from app.fx import FxQuote
from app.links import check_link

LONGEST_AMOUNT = "1000000000,00"  # format_amount(plan.MAX_AMOUNT_CENTS): 10**11 cents
LONGEST_RATE = "1234567.123456789"  # generous: a Decimal rate as printed
LONGEST_DATE = "2026-10-12"
CURRENCY = "XXX"


def _cut_url() -> str:
    return "u" * mapping.NOTE_URL_KEEP + mapping.NOTE_ELLIPSIS


def worst_case_provenance_after_cuts() -> list[str]:
    source_label = max(mapping.FX_SOURCE_LABELS.values(), key=len)
    fx_line = max(
        mapping.NOTE_FX_CONVERTED.format(
            amount=LONGEST_AMOUNT,
            currency=CURRENCY,
            rate=LONGEST_RATE,
            source=source_label,
            date=LONGEST_DATE,
        ),
        mapping.NOTE_FX_MISSING.format(amount=LONGEST_AMOUNT, currency=CURRENCY),
        key=len,
    )
    return [
        max(mapping.NOTE_PRICE_VERIFIED, mapping.NOTE_PRICE_ESTIMATED, key=len),
        mapping.NOTE_PRICE_SOURCE.format(url=_cut_url()),
        mapping.NOTE_BOOK_BY_REASON.format(reason="r" * plan.MAX_REASON),
        fx_line,
        mapping.NOTE_UNCHECKED_LINK.format(url=_cut_url()),
        mapping.NOTE_BOOK_NOW,
    ]


def test_mapping_and_plan_share_the_notes_cap() -> None:
    assert mapping.MAX_NOTES == plan.MAX_NOTES == 4000


def test_provenance_lines_fit_the_notes_once_urls_are_cut() -> None:
    lines = worst_case_provenance_after_cuts()

    assert len("\n".join(lines)) <= mapping.MAX_NOTES


def test_a_cut_url_is_shorter_than_a_full_one() -> None:
    assert mapping.NOTE_URL_KEEP < plan.MAX_URL


def test_the_assumed_amount_is_the_real_longest_amount() -> None:
    assert mapping.format_amount(plan.MAX_AMOUNT_CENTS) == LONGEST_AMOUNT


def _booking_at_every_cap() -> plan.PlanBooking:
    def url(host: str) -> str:
        base = f"https://{host}/?q="
        return base + "u" * (plan.MAX_URL - len(base))

    return plan.PlanBooking.model_validate(
        {
            "title": "t" * plan.MAX_TITLE,
            "kind": "lodging",
            "vendor": "v" * plan.MAX_NAME,
            "book_by_reason": "r" * plan.MAX_REASON,
            "link": url("www.not-allowed.example"),
            "price": {
                "amount_cents": plan.MAX_AMOUNT_CENTS,
                "currency": CURRENCY,
                "status": "estimated",
                "source_url": url("www.prices.example"),
                "retrieved_at": "2026-10-12T09:00:00+02:00",
            },
            "notes": "n" * plan.MAX_NOTES,
        }
    )


def test_the_real_notes_of_a_booking_at_every_cap_fit() -> None:
    booking = _booking_at_every_cap()
    quote = FxQuote(
        CURRENCY, Decimal(LONGEST_RATE + "987654321"), dt.date(2026, 10, 1), "bdi_daily"
    )

    notes = mapping.booking_notes(
        booking, quote=quote, link=check_link(booking.link or ""), book_now=True
    )

    assert notes is not None
    assert len(notes) <= mapping.MAX_NOTES
    fx_line = next(line for line in notes.split("\n") if line.startswith("Prezzo originale"))
    assert len(fx_line) <= len(worst_case_provenance_after_cuts()[3])


def test_a_missing_conversion_also_fits() -> None:
    booking = _booking_at_every_cap()

    notes = mapping.booking_notes(
        booking, quote=None, link=check_link(booking.link or ""), book_now=True
    )

    assert notes is not None
    assert len(notes) <= mapping.MAX_NOTES
    assert mapping.NOTE_FX_MISSING.format(amount=LONGEST_AMOUNT, currency=CURRENCY) in notes
