"""Helpers shared by the scripts' tests (imported by name: a unique module name, so it never
collides with another directory's conftest when several test trees run in one pytest call)."""

from __future__ import annotations

import itertools
import json
import re
import shutil
import sys
from pathlib import Path
from typing import Any

SCRIPTS_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = SCRIPTS_DIR.parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

CLOSED_PORT_URL = "http://127.0.0.1:9"
SKILLS = ("booking-links", "travel-research-rules", "trip-tracker-schema")
CREDENTIAL_VARS = (
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_AUTH_TOKEN",
    "ANTHROPIC_IDENTITY_TOKEN_FILE",
    "ANTHROPIC_FEDERATION_RULE_ID",
    "ANTHROPIC_ORGANIZATION_ID",
    "ANTHROPIC_PROFILE",
)


def make_fake_repo(tmp_path: Path) -> Path:
    """A copy of the repository's agent sources with stub skills, rendered: what bootstrap
    and the renderer read, isolated from the real tree (other teams write skills/ in parallel)."""
    import render_profiles

    root = tmp_path / "repo"
    (root / "backend").mkdir(parents=True)
    shutil.copytree(REPO_ROOT / "agents", root / "agents")
    shutil.copytree(REPO_ROOT / "schema", root / "schema")
    for name in SKILLS:
        skill = root / "skills" / name
        skill.mkdir(parents=True)
        (skill / "SKILL.md").write_text(
            f"---\nname: {name}\ndescription: Stub {name} skill for tests.\n---\n# {name}\n",
            encoding="utf-8",
        )
    links = root / "skills" / "booking-links"
    (links / "build_link.py").write_text("print('https://www.booking.com/')\n", encoding="utf-8")
    (links / "test_build_link.py").write_text("def test_x():\n    pass\n", encoding="utf-8")
    (links / "__pycache__").mkdir()
    (links / "__pycache__" / "build_link.cpython-312.pyc").write_bytes(b"\x00junk")
    (links / ".DS_Store").write_bytes(b"junk")
    render_profiles.write_outputs(root)
    return root


class FakeAnthropicApi:
    """A tiny in-memory Managed Agents + Skills API behind httpx2.MockTransport."""

    ORG = "org_test"
    WORKSPACE = "wrkspc_test"
    NOW = "2026-10-12T08:00:00Z"

    def __init__(self) -> None:
        self.requests: list[tuple[str, str, Any]] = []
        self.agents: dict[str, dict[str, Any]] = {}
        self.environments: dict[str, dict[str, Any]] = {}
        self.skills: dict[str, dict[str, Any]] = {}
        self.skill_uploads: dict[str, list[str]] = {}
        self._ids = itertools.count(1)
        self.workspace = self.WORKSPACE

    # helpers ------------------------------------------------------------------------------------

    def client(self) -> Any:
        import anthropic
        import httpx2

        return anthropic.Anthropic(
            api_key="sk-ant-test-not-a-key",
            base_url=CLOSED_PORT_URL,
            http_client=httpx2.Client(transport=httpx2.MockTransport(self.handler)),
            max_retries=0,
        )

    def writes(self) -> list[tuple[str, str, Any]]:
        return [r for r in self.requests if r[0] == "POST"]

    def _next(self, prefix: str) -> str:
        return f"{prefix}_{next(self._ids):04d}"

    @staticmethod
    def _error(status: int, kind: str, message: str) -> Any:
        import httpx2

        return httpx2.Response(
            status, json={"type": "error", "error": {"type": kind, "message": message}}
        )

    # the transport ------------------------------------------------------------------------------

    def handler(self, request: Any) -> Any:
        import httpx2

        method, path = request.method, request.url.path
        content_type = request.headers.get("content-type", "")
        body: Any = None
        if request.content and content_type.startswith("application/json"):
            body = json.loads(request.content)
        elif request.content:
            body = re.findall(rb'filename="([^"]+)"', request.content)
            body = [name.decode() for name in body]
        self.requests.append((method, path, body))

        if path == "/v1/models" and method == "GET":
            return httpx2.Response(
                200,
                json={"data": [], "has_more": False, "first_id": None, "last_id": None},
                headers={
                    "anthropic-organization-id": self.ORG,
                    "anthropic-workspace-id": self.workspace,
                },
            )
        if path == "/v1/skills" and method == "POST":
            skill_id, version = self._next("skill"), self._next("skver")
            self.skills[skill_id] = {
                "id": skill_id,
                "type": "skill",
                "display_name": body[0].split("/")[0] if body else "",
                "latest_version_id": version,
                "source": "custom",
                "created_at": self.NOW,
                "updated_at": self.NOW,
            }
            self.skill_uploads[skill_id] = body
            return httpx2.Response(200, json=self.skills[skill_id])
        match = re.fullmatch(r"/v1/skills/([^/]+)/versions", path)
        if match and method == "POST":
            skill = self.skills.get(match.group(1))
            if skill is None:
                return self._error(404, "not_found_error", "no such skill")
            version = self._next("skver")
            skill["latest_version_id"] = version
            self.skill_uploads[skill["id"]] = body
            return httpx2.Response(
                200,
                json={
                    "id": version,
                    "type": "skill_version",
                    "skill_id": skill["id"],
                    "name": skill["display_name"],
                    "description": "",
                    "created_at": self.NOW,
                },
            )
        match = re.fullmatch(r"/v1/skills/([^/]+)", path)
        if match and method == "GET":
            skill = self.skills.get(match.group(1))
            return (
                httpx2.Response(200, json=skill)
                if skill
                else self._error(404, "not_found_error", "nf")
            )

        for collection, prefix, store in (
            ("environments", "env", self.environments),
            ("agents", "agent", self.agents),
        ):
            if path == f"/v1/{collection}" and method == "POST":
                if prefix == "env" and any(e["name"] == body["name"] for e in store.values()):
                    return self._error(
                        409, "invalid_request_error", "environment name already in use"
                    )
                resource_id = self._next(prefix)
                obj = {
                    **body,
                    "id": resource_id,
                    "type": prefix if prefix == "agent" else "environment",
                    "created_at": self.NOW,
                    "updated_at": self.NOW,
                    "archived_at": None,
                }
                if prefix == "agent":
                    obj["version"] = 1
                store[resource_id] = obj
                return httpx2.Response(200, json=obj)
            match = re.fullmatch(rf"/v1/{collection}/([^/]+)/archive", path)
            if match and method == "POST":
                obj = store.get(match.group(1))
                if obj is None:
                    return self._error(404, "not_found_error", "nf")
                obj["archived_at"] = self.NOW
                return httpx2.Response(200, json=obj)
            match = re.fullmatch(rf"/v1/{collection}/([^/]+)", path)
            if match:
                obj = store.get(match.group(1))
                if obj is None:
                    return self._error(404, "not_found_error", "nf")
                if method == "GET":
                    return httpx2.Response(200, json=obj)
                if method == "DELETE":
                    del store[match.group(1)]
                    return httpx2.Response(
                        200, json={"id": obj["id"], "type": f"{obj['type']}_deleted"}
                    )
                if method == "POST":
                    update = dict(body)
                    if prefix == "agent":
                        if update.pop("version", None) != obj["version"]:
                            return self._error(409, "invalid_request_error", "version conflict")
                        obj["version"] += 1
                    for key, value in update.items():
                        if value is None:
                            obj.pop(key, None)
                        else:
                            obj[key] = value
                    return httpx2.Response(200, json=obj)
        return self._error(404, "not_found_error", f"unexpected {method} {path}")
