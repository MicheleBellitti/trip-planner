"""JSON Schema export (app/schemas.py): the committed schema/ files match the models, the
submit_plan input_schema is self-contained, and real instances validate against every file."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator

from app import schemas
from app.events import UIEvent
from app.plan import Plan
from app.request import PlanRequest
from app.schemas import (
    SCHEMA_DIR,
    SCHEMAS,
    build_all,
    check_self_contained,
    iter_refs,
    main,
    plan_input_schema,
    render,
    stale_files,
    unexpected_files,
)
from tests.test_plan import make_plan
from tests.test_request import make_request
from tests.test_results import envelope
from tests.test_ui_event import make_event

BACKEND_DIR = Path(__file__).resolve().parents[1]

EXPECTED_FILES = {
    "plan.json",
    "request.json",
    "ui_event.json",
    "results/flights.json",
    "results/lodging.json",
    "results/activities.json",
    "results/transport.json",
}


def load(name: str) -> dict[str, Any]:
    return json.loads((SCHEMA_DIR / name).read_text(encoding="utf-8"))


def validator(name: str) -> Draft202012Validator:
    return Draft202012Validator(load(name))


def iter_properties(node: Any, path: str = "") -> Any:
    """(path, property schema) for every object property in a schema, $defs included."""
    if isinstance(node, dict):
        for key, value in node.get("properties", {}).items():
            yield f"{path}.{key}", value
        for key, value in node.items():
            if key != "properties":
                yield from iter_properties(value, f"{path}/{key}")
    elif isinstance(node, list):
        for index, item in enumerate(node):
            yield from iter_properties(item, f"{path}[{index}]")


# --- the committed files -------------------------------------------------------------------


def test_exported_files_are_the_expected_set() -> None:
    assert set(SCHEMAS) == EXPECTED_FILES


def test_committed_schemas_are_up_to_date() -> None:
    assert stale_files() == [], "run `uv run python -m app.schemas` from backend/"
    assert unexpected_files() == []


def test_check_flag_passes_on_the_repository() -> None:
    completed = subprocess.run(
        [sys.executable, "-m", "app.schemas", "--check"],
        cwd=BACKEND_DIR,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert "up to date (7 schemas)" in completed.stdout


@pytest.mark.parametrize("name", sorted(EXPECTED_FILES))
def test_every_file_is_a_valid_draft_2020_12_schema(name: str) -> None:
    Draft202012Validator.check_schema(load(name))


@pytest.mark.parametrize("name", sorted(EXPECTED_FILES))
def test_every_property_is_described(name: str) -> None:
    undocumented = [
        path for path, prop in iter_properties(load(name)) if not prop.get("description")
    ]

    assert undocumented == []


@pytest.mark.parametrize("name", sorted(EXPECTED_FILES))
def test_field_titles_are_omitted(name: str) -> None:
    titled = [path for path, prop in iter_properties(load(name)) if "title" in prop]

    assert titled == []


# --- determinism ---------------------------------------------------------------------------


def test_output_is_deterministic() -> None:
    first, second = build_all(), build_all()

    assert first == second
    for name, content in first.items():
        assert content.endswith("}\n"), name
        assert not content.endswith("\n\n"), name
        assert (
            content
            == json.dumps(json.loads(content), indent=2, sort_keys=True, ensure_ascii=False) + "\n"
        )


def test_render_sorts_keys_and_keeps_unicode() -> None:
    assert render({"b": 1, "a": "→"}) == '{\n  "a": "→",\n  "b": 1\n}\n'


# --- plan.json as the submit_plan input_schema ---------------------------------------------


def test_plan_schema_is_a_self_contained_object() -> None:
    schema = load("plan.json")

    assert schema["type"] == "object"
    assert schema["title"] == "Plan"
    assert schema["description"].startswith("The final trip plan, the input of submit_plan.")
    assert schema["additionalProperties"] is False
    refs = set(iter_refs(schema))
    assert refs == {f"#/$defs/{name}" for name in ("PlanDay", "PlanStop", "PlanBooking", "Price")}
    check_self_contained(schema)
    assert "$schema" not in schema
    assert "$id" not in schema


def test_plan_schema_matches_the_model() -> None:
    assert load("plan.json") == json.loads(render(plan_input_schema()))
    assert set(load("plan.json")["properties"]) == set(Plan.model_fields)


def test_plan_schema_keeps_the_contract_constraints() -> None:
    schema = load("plan.json")
    stop = schema["$defs"]["PlanStop"]["properties"]
    booking = schema["$defs"]["PlanBooking"]["properties"]
    price = schema["$defs"]["Price"]["properties"]

    assert schema["properties"]["days"]["maxItems"] == 120
    assert schema["properties"]["title"]["maxLength"] == 120
    assert stop["start_time"]["anyOf"][0]["pattern"] == r"^([01]\d|2[0-3]):[0-5]\d$"
    assert stop["kind"]["enum"] == ["activity", "meal", "transfer", "rest"]
    assert booking["book_by"]["anyOf"][0] == {"format": "date-time", "type": "string"}
    assert price["currency"]["pattern"] == "^[A-Z]{3}$"
    assert price["status"]["enum"] == ["verified", "estimated"]
    assert set(schema["required"]) == {
        "title",
        "destination",
        "timezone",
        "start_date",
        "end_date",
        "travelers",
        "days",
        "bookings",
        "summary",
    }


def test_check_self_contained_rejects_external_and_dangling_refs() -> None:
    with pytest.raises(ValueError, match="non-local"):
        check_self_contained({"properties": {"a": {"$ref": "schema/price.json"}}})
    with pytest.raises(ValueError, match="no matching entry"):
        check_self_contained({"$defs": {}, "properties": {"a": {"$ref": "#/$defs/Price"}}})
    check_self_contained({"$defs": {"Price": {}}, "items": [{"$ref": "#/$defs/Price"}]})


def test_plan_input_schema_requires_an_object(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(schemas, "model_schema", lambda *_args, **_kwargs: {"type": "array"})

    with pytest.raises(ValueError, match="must describe an object"):
        plan_input_schema()


# --- instances validate against the exported files -----------------------------------------


def test_a_valid_plan_matches_plan_json() -> None:
    plan = Plan.model_validate(make_plan())

    validator("plan.json").validate(make_plan())
    validator("plan.json").validate(plan.model_dump(mode="json"))


def test_plan_json_rejects_what_the_model_rejects() -> None:
    check = validator("plan.json")

    assert not check.is_valid(make_plan(title="x" * 121))
    assert not check.is_valid(make_plan(unexpected=True))
    data = make_plan()
    data["days"][0]["stops"][0]["start_time"] = "7:05"
    assert not check.is_valid(data)
    data = make_plan()
    data["bookings"][0]["kind"] = "flight"
    assert not check.is_valid(data)


def test_a_valid_request_matches_request_json() -> None:
    check = validator("request.json")

    check.validate(make_request())
    check.validate(make_request(destination=None, suggest_destination=True))
    assert not check.is_valid(make_request(travelers=[]))
    assert not check.is_valid(make_request(dates={"month": "2026-1", "nights": 3}))


def test_request_json_lists_the_error_codes() -> None:
    assert load("request.json")["x-error-codes"] == PlanRequest.model_json_schema()["x-error-codes"]


@pytest.mark.parametrize("agent", ["flights", "lodging", "activities", "transport"])
def test_a_valid_result_matches_its_schema(agent: str) -> None:
    check = validator(f"results/{agent}.json")

    check.validate(envelope(agent))
    assert not check.is_valid(envelope(agent, version=0))
    assert not check.is_valid({**envelope(agent), "agent": "coordinator"})


def test_transport_schema_uses_from_and_to() -> None:
    transfer = load("results/transport.json")["$defs"]["TransferOption"]

    assert {"from", "to"} <= set(transfer["required"])
    assert "from_" not in transfer["properties"]


def test_a_valid_event_matches_ui_event_json() -> None:
    check = validator("ui_event.json")
    event = UIEvent.model_validate(make_event(detail=None, cost_cents=None))

    check.validate(event.model_dump(mode="json"))
    assert not check.is_valid(make_event(title="a\nb"))
    assert not check.is_valid(make_event(agent="planner"))
    # What the server sends always carries every key, so the browser can rely on them.
    assert set(load("ui_event.json")["required"]) == set(UIEvent.model_fields)


# --- the command line ----------------------------------------------------------------------


def test_main_writes_then_checks(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--check", "--out-dir", str(tmp_path)]) == 1
    assert "stale or missing" in capsys.readouterr().err

    assert main(["--out-dir", str(tmp_path)]) == 0
    written = {p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*.json")}
    assert written == EXPECTED_FILES
    assert "wrote" in capsys.readouterr().out

    assert main(["--check", "--out-dir", str(tmp_path)]) == 0
    assert main(["--out-dir", str(tmp_path)]) == 0
    assert "is up to date" in capsys.readouterr().out


def test_check_detects_an_edited_file(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    main(["--out-dir", str(tmp_path)])
    target = tmp_path / "results" / "flights.json"
    target.write_text(target.read_text(encoding="utf-8").replace("TP827", "XX1"), encoding="utf-8")

    assert main(["--check", "--out-dir", str(tmp_path)]) == 1
    err = capsys.readouterr().err
    assert "flights.json" in err
    assert "uv run python -m app.schemas" in err


def test_check_detects_a_leftover_file(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    main(["--out-dir", str(tmp_path)])
    (tmp_path / "results" / "hotels.json").write_text("{}\n", encoding="utf-8")

    assert main(["--check", "--out-dir", str(tmp_path)]) == 1
    assert "not generated by app.schemas" in capsys.readouterr().err
    assert main(["--out-dir", str(tmp_path)]) == 0
    assert "warning" in capsys.readouterr().err


def test_writing_skips_unchanged_files(tmp_path: Path) -> None:
    main(["--out-dir", str(tmp_path)])
    plan = tmp_path / "plan.json"
    before = plan.stat().st_mtime_ns

    assert schemas.write_all(tmp_path) == []
    assert plan.stat().st_mtime_ns == before
