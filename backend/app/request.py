"""The trip request: the body of POST /plans, and the source of the web form.

`python -m app.schemas` exports `PlanRequest` as schema/request.json; the frontend builds and
validates its form from that file, so the two never diverge. Field descriptions are English
(they document the contract); the Italian labels live in the web app.

Rules checked on top of the field constraints ("Contratto del piano"):

- a destination, or `suggest_destination`, exactly one of them; `destination_idea` is used
  only with `suggest_destination` and otherwise dropped (the form hides the field, so a value
  left over from switching "Suggeriscimi tu" off is not an error);
- fixed dates (`exact_start` + `exact_end`, end on or after start: a day trip has 0 nights) or
  flexible dates (`month` + `nights`, at least one night), never both; the trip lasts at most
  120 days;
- dates in the future: `exact_start` after today, `month` this month or later (Europe/Rome);
- every child has an age, adults have none; at least one adult travels;
- no text carries a control character other than tab, line feed or carriage return
  (`plan.ContractModel`).

Errors have stable `type` codes (`RequestErrorCode`, also listed in the schema under
`x-error-codes`) and the location of the field to highlight, so the frontend can map each one
to an Italian message. A request read back from the database is validated with
`PlanRequest.from_stored()`, which skips the "in the future" checks: its dates were in the
future when it was submitted.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Mapping
from enum import StrEnum
from typing import Any, Literal, Self

from pydantic import (
    ConfigDict,
    Field,
    PositiveInt,
    ValidationInfo,
    field_validator,
    model_validator,
)

from app import clock
from app.plan import MAX_TRIP_DAYS, ContractModel, Problems

ALLOW_PAST_DATES = "allow_past_dates"
"""Validation context key: `{ALLOW_PAST_DATES: True}` skips the "dates in the future" checks."""


class RequestErrorCode(StrEnum):
    """Stable error types of PlanRequest's own rules (pydantic's built-in types also apply)."""

    DESTINATION_REQUIRED = "destination_required"
    DESTINATION_CONFLICT = "destination_conflict"
    ADULT_REQUIRED = "adult_required"
    CHILD_AGE_REQUIRED = "child_age_required"
    ADULT_AGE_NOT_ALLOWED = "adult_age_not_allowed"
    DATES_REQUIRED = "dates_required"
    DATES_CONFLICT = "dates_conflict"
    EXACT_START_REQUIRED = "exact_start_required"
    EXACT_END_REQUIRED = "exact_end_required"
    END_BEFORE_START = "end_before_start"
    START_NOT_IN_FUTURE = "start_not_in_future"
    MONTH_REQUIRED = "month_required"
    NIGHTS_REQUIRED = "nights_required"
    INVALID_MONTH = "invalid_month"
    MONTH_IN_PAST = "month_in_past"
    TRIP_TOO_LONG = "trip_too_long"


# English message templates; `{name}` fields come from the error's context (`ctx`).
REQUEST_ERRORS: dict[RequestErrorCode, str] = {
    RequestErrorCode.DESTINATION_REQUIRED: (
        "give a destination, or set suggest_destination to let the planner choose"
    ),
    RequestErrorCode.DESTINATION_CONFLICT: (
        "give either a destination or suggest_destination, not both"
    ),
    RequestErrorCode.ADULT_REQUIRED: "at least one adult must travel",
    RequestErrorCode.CHILD_AGE_REQUIRED: "a child needs an age (0-17)",
    RequestErrorCode.ADULT_AGE_NOT_ALLOWED: "age is only for children; leave it empty for adults",
    RequestErrorCode.DATES_REQUIRED: (
        "choose fixed dates (exact_start and exact_end) or flexible dates (month and nights)"
    ),
    RequestErrorCode.DATES_CONFLICT: (
        "choose either fixed dates (exact_start, exact_end) or flexible dates (month, nights), "
        "not both"
    ),
    RequestErrorCode.EXACT_START_REQUIRED: "exact_start is required with exact_end",
    RequestErrorCode.EXACT_END_REQUIRED: "exact_end is required with exact_start",
    RequestErrorCode.END_BEFORE_START: (
        "exact_end ({exact_end}) must be on or after exact_start ({exact_start})"
    ),
    RequestErrorCode.START_NOT_IN_FUTURE: (
        "exact_start ({exact_start}) must be after today ({today})"
    ),
    RequestErrorCode.MONTH_REQUIRED: "month is required with nights",
    RequestErrorCode.NIGHTS_REQUIRED: "nights is required with month",
    RequestErrorCode.INVALID_MONTH: "month '{month}' is not a month: use YYYY-MM with MM 01-12",
    RequestErrorCode.MONTH_IN_PAST: "month {month} is in the past: choose {current_month} or later",
    RequestErrorCode.TRIP_TOO_LONG: (
        "the trip can last at most {max_days} days ({max_nights} nights), got {nights} nights"
    ),
}

MAX_NIGHTS = MAX_TRIP_DAYS - 1


def _add(
    problems: Problems, loc: tuple[str, ...], code: RequestErrorCode, value: Any, **ctx: Any
) -> None:
    problems.add(loc, code.value, REQUEST_ERRORS[code], value, **ctx)


def _future_dates_required(info: ValidationInfo) -> bool:
    context = info.context
    return not (isinstance(context, Mapping) and context.get(ALLOW_PAST_DATES))


class Traveler(ContractModel):
    """One person in the party."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["adult", "child"] = Field(description="adult, or child (under 18).")
    age: int | None = Field(
        default=None,
        ge=0,
        le=17,
        description="Age in years, required for a child (0-17); empty for an adult.",
    )

    @model_validator(mode="before")
    @classmethod
    def _no_age_for_adults(cls, data: Any) -> Any:
        if not isinstance(data, Mapping):
            return data
        age = data.get("age")
        if age == "":
            data = {**data, "age": None}
            age = None
        if data.get("kind") == "adult" and age is not None:
            problems = Problems(cls.__name__)
            _add(problems, ("age",), RequestErrorCode.ADULT_AGE_NOT_ALLOWED, age)
            problems.raise_if_any()
        return data

    @model_validator(mode="after")
    def _age_for_children(self) -> Self:
        if self.kind == "child" and self.age is None:
            problems = Problems(type(self).__name__)
            _add(problems, ("age",), RequestErrorCode.CHILD_AGE_REQUIRED, None)
            problems.raise_if_any()
        return self


class DateWindow(ContractModel):
    """When to travel: fixed dates, or a month and a number of nights."""

    exact_start: dt.date | None = Field(
        default=None,
        description=(
            "Fixed dates: first day of the trip, YYYY-MM-DD, after today. Set with exact_end; "
            "leave month and nights empty."
        ),
    )
    exact_end: dt.date | None = Field(
        default=None,
        description=(
            "Fixed dates: last day of the trip, YYYY-MM-DD, on or after exact_start (the same "
            "day for a day trip)."
        ),
    )
    month: str | None = Field(
        default=None,
        pattern=r"^\d{4}-\d{2}$",
        description=(
            "Flexible dates: the month to leave in, YYYY-MM (e.g. '2026-11'), this month or "
            "later. Set with nights; leave exact_start and exact_end empty."
        ),
    )
    nights: PositiveInt | None = Field(
        default=None,
        description=f"Flexible dates: number of nights, 1 to {MAX_NIGHTS}. Set with month.",
    )

    @field_validator("month", mode="before")
    @classmethod
    def _blank_month_is_missing(cls, value: Any) -> Any:
        return None if isinstance(value, str) and not value.strip() else value

    @property
    def is_exact(self) -> bool:
        """True for fixed dates, False for a month and a number of nights."""
        return self.exact_start is not None

    @model_validator(mode="after")
    def _check_window(self, info: ValidationInfo) -> Self:
        problems = Problems(type(self).__name__)
        exact = self.exact_start is not None or self.exact_end is not None
        flexible = self.month is not None or self.nights is not None
        if exact and flexible:
            _add(problems, (), RequestErrorCode.DATES_CONFLICT, None)
        elif not exact and not flexible:
            _add(problems, (), RequestErrorCode.DATES_REQUIRED, None)
        elif exact:
            self._check_exact(problems, future=_future_dates_required(info))
        else:
            self._check_flexible(problems, future=_future_dates_required(info))
        problems.raise_if_any()
        return self

    def _check_exact(self, problems: Problems, *, future: bool) -> None:
        start, end = self.exact_start, self.exact_end
        if start is None:
            _add(problems, ("exact_start",), RequestErrorCode.EXACT_START_REQUIRED, None)
        if end is None:
            _add(problems, ("exact_end",), RequestErrorCode.EXACT_END_REQUIRED, None)
        if future and start is not None and start <= (today := clock.today()):
            _add(
                problems,
                ("exact_start",),
                RequestErrorCode.START_NOT_IN_FUTURE,
                start,
                exact_start=start,
                today=today,
            )
        if start is None or end is None:
            return
        nights = (end - start).days
        if nights < 0:
            _add(
                problems,
                ("exact_end",),
                RequestErrorCode.END_BEFORE_START,
                end,
                exact_start=start,
                exact_end=end,
            )
        elif nights > MAX_NIGHTS:
            _add(
                problems,
                ("exact_end",),
                RequestErrorCode.TRIP_TOO_LONG,
                end,
                max_days=MAX_TRIP_DAYS,
                max_nights=MAX_NIGHTS,
                nights=nights,
            )

    def _check_flexible(self, problems: Problems, *, future: bool) -> None:
        if self.month is None:
            _add(problems, ("month",), RequestErrorCode.MONTH_REQUIRED, None)
        elif not self.month.isascii() or not 1 <= int(self.month[5:]) <= 12:
            _add(problems, ("month",), RequestErrorCode.INVALID_MONTH, self.month, month=self.month)
        elif future and self.month < (current := clock.current_month()):
            _add(
                problems,
                ("month",),
                RequestErrorCode.MONTH_IN_PAST,
                self.month,
                month=self.month,
                current_month=current,
            )
        if self.nights is None:
            _add(problems, ("nights",), RequestErrorCode.NIGHTS_REQUIRED, None)
        elif self.nights > MAX_NIGHTS:
            _add(
                problems,
                ("nights",),
                RequestErrorCode.TRIP_TOO_LONG,
                self.nights,
                max_days=MAX_TRIP_DAYS,
                max_nights=MAX_NIGHTS,
                nights=self.nights,
            )


class PlanRequest(ContractModel):
    """A trip request: where from, where to (or "suggest one"), when, who, and the budget."""

    model_config = ConfigDict(
        json_schema_extra={
            "x-error-codes": {code.value: message for code, message in REQUEST_ERRORS.items()}
        },
    )

    origin: str = Field(
        min_length=1,
        max_length=200,
        description="Where the trip starts: a city or an IATA airport code, e.g. 'Milano', 'MXP'.",
    )
    destination: str | None = Field(
        default=None,
        max_length=200,
        description=(
            "Where to go: a city, region or country. Empty when suggest_destination is true."
        ),
    )
    suggest_destination: bool = Field(
        default=False,
        description=(
            "True to let the planner choose the destination (up to three candidates, with "
            "reasons); destination must then be empty."
        ),
    )
    destination_idea: str | None = Field(
        default=None,
        max_length=500,
        description=(
            "Only with suggest_destination: what the trip should be like, e.g. "
            "'mare a novembre, volo diretto'. Ignored (dropped) when suggest_destination is "
            "false."
        ),
    )
    dates: DateWindow = Field(description="Fixed dates, or a month and a number of nights.")
    travelers: list[Traveler] = Field(
        min_length=1,
        max_length=9,
        description="Everyone travelling (1-9 people): at least one adult; children with age.",
    )
    budget_eur: PositiveInt = Field(
        description="Total budget in whole euro for the whole party: travel, lodging, activities.",
    )
    preferences: str | None = Field(
        default=None,
        max_length=2000,
        description="Free-text preferences, e.g. 'niente voli prima delle 8, cucina locale'.",
    )

    @field_validator("destination", "destination_idea", "preferences", mode="before")
    @classmethod
    def _blank_is_missing(cls, value: Any) -> Any:
        return None if isinstance(value, str) and not value.strip() else value

    @model_validator(mode="after")
    def _check_request(self) -> Self:
        problems = Problems(type(self).__name__)
        if self.destination is not None and self.suggest_destination:
            _add(
                problems,
                ("destination",),
                RequestErrorCode.DESTINATION_CONFLICT,
                self.destination,
            )
        elif self.destination is None and not self.suggest_destination:
            _add(problems, ("destination",), RequestErrorCode.DESTINATION_REQUIRED, None)
        if not self.suggest_destination:
            # A leftover from the hidden form field: the idea only steers a suggestion.
            self.destination_idea = None
        if not any(traveler.kind == "adult" for traveler in self.travelers):
            _add(problems, ("travelers",), RequestErrorCode.ADULT_REQUIRED, None)
        problems.raise_if_any()
        return self

    @classmethod
    def from_stored(cls, data: Mapping[str, Any]) -> Self:
        """Validate a request read back from `plans.request`, without the "in the future"
        checks: its dates were in the future when it was submitted."""
        return cls.model_validate(data, context={ALLOW_PAST_DATES: True})

    @property
    def adults(self) -> int:
        return sum(1 for traveler in self.travelers if traveler.kind == "adult")

    @property
    def child_ages(self) -> list[int]:
        return [t.age for t in self.travelers if t.kind == "child" and t.age is not None]
