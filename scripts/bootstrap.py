#!/usr/bin/env python3
"""Apply one profile's agents, environment and skills through the Anthropic SDK.

This is the SDK equivalent of

    ant apply --lock-file backend/claude-lock.<profile>.json profiles/<profile>

run from the repository root, for machines where the `ant` CLI is not installed
(docs/managed-agents-notes.md §2h "If ant can't be used"). It reads the same files, resolves
the same relative references and writes the lockfile in ant's own format, so ant can take over
later and backend/app/lockfile.py reads it. From backend/ (the venv has anthropic 1.13.0):

    uv run python ../scripts/bootstrap.py --profile development --dry-run   # no network at all
    uv run python ../scripts/bootstrap.py --profile development             # plan only
    uv run python ../scripts/bootstrap.py --profile development --yes       # plan, then apply
    uv run python ../scripts/bootstrap.py --profile production --i-know-this-is-production --yes

What it does, in ant's order (core/apply.go, core/plan.go of anthropics/anthropic-cli):

1. Refuses stale profiles (scripts/render_profiles.py --check) and loads profiles/<profile>/:
   agents/*.md (frontmatter = POST /v1/agents body, Markdown body = `system`),
   environments/*.yaml, the `- ./tools/x.json` includes in `tools`/`mcp_servers`, and every
   resource a relative path references (`skills`, `multiagent.*.predefined_agents`).
2. Orders resources so each comes after what it references: skills, the environment, the
   subagents, then the coordinator, so the coordinator's pins are fresh.
3. Plans each one against the lockfile (hash of the body, or of the skill's files) and, unless
   --dry-run, against the server (drift: an out-of-band change blocks the plan unless --force).
4. With --yes, creates or updates in order, resolving each path reference to
   {type, id, version} (skills: {type: custom, skill_id, version}), and saves the lockfile
   after every write, so a failure halfway loses nothing.

Skills are uploaded through the GA `client.skills` namespace, so their lockfile `version` is a
version id (`skver_...`). ant uploads them through the Beta skills API and may record an
epoch-like digit string instead; the entry shape is the same ({kind, id, version, hash}), and
backend/app/lockfile.py reads both. The two forms cannot be compared with each other, so a
skill whose recorded version and server version differ only in form is not reported as drift.
The upload skips what ant skips (dotfiles, __pycache__, .venv, node_modules, dist, build,
symlinks) and also the skill's tests (test_*.py, *_test.py, conftest.py, tests/): they are not
agent content.

Lockfile keys are written exactly as ant writes them: relative to the lockfile's directory
(anthropic-cli v1.40.0 pkg/cmd/apply.go `lock.Root()`, core/lock.go `Root()` =
`filepath.Dir(lf.Path)`, core/loader.go `keyFor`), so backend/claude-lock.<profile>.json holds
`../profiles/<profile>/agents/<name>.md` and `../skills/<name>`. The first version of this
script keyed them from the repository root (`./profiles/...`); such entries are rewritten to
ant's key on the next run that writes the lockfile (never duplicated as new resources).
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import mimetypes
import os
import re
import sys
import tempfile
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml

if TYPE_CHECKING:
    import anthropic

REPO_ROOT = Path(__file__).resolve().parents[1]
PROFILES = ("development", "production")
LOCKFILE_VERSION = 1
KNOWN_AFTER_APPLY = "(known after apply)"

SKILL = "skill"
ENVIRONMENT = "environment"
AGENT = "agent"
KIND_RANK = {SKILL: 0, ENVIRONMENT: 1, AGENT: 4}
"""ant's registry order (skill, environment, memory_store, vault, agent, deployment)."""

ID_PREFIXES = {"skill_": SKILL, "env_": ENVIRONMENT, "agent_": AGENT}
KIND_BY_DIR = {"environments": ENVIRONMENT, "agents": AGENT}
FILE_KINDS = (ENVIRONMENT, AGENT)
DATA_EXTENSIONS = (".yml", ".yaml", ".json")
RESOURCE_EXTENSIONS = (".md", ".markdown", *DATA_EXTENSIONS)
WALK_SKIP_DIRS = frozenset(
    {".git", "node_modules", "vendor", "__pycache__", ".venv", "venv", "dist", "build"}
)

COMPUTED = {
    SKILL: ("id", "type", "created_at", "updated_at", "latest_version_id", "source"),
    ENVIRONMENT: ("id", "type", "created_at", "updated_at", "archived_at"),
    AGENT: ("id", "type", "created_at", "updated_at", "archived_at", "version"),
}
"""Server-owned fields stripped before fingerprinting a remote object (ant kinds.go)."""
CLEARABLE = {
    ENVIRONMENT: ("description",),
    AGENT: ("description", "system", "tools", "mcp_servers", "multiagent", "skills"),
}
"""Fields that, once removed from a file, are sent as null to clear them on the server."""
INCLUDE_FIELDS = {AGENT: ("tools", "mcp_servers")}

MAX_SKILL_FILES = 1000
MAX_SKILL_TOTAL = 32 << 20
MAX_SKILL_FILE = 16 << 20
SKILL_TEST_FILE = re.compile(r"^(test_.*\.py|.*_test\.py|conftest\.py)$")
SKILL_TEST_DIRS = frozenset({"tests", "test"})


class BootstrapError(Exception):
    """Something the user must fix; the message names the file or resource."""


# --- canonical JSON and hashes (ant core/hash.go) ------------------------------------------------


def go_string(text: str) -> str:
    """A JSON string as Go's encoding/json writes it (HTML-safe escaping, UTF-8 kept)."""
    out = ['"']
    for char in text:
        code = ord(char)
        if char in '"\\':
            out.append("\\" + char)
        elif char == "\n":
            out.append("\\n")
        elif char == "\r":
            out.append("\\r")
        elif char == "\t":
            out.append("\\t")
        elif char == "\b":
            out.append("\\b")
        elif char == "\f":
            out.append("\\f")
        elif code < 0x20 or char in "<>&\u2028\u2029":
            out.append(f"\\u{code:04x}")
        else:
            out.append(char)
    out.append('"')
    return "".join(out)


def go_float(value: float) -> str:
    """A float as ant's canonicalize renders it: whole values as integers, others like Go's
    strconv.FormatFloat(f, 'g', -1, 64)."""
    if math.isnan(value) or math.isinf(value):
        raise BootstrapError("NaN and infinite numbers cannot be sent as JSON")
    if value == math.trunc(value) and abs(value) < 2**53:
        return str(int(value))
    sign, digits_tuple, exponent = Decimal(repr(value)).as_tuple()
    assert isinstance(exponent, int)
    digits = "".join(map(str, digits_tuple))
    point = len(digits) + exponent  # position of the decimal point in `digits`
    digits = digits.rstrip("0") or "0"
    stripped_leading = len(digits) - len(digits.lstrip("0"))
    digits, point = digits.lstrip("0") or "0", point - stripped_leading
    neg = "-" if sign else ""
    exp = point - 1
    if exp < -4 or exp >= 6:
        mantissa = digits[0] + ("." + digits[1:] if len(digits) > 1 else "")
        return f"{neg}{mantissa}e{'-' if exp < 0 else '+'}{abs(exp):02d}"
    if point <= 0:
        return f"{neg}0.{'0' * -point}{digits}"
    if point >= len(digits):
        return f"{neg}{digits}{'0' * (point - len(digits))}"
    return f"{neg}{digits[:point]}.{digits[point:]}"


def canonical_json(value: Any) -> str:
    """json.Marshal(canonicalize(v)) in Go: sorted keys, no spaces, one spelling per number."""
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return go_float(value)
    if isinstance(value, str):
        return go_string(value)
    if isinstance(value, Mapping):
        items = sorted((str(key), item) for key, item in value.items())
        return "{" + ",".join(f"{go_string(k)}:{canonical_json(v)}" for k, v in items) + "}"
    if isinstance(value, list | tuple):
        return "[" + ",".join(canonical_json(item) for item in value) + "]"
    raise BootstrapError(f"cannot encode {type(value).__name__} as JSON")


def digest(data: bytes) -> str:
    """ant's fingerprint: sha256 over `<len>:` + data, first 32 hex characters."""
    hasher = hashlib.sha256()
    hasher.update(f"{len(data)}:".encode())
    hasher.update(data)
    return hasher.hexdigest()[:32]


def hash_body(body: Mapping[str, Any]) -> str:
    return digest(canonical_json(body).encode("utf-8"))


def drop_empty(mapping: Mapping[str, Any]) -> dict[str, Any]:
    """Drop nulls, empty strings and empty maps and lists, recursively (ant dropEmpty)."""
    out: dict[str, Any] = {}
    for key, value in mapping.items():
        if value is None or value == "":
            continue
        if isinstance(value, Mapping):
            nested = drop_empty(value)
            if nested:
                out[key] = nested
            continue
        if isinstance(value, list):
            if not value:
                continue
            out[key] = [drop_empty(item) if isinstance(item, Mapping) else item for item in value]
            continue
        out[key] = value
    return out


def normalize_remote(kind: str, remote: Mapping[str, Any]) -> dict[str, Any]:
    out = {key: value for key, value in remote.items() if key not in COMPUTED[kind]}
    return drop_empty(out)


# --- lockfile (ant core/lock.go) -----------------------------------------------------------------

ENTRY_KEYS = ("kind", "id", "version", "hash", "remote_hash", "revision", "subpath")
ENTRY_OMIT_EMPTY = frozenset({"version", "remote_hash", "revision", "subpath"})


@dataclass
class LockEntry:
    kind: str
    id: str
    version: str = ""
    hash: str = ""
    remote_hash: str = ""
    revision: str = ""
    subpath: str = ""
    unknown: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_json(cls, key: str, data: Any) -> LockEntry:
        if not isinstance(data, dict):
            raise BootstrapError(f"lockfile entry {key!r}: expected an object")
        if not data.get("id") or not data.get("kind"):
            raise BootstrapError(f"lockfile entry {key!r}: missing `id` or `kind`")
        version = data.get("version", "")
        return cls(
            kind=str(data["kind"]),
            id=str(data["id"]),
            version="" if version is None else str(version),
            hash=str(data.get("hash") or ""),
            remote_hash=str(data.get("remote_hash") or ""),
            revision=str(data.get("revision") or ""),
            subpath=str(data.get("subpath") or ""),
            unknown={k: v for k, v in data.items() if k not in ENTRY_KEYS},
        )

    def to_json(self) -> dict[str, Any]:
        known: dict[str, Any] = {}
        for key in ENTRY_KEYS:
            value = getattr(self, key)
            if value == "" and key in ENTRY_OMIT_EMPTY:
                continue
            known[key] = value
        if not self.unknown:
            return known
        merged = {**known, **self.unknown}
        return {key: merged[key] for key in sorted(merged)}


@dataclass
class Lockfile:
    path: Path
    resources: dict[str, LockEntry] = field(default_factory=dict)
    origin: dict[str, str] | None = None
    existed: bool = False

    @classmethod
    def load(cls, path: Path) -> Lockfile:
        lock = cls(path=path)
        if not path.is_file():
            return lock
        lock.existed = True
        text = path.read_text(encoding="utf-8")
        if not text.strip():
            return lock
        try:
            doc = json.loads(text)
        except ValueError as exc:
            raise BootstrapError(f"{path}: {exc}") from exc
        if not isinstance(doc, dict):
            raise BootstrapError(f"{path}: expected a JSON object")
        if int(doc.get("version", 0)) > LOCKFILE_VERSION:
            raise BootstrapError(
                f"{path}: written by a newer ant (lockfile version {doc['version']})"
            )
        origin = doc.get("origin")
        lock.origin = (
            {k: str(v) for k, v in origin.items() if v} if isinstance(origin, dict) else None
        )
        for key, entry in (doc.get("resources") or {}).items():
            if not (key.startswith(("./", "../", "https://", "http://"))):
                raise BootstrapError(
                    f"{path}: entry {key!r}: resource keys start with ./, ../ or https://"
                )
            lock.resources[key] = LockEntry.from_json(key, entry)
        return lock

    def render(self) -> str:
        """The file as ant's json.MarshalIndent writes it, plus a trailing newline."""
        doc: dict[str, Any] = {"version": LOCKFILE_VERSION}
        if self.origin is not None:
            doc["origin"] = {
                key: self.origin[key]
                for key in ("base_url", "organization_id", "workspace_id")
                if self.origin.get(key)
            }
        doc["resources"] = {key: self.resources[key].to_json() for key in sorted(self.resources)}
        return go_indent(doc, 0) + "\n"

    def save(self) -> None:
        """Atomic write: a temp file in the same directory, then rename."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle, temp = tempfile.mkstemp(dir=self.path.parent, prefix=f".{self.path.name}.tmp-")
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as out:
                out.write(self.render())
                out.flush()
                os.fsync(out.fileno())
            os.chmod(temp, 0o644)
            os.replace(temp, self.path)
        except BaseException:
            Path(temp).unlink(missing_ok=True)
            raise


def go_indent(value: Any, level: int) -> str:
    """json.MarshalIndent(v, "", "  "): keys in the given order, Go string escaping."""
    pad, inner = "  " * level, "  " * (level + 1)
    if isinstance(value, Mapping):
        if not value:
            return "{}"
        items = [f"{inner}{go_string(str(k))}: {go_indent(v, level + 1)}" for k, v in value.items()]
        return "{\n" + ",\n".join(items) + "\n" + pad + "}"
    if isinstance(value, list):
        if not value:
            return "[]"
        items = [f"{inner}{go_indent(v, level + 1)}" for v in value]
        return "[\n" + ",\n".join(items) + "\n" + pad + "]"
    return canonical_json(value)


# --- loading -------------------------------------------------------------------------------------


@dataclass(frozen=True)
class SkillFile:
    rel_path: str
    abs_path: Path
    size: int

    def upload_name(self, upload_dir: str) -> str:
        return f"{upload_dir}/{self.rel_path}"

    def content_type(self) -> str:
        guessed, _ = mimetypes.guess_type(self.rel_path)
        return guessed or "application/octet-stream"


@dataclass(frozen=True)
class SkillBundle:
    upload_dir: str
    display_name: str
    files: tuple[SkillFile, ...]

    def fingerprint(self) -> str:
        """ant's skillBundle.Fingerprint: paths, sizes and contents, in path order."""
        hasher = hashlib.sha256()
        hasher.update(f"dir:{self.upload_dir}\x00title:{self.display_name}\x00".encode())
        for item in self.files:
            hasher.update(f"path:{item.rel_path}\x00size:{item.size}\x00".encode())
            hasher.update(item.abs_path.read_bytes())
            hasher.update(b"\x00")
        return hasher.hexdigest()[:32]

    def describe(self) -> str:
        return "1 file" if len(self.files) == 1 else f"{len(self.files)} files"


@dataclass
class RefEntry:
    """One element of a reference slot: a loaded resource (by key) or a value sent as is."""

    target_key: str | None = None
    pinned: bool = True
    value: Any = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SlotSpec:
    path: str
    targets: tuple[str, ...]
    encode: Callable[[Target], dict[str, Any]]


@dataclass
class Slot:
    spec: SlotSpec
    entries: list[RefEntry]


@dataclass
class Source:
    key: str
    kind: str
    path: Path
    body: dict[str, Any]
    payload: SkillBundle | None = None
    slots: list[Slot] = field(default_factory=list)

    @property
    def deps(self) -> list[str]:
        return [e.target_key for slot in self.slots for e in slot.entries if e.target_key]


@dataclass
class Target:
    kind: str
    id: str | None = None
    version: Any = None
    pinned: bool = True
    known: bool = False
    versioned: bool = True

    def id_or_placeholder(self) -> Any:
        return self.id if self.known else KNOWN_AFTER_APPLY

    def version_or_placeholder(self) -> Any:
        return self.version if self.version is not None else KNOWN_AFTER_APPLY


def encode_object(type_name: str, id_field: str) -> Callable[[Target], dict[str, Any]]:
    def encode(target: Target) -> dict[str, Any]:
        out: dict[str, Any] = {"type": type_name, id_field: target.id_or_placeholder()}
        if target.pinned:
            out["version"] = target.version_or_placeholder()
        return out

    return encode


AGENT_SLOTS = (
    SlotSpec("skills", (SKILL,), encode_object("custom", "skill_id")),
    SlotSpec("multiagent.agents", (AGENT,), encode_object("agent", "id")),
    SlotSpec("multiagent.subagents.predefined_agents", (AGENT,), encode_object("agent", "id")),
    SlotSpec("multiagent.workflows.predefined_agents", (AGENT,), encode_object("agent", "id")),
)
SLOTS = {AGENT: AGENT_SLOTS, ENVIRONMENT: (), SKILL: ()}


def get_path(body: Mapping[str, Any], dotted: str) -> tuple[Any, bool]:
    node: Any = body
    for part in dotted.split("."):
        if not isinstance(node, Mapping) or part not in node:
            return None, False
        node = node[part]
    return node, True


def set_path(body: dict[str, Any], dotted: str, value: Any) -> None:
    parts = dotted.split(".")
    node = body
    for part in parts[:-1]:
        node = node[part]
    node[parts[-1]] = value


def split_frontmatter(text: str) -> tuple[str | None, str]:
    """(frontmatter or None, body), as ant's core/source.go splits a Markdown file."""
    text = text.removeprefix("﻿")
    trimmed = text.lstrip("\r\n \t")
    if not trimmed.startswith("---"):
        return None, text
    rest = trimmed[3:]
    newline = rest.find("\n")
    if newline < 0 or rest[:newline].strip():
        return None, text
    rest = rest[newline + 1 :]
    offset = 0
    for line in rest.splitlines(keepends=True):
        if line.strip() == "---":
            return rest[:offset], rest[offset + len(line) :]
        offset += len(line)
    raise BootstrapError("frontmatter opened with --- but never closed")


def parse_yaml_map(text: str, what: str) -> dict[str, Any]:
    if not text.strip():
        return {}
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise BootstrapError(f"parsing {what}: {exc}") from exc
    if not isinstance(data, dict):
        raise BootstrapError(f"parsing {what}: expected a mapping")
    return data


def kind_for_id(text: str) -> str | None:
    for prefix, kind in ID_PREFIXES.items():
        if text.startswith(prefix) and len(text) > len(prefix):
            return kind
    return None


class Loader:
    """Turns a profile directory into a closed set of Sources keyed like the lockfile: `key_root`
    is the lockfile's directory, as in ant (`core.NewLoader(registry, lock.Root(), ...)`)."""

    def __init__(self, key_root: Path) -> None:
        self.key_root = key_root.resolve()
        self.sources: dict[str, Source] = {}

    def key_for(self, path: Path) -> str:
        rel = Path(os.path.relpath(path.resolve(), self.key_root)).as_posix()
        return rel if rel.startswith("../") else "./" + rel

    # walking --------------------------------------------------------------------------------

    def add_dir(self, directory: Path) -> None:
        directory = directory.resolve()
        if not directory.is_dir():
            raise BootstrapError(f"{directory}: not a directory")
        for path in self._walk(directory):
            self._load(path, walked=True)

    def _walk(self, root: Path) -> Iterator[Path]:
        for current, dirnames, filenames in os.walk(root):
            here = Path(current)
            keep = []
            for name in sorted(dirnames):
                if name in WALK_SKIP_DIRS or name.startswith("."):
                    continue
                if (here / name / "SKILL.md").is_file():
                    yield here / name
                    continue
                keep.append(name)
            dirnames[:] = keep
            for name in sorted(filenames):
                if Path(name).suffix.lower() in RESOURCE_EXTENSIONS and name != "claude-lock.json":
                    yield here / name

    # one resource ---------------------------------------------------------------------------

    def _load(self, path: Path, *, walked: bool) -> Source | None:
        path = path.resolve()
        if path.name == "SKILL.md":
            path = path.parent
        key = self.key_for(path)
        if key in self.sources:
            return self.sources[key]
        if path.is_dir():
            if not (path / "SKILL.md").is_file():
                raise BootstrapError(f"{key} is a directory but declares no resource")
            source = self._load_skill(path, key)
        else:
            source = self._load_file(path, key, walked=walked)
            if source is None:
                return None
        self.sources[key] = source
        self._resolve_slots(source)
        return source

    def _load_file(self, path: Path, key: str, *, walked: bool) -> Source | None:
        text = path.read_text(encoding="utf-8")
        markdown = path.suffix.lower() in (".md", ".markdown")
        prose = ""
        try:
            if markdown:
                front, prose = split_frontmatter(text)
                if front is None and walked:
                    return None
                fields = parse_yaml_map(front or "", f"{key} frontmatter")
            else:
                fields = parse_yaml_map(text, key)
        except BootstrapError:
            if walked:
                return None
            raise
        kind = classify(path, fields, markdown=markdown, walked=walked)
        if kind is None:
            return None
        fields.pop("type", None)
        prose_field = "system" if kind == AGENT else "description"
        if prose.strip():
            if prose_field in fields:
                raise BootstrapError(
                    f"{key}: has a Markdown body and also sets `{prose_field}`; keep one"
                )
            fields[prose_field] = prose.strip()
        fields.setdefault("name", path.stem)
        source = Source(key=key, kind=kind, path=path, body=fields)
        self._expand_includes(source)
        return source

    def _load_skill(self, directory: Path, key: str) -> Source:
        manifest = directory / "SKILL.md"
        front, _ = split_frontmatter(manifest.read_text(encoding="utf-8"))
        if front is None:
            raise BootstrapError(f"{manifest}: has no frontmatter")
        fields = parse_yaml_map(front, f"{manifest} frontmatter")
        name = first_string(fields, "name")
        display = (
            first_string(fields, "display_name", "display_title", "title") or name or directory.name
        )
        body: dict[str, Any] = {"display_name": display}
        if name:
            body["name"] = name
        bundle = SkillBundle(
            upload_dir=name or directory.name,
            display_name=display,
            files=collect_skill_files(directory),
        )
        return Source(key=key, kind=SKILL, path=directory, body=body, payload=bundle)

    # includes and references ----------------------------------------------------------------

    def _expand_includes(self, source: Source) -> None:
        for field_name in INCLUDE_FIELDS.get(source.kind, ()):
            raw = source.body.get(field_name)
            if raw is None:
                continue
            if not isinstance(raw, list):
                raise BootstrapError(f"{source.key}: `{field_name}` must be a list")
            out: list[Any] = []
            for index, entry in enumerate(raw):
                if not isinstance(entry, str):
                    out.append(entry)
                    continue
                target = (source.path.parent / entry.strip()).resolve()
                where = f"{source.key}: `{field_name}`[{index}] {entry!r}"
                if target.suffix.lower() not in DATA_EXTENSIONS or not target.is_file():
                    raise BootstrapError(f"{where}: not a .json/.yml/.yaml file on disk")
                if target.parent.name.lower() in KIND_BY_DIR:
                    raise BootstrapError(
                        f"{where}: a data file in a kind directory would be read as a resource; "
                        "move it to a subdirectory such as ./tools/"
                    )
                try:
                    doc = yaml.safe_load(target.read_text(encoding="utf-8"))
                except yaml.YAMLError as exc:
                    raise BootstrapError(f"{where}: {exc}") from exc
                items = doc if isinstance(doc, list) else [doc] if doc is not None else []
                if not all(isinstance(item, dict) for item in items):
                    raise BootstrapError(f"{where}: every included element must be a mapping")
                out.extend(items)
            source.body[field_name] = out

    def _resolve_slots(self, source: Source) -> None:
        for spec in SLOTS[source.kind]:
            raw, present = get_path(source.body, spec.path)
            if not present:
                continue
            if not isinstance(raw, list):
                raise BootstrapError(f"{source.key}: `{spec.path}` must be a list")
            entries: list[RefEntry] = []
            for value in raw:
                entries.append(self._resolve_entry(source, spec, value))
            source.slots.append(Slot(spec=spec, entries=entries))

    def _resolve_entry(self, source: Source, spec: SlotSpec, value: Any) -> RefEntry:
        where = f"{source.key}: `{spec.path}`"
        pinned, extra = True, {}
        if isinstance(value, dict):
            if "path" not in value:
                return RefEntry(value=value)  # a hand-written API object, sent unchanged
            text = value["path"]
            if "version" in value:
                if str(value["version"]).lower() != "latest":
                    raise BootstrapError(f'{where}: `version` next to `path` may only be "latest"')
                pinned = False
            extra = {k: v for k, v in value.items() if k not in ("path", "version")}
        elif isinstance(value, str):
            text = value
        else:
            raise BootstrapError(f"{where}: expected a path, an ID or an object")
        text = text.strip()
        if text.startswith(("http://", "https://")):
            raise BootstrapError(f"{where}: URL references are not supported here; use ant apply")
        inline_kind = kind_for_id(text)
        if inline_kind is not None:
            if inline_kind not in spec.targets:
                raise BootstrapError(f"{where}: {text} is a {inline_kind}")
            encoded = spec.encode(Target(kind=inline_kind, id=text, known=True, pinned=False))
            return RefEntry(value={**encoded, **extra})
        target_path = (source.path.parent / text).resolve()
        if not target_path.exists():
            raise BootstrapError(f"{where}: {text!r} matched nothing on disk")
        target = self._load(target_path, walked=False)
        if target is None or target.kind not in spec.targets:
            raise BootstrapError(f"{where}: {text!r} is not a {' or '.join(spec.targets)}")
        if target.key == source.key:
            raise BootstrapError(f"{where}: a resource cannot reference itself by path")
        return RefEntry(target_key=target.key, pinned=pinned, extra=extra)

    # order ----------------------------------------------------------------------------------

    def topo_order(self) -> list[str]:
        """Dependencies first; ties by kind rank, then key (ant core/graph.go)."""
        order: list[str] = []
        state: dict[str, int] = {}

        def visit(key: str, chain: tuple[str, ...]) -> None:
            if state.get(key) == 2:
                return
            if state.get(key) == 1:
                raise BootstrapError("reference cycle: " + " -> ".join((*chain, key)))
            state[key] = 1
            deps = sorted(set(self.sources[key].deps), key=self._rank)
            for dep in deps:
                visit(dep, (*chain, key))
            state[key] = 2
            order.append(key)

        for key in sorted(self.sources, key=self._rank):
            visit(key, ())
        return order

    def _rank(self, key: str) -> tuple[int, str]:
        return KIND_RANK[self.sources[key].kind], key


def classify(path: Path, fields: Mapping[str, Any], *, markdown: bool, walked: bool) -> str | None:
    """ant's claude/schema.go Classify, for the kinds this project uses."""
    declared = fields.get("type")
    if isinstance(declared, str) and declared.strip() in (SKILL, ENVIRONMENT, AGENT):
        return declared.strip()
    dir_kind = KIND_BY_DIR.get(path.parent.name.lower())
    stem = path.stem.lower()
    file_kind = next(
        (k for k in FILE_KINDS if stem == k or any(stem.startswith(k + s) for s in "_-.")), None
    )
    looks_declared = (dir_kind or file_kind) and (markdown or bool(fields))
    if walked and not looks_declared:
        return None
    if declared is not None:
        raise BootstrapError(f"{path}: unknown type {declared!r}")
    if dir_kind:
        return dir_kind
    if file_kind:
        return file_kind
    if markdown:
        return AGENT
    raise BootstrapError(f"{path}: cannot tell what kind of resource this is")


def first_string(fields: Mapping[str, Any], *keys: str) -> str:
    for key in keys:
        value = fields.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def collect_skill_files(directory: Path) -> tuple[SkillFile, ...]:
    """The bundle, filtered like ant (dotfiles, tooling dirs, symlinks) plus tests."""
    files: list[SkillFile] = []
    total = 0
    for current, dirnames, filenames in os.walk(directory):
        here = Path(current)
        dirnames[:] = sorted(
            name
            for name in dirnames
            if not name.startswith(".")
            and name not in WALK_SKIP_DIRS
            and name not in SKILL_TEST_DIRS
            and not (here / name).is_symlink()
        )
        for name in sorted(filenames):
            path = here / name
            if name.startswith(".") or SKILL_TEST_FILE.match(name) or path.is_symlink():
                continue
            if not path.is_file():
                continue
            size = path.stat().st_size
            if size > MAX_SKILL_FILE:
                raise BootstrapError(f"{path} is over the 16 MiB per-file limit")
            total += size
            if total > MAX_SKILL_TOTAL:
                raise BootstrapError(f"{directory} exceeds the 32 MiB skill limit")
            files.append(SkillFile(path.relative_to(directory).as_posix(), path, size))
            if len(files) > MAX_SKILL_FILES:
                raise BootstrapError(f"{directory} holds more than {MAX_SKILL_FILES} files")
    files.sort(key=lambda item: item.rel_path)
    if not any(item.rel_path == "SKILL.md" for item in files):
        raise BootstrapError(f"{directory} has no SKILL.md at its root")
    return tuple(files)


# --- planning ------------------------------------------------------------------------------------

CREATE, UPDATE, NOOP = "create", "update", "no change"


@dataclass
class Change:
    source: Source
    action: str
    hash: str
    body: dict[str, Any]
    entry: LockEntry | None = None
    remote: dict[str, Any] | None = None
    reasons: list[str] = field(default_factory=list)
    blocked: str | None = None
    unresolved: bool = False

    @property
    def key(self) -> str:
        return self.source.key

    @property
    def kind(self) -> str:
        return self.source.kind


def build_body(source: Source, targets: Mapping[str, Target]) -> tuple[dict[str, Any], bool]:
    """The request body with every reference encoded; True when a placeholder remains."""
    body = copy.deepcopy(source.body)
    unresolved = False
    for slot in source.slots:
        values: list[Any] = []
        for entry in slot.entries:
            if entry.target_key is None:
                values.append(entry.value)
                continue
            target = copy.copy(targets[entry.target_key])
            target.pinned = entry.pinned and target.versioned
            if not target.known or (target.pinned and target.version is None):
                unresolved = True
            encoded = slot.spec.encode(target)
            clash = set(entry.extra) & set(encoded)
            if clash:
                raise BootstrapError(f"{source.key}: {sorted(clash)} are filled in from `path`")
            values.append({**encoded, **entry.extra})
        set_path(body, slot.spec.path, values)
    return body, unresolved


def remote_version(kind: str, remote: Mapping[str, Any] | None) -> str:
    if not remote:
        return ""
    value = remote.get("latest_version_id" if kind == SKILL else "version")
    if kind == ENVIRONMENT or value is None:
        return ""
    return str(value)


def version_value(kind: str, version: str) -> Any:
    if not version:
        return None
    if kind == AGENT:
        try:
            return int(version)
        except ValueError:
            return version
    return version


def target_after(change: Change) -> Target:
    """What dependents will reference once this change is applied: only an unchanged
    resource has a known version yet, so a changing dependency cascades an update."""
    target = Target(kind=change.kind, versioned=change.kind != ENVIRONMENT)
    if change.action == CREATE or change.entry is None:
        return target
    target.known, target.id = True, change.entry.id
    if change.action == NOOP:
        current = remote_version(change.kind, change.remote) or change.entry.version
        target.version = version_value(change.kind, current)
    return target


def plan(
    loader: Loader,
    lock: Lockfile,
    remotes: Mapping[str, tuple[dict[str, Any] | None, str | None]] | None,
    *,
    force: bool,
) -> list[Change]:
    """One Change per source, in apply order. `remotes` is None for a dry run (no network);
    otherwise key -> (remote object, error) where error is "not_found" or None."""
    changes: list[Change] = []
    targets: dict[str, Target] = {}
    for key in loader.topo_order():
        source = loader.sources[key]
        body, unresolved = build_body(source, targets)
        digest_value = source.payload.fingerprint() if source.payload else hash_body(body)
        change = Change(
            source=source, action=CREATE, hash=digest_value, body=body, unresolved=unresolved
        )
        entry = lock.resources.get(key)
        if entry is not None:
            change.entry = entry
            if entry.kind != source.kind:
                change.blocked = (
                    f"this file was a {entry.kind} ({entry.id}) and is now a {source.kind}"
                )
            elif remotes is not None and remotes.get(key, (None, None))[1] == "not_found":
                plan_recreate(change, "is no longer on the server", force)
            else:
                remote = remotes.get(key, (None, None))[0] if remotes is not None else None
                change.remote = remote
                if remote and remote.get("archived_at"):
                    plan_recreate(change, "is archived and cannot be revived", force)
                else:
                    detect_drift(change)
                    if change.hash == entry.hash and not change.reasons and not unresolved:
                        change.action = NOOP
                    else:
                        change.action = UPDATE
                        if change.reasons and not force:
                            change.blocked = (
                                f"{entry.id} changed outside this config since the last apply; "
                                "re-run with --force to overwrite it"
                            )
                    if unresolved and change.action == UPDATE and not change.reasons:
                        change.reasons.append("a referenced resource gets a new version")
        changes.append(change)
        targets[key] = target_after(change)
    return changes


def plan_recreate(change: Change, why: str, force: bool) -> None:
    assert change.entry is not None
    change.reasons.append(f"{change.entry.id} {why}, so it would be created again with a new id")
    change.action, change.entry = CREATE, None
    if not force:
        change.blocked = f"the tracked resource {why}; re-run with --force to create a replacement"


def version_form(version: str) -> str:
    """`id` (`skver_...`, the GA skills API), `epoch` (digits: ant's Beta skills API, and agent
    versions) or `other`."""
    if version.startswith("skver_"):
        return "id"
    return "epoch" if version.isdigit() else "other"


def comparable_versions(kind: str, recorded: str, current: str) -> bool:
    """Whether two versions of one resource can be compared: a skill recorded by ant (Beta API,
    maybe an epoch string) and read back through the GA API (a version id) cannot."""
    return kind != SKILL or version_form(recorded) == version_form(current)


def detect_drift(change: Change) -> None:
    entry, remote = change.entry, change.remote
    if entry is None or remote is None:
        return
    current = remote_version(change.kind, remote)
    if (
        current
        and entry.version
        and current != entry.version
        and comparable_versions(change.kind, entry.version, current)
    ):
        change.reasons.append(
            f"server has version {current} but the lockfile recorded {entry.version}"
        )
        return
    if entry.remote_hash and hash_body(normalize_remote(change.kind, remote)) != entry.remote_hash:
        change.reasons.append("the server's copy no longer matches what the last apply left behind")


# --- the API -------------------------------------------------------------------------------------


class Api:
    """The few calls apply needs, returning the server's JSON (raw, like ant) as dicts."""

    def __init__(self, client: anthropic.Anthropic) -> None:
        self.client = client
        self.once = client.with_options(max_retries=0)

    @staticmethod
    def _json(response: Any) -> dict[str, Any]:
        data = response.http_response.json()
        if not isinstance(data, dict):
            raise BootstrapError("the API returned a non-object body")
        return data

    def origin(self) -> dict[str, str]:
        response = self.client.models.with_raw_response.list(limit=1)
        headers = response.http_response.headers
        origin = {"base_url": str(self.client.base_url).rstrip("/")}
        for header, key in (
            ("anthropic-organization-id", "organization_id"),
            ("anthropic-workspace-id", "workspace_id"),
        ):
            if headers.get(header):
                origin[key] = headers[header]
        return origin

    def get(self, kind: str, resource_id: str) -> dict[str, Any]:
        if kind == SKILL:
            return self._json(self.client.skills.with_raw_response.retrieve(resource_id))
        if kind == ENVIRONMENT:
            return self._json(self.client.beta.environments.with_raw_response.retrieve(resource_id))
        return self._json(self.client.beta.agents.with_raw_response.retrieve(resource_id))

    def create(self, change: Change) -> dict[str, Any]:
        body = change.body
        if change.kind == SKILL:
            return self._json(
                self.once.skills.with_raw_response.create(
                    files=skill_upload(change.source.payload), display_name=body["display_name"]
                )
            )
        rest = {key: value for key, value in body.items() if key not in ("name", "model")}
        if change.kind == ENVIRONMENT:
            return self._json(
                self.once.beta.environments.with_raw_response.create(
                    name=body["name"], extra_body=rest
                )
            )
        return self._json(
            self.once.beta.agents.with_raw_response.create(
                name=body["name"], model=body["model"], extra_body=rest
            )
        )

    def update(self, change: Change) -> dict[str, Any]:
        assert change.entry is not None
        resource_id = change.entry.id
        if change.kind == SKILL:
            obj = self._json(
                self.once.skills.versions.with_raw_response.create(
                    resource_id, files=skill_upload(change.source.payload)
                )
            )
            if "version" not in obj and obj.get("id") and obj["id"] != resource_id:
                obj["version"] = obj["id"]
            return obj
        body = with_clears(change)
        if change.kind == ENVIRONMENT:
            return self._json(
                self.once.beta.environments.with_raw_response.update(resource_id, extra_body=body)
            )
        current = remote_version(AGENT, change.remote)
        if not current:
            raise BootstrapError(
                f"cannot update {resource_id}: the server reported no current version"
            )
        return self._json(
            self.once.beta.agents.with_raw_response.update(
                resource_id, version=int(current), extra_body=body
            )
        )


def skill_upload(bundle: SkillBundle | None) -> list[tuple[str, bytes, str]]:
    if bundle is None:
        raise BootstrapError("a skill write carries no files")
    return [
        (item.upload_name(bundle.upload_dir), item.abs_path.read_bytes(), item.content_type())
        for item in bundle.files
    ]


def with_clears(change: Change) -> dict[str, Any]:
    """The update body plus an explicit null for clearable fields the file no longer sets."""
    body = copy.deepcopy(change.body)
    remote = change.remote or {}
    for name in CLEARABLE.get(change.kind, ()):
        if name not in body and remote.get(name) not in (None, "", [], {}):
            body[name] = None
    remote_metadata = remote.get("metadata") or {}
    if remote_metadata:
        local = dict(body.get("metadata") or {})
        removed = [key for key in remote_metadata if key not in local]
        if removed:
            body["metadata"] = {**local, **dict.fromkeys(removed)}
    return body


# --- apply ---------------------------------------------------------------------------------------


def fetch_remotes(
    api: Api, loader: Loader, lock: Lockfile
) -> dict[str, tuple[dict[str, Any] | None, str | None]]:
    import anthropic

    remotes: dict[str, tuple[dict[str, Any] | None, str | None]] = {}
    for key in loader.sources:
        entry = lock.resources.get(key)
        if entry is None:
            continue
        try:
            remotes[key] = (api.get(entry.kind, entry.id), None)
        except anthropic.NotFoundError:
            remotes[key] = (None, "not_found")
    return remotes


def migrate_legacy_keys(lock: Lockfile, loader: Loader, repo_root: Path) -> list[tuple[str, str]]:
    """Rewrite entries keyed from the repository root by the first bootstrap.py
    (`./profiles/...`, `./skills/...`) to ant's key, relative to the lockfile's directory.

    Only an entry whose key is not a source, whose repository-root reading is a source, and
    whose new key is free moves; anything else is left for the plan to show. Returns
    (old, new) pairs. Without this the entries would look deleted and every resource would
    be created again, with new ids."""
    moved: list[tuple[str, str]] = []
    if loader.key_root == repo_root.resolve():
        return moved  # a lockfile at the repository root: both readings agree
    for key in sorted(lock.resources):
        if key in loader.sources or not key.startswith("./"):
            continue
        new_key = loader.key_for(repo_root / key)
        if new_key in loader.sources and new_key not in lock.resources:
            lock.resources[new_key] = lock.resources.pop(key)
            moved.append((key, new_key))
    return moved


def check_origin(lock: Lockfile, current: Mapping[str, str]) -> None:
    recorded = lock.origin
    if not lock.resources or not recorded:
        return

    def host(url: str) -> str:
        match = re.match(r"^[a-z]+://([^/]+)", url.strip().lower())
        return match.group(1) if match else url.rstrip("/")

    for key, what in (
        ("base_url", "API host"),
        ("organization_id", "organization"),
        ("workspace_id", "workspace"),
    ):
        was, now = recorded.get(key, ""), current.get(key, "")
        if key == "base_url":
            was, now = host(was) if was else "", host(now) if now else ""
        if was and now and was != now:
            raise BootstrapError(
                f"{lock.path} tracks resources on {what} {was}, but the credentials in use target "
                f"{now}"
            )


def apply(api: Api, changes: list[Change], lock: Lockfile, report: Callable[[str], None]) -> None:
    """Execute the plan in order, saving the lockfile after every write."""
    targets: dict[str, Target] = {}
    for change in changes:
        if change.action == NOOP:
            assert change.entry is not None
            if change.hash != change.entry.hash:
                change.entry.hash = change.hash
            targets[change.key] = target_after(change)
            report(f"  unchanged  {change.key}")
            continue
        body, unresolved = build_body(change.source, targets)
        if unresolved:
            raise BootstrapError(
                f"{change.key}: a referenced resource was applied but reported no id or version"
            )
        change.body = body
        digest_value = (
            change.source.payload.fingerprint() if change.source.payload else hash_body(body)
        )
        if change.action == CREATE:
            obj = api.create(change)
            resource_id = obj.get("id")
        else:
            assert change.entry is not None
            obj = api.update(change)
            resource_id = change.entry.id
        if not resource_id or not isinstance(resource_id, str):
            raise BootstrapError(f"{change.key}: the API returned no id")
        if change.kind == SKILL:
            version = str(obj.get("version") or obj.get("latest_version_id") or "")
        else:
            version = remote_version(change.kind, obj)
        entry = LockEntry(kind=change.kind, id=resource_id, version=version, hash=digest_value)
        if change.source.payload is None:
            entry.remote_hash = hash_body(normalize_remote(change.kind, obj))
        lock.resources[change.key] = entry
        lock.save()
        targets[change.key] = Target(
            kind=change.kind,
            id=resource_id,
            version=version_value(change.kind, version),
            known=True,
            versioned=change.kind != ENVIRONMENT,
        )
        report(
            f"  {'created' if change.action == CREATE else 'updated'}  {change.key}  {resource_id}"
            + (f" version {version}" if version else "")
        )
    lock.save()


# --- output --------------------------------------------------------------------------------------


def describe_plan(changes: list[Change], *, show_payloads: bool) -> str:
    lines = []
    for change in changes:
        marker = {CREATE: "+", UPDATE: "~", NOOP: "="}[change.action]
        name = change.body.get("name") or change.body.get("display_name") or ""
        line = f"{marker} {change.action:<9} {change.kind:<11} {change.key}  ({name})"
        if change.entry is not None:
            line += f"  {change.entry.id}"
        lines.append(line)
        lines.extend(f"      because {reason}" for reason in change.reasons)
        if change.blocked:
            lines.append(f"      BLOCKED: {change.blocked}")
        if show_payloads and change.action != NOOP:
            if change.source.payload is not None:
                bundle = change.source.payload
                lines.append(
                    f"      upload {bundle.describe()} as {bundle.upload_dir}/ (display_name "
                    f"{bundle.display_name!r}):"
                )
                lines.extend(
                    f"        {item.upload_name(bundle.upload_dir)}  {item.size} B"
                    for item in bundle.files
                )
            else:
                payload = json.dumps(change.body, indent=2, ensure_ascii=False)
                lines.extend("      " + text for text in payload.splitlines())
    counts = {
        action: sum(1 for c in changes if c.action == action) for action in (CREATE, UPDATE, NOOP)
    }
    lines.append(
        f"Plan: {counts[CREATE]} to create, {counts[UPDATE]} to update, {counts[NOOP]} unchanged."
    )
    return "\n".join(lines)


# --- CLI -----------------------------------------------------------------------------------------


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="bootstrap.py",
        description="Apply profiles/<profile> with the Anthropic SDK and write ant's lockfile.",
    )
    parser.add_argument(
        "--profile", required=True, choices=PROFILES, help="the agent profile to apply (required)"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="print the plan and the payloads; no network"
    )
    parser.add_argument(
        "--yes", action="store_true", help="apply the plan (otherwise only print it)"
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="overwrite out-of-band changes and recreate gone resources",
    )
    parser.add_argument(
        "--i-know-this-is-production",
        dest="production_ok",
        action="store_true",
        help="required with --profile production, dry runs included",
    )
    parser.add_argument(
        "--lock-file",
        type=Path,
        help="default: backend/claude-lock.<profile>.json; keys are relative to its directory",
    )
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT, help=argparse.SUPPRESS)
    parser.add_argument("--skip-render-check", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.profile == "production" and not args.production_ok:
        parser.error("refusing the production profile without --i-know-this-is-production")
    return args


def main(
    argv: list[str] | None = None,
    *,
    client: anthropic.Anthropic | None = None,
    out: Callable[[str], None] = print,
) -> int:
    args = parse_args(argv)
    repo_root: Path = args.repo_root.resolve()
    lock_path = (
        args.lock_file or repo_root / "backend" / f"claude-lock.{args.profile}.json"
    ).resolve()
    try:
        if not args.skip_render_check:
            check_rendered(repo_root)
        loader = Loader(lock_path.parent)
        loader.add_dir(repo_root / "profiles" / args.profile)
        lock = Lockfile.load(lock_path)
        rekeyed = migrate_legacy_keys(lock, loader, repo_root)
        for old, new in rekeyed:
            out(f"  rekey  {old} -> {new}  (keys are relative to the lockfile's directory)")
        if args.dry_run:
            changes = plan(loader, lock, None, force=args.force)
            out(
                f"Dry run of profile {args.profile} against {lock_path} (no network; drift not "
                "checked)."
            )
            out(describe_plan(changes, show_payloads=True))
            return 0
        if client is None:
            import anthropic

            client = anthropic.Anthropic(max_retries=4)
        api = Api(client)
        origin = api.origin()
        check_origin(lock, origin)
        remotes = fetch_remotes(api, loader, lock)
        tracked = [key for key in loader.sources if key in lock.resources]
        if (
            len(tracked) >= 2
            and not args.force
            and all(remotes[k][1] == "not_found" for k in tracked)
        ):
            raise BootstrapError(
                f"none of the {len(tracked)} tracked resources were found with these credentials: "
                "they probably belong to another organization or workspace (use --force if they "
                "were deleted)"
            )
        changes = plan(loader, lock, remotes, force=args.force)
        out(f"Profile {args.profile}, lockfile {lock_path}:")
        out(describe_plan(changes, show_payloads=False))
        blocked = [c for c in changes if c.blocked]
        if blocked:
            out("Refusing to apply: " + "; ".join(f"{c.key}: {c.blocked}" for c in blocked))
            return 1
        if all(c.action == NOOP for c in changes):
            if (
                rekeyed
                or any(c.entry and c.hash != c.entry.hash for c in changes)
                or lock.origin is None
            ):
                lock.origin = lock.origin or origin
                apply(api, changes, lock, out)
            out("Nothing to do.")
            return 0
        if not args.yes:
            out("Re-run with --yes to apply this plan.")
            return 2
        if lock.origin is None:
            lock.origin = origin
        apply(api, changes, lock, out)
        out(f"Applied. Lockfile written: {lock_path}")
        return 0
    except BootstrapError as exc:
        print(f"bootstrap: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        import anthropic

        if not isinstance(exc, anthropic.APIError):
            raise
        status = getattr(exc, "status_code", "")
        print(
            f"bootstrap: the API refused a call ({status} {type(exc).__name__}): {exc}. "
            "The lockfile keeps every write that succeeded; fix the cause and run again.",
            file=sys.stderr,
        )
        return 1


def check_rendered(repo_root: Path) -> None:
    """Refuse to apply generated files that no longer match their templates."""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import render_profiles

    try:
        problems = render_profiles.stale_files(repo_root)
    except render_profiles.RenderError as exc:
        raise BootstrapError(f"cannot render the profiles: {exc}") from exc
    if problems:
        raise BootstrapError(
            "profiles/ is out of date with agents/ (run scripts/render_profiles.py): "
            + ", ".join(problems)
        )


if __name__ == "__main__":
    sys.exit(main())
