"""Domain allowlist for booking links: a link outside the list is shown as text, not a button.

Spec: "Sicurezza e privacy" ("I link degli MCP passano un controllo di dominio nel backend
(elenco consentito per fornitore); quelli fuori elenco si mostrano come testo, non come
bottone") and CLAUDE.md contract rule 4. Host lists and matching rule: docs/research/
integrations.md §1.12 (verified 2026-10-12).

Links are only checked, never rewritten: an MCP link is used exactly as received. The check
covers every provider of the booking-links skill as well as the three MCP servers, because a
`PlanBooking.link` does not say whether it came from an MCP or from build_link.py.

Matching rule (`check_link`): parse with `urllib.parse.urlsplit`; require `https`, no userinfo,
port absent or 443, length <= 2000; take `hostname.lower()`, which must be a plain ASCII DNS name
(every allowed host is one, so an IDN or `xn--` punycode lookalike and an IP address are
rejected outright rather than IDNA-encoded), and match it exactly against `hosts`, or as
`host == suffix or host.endswith("." + suffix)` against `suffixes`; a provider with
`path_prefix` also requires the path to be that prefix or below it, with no dot segment. Never
a substring check: `booking.com.evil.example` fails. URLs holding spaces, control characters or
backslashes are rejected first, because browsers would not open them where `urlsplit` says.

Used by `mapping.plan_to_trip` (only allowed links become `Booking.url`; others go to the notes
as text) and by `routes` (`PlanDetail.booking_links`: the web app draws "Prenota su <sito>" only
for allowed links). Pure module, no I/O.
"""

from __future__ import annotations

import ipaddress
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Literal
from urllib.parse import urlsplit

MAX_LINK_LENGTH = 2000
"""TripTracker's URL cap (LIMITE.url) and PlanBooking.link's max_length."""


@dataclass(frozen=True, slots=True)
class ProviderHosts:
    """Where one provider's links may point."""

    label: str
    """Display name for "Prenota su <label>" (a proper name, not translated)."""
    hosts: frozenset[str]
    """Exact host names."""
    suffixes: frozenset[str] = frozenset()
    """Registrable domains whose every subdomain is accepted (also the bare domain)."""
    path_prefix: str | None = None
    """Required path prefix, e.g. Google is accepted only under /travel/flights."""


def _expedia_hosts() -> frozenset[str]:
    country_hosts = [
        "ae", "at", "be", "ca", "ch", "co.id", "co.in", "co.jp", "co.kr", "co.nz", "co.th",
        "co.uk", "com.ar", "com.au", "com.br", "com.hk", "com.my", "com.ph", "com.sg",
        "com.tw", "com.vn", "de", "dk", "es", "fi", "fr", "ie", "mx", "nl", "no", "sa", "se",
    ]  # fmt: skip
    return frozenset(
        {"www.expedia.com", "expedia.com", "www.expedia.it", "expedia.it"}
        | {f"www.expedia.{tld}" for tld in country_hosts}
    )


PROVIDERS: Mapping[str, ProviderHosts] = {
    "booking": ProviderHosts("Booking.com", frozenset({"www.booking.com", "booking.com"})),
    "airbnb": ProviderHosts(
        "Airbnb",
        frozenset({"www.airbnb.it", "airbnb.it", "www.airbnb.com", "airbnb.com"}),
    ),
    "google_flights": ProviderHosts(
        "Google Voli",
        frozenset({"www.google.com", "www.google.it"}),
        path_prefix="/travel/flights",
    ),
    "expedia": ProviderHosts("Expedia", _expedia_hosts()),
    # MCP booking links are "shortened, dedicated" links on an unverified host: any kiwi.com
    # subdomain until day 1 shows the real one (integrations.md §5, item 1).
    "kiwi": ProviderHosts(
        "Kiwi.com", frozenset({"www.kiwi.com", "kiwi.com"}), suffixes=frozenset({"kiwi.com"})
    ),
    "lastminute": ProviderHosts(
        "lastminute.com",
        frozenset(
            {
                "www.lastminute.it",
                "lastminute.it",
                "www.lastminute.de",
                "www.lastminute.ie",
                "www.lastminute.be",
                "fr.lastminute.be",
            }
        ),
        suffixes=frozenset({"lastminute.com"}),
    ),
    "trenitalia": ProviderHosts(
        "Trenitalia",
        frozenset({"www.trenitalia.com", "trenitalia.com", "www.lefrecce.it", "lefrecce.it"}),
    ),
    "italo": ProviderHosts(
        "Italo",
        frozenset(
            {
                "www.italotreno.com",
                "italotreno.com",
                "biglietti.italotreno.com",
                "www.italotreno.it",
            }
        ),
    ),
    "omio": ProviderHosts(
        "Omio", frozenset({"www.omio.it", "omio.it", "www.omio.com", "omio.com"})
    ),
}
"""Provider key -> allowed hosts. Keys match the booking-links skill's templates.json where a
template exists (expedia covers both expedia_hotels and expedia_flights)."""

MCP_PROVIDERS: tuple[str, ...] = ("expedia", "kiwi", "lastminute")
"""The providers whose MCP servers return booking links (integrations.md §4)."""

RejectionReason = Literal[
    "unparseable", "too_long", "not_https", "userinfo", "port", "unknown_host", "path"
]


@dataclass(frozen=True, slots=True)
class LinkVerdict:
    """The result of checking one link. `allowed` implies `provider` and `host` are set."""

    allowed: bool
    provider: str | None = None
    """Provider key of the matching entry in `PROVIDERS`."""
    label: str | None = None
    """`PROVIDERS[provider].label`, for the button text."""
    host: str | None = None
    """The link's lower-cased host, also set for rejected links when parseable (logs)."""
    reason: RejectionReason | None = None
    """Why the link was rejected; None when allowed."""


def check_link(url: str, *, providers: Iterable[str] | None = None) -> LinkVerdict:
    """Check `url` against `providers` (default: every key of `PROVIDERS`) with the module's
    matching rule. Never raises and never fetches anything; the URL is returned to callers
    unchanged, only judged.

    Beyond the matching rule, anything a browser would parse differently from
    `urllib.parse.urlsplit` is rejected before the host is compared: control characters, spaces
    and backslashes (browsers read `\\` as `/`, so `https://evil.example\\.kiwi.com/` would
    open evil.example); hosts that are not plain ASCII letter-digit-hyphen labels (IDN and
    punycode lookalikes: a Cyrillic letter in place of a Latin one, or an `xn--` label); IP
    addresses; and dot segments under a `path_prefix` (`/travel/flights/../../url` would reach
    Google's open redirect). Unknown provider keys in `providers` are ignored (fail closed)."""
    if not isinstance(url, str) or not url:
        return LinkVerdict(allowed=False, reason="unparseable")
    if len(url) > MAX_LINK_LENGTH:
        return LinkVerdict(allowed=False, reason="too_long")
    if _FORBIDDEN_CHARACTER.search(url):
        return LinkVerdict(allowed=False, reason="unparseable")
    try:
        parts = urlsplit(url)
        raw_host = parts.hostname
    except ValueError:
        return LinkVerdict(allowed=False, reason="unparseable")
    host = raw_host.lower() if raw_host else None
    if parts.scheme != "https":
        return LinkVerdict(allowed=False, host=host, reason="not_https")
    if "@" in parts.netloc or parts.username is not None or parts.password is not None:
        return LinkVerdict(allowed=False, host=host, reason="userinfo")
    try:
        port = parts.port
    except ValueError:
        return LinkVerdict(allowed=False, host=host, reason="port")
    if port not in (None, 443):
        return LinkVerdict(allowed=False, host=host, reason="port")
    if not host:
        return LinkVerdict(allowed=False, reason="unparseable")
    if not _is_plain_dns_name(host):
        return LinkVerdict(allowed=False, host=host, reason="unknown_host")
    keys = PROVIDERS.keys() if providers is None else providers
    for key in keys:
        entry = PROVIDERS.get(key)
        if entry is None or not _host_matches(host, entry):
            continue
        if entry.path_prefix is not None and not _path_matches(parts.path, entry.path_prefix):
            return LinkVerdict(allowed=False, host=host, reason="path")
        return LinkVerdict(allowed=True, provider=key, label=entry.label, host=host)
    return LinkVerdict(allowed=False, host=host, reason="unknown_host")


def is_allowed_link(url: str | None) -> bool:
    """`check_link(url).allowed`; False for None or an empty string."""
    if not url:
        return False
    return check_link(url).allowed


# --- matching helpers -------------------------------------------------------------------------

_FORBIDDEN_CHARACTER = re.compile(r"[\x00-\x20\x7f\\]")
"""ASCII control characters, space, DEL and backslash: browsers strip, encode or reinterpret
them, so a URL holding one may not open where `urlsplit` says it does."""

_DNS_LABEL = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
_MAX_HOST_LENGTH = 253


def _is_plain_dns_name(host: str) -> bool:
    """A lower-case ASCII host name of letter-digit-hyphen labels, not an IP address and with
    no punycode (`xn--`) label. Every allowed host is plain ASCII, so an IDN that only looks
    like one (a Cyrillic o for a Latin o) never matches, not even under a suffix."""
    if len(host) > _MAX_HOST_LENGTH or not host.isascii():
        return False
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        return False
    labels = host.split(".")
    return all(_DNS_LABEL.match(label) and not label.startswith("xn--") for label in labels)


def _host_matches(host: str, entry: ProviderHosts) -> bool:
    if host in entry.hosts:
        return True
    return any(host == suffix or host.endswith("." + suffix) for suffix in entry.suffixes)


def _path_matches(path: str, prefix: str) -> bool:
    """`path` is `prefix` or below it (segment boundary), with no `.`/`..` segment (plain or
    percent-encoded, as browsers resolve them) that could climb out of it."""
    if path != prefix and not path.startswith(prefix.rstrip("/") + "/"):
        return False
    segments = path.split("/")
    return all(segment.lower().replace("%2e", ".") not in {".", ".."} for segment in segments)
