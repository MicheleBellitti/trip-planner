"""The `ask_traveller` tool: the coordinator pauses the run to let the traveller choose.

Spec: docs/superpowers/specs/2026-10-18-plan-creation-ux-design.md §2 "The mechanism". Fact
from probe P14: a custom tool call keeps the session idle until its result arrives, and the
session resumed warm after 243 s (every cache write was a 5-minute write), so the answer must
come within the 5-minute prompt cache. On `user.interrupt` the platform closes the pending call
itself with an `is_error` result; the backend then closes the row as `closed`.

This module is the contract: the input model (its JSON Schema, schema/ask_traveller.json, is
the agent's documentation of the tool, so every field description states its rule), the
admission limits, the answers sent back to the coordinator (English) and the timeline titles
(Italian). Storage and queries come later in the module.
"""

from __future__ import annotations

import re
from collections.abc import Collection, Sequence
from dataclasses import dataclass
from typing import Any, Literal, Self, get_args

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator
from pydantic_core import PydanticCustomError

from app.events import SINGLE_LINE_PATTERN, one_line
from app.plan import MAX_AMOUNT_CENTS, ContractModel, describe_validation_errors

# ============================================================================================
# Contract: constants and types
# ============================================================================================

ASK_TRAVELLER_TOOL = "ask_traveller"

ChoiceKind = Literal["destination", "journey", "activities", "food", "other"]
AnsweredBy = Literal["traveller", "skip", "timeout", "closed"]

MULTIPLE_KINDS: frozenset[str] = frozenset({"activities", "food"})
"""Kinds where the traveller may pick several options (and `multiple` must be true)."""

SHARED_SLOT_KINDS: frozenset[str] = frozenset({"destination", "journey", "other"})
"""At most one of these per plan: they share the third pause."""

MAX_CHOICES_PER_PLAN = 3

MIN_OPTIONS = 2
MIN_ACTIVITY_OPTIONS = 3
MAX_OPTIONS = 6
MAX_QUESTION = 120
MAX_TITLE = 80
MAX_REASON = 140
MAX_AREA = 60
MAX_PLACE = 120
MAX_DURATION_MIN = 1440

OPTION_ID_PATTERN = r"^[A-Za-z0-9_-]{1,32}$"
CURRENCY_PATTERN = r"^[A-Z]{3}$"
URL_PATTERN = re.compile(r"(?i)\b(?:[a-z][a-z0-9+.-]*://|www\.)")


class ChoicePrice(ContractModel):
    """What an option costs, for the whole party."""

    amount_cents: int = Field(
        ge=0,
        le=MAX_AMOUNT_CENTS,
        description=(
            "Total amount times 100, as an integer, for the whole party: 12.50 EUR is 1250."
        ),
    )
    currency: str = Field(
        pattern=CURRENCY_PATTERN,
        description="ISO 4217 currency code in upper case, e.g. EUR, USD, GBP.",
    )


class ChoiceOption(ContractModel):
    """One card the traveller can pick."""

    id: str = Field(
        pattern=OPTION_ID_PATTERN,
        description=(
            "Short identifier unique among the options: 1 to 32 letters, digits, '_' or '-', "
            "e.g. 'a1'. The answer refers to options by this id."
        ),
    )
    title: str = Field(
        min_length=1,
        max_length=MAX_TITLE,
        description="Name of the option, Italian, at most 80 characters, no URL.",
    )
    reason: str = Field(
        min_length=1,
        max_length=MAX_REASON,
        pattern=SINGLE_LINE_PATTERN,
        description=(
            "Why this option fits this traveller, Italian, one line, at most 140 characters, "
            "no URL."
        ),
    )
    duration_min: int | None = Field(
        default=None,
        ge=1,
        le=MAX_DURATION_MIN,
        description="Typical duration in minutes, 1 to 1440. Omit when it does not apply.",
    )
    price: ChoicePrice | None = Field(
        default=None,
        description="Indicative price for the whole party. Omit when unknown.",
    )
    area: str | None = Field(
        default=None,
        min_length=1,
        max_length=MAX_AREA,
        description="Neighbourhood or area, at most 60 characters, no URL. Omit when unknown.",
    )
    place: str | None = Field(
        default=None,
        min_length=1,
        max_length=MAX_PLACE,
        description=(
            "Name and address of the place, at most 120 characters, no URL, used to look up a "
            "photo. Omit when the option is not a place."
        ),
    )


class ChoiceRequest(ContractModel):
    """The input of `ask_traveller`: one question with 2 to 6 options."""

    kind: ChoiceKind = Field(
        description=(
            "What the question is about: 'destination', 'journey' (the travel mode), "
            "'activities', 'food' or 'other'. Each kind can be asked once per plan; "
            "'destination', 'journey' and 'other' share one slot."
        ),
    )
    question: str = Field(
        min_length=1,
        max_length=MAX_QUESTION,
        pattern=SINGLE_LINE_PATTERN,
        description="The question, Italian, one line, at most 120 characters, no URL.",
    )
    multiple: bool = Field(
        description=(
            "true for 'activities' and 'food' (the traveller may pick several), false "
            "otherwise (exactly one)."
        ),
    )
    options: list[ChoiceOption] = Field(
        min_length=MIN_OPTIONS,
        max_length=MAX_OPTIONS,
        description=(
            "2 to 6 options with unique ids; 'activities' needs at least 3. Offer only "
            "options you would put in the plan."
        ),
    )

    @field_validator("options")
    @classmethod
    def _activities_need_three(cls, options: list[ChoiceOption], info: Any) -> list[ChoiceOption]:
        if info.data.get("kind") == "activities" and len(options) < MIN_ACTIVITY_OPTIONS:
            msg = f"'activities' needs at least {MIN_ACTIVITY_OPTIONS} options"
            raise PydanticCustomError("too_few_options", "{msg}", {"msg": msg})
        return options

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        if self.multiple != (self.kind in MULTIPLE_KINDS):
            expected = "true" if self.kind in MULTIPLE_KINDS else "false"
            msg = f"multiple must be {expected} for kind '{self.kind}'"
            raise PydanticCustomError("multiple_mismatch", "{msg}", {"msg": msg})
        ids = [option.id for option in self.options]
        repeated = sorted({value for value in ids if ids.count(value) > 1})
        if repeated:
            msg = f"option ids must be unique: {', '.join(repeated)} appear more than once"
            raise PydanticCustomError("duplicate_option_ids", "{msg}", {"msg": msg})
        for text in self._texts():
            if URL_PATTERN.search(text):
                msg = "no URL anywhere: write plain text only"
                raise PydanticCustomError("url_not_allowed", "{msg}", {"msg": msg})
        return self

    def _texts(self) -> list[str]:
        texts = [self.question]
        for option in self.options:
            texts += [option.title, option.reason]
            texts += [text for text in (option.area, option.place) if text]
        return texts


# ============================================================================================
# Contract: parsing and admission
# ============================================================================================

NO_MORE_QUESTIONS_TEXT = "No more questions: choose yourself."
"""The (`is_error`) answer to a call refused for a limit, or made once a plan is accepted."""


@dataclass(frozen=True, slots=True)
class ChoiceRejected:
    """An invalid call: `message` is the `is_error` tool result, `errors` the problem lines."""

    message: str
    errors: list[str]


def parse_choice_request(tool_input: Any) -> ChoiceRequest | ChoiceRejected:
    """Validate the tool input. Nothing is shown to the traveller for a rejected call."""
    try:
        return ChoiceRequest.model_validate(tool_input)
    except ValidationError as error:
        lines = describe_validation_errors(error)
        header = (
            f"ask_traveller rejected: {error.error_count()} validation error(s). Nothing was "
            "shown to the traveller. Fix every one and call ask_traveller again."
        )
        return ChoiceRejected(
            message="\n".join([header, *(f"- {line}" for line in lines)]), errors=lines
        )


def admission_refusal(kind: ChoiceKind, asked: Collection[str], *, accepted: bool) -> str | None:
    """Why a valid call cannot be shown, as the log reason, or None when it can.

    `asked` holds the kinds already asked in this plan; `accepted` is true once the plan was
    accepted. A refused call is not a pause: no row, nothing shown."""
    if accepted:
        return "accepted"
    if len(asked) >= MAX_CHOICES_PER_PLAN:
        return "limit"
    if kind in asked:
        return "same_kind"
    if kind in SHARED_SLOT_KINDS and any(other in SHARED_SLOT_KINDS for other in asked):
        return "shared_slot"
    return None


# ============================================================================================
# Contract: answers
# ============================================================================================


class ChoiceAnswer(BaseModel):
    """The body of the answer endpoint: the picked option ids, or `skip`."""

    model_config = ConfigDict(extra="forbid")

    selected: list[str] | None = Field(default=None, min_length=1, max_length=MAX_OPTIONS)
    skip: bool = False

    @model_validator(mode="after")
    def _exactly_one(self) -> Self:
        if (self.selected is None) == (not self.skip):
            msg = "give exactly one of selected and skip"
            raise ValueError(msg)
        return self


def selection_problem(request: ChoiceRequest, selected: Sequence[str]) -> str | None:
    """Why `selected` does not fit the request: "duplicate", "unknown_option" or
    "single_choice" (not exactly one pick when `multiple` is false); None when it does."""
    if len(set(selected)) != len(selected):
        return "duplicate"
    offered = {option.id for option in request.options}
    if any(value not in offered for value in selected):
        return "unknown_option"
    if not request.multiple and len(selected) != 1:
        return "single_choice"
    return None


def _picked(request: ChoiceRequest, selected: Sequence[str]) -> list[ChoiceOption]:
    """The picked options, in the order they were offered."""
    chosen = set(selected)
    return [option for option in request.options if option.id in chosen]


def answer_text(request: ChoiceRequest, answered_by: AnsweredBy, selected: Sequence[str]) -> str:
    """The tool result sent to the coordinator (English). `closed` is never sent: the platform
    closes the call itself; it reads like a skip."""
    if answered_by == "traveller":
        picks = _picked(request, selected)
        listed = ", ".join(f'{option.id} "{option.title}"' for option in picks)
        around = "it" if len(picks) == 1 else "these"
        return (
            f"The traveller chose: {listed}. Build the plan around {around} and drop the "
            "other options you offered."
        )
    if request.kind == "journey":
        return (
            "The traveller did not choose a mode. Take the most sensible one and say so in one "
            "warning line."
        )
    if request.kind == "destination":
        return "The traveller let you choose. Take your leading candidate and go on."
    return (
        "The traveller let you choose. Pick what fits the request best and go on; do not "
        "mention it in the warnings."
    )


def auto_pick(request: ChoiceRequest) -> list[str]:
    """What evals and the CLI pick: the first id, or the first two when `multiple`."""
    count = 2 if request.multiple else 1
    return [option.id for option in request.options[:count]]


# ============================================================================================
# Contract: timeline titles (Italian)
# ============================================================================================

_ASKED_TITLES: dict[str, str] = {
    "destination": "Tocca a te: scegli la destinazione",
    "journey": "Tocca a te: scegli come viaggiare",
    "activities": "Tocca a te: scegli cosa vedere",
    "food": "Tocca a te: scegli cosa mangiare",
    "other": "Tocca a te: scegli tra le opzioni",
}
assert set(_ASKED_TITLES) == set(get_args(ChoiceKind))

TOOL_USE_TITLE = "Domanda al viaggiatore"
"""The title of the raw `ask_traveller` tool use in the timeline."""


def asked_title(kind: ChoiceKind) -> str:
    return one_line(_ASKED_TITLES[kind])


def answered_title(request: ChoiceRequest, answered_by: AnsweredBy, selected: Sequence[str]) -> str:
    if answered_by == "traveller":
        titles = ", ".join(option.title for option in _picked(request, selected))
        return one_line(f"Hai scelto: {titles}")
    return {
        "skip": "Hai lasciato scegliere ad Atlas",
        "timeout": "Tempo scaduto: sceglie Atlas",
        "closed": "Domanda chiusa: piano interrotto",
    }[answered_by]
