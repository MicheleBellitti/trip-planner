"""The ask_traveller contract (app/choices.py): input validation, admission limits, the tool
answers sent to the coordinator and the timeline titles."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from app.choices import (
    NO_MORE_QUESTIONS_TEXT,
    ONE_QUESTION_AT_A_TIME_TEXT,
    ChoiceAnswer,
    ChoiceRejected,
    ChoiceRequest,
    admission_refusal,
    answer_text,
    answered_title,
    asked_title,
    auto_pick,
    parse_choice_request,
    selection_problem,
)

OPTIONS: list[dict[str, Any]] = [
    {
        "id": "a1",
        "title": "Torre di Belém",
        "reason": "Il simbolo della città.",
        "duration_min": 90,
    },
    {
        "id": "a2",
        "title": "Castelo de São Jorge",
        "reason": "Vista su tutta Lisbona.",
        "price": {"amount_cents": 1500, "currency": "EUR"},
        "area": "Alfama",
        "place": "R. de Santa Cruz do Castelo, Lisboa",
    },
    {"id": "a3", "title": "Alfama e i miradouros", "reason": "Si gira a piedi."},
    {"id": "a4", "title": "LX Factory", "reason": "Negozi e caffè."},
]

JOURNEY_OPTIONS: list[dict[str, Any]] = [
    {"id": "c1", "title": "Volo", "reason": "Il più veloce."},
    {"id": "c2", "title": "Treno", "reason": "Dal centro al centro."},
]


def request_data(**change: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "kind": "activities",
        "question": "Cosa vuoi vedere a Lisbona?",
        "multiple": True,
        "options": OPTIONS,
    }
    return data | change


def make(**change: Any) -> ChoiceRequest:
    return ChoiceRequest.model_validate(request_data(**change))


def make_with(kind: str, options: list[dict[str, Any]], *, multiple: bool) -> ChoiceRequest:
    return make(kind=kind, options=options, multiple=multiple)


ACTIVITIES = make()
FOOD = make(kind="food", options=OPTIONS[:2])
JOURNEY = make_with("journey", JOURNEY_OPTIONS, multiple=False)
DESTINATION = make_with("destination", JOURNEY_OPTIONS, multiple=False)
OTHER = make_with("other", JOURNEY_OPTIONS, multiple=False)


def test_a_valid_activities_request_parses() -> None:
    parsed = parse_choice_request(request_data())

    assert isinstance(parsed, ChoiceRequest)
    assert parsed.kind == "activities"
    assert parsed.multiple is True
    assert [option.id for option in parsed.options] == ["a1", "a2", "a3", "a4"]
    assert parsed.options[1].price is not None
    assert parsed.options[1].price.currency == "EUR"


@pytest.mark.parametrize(
    ("change", "path"),
    [
        ({"multiple": False}, ()),
        ({"kind": "journey"}, ()),
        ({"options": OPTIONS[:2]}, ("options",)),
        ({"options": [*OPTIONS, *OPTIONS[:3]]}, ("options",)),
        ({"options": [OPTIONS[0], OPTIONS[0], OPTIONS[1]]}, ()),
        ({"question": "x" * 121}, ("question",)),
        ({"options": [{**OPTIONS[0], "id": "bad id"}, *OPTIONS[1:]]}, ("options", 0, "id")),
        ({"options": [{**OPTIONS[0], "duration_min": 1441}, *OPTIONS[1:]]}, ("options", 0)),
        ({"options": [{**OPTIONS[0], "reason": "a\nb"}, *OPTIONS[1:]]}, ("options", 0, "reason")),
        ({"options": [{**OPTIONS[0], "title": "x" * 81}, *OPTIONS[1:]]}, ("options", 0, "title")),
        ({"options": [{**OPTIONS[0], "title": "a\nb"}, *OPTIONS[1:]]}, ("options", 0, "title")),
        ({"options": [{**OPTIONS[0], "area": "a\nb"}, *OPTIONS[1:]]}, ("options", 0, "area")),
        ({"options": [{**OPTIONS[0], "place": "a\rb"}, *OPTIONS[1:]]}, ("options", 0, "place")),
        ({"unknown": 1}, ("unknown",)),
    ],
)
def test_invalid_requests_are_rejected(change: dict[str, Any], path: tuple[Any, ...]) -> None:
    with pytest.raises(ValidationError) as caught:
        ChoiceRequest.model_validate(request_data(**change))

    locations = [tuple(error["loc"]) for error in caught.value.errors()]
    assert any(location[: len(path)] == path for location in locations), locations
    if not path:
        assert () in locations


def test_journey_needs_two_options_and_one_pick() -> None:
    with pytest.raises(ValidationError):
        make_with("journey", JOURNEY_OPTIONS[:1], multiple=False)
    assert make_with("food", JOURNEY_OPTIONS, multiple=True).multiple is True


@pytest.mark.parametrize("text", ["vedi https://x.pt", "www.visitlisboa.com", "ftp://a"])
@pytest.mark.parametrize("where", ["question", "reason", "title", "area", "place"])
def test_no_url_anywhere(text: str, where: str) -> None:
    if where == "question":
        data = request_data(question=text)
    else:
        first = {**OPTIONS[0], where: text}
        data = request_data(options=[first, *OPTIONS[1:]])

    assert isinstance(parse_choice_request(data), ChoiceRejected)


def test_parse_choice_request_message() -> None:
    rejected = parse_choice_request({"kind": "food"})

    assert isinstance(rejected, ChoiceRejected)
    assert rejected.message.startswith("ask_traveller rejected: ")
    assert "validation error(s). Nothing was shown to the traveller." in rejected.message
    assert rejected.message.splitlines()[0].endswith("Fix every one and call ask_traveller again.")
    assert rejected.errors
    assert rejected.message.splitlines()[1:] == [f"- {line}" for line in rejected.errors]
    assert rejected.message.startswith(f"ask_traveller rejected: {len(rejected.errors)} ")


def test_parse_choice_request_rejects_a_non_object() -> None:
    assert isinstance(parse_choice_request("food"), ChoiceRejected)
    assert isinstance(parse_choice_request(None), ChoiceRejected)


@pytest.mark.parametrize(
    ("kind", "asked", "accepted", "another_open", "reason"),
    [
        ("food", ["activities"], False, False, None),
        ("other", ["activities", "food"], False, False, None),
        ("destination", ["activities", "food", "other"], False, False, "limit"),
        ("food", ["food"], False, False, "same_kind"),
        ("journey", ["destination"], False, False, "shared_slot"),
        ("food", [], True, False, "accepted"),
        # One question at a time, checked before the limits.
        ("food", ["activities"], False, True, "open"),
        ("destination", ["activities", "food", "other"], False, True, "open"),
        ("food", ["food"], False, True, "open"),
        ("journey", ["destination"], False, True, "open"),
        ("food", [], True, True, "accepted"),
    ],
)
def test_admission_refusal(
    kind: Any, asked: list[str], accepted: bool, another_open: bool, reason: str | None
) -> None:
    assert admission_refusal(kind, asked, accepted=accepted, another_open=another_open) == reason


def test_answer_texts_are_the_spec_s() -> None:
    assert answer_text(ACTIVITIES, "traveller", ["a3", "a1"]) == (
        'The traveller chose: a1 "Torre di Belém", a3 "Alfama e i miradouros". Build the plan '
        "around these and drop the other options you offered."
    )
    assert answer_text(JOURNEY, "traveller", ["c2"]) == (
        'The traveller chose: c2 "Treno". Build the plan around it and drop the other options '
        "you offered."
    )
    let_choose = (
        "The traveller let you choose. Pick what fits the request best and go on; do not "
        "mention it in the warnings."
    )
    assert answer_text(FOOD, "timeout", []) == answer_text(FOOD, "skip", []) == let_choose
    assert answer_text(OTHER, "skip", []) == let_choose
    assert (
        answer_text(JOURNEY, "skip", [])
        == answer_text(JOURNEY, "timeout", [])
        == (
            "The traveller did not choose a mode. Take the most sensible one and say so in one "
            "warning line."
        )
    )
    assert (
        answer_text(DESTINATION, "skip", [])
        == answer_text(DESTINATION, "timeout", [])
        == ("The traveller let you choose. Take your leading candidate and go on.")
    )
    assert NO_MORE_QUESTIONS_TEXT == "No more questions: choose yourself."
    assert ONE_QUESTION_AT_A_TIME_TEXT == (
        "One question at a time: the traveller has not answered your open question yet. Ask "
        "again after the answer."
    )


def test_selection_problem() -> None:
    assert selection_problem(ACTIVITIES, ["a3", "a1"]) is None
    assert selection_problem(ACTIVITIES, ["a1", "zz"]) == "unknown_option"
    assert selection_problem(ACTIVITIES, ["a1", "a1"]) == "duplicate"
    assert selection_problem(JOURNEY, ["c1"]) is None
    assert selection_problem(JOURNEY, ["c1", "c2"]) == "single_choice"
    assert selection_problem(JOURNEY, []) == "single_choice"


def test_choice_answer_needs_exactly_one_of_selected_or_skip() -> None:
    assert ChoiceAnswer(selected=["a1"]).skip is False
    assert ChoiceAnswer(skip=True).selected is None
    for body in (
        {},
        {"skip": False},
        {"selected": ["a1"], "skip": True},
        {"selected": []},
        {"selected": ["a"] * 7},
        {"selected": ["a1"], "extra": 1},
    ):
        with pytest.raises(ValidationError):
            ChoiceAnswer.model_validate(body)


def test_auto_pick() -> None:
    assert auto_pick(ACTIVITIES) == ["a1", "a2"]
    assert auto_pick(JOURNEY) == ["c1"]


def test_titles() -> None:
    assert asked_title("destination") == "Tocca a te: scegli la destinazione"
    assert asked_title("journey") == "Tocca a te: scegli come viaggiare"
    assert asked_title("activities") == "Tocca a te: scegli cosa vedere"
    assert asked_title("food") == "Tocca a te: scegli cosa mangiare"
    assert asked_title("other") == "Tocca a te: scegli tra le opzioni"
    assert answered_title(ACTIVITIES, "traveller", ["a3", "a1"]) == (
        "Hai scelto: Torre di Belém, Alfama e i miradouros"
    )
    assert answered_title(FOOD, "skip", []) == "Hai lasciato scegliere ad Atlas"
    assert answered_title(FOOD, "timeout", []) == "Tempo scaduto: sceglie Atlas"
    assert answered_title(FOOD, "closed", []) == "Domanda chiusa: piano interrotto"
