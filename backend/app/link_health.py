"""Link health: which URLs of a delivered plan still work.

Spec: docs/superpowers/specs/2026-10-18-plan-creation-ux-design.md, section 3 (the link check).
The first part is pure (no I/O): collecting a plan's URLs, the health records and how a URL is
resolved against them, the homepage fallback, the public-address test and the soft 404 test.
The second part does the I/O: `HttpLinkChecker` (one GET per hop, redirects followed by hand),
`PinnedNetworkBackend` (connections only to public addresses), `system_resolver`, and
`build_link_checker`, the production wiring. `NO_LINK_CHECKS` is the checker that checks nothing
(LINK_CHECK_ENABLED=false).

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

Limits: GET only, at most 5 redirects, 5 s per request (httpcore's timeouts; an asyncio guard
0.5 s later also bounds the resolution and the whole body read), 8 URLs at a time, 10 s for the
whole plan, exact (a URL not checked by then is `unknown`, reason `deadline`), at most 65,536
body bytes read.
"""

from __future__ import annotations

import asyncio
import contextlib
import datetime as dt
import html
import re
import socket
import ssl
import time
from collections.abc import AsyncGenerator, Awaitable, Callable, Iterable, Iterator, Mapping
from dataclasses import dataclass, replace
from ipaddress import IPv4Address, IPv6Address, IPv6Network, ip_address
from typing import TYPE_CHECKING, Any, Final, Literal, Protocol, cast
from urllib.parse import urljoin, urlsplit

import httpcore
import httpx
import structlog

from app.links import check_link

if TYPE_CHECKING:
    from app.config import Settings
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
    """True only for a globally routable unicast address.

    IPv4-mapped IPv6 is judged as its IPv4 address. An IPv6 address that carries an IPv4 one
    (6to4, Teredo's client, the NAT64 well-known prefix 64:ff9b::/96) is public only when that
    IPv4 address is public too. The deprecated IPv4-compatible (::/96), IPv4-translated
    (::ffff:0:0:0/96) and site-local (fec0::/10) ranges, which Python still calls global, never
    are.
    """
    if isinstance(address, IPv6Address):
        if address.ipv4_mapped is not None:
            return is_public_address(address.ipv4_mapped)
        if address.is_site_local or any(address in net for net in _DEPRECATED_IPV4_IN_IPV6):
            return False
        embedded = _embedded_ipv4(address)
        if embedded is not None and not is_public_address(embedded):
            return False
    return address.is_global and not address.is_multicast


_NAT64: Final[IPv6Network] = IPv6Network("64:ff9b::/96")
_DEPRECATED_IPV4_IN_IPV6: Final[tuple[IPv6Network, ...]] = (
    IPv6Network("::/96"),
    IPv6Network("::ffff:0:0:0/96"),
)


def _embedded_ipv4(address: IPv6Address) -> IPv4Address | None:
    """The IPv4 address a 6to4, Teredo (client) or NAT64 (64:ff9b::/96) address carries."""
    if address.sixtofour is not None:
        return address.sixtofour
    if address.teredo is not None:
        return address.teredo[1]
    if address in _NAT64:
        return IPv4Address(int(address) & 0xFFFF_FFFF)
    return None


def looks_not_found(content_type: str | None, body: bytes) -> bool:
    """A soft 404: an HTML page whose first `<title>` says the page was not found."""
    if not _is_html(content_type):
        return False
    match = _TITLE.search(body)
    if match is None:
        return False
    title = " ".join(html.unescape(match.group(1).decode("utf-8", errors="ignore")).split())
    folded = title.casefold()
    return any(phrase in folded for phrase in NOT_FOUND_PHRASES)


def _is_html(content_type: str | None) -> bool:
    return content_type is not None and content_type.split(";")[0].strip().lower() == "text/html"


# --- The checker (I/O) ------------------------------------------------------------------------

log = structlog.get_logger(__name__)

Resolver = Callable[[str], Awaitable[list[IPv4Address | IPv6Address]]]
"""A host name -> its addresses. Raises HostNotFoundError when the name does not exist; any
other failure (an OSError) means the answer is not known."""

_REDIRECT_CODES: Final[frozenset[int]] = frozenset({301, 302, 303, 307, 308})
_DEAD_CODES: Final[frozenset[int]] = frozenset({404, 410})
_ALLOWED_PORTS: Final[frozenset[int | None]] = frozenset({None, 80, 443})
_GUARD_MARGIN: Final[float] = 0.5
"""Seconds the per-request asyncio guard waits beyond httpcore's own timeouts, so httpcore's
(which close their socket) fire first; the guard only catches what httpcore does not bound,
such as a body that trickles in under the read timeout."""


class HostNotFoundError(Exception):
    """The host name does not exist."""


class LinkHealthChecker(Protocol):
    """Checks a delivered plan's URLs."""

    async def check_plan(self, plan: Plan) -> LinkHealthMap: ...

    async def aclose(self) -> None: ...


class NoLinkChecks:
    """The checker that checks nothing (LINK_CHECK_ENABLED=false): no request, an empty map."""

    async def check_plan(self, plan: Plan) -> LinkHealthMap:
        return LinkHealthMap.empty()

    async def aclose(self) -> None:
        return None


NO_LINK_CHECKS: Final[NoLinkChecks] = NoLinkChecks()


class HttpLinkChecker:
    """Checks URLs with GET under the module's safety rules and limits.

    Each request goes straight to `transport.handle_async_request`: there is no
    httpx.AsyncClient, so no cookie jar, no auth and no proxy from the environment. Every hop's
    host is resolved through `resolver` and refused unless all its addresses are public, before
    any request; the transport `build_link_checker` builds resolves again and connects only to
    a public address (`PinnedNetworkBackend`), so a DNS answer that changes in between cannot
    move the connection.
    """

    def __init__(
        self,
        *,
        transport: httpx.AsyncBaseTransport,
        resolver: Resolver,
        user_agent: str,
        now: Callable[[], dt.datetime],
        request_timeout: float = 5.0,
        total_deadline: float = 10.0,
        concurrency: int = 8,
        max_redirects: int = 5,
        max_body: int = 65_536,
    ) -> None:
        self._transport = transport
        self._resolver = resolver
        self._user_agent = user_agent
        self._now = now
        self._request_timeout = request_timeout
        self._total_deadline = total_deadline
        self._concurrency = concurrency
        self._max_redirects = max_redirects
        self._max_body = max_body
        self._headers = {
            "User-Agent": user_agent,
            "Accept": "text/html,*/*;q=0.8",
            "Accept-Language": "it,en;q=0.8",
            # The soft 404 test reads the raw body: ask for it uncompressed.
            "Accept-Encoding": "identity",
        }
        self._timeouts = dict.fromkeys(("connect", "read", "write", "pool"), request_timeout)

    async def check_plan(self, plan: Plan) -> LinkHealthMap:
        """Every distinct URL of the plan, `concurrency` at a time, within `total_deadline`:
        a URL still being checked then is cancelled and `unknown` (`deadline`). Never raises
        because of a URL: a failed check is `unknown` (`error`)."""
        started = time.monotonic()
        urls = collect_plan_urls(plan)
        semaphore = asyncio.Semaphore(self._concurrency)

        async def check(url: str) -> LinkHealth:
            try:
                async with semaphore:
                    return await self.check_url(url)
            except Exception as exc:  # a link never fails the plan
                log.warning("link_check_failed", host=_host_of(url), error=type(exc).__name__)
                return LinkHealth(status="unknown", reason="error", checked_at=self._now())

        tasks: list[asyncio.Task[LinkHealth]] = []
        with contextlib.suppress(TimeoutError):
            async with asyncio.timeout(self._total_deadline), asyncio.TaskGroup() as group:
                tasks.extend(group.create_task(check(url)) for url in urls)
        entries = {
            url: (
                LinkHealth(status="unknown", reason="deadline", checked_at=self._now())
                if task.cancelled()
                else task.result()
            )
            for url, task in zip(urls, tasks, strict=True)
        }
        health = LinkHealthMap(entries)
        counts = health.counts()
        log.info(
            "link_check",
            urls=len(entries),
            ok=counts["ok"],
            dead=counts["dead"],
            unknown=counts["unknown"],
            elapsed_ms=round((time.monotonic() - started) * 1000),
        )
        for url, entry in entries.items():
            if entry.status == "dead":
                log.info("link_dead", host=_host_of(url), reason=entry.reason)
        return health

    async def check_url(self, url: str) -> LinkHealth:
        """The verdict on `url`, within `total_deadline`. A dead URL gets its homepage as
        `fallback` when the homepage is not dead too, with `fallback_allowed` from the
        booking-link allowlist; not when the URL's own host does not exist (`nxdomain`; a
        missing host further down a redirect chain is `redirect_nxdomain`)."""
        try:
            async with asyncio.timeout(self._total_deadline):
                health = await self._follow(url)
                home = homepage_of(url)
                if (
                    health.status == "dead"
                    and health.reason != "nxdomain"
                    and home is not None
                    and (await self._follow(home)).status != "dead"
                ):
                    health = replace(
                        health, fallback=home, fallback_allowed=check_link(home).allowed
                    )
        except TimeoutError:
            health = LinkHealth(status="unknown", reason="deadline")
        return replace(health, checked_at=self._now())

    async def aclose(self) -> None:
        await self._transport.aclose()

    async def _follow(self, url: str) -> LinkHealth:
        """GET `url`, following at most `max_redirects` redirects by hand, every hop vetted."""
        current = url
        for hop in range(self._max_redirects + 1):
            target = _safe_target(current)
            if target is None:
                return LinkHealth(status="unknown", reason="unsafe_url")
            request_url, host = target
            try:
                async with asyncio.timeout(self._request_timeout + _GUARD_MARGIN):
                    refusal = await self._vet(host, own_host=hop == 0)
                    answer = refusal if refusal is not None else await self._get(request_url)
            except TimeoutError:
                return LinkHealth(status="unknown", reason="timeout")
            except httpx.TransportError as exc:
                return LinkHealth(status="unknown", reason=_transport_reason(exc))
            if isinstance(answer, LinkHealth):
                return answer
            try:
                current = urljoin(current, answer)
            except ValueError:  # a malformed Location, e.g. http://[::1/
                return LinkHealth(status="unknown", reason="unsafe_url")
        return LinkHealth(status="unknown", reason="redirects")

    async def _vet(self, host: str, *, own_host: bool) -> LinkHealth | None:
        """None when every address of `host` is public; otherwise the verdict. `own_host`: the
        host is the checked URL's own, not a redirect's."""
        try:
            addresses = await _resolve(self._resolver, host)
        except HostNotFoundError:
            return LinkHealth(status="dead", reason="nxdomain" if own_host else "redirect_nxdomain")
        except OSError:
            return LinkHealth(status="unknown", reason="dns_error")
        if not addresses:
            return LinkHealth(status="unknown", reason="dns_error")
        if not all(is_public_address(address) for address in addresses):
            return LinkHealth(status="unknown", reason="unsafe_address")
        return None

    async def _get(self, target: httpx.URL) -> LinkHealth | str:
        """One GET: the verdict, or the `Location` of a redirect to follow."""
        request = httpx.Request(
            "GET", target, headers=self._headers, extensions={"timeout": self._timeouts}
        )
        response = await self._transport.handle_async_request(request)
        try:
            code = response.status_code
            location = response.headers.get("Location")
            if code in _REDIRECT_CODES and location:
                return location
            if code in _DEAD_CODES:
                return LinkHealth(status="dead", reason=f"http_{code}", http_status=code)
            if not 200 <= code < 300:
                return LinkHealth(status="unknown", reason=f"http_{code}", http_status=code)
            content_type = response.headers.get("Content-Type")
            if _is_html(content_type) and looks_not_found(
                content_type, await self._head_of(response)
            ):
                return LinkHealth(status="dead", reason="soft_404", http_status=code)
            return LinkHealth(status="ok", reason="ok", http_status=code)
        finally:
            await response.aclose()

    async def _head_of(self, response: httpx.Response) -> bytes:
        """At most `max_body` bytes of the body, as received."""
        stream = response.stream
        if not isinstance(stream, httpx.AsyncByteStream):
            return b""
        head = bytearray()
        chunks = aiter(stream)
        try:
            async for chunk in chunks:
                head += chunk
                if len(head) >= self._max_body:
                    break
        finally:
            if isinstance(chunks, AsyncGenerator):
                await chunks.aclose()
        return bytes(head[: self._max_body])


def _safe_target(url: str) -> tuple[httpx.URL, str] | None:
    """The URL as httpx sends it, and its host; None when the safety rules refuse it (http or
    https only, port absent, 80 or 443, no userinfo). httpx parses it because httpx also builds
    the request from it: the host vetted is the host connected to."""
    try:
        target = httpx.URL(url)
        host = target.raw_host.decode("ascii")
    except (httpx.InvalidURL, UnicodeDecodeError):
        return None
    if (
        target.scheme not in ("http", "https")
        or not host
        or target.userinfo
        or target.port not in _ALLOWED_PORTS
    ):
        return None
    return target, host


async def _resolve(resolver: Resolver, host: str) -> list[IPv4Address | IPv6Address]:
    """An IP literal is its own answer; a name goes to the resolver."""
    try:
        return [ip_address(host)]
    except ValueError:
        return await resolver(host)


def _transport_reason(error: httpx.TransportError) -> str:
    if isinstance(error, httpx.TimeoutException):
        return "timeout"
    if isinstance(error, httpx.ConnectError):
        return "tls_error" if _caused_by_tls(error) else "connect_error"
    return "network_error"


def _caused_by_tls(error: BaseException) -> bool:
    """True when an ssl.SSLError is in the exception's chain (httpx wraps httpcore's error,
    which wraps the ssl module's)."""
    seen: set[int] = set()
    current: BaseException | None = error
    while current is not None and id(current) not in seen:
        if isinstance(current, ssl.SSLError):
            return True
        seen.add(id(current))
        current = current.__cause__ or current.__context__
    return False


def _host_of(url: str) -> str | None:
    """The host for a log line (never the full URL)."""
    try:
        return urlsplit(url).hostname
    except ValueError:
        return None


class PinnedNetworkBackend(httpcore.AsyncNetworkBackend):
    """An httpcore network backend that connects only to public addresses.

    httpcore hands `connect_tcp` the URL's host name: this resolves it through `resolver` and
    opens the socket to a public address of the answer (the first that accepts, in order), else
    raises httpcore.ConnectError. A DNS answer that changed since the checker vetted the host
    (rebinding) cannot point the connection at a private address. TLS keeps the URL's host name
    for SNI and certificate verification: httpcore passes the origin's host to `start_tls`, not
    the address connected to.
    """

    def __init__(
        self, resolver: Resolver, inner: httpcore.AsyncNetworkBackend | None = None
    ) -> None:
        self._resolver = resolver
        # cast: httpcore's __init__ also declares a stand-in AnyIOBackend for when anyio is
        # missing, so pyright sees a union; anyio is installed (httpx needs it).
        self._inner = (
            inner
            if inner is not None
            else cast(httpcore.AsyncNetworkBackend, httpcore.AnyIOBackend())
        )

    async def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,  # noqa: ASYNC109 (httpcore's signature)
        local_address: str | None = None,
        socket_options: Iterable[Any] | None = None,
    ) -> httpcore.AsyncNetworkStream:
        try:
            async with asyncio.timeout(timeout):
                addresses = await _resolve(self._resolver, host)
        except TimeoutError as exc:
            raise httpcore.ConnectTimeout(f"resolving {host} timed out") from exc
        except (HostNotFoundError, OSError) as exc:
            raise httpcore.ConnectError(f"cannot resolve {host}") from exc
        public = [address for address in addresses if is_public_address(address)]
        if not public:
            raise httpcore.ConnectError(f"no public address for {host}")
        for address in public[:-1]:
            with contextlib.suppress(httpcore.ConnectError):
                return await self._inner.connect_tcp(
                    str(address), port, timeout, local_address, socket_options
                )
        return await self._inner.connect_tcp(
            str(public[-1]), port, timeout, local_address, socket_options
        )

    async def sleep(self, seconds: float) -> None:
        await self._inner.sleep(seconds)


_NAME_NOT_FOUND: Final[frozenset[int]] = frozenset(
    code for code in (socket.EAI_NONAME, getattr(socket, "EAI_NODATA", None)) if code is not None
)


async def system_resolver(host: str) -> list[IPv4Address | IPv6Address]:
    """The host's addresses from getaddrinfo, in its order, without duplicates.

    HostNotFoundError when the name does not exist (EAI_NONAME, EAI_NODATA); any other failure
    is the socket.gaierror (an OSError)."""
    loop = asyncio.get_running_loop()
    try:
        answers = await loop.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        if exc.errno in _NAME_NOT_FOUND:
            raise HostNotFoundError(host) from exc
        raise
    addresses: list[IPv4Address | IPv6Address] = []
    for family, _type, _proto, _name, sockaddr in answers:
        if family in (socket.AF_INET, socket.AF_INET6):
            address = ip_address(sockaddr[0])
            if address not in addresses:
                addresses.append(address)
    return addresses


def build_link_checker(settings: Settings, *, now: Callable[[], dt.datetime]) -> HttpLinkChecker:
    """The production checker: the system resolver, and a transport pinned to public
    addresses."""
    return HttpLinkChecker(
        transport=_pinned_transport(PinnedNetworkBackend(system_resolver)),
        resolver=system_resolver,
        user_agent=settings.link_check_user_agent,
        now=now,
    )


def _pinned_transport(backend: httpcore.AsyncNetworkBackend) -> httpx.AsyncHTTPTransport:
    """An httpx transport (no proxy, nothing from the environment) whose connections go
    through `backend`, and are closed after each answer (no keep-alive: a plan's checks are
    one burst, and an idle pool would hold sockets for the life of the process).

    httpx 0.28.1, the locked version, has no public way to give its transport a network
    backend, so this replaces the transport's private `_pool`. After an httpx upgrade,
    tests/test_link_health.py::test_the_built_checker_connects_through_the_pinned_backend
    says whether it still works.
    """
    transport = httpx.AsyncHTTPTransport(trust_env=False)
    transport._pool = httpcore.AsyncConnectionPool(
        ssl_context=httpx.create_ssl_context(trust_env=False),
        max_connections=100,
        max_keepalive_connections=0,
        network_backend=backend,
    )
    return transport
