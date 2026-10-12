#!/usr/bin/env python3
"""Validate a subagent's result and write it atomically to /workspace/results/<agent>.json.

    python3 write_result.py <agent> [FILE]      FILE holds the JSON; without FILE (or "-"): stdin
    python3 write_result.py <agent> FILE --check     validate only, write nothing

<agent> is flights, lodging, activities or transport. The input is the result envelope
(`agent`, `options`, `failures`, `warnings`); `version` and `updated_at` may be left out: this
script sets `version` to the previous file's version + 1 (1 for the first write) and
`updated_at` to now, with UTC offset. It checks the envelope and every option against
schemas/<agent>.json (and the cross-field rules of the backend's results.py), then writes a temp
file in the same directory and renames it over the result, so a reader never sees half a file.

Exit status: 0 written (one line on stdout: path, version, counts), 1 the result breaks the
schema (one line per problem on stderr; nothing written), 2 bad usage or unreadable input.

Options: --results-dir DIR (default /workspace/results), --schema-dir DIR (default: the schemas/
directory next to this script).

Stdlib only, Python 3.10+: this script runs inside the agent sandbox.
"""

from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import json
import os
import re
import sys
import tempfile
from collections.abc import Iterator, Mapping, Sequence
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

AGENTS = ("flights", "lodging", "activities", "transport")
RESULTS_DIR = Path("/workspace/results")
SCHEMA_DIR = Path(__file__).resolve().with_name("schemas")
MCP_SOURCES = {"expedia", "kiwi", "lastminute"}
"""Prices are "verified" only when they come from one of these MCP servers."""
MAX_ERRORS = 50

DATE_TIME = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2}(\.\d{1,6})?)?(Z|[+-]\d{2}:\d{2})$")
DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class UsageError(Exception):
    """Bad command line or unreadable input (exit status 2)."""


# --- a minimal JSON Schema validator ---------------------------------------------------------
# It covers the keywords the exported Pydantic schemas use: $ref (local), $defs, type, enum,
# const, anyOf/oneOf/allOf, properties, required, additionalProperties, items, minItems,
# maxItems, minLength, maxLength, pattern, minimum, maximum, exclusiveMinimum,
# exclusiveMaximum, and the formats date-time (with a mandatory offset), date and uri.


def path_text(path: Sequence[str | int]) -> str:
    """("options", 0, "price") -> options[0].price; the root is (result)."""
    text = ""
    for part in path:
        if isinstance(part, int):
            text += f"[{part}]"
        else:
            text += f".{part}" if text else part
    return text or "(result)"


def shown(value: Any) -> str:
    text = json.dumps(value, ensure_ascii=False)
    return text if len(text) <= 60 else text[:57] + "..."


def type_name(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return type(value).__name__


def is_type(value: Any, expected: str) -> bool:
    """JSON types. An integer is written without a fraction: 1250, never 1250.0."""
    actual = type_name(value)
    if expected == "number":
        return actual in {"integer", "number"}
    return actual == expected


def parse_instant(text: str) -> dt.datetime | None:
    """An ISO 8601 instant WITH a UTC offset, else None."""
    if not DATE_TIME.match(text):
        return None
    try:
        value = dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return value if value.utcoffset() is not None else None


def parse_day(text: str) -> dt.date | None:
    if not DATE.match(text):
        return None
    try:
        return dt.date.fromisoformat(text)
    except ValueError:
        return None


def format_error(fmt: str, value: str) -> str | None:
    if fmt == "date-time" and parse_instant(value) is None:
        return "must be an ISO 8601 date and time with a UTC offset, e.g. 2027-05-13T07:05:00+02:00"
    if fmt == "date" and parse_day(value) is None:
        return "must be a calendar date YYYY-MM-DD, e.g. 2027-05-13"
    if fmt == "uri":
        parts = urlsplit(value)
        if parts.scheme not in {"http", "https"} or not parts.netloc:
            return "must be an absolute http(s) URL, copied exactly from the source"
    return None


class Validator:
    def __init__(self, root: Mapping[str, Any]) -> None:
        self.root = root

    def errors(self, instance: Any) -> list[str]:
        found: list[str] = []
        self._check(instance, self.root, (), found)
        return found

    def _resolve(self, ref: str) -> Mapping[str, Any]:
        if not ref.startswith("#/"):
            msg = f"unsupported $ref {ref!r}: only local references are resolved"
            raise ValueError(msg)
        node: Any = self.root
        for part in ref[2:].split("/"):
            node = node[part.replace("~1", "/").replace("~0", "~")]
        return node

    def _check(
        self, value: Any, schema: Mapping[str, Any], path: tuple[str | int, ...], out: list[str]
    ) -> None:
        if "$ref" in schema:
            self._check(value, self._resolve(schema["$ref"]), path, out)
        for sub in schema.get("allOf", []):
            self._check(value, sub, path, out)
        for keyword in ("anyOf", "oneOf"):
            if keyword in schema:
                self._check_choice(value, schema[keyword], path, out)

        where = path_text(path)
        expected = schema.get("type")
        if expected is not None:
            names = expected if isinstance(expected, list) else [expected]
            if not any(is_type(value, name) for name in names):
                out.append(
                    f"{where}: must be {' or '.join(names)}, got {type_name(value)} {shown(value)}"
                )
                return
        if "const" in schema and value != schema["const"]:
            out.append(f"{where}: must be {shown(schema['const'])}, got {shown(value)}")
        if "enum" in schema and value not in schema["enum"]:
            allowed = ", ".join(shown(item) for item in schema["enum"])
            out.append(f"{where}: must be one of {allowed}, got {shown(value)}")

        if isinstance(value, str):
            self._check_string(value, schema, where, out)
        elif isinstance(value, (int, float)) and not isinstance(value, bool):
            self._check_number(value, schema, where, out)
        elif isinstance(value, list):
            self._check_array(value, schema, path, out)
        elif isinstance(value, dict):
            self._check_object(value, schema, path, out)

    def _check_choice(
        self,
        value: Any,
        options: Sequence[Mapping[str, Any]],
        path: tuple[str | int, ...],
        out: list[str],
    ) -> None:
        attempts: list[list[str]] = []
        for option in options:
            found: list[str] = []
            self._check(value, option, path, found)
            if not found:
                return
            attempts.append(found)
        # Report the branch whose type matches the value (e.g. the string branch of a nullable
        # string), else the first branch.
        for option, found in zip(options, attempts, strict=True):
            target = self._resolve(option["$ref"]) if "$ref" in option else option
            kind = target.get("type")
            if kind is None or is_type(value, kind if isinstance(kind, str) else kind[0]):
                out.extend(found)
                return
        out.extend(attempts[0])

    @staticmethod
    def _check_string(value: str, schema: Mapping[str, Any], where: str, out: list[str]) -> None:
        length = len(value)  # code points, like Pydantic and TripTracker's zod
        if "minLength" in schema and length < schema["minLength"]:
            if schema["minLength"] == 1:
                out.append(f"{where}: must not be empty")
            else:
                out.append(
                    f"{where}: must have at least {schema['minLength']} characters, got {length}"
                )
        if "maxLength" in schema and length > schema["maxLength"]:
            out.append(f"{where}: must have at most {schema['maxLength']} characters, got {length}")
        if "pattern" in schema and re.search(schema["pattern"], value) is None:
            out.append(f"{where}: must match {schema['pattern']}, got {shown(value)}")
        if "format" in schema:
            problem = format_error(schema["format"], value)
            if problem:
                out.append(f"{where}: {problem}; got {shown(value)}")

    @staticmethod
    def _check_number(value: float, schema: Mapping[str, Any], where: str, out: list[str]) -> None:
        if "minimum" in schema and value < schema["minimum"]:
            out.append(f"{where}: must be at least {schema['minimum']}, got {value}")
        if "maximum" in schema and value > schema["maximum"]:
            out.append(f"{where}: must be at most {schema['maximum']}, got {value}")
        if "exclusiveMinimum" in schema and value <= schema["exclusiveMinimum"]:
            out.append(f"{where}: must be greater than {schema['exclusiveMinimum']}, got {value}")
        if "exclusiveMaximum" in schema and value >= schema["exclusiveMaximum"]:
            out.append(f"{where}: must be less than {schema['exclusiveMaximum']}, got {value}")

    def _check_array(
        self,
        value: list[Any],
        schema: Mapping[str, Any],
        path: tuple[str | int, ...],
        out: list[str],
    ) -> None:
        where = path_text(path)
        if "minItems" in schema and len(value) < schema["minItems"]:
            out.append(f"{where}: needs at least {schema['minItems']} item(s), got {len(value)}")
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            out.append(f"{where}: allows at most {schema['maxItems']} items, got {len(value)}")
        items = schema.get("items")
        if isinstance(items, Mapping):
            for index, item in enumerate(value):
                self._check(item, items, (*path, index), out)

    def _check_object(
        self,
        value: dict[str, Any],
        schema: Mapping[str, Any],
        path: tuple[str | int, ...],
        out: list[str],
    ) -> None:
        properties: Mapping[str, Any] = schema.get("properties", {})
        for key in schema.get("required", []):
            if key not in value:
                out.append(f"{path_text((*path, key))}: is required")
        extra = schema.get("additionalProperties", True)
        for key, item in value.items():
            if key in properties:
                self._check(item, properties[key], (*path, key), out)
            elif extra is False:
                known = ", ".join(properties)
                out.append(
                    f"{path_text((*path, key))}: is not part of the schema; remove it "
                    f"(allowed: {known})"
                )
            elif isinstance(extra, Mapping):
                self._check(item, extra, (*path, key), out)


# --- cross-field rules (backend/app/results.py), checked only on well-formed parts ------------


def _instant(value: Any) -> dt.datetime | None:
    return parse_instant(value) if isinstance(value, str) else None


def semantic_errors(agent: str, result: Mapping[str, Any]) -> list[str]:
    out: list[str] = []
    options = result.get("options")
    if not isinstance(options, list):
        return out
    first: dict[str, int] = {}
    for index, option in enumerate(options):
        if not isinstance(option, dict):
            continue
        where = f"options[{index}]"
        option_id = option.get("id")
        if isinstance(option_id, str):
            if option_id in first:
                out.append(
                    f"{where}.id: '{option_id}' is already used by options[{first[option_id]}]; "
                    "ids must be unique"
                )
            else:
                first[option_id] = index

        price = option.get("price")
        if isinstance(price, dict) and price.get("status") == "verified":
            source = option.get("source")
            if agent in {"activities", "transport"}:
                out.append(
                    f"{where}.price.status: the {agent} agent has no MCP source, so its prices are "
                    "'estimated'; only MCP prices are 'verified'"
                )
            elif source not in MCP_SOURCES:
                out.append(
                    f"{where}.price.status: a price from source {shown(source)} is 'estimated'; "
                    "only MCP prices (expedia, kiwi, lastminute) are 'verified'"
                )

        if (option.get("lat") is None) != (option.get("lon") is None):
            out.append(f"{where}: lat and lon go together: set both or neither")

        if agent == "lodging":
            check_in, check_out = option.get("check_in"), option.get("check_out")
            day_in = parse_day(check_in) if isinstance(check_in, str) else None
            day_out = parse_day(check_out) if isinstance(check_out, str) else None
            if day_in and day_out and day_out <= day_in:
                out.append(f"{where}.check_out: ({check_out}) must be after check_in ({check_in})")

        if agent == "flights" and isinstance(option.get("segments"), list):
            previous_arrival: dt.datetime | None = None
            for leg_index, leg in enumerate(option["segments"]):
                if not isinstance(leg, dict):
                    continue
                leg_where = f"{where}.segments[{leg_index}]"
                if leg.get("from_airport") and leg.get("from_airport") == leg.get("to_airport"):
                    out.append(f"{leg_where}.to_airport: equals from_airport ({leg['to_airport']})")
                depart, arrive = _instant(leg.get("depart_at")), _instant(leg.get("arrive_at"))
                if depart and arrive and arrive <= depart:
                    out.append(f"{leg_where}.arrive_at: must be after depart_at")
                if depart and previous_arrival and depart <= previous_arrival:
                    out.append(
                        f"{leg_where}.depart_at: departs before the previous leg lands; list the "
                        "legs in travel order"
                    )
                previous_arrival = arrive

        if agent == "transport":
            depart, arrive = _instant(option.get("depart_at")), _instant(option.get("arrive_at"))
            if depart and arrive and arrive <= depart:
                out.append(f"{where}.arrive_at: must be after depart_at")
    return out


# --- reading, versioning, writing ------------------------------------------------------------


def load_schema(schema_dir: Path, agent: str) -> dict[str, Any]:
    path = schema_dir / f"{agent}.json"
    try:
        with path.open(encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError) as error:
        msg = f"cannot read the schema {path}: {error}"
        raise UsageError(msg) from None


def read_input(source: str | None) -> Any:
    try:
        if source in (None, "-"):
            text = sys.stdin.read()
            name = "stdin"
        else:
            text = Path(source).read_text(encoding="utf-8")
            name = source
    except OSError as error:
        msg = f"cannot read {source}: {error}"
        raise UsageError(msg) from None
    try:
        return json.loads(text)
    except ValueError as error:
        msg = f"{name} is not valid JSON: {error}"
        raise UsageError(msg) from None


def previous_version(target: Path) -> int:
    """The version of the file being replaced; 0 when there is none."""
    if not target.exists():
        return 0
    try:
        version = json.loads(target.read_text(encoding="utf-8")).get("version")
    except (OSError, ValueError, AttributeError):
        version = None
    if isinstance(version, int) and not isinstance(version, bool) and version >= 1:
        return version
    print(
        f"write_result.py: warning: {target} has no readable version; this write is version 1",
        file=sys.stderr,
    )
    return 0


def now_utc() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0)


@contextlib.contextmanager
def locked(directory: Path, agent: str) -> Iterator[None]:
    """Serialize writers of the same file (read version -> write -> rename), where supported."""
    try:
        import fcntl
    except ImportError:  # not POSIX: one writer per file is still the rule
        yield
        return
    with (directory / f".{agent}.lock").open("w") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def write_atomically(target: Path, data: Mapping[str, Any]) -> None:
    text = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    handle, temp_name = tempfile.mkstemp(
        dir=target.parent, prefix=f".{target.stem}.", suffix=".tmp"
    )
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temp_name, 0o644)
        os.replace(temp_name, target)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(temp_name)
        raise


def prepare(agent: str, data: Any) -> dict[str, Any]:
    """Fill the fields this script owns; the version is set later, under the lock."""
    if not isinstance(data, dict):
        msg = f"the result must be a JSON object (the envelope), got {type_name(data)}"
        raise UsageError(msg)
    if data.get("agent", agent) != agent:
        msg = f"the result says agent {shown(data.get('agent'))} but this is the {agent} result"
        raise UsageError(msg)
    result: dict[str, Any] = {"agent": agent, "version": 1, "updated_at": ""}
    result.update(
        {key: value for key, value in data.items() if key not in {"version", "updated_at"}}
    )
    result["agent"] = agent
    result.setdefault("failures", [])
    result.setdefault("warnings", [])
    return result


def check(agent: str, result: Mapping[str, Any], schema: Mapping[str, Any]) -> list[str]:
    problems = Validator(schema).errors(result)
    problems += semantic_errors(agent, result)
    return problems


def write_result(
    agent: str,
    data: Any,
    *,
    results_dir: Path = RESULTS_DIR,
    schema_dir: Path = SCHEMA_DIR,
    now: dt.datetime | None = None,
    dry_run: bool = False,
) -> tuple[Path, dict[str, Any], list[str]]:
    """Validate and write; returns (path, the final result, problems). Nothing is written when
    there are problems or with `dry_run`."""
    if agent not in AGENTS:
        msg = f"unknown agent {agent!r}; expected one of {', '.join(AGENTS)}"
        raise UsageError(msg)
    schema = load_schema(schema_dir, agent)
    result = prepare(agent, data)
    stamp = now or now_utc()
    if stamp.utcoffset() is None:
        msg = "now must carry a UTC offset"
        raise ValueError(msg)
    result["updated_at"] = stamp.isoformat()
    target = results_dir / f"{agent}.json"
    problems = check(agent, result, schema)
    if problems or dry_run:
        return target, result, problems
    results_dir.mkdir(parents=True, exist_ok=True)
    with locked(results_dir, agent):
        result["version"] = previous_version(target) + 1
        write_atomically(target, result)
    return target, result, []


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="write_result.py",
        description="Validate a subagent result against schemas/<agent>.json and write it "
        "atomically with version + 1 and updated_at.",
        allow_abbrev=False,
    )
    parser.add_argument("agent", help=f"one of {', '.join(AGENTS)}")
    parser.add_argument("file", nargs="?", help="the JSON result; '-' or omitted: stdin")
    parser.add_argument("--check", action="store_true", help="validate only, write nothing")
    parser.add_argument(
        "--results-dir", type=Path, default=RESULTS_DIR, help=f"default {RESULTS_DIR}"
    )
    parser.add_argument(
        "--schema-dir", type=Path, default=SCHEMA_DIR, help="default: schemas/ next to this script"
    )
    args = parser.parse_args(argv)

    try:
        data = read_input(args.file)
        target, result, problems = write_result(
            args.agent,
            data,
            results_dir=args.results_dir,
            schema_dir=args.schema_dir,
            dry_run=args.check,
        )
    except UsageError as error:
        print(f"write_result.py: error: {error}", file=sys.stderr)
        return 2
    if problems:
        print(
            f"write_result.py: {len(problems)} problem(s); nothing was written. Fix them all and "
            "run again:",
            file=sys.stderr,
        )
        for line in problems[:MAX_ERRORS]:
            print(f"- {line}", file=sys.stderr)
        if len(problems) > MAX_ERRORS:
            print(f"- ... and {len(problems) - MAX_ERRORS} more", file=sys.stderr)
        return 1
    counts = (
        f"{len(result['options'])} options, {len(result['failures'])} failures, "
        f"{len(result['warnings'])} warnings"
    )
    if args.check:
        print(f"ok: valid {args.agent} result ({counts}); nothing written (--check)")
    else:
        print(f"wrote {target} v{result['version']} at {result['updated_at']}: {counts}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
