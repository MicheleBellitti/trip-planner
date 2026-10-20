"""Captures the photos of the recorded choice cards, once, for the demo.

The demo never calls Wikimedia: the photos of the `choices` recording are committed in
web/lib/demo/choice-photos.json, and web/scripts/gen-backend-fixtures.py reads them. This script
makes that file. It needs the network (Wikimedia only) and a migrated Postgres, because the
backend's `CoverResolver` caches in the database. It runs by hand, rarely: when the recording's
`place` fields change.

Run from backend/, with a migrated development database (never production):

    ENVIRONMENT=development AUTH_MODE=local PLANNER_ALLOWED_EMAILS=dev@example.com \\
    DATABASE_URL=postgresql+asyncpg://localhost:5432/trip_planner_cards_dev \\
        uv run python ../web/scripts/capture-choice-photos.py

Look at every photo it lists before committing: each must show its place. Drop a wrong entry
from the JSON by hand (never write photo metadata by hand: it is a licence credit).
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any

import httpx

WEB_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = WEB_DIR.parent
BACKEND_DIR = REPO_ROOT / "backend"
RECORDING = BACKEND_DIR / "tests" / "fixtures" / "ma" / "choices.jsonl"
OUT = WEB_DIR / "lib" / "demo" / "choice-photos.json"

if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app import clock  # noqa: E402
from app.choices import ASK_TRAVELLER_TOOL, ChoiceRequest  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.covers import PLACE_KEY_PREFIX, CoverResolver, PlacePhotos  # noqa: E402
from app.db import create_engine, create_session_factory  # noqa: E402
from app.sessions import PLACE_PHOTO_LOOKUP_SECONDS  # noqa: E402

SOURCE = (
    "Wikimedia Commons through the backend's PlacePhotos (app/covers.py): the free photo "
    "of each option's place in tests/fixtures/ma/choices.jsonl"
)


def asked_requests() -> list[ChoiceRequest]:
    """The `ask_traveller` inputs of the recording, in order."""
    out: list[ChoiceRequest] = []
    for line in RECORDING.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        event: dict[str, Any] = json.loads(line).get("event") or {}
        if event.get("type") == "agent.custom_tool_use" and event.get("name") == ASK_TRAVELLER_TOOL:
            out.append(ChoiceRequest.model_validate(event["input"]))
    return out


async def capture() -> dict[str, Any]:
    settings = get_settings()
    engine = create_engine(settings)
    try:
        async with httpx.AsyncClient(follow_redirects=False) as http:
            photos = PlacePhotos(
                CoverResolver(
                    session_factory=create_session_factory(engine),
                    http=http,
                    user_agent=settings.wikimedia_user_agent,
                    key_prefix=PLACE_KEY_PREFIX,
                    lookup_deadline_seconds=PLACE_PHOTO_LOOKUP_SECONDS,
                )
            )
            found: dict[str, Any] = {}
            for request in asked_requests():
                places = {o.id: o.place for o in request.options if o.place}
                covers = await photos.photos_for(places)
                for option_id in places:
                    cover = covers.get(option_id)
                    print(f"{option_id}: {places[option_id]} -> {cover.url if cover else None}")
                found.update({key: c.model_dump(mode="json") for key, c in covers.items()})
    finally:
        await engine.dispose()
    return {"captured_on": clock.today().isoformat(), "source": SOURCE, "photos": found}


def main() -> int:
    data = asyncio.run(capture())
    if not data["photos"]:
        print("no photo found: is Wikimedia reachable?", file=sys.stderr)
        return 1
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {OUT.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
