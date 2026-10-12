"""Destination cover photos from Wikimedia, for GET /plans/{id}/cover.

The home list and the top of a plan show a real photo of the destination. The photo comes from
the Wikipedia article about the place and is described by its Commons file page, so every
answer carries what the licenses ask us to show: author, license and a link to the source.

Lookup (`CoverResolver.get`, the only entry point; it never raises):

1. `cache_key(destination)`: the name, casefolded and with spaces collapsed. In-process cache
   first, then the `destination_covers` table (`db.DestinationCoverRecord`): a found cover is
   kept `COVER_TTL` (30 days), a miss (`cover` NULL) `MISS_TTL` (6 hours), so Wikimedia is
   asked about a destination about once a month, and a place without a usable free photo is
   retried a few times a day at most. Concurrent requests for one destination share one
   lookup (a lock per key).
2. Candidate titles (`candidate_titles`): the whole name ("Lisbona, Portogallo") and the part
   before the first comma, parenthesis or slash ("Lisbona").
3. Wikipedia, `it` then `en` (`WIKIPEDIA_LANGUAGES`): one `action=query` per wiki with all the
   candidates as `titles` (redirects followed), `prop=pageimages|pageprops` (+ `langlinks` to
   `en` on `it`): the page image's file name, and whether the page is a disambiguation. English
   titles found through the Italian page's interlanguage links are tried first on `en`, because
   Italian city pages often have a flag as the page image ("Lisbona" -> "Lisbon").
4. A page image is skipped unless its file name looks like a photo (`is_photo_name`: jpeg, png
   or webp, and not a flag, coat of arms, logo, map, ...), then its **Commons** file page is
   read (`action=query&prop=imageinfo`, `extmetadata`) and `parse_commons_cover` decides:
   the license must be free (`is_free_license`: CC0, public domain, CC BY, CC BY-SA; anything
   else, such as NC, ND, GFDL, fair use, or a file that is not on Commons, is refused), the
   file must not be flagged non-free or restricted, and CC BY / CC BY-SA need a named author.
   The first image that passes wins; at most `MAX_COMMONS_LOOKUPS` file pages are read.
5. The image URL is the API's 1920 px thumbnail (Wikimedia only serves a fixed set of widths,
   1600 is a 400), always on `https://upload.wikimedia.org` (`Cover` refuses any other host,
   also when read back from the table), or the original when the file is smaller.

HTTP: every request has `HTTP_TIMEOUT_SECONDS` and the whole lookup `LOOKUP_DEADLINE_SECONDS`;
the User-Agent is `Settings.wikimedia_user_agent` (WIKIMEDIA_CONTACT_URL). A network error,
timeout, non-200 answer or API error is *transient*: it is not stored in the table, the
resolver answers "no cover" (or the stale one, when a refresh fails) and does not ask Wikimedia
again for that destination for `TRANSIENT_TTL`. No retries: the page works without a photo.

Privacy: the only thing that leaves the backend is the destination name, as a `titles` query
parameter. Logs (`cover_*`) carry the wiki, the HTTP status or exception class and the
outcome, never the destination.

Fixtures of real responses: tests/fixtures/covers/ (tests/test_covers.py).
"""

from __future__ import annotations

import asyncio
import datetime as dt
import re
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from html.parser import HTMLParser
from typing import TYPE_CHECKING, Any, Final
from urllib.parse import urlsplit

import httpx
import structlog
from pydantic import BaseModel, Field, ValidationError, field_validator
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import SQLAlchemyError

from app import clock
from app.db import DestinationCoverRecord

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

log = structlog.get_logger(__name__)

WIKIPEDIA_LANGUAGES: Final = ("it", "en")
COMMONS_API: Final = "https://commons.wikimedia.org/w/api.php"
UPLOAD_HOST: Final = "upload.wikimedia.org"
THUMB_HOSTS: Final = frozenset({"upload.wikimedia.org", "thumb.wikimedia.org"})
COMMONS_HOST: Final = "commons.wikimedia.org"

COVER_WIDTH: Final = 1920
"""Requested width: Wikimedia serves thumbnails only at fixed steps (1280, 1920, ...)."""

HTTP_TIMEOUT_SECONDS: Final = 6.0
LOOKUP_DEADLINE_SECONDS: Final = 15.0
MAX_COMMONS_LOOKUPS: Final = 4

COVER_TTL: Final = dt.timedelta(days=30)
MISS_TTL: Final = dt.timedelta(hours=6)
TRANSIENT_TTL: Final = dt.timedelta(minutes=2)

MAX_KEY_LENGTH: Final = 200
MAX_AUTHOR_LENGTH: Final = 200
MAX_MEMORY_ENTRIES: Final = 512

_PHOTO_EXTENSIONS: Final = (".jpg", ".jpeg", ".png", ".webp")
_PHOTO_MIME_TYPES: Final = frozenset({"image/jpeg", "image/png", "image/webp"})

# Words that mark a file as a flag, a coat of arms, a logo or a map: Wikipedia often uses those
# as the page image of a city, and they make a poor cover.
_NOT_A_PHOTO: Final = re.compile(
    r"\b(flags?|bandiera|bandeira|bandera|drapeau|flagge|coat of arms|stemma|gonfalone|"
    r"escudo|brasao|brasão|blason|wappen|logo|seal|emblem|locator|location map|map|mappa|"
    r"carte|diagram|icon)\b",
    re.IGNORECASE,
)

_NAME_SPLIT: Final = re.compile(r"[,;(/]|\s[-–—]\s")
_SPACES: Final = re.compile(r"\s+")

_FREE_LICENSE: Final = re.compile(
    r"""^(?:
        cc0\b.*
        | (?:public\ domain|pd)(?:[\ -].*)?
        | cc[\ -]by(?:[\ -]sa)?(?:[\ -]\d\.\d)?(?:\ [a-z]{2,4})?
    )$""",
    re.IGNORECASE | re.VERBOSE,
)
_ATTRIBUTION_LICENSE: Final = re.compile(r"^cc[\ -]by", re.IGNORECASE)


class CoverErrorCode(StrEnum):
    """`detail.code` of the 404 of GET /plans/{id}/cover."""

    COVER_UNAVAILABLE = "cover_unavailable"


class Cover(BaseModel):
    """A free-licensed photo of a destination and what must be shown with it."""

    url: str = Field(description="The image, an https://upload.wikimedia.org URL, ~1920 px wide.")
    width: int = Field(gt=0, description="Pixels of the image at `url`.")
    height: int = Field(gt=0, description="Pixels of the image at `url`.")
    author: str | None = Field(
        default=None, description="Plain-text author (HTML stripped); null when unknown."
    )
    license: str = Field(description="Short license name, e.g. 'CC BY-SA 4.0'.")
    license_url: str | None = Field(
        default=None, description="Link to the license text; null for public domain."
    )
    source_page: str = Field(description="The file's page on commons.wikimedia.org.")
    title: str = Field(description="The file's title, without 'File:' and the extension.")

    @field_validator("url")
    @classmethod
    def _upload_host_only(cls, value: str) -> str:
        parts = urlsplit(value)
        if parts.scheme != "https" or parts.hostname != UPLOAD_HOST or parts.username:
            msg = f"cover images must be served from https://{UPLOAD_HOST}, got {value!r}"
            raise ValueError(msg)
        return value

    @field_validator("source_page")
    @classmethod
    def _commons_page_only(cls, value: str) -> str:
        parts = urlsplit(value)
        if parts.scheme != "https" or parts.hostname != COMMONS_HOST:
            msg = f"the source page must be on https://{COMMONS_HOST}, got {value!r}"
            raise ValueError(msg)
        return value

    @field_validator("license_url")
    @classmethod
    def _web_link_only(cls, value: str | None) -> str | None:
        if value is not None and urlsplit(value).scheme not in {"http", "https"}:
            msg = f"license_url must be an http(s) link, got {value!r}"
            raise ValueError(msg)
        return value


# --- pure helpers -------------------------------------------------------------------------------


def cache_key(destination: str) -> str | None:
    """The cache key of a destination name: NFKC, casefolded, spaces collapsed, at most
    `MAX_KEY_LENGTH` characters. None for a blank name."""
    text = _SPACES.sub(" ", unicodedata.normalize("NFKC", destination)).strip().casefold()
    return text[:MAX_KEY_LENGTH].strip() or None


def candidate_titles(destination: str) -> list[str]:
    """Wikipedia titles to try for `destination`, best first: the whole name, then the part
    before the first comma, semicolon, parenthesis, slash or spaced dash ("Lisbona, Portogallo"
    -> "Lisbona, Portogallo", "Lisbona"). No `|` (it separates titles in one request)."""
    whole = _SPACES.sub(" ", destination.replace("|", " ")).strip()[:MAX_KEY_LENGTH]
    first = _NAME_SPLIT.split(whole, maxsplit=1)[0].strip()
    titles: list[str] = []
    for title in (whole, first):
        if title and title.casefold() not in {seen.casefold() for seen in titles}:
            titles.append(title)
    return titles


def is_photo_name(file_name: str) -> bool:
    """True when a Wikipedia page-image file name looks like a photograph: a jpeg, png or webp
    that is not a flag, coat of arms, logo, map or the like."""
    name = file_name.replace("_", " ").strip().lower()
    return name.endswith(_PHOTO_EXTENSIONS) and _NOT_A_PHOTO.search(name) is None


def is_free_license(short_name: str) -> bool:
    """True for CC0, public domain, CC BY and CC BY-SA (any version and port, e.g. 'CC BY-SA
    4.0', 'CC BY 3.0 de', 'Public domain'); False for everything else, NC and ND variants,
    GFDL, fair use and unknown names included."""
    return _FREE_LICENSE.match(_SPACES.sub(" ", short_name).strip()) is not None


class _TextExtractor(HTMLParser):
    _BLOCKS: Final = frozenset({"br", "p", "div", "li", "ul", "ol", "tr", "td", "table"})

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skipping = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style"}:
            self._skipping += 1
        elif tag in self._BLOCKS:
            self.parts.append(" ")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style"} and self._skipping:
            self._skipping -= 1
        elif tag in self._BLOCKS:
            self.parts.append(" ")

    def handle_data(self, data: str) -> None:
        if not self._skipping:
            self.parts.append(data)


def strip_html(value: str, *, limit: int = MAX_AUTHOR_LENGTH) -> str:
    """The text of an HTML fragment (Commons' `Artist`, `ObjectName`): tags and scripts gone,
    entities decoded, spaces collapsed, no angle brackets left, at most `limit` characters."""
    extractor = _TextExtractor()
    try:
        extractor.feed(value)
        extractor.close()
    except Exception:  # HTMLParser on hostile input must never break a lookup
        return ""
    text = "".join(extractor.parts).replace("<", " ").replace(">", " ")
    text = "".join(ch for ch in text if ch.isprintable() or ch.isspace())
    return _SPACES.sub(" ", text).strip()[:limit].strip()


def _mapping(value: object) -> Mapping[str, Any] | None:
    return value if isinstance(value, Mapping) else None


def _items(value: object) -> list[Mapping[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, Mapping)]


def _text(value: object) -> str | None:
    return value.strip() or None if isinstance(value, str) else None


def _positive_int(value: object) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool) and value > 0:
        return value
    return None


@dataclass(frozen=True, slots=True)
class WikipediaPage:
    """What a Wikipedia answer says about one candidate title."""

    title: str
    image_file: str | None
    """`pageimage`: the page's lead image file name (underscores), None without one."""
    english_title: str | None
    """The article's title on en.wikipedia, from the interlanguage links (it only)."""


def parse_wikipedia_pages(payload: Mapping[str, Any], titles: list[str]) -> list[WikipediaPage]:
    """The usable articles for `titles`, in the order of `titles` and without duplicates.

    Follows `normalized` and `redirects`; leaves out missing pages, pages outside the main
    namespace and disambiguation pages. Pure."""
    query = _mapping(payload.get("query"))
    if query is None:
        return []
    moved: dict[str, str] = {}
    for key in ("normalized", "redirects"):
        for entry in _items(query.get(key)):
            source, target = _text(entry.get("from")), _text(entry.get("to"))
            if source and target:
                moved[source] = target
    pages = {
        title: page for page in _items(query.get("pages")) if (title := _text(page.get("title")))
    }
    found: list[WikipediaPage] = []
    seen: set[str] = set()
    for requested in titles:
        title = requested
        for _ in range(2):  # normalized, then redirected (an unmoved title stays as it is)
            title = moved.get(title, title)
        page = pages.get(title)
        if page is None or title in seen or page.get("missing") or page.get("ns") != 0:
            continue
        seen.add(title)
        if _mapping(page.get("pageprops")) and "disambiguation" in page["pageprops"]:
            continue
        english = next(
            (
                english_title
                for link in _items(page.get("langlinks"))
                if link.get("lang") == "en" and (english_title := _text(link.get("title")))
            ),
            None,
        )
        found.append(WikipediaPage(title, _text(page.get("pageimage")), english))
    return found


def _thumbnail_url(info: Mapping[str, Any]) -> tuple[str, int, int] | None:
    """(url, width, height) of the image to show: the thumbnail when the API made one (moved to
    upload.wikimedia.org, without its tracking query), else the original."""
    thumb = _text(info.get("thumburl"))
    width, height = _positive_int(info.get("thumbwidth")), _positive_int(info.get("thumbheight"))
    if thumb and width and height:
        parts = urlsplit(thumb)
        if parts.scheme == "https" and parts.hostname in THUMB_HOSTS and parts.path:
            return f"https://{UPLOAD_HOST}{parts.path}", width, height
        return None
    original = _text(info.get("url"))
    width, height = _positive_int(info.get("width")), _positive_int(info.get("height"))
    if original and width and height:
        return f"https://{UPLOAD_HOST}{urlsplit(original).path}", width, height
    return None


def _metadata(info: Mapping[str, Any], key: str) -> str | None:
    entry = _mapping((_mapping(info.get("extmetadata")) or {}).get(key))
    return _text(entry.get("value")) if entry else None


def parse_commons_cover(payload: Mapping[str, Any]) -> Cover | None:
    """The `Cover` described by a Commons `imageinfo` answer, or None when the file is missing,
    is not a jpeg/png/webp, is flagged non-free or restricted, has a license that
    `is_free_license` refuses, or (CC BY / CC BY-SA) has no author. Pure."""
    pages = _items((_mapping(payload.get("query")) or {}).get("pages"))
    page = pages[0] if pages else None
    infos = _items(page.get("imageinfo")) if page and not page.get("missing") else []
    if page is None or not infos:
        return None
    info = infos[0]
    if info.get("mime") not in _PHOTO_MIME_TYPES:
        return None
    license_name = strip_html(_metadata(info, "LicenseShortName") or "", limit=80)
    if not license_name or not is_free_license(license_name):
        return None
    non_free = (_metadata(info, "NonFree") or "").lower()
    if non_free in {"true", "1", "yes"} or _metadata(info, "Restrictions"):
        return None
    author = strip_html(_metadata(info, "Artist") or "") or None
    if author is None and _ATTRIBUTION_LICENSE.match(license_name):
        return None
    image = _thumbnail_url(info)
    if image is None:
        return None
    page_title = _text(page.get("title")) or ""
    title = strip_html(_metadata(info, "ObjectName") or "", limit=200) or re.sub(
        r"\.[A-Za-z0-9]+$", "", page_title.removeprefix("File:")
    )
    source_page = _text(info.get("descriptionurl")) or (
        f"https://{COMMONS_HOST}/wiki/{page_title.replace(' ', '_')}"
    )
    try:
        return Cover(
            url=image[0],
            width=image[1],
            height=image[2],
            author=author,
            license=license_name,
            license_url=_text(_metadata(info, "LicenseUrl")),
            source_page=source_page,
            title=title or "Foto",
        )
    except ValidationError:
        return None


# --- the resolver ---------------------------------------------------------------------------------


class WikimediaUnavailableError(Exception):
    """A Wikimedia request failed in a way that may pass (network, timeout, HTTP or API error)."""


@dataclass(frozen=True, slots=True)
class _Cached:
    cover: Cover | None
    expires: dt.datetime


class CoverResolver:
    """Finds, caches and returns the cover of a destination (module docstring). One instance
    per process (`routes.get_cover_resolver` builds it from the planner's shared client)."""

    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        http: httpx.AsyncClient,
        user_agent: str,
    ) -> None:
        self._session_factory = session_factory
        self._http = http
        self._headers = {"User-Agent": user_agent, "Accept": "application/json"}
        self._memory: dict[str, _Cached] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    async def get(self, destination: str) -> Cover | None:
        """The cover for `destination`, or None (no usable free photo, or Wikimedia is
        unreachable). Never raises."""
        key = cache_key(destination)
        if key is None:
            return None
        try:
            return await self._get(key, destination)
        except Exception:  # a cover is decoration: nothing here may reach the caller
            log.exception("cover_lookup_failed")
            return None

    async def _get(self, key: str, destination: str) -> Cover | None:
        hit = self._remembered(key)
        if hit is not None:
            return hit.cover
        lock = self._locks.setdefault(key, asyncio.Lock())
        try:
            async with lock:
                hit = self._remembered(key)
                if hit is not None:
                    return hit.cover
                stored = await self._read_row(key)
                if stored is not None and stored.expires > clock.now():
                    self._remember(key, stored)
                    return stored.cover
                try:
                    async with asyncio.timeout(LOOKUP_DEADLINE_SECONDS):
                        cover = await self._lookup(destination)
                except (WikimediaUnavailableError, TimeoutError) as exc:
                    log.warning("cover_wikimedia_unavailable", reason=type(exc).__name__)
                    # Keep showing the stale cover while a refresh cannot be made.
                    stale = stored.cover if stored is not None else None
                    self._remember(key, _Cached(stale, clock.now() + TRANSIENT_TTL))
                    return stale
                ttl = COVER_TTL if cover is not None else MISS_TTL
                entry = _Cached(cover, clock.now() + ttl)
                self._remember(key, entry)
                await self._write_row(key, cover)
                log.info("cover_resolved", found=cover is not None)
                return cover
        finally:
            if self._locks.get(key) is lock and not lock.locked():
                del self._locks[key]

    # --- caches -----------------------------------------------------------------------------

    def _remembered(self, key: str) -> _Cached | None:
        entry = self._memory.get(key)
        if entry is not None and entry.expires <= clock.now():
            del self._memory[key]
            return None
        return entry

    def _remember(self, key: str, entry: _Cached) -> None:
        if len(self._memory) >= MAX_MEMORY_ENTRIES and key not in self._memory:
            del self._memory[next(iter(self._memory))]
        self._memory[key] = entry

    async def _read_row(self, key: str) -> _Cached | None:
        """The table row of `key` as a cache entry (`expires` already in the past when stale),
        or None when there is no row or the table cannot be read."""
        try:
            async with self._session_factory() as db:
                row = await db.get(DestinationCoverRecord, key)
        except (SQLAlchemyError, OSError) as exc:
            log.warning("cover_cache_read_failed", error=type(exc).__name__)
            return None
        if row is None:
            return None
        cover: Cover | None = None
        if row.cover is not None:
            try:
                cover = Cover.model_validate(row.cover)
            except ValidationError:
                return None
        return _Cached(cover, row.fetched_at + (COVER_TTL if cover is not None else MISS_TTL))

    async def _write_row(self, key: str, cover: Cover | None) -> None:
        values: dict[str, Any] = {
            "destination_key": key,
            "cover": cover.model_dump(mode="json") if cover is not None else None,
            "fetched_at": clock.now(),
        }
        statement = pg_insert(DestinationCoverRecord).values(**values)
        statement = statement.on_conflict_do_update(
            index_elements=["destination_key"],
            set_={"cover": statement.excluded.cover, "fetched_at": statement.excluded.fetched_at},
        )
        try:
            async with self._session_factory() as db:
                await db.execute(statement)
                await db.commit()
        except (SQLAlchemyError, OSError) as exc:
            log.warning("cover_cache_write_failed", error=type(exc).__name__)

    # --- Wikimedia --------------------------------------------------------------------------

    async def _lookup(self, destination: str) -> Cover | None:
        names = candidate_titles(destination)
        english_titles: list[str] = []
        tried: set[str] = set()
        commons_lookups = 0
        for language in WIKIPEDIA_LANGUAGES:
            titles = [*english_titles, *names] if language == "en" else names
            titles = [
                title
                for index, title in enumerate(titles)
                if title.casefold() not in {other.casefold() for other in titles[:index]}
            ]
            if not titles:
                continue
            payload = await self._get_json(
                f"https://{language}.wikipedia.org/w/api.php",
                wikipedia_params(language, titles),
            )
            for page in parse_wikipedia_pages(payload, titles):
                if language != "en" and page.english_title:
                    english_titles.append(page.english_title)
                file = page.image_file
                if file is None or file in tried or not is_photo_name(file):
                    continue
                tried.add(file)
                if commons_lookups >= MAX_COMMONS_LOOKUPS:
                    return None
                commons_lookups += 1
                cover = parse_commons_cover(await self._get_json(COMMONS_API, commons_params(file)))
                if cover is not None:
                    return cover
        return None

    async def _get_json(self, url: str, params: Mapping[str, str]) -> Mapping[str, Any]:
        try:
            response = await self._http.get(
                url, params=params, headers=self._headers, timeout=HTTP_TIMEOUT_SECONDS
            )
        except httpx.HTTPError as exc:
            raise WikimediaUnavailableError(type(exc).__name__) from exc
        if response.status_code != 200:
            raise WikimediaUnavailableError(f"HTTP {response.status_code}")
        try:
            payload: object = response.json()
        except ValueError as exc:
            raise WikimediaUnavailableError("invalid JSON") from exc
        body = _mapping(payload)
        if body is None or "error" in body:
            raise WikimediaUnavailableError("API error")
        return body


def wikipedia_params(language: str, titles: list[str]) -> dict[str, str]:
    """The `action=query` parameters for the candidate `titles` on `<language>.wikipedia.org`."""
    params = {
        "action": "query",
        "format": "json",
        "formatversion": "2",
        "redirects": "1",
        "titles": "|".join(titles),
        "prop": "pageimages|pageprops" + ("" if language == "en" else "|langlinks"),
        "piprop": "original|name",
        "ppprop": "disambiguation",
    }
    if language != "en":
        params["lllang"] = "en"
    return params


def commons_params(file_name: str) -> dict[str, str]:
    """The `imageinfo` parameters for a Commons file (a Wikipedia `pageimage` name)."""
    return {
        "action": "query",
        "format": "json",
        "formatversion": "2",
        "titles": f"File:{file_name}",
        "prop": "imageinfo",
        "iiprop": "url|size|mime|extmetadata",
        "iiurlwidth": str(COVER_WIDTH),
        "iiextmetadatafilter": "Artist|LicenseShortName|LicenseUrl|Restrictions|NonFree|ObjectName",
    }
