"""Tests for write_result.py: envelope and option checks against the exported schemas, version and
updated_at handling, atomic replacement, and agreement with the backend's own validation
(backend/app/results.py), which re-checks every result file.

Offline, in a temporary results directory. Schemas come from the repository's schema/results/
(the files that scripts/render_profiles.py copies into this skill's schemas/ directory).

Run: cd backend && uv run pytest ../skills -q
"""

from __future__ import annotations

import copy
import datetime as dt
import importlib
import importlib.util
import io
import json
import os
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from pydantic import ValidationError

HERE = Path(__file__).resolve().parent
SCRIPT = HERE / "write_result.py"
REPO = HERE.parents[1]
BACKEND = REPO / "backend"
SCHEMAS = REPO / "schema" / "results"


def _load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("travel_rules_write_result", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _backend_results() -> ModuleType:
    if str(BACKEND) not in sys.path:
        sys.path.append(str(BACKEND))
    return importlib.import_module("app.results")


wr = _load_script()
RESULTS = _backend_results()
NOW = dt.datetime(2027, 3, 1, 9, 30, tzinfo=dt.timezone.utc)

PRICE = {
    "amount_cents": 48600,
    "currency": "EUR",
    "status": "verified",
    "source_url": "https://www.kiwi.com/en/search/results/milan-italy/edinburgh-united-kingdom/2027-05-13/2027-05-18",
    "retrieved_at": "2027-03-01T10:15:00+01:00",
}

SAMPLES: dict[str, dict[str, Any]] = {
    "flights": {
        "agent": "flights",
        "options": [
            {
                "id": "f1",
                "segments": [
                    {
                        "from_airport": "MXP",
                        "to_airport": "EDI",
                        "depart_at": "2027-05-13T07:10:00+02:00",
                        "arrive_at": "2027-05-13T08:50:00+01:00",
                        "carrier": "easyJet",
                        "flight_number": "U2 3127",
                    },
                    {
                        "from_airport": "EDI",
                        "to_airport": "MXP",
                        "depart_at": "2027-05-18T18:30:00+01:00",
                        "arrive_at": "2027-05-18T21:45:00+02:00",
                        "carrier": "easyJet",
                        "flight_number": "U23128",
                    },
                ],
                "stops": 0,
                "baggage_included": False,
                "price": PRICE,
                "link": None,
                "source": "kiwi",
            }
        ],
        "failures": [
            {
                "source": "expedia",
                "reason": "nessuna risposta dopo 30 secondi",
                "at": "2027-03-01T10:12:00+01:00",
            }
        ],
        "warnings": ["Expedia non ha risposto: i voli vengono da Kiwi.com."],
    },
    "lodging": {
        "agent": "lodging",
        "options": [
            {
                "id": "l1",
                "name": "Old Town Residence",
                "kind": "apartment",
                "address": "Blackfriars Street, Edinburgh EH1 1NB",
                "lat": 55.9497,
                "lon": -3.1858,
                "check_in": "2027-05-13",
                "check_out": "2027-05-18",
                "free_cancellation_until": "2027-05-06T23:59:00+01:00",
                "price": {
                    **PRICE,
                    "amount_cents": 114000,
                    "status": "estimated",
                    "source_url": "https://www.booking.com/searchresults.it.html?ss=Old%20Town",
                },
                "link": None,
                "source": "web",
            }
        ],
    },
    "activities": {
        "agent": "activities",
        "options": [
            {
                "id": "a1",
                "title": "Edinburgh Castle",
                "suggested_day": "2027-05-14",
                "start_time": "09:30",
                "duration_min": 120,
                "location_name": "Edinburgh Castle",
                "lat": 55.9486,
                "lon": -3.1999,
                "booking_required": True,
                "book_by": "2027-05-07T20:00:00+01:00",
                "price": {
                    **PRICE,
                    "amount_cents": 5580,
                    "currency": "GBP",
                    "status": "estimated",
                    "source_url": "https://www.edinburghcastle.scot/",
                },
                "link": "https://www.edinburghcastle.scot/",
            },
            {"id": "a2", "title": "Salita ad Arthur's Seat", "booking_required": False},
        ],
        "failures": [],
        "warnings": [],
    },
    "transport": {
        "agent": "transport",
        "options": [
            {
                "from": "Edinburgh Airport",
                "id": "t1",
                "to": "Old Town Residence",
                "mode": "tram",
                "depart_at": "2027-05-13T09:30:00+01:00",
                "arrive_at": "2027-05-13T10:05:00+01:00",
                "duration_min": 35,
                "price": {
                    **PRICE,
                    "amount_cents": 1880,
                    "currency": "GBP",
                    "status": "estimated",
                    "source_url": "https://edinburghtrams.com/",
                },
                "link": None,
            },
            {
                "id": "t2",
                "from": "Old Town Residence",
                "to": "Edinburgh Castle",
                "mode": "walk",
                "duration_min": 10,
            },
        ],
    },
}


def write(
    agent: str, data: Any, tmp_path: Path, **kwargs: Any
) -> tuple[Path, dict[str, Any], list[str]]:
    return wr.write_result(agent, data, results_dir=tmp_path, schema_dir=SCHEMAS, now=NOW, **kwargs)


# --- valid results --------------------------------------------------------------------------


@pytest.mark.parametrize("agent", sorted(SAMPLES))
def test_valid_result_is_written_and_accepted_by_the_backend(agent: str, tmp_path: Path) -> None:
    target, result, problems = write(agent, SAMPLES[agent], tmp_path)
    assert problems == []
    assert target == tmp_path / f"{agent}.json"
    stored = json.loads(target.read_text(encoding="utf-8"))
    assert stored == result
    assert stored["agent"] == agent
    assert stored["version"] == 1
    assert stored["updated_at"] == "2027-03-01T09:30:00+00:00"
    assert list(stored)[:3] == ["agent", "version", "updated_at"]
    RESULTS.parse_result(agent, target.read_text(encoding="utf-8"))  # the backend agrees


def test_version_grows_at_every_rewrite(tmp_path: Path) -> None:
    for expected in (1, 2, 3):
        _, result, problems = write("flights", SAMPLES["flights"], tmp_path)
        assert problems == []
        assert result["version"] == expected
    assert json.loads((tmp_path / "flights.json").read_text())["version"] == 3


def test_version_and_updated_at_in_the_input_are_replaced(tmp_path: Path) -> None:
    write("lodging", SAMPLES["lodging"], tmp_path)
    data = {**SAMPLES["lodging"], "version": 99, "updated_at": "2020-01-01T00:00:00+00:00"}
    _, result, problems = write("lodging", data, tmp_path)
    assert problems == []
    assert result["version"] == 2
    assert result["updated_at"] == "2027-03-01T09:30:00+00:00"


def test_agent_failures_and_warnings_are_filled_in(tmp_path: Path) -> None:
    data = {"options": SAMPLES["transport"]["options"]}
    _, result, problems = write("transport", data, tmp_path)
    assert problems == []
    assert result["agent"] == "transport"
    assert result["failures"] == []
    assert result["warnings"] == []


def test_unreadable_previous_file_restarts_at_version_1(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "flights.json").write_text("{not json", encoding="utf-8")
    _, result, problems = write("flights", SAMPLES["flights"], tmp_path)
    assert problems == []
    assert result["version"] == 1
    assert "no readable version" in capsys.readouterr().err


def test_write_is_atomic_and_leaves_no_temp_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write("flights", SAMPLES["flights"], tmp_path)
    before = (tmp_path / "flights.json").read_text()

    def broken_replace(src: str, dst: str) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(wr.os, "replace", broken_replace)
    changed = copy.deepcopy(SAMPLES["flights"])
    changed["options"][0]["stops"] = 1
    with pytest.raises(OSError, match="disk full"):
        write("flights", changed, tmp_path)
    assert (tmp_path / "flights.json").read_text() == before
    assert sorted(p.name for p in tmp_path.iterdir() if p.name.endswith(".tmp")) == []


def test_check_mode_writes_nothing(tmp_path: Path) -> None:
    target, _, problems = write("activities", SAMPLES["activities"], tmp_path, dry_run=True)
    assert problems == []
    assert not target.exists()


# --- invalid results: rejected here AND by the backend ---------------------------------------

Mutation = Callable[[dict[str, Any]], None]
_DELETE = object()


def _set(path: str, value: Any) -> Mutation:
    def apply(data: dict[str, Any]) -> None:
        node: Any = data
        parts = path.split(".")
        for part in parts[:-1]:
            node = node[int(part)] if part.isdigit() else node[part]
        last = parts[-1]
        if value is _DELETE:
            del node[last]
        else:
            node[last] = value

    return apply


INVALID: list[tuple[str, Mutation, str]] = [
    (
        "flights",
        _set("options.0.price.source_url", _DELETE),
        "options[0].price.source_url: is required",
    ),
    ("flights", _set("options.0.price.retrieved_at", "2027-03-01T10:15:00"), "UTC offset"),
    ("flights", _set("options.0.price.source_url", "kiwi"), "absolute http(s) URL"),
    ("flights", _set("options.0.price.amount_cents", 486.5), "must be integer"),
    ("flights", _set("options.0.price.amount_cents", -1), "at least 0"),
    ("flights", _set("options.0.price.currency", "eur"), "must match"),
    ("flights", _set("options.0.source", "web"), "only MCP prices"),
    ("flights", _set("options.0.source", "skyscanner"), "must be one of"),
    ("flights", _set("options.0.segments", []), "at least 1 item"),
    ("flights", _set("options.0.segments.0.flight_number", "easyJet 3127"), "must match"),
    ("flights", _set("options.0.segments.0.to_airport", "MXP"), "equals from_airport"),
    (
        "flights",
        _set("options.0.segments.1.depart_at", "2027-05-13T08:00:00+01:00"),
        "travel order",
    ),
    ("flights", _set("options.0.price.total", 1), "not part of the schema"),
    ("flights", _set("failures.0.at", "ieri"), "UTC offset"),
    ("lodging", _set("options.0.lon", None), "lat and lon go together"),
    ("lodging", _set("options.0.check_out", "2027-05-13"), "must be after check_in"),
    ("lodging", _set("options.0.check_in", "2027-02-30"), "calendar date"),
    ("lodging", _set("options.0.kind", "castle"), "must be one of"),
    ("lodging", _set("options.0.name", "x" * 201), "at most 200 characters"),
    ("lodging", _set("options.0.address", ""), "must not be empty"),
    ("activities", _set("options.0.price.status", "verified"), "no MCP source"),
    ("activities", _set("options.0.title", "x" * 121), "at most 120 characters"),
    ("activities", _set("options.0.start_time", "9:30"), "must match"),
    ("activities", _set("options.1.id", "a1"), "already used"),
    ("activities", _set("options.0.booking_required", "maybe"), "must be boolean"),
    ("activities", _set("options.0.duration_min", 0), "greater than 0"),
    (
        "transport",
        _set("options.0.arrive_at", "2027-05-13T09:00:00+01:00"),
        "must be after depart_at",
    ),
    ("transport", _set("options.0.mode", "teleport"), "must be one of"),
    ("transport", _set("options.0.from", _DELETE), "options[0].from: is required"),
    ("transport", _set("options", {"t1": {}}), "options: must be array"),
    ("transport", _set("warnings", "nessuno"), "warnings: must be array"),
]


@pytest.mark.parametrize(("agent", "mutate", "message"), INVALID)
def test_invalid_result_is_rejected_like_the_backend_does(
    agent: str, mutate: Mutation, message: str, tmp_path: Path
) -> None:
    data = copy.deepcopy(SAMPLES[agent])
    mutate(data)
    target, result, problems = write(agent, data, tmp_path)
    assert any(message in line for line in problems), problems
    assert not target.exists()
    with pytest.raises(ValidationError):
        RESULTS.parse_result(agent, result)


def test_wrong_agent_or_shape_is_a_usage_error(tmp_path: Path) -> None:
    with pytest.raises(wr.UsageError, match="this is the lodging result"):
        write("lodging", SAMPLES["flights"], tmp_path)
    with pytest.raises(wr.UsageError, match="unknown agent"):
        write("weather", SAMPLES["flights"], tmp_path)
    with pytest.raises(wr.UsageError, match="JSON object"):
        write("flights", [SAMPLES["flights"]], tmp_path)


def test_validator_rejects_unsupported_references() -> None:
    validator = wr.Validator({"$ref": "https://example.com/schema.json"})
    with pytest.raises(ValueError, match="only local references"):
        validator.errors({})


# --- command line -----------------------------------------------------------------------------


def run_cli(*args: str, stdin: str | None = None) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        input=stdin,
        capture_output=True,
        text=True,
        check=False,
        env=env,
        timeout=60,
    )


def test_cli_writes_from_a_file(tmp_path: Path) -> None:
    draft = tmp_path / "flights-draft.json"
    draft.write_text(json.dumps(SAMPLES["flights"]), encoding="utf-8")
    results = tmp_path / "results"
    out = run_cli(
        "flights", str(draft), "--results-dir", str(results), "--schema-dir", str(SCHEMAS)
    )
    assert out.returncode == 0, out.stderr
    assert out.stdout.startswith(f"wrote {results / 'flights.json'} v1 at ")
    assert out.stdout.rstrip().endswith("1 options, 1 failures, 1 warnings")
    assert json.loads((results / "flights.json").read_text())["version"] == 1


def test_cli_reads_stdin_and_reports_every_problem(tmp_path: Path) -> None:
    data = copy.deepcopy(SAMPLES["activities"])
    data["options"][0]["price"]["status"] = "verified"
    data["options"][0]["start_time"] = "25:00"
    out = run_cli(
        "activities",
        "--results-dir",
        str(tmp_path),
        "--schema-dir",
        str(SCHEMAS),
        stdin=json.dumps(data),
    )
    assert out.returncode == 1
    assert out.stdout == ""
    assert "2 problem(s); nothing was written" in out.stderr
    assert "- options[0].start_time: must match" in out.stderr
    assert "- options[0].price.status:" in out.stderr
    assert not (tmp_path / "activities.json").exists()


def test_cli_bad_json_and_check_mode(tmp_path: Path) -> None:
    bad = run_cli(
        "lodging", "--results-dir", str(tmp_path), "--schema-dir", str(SCHEMAS), stdin="{oops"
    )
    assert bad.returncode == 2
    assert "not valid JSON" in bad.stderr
    ok = run_cli(
        "lodging", "--check", "--results-dir", str(tmp_path), "--schema-dir", str(SCHEMAS),
        stdin=json.dumps(SAMPLES["lodging"]),
    )  # fmt: skip
    assert ok.returncode == 0, ok.stderr
    assert ok.stdout.startswith("ok: valid lodging result")
    assert not (tmp_path / "lodging.json").exists()


def test_main_reads_stdin_in_process(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(SAMPLES["transport"])))
    code = wr.main(["transport", "-", "--results-dir", str(tmp_path), "--schema-dir", str(SCHEMAS)])
    assert code == 0
    assert "v1" in capsys.readouterr().out


def test_default_schema_dir_holds_the_exported_schemas() -> None:
    """schemas/ is generated by scripts/render_profiles.py; when present it must match."""
    if not wr.SCHEMA_DIR.is_dir():
        pytest.skip("schemas/ not generated yet (scripts/render_profiles.py)")
    for agent in wr.AGENTS:
        shipped = json.loads((wr.SCHEMA_DIR / f"{agent}.json").read_text(encoding="utf-8"))
        exported = json.loads((SCHEMAS / f"{agent}.json").read_text(encoding="utf-8"))
        assert shipped == exported, agent
