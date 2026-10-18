"""Rate limits kept in the process: sliding windows per key, and a count of open streams per
user (roadmap phase 1, "per-user economics").

One replica runs the backend today, so a dictionary is the store: a redeploy starts every
window over (harmless: the windows guard bursts, the quotas in app/quota.py guard the money),
and two replicas during a redeploy's overlap would each allow their own share. Redis, or a
Postgres counter, comes with more replicas.

What is limited and where (app/routes.py):

- `POST /plans`: `PLAN_CREATE_LIMIT_PER_USER` and `PLAN_CREATE_LIMIT_PER_IP` requests per
  `PLAN_CREATE_WINDOW_SECONDS`, checked in the route's body: after the user is known (an
  anonymous request is a 401 before it counts), the body validated (a 422 never counts) and
  the demo parameter checked (nor does a 404), and before any quota query. A request refused
  because the planner is not ready (503 `planner_unavailable`) gives its slot back. Over the
  limit: 429 `too_many_requests` with `Retry-After` = seconds until the oldest request in the
  window leaves it.
- `GET /plans/{id}/events`: at most `MAX_STREAMS_PER_USER` event streams open per user at any
  moment, every tab of theirs counted; over it: 429 with `Retry-After` 5. The count is released
  when the stream ends, however it ends.

Keys are the user's email (lower-cased, as `CurrentUser.email` already is) and the client IP.
With `Settings.trusts_proxy_headers` (the default in production) the IP is the last value of
`X-Forwarded-For`, every such header joined in order: the one appended by the proxy in front
(Railway's edge), which a client cannot forge; the earlier values are the client's own and are
ignored. Otherwise it is `request.client.host`, which is the socket's peer only without proxy
handling: the image runs uvicorn with `--proxy-headers` and `FORWARDED_ALLOW_IPS="*"`, and then
uvicorn has already replaced it with the **leftmost** `X-Forwarded-For` value, which the client
chose. So behind Railway `TRUST_PROXY_HEADERS` must stay on (unset or true); turning it off there
lets a client pick its own bucket. Nothing here is logged with a key.
"""

from __future__ import annotations

import math
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field

from fastapi import Request

STREAM_RETRY_SECONDS = 5
"""`Retry-After` when a user holds `MAX_STREAMS_PER_USER` streams: closing a tab is quick."""


@dataclass(frozen=True)
class Decision:
    """Whether a request may go on, and when to retry when it may not."""

    allowed: bool
    retry_after_seconds: int = 0
    at: float | None = None
    """When an allowed hit was recorded (`SlidingWindow.undo` takes it back)."""


@dataclass
class SlidingWindow:
    """At most `limit` events per `window_seconds`, per key, over the last `window_seconds`.

    `now` returns a monotonic-or-wall clock in seconds (tests inject one). Keys whose events
    all left the window are dropped: `hit` sweeps every key at most once per window, so the
    store holds only the keys seen in the last two windows, not every address ever seen.
    """

    limit: int
    window_seconds: float
    now: Callable[[], float]
    _hits: dict[str, deque[float]] = field(default_factory=dict, repr=False)
    _swept_at: float | None = field(default=None, repr=False)

    def hit(self, key: str) -> Decision:
        """Record one event for `key` if it fits; refuse (recording nothing) when it does not."""
        moment = self.now()
        horizon = moment - self.window_seconds
        if self._swept_at is None or moment - self._swept_at >= self.window_seconds:
            self._sweep(horizon)
            self._swept_at = moment
        hits = self._hits.get(key)
        if hits is None:
            hits = deque()
            self._hits[key] = hits
        while hits and hits[0] <= horizon:
            hits.popleft()
        if len(hits) >= self.limit:
            retry = max(1, math.ceil(hits[0] + self.window_seconds - moment))
            return Decision(allowed=False, retry_after_seconds=retry)
        hits.append(moment)
        return Decision(allowed=True, at=moment)

    def undo(self, key: str, decision: Decision) -> None:
        """Take back the event an allowed `decision` recorded for `key` (a request that turned
        out not to be one the window guards, e.g. refused because the planner is not ready)."""
        hits = self._hits.get(key)
        if not decision.allowed or decision.at is None or hits is None:
            return
        try:
            hits.remove(decision.at)
        except ValueError:
            return
        if not hits:
            del self._hits[key]

    def forget(self, key: str) -> None:
        """Drop `key`'s events (tests, and a future admin reset)."""
        self._hits.pop(key, None)

    def _sweep(self, horizon: float) -> None:
        for key, hits in list(self._hits.items()):
            while hits and hits[0] <= horizon:
                hits.popleft()
            if not hits:
                del self._hits[key]

    def __len__(self) -> int:
        """How many keys have events in the window: the expired ones are swept first."""
        self._sweep(self.now() - self.window_seconds)
        return len(self._hits)


@dataclass
class StreamCounter:
    """How many event streams each user holds open; `acquire` refuses past `limit`."""

    limit: int
    _open: dict[str, int] = field(default_factory=dict, repr=False)

    def acquire(self, key: str) -> Decision:
        count = self._open.get(key, 0)
        if count >= self.limit:
            return Decision(allowed=False, retry_after_seconds=STREAM_RETRY_SECONDS)
        self._open[key] = count + 1
        return Decision(allowed=True)

    def release(self, key: str) -> None:
        count = self._open.get(key, 0) - 1
        if count <= 0:
            self._open.pop(key, None)
        else:
            self._open[key] = count

    def held(self, key: str) -> int:
        return self._open.get(key, 0)


def client_ip(request: Request, *, trust_proxy: bool) -> str:
    """The client's address for a rate-limit key: with `trust_proxy` the last `X-Forwarded-For`
    value (what the proxy appended; a client that sends its own header gets the proxy's value
    appended after it, in the same header or in a second one, so every header is read, joined
    in order), else `request.client.host` (the module docstring says what uvicorn's proxy
    handling puts there). "unknown" when neither exists, so every such request shares one
    bucket rather than escaping the limit."""
    if trust_proxy:
        forwarded = ", ".join(request.headers.getlist("x-forwarded-for"))
        if forwarded:
            last = forwarded.rsplit(",", 1)[-1].strip()
            if last:
                return last
    if request.client is not None and request.client.host:
        return request.client.host
    return "unknown"
