# Plan UX, PR 1: the link check — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When the coordinator delivers a plan, the backend checks every URL in it; a dead page
points to its site's homepage when that works, else it reads "Pagina non trovata", on screen
and in the TripTracker export.

**Architecture:** A new `app/link_health.py` holds pure helpers (URL collection, soft-404
detection, the public-address rule, the verdict map) and an HTTP checker that fetches through a
transport which connects only to vetted public addresses. The consumer runs it inside
`evaluate_submission`, threads the verdicts into `mapping.plan_to_trip`, and stores them in a new
`plans.link_health` column; `GET /plans/{id}` exposes them and the web renders each URL from
them. Evals gain a non-blocking `dead_links` check.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2 async + Alembic, httpx 0.28.1 / httpcore
1.0.9, pytest + respx + time-machine; Next.js 16, TypeScript strict, Zod 4 mini, vitest.

**Spec:** `docs/superpowers/specs/2026-10-18-plan-creation-ux-design.md`, section 3 (and 4, 5
for delivery). This plan covers PR 1 of 5 only; section 3's prompt rule for transport and
activities ships with the agents in PR 4.

## Global Constraints

- Code, identifiers, logs, comments: English. User-facing copy: Italian, sentence case, no em
  dash (`web/components/ui/invariants.test.ts`).
- Exact copy: `Sito di {host}` (host without `www.`), `Pagina non trovata`.
- Verdicts: `ok`, `dead`, `unknown`. Dead only on a final 404 or 410, a host that does not
  exist, or a soft 404; 401, 403, 405, 429, 5xx, timeouts, TLS and network errors are `unknown`.
- Limits: GET only; at most 5 redirects, each hop vetted; 5 s per request; 8 requests in
  parallel; 10 s for the whole plan (unchecked URLs become `unknown`); at most 65,536 body bytes
  read.
- Safety: http and https only, port absent, 80 or 443, no userinfo; every resolved address must
  be public, on every hop; connections go only to vetted addresses; no cookies, no credentials,
  no proxy from the environment (`trust_env=False`).
- The fallback is the URL's own origin (`{scheme}://{host}/`), computed by code; a booking link
  uses it only when `links.check_link(fallback).allowed`.
- Never reject the plan or message the coordinator because of a link.
- Logs never carry a full URL or page content: host and reason only.
- One Alembic migration in this PR; `down_revision` = the head of `origin/main` at merge time
  (today `600fbb922f91`).
- Before each task and before opening or updating the PR: `git fetch origin && git merge
  origin/main`; regenerate generated files after a merge, never hand-merge them (CLAUDE.md
  table).
- This PR changes no file under `agents/`, `profiles/`, `skills/` and not
  `backend/app/plan.py` (those trigger the paid `evals.yml`).
- Every backend command runs from `backend/`; every web command from `web/`.

## Review Focus

1. **The same URL in several places** (a stop's page that is also a price source): checked once,
   resolved the same way everywhere. Test in Task 1 (`collect_plan_urls` dedupes) and Task 6
   (one `link_health` entry drives both renderings).
2. **Plans stored before this PR** (`plans.link_health` NULL, `PlanDetail.link_health` empty):
   the export, the API and the page behave exactly as today. Tests in Tasks 3, 5 and 6.
3. **A title that merely contains "404"** ("Linea 404 · Carris"): not a soft 404. Test in Task 1.
4. **A slow site among many URLs**: the plan is still accepted within the 10 s deadline, the
   slow URL `unknown`. Test in Task 2.
5. **A dead Google Flights link**: its homepage fails the allowlist's path rule, so no button
   and "Pagina non trovata", never a button to `https://www.google.com/`. Tests in Tasks 3 and 6.

---

### Task 0: Branch

- [ ] **Step 1:** In the worktree `.claude/worktrees/plan-creation-ux`, rename the branch and
  sync: `git branch -m feat/plan-creation-ux feat/link-health && git fetch origin && git merge
  origin/main`. The spec and this plan land with PR 1.

### Task 1: Pure helpers in `app/link_health.py`

**Files:**
- Create: `backend/app/link_health.py`
- Test: `backend/tests/test_link_health.py`

**Interfaces:**
- Produces:
  - `HealthStatus = Literal["ok", "dead", "unknown"]`
  - `@dataclass(frozen=True, slots=True) class LinkHealth: status: HealthStatus; reason: str;
    http_status: int | None = None; fallback: str | None = None; fallback_allowed: bool = False;
    checked_at: dt.datetime | None = None`, with `to_json() -> dict[str, Any]` and
    `from_json(value: Mapping[str, Any]) -> LinkHealth | None` (None for a malformed entry).
  - `class LinkHealthMap`: immutable mapping url -> `LinkHealth`; `empty()`;
    `to_json() -> dict[str, dict[str, Any]]`; `from_json(value: Any) -> LinkHealthMap` (None or
    malformed -> empty, malformed entries skipped); `get(url: str) -> LinkHealth | None`;
    `resolve(url: str | None, *, booking: bool = False) -> str | None` (None in -> None; no entry
    or not dead -> url; dead -> fallback, but for `booking=True` only when `fallback_allowed`;
    else None); `counts() -> dict[HealthStatus, int]`.
  - `collect_plan_urls(plan: Plan) -> list[str]`: distinct, first-seen order: bookings' `link`,
    alternatives' `link`, stops' `url`, bookings' and alternatives' `str(price.source_url)`.
  - `homepage_of(url: str) -> str | None`: `{scheme}://{host}[:{port}]/`; None when unparseable
    or when the URL already is that homepage (path empty or `/`, no query).
  - `is_public_address(address: IPv4Address | IPv6Address) -> bool`
  - `looks_not_found(content_type: str | None, body: bytes) -> bool`

- [ ] **Step 1: Write the failing tests**

```python
def test_collect_plan_urls_dedupes_in_first_seen_order() -> None:
    # a plan whose stop url equals a booking's price source_url, plus one booking link
    assert collect_plan_urls(plan) == [BOOKING_LINK, STOP_URL]

@pytest.mark.parametrize(("url", "home"), [
    ("https://www.carris.pt/tarifas/aeroporto", "https://www.carris.pt/"),
    ("http://example.org:8080/a?b=1", "http://example.org:8080/"),
    ("https://www.carris.pt/", None),
    ("not a url", None),
])
def test_homepage_of(url: str, home: str | None) -> None: ...

@pytest.mark.parametrize(("address", "public"), [
    ("93.184.216.34", True), ("2606:4700::1111", True),
    ("10.0.0.1", False), ("172.16.5.4", False), ("192.168.1.1", False), ("127.0.0.1", False),
    ("169.254.169.254", False), ("100.64.0.1", False), ("0.0.0.0", False), ("224.0.0.1", False),
    ("::1", False), ("fd00::1", False), ("fe80::1", False), ("::ffff:10.0.0.1", False),
])
def test_is_public_address(address: str, public: bool) -> None: ...

@pytest.mark.parametrize(("title", "dead"), [
    ("Pagina non trovata - Carris", True), ("404 Not Found", True), ("Page not found", True),
    ("Página no encontrada", True), ("Página não encontrada", True), ("Page introuvable", True),
    ("Seite nicht gefunden", True), ("Errore 404 - pagina non trovata", True),
    ("Linea 404 · Carris", False), ("Tarifas | Carris", False),
])
def test_looks_not_found_reads_the_title(title: str, dead: bool) -> None:
    body = f"<html><head><title>{title}</title></head></html>".encode()
    assert looks_not_found("text/html; charset=utf-8", body) is dead

def test_looks_not_found_ignores_non_html() -> None:
    assert looks_not_found("application/pdf", b"<title>Page not found</title>") is False

def test_resolve_dead_with_fallback_and_booking_rule() -> None:
    health = LinkHealthMap.from_json({
        "https://a.example/x": {"status": "dead", "reason": "http_404",
                                "fallback": "https://a.example/", "fallback_allowed": False},
    })
    assert health.resolve("https://a.example/x") == "https://a.example/"
    assert health.resolve("https://a.example/x", booking=True) is None
    assert health.resolve("https://other.example/") == "https://other.example/"
    assert health.resolve(None) is None

def test_from_json_tolerates_null_and_malformed_entries() -> None:
    assert LinkHealthMap.from_json(None).to_json() == {}
    assert LinkHealthMap.from_json({"u": {"status": "weird"}, "v": 3}).to_json() == {}
```

- [ ] **Step 2:** Run `uv run pytest tests/test_link_health.py -q`. Expected: FAIL (module missing).
- [ ] **Step 3: Implement the module's pure part.** `is_public_address`: unwrap
  `ipv4_mapped`, then `address.is_global and not address.is_multicast`. `looks_not_found`: only
  for `text/html`; take the first `<title>` (case-insensitive, whitespace collapsed,
  `html.unescape`); dead when it contains one of `pagina non trovata`, `page not found`,
  `not found`, `página no encontrada`, `página não encontrada`, `page introuvable`,
  `seite nicht gefunden` (casefolded); a bare number never counts. Module docstring: the spec
  section, the verdict rules and the safety rules of Global Constraints.
- [ ] **Step 4:** Run the tests. Expected: PASS. Then `uv run ruff check app tests && uv run
  pyright`.
- [ ] **Step 5:** Commit: `feat(backend): link_health's pure helpers: URLs, homepage, public
  addresses, soft 404`.

### Task 2: The HTTP checker and the pinned transport

**Files:**
- Modify: `backend/app/link_health.py`
- Modify: `backend/app/config.py` (`link_check_enabled`, `link_check_user_agent`),
  `backend/.env.example` (`LINK_CHECK_ENABLED`, one-line reason)
- Test: `backend/tests/test_link_health.py`, `backend/tests/test_config.py`

**Interfaces:**
- Consumes: Task 1.
- Produces:
  - `Resolver = Callable[[str], Awaitable[list[IPv4Address | IPv6Address]]]`; it raises
    `HostNotFoundError` when the name does not exist.
  - `class LinkHealthChecker(Protocol): async def check_plan(self, plan: Plan) -> LinkHealthMap;
    async def aclose(self) -> None`
  - `class NoLinkChecks` (returns `LinkHealthMap.empty()`) and the instance `NO_LINK_CHECKS`.
  - `class HttpLinkChecker(*, transport: httpx.AsyncBaseTransport, resolver: Resolver,
    user_agent: str, now: Callable[[], dt.datetime], request_timeout: float = 5.0,
    total_deadline: float = 10.0, concurrency: int = 8, max_redirects: int = 5,
    max_body: int = 65_536)` with `check_plan`, `check_url(url: str) -> LinkHealth`, `aclose`.
  - `async def system_resolver(host: str) -> list[IPv4Address | IPv6Address]`
  - `class PinnedNetworkBackend(httpcore.AsyncNetworkBackend)(resolver: Resolver,
    inner: httpcore.AsyncNetworkBackend | None = None)`
  - `def build_link_checker(settings: Settings, *, now: Callable[[], dt.datetime]) -> HttpLinkChecker`
  - `Settings.link_check_enabled: bool = True`; `Settings.link_check_user_agent` property:
    `f"AtlasLinkCheck/1.0 (+{self.frontend_origin})"`.

- [ ] **Step 1: Write the failing tests** (a `respx.MockRouter` passed as
  `transport=httpx.MockTransport(router.handler)`, a fake resolver mapping hosts to addresses,
  `NOW` fixed):

```python
async def test_200_is_ok(): assert (await checker.check_url(U)).status == "ok"
async def test_404_and_410_are_dead_with_reason(): ...           # reason "http_404" / "http_410"
async def test_403_429_500_are_unknown(): ...                     # never "dead"
async def test_redirect_to_404_is_dead(): ...                     # 301 -> /gone -> 404
async def test_redirect_to_a_private_address_is_unknown_and_not_fetched(): ...
    # hop 2's host resolves to 10.0.0.1: reason "unsafe_address"; the router saw one request
async def test_unsafe_urls_are_never_fetched(): ...
    # ftp://, https://user:pw@h/, https://h:8443/ -> unknown "unsafe_url", zero requests
async def test_unknown_host_is_dead_without_fallback(): ...       # HostNotFoundError -> "nxdomain"
async def test_soft_404_is_dead(): ...                            # 200 + <title>Pagina non trovata</title>
async def test_more_than_five_redirects_is_unknown(): ...         # reason "redirects"
async def test_dead_page_gets_its_homepage_when_it_answers(): ...
    # /x 404, / 200 -> fallback "https://a.example/", fallback_allowed False (not on allowlist)
async def test_dead_page_and_dead_homepage_have_no_fallback(): ...
async def test_dead_booking_link_fallback_allowed_follows_the_allowlist(): ...
    # https://www.booking.com/searchresults.it.html?x 404, / 200 -> fallback_allowed True
    # https://www.google.com/travel/flights?q=x 404, / 200 -> fallback_allowed False
async def test_slow_url_becomes_unknown_within_the_deadline(): ...
    # total_deadline=0.2, one route sleeps 1 s: check_plan returns in < 0.5 s; slow one "unknown"
async def test_check_plan_checks_each_distinct_url_once(): ...
async def test_requests_carry_the_user_agent_and_no_cookie(): ...
    # first response sets a cookie; the next request has no Cookie header
async def test_pinned_backend_refuses_private_addresses():
    backend = PinnedNetworkBackend(resolver_returning("10.0.0.1"), inner=RecordingBackend())
    with pytest.raises(httpcore.ConnectError):
        await backend.connect_tcp("evil.example", 443)
    assert backend_inner.calls == []
async def test_pinned_backend_connects_to_the_vetted_address(): ...  # inner sees "93.184.216.34"
def test_link_check_settings(make_settings): ...  # default True; user agent names frontend_origin
```

- [ ] **Step 2:** Run `uv run pytest tests/test_link_health.py tests/test_config.py -q`.
  Expected: FAIL.
- [ ] **Step 3: Implement.** `check_url` follows the Global Constraints' rules hop by hop:
  validate the URL, resolve the host through `resolver` and refuse a non-public answer before any
  request, send `GET` straight through `transport.handle_async_request` (so no client cookie jar
  exists) with `User-Agent`, `Accept: text/html,*/*;q=0.8`, `Accept-Language: it,en;q=0.8` and a
  per-request timeout extension, read at most `max_body` bytes, close the stream. A dead verdict
  (except `nxdomain`) checks `homepage_of(url)` once the same way; a homepage `ok` or `unknown`
  becomes `fallback`, and `fallback_allowed = links.check_link(fallback).allowed`. `check_plan`
  runs `collect_plan_urls` under a semaphore of `concurrency`, waits at most `total_deadline`,
  cancels the rest as `unknown` / `deadline`, then logs one `link_check` line (counts per status,
  elapsed ms) and one `link_dead` line per dead URL (host and reason only).
  `PinnedNetworkBackend.connect_tcp` resolves `host` through the resolver, connects `inner`
  (default `httpcore.AnyIOBackend()`) to the first public address, else raises
  `httpcore.ConnectError`; TLS keeps the request's host name for SNI and verification.
  `build_link_checker` builds `httpx.AsyncHTTPTransport(trust_env=False)` and replaces its
  `_pool` with `httpcore.AsyncConnectionPool(ssl_context=httpx.create_ssl_context(),
  network_backend=PinnedNetworkBackend(system_resolver))` (a private attribute of the locked
  httpx 0.28.1: say so in a comment and keep a test that a request through it reaches
  `PinnedNetworkBackend`). `system_resolver` uses `loop.getaddrinfo(host, None,
  type=socket.SOCK_STREAM)` and maps `EAI_NONAME`/`EAI_NODATA` to `HostNotFoundError`.
- [ ] **Step 4:** Run the tests, then `uv run ruff check . && uv run ruff format --check . &&
  uv run pyright`. Expected: PASS.
- [ ] **Step 5:** Commit: `feat(backend): the link checker, through a transport pinned to
  public addresses`.

### Task 3: The TripTracker export uses the verdicts

**Files:**
- Modify: `backend/app/mapping.py` (docstring rules, `plan_to_trip`, `_map_stop`,
  `_map_booking`, `booking_notes`, a new `NOTE_PRICE_SOURCE_MISSING`)
- Test: `backend/tests/test_mapping.py`, `backend/tests/test_mapping_budget.py`

**Interfaces:**
- Consumes: `LinkHealthMap.resolve`, `LinkHealthMap.empty`.
- Produces: `plan_to_trip(plan, *, now, fx, ids, health: LinkHealthMap | None = None) ->
  TripMapping` (None means "no verdicts": today's behaviour). `NOTE_PRICE_SOURCE_MISSING =
  "Fonte del prezzo: pagina non trovata ({host})"`.

- [ ] **Step 1: Write the failing tests**

```python
def test_dead_stop_url_uses_the_homepage() -> None:       # Stop.url == "https://a.example/"
def test_dead_stop_url_without_fallback_is_omitted() -> None:   # "url" not in stop
def test_dead_booking_link_with_allowed_fallback_points_to_it() -> None:
def test_dead_google_flights_link_has_no_url_and_no_unchecked_note() -> None:
    # Booking has no "url"; notes do not contain "Link da verificare"
def test_dead_price_source_note_says_page_not_found() -> None:
    # notes contain "Fonte del prezzo: pagina non trovata (a.example)"
def test_without_health_the_trip_is_unchanged() -> None:
    assert run(plan) == run_with(plan, health=None) == run_with(plan, health=LinkHealthMap.empty())
```

- [ ] **Step 2:** Run `uv run pytest tests/test_mapping.py tests/test_mapping_budget.py -q`.
  Expected: FAIL.
- [ ] **Step 3: Implement.** Stops: `url = health.resolve(stop.url)`. Bookings: `link =
  health.resolve(booking.link, booking=True)`; the allowlist check and the "unchecked link" note
  apply to that value only (a dead link with no usable fallback is dropped, never put in the
  notes). Price source: `health.resolve(source_url)`; None -> `NOTE_PRICE_SOURCE_MISSING` with
  the host without `www.`. The notes budget keeps its guarantees (the new line is shorter than
  the URL line it replaces). Update the module docstring's Stops and Bookings rules.
- [ ] **Step 4:** Run the tests. Expected: PASS.
- [ ] **Step 5:** Commit: `feat(backend): the TripTracker export follows the link check`.

### Task 4: Store the verdicts and run the check at delivery

**Files:**
- Create: `backend/migrations/versions/20261018_<rev>_plans_link_health.py` (autogenerate,
  then review: one nullable JSONB column)
- Modify: `backend/app/db.py` (`PlanRecord.link_health: Mapped[JsonObject | None]`),
  `backend/app/consumer.py` (`ConsumerDeps.link_checker`, `Accepted.link_health`,
  `PlanUpdate.link_health`, `_apply_update`, `translate_submission`, `evaluate_submission`),
  `backend/app/sessions.py` (`PlannerServices.link_checker`, `start_planner`, `stop_planner`),
  `backend/tests/conftest.py` (`TEST_ENV["LINK_CHECK_ENABLED"] = "false"`)
- Test: `backend/tests/test_consumer.py`, `backend/tests/test_sessions.py`, `backend/tests/test_db.py`
  (drift check, unchanged)

**Interfaces:**
- Consumes: Tasks 1 to 3.
- Produces: `ConsumerDeps.link_checker: LinkHealthChecker = NO_LINK_CHECKS`;
  `translate_submission(plan, *, schema, fx, now, ids, health: LinkHealthMap | None = None)`;
  `Accepted.link_health: dict[str, Any]` (`health.to_json()`, `{}` without checks);
  `PlanUpdate.link_health: Mapping[str, Any] | None`; column `plans.link_health`.

- [ ] **Step 1: Write the failing tests**

```python
def test_translate_submission_passes_health_to_the_trip_and_the_outcome() -> None:
    # a dead stop url with fallback: Accepted.trip's stop url is the fallback,
    # Accepted.link_health == health.to_json()
async def test_accepted_plan_stores_link_health(harness) -> None:
    # deps.link_checker = a stub returning a map with one dead URL
    # after the happy_path scenario: plans.link_health == that map's to_json()
async def test_rejected_plan_stores_no_link_health(harness) -> None:
async def test_link_check_runs_with_fx_and_schema_concurrently(harness) -> None:
    # a stub checker that waits on an event set by the fx stub: no deadlock
async def test_start_planner_builds_no_checker_in_demo_or_when_disabled(...) -> None:
    # DEMO_MODE, fx_offline=True and LINK_CHECK_ENABLED=false -> NO_LINK_CHECKS
```

- [ ] **Step 2:** Run `uv run pytest tests/test_consumer.py tests/test_sessions.py -q -k
  "link_health or link_check or checker"`. Expected: FAIL.
- [ ] **Step 3: Implement.** `evaluate_submission` runs `deps.link_checker.check_plan(parsed)`
  concurrently with the FX prefetch and `trip_schema.require()` (`asyncio.gather`; a
  `TripSchemaUnavailableError` still propagates), then calls `translate_submission(...,
  health=health)`. The accept branch passes `link_health=outcome.link_health` in its
  `PlanUpdate`. `start_planner` builds `build_link_checker(settings, now=clock.now)` only when
  `settings.link_check_enabled` and neither DEMO_MODE nor `fx_offline`, else `NO_LINK_CHECKS`;
  `stop_planner` awaits `link_checker.aclose()`. Run `uv run alembic revision --autogenerate -m
  "add link_health to plans"`, keep only the column, set `down_revision` to the current head.
- [ ] **Step 4:** Run `uv run alembic upgrade head` on the dev database, then the whole suite:
  `uv run pytest -q`. Expected: PASS (test_db's drift check included).
- [ ] **Step 5:** Commit: `feat(backend): check a plan's links when it is delivered and store the verdicts`.

### Task 5: `GET /plans/{id}` exposes the verdicts

**Files:**
- Modify: `backend/app/routes.py` (`LinkHealthOut`, `PlanDetail.link_health`, `plan_detail`),
  `web/lib/schemas/api.ts` (`LinkHealthSchema`, `PlanDetailSchema.link_health`),
  `docs/backend-interfaces.md` (one decision entry: the link check, its limits, why the plan is
  never rejected)
- Test: `backend/tests/test_routes.py`, `web/lib/schemas/api.test.ts` (new)

**Interfaces:**
- Produces: `class LinkHealthOut(BaseModel): status: str; fallback: str | None = None;
  fallback_allowed: bool = False`; `PlanDetail.link_health: dict[str, LinkHealthOut]` (default
  `{}`). Web: `LinkHealthSchema = z.object({ status: z.string(), fallback:
  z._default(z.nullable(z.string()), null), fallback_allowed: z._default(z.boolean(), false) })`,
  `PlanDetail.link_health: z._default(z.record(z.string(), LinkHealthSchema), () => ({}))`;
  `type LinkHealthEntry`, `type LinkHealthMap = Record<string, LinkHealthEntry>`.

- [ ] **Step 1: Write the failing tests**

```python
async def test_plan_detail_exposes_link_health(client, plan_rows) -> None:
    # a ready plan whose link_health has one dead entry -> detail["link_health"][url] ==
    # {"status": "dead", "fallback": "https://a.example/", "fallback_allowed": False}
async def test_plan_detail_link_health_is_empty_for_older_plans(client, plan_rows) -> None:
```

```ts
it("parses a detail without link_health as an empty map", ...)
it("keeps an unknown status string instead of rejecting the detail", ...)
```

- [ ] **Step 2:** Run `uv run pytest tests/test_routes.py -q -k link_health` and `npm test --
  lib/schemas`. Expected: FAIL.
- [ ] **Step 3: Implement** `plan_detail` with `LinkHealthMap.from_json(record.link_health)`
  (`http_status`, `reason` and `checked_at` stay in the database).
- [ ] **Step 4:** Run both again. Expected: PASS.
- [ ] **Step 5:** Commit: `feat: GET /plans/{id} carries the link check's verdicts`.

### Task 6: The plan page renders each URL from its verdict

**Files:**
- Modify: `web/components/plan/plan-model.ts` (`planUrl`, `bookingAction`),
  `web/components/plan/bookings.tsx` (`PriceLine`, `ActionSide`, `BookingRow` props),
  `web/components/plan/itinerary.tsx` (`StopRow`), `web/components/plan/PlanView.tsx` (pass
  `detail.link_health` down), `web/app/dev/plan/preview.tsx` (a dead stop page with a fallback,
  a dead price source without one, a dead Google Flights booking link)
- Test: `web/components/plan/plan-model.test.ts`, `web/components/plan/PlanView.test.tsx`

**Interfaces:**
- Consumes: `LinkHealthMap` from Task 5.
- Produces:
  - `type PlanUrl = { kind: "link"; href: string; host: string } | { kind: "homepage"; href:
    string; host: string } | { kind: "missing"; host: string | null } | { kind: "none" }`
  - `planUrl(url: string | null | undefined, health: LinkHealthMap): PlanUrl` (`none` for an
    empty or non-http URL; `host` without `www.`; an entry that is not `dead` reads as `link`)
  - `bookingAction(link, check, health?: LinkHealthMap)` adds `{ kind: "missing" }`: a dead link
    whose fallback is missing or not `fallback_allowed`; a dead link with an allowed fallback is a
    button to the fallback with the same site label.

- [ ] **Step 1: Write the failing tests**

```ts
it("planUrl: a dead page with a fallback is the homepage", () =>
  expect(planUrl(DEAD, HEALTH)).toEqual({ kind: "homepage", href: "https://a.example/", host: "a.example" }));
it("planUrl: a dead page without a fallback is missing", ...);
it("planUrl: no verdict, or ok or unknown, is the link as today", ...);
it("bookingAction: a dead Google Flights link is missing, never a button", ...);
it("bookingAction: a dead Booking.com link with an allowed fallback is a button to it", ...);
// PlanView
it("shows 'Sito di a.example' for a dead stop page with a fallback", ...);
it("shows 'Pagina non trovata' and no link for a dead stop page without one", ...);
it("one verdict drives the stop link and the price source of the same URL", ...);
it("renders an older plan without link_health exactly as before", ...);
```

- [ ] **Step 2:** Run `npm test -- components/plan`. Expected: FAIL.
- [ ] **Step 3: Implement.** Stop: `link` -> today's `QuietExternalLink` with the host;
  `homepage` -> the same link component, text `Sito di {host}`; `missing` -> a plain `<p>` with
  `Pagina non trovata`. Price source: `Fonte {host}` as today, `Fonte sito di {host}` linked to
  the homepage, or `Fonte {host} (pagina non trovata)` as text. Booking `missing`: the action
  side shows `Pagina non trovata` and the line `Cerca l'offerta sul sito del fornitore.`, no
  button. No new colour: the missing state is `ink-2` text.
- [ ] **Step 4:** Run `npm test`, `npm run lint`, `npm run typecheck`. Expected: PASS.
- [ ] **Step 5:** Look at `/dev/plan` in the browser at 393 px and desktop, light and dark;
  screenshot each of the three dead cases.
- [ ] **Step 6:** Commit: `feat(web): dead links read "Sito di …" or "Pagina non trovata"`.

### Task 7: The `dead_links` eval check

**Files:**
- Modify: `evals/checks.py` (`DEAD_LINKS`, `check_dead_links`, `CHECK_NAMES`, `CHECKS`,
  `RunMetadata.link_health`), `evals/run.py` (fill `link_health` from the plan row),
  `web/components/evals/eval-model.ts` (label `dead_links: "Nessun link rotto"`),
  `evals/README.md` (one line)
- Test: `evals/tests/test_eval_checks.py`, `evals/tests/test_eval_compare.py`,
  `web/components/evals/eval-model.test.ts`

**Interfaces:**
- Produces: `DEAD_LINKS = "dead_links"`; `RunMetadata.link_health: Mapping[str, Any] | None =
  None`; `check_dead_links(request, plan, trip, metadata) -> CheckResult`, never blocking.

- [ ] **Step 1: Write the failing tests**

```python
def test_dead_links_passes_with_none_dead() -> None:      # "pass", "3 link(s) checked, none dead"
def test_dead_links_warns_with_hosts_and_reasons() -> None:
    # status "warn", blocking False, details ["a.example http_404 (homepage: yes)"]
def test_dead_links_skips_without_a_plan_or_without_verdicts() -> None:
def test_compare_does_not_block_on_a_check_missing_from_the_baseline() -> None:
```

- [ ] **Step 2:** Run `uv run pytest ../evals/tests -q`. Expected: FAIL.
- [ ] **Step 3: Implement** (`dead_links` goes last in `CHECK_NAMES`; details carry the host,
  never the full URL).
- [ ] **Step 4:** Run `uv run pytest ../skills ../scripts ../evals/tests -q`, `uv run ruff check
  ../evals && uv run pyright -p ../evals`, `npm test -- components/evals`. Expected: PASS.
- [ ] **Step 5:** Commit: `feat(evals): count dead links per plan`.

### Task 8: Docs, full checks and the PR

**Files:**
- Modify: `CLAUDE.md` (Layout: `app/link_health.py`; "Database and migrations": `plans` keeps
  the link check's verdicts; contract rule 4: one sentence on the homepage fallback derived by
  code), `backend/.env.example` if not done in Task 2

- [ ] **Step 1:** `git fetch origin && git merge origin/main`; if a migration landed, re-point
  ours; regenerate whatever the CLAUDE.md table says changed.
- [ ] **Step 2:** Run every check CI runs, from `backend/`: `uv run ruff check . && uv run ruff
  format --check . && uv run pyright && uv run python -m app.schemas --check && uv run python
  ../scripts/render_profiles.py --check && uv run python ../web/scripts/gen-backend-fixtures.py
  --check && uv run pytest -q`; the non-backend checks of CLAUDE.md; from `web/`: `npm run
  gen:schemas -- --check && npm run lint && npm run typecheck && npm test && npm run build`.
  Expected: all PASS.
- [ ] **Step 3:** Run impeccable's critique on the plan page's link states; fix anything below
  32/40 or any open P0/P1.
- [ ] **Step 4:** Commit: `docs: the link check in CLAUDE.md`.
- [ ] **Step 5:** Ask Michele before pushing and opening the PR (title `feat: check a plan's
  links when it is delivered`, body: the spec link, what changes on screen, the migration, no
  agent change, the baseline evals run to do after merge).
- [ ] **Step 6:** After the merge: the paid evals run Michele approved (about 7 $), so
  `dead_links` has a starting point before PR 4's prompt rule.
