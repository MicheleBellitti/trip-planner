"""Link health: which URLs of a delivered plan still work.

Spec: docs/superpowers/specs/2026-10-18-plan-creation-ux-design.md, section 3 (the link check).
This part is pure (no I/O): collecting a plan's URLs, the health records and how a URL is
resolved against them, the homepage fallback, the public-address test and the soft 404 test.
The HTTP checker is added to this module by a later task.

Verdict rules: `ok`, `dead` or `unknown`. A URL is `dead` only on a final 404 or 410, a host
that does not exist, or a soft 404 (an HTML page whose title says "not found"). 401, 403, 405,
429, 5xx, timeouts, TLS and network errors are `unknown`: the link is kept. The fallback of a
dead URL is its own origin (`{scheme}://{host}/`), computed here by `homepage_of`, never
written by an agent; a booking link may use it only when the caller found it allowed by the
booking-link allowlist (`LinkHealth.fallback_allowed`).

Safety rules for the checker: http and https only, port absent, 80 or 443, no userinfo; every
resolved address must be public (`is_public_address`), on every redirect hop; connections go
only to vetted addresses; no cookies, no credentials, no proxy from the environment. A link
never rejects a plan. Logs carry the host and the reason, never a full URL or page content.
"""

from __future__ import annotations

import datetime as dt
import html
import re
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from ipaddress import IPv4Address, IPv6Address
from typing import TYPE_CHECKING, Any, Final, Literal
from urllib.parse import urlsplit

if TYPE_CHECKING:
    from app.plan import Plan

HealthStatus = Literal["ok", "dead", "unknown"]
_STATUSES: Final[frozenset[str]] = frozenset({"ok", "dead", "unknown"})

NOT_FOUND_PHRASES: Final[tuple[str, ...]] = (
    "pagina non trovata",
    "page not found",
    "not found",
    "página no encontrada",
    "página não encontrada",
    "page introuvable",
    "seite nicht gefunden",
)
"""Casefolded phrases that make an HTML title a soft 404."""

_TITLE = re.compile(rb"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)


@dataclass(frozen=True, slots=True)
class LinkHealth:
    """The verdict on one URL."""

    status: HealthStatus
    reason: str
    """Short machine string: ok, http_404, soft_404, nxdomain, unsafe_url, deadline, ..."""
    http_status: int | None = None
    fallback: str | None = None
    fallback_allowed: bool = False
    checked_at: dt.datetime | None = None

    def to_json(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "reason": self.reason,
            "http_status": self.http_status,
            "fallback": self.fallback,
            "fallback_allowed": self.fallback_allowed,
            "checked_at": self.checked_at.isoformat() if self.checked_at else None,
        }

    @classmethod
    def from_json(cls, value: Mapping[str, Any]) -> LinkHealth | None:
        """None for a malformed entry (not a verdict, or a wrongly typed field)."""
        if not isinstance(value, Mapping):
            return None
        status = value.get("status")
        if not isinstance(status, str) or status not in _STATUSES:
            return None
        reason = value.get("reason")
        http_status = value.get("http_status")
        fallback = value.get("fallback")
        checked_raw = value.get("checked_at")
        checked_at: dt.datetime | None = None
        if checked_raw is not None:
            if not isinstance(checked_raw, str):
                return None
            try:
                checked_at = dt.datetime.fromisoformat(checked_raw)
            except ValueError:
                return None
            if checked_at.tzinfo is None:
                return None
        if (
            not isinstance(reason, str)
            or (http_status is not None and not _is_int(http_status))
            or (fallback is not None and not isinstance(fallback, str))
        ):
            return None
        return cls(
            status=status,  # pyright: ignore[reportArgumentType]  # checked against _STATUSES
            reason=reason,
            http_status=http_status,
            fallback=fallback,
            fallback_allowed=value.get("fallback_allowed") is True,
            checked_at=checked_at,
        )


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


class LinkHealthMap:
    """Immutable mapping url -> LinkHealth, as stored with a plan."""

    __slots__ = ("_entries",)

    def __init__(self, entries: Mapping[str, LinkHealth] | None = None) -> None:
        self._entries: dict[str, LinkHealth] = dict(entries or {})

    @classmethod
    def empty(cls) -> LinkHealthMap:
        return cls()

    @classmethod
    def from_json(cls, value: Any) -> LinkHealthMap:
        """None or a malformed document gives an empty map; malformed entries are skipped."""
        if not isinstance(value, Mapping):
            return cls()
        entries: dict[str, LinkHealth] = {}
        for url, raw in value.items():
            if not isinstance(url, str):
                continue
            entry = LinkHealth.from_json(raw)
            if entry is not None:
                entries[url] = entry
        return cls(entries)

    def to_json(self) -> dict[str, dict[str, Any]]:
        return {url: entry.to_json() for url, entry in self._entries.items()}

    def get(self, url: str) -> LinkHealth | None:
        return self._entries.get(url)

    def __len__(self) -> int:
        return len(self._entries)

    def __iter__(self) -> Iterator[str]:
        return iter(self._entries)

    def resolve(self, url: str | None, *, booking: bool = False) -> str | None:
        """The URL to show: itself, its fallback when dead, or None.

        A booking link uses the fallback only when `fallback_allowed`.
        """
        if url is None:
            return None
        entry = self._entries.get(url)
        if entry is None or entry.status != "dead":
            return url
        if entry.fallback is None or (booking and not entry.fallback_allowed):
            return None
        return entry.fallback

    def counts(self) -> dict[HealthStatus, int]:
        counts: dict[HealthStatus, int] = {"ok": 0, "dead": 0, "unknown": 0}
        for entry in self._entries.values():
            counts[entry.status] += 1
        return counts


def collect_plan_urls(plan: Plan) -> list[str]:
    """Every distinct URL of the plan, in first-seen order.

    Bookings' links, alternatives' links, stops' urls, then the price sources of bookings and
    alternatives.
    """
    found: list[str] = []
    seen: set[str] = set()

    def add(url: str | None) -> None:
        if url and url not in seen:
            seen.add(url)
            found.append(url)

    bookings = [*plan.bookings, *plan.alternatives]
    for booking in bookings:
        add(booking.link)
    for _day_index, _stop_index, stop in plan.iter_stops():
        add(stop.url)
    for booking in bookings:
        if booking.price is not None:
            add(str(booking.price.source_url))
    return found


def homepage_of(url: str) -> str | None:
    """`{scheme}://{host}[:{port}]/`, or None when unparseable or already the homepage."""
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        return None
    host = parts.hostname
    if parts.scheme not in ("http", "https") or not host:
        return None
    netloc = f"[{host}]" if ":" in host else host
    if port is not None:
        netloc = f"{netloc}:{port}"
    if parts.path in ("", "/") and not parts.query:
        return None
    return f"{parts.scheme}://{netloc}/"


def is_public_address(address: IPv4Address | IPv6Address) -> bool:
    """True only for a globally routable unicast address (IPv4-mapped IPv6 is unwrapped)."""
    if isinstance(address, IPv6Address) and address.ipv4_mapped is not None:
        address = address.ipv4_mapped
    return address.is_global and not address.is_multicast


def looks_not_found(content_type: str | None, body: bytes) -> bool:
    """A soft 404: an HTML page whose first `<title>` says the page was not found."""
    if content_type is None or content_type.split(";")[0].strip().lower() != "text/html":
        return False
    match = _TITLE.search(body)
    if match is None:
        return False
    title = " ".join(html.unescape(match.group(1).decode("utf-8", errors="ignore")).split())
    folded = title.casefold()
    return any(phrase in folded for phrase in NOT_FOUND_PHRASES)
