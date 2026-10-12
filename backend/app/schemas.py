"""Export the contract's JSON Schemas to the repository's schema/ directory.

    uv run python -m app.schemas           # (re)write schema/*.json from the Pydantic models
    uv run python -m app.schemas --check   # exit 1 if a file is missing, stale or unexpected

The files are generated, never edited by hand:

    plan.json              Plan: the input_schema of the coordinator's submit_plan tool
    request.json           PlanRequest: POST /plans body, drives the web form
    ui_event.json          UIEvent: what the browser receives over SSE
    results/<agent>.json   the subagents' blackboard files (travel-research-rules skill)

Output is deterministic (sorted keys, two-space indent, trailing newline), so `--check` can run
in CI. plan.json is self-contained: its only references are local `#/$defs/...` ones, so it can
be pasted inline as a tool input_schema.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable, Iterator, Sequence
from pathlib import Path
from typing import Any

from pydantic import BaseModel
from pydantic.json_schema import GenerateJsonSchema, JsonSchemaMode

from app.events import UIEvent
from app.plan import Plan
from app.request import PlanRequest
from app.results import RESULT_MODELS, SUBAGENTS, SubagentName

SCHEMA_DIR = Path(__file__).resolve().parents[2] / "schema"
"""schema/ at the repository root."""

LOCAL_REF_PREFIX = "#/$defs/"

JsonSchema = dict[str, Any]


class ContractJsonSchema(GenerateJsonSchema):
    """Pydantic's generator without the automatic per-field titles ("Amount Cents"): they add
    tokens to the tool definition and say nothing that the field name and description don't.
    Model titles (the `$defs` names) stay."""

    def field_title_should_be_set(self, schema: Any) -> bool:
        return False


def model_schema(model: type[BaseModel], mode: JsonSchemaMode = "validation") -> JsonSchema:
    return model.model_json_schema(mode=mode, schema_generator=ContractJsonSchema)


def iter_refs(node: Any) -> Iterator[str]:
    """Every `$ref` value in a schema, depth first."""
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "$ref" and isinstance(value, str):
                yield value
            else:
                yield from iter_refs(value)
    elif isinstance(node, list):
        for item in node:
            yield from iter_refs(item)


def check_self_contained(schema: JsonSchema) -> None:
    """Raise ValueError unless every `$ref` points at an existing entry of the schema's $defs."""
    definitions = schema.get("$defs", {})
    for ref in iter_refs(schema):
        if not ref.startswith(LOCAL_REF_PREFIX):
            msg = f"non-local $ref {ref!r}: the schema must be self-contained"
            raise ValueError(msg)
        if ref.removeprefix(LOCAL_REF_PREFIX) not in definitions:
            msg = f"$ref {ref!r} has no matching entry in $defs"
            raise ValueError(msg)


def plan_input_schema() -> JsonSchema:
    """The submit_plan input_schema: a self-contained JSON Schema object."""
    schema = model_schema(Plan)
    if schema.get("type") != "object":
        msg = "a tool input_schema must describe an object"
        raise ValueError(msg)
    check_self_contained(schema)
    return schema


def _result_schema(agent: SubagentName) -> Callable[[], JsonSchema]:
    return lambda: model_schema(RESULT_MODELS[agent])


SCHEMAS: dict[str, Callable[[], JsonSchema]] = {
    "plan.json": plan_input_schema,
    "request.json": lambda: model_schema(PlanRequest),
    # The browser receives serialized events: describe the output shape.
    "ui_event.json": lambda: model_schema(UIEvent, mode="serialization"),
    **{f"results/{agent}.json": _result_schema(agent) for agent in SUBAGENTS},
}
"""Exported files, relative to schema/, and how to build each one."""


def render(schema: JsonSchema) -> str:
    """Deterministic JSON text: sorted keys, two-space indent, UTF-8 as is, trailing newline."""
    return json.dumps(schema, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def build_all() -> dict[str, str]:
    """Every exported file's expected content, keyed by its path relative to schema/."""
    return {name: render(factory()) for name, factory in SCHEMAS.items()}


def write_all(directory: Path = SCHEMA_DIR) -> list[str]:
    """Write every schema whose content changed; return the paths written (relative)."""
    written: list[str] = []
    for name, content in build_all().items():
        path = directory / name
        if path.is_file() and path.read_text(encoding="utf-8") == content:
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        written.append(name)
    return written


def unexpected_files(directory: Path = SCHEMA_DIR) -> list[str]:
    """JSON files under `directory` that no model generates (left over from a rename)."""
    if not directory.is_dir():
        return []
    present = {path.relative_to(directory).as_posix() for path in directory.rglob("*.json")}
    return sorted(present - SCHEMAS.keys())


def stale_files(directory: Path = SCHEMA_DIR) -> list[str]:
    """Generated files that are missing or differ from what the models produce."""
    stale: list[str] = []
    for name, content in build_all().items():
        path = directory / name
        if not path.is_file() or path.read_text(encoding="utf-8") != content:
            stale.append(name)
    return stale


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m app.schemas",
        description="Export the contract's JSON Schemas (Plan, PlanRequest, UIEvent, results).",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="write nothing; exit 1 if any file is missing, stale or unexpected",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=SCHEMA_DIR,
        help="target directory (default: schema/ at the repository root)",
    )
    args = parser.parse_args(argv)
    directory: Path = args.out_dir

    if args.check:
        stale = stale_files(directory)
        extra = unexpected_files(directory)
        for name in stale:
            print(f"stale or missing: {directory / name}", file=sys.stderr)
        for name in extra:
            print(f"not generated by app.schemas: {directory / name}", file=sys.stderr)
        if stale or extra:
            print(
                "run `uv run python -m app.schemas` from backend/ and commit the result",
                file=sys.stderr,
            )
            return 1
        print(f"{directory} is up to date ({len(SCHEMAS)} schemas)")
        return 0

    written = write_all(directory)
    for name in written:
        print(f"wrote {directory / name}")
    for name in unexpected_files(directory):
        print(f"warning: {directory / name} is not generated by app.schemas", file=sys.stderr)
    if not written:
        print(f"{directory} is up to date ({len(SCHEMAS)} schemas)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
