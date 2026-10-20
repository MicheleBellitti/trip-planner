"""Destination cover photos (app/covers.py) and GET /plans/{id}/cover (app/routes.py).

Everything is offline: respx answers the Wikipedia and Commons APIs with real responses recorded
once with curl (tests/fixtures/covers/, the same query parameters `covers` sends), under
`assert_all_mocked`, so an unexpected request fails the test. Where a test needs a case the
public APIs cannot produce on demand (a non-free license, an author-less file, an API outage)
it edits a recorded response and says so.
"""

from __future__ import annotations

import asyncio
import copy
import datetime as dt
import json
import uuid
from collections.abc import AsyncIterator, Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app import clock, covers
from app.covers import (
    COVER_TTL,
    MISS_TTL,
    NO_PHOTOS,
    PLACE_KEY_PREFIX,
    TRANSIENT_TTL,
    Cover,
    CoverResolver,
    PlacePhotos,
    cache_key,
    candidate_titles,
    is_free_license,
    is_photo_name,
    parse_commons_cover,
    parse_wikipedia_pages,
    strip_html,
)
from app.db import DestinationCoverRecord, PlanStatus
from tests.conftest import AppFactory, PlanRows, StubPlanner

FIXTURES = Path(__file__).parent / "fixtures" / "covers"
USER_AGENT = "AtlasTripPlanner/1.0 (https://atlas.bellittim.com; personal trip planner)"
SessionFactory = async_sessionmaker[AsyncSession]


def load(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


LISBON_FILE = "Lisboa_-_Portugal_(52597836992).jpg"
ROME_FILE = "Trevi_Fountain,_Rome,_Italy_2_-_May_2007.jpg"
KYOTO_FILE = "Kyoto,_Japan_(49667780482).jpg"


def commons_edit(name: str, **metadata: str | None) -> dict[str, Any]:
    """A recorded Commons answer with some `extmetadata` values replaced (None removes one)."""
    payload = load(name)
    info = payload["query"]["pages"][0]["imageinfo"][0]
    for key, value in metadata.items():
        if value is None:
            info["extmetadata"].pop(key, None)
        else:
            info["extmetadata"][key] = {"value": value, "source": "commons-desc-page"}
    return payload


def with_page_image(payload: dict[str, Any], file: str) -> dict[str, Any]:
    """A recorded Wikipedia answer whose first article's lead image is `file`."""
    edited = copy.deepcopy(payload)
    for page in edited["query"]["pages"]:
        if "pageimage" in page:
            page["pageimage"] = file
            break
    return edited


def missing_wikipedia(titles: str) -> dict[str, Any]:
    return {
        "batchcomplete": True,
        "query": {"pages": [{"ns": 0, "title": t, "missing": True} for t in titles.split("|")]},
    }


# --- pure helpers -------------------------------------------------------------------------------


def test_cache_key_is_the_casefolded_name_with_collapsed_spaces() -> None:
    assert cache_key("  Lisbona,   Portogallo ") == "lisbona, portogallo"
    assert cache_key("ISTANBUL") == cache_key("istanbul")
    assert cache_key("\uff30\uff41\uff52\uff49\uff47\uff49") == "parigi"  # full-width letters, NFKC
    assert cache_key("   ") is None
    assert cache_key("") is None
    assert len(cache_key("a" * 500) or "") == covers.MAX_KEY_LENGTH


@pytest.mark.parametrize(
    ("destination", "expected"),
    [
        ("Lisbona", ["Lisbona"]),
        ("Lisbona, Portogallo", ["Lisbona, Portogallo", "Lisbona"]),
        ("Lisbona (Portogallo)", ["Lisbona (Portogallo)", "Lisbona"]),
        ("Costa Amalfitana / Napoli", ["Costa Amalfitana / Napoli", "Costa Amalfitana"]),
        ("Napoli - Campania", ["Napoli - Campania", "Napoli"]),
        ("Lisbon | File:X", ["Lisbon File:X"]),
        ("  ", []),
    ],
)
def test_candidate_titles(destination: str, expected: list[str]) -> None:
    assert candidate_titles(destination) == expected


def test_candidate_titles_never_contain_the_title_separator() -> None:
    assert all("|" not in title for title in candidate_titles("A|B, C"))


@pytest.mark.parametrize(
    "name",
    [
        LISBON_FILE,
        ROME_FILE,
        "Praça_do_Comércio_-_Lisbon.JPG",
        "Vista.webp",
        "Panorama de Roma.png",
    ],
)
def test_photo_names_are_accepted(name: str) -> None:
    assert is_photo_name(name)


@pytest.mark.parametrize(
    "name",
    [
        "Bandeira_municipal_de_Lisboa.png",
        "Roma-Gonfalone.svg",
        "Flag_of_Kyoto_City.svg",
        "Drapeau_des_armes_de_la_ville_de_Paris.svg",
        "Coat_of_arms_of_Lisbon.png",
        "Stemma_di_Roma_Capitale.png",
        "Logo_Lisboa.jpg",
        "Lisbon_location_map.png",
        "Mappa_di_Roma.jpg",
        "Lisbon.svg",
        "Lisbon.tif",
        "Lisbon.gif",
        "Lisbon",
    ],
)
def test_flags_logos_maps_and_non_photo_formats_are_refused(name: str) -> None:
    assert not is_photo_name(name)


@pytest.mark.parametrize(
    "license_name",
    [
        "CC0",
        "CC0 1.0",
        "Public domain",
        "PD",
        "PD-old-70",
        "CC BY 2.0",
        "CC BY 4.0",
        "CC BY-SA 4.0",
        "CC BY-SA 2.5",
        "CC BY-SA 3.0 IGO",
        "CC BY 3.0 de",
        "CC-BY-SA-4.0",
        "cc by-sa 4.0",
    ],
)
def test_free_licenses_are_accepted(license_name: str) -> None:
    assert is_free_license(license_name)


@pytest.mark.parametrize(
    "license_name",
    [
        "",
        "CC BY-NC 4.0",
        "CC BY-NC-SA 3.0",
        "CC BY-ND 2.0",
        "CC BY-NC-ND 4.0",
        "GFDL",
        "GFDL 1.2",
        "Fair use",
        "Non-free logo",
        "Copyrighted free use",
        "All rights reserved",
        "Attribution",
        "pdf",
        "OGL",
    ],
)
def test_other_licenses_are_refused(license_name: str) -> None:
    assert not is_free_license(license_name)


def test_strip_html_keeps_only_the_text() -> None:
    link = (
        '<a rel="nofollow" class="external text" '
        'href="https://www.flickr.com/people/21446942@N00">Vitor Oliveira</a> '
        "from Torres Vedras, PORTUGAL"
    )
    assert strip_html(link) == "Vitor Oliveira from Torres Vedras, PORTUGAL"
    assert strip_html("<ul><li>Sérgio Horta</li><li>Ornellas e outros</li></ul>") == (
        "Sérgio Horta Ornellas e outros"
    )
    assert strip_html("A &amp; B&nbsp;&eacute;") == "A & B é"
    assert strip_html("<script>alert(1)</script><style>p{}</style>Mario") == "Mario"
    assert strip_html("Mario<br/>Rossi") == "Mario Rossi"
    assert strip_html("1 &lt; 2 &gt; 0") == "1 2 0"
    assert strip_html("<b>unclosed <i>text") == "unclosed text"
    assert strip_html("  \n\t ") == ""
    assert len(strip_html("x" * 1000)) == covers.MAX_AUTHOR_LENGTH


def test_wikipedia_flag_page_has_an_english_title_to_follow() -> None:
    titles = ["Lisbona, Portogallo", "Lisbona"]

    pages = parse_wikipedia_pages(load("wikipedia_it_lisbona"), titles)

    assert [(p.title, p.image_file, p.english_title) for p in pages] == [
        ("Lisbona", "Bandeira_municipal_de_Lisboa.png", "Lisbon")
    ]


def test_wikipedia_redirects_are_followed_and_disambiguations_dropped() -> None:
    titles = ["Rome", "Roma, Italia", "Roma"]

    pages = parse_wikipedia_pages(load("wikipedia_en_rome"), titles)

    # "Roma, Italia" redirects to the page already listed; "Roma" is a disambiguation page.
    assert [(p.title, p.image_file) for p in pages] == [("Rome", ROME_FILE)]


def test_wikipedia_missing_and_disambiguation_answers_have_no_page() -> None:
    assert parse_wikipedia_pages(load("wikipedia_it_missing"), ["Zzqxw Nonexistent City"]) == []
    assert parse_wikipedia_pages(load("wikipedia_it_disambiguation"), ["Lisbon"]) == []


@pytest.mark.parametrize("payload", [{}, {"query": []}, {"query": {"pages": "x"}}, {"query": {}}])
def test_wikipedia_garbage_has_no_page(payload: dict[str, Any]) -> None:
    assert parse_wikipedia_pages(payload, ["A"]) == []


def test_commons_answer_becomes_a_cover_with_the_license_and_author() -> None:
    cover = parse_commons_cover(load("commons_lisbon_cc_by_sa"))

    assert cover == Cover(
        url=(
            "https://upload.wikimedia.org/wikipedia/commons/thumb/f/f2/"
            "Lisboa_-_Portugal_%2852597836992%29.jpg/1920px-Lisboa_-_Portugal_%2852597836992%29.jpg"
        ),
        width=1920,
        height=1231,
        author="Vitor Oliveira from Torres Vedras, PORTUGAL",
        license="CC BY-SA 2.0",
        license_url="https://creativecommons.org/licenses/by-sa/2.0",
        source_page="https://commons.wikimedia.org/wiki/File:Lisboa_-_Portugal_(52597836992).jpg",
        title="Lisboa - Portugal (52597836992)",
    )


def test_cover_carries_no_tracking_query_and_never_the_thumb_host() -> None:
    for name in ("commons_lisbon_cc_by_sa", "commons_rome", "commons_kyoto"):
        cover = parse_commons_cover(load(name))
        assert cover is not None
        assert cover.url.startswith("https://upload.wikimedia.org/")
        assert "?" not in cover.url
        assert "thumb.wikimedia.org" not in cover.url


def test_commons_cc_by_needs_no_url_rewrite_beyond_the_host() -> None:
    cover = parse_commons_cover(load("commons_rome"))

    assert cover is not None
    assert (cover.license, cover.author, cover.width) == ("CC BY 3.0", "Diliff", 1920)
    assert cover.license_url == "https://creativecommons.org/licenses/by/3.0"


def test_public_domain_has_no_license_url_and_html_author_is_stripped() -> None:
    # The recorded flag file is public domain with an <ul><li> author and no license URL.
    cover = parse_commons_cover(load("commons_flag_lisbona"))

    assert cover is not None
    assert cover.license == "Public domain"
    assert cover.license_url is None
    assert cover.author == "Sérgio Horta, a partir de orginal de Ornellas e outros"


def test_a_file_that_is_not_on_commons_has_no_cover() -> None:
    assert parse_commons_cover(load("commons_missing")) is None


@pytest.mark.parametrize(
    "license_name",
    ["CC BY-NC 4.0", "CC BY-NC-SA 2.0", "CC BY-ND 2.0", "GFDL", "Fair use", "Non-free media", ""],
)
def test_non_free_licenses_have_no_cover(license_name: str) -> None:
    payload = commons_edit("commons_lisbon_cc_by_sa", LicenseShortName=license_name)

    assert parse_commons_cover(payload) is None


def test_non_free_and_restricted_files_have_no_cover() -> None:
    assert parse_commons_cover(commons_edit("commons_rome", NonFree="true")) is None
    assert parse_commons_cover(commons_edit("commons_rome", Restrictions="trademarked")) is None
    assert parse_commons_cover(commons_edit("commons_rome", NonFree="false")) is not None


def test_attribution_licenses_need_an_author_public_domain_does_not() -> None:
    assert parse_commons_cover(commons_edit("commons_rome", Artist=None)) is None
    assert parse_commons_cover(commons_edit("commons_rome", Artist="<b> </b>")) is None
    pd = commons_edit("commons_rome", Artist=None, LicenseShortName="Public domain")
    cover = parse_commons_cover(pd)
    assert cover is not None
    assert cover.author is None


def test_html_in_the_license_name_is_stripped_before_the_check() -> None:
    payload = commons_edit("commons_rome", LicenseShortName="<b>CC BY 3.0</b>")

    cover = parse_commons_cover(payload)

    assert cover is not None
    assert cover.license == "CC BY 3.0"


def test_only_photographs_are_accepted_by_mime_type() -> None:
    payload = load("commons_rome")
    payload["query"]["pages"][0]["imageinfo"][0]["mime"] = "image/svg+xml"

    assert parse_commons_cover(payload) is None


def test_images_from_other_hosts_are_refused() -> None:
    payload = load("commons_rome")
    info = payload["query"]["pages"][0]["imageinfo"][0]
    info["thumburl"] = "https://evil.example/thumb/x.jpg"

    assert parse_commons_cover(payload) is None

    del info["thumburl"]
    info["url"] = "https://evil.example/x.jpg"
    # No thumbnail: the original is used, on the upload host, whatever host the API named.
    cover = parse_commons_cover(payload)
    assert cover is not None
    assert cover.url == "https://upload.wikimedia.org/x.jpg"


def test_without_a_thumbnail_the_original_and_its_size_are_used() -> None:
    payload = load("commons_rome")
    info = payload["query"]["pages"][0]["imageinfo"][0]
    for key in ("thumburl", "thumbwidth", "thumbheight"):
        info.pop(key, None)

    cover = parse_commons_cover(payload)

    assert cover is not None
    assert (cover.width, cover.height) == (3500, 2325)
    assert cover.url.endswith("/7/7e/Trevi_Fountain%2C_Rome%2C_Italy_2_-_May_2007.jpg")


def test_the_source_page_is_built_when_the_api_omits_it() -> None:
    payload = load("commons_rome")
    del payload["query"]["pages"][0]["imageinfo"][0]["descriptionurl"]

    cover = parse_commons_cover(payload)

    assert cover is not None
    assert cover.source_page == (
        "https://commons.wikimedia.org/wiki/File:Trevi_Fountain,_Rome,_Italy_2_-_May_2007.jpg"
    )


@pytest.mark.parametrize("payload", [{}, {"query": {}}, {"query": {"pages": []}}, {"query": 3}])
def test_commons_garbage_has_no_cover(payload: dict[str, Any]) -> None:
    assert parse_commons_cover(payload) is None


def test_cover_model_refuses_foreign_hosts_and_schemes() -> None:
    good: dict[str, Any] = {
        "url": "https://upload.wikimedia.org/wikipedia/commons/a/ab/X.jpg",
        "width": 10,
        "height": 10,
        "license": "CC0",
        "source_page": "https://commons.wikimedia.org/wiki/File:X.jpg",
        "title": "X",
    }
    assert Cover(**good).author is None
    for field_name, bad in [
        ("url", "http://upload.wikimedia.org/x.jpg"),
        ("url", "https://upload.wikimedia.org.evil.example/x.jpg"),
        ("url", "https://user@upload.wikimedia.org/x.jpg"),
        ("url", "https://thumb.wikimedia.org/x.jpg"),
        ("source_page", "https://evil.example/wiki/File:X.jpg"),
        ("license_url", "javascript:alert(1)"),
    ]:
        with pytest.raises(ValidationError):
            Cover(**{**good, field_name: bad})


# --- a fake Wikimedia -----------------------------------------------------------------------------


@dataclass
class Wikimedia:
    """Answers the Wikipedia and Commons APIs from recorded responses and keeps the requests."""

    wikipedia: dict[str, dict[str, Any]] = field(default_factory=dict[str, dict[str, Any]])
    commons: dict[str, dict[str, Any]] = field(default_factory=dict[str, dict[str, Any]])
    failure: httpx.Response | Exception | None = None
    requests: list[httpx.Request] = field(default_factory=list[httpx.Request])

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.failure is not None:
            if isinstance(self.failure, Exception):
                raise self.failure
            return self.failure
        params = request.url.params
        if request.url.host == "commons.wikimedia.org":
            file = params["titles"].removeprefix("File:")
            return httpx.Response(200, json=self.commons.get(file, load("commons_missing")))
        language = request.url.host.split(".")[0]
        payload = self.wikipedia.get(language) or missing_wikipedia(params["titles"])
        return httpx.Response(200, json=payload)

    def hosts(self) -> list[str]:
        return [request.url.host for request in self.requests]


@pytest.fixture
def wikimedia() -> Iterator[Wikimedia]:
    fake = Wikimedia()
    with respx.mock(assert_all_called=False, assert_all_mocked=True) as router:
        router.get(host__regex=r"^((it|en)\.wikipedia\.org|commons\.wikimedia\.org)$").mock(
            side_effect=fake
        )
        yield fake


def lisbon(wikimedia: Wikimedia) -> Wikimedia:
    """Lisbon as the APIs answer today: the Italian article's image is a flag, the English
    one's is a CC BY-SA photograph."""
    wikimedia.wikipedia = {"it": load("wikipedia_it_lisbona"), "en": load("wikipedia_en_lisbon")}
    wikimedia.commons = {
        "Bandeira_municipal_de_Lisboa.png": load("commons_flag_lisbona"),
        LISBON_FILE: load("commons_lisbon_cc_by_sa"),
    }
    return wikimedia


@dataclass
class FakeClock:
    now: dt.datetime = dt.datetime(2026, 10, 12, 12, 0, tzinfo=clock.HOME_TIMEZONE)

    def advance(self, delta: dt.timedelta) -> None:
        self.now += delta


@pytest.fixture
def frozen_clock(monkeypatch: pytest.MonkeyPatch) -> FakeClock:
    fake = FakeClock()
    monkeypatch.setattr(clock, "now", lambda: fake.now)
    return fake


@pytest.fixture
async def http() -> AsyncIterator[httpx.AsyncClient]:
    async with httpx.AsyncClient() as client:
        yield client


@pytest.fixture
def make_resolver(
    db_session_factory: SessionFactory, http: httpx.AsyncClient
) -> Callable[..., CoverResolver]:
    def factory(**overrides: Any) -> CoverResolver:
        options: dict[str, Any] = {
            "session_factory": db_session_factory,
            "http": http,
            "user_agent": USER_AGENT,
        }
        return CoverResolver(**{**options, **overrides})

    return factory


async def stored(db_session_factory: SessionFactory) -> dict[str, DestinationCoverRecord]:
    async with db_session_factory() as db:
        rows = (await db.scalars(select(DestinationCoverRecord))).all()
    return {row.destination_key: row for row in rows}


# --- the resolver ---------------------------------------------------------------------------------


async def test_lisbon_skips_the_italian_flag_and_finds_the_english_photograph(
    wikimedia: Wikimedia, make_resolver: Callable[..., CoverResolver]
) -> None:
    lisbon(wikimedia)

    cover = await make_resolver().get("Lisbona, Portogallo")

    assert cover is not None
    assert cover.license == "CC BY-SA 2.0"
    assert cover.author == "Vitor Oliveira from Torres Vedras, PORTUGAL"
    assert cover.url.startswith("https://upload.wikimedia.org/wikipedia/commons/thumb/f/f2/")
    # it.wikipedia (the flag is skipped by name, no Commons call), en.wikipedia, then Commons.
    assert wikimedia.hosts() == ["it.wikipedia.org", "en.wikipedia.org", "commons.wikimedia.org"]
    italian, english, commons = (request.url.params for request in wikimedia.requests)
    assert italian["titles"] == "Lisbona, Portogallo|Lisbona"
    assert italian["lllang"] == "en"
    assert english["titles"] == "Lisbon|Lisbona, Portogallo|Lisbona"  # the English title first
    assert "langlinks" not in english["prop"]
    assert commons["titles"] == f"File:{LISBON_FILE}"
    assert commons["iiurlwidth"] == "1920"


async def test_only_the_destination_name_leaves_the_backend(
    wikimedia: Wikimedia, make_resolver: Callable[..., CoverResolver]
) -> None:
    lisbon(wikimedia)

    await make_resolver().get("Lisbona, Portogallo")

    for request in wikimedia.requests:
        assert request.method == "GET"
        assert request.url.scheme == "https"
        assert request.headers["User-Agent"] == USER_AGENT
        assert "cookie" not in request.headers
        assert "authorization" not in request.headers
        assert not request.content
        assert request.url.params["action"] == "query"
        text = str(request.url).lower()
        for private in ("test@example.com", "milano", "budget", "adult", "2027"):
            assert private not in text


async def test_a_page_image_that_is_a_photo_is_used_without_looking_further(
    wikimedia: Wikimedia, make_resolver: Callable[..., CoverResolver]
) -> None:
    wikimedia.wikipedia = {"it": with_page_image(load("wikipedia_it_roma"), ROME_FILE)}
    wikimedia.commons = {ROME_FILE: load("commons_rome")}

    cover = await make_resolver().get("Roma, Italia")

    assert cover is not None
    assert cover.license == "CC BY 3.0"
    assert wikimedia.hosts() == ["it.wikipedia.org", "commons.wikimedia.org"]


async def test_rome_follows_the_interlanguage_link_past_the_gonfalone(
    wikimedia: Wikimedia, make_resolver: Callable[..., CoverResolver]
) -> None:
    wikimedia.wikipedia = {"it": load("wikipedia_it_roma"), "en": load("wikipedia_en_rome")}
    wikimedia.commons = {ROME_FILE: load("commons_rome")}

    cover = await make_resolver().get("Roma, Italia")

    assert cover is not None
    assert cover.title == "Trevi Fountain, Rome, Italy 2 - May 2007"
    assert wikimedia.requests[1].url.params["titles"].startswith("Rome|")


async def test_a_refused_license_moves_on_to_the_next_image(
    wikimedia: Wikimedia, make_resolver: Callable[..., CoverResolver]
) -> None:
    lisbon(wikimedia)
    wikimedia.wikipedia["it"] = with_page_image(load("wikipedia_it_lisbona"), "Lisboa_nc.jpg")
    wikimedia.commons["Lisboa_nc.jpg"] = commons_edit(
        "commons_lisbon_cc_by_sa", LicenseShortName="CC BY-NC 2.0"
    )

    cover = await make_resolver().get("Lisbona")

    assert cover is not None
    assert cover.license == "CC BY-SA 2.0"
    assert wikimedia.hosts() == [
        "it.wikipedia.org",
        "commons.wikimedia.org",  # the non-commercial photo: refused
        "en.wikipedia.org",
        "commons.wikimedia.org",
    ]


async def test_a_local_fair_use_file_is_refused_because_commons_does_not_have_it(
    wikimedia: Wikimedia, make_resolver: Callable[..., CoverResolver]
) -> None:
    wikimedia.wikipedia = {"it": with_page_image(load("wikipedia_it_lisbona"), "Foto_locale.jpg")}

    cover = await make_resolver().get("Lisbona")

    assert cover is None
    assert wikimedia.hosts() == ["it.wikipedia.org", "commons.wikimedia.org", "en.wikipedia.org"]


async def test_only_a_few_files_are_looked_up(
    wikimedia: Wikimedia,
    make_resolver: Callable[..., CoverResolver],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(covers, "MAX_COMMONS_LOOKUPS", 1)
    lisbon(wikimedia)
    wikimedia.wikipedia["it"] = with_page_image(load("wikipedia_it_lisbona"), "Foto_locale.jpg")

    assert await make_resolver().get("Lisbona") is None
    assert wikimedia.hosts().count("commons.wikimedia.org") == 1


async def test_a_found_cover_is_asked_once_and_then_served_from_memory_and_the_table(
    wikimedia: Wikimedia,
    make_resolver: Callable[..., CoverResolver],
    db_session_factory: SessionFactory,
) -> None:
    lisbon(wikimedia)
    resolver = make_resolver()
    first = await resolver.get("Lisbona, Portogallo")
    asked = len(wikimedia.requests)

    again = await resolver.get("  LISBONA,  portogallo ")
    after_restart = await make_resolver().get("Lisbona, Portogallo")

    assert first is not None
    assert again == first
    assert after_restart == first
    assert len(wikimedia.requests) == asked  # not one request more
    rows = await stored(db_session_factory)
    assert list(rows) == ["lisbona, portogallo"]
    assert rows["lisbona, portogallo"].cover == first.model_dump(mode="json")


async def test_a_cover_is_refreshed_after_thirty_days(
    wikimedia: Wikimedia, make_resolver: Callable[..., CoverResolver], frozen_clock: FakeClock
) -> None:
    lisbon(wikimedia)
    resolver = make_resolver()
    await resolver.get("Lisbona")
    asked = len(wikimedia.requests)

    frozen_clock.advance(COVER_TTL - dt.timedelta(minutes=1))
    await resolver.get("Lisbona")
    assert len(wikimedia.requests) == asked

    frozen_clock.advance(dt.timedelta(minutes=2))
    await resolver.get("Lisbona")
    assert len(wikimedia.requests) > asked


async def test_a_miss_is_cached_briefly(
    wikimedia: Wikimedia,
    make_resolver: Callable[..., CoverResolver],
    db_session_factory: SessionFactory,
    frozen_clock: FakeClock,
) -> None:
    resolver = make_resolver()
    assert await resolver.get("Lisbona") is None  # Wikimedia knows no such page (yet)
    asked = len(wikimedia.requests)
    assert asked == 2  # it and en: no page, so no Commons call
    rows = await stored(db_session_factory)
    assert rows["lisbona"].cover is None

    assert await make_resolver().get("Lisbona") is None
    assert len(wikimedia.requests) == asked

    frozen_clock.advance(MISS_TTL + dt.timedelta(minutes=1))
    assert await make_resolver().get("Lisbona") is None
    assert len(wikimedia.requests) == asked * 2

    # The place got a photo in the meantime: the retry finds it and replaces the cached miss.
    lisbon(wikimedia)
    frozen_clock.advance(MISS_TTL + dt.timedelta(minutes=1))
    assert await make_resolver().get("Lisbona") is not None
    rows = await stored(db_session_factory)
    assert rows["lisbona"].cover is not None


async def test_a_disambiguation_page_is_no_destination(
    wikimedia: Wikimedia, make_resolver: Callable[..., CoverResolver]
) -> None:
    wikimedia.wikipedia = {"it": load("wikipedia_it_disambiguation")}

    assert await make_resolver().get("Lisbon") is None


@pytest.mark.parametrize(
    "failure",
    [
        httpx.Response(503, text="maintenance"),
        httpx.Response(429, json={"error": "slow down"}),
        httpx.Response(200, text="<html>not json</html>"),
        httpx.Response(200, json=[1, 2]),
        httpx.Response(200, json={"error": {"code": "ratelimited", "info": "slow down"}}),
        httpx.ConnectTimeout("too slow"),
        httpx.ReadError("reset"),
    ],
    ids=["503", "429", "html", "list", "api-error", "timeout", "read-error"],
)
async def test_a_wikimedia_failure_is_no_cover_not_an_error_and_is_not_stored(
    wikimedia: Wikimedia,
    make_resolver: Callable[..., CoverResolver],
    db_session_factory: SessionFactory,
    frozen_clock: FakeClock,
    failure: httpx.Response | Exception,
) -> None:
    lisbon(wikimedia)
    wikimedia.failure = failure
    resolver = make_resolver()

    assert await resolver.get("Lisbona") is None
    assert len(wikimedia.requests) == 1  # no retries, and the lookup stopped at the failure
    assert await stored(db_session_factory) == {}

    # Not asked again for a couple of minutes ...
    assert await resolver.get("Lisbona") is None
    assert len(wikimedia.requests) == 1

    # ... then the next view tries again and, if Wikimedia is back, gets the photo.
    wikimedia.failure = None
    frozen_clock.advance(TRANSIENT_TTL + dt.timedelta(seconds=1))
    assert await resolver.get("Lisbona") is not None


async def test_a_stale_cover_is_kept_while_the_refresh_fails(
    wikimedia: Wikimedia,
    make_resolver: Callable[..., CoverResolver],
    db_session_factory: SessionFactory,
    frozen_clock: FakeClock,
) -> None:
    lisbon(wikimedia)
    first = await make_resolver().get("Lisbona")
    frozen_clock.advance(COVER_TTL + dt.timedelta(days=1))
    wikimedia.failure = httpx.Response(503)

    stale = await make_resolver().get("Lisbona")

    assert stale == first
    rows = await stored(db_session_factory)
    assert rows["lisbona"].cover is not None  # the old row stays for the next refresh


async def test_concurrent_requests_for_one_destination_share_one_lookup(
    wikimedia: Wikimedia, make_resolver: Callable[..., CoverResolver]
) -> None:
    lisbon(wikimedia)
    resolver = make_resolver()

    results = await asyncio.gather(*(resolver.get("Lisbona, Portogallo") for _ in range(8)))

    assert all(result == results[0] and result is not None for result in results)
    assert len(wikimedia.requests) == 3


async def test_a_broken_table_does_not_break_the_lookup(
    wikimedia: Wikimedia, make_resolver: Callable[..., CoverResolver]
) -> None:
    lisbon(wikimedia)

    def down() -> Any:
        raise OSError("database is down")

    resolver = make_resolver(session_factory=down)

    assert await resolver.get("Lisbona") is not None
    assert await resolver.get("Lisbona") is not None  # still cached, in memory
    assert len(wikimedia.requests) == 3


async def test_a_stored_cover_with_a_foreign_host_is_ignored(
    wikimedia: Wikimedia,
    make_resolver: Callable[..., CoverResolver],
    db_session_factory: SessionFactory,
) -> None:
    lisbon(wikimedia)
    bad = Cover.model_construct(
        url="https://evil.example/x.jpg",
        width=1,
        height=1,
        author=None,
        license="CC0",
        license_url=None,
        source_page="https://commons.wikimedia.org/wiki/File:X.jpg",
        title="X",
    )
    async with db_session_factory() as db:
        db.add(DestinationCoverRecord(destination_key="lisbona", cover=bad.model_dump()))
        await db.commit()

    cover = await make_resolver().get("Lisbona")

    assert cover is not None
    assert cover.url.startswith("https://upload.wikimedia.org/")
    assert len(wikimedia.requests) == 3


async def test_nothing_ever_escapes_the_resolver(
    make_resolver: Callable[..., CoverResolver], monkeypatch: pytest.MonkeyPatch
) -> None:
    async def explode(self: CoverResolver, destination: str) -> Cover | None:
        raise RuntimeError("boom")

    monkeypatch.setattr(CoverResolver, "_lookup", explode)

    assert await make_resolver().get("Lisbona") is None
    assert await make_resolver().get("   ") is None


async def test_a_slow_lookup_gives_up_at_the_deadline(
    make_resolver: Callable[..., CoverResolver], monkeypatch: pytest.MonkeyPatch
) -> None:
    async def forever(self: CoverResolver, destination: str) -> Cover | None:
        await asyncio.sleep(3600)

    monkeypatch.setattr(CoverResolver, "_lookup", forever)
    monkeypatch.setattr(covers, "LOOKUP_DEADLINE_SECONDS", 0.05)

    assert await make_resolver().get("Lisbona") is None


# --- GET /plans/{id}/cover ------------------------------------------------------------------------

USER = "test@example.com"


@dataclass
class Api:
    client: httpx.AsyncClient
    app: Any


@pytest.fixture
async def api(
    make_app: AppFactory,
    stub_planner: StubPlanner,
    db_session_factory: Any,  # prepares and empties the test database
) -> AsyncIterator[Api]:
    async with make_app() as app:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            yield Api(client, app)


def error(response: httpx.Response) -> dict[str, Any]:
    body = response.json()
    assert set(body) == {"detail"}
    assert set(body["detail"]) == {"code", "message", "data"}
    return body["detail"]


async def test_the_cover_of_a_ready_plan_uses_the_plans_destination(
    api: Api, wikimedia: Wikimedia, plan_rows: PlanRows
) -> None:
    lisbon(wikimedia)
    record = await plan_rows.add_plan(
        status=PlanStatus.READY,
        plan={"title": "Lisbona, quattro giorni", "destination": "Lisbona, Portogallo"},
        request={"destination": "Portogallo"},
    )

    response = await api.client.get(f"/plans/{record.id}/cover")

    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "private, max-age=3600"
    body = response.json()
    assert set(body) == {
        "url",
        "width",
        "height",
        "author",
        "license",
        "license_url",
        "source_page",
        "title",
    }
    assert body["license"] == "CC BY-SA 2.0"
    assert body["author"] == "Vitor Oliveira from Torres Vedras, PORTUGAL"
    assert (body["width"], body["height"]) == (1920, 1231)
    assert body["url"].startswith("https://upload.wikimedia.org/")
    assert wikimedia.requests[0].url.params["titles"] == "Lisbona, Portogallo|Lisbona"
    # The user's user agent is the configured contact, not the browser's.
    assert wikimedia.requests[0].headers["User-Agent"].startswith("AtlasTripPlanner/")


async def test_a_plan_still_running_uses_the_requests_destination(
    api: Api, wikimedia: Wikimedia, plan_rows: PlanRows
) -> None:
    lisbon(wikimedia)
    record = await plan_rows.add_plan(request={"destination": "Lisbona"})

    response = await api.client.get(f"/plans/{record.id}/cover")

    assert response.status_code == 200
    assert wikimedia.requests[0].url.params["titles"] == "Lisbona"


async def test_a_ready_plan_without_a_destination_falls_back_to_the_request(
    api: Api, wikimedia: Wikimedia, plan_rows: PlanRows
) -> None:
    lisbon(wikimedia)
    record = await plan_rows.add_plan(
        status=PlanStatus.READY,
        plan={"title": "x", "destination": "  "},
        request={"destination": "Lisbona"},
    )

    assert (await api.client.get(f"/plans/{record.id}/cover")).status_code == 200
    assert wikimedia.requests[0].url.params["titles"] == "Lisbona"


async def test_the_planners_choice_has_no_cover_until_the_plan_is_ready(
    api: Api, wikimedia: Wikimedia, plan_rows: PlanRows
) -> None:
    suggest = {"suggest_destination": True, "destination": None}
    running = await plan_rows.add_plan(request=suggest)
    failed = await plan_rows.add_plan(status=PlanStatus.FAILED, request=suggest)

    for record in (running, failed):
        response = await api.client.get(f"/plans/{record.id}/cover")
        assert response.status_code == 404
        assert error(response) == {
            "code": "cover_unavailable",
            "message": "Per questa destinazione non c'è una foto.",
            "data": None,
        }
    assert wikimedia.requests == []  # nothing to ask Wikimedia about

    lisbon(wikimedia)
    ready = await plan_rows.add_plan(
        status=PlanStatus.READY,
        request=suggest,
        plan={"title": "x", "destination": "Lisbona, Portogallo"},
    )
    assert (await api.client.get(f"/plans/{ready.id}/cover")).status_code == 200


async def test_a_destination_without_a_free_photo_is_404_cover_unavailable(
    api: Api, wikimedia: Wikimedia, plan_rows: PlanRows
) -> None:
    record = await plan_rows.add_plan(request={"destination": "Zzqxw Nonexistent City"})

    response = await api.client.get(f"/plans/{record.id}/cover")

    assert response.status_code == 404
    assert error(response)["code"] == "cover_unavailable"
    assert "Cache-Control" not in response.headers


async def test_wikimedia_being_down_is_404_cover_unavailable_too(
    api: Api, wikimedia: Wikimedia, plan_rows: PlanRows
) -> None:
    wikimedia.failure = httpx.ConnectError("no route")
    record = await plan_rows.add_plan(request={"destination": "Lisbona"})

    response = await api.client.get(f"/plans/{record.id}/cover")

    assert response.status_code == 404
    assert error(response)["code"] == "cover_unavailable"


async def test_the_second_plan_for_a_destination_does_not_ask_wikimedia_again(
    api: Api, wikimedia: Wikimedia, plan_rows: PlanRows
) -> None:
    lisbon(wikimedia)
    first = await plan_rows.add_plan(request={"destination": "Lisbona"})
    second = await plan_rows.add_plan(request={"destination": "lisbona "})

    assert (await api.client.get(f"/plans/{first.id}/cover")).status_code == 200
    asked = len(wikimedia.requests)
    assert (await api.client.get(f"/plans/{second.id}/cover")).status_code == 200
    assert len(wikimedia.requests) == asked


async def test_another_users_plan_and_an_unknown_plan_are_404_plan_not_found(
    api: Api, wikimedia: Wikimedia, plan_rows: PlanRows
) -> None:
    other = await plan_rows.add_plan(
        user_email="other@example.com", request={"destination": "Lisbona"}
    )

    for plan_id in (other.id, uuid.uuid4()):
        response = await api.client.get(f"/plans/{plan_id}/cover")
        assert response.status_code == 404
        assert error(response)["code"] == "plan_not_found"
    assert wikimedia.requests == []


async def test_the_cover_route_needs_a_session(
    make_app: AppFactory,
    make_settings: Callable[..., Any],
    stub_planner: StubPlanner,
    db_session_factory: Any,
) -> None:
    async with make_app(settings=make_settings(auth_mode="triptracker")) as app:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            response = await client.get(f"/plans/{uuid.uuid4()}/cover")

    assert response.status_code == 401
    assert error(response)["code"] == "not_authenticated"


async def test_the_frontend_may_read_the_cover_across_origins(
    api: Api, wikimedia: Wikimedia, plan_rows: PlanRows
) -> None:
    lisbon(wikimedia)
    record = await plan_rows.add_plan(request={"destination": "Lisbona"})

    response = await api.client.get(
        f"/plans/{record.id}/cover", headers={"Origin": "https://atlas.bellittim.com"}
    )

    assert response.headers["access-control-allow-origin"] == "https://atlas.bellittim.com"
    assert response.headers["access-control-allow-credentials"] == "true"


def test_user_agent_names_the_app_and_a_contact(make_settings: Callable[..., Any]) -> None:
    assert make_settings().wikimedia_user_agent == USER_AGENT
    custom = make_settings(wikimedia_contact_url="mailto:atlas@example.org")
    assert (
        custom.wikimedia_user_agent
        == "AtlasTripPlanner/1.0 (mailto:atlas@example.org; personal trip planner)"
    )
    with pytest.raises(ValueError, match="WIKIMEDIA_CONTACT_URL"):
        make_settings(wikimedia_contact_url="atlas@example.org")


# --- place photos ---------------------------------------------------------------------------------


@pytest.fixture
def make_place_photos(
    make_resolver: Callable[..., CoverResolver],
) -> Callable[..., PlacePhotos]:
    def factory(*, deadline_seconds: float = 3.0, **resolver_options: Any) -> PlacePhotos:
        resolver = make_resolver(
            key_prefix=PLACE_KEY_PREFIX,
            lookup_deadline_seconds=deadline_seconds,
            **resolver_options,
        )
        return PlacePhotos(resolver, deadline_seconds=deadline_seconds)

    return factory


def lisbon_only(delay: float = 0.0, slow: str = "") -> Callable[[httpx.Request], Any]:
    """A Wikimedia fake that knows Lisbon and nothing else; the Wikipedia route of a title
    containing `slow` sleeps `delay` seconds first."""
    recorded = {
        "it": load("wikipedia_it_lisbona"),
        "en": load("wikipedia_en_lisbon"),
    }
    commons = {
        "Bandeira_municipal_de_Lisboa.png": load("commons_flag_lisbona"),
        LISBON_FILE: load("commons_lisbon_cc_by_sa"),
    }

    async def answer(request: httpx.Request) -> httpx.Response:
        params = request.url.params
        if request.url.host == "commons.wikimedia.org":
            file = params["titles"].removeprefix("File:")
            return httpx.Response(200, json=commons.get(file, load("commons_missing")))
        titles = params["titles"]
        if slow and slow in titles:
            await asyncio.sleep(delay)
        if "lisbona" in titles.lower():
            return httpx.Response(200, json=recorded[request.url.host.split(".")[0]])
        return httpx.Response(200, json=missing_wikipedia(titles))

    return answer


@pytest.fixture
def lisbon_wikimedia() -> Iterator[respx.MockRouter]:
    with respx.mock(assert_all_called=False, assert_all_mocked=True) as router:
        yield router


async def test_place_photos_finds_a_place(
    wikimedia: Wikimedia, make_place_photos: Callable[..., PlacePhotos]
) -> None:
    lisbon(wikimedia)

    photos = await make_place_photos().photos_for({"a1": "Lisbona"})

    assert set(photos) == {"a1"}
    assert photos["a1"].license == "CC BY-SA 2.0"
    assert photos["a1"].url.startswith("https://upload.wikimedia.org/")


async def test_place_photos_leaves_out_a_place_without_a_free_photo(
    lisbon_wikimedia: respx.MockRouter, make_place_photos: Callable[..., PlacePhotos]
) -> None:
    lisbon_wikimedia.get(host__regex=r"wikipedia\.org|commons\.wikimedia\.org").mock(
        side_effect=lisbon_only()
    )

    photos = await make_place_photos().photos_for({"a1": "Lisbona", "a2": "Zzyzx Nowhere"})

    assert set(photos) == {"a1"}


async def test_two_options_with_one_place_share_a_lookup(
    wikimedia: Wikimedia, make_place_photos: Callable[..., PlacePhotos]
) -> None:
    lisbon(wikimedia)

    photos = await make_place_photos().photos_for({"a1": "Lisbona", "a2": "  lisbona "})

    assert set(photos) == {"a1", "a2"}
    assert photos["a1"] == photos["a2"]
    assert wikimedia.hosts().count("commons.wikimedia.org") == 1


async def test_place_photos_returns_what_is_found_by_the_deadline(
    lisbon_wikimedia: respx.MockRouter, make_place_photos: Callable[..., PlacePhotos]
) -> None:
    lisbon_wikimedia.get(host__regex=r"wikipedia\.org|commons\.wikimedia\.org").mock(
        side_effect=lisbon_only(delay=5.0, slow="Lentissimo")
    )
    loop = asyncio.get_running_loop()
    started = loop.time()

    photos = await make_place_photos(deadline_seconds=0.2).photos_for(
        {"a1": "Lisbona", "a2": "Lentissimo"}
    )

    assert set(photos) == {"a1"}
    assert loop.time() - started < 0.7


async def test_place_photos_cancel_unfinished_lookups(
    lisbon_wikimedia: respx.MockRouter, make_place_photos: Callable[..., PlacePhotos]
) -> None:
    lisbon_wikimedia.get(host__regex=r"wikipedia\.org|commons\.wikimedia\.org").mock(
        side_effect=lisbon_only(delay=5.0, slow="Lentissimo")
    )
    before = asyncio.all_tasks()

    await make_place_photos(deadline_seconds=0.1).photos_for({"a2": "Lentissimo"})

    assert asyncio.all_tasks() <= before


async def test_place_photos_with_no_places_creates_no_task(
    make_place_photos: Callable[..., PlacePhotos], monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse(*_: Any, **__: Any) -> None:
        raise AssertionError("no task expected")

    monkeypatch.setattr(asyncio, "create_task", refuse)

    assert await make_place_photos().photos_for({}) == {}


async def test_place_keys_do_not_collide_with_destination_covers(
    wikimedia: Wikimedia,
    make_resolver: Callable[..., CoverResolver],
    db_session_factory: SessionFactory,
) -> None:
    lisbon(wikimedia)
    destinations = make_resolver()
    places = make_resolver(key_prefix=PLACE_KEY_PREFIX)

    assert await destinations.get("Lisbona") is not None
    assert await places.get("Lisbona") is not None

    assert set(await stored(db_session_factory)) == {"lisbona", "place:lisbona"}


async def test_place_photos_send_only_the_place_name(
    wikimedia: Wikimedia, make_place_photos: Callable[..., PlacePhotos]
) -> None:
    lisbon(wikimedia)

    await make_place_photos().photos_for({"a1": "Lisbona, Portogallo"})

    wikipedia = [r for r in wikimedia.requests if r.url.host.endswith("wikipedia.org")]
    assert wikipedia
    assert wikipedia[0].url.params["titles"] == "Lisbona, Portogallo|Lisbona"
    assert "a1" not in str(wikipedia[0].url)


async def test_place_photos_log_counts_only(
    lisbon_wikimedia: respx.MockRouter,
    make_place_photos: Callable[..., PlacePhotos],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lisbon_wikimedia.get(host__regex=r"wikipedia\.org|commons\.wikimedia\.org").mock(
        side_effect=lisbon_only()
    )
    logs: list[dict[str, Any]] = []

    class Recorder:
        def __getattr__(self, level: str) -> Callable[..., None]:
            return lambda event, **kw: logs.append({"event": event, "level": level, **kw})

    monkeypatch.setattr(covers, "log", Recorder())

    await make_place_photos().photos_for({"a1": "Lisbona", "a2": "Zzyzx Nowhere"})

    (line,) = [entry for entry in logs if entry["event"] == "choice_photos"]
    assert (line["requested"], line["found"], line["timed_out"]) == (2, 1, 0)
    assert "Lisbona" not in str(logs)
    assert "Zzyzx" not in str(logs)


async def test_no_photos() -> None:
    assert await NO_PHOTOS.photos_for({"a1": "X"}) == {}


def test_cover_text_fields_lose_nul_characters() -> None:
    cover = Cover(
        url="https://upload.wikimedia.org/wikipedia/commons/a/ab/X.jpg",
        width=10,
        height=10,
        author="A\x00B",
        license="CC\x00 0",
        source_page="https://commons.wikimedia.org/wiki/File:X.jpg",
        title="T\x00",
    )

    assert (cover.author, cover.license, cover.title) == ("AB", "CC 0", "T")
