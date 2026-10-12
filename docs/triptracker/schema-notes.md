# TripTracker schema notes

What the planner must produce for TripTracker, taken from TripTracker's real code rather
than from the spec. The spec is `docs/spec/implementation-doc.it.md`, section "Contratto del
piano".

- **Source:** private repo `MicheleBellitti/trip-tracker`, `main` at
  `71be320dd6d7095e74284f9f2c8d4e76144007ea` (2026-10-11). Read-only clone. All 37 of
  TripTracker's own vitest tests pass at this commit.
- **Versions in the lockfile:** zod `4.5.4`, better-auth `1.7.3`, next `16.3.4`,
  react `19.2.8`, vitest `5.0.0`.
- **Verbatim sources:** `docs/triptracker/snapshot/` (see its README).
- **Generated artifacts:**
  - `backend/tests/fixtures/triptracker/trip.schema.json` is the output of
    `z.toJSONSchema(tripSchema)` with default options (draft 2020-12, `io: "output"`),
    produced by zod 4.5.4 inside the clone. Zod is v4, so `zod-to-json-schema` was not needed.
    It stands in for the future `https://viaggi.bellittim.com/schema/trip.json`, which does
    not exist yet. There is no `public/schema/` and no build hook at this commit.
  - `backend/tests/fixtures/triptracker/valid_trip.json` is a complete valid Trip (see §9).
    It passes `tripSchema.parse` in node (lossless round trip) and `Draft202012Validator`
    (jsonschema 4.26.0) against `trip.schema.json`.

Contents:

1. Where things live
2. Shared formats and caps
3. Trip, Day, Stop and Booking, field by field
4. Semantics: sortOrder, state, status, the two dates, lead times, coverSeed, dayIndex
5. The store (`lib/store.ts`) and what `importTrip` has to respect
6. Auth and configuration (Better Auth, `configurazione.ts`, `ORIGINI_FIDATE`, `EMAIL_AMMESSE`, `/accedi`, next config)
7. JSON Schema compared with Zod (what the backend check can and cannot catch)
8. Divergences: spec compared with TripTracker
9. The fixture

---

## 1. Where things live

| Concern | File (TripTracker) | Notes |
|---|---|---|
| Zod schemas, caps (`LIMITE`), inferred types | `lib/schema.ts` | `stopSchema`, `daySchema`, `bookingSchema`, `tripSchema`, `storeSchema`, `STORAGE_KEY = "trip-tracker:v1"` |
| Trip construction, ids, coverSeed, default timezone | `lib/trip.ts` | `newId(prefix)`, `buildTrip`, `buildDays`, `DEFAULT_TIMEZONE = "Europe/Rome"`, `TIMEZONE_OPTIONS` |
| Default lead days, booking state machine, instant helpers | `lib/bookings.ts` | `DEFAULT_LEAD_DAYS` (module-private), `defaultLeadDays()`, `leadDaysOf()`, `TRANSITIONS`, `localInputToInstant()` |
| Stop ordering | `lib/stops.ts` | `SORT_ORDER_STEP = 1000`, `sortStops`, `nextSortOrder`, `renumber` |
| Civil-date arithmetic | `lib/dates.ts` | `datesInRange` (inclusive), `todayInTimezone` |
| The localStorage store | `lib/store.ts` | `createTrip`, `update()`, divergence handling, `applyFromSync`, `replaceStore` |
| Encrypted sync | `lib/sync.ts` | Detects changed trips by content hash and re-validates incoming trips with `tripSchema` |
| ICS export (uses leadDays) | `lib/ics.ts` | Not snapshotted |
| Better Auth server config | `lib/auth.ts` | |
| Env-derived server config | `lib/server/configurazione.ts` | `databaseUrl`, `authSecret`, `backendConfigurato`, `originiFidate` |
| Sign-up allowlist | `lib/server/registrazione.ts` | `emailAmmessa()` reads `EMAIL_AMMESSE` |
| Auth routes | `app/api/auth/[...all]/route.ts` | Catch-all; 503 when the backend isn't configured |
| Login page | `app/accedi/page.tsx` + `components/account.tsx` (`Accesso`) | |
| Backup export and import | `app/impostazioni/page.tsx` | `snapshotJson()` / `storeSchema.safeParse` + `replaceStore` |
| Real backup | `backup/pinzolo-2026-09.json` | Store-shaped. Used by `lib/schema.test.ts`. Not copied here (privacy) |

## 2. Shared formats and caps

### Primitive formats (`lib/schema.ts`)

| Name | Zod | Regex / bounds | Meaning |
|---|---|---|---|
| `isoDate` | `z.string().regex(...)` | `^\d{4}-\d{2}-\d{2}$` | Civil date. **Regex only**: `2026-02-30` is accepted. |
| `localTime` | `z.string().regex(...)` | `^([01]\d\|2[0-3]):[0-5]\d$` | `HH:mm` wall clock on the Day's date, in the trip timezone. `24:00` is rejected. |
| `instant` | `z.string().regex(...)` | `^\d{4}-\d{2}-\d{2}T([01]\d\|2[0-3]):[0-5]\d(:[0-5]\d)?(\.\d+)?(Z\|[+-]([01]\d\|2[0-3]):[0-5]\d)$` | Absolute instant with **mandatory** offset. Seconds and fraction are optional. `Z` is accepted. The offset can't carry seconds. |
| `latitude` | `z.number().min(-90).max(90)` | | |
| `longitude` | `z.number().min(-180).max(180)` | | |
| URLs | `z.string().max(2000)` | none | Deliberately free text, not `z.url()`. TripTracker normalises at render time (`externalHref` adds `https://`). |

Example instants that pass: `2026-11-14T15:00:00+00:00`, `2026-11-14T15:00:00Z`,
`2026-11-14T15:00+01:00`, `2026-11-14T15:00:00.123456+01:00`. Floating times fail
(`2026-11-14T15:00:00`).

Pydantic v2 (2.14) `AwareDatetime` serialises offset 0 as `Z` (`2026-11-14T15:00:00Z`, even
for `ZoneInfo("Europe/Lisbon")`), other offsets as `+01:00`, and microseconds as `.123456`.
All of these pass. `datetime.isoformat()` gives `+00:00`, which also passes.

### Caps: `LIMITE` (the spec's "tetti di LIMITE")

```ts
export const LIMITE = {
  titolo: 120, nome: 200, indirizzo: 300, telefono: 40,
  riferimento: 120, url: 2000, note: 4000, giorni: 120,
} as const;
```

| Cap | Value | Applied to |
|---|---|---|
| `titolo` | 120 | `Trip.title`, `Day.title`, `Stop.title`, `Booking.title` |
| `nome` | 200 | `Trip.destinationName`, `Trip.baseName`, `Stop.locationName`, `Booking.vendor` |
| `indirizzo` | 300 | `Trip.baseAddress`, `Stop.address` |
| `telefono` | 40 | `Booking.phone` |
| `riferimento` | 120 | `Booking.confirmationRef` |
| `url` | 2000 | `Stop.url`, `Booking.url` |
| `note` | 4000 | `Trip.notes`, `Day.notes`, `Stop.notes`, `Booking.notes` |
| `giorni` | 120 | `Trip.days` (array length) |

There are no caps on the number of stops per day, the number of bookings, `timezone`, or ids
(ids only need `min(1)`).

**Length unit:** zod 4.5.4 counts **Unicode code points** for string `.min/.max`. This was
verified both in `node_modules/zod/v4/core/checks.js` and by experiment: 61 astral emoji are
122 UTF-16 units and pass `max(120)`. Python `len()`, Pydantic `max_length` and jsonschema
`maxLength` count code points too, so the planner and TripTracker agree. The comment in
TripTracker's `lib/schema.test.ts` saying the cap is in UTF-16 units is stale for zod 4.5.4.
TripTracker's HTML `maxLength` in forms does count UTF-16 units, which only matters inside
TripTracker's own forms.

### Ids

- TripTracker generates `${prefix}_${crypto.randomUUID()}` with prefixes `trip`, `day`,
  `stop` and `booking` (`lib/trip.ts` `newId`). Example: `trip_1b9d6bcd-...`.
- The real backup uses hand-written slugs (`trip-pinzolo-2026-09`, `day-2026-09-07`,
  `stop-nardis`, `booking-garda-pranzo`).
- The schema accepts **any non-empty string**. A bare UUID v4 (what the spec asks for) is
  valid.

### null compared with absent, and unknown keys

- An optional field means the key is **absent**. `null` is rejected by Zod and by the JSON
  Schema (`baseName: null` fails both). The planner must drop `None` values. For example,
  use Pydantic `model_dump(mode="json", exclude_none=True)` on the Trip it builds, and make
  sure no required key is ever `None`.
- Unknown keys: Zod `z.object` **strips** them silently, so `/import` would accept them. The
  exported JSON Schema (`io: "output"`) has `additionalProperties: false` at every level, so
  the backend check **rejects** them. For example, a leaked `ref` or `stop_ref` on a Stop or
  Booking fails the backend check.

## 3. Trip, Day, Stop and Booking, field by field

"Req" means required. Types are Zod types. JSON Schema equivalents are in
`trip.schema.json`.

### Trip (`tripSchema`)

| Field | Type | Req | Constraint | Notes |
|---|---|---|---|---|
| `id` | string | yes | min 1 | |
| `title` | string | yes | min 1, max 120 | |
| `destinationName` | string | yes | max 200 | Always present, **may be `""`** |
| `timezone` | string | yes | min 1 | IANA by convention (`"Europe/Rome"` default). **No IANA validation** in the schema, but `date-fns-tz` display code throws on unknown zones. The planner must validate it with `zoneinfo`. |
| `startDate` | isoDate | yes | | |
| `endDate` | isoDate | yes | | `.refine(endDate >= startDate)` (string comparison), with the error on path `endDate`. **The refine is lost in the JSON Schema.** |
| `baseName` | string | no | max 200 | The lodging name |
| `baseAddress` | string | no | max 300 | |
| `baseLat` | number | no | [-90, 90] | |
| `baseLon` | number | no | [-180, 180] | |
| `notes` | string | no | max 4000 | |
| `coverSeed` | int | yes | safe integer, may be negative in the schema | See §4 |
| `icsSequence` | int | no | >= 0 | Calendar-export counter, incremented by `exportIcs`. The planner never sets it. |
| `days` | Day[] | yes | max 120 items | Order matters, see §4 |
| `bookings` | Booking[] | yes | unbounded | |

The Store wrapper (localStorage and backup file) is `{ schemaVersion: 1, trips: Trip[] }`
(`storeSchema`).

### Day (`daySchema`)

| Field | Type | Req | Constraint | Notes |
|---|---|---|---|---|
| `id` | string | yes | min 1 | |
| `tripId` | string | yes | min 1 | Redundant foreign key, must equal `Trip.id`. **Not enforced by the schema.** |
| `date` | isoDate | yes | | One Day per date in `[startDate, endDate]`, inclusive |
| `dayIndex` | int | yes | >= 0 | 0-based position. The UI shows "Giorno {dayIndex+1} di {days.length}". |
| `title` | string | no | max 120 | |
| `notes` | string | no | max 4000 | |
| `stops` | Stop[] | yes | unbounded | May be `[]` |

### Stop (`stopSchema`)

| Field | Type | Req | Constraint | Notes |
|---|---|---|---|---|
| `id` | string | yes | min 1 | |
| `dayId` | string | yes | min 1 | Must equal the parent `Day.id`. **Not enforced.** |
| `title` | string | yes | min 1, max 120 | |
| `kind` | enum | yes | `activity` \| `meal` \| `transfer` \| `rest` | |
| `startTime` | localTime | no | `HH:mm` | A label only. Stops without a time are legitimate. |
| `durationMin` | int | no | > 0 | |
| `locationName` | string | no | max 200 | |
| `address` | string | no | max 300 | |
| `lat` | number | no | [-90, 90] | The comment says always paired with `lon`. **The schema does not enforce the pair.** |
| `lon` | number | no | [-180, 180] | |
| `url` | string | no | max 2000 | Free text |
| `notes` | string | no | max 4000 | |
| `sortOrder` | number | yes | any finite float, may be negative | The ordering key, see §4 |
| `state` | enum | yes | `planned` \| `done` \| `skipped` | |

### Booking (`bookingSchema`)

| Field | Type | Req | Constraint | Notes |
|---|---|---|---|---|
| `id` | string | yes | min 1 | |
| `tripId` | string | yes | min 1 | Must equal `Trip.id`. **Not enforced.** |
| `stopId` | string | no | min 1 | Links to a Stop. **Referential integrity is not enforced**: a dangling id passes. |
| `title` | string | yes | min 1, max 120 | |
| `vendor` | string | no | max 200 | |
| `kind` | enum | yes | `restaurant` \| `wellness` \| `ticket` \| `parking` \| `transport` \| `lodging` \| `activity` \| `other` | |
| `status` | enum | yes | `to_book` \| `booked` \| `confirmed` \| `cancelled` | |
| `dueAt` | instant | no | offset mandatory | **By when to book** |
| `scheduledFor` | instant | no | offset mandatory | **When the thing happens** |
| `leadDays` | int | no | >= 0 | Reminder offset before `dueAt`. Absent means the kind default (§4). |
| `confirmationRef` | string | no | max 120 | Required by the UI to move a booking to `confirmed` |
| `phone` | string | no | max 40 | |
| `url` | string | no | max 2000 | Free text |
| `costCents` | int | no | >= 0 | Always shown as **EUR** (`formatCost` hard-codes EUR). There is no currency field. |
| `notes` | string | no | max 4000 | |
| `sortOrder` | number | yes | any float | Required. The bookings UI sorts by `dueAt`, not by this field (§4). |

The schema does not order `dueAt` against `scheduledFor`. "Book by" after "happens at" is
schema-valid.

## 4. Semantics

### sortOrder

- **Stops** are ordered by `sortOrder` ascending, **never by `startTime`**. Ties break on
  `id` (`localeCompare`). Steps are `SORT_ORDER_STEP = 1000`. A new stop at the end of a day
  gets `max + 1000` (or `1000` in an empty day). An insert between two stops gets the mean of
  its neighbours. `renumber()` rewrites to `1000, 2000, ...` only when floats run out of
  precision. Values are per day: every day starts at 1000. This matches the spec rule
  (`1000, 2000, 3000...` in the given order).
- **Bookings**: `addBooking` gives `1000` to the first booking, then `max + 1000`. The
  bookings page groups bookings ("In scadenza" for `to_book` with `dueAt` within 72 h, then
  "Da fare", "Fatte" (`confirmed`), "Annullate") and sorts each group by `dueAt`. Bookings
  without `dueAt` go last, sorted by title. `sortOrder` is required but not used for display.

### Stop.state

`planned`, `done` or `skipped`. In the day view `done` draws a solid line and filled node,
`planned` a dashed line and hollow node. Skipped stops are excluded from the ICS export. The
planner always emits `planned`.

### Booking.status (state machine in `lib/bookings.ts`, enforced by `setBookingStatus`)

```
to_book → booked → confirmed
   ↓        ↓          ↓
      cancelled → to_book
```

`confirmed` requires a non-blank `confirmationRef`. The planner always emits `to_book`. A
booking linked to a stop with status `to_book` shows the amber dot on that stop's node
(`hasPendingBooking`).

### The two dates (CLAUDE.md rule 1)

`dueAt` is *by when to book*. `scheduledFor` is *when it happens*. They are never merged and
always shown as two separate, labelled values: the booking sheet has "Entro quando
prenotare" and "Quando avviene". TripTracker's own UI writes both in the **trip timezone's**
offset (`localInputToInstant` → `yyyy-MM-dd'T'HH:mm:ssXXX`). The `XXX` pattern gives `Z` for
a zero offset. Verified: `Europe/Lisbon` 2026-11-14 15:00 gives `2026-11-14T15:00:00Z`, and
2026-10-20 20:00 gives `2026-10-20T20:00:00+01:00`. That is the same convention as Pydantic.
The fixture uses `+00:00` (`isoformat()`); both forms pass. Display always converts to the
trip timezone.

### Default lead times (`lib/bookings.ts`)

```ts
const DEFAULT_LEAD_DAYS: Record<BookingKind, number> = {
  restaurant: 2, wellness: 3, ticket: 3, parking: 1,
  transport: 1, lodging: 7, activity: 2, other: 2,
};
```

**Meaning in TripTracker:** `leadDays` (or this default when `leadDays` is absent) is how many
days **before `dueAt`** the reminder fires. In the ICS file, the deadline event (15 minutes at
`dueAt`, only for `to_book` bookings with a `dueAt`) gets `VALARM -P{lead}D`, plus a fixed
`-PT2H` safety alarm. A lead of 0 skips the first alarm. The booking sheet labels it
"Promemoria, giorni prima della scadenza". It is **not** an offset from `scheduledFor`.
`DEFAULT_LEAD_DAYS` is module-private (only `defaultLeadDays(kind)` is exported). It isn't in
the JSON Schema, so the planner has to copy these values, and they can drift silently. See
divergence A8.

### coverSeed

A stable random seed for cover decoration: "chosen once and kept, so the trip always looks
the same". TripTracker sets `Math.floor(Math.random() * 10000)`, an integer in **[0, 9999]**.
The schema accepts any safe integer, including negatives. At this commit nothing in the UI
reads it yet (`git grep` finds only the writer in `lib/trip.ts`). Recommendation: use
`random.randrange(10_000)`.

### Days and dayIndex

`buildDays` makes one Day per date in `datesInRange(startDate, endDate)` (inclusive), in date
order, with `dayIndex = position` and `stops: []`. The day view navigates by **array
position** and opens on the Day whose `date` is today in the trip timezone. The planner must
emit Days sorted by date, contiguous, with no duplicates, and with `dayIndex == index`. None
of this is enforced by the schema.

### timezone

The default is `Europe/Rome`. The new-trip form offers 8 zones (`Europe/Rome`,
`Europe/London`, `Europe/Lisbon`, `Europe/Athens`, `Europe/Moscow`, `America/New_York`,
`America/Los_Angeles`, `Asia/Tokyo`). There is no timezone editor after creation. Any valid
IANA name renders, because `date-fns-tz` and `Intl` accept it.

## 5. The store (`lib/store.ts`) and what `importTrip` has to respect

- **One blob** in `localStorage["trip-tracker:v1"]`, shaped `{schemaVersion: 1, trips}`. It is
  validated **on read** with `storeSchema`. If validation fails, the state becomes `corrupt`
  and the app **never writes again** (except an explicit backup import through
  `replaceStore`). It shows a banner that offers a raw export.
- **States:** `loading` (also the server snapshot), then `ready {persisted, divergente}`, or
  `corrupt`.
- **`update(recipe)`:**
  - Returns `false` unless the state is `ready`, so writes during `loading` and `corrupt` are
    refused.
  - It replaces the whole blob, debounced 300 ms (`schedulePersist`), and flushes on
    `pagehide` and `visibilitychange`.
  - It **inherits `divergente`**: a local edit does not clear it.
- **Divergent-tab suspension:**
  - A `storage` event for the store key raises `divergente`. The browser only sends that event
    to *other* tabs.
  - From then on `writeNow()` returns early. Edits still update memory, but **nothing reaches
    disk** until the user picks one of two options in `DivergenzaBanner`:
    - "Prendi la versione aggiornata" (`adottaVersioneSuDisco`) rehydrates from disk and
      **discards** unsaved local changes.
    - "Tieni questa e sovrascrivi" (`sovrascriviConQuestaScheda`) clears the flag and
      persists.
  - Consequence for `/import`: an import made in a divergent tab is visible but not saved.
    Adopting the disk version drops it.
- **`persisted: false`** means `setItem` threw (quota or denied). `PersistBanner` asks the
  user to export a backup.
- **`createTrip(input)`:**
  - Builds the trip, then validates it with `tripSchema.safeParse(trip).success`. If that
    fails it returns `null`: "the store doesn't accept what it couldn't read back".
  - It then appends via `update` and pushes the **original object**, not `parsed.data`. That
    is harmless there because `buildTrip` never adds extra keys.
  - The spec's `importTrip` should validate with `tripSchema` and append **`parsed.data`**, so
    unknown keys are stripped.
- **`applyFromSync(upserts, removals)`** is the sync entry point. It upserts by `id`, replacing
  whole trips. `importTrip` must *not* reuse it as is, because the spec says a duplicate `id`
  is not replaced ("Questo viaggio è già fra i tuoi").
- **`replaceStore(next)`** is the backup import. It replaces everything, is allowed from
  `corrupt`, and clears `divergente`.
- **Sync** (`lib/sync.ts`) keeps a per-trip hash index, so a trip added through `update()` is
  detected and pushed, encrypted, automatically if an account and key are configured.
  Incoming trips are re-validated with `tripSchema.safeParse`. On a version conflict the
  local copy becomes a new trip (`newId`, title suffix "(copia di questo dispositivo)").
- **Tests** live in `lib/store.test.ts` with `environment: "node"`. The tests stub `window`
  and `localStorage`, call `vi.resetModules()` per simulated tab, and dispatch `storage`
  events by hand. vitest only includes `lib/**/*.test.ts`.
- **Pages** (`app/trips/[tripId]/page.tsx` pattern): render nothing while `loading`, show
  `CorruptBanner` when `corrupt`, and show "Questo viaggio non c'è." when the trip is not
  found. `/trips/<id>` exists, so `/import` can redirect there.

## 6. Auth and configuration

### Better Auth (`lib/auth.ts`, better-auth 1.7.3)

- **Config:**
  - `betterAuth({ appName: "Trip Tracker", secret: authSecret, baseURL: process.env.BETTER_AUTH_URL, trustedOrigins: originiFidate, database: drizzleAdapter(pg), plugins: [nextCookies()] })`.
  - Email and password only, `minPasswordLength: 12`, `requireEmailVerification: false`.
  - Session `expiresIn` 30 days, `updateAge` 1 day.
  - Rate limit enabled with database storage (default window 10 s, max 100).
  - A `databaseHooks.user.create.before` hook rejects sign-up with 403 unless
    `emailAmmessa(email)`.
- **No `advanced` block** at this commit: no `crossSubDomainCookies`, no `cookiePrefix`, no
  `useSecureCookies`, and no session `cookieCache`.
- **Cookie names** (from `better-auth/dist/cookies/index.mjs`):
  - The name is `${secure ? "__Secure-" : ""}better-auth.<name>`. `secure` is true when
    `BETTER_AUTH_URL` starts with `https://`, or with no baseURL when
    `NODE_ENV=production`.
  - Production: **`__Secure-better-auth.session_token`**, which matches the spec. Local http
    dev: `better-auth.session_token`.
  - Also possible: `...better-auth.dont_remember`. `...session_data` (cookie cache) is
    disabled.
  - Attributes: HttpOnly, `SameSite=Lax`, `Path=/`, Secure in production, `Max-Age` 30 days.
    The cookie is **host-only** today (no `Domain`).
  - The value is a **signed** cookie, `<token>.<hmac>` (URL-encoded). The planner should hash
    the raw cookie value for its cache key and forward the `Cookie` header untouched.
  - With `advanced.crossSubDomainCookies: { enabled: true, domain: "bellittim.com" }` the same
    name gets `Domain=bellittim.com`. Better Auth throws at startup if it is enabled with
    neither a domain nor a baseURL.
- **get-session:**
  - Request: `GET https://viaggi.bellittim.com/api/auth/get-session` (default basePath
    `/api/auth`, served by the catch-all `app/api/auth/[...all]/route.ts`). `POST` is
    rejected unless `deferSessionRefresh` is set.
  - With a valid session it returns **200** with
    `{ "session": {id, token, userId, expiresAt, createdAt, updatedAt, ipAddress, userAgent}, "user": {id, email, name, emailVerified, image, createdAt, updatedAt} }`.
  - Without a session it returns **200 with the JSON body `null`**, not 401. The planner must
    map `null` to 401.
  - It returns **503** `{"message": "Gli account non sono configurati su questo server."}`
    when `DATABASE_URL` is missing, or when `BETTER_AUTH_SECRET` is missing in production.
  - Headers: `Cache-Control: no-store`. It may also send `Set-Cookie` (a daily session
    refresh), which the planner should ignore.
  - The response contains `session.token`, so never log it.
- **Client:** `lib/auth-client.ts` uses `createAuthClient()` with no baseURL (same origin).
- **Identity in TripTracker routes:** `lib/server/sessione.ts` `utenteCorrente()` uses
  `auth.api.getSession({ headers })` and returns the user id or `null`.

### `lib/server/configurazione.ts` (`import "server-only"`)

- `databaseUrl = process.env.DATABASE_URL`.
- `authSecret = BETTER_AUTH_SECRET`. Outside production the fallback is the string
  `"sviluppo-locale-non-usare-in-produzione"`. In production without a secret it is
  `undefined`.
- `backendConfigurato = Boolean(databaseUrl && authSecret)`. When it is false, the auth and
  sync routes answer 503 and the rest of the app works.
- `originiFidate`:
  - Built from `ORIGINI_FIDATE`, a comma-separated list. Each entry is trimmed and loses any
    trailing `/`. Empty entries are dropped, so an empty variable means `[]`.
  - It is passed to Better Auth as `trustedOrigins`, *in addition to* the `BETTER_AUTH_URL`
    origin.
  - It was introduced by the HEAD commit 71be320 for the migration from
    `trip-tracker-nu-ivory.vercel.app` to `viaggi.bellittim.com`, so the old PWA can still
    sync.
- There is nothing about cookie domains yet. `COOKIE_DOMAIN` is new and belongs here. New
  code is in English per spec decision 4, while the file name stays Italian.

### `EMAIL_AMMESSE` (`lib/server/registrazione.ts`)

`emailAmmessa(email)` splits the variable on commas, then trims and lowercases each entry.
An empty variable means **nobody**, and `"*"` means **everybody**. It gates **sign-up only**,
through the user-create hook. Existing accounts keep signing in even when they are not in the
list, so a valid TripTracker session does not imply the email is in `EMAIL_AMMESSE`.

### `/accedi` (`app/accedi/page.tsx`, client component)

- `useSession()` drives the page:
  - While pending, it renders nothing below the heading.
  - Offline, with no session and a sync key on the device, it shows `SenzaRete`.
  - Already signed in, it shows "Sei già collegato come <email>" with links to "/" and
    "/impostazioni".
  - Otherwise it shows the `Accesso` form (`components/account.tsx`), with sign-in and
    invite-only sign-up.
- After a successful sign-in, `onSuccess` calls `router.replace("/")`, after
  `registraIngresso("account")`.
- "Entra come ospite" sets the guest flag and goes to "/".
- `/accedi` is in the service worker precache. **There is no `returnTo` handling today.**

### `next.config.ts`

An empty `NextConfig` (`{}`): no headers, rewrites, CORS or env. `.env.example` lists
`DATABASE_URL`, `BETTER_AUTH_SECRET`, `BETTER_AUTH_URL` (commented), `ORIGINI_FIDATE`
(commented, example `https://trip-tracker-nu-ivory.vercel.app`) and `EMAIL_AMMESSE=`.
`AGENTS.md` warns that Next 16 differs from training data and points to
`node_modules/next/dist/docs/`.

### CLAUDE.md rules the PR must keep

- The two booking dates stay separate and labelled, including in previews.
- Amber is only for deadlines: never on the import button. Text uses `amber-ink`; strokes use
  `--amber`.
- No identical card grids: a day is a vertical sequence on the route line.
- Copy is in sentence case, buttons say what happens, empty states are invitations, and
  errors say what was not saved and how to fix it.
- The store never writes what it couldn't read back.
- Look at the day view in the browser.
- Every new animation declares its reduced-motion behaviour.
- One phase per session, one commit per phase.

## 7. JSON Schema compared with Zod

`trip.schema.json` was produced by a script equivalent to the one below. It ran with the
clone's own `node_modules/.bin/tsx` and resolved `zod` and `lib/schema.ts` from the clone
after `npm ci`. To regenerate, run it the same way and copy the output over the fixture.

```ts
import { writeFileSync } from "node:fs";
import { z } from "zod";                 // 4.5.4, from the clone's node_modules
import { tripSchema } from "./lib/schema";
writeFileSync(process.argv[2], JSON.stringify(z.toJSONSchema(tripSchema), null, 2) + "\n");
```

`$schema` is `https://json-schema.org/draft/2020-12/schema` (use
`jsonschema.Draft202012Validator`). With `{ io: "input" }` the only difference is that
**`additionalProperties: false` disappears** at all four object levels. The default
(`"output"`) is what TripTracker will export if it calls `z.toJSONSchema(tripSchema)` as the
spec says.

Parity checks run against the fixture. Zod ran in node; the JSON Schema check ran in Python
jsonschema 4.26.0.

| Probe | Zod `tripSchema` | JSON Schema (Python) |
|---|---|---|
| Title of 121 chars | reject | reject |
| Title of 61 astral emoji (122 UTF-16 units) | accept (code points) | accept |
| Empty title | reject | reject |
| `endDate < startDate` | **reject** (refine) | **accept** (refine not exported) |
| Unknown key (e.g. `summary`) | **accept and strip** | **reject** (`additionalProperties: false`) |
| `baseName: null` | reject | reject |
| `dueAt` without offset | reject | reject |
| `dueAt` with `Z`, without seconds, or with microseconds | accept | accept |
| `date: "2026-02-30"` | accept (regex only) | accept |
| Date written with Arabic-Indic digits | **reject** (JS `\d` is ASCII) | **accept** (Python `re` `\d` is Unicode) |
| `startTime: "24:00"` | reject | reject |
| `durationMin: 0` | reject | reject |
| `lat: 91` | reject | reject |
| `lat` without `lon` | accept | accept |
| `costCents: 10.5` / `-1` / `true` | reject | reject |
| `costCents: 10.0` | accept (JSON `10.0` parses to 10) | accept (integral float) |
| 121 days | reject | reject |
| Dangling `stopId`, non-IANA `timezone`, `id: "x"`, negative `coverSeed` | accept | accept |

The backend's `jsonschema` check therefore does **not** catch:

- `endDate < startDate`
- non-ASCII digits
- dangling references (`stopId`, `tripId`, `dayId`)
- invalid calendar dates
- invalid timezones
- days that don't cover the range or are out of order

Validate these in the Plan or in `plan_to_trip`. The check is **stricter** than `/import` on
unknown keys.

## 8. Divergences: spec compared with TripTracker

### A. The mapping table ("Contratto del piano") compared with TripTracker reality

1. **Id format.** The spec generates **UUID v4** for `trip.id`, `day.id`, `stop.id` and
   `booking.id`. TripTracker's own convention is `trip_<uuid>`, `day_<uuid>`, and so on; the
   backup uses slugs. Both are valid because the schema only needs `min(1)`. `importTrip`
   deduplicates by `id`, so `GET /plans/{id}/trip` must return the **same stored Trip** every
   time and must not generate new ids per request. Otherwise a re-import duplicates the trip.
2. **Required TripTracker fields with no rule in the table.**
   - `Day.id`, `Day.tripId`, `Day.dayIndex`, `Stop.id`, `Stop.dayId`, `Booking.id`,
     `Booking.tripId` and **`Booking.sortOrder`** are all required. The spec only defines
     `sortOrder` for stops.
   - Recommendation: give bookings `1000, 2000, ...` in plan order, as `addBooking` does.
   - `dayIndex` must equal the array position, with Days in date order.
3. **Renamed fields missing from the table.** These are implied but unlisted:
   - `PlanBooking.link` → `Booking.url`
   - `PlanStop.start_time` / `duration_min` / `location_name` → `startTime` / `durationMin` /
     `locationName`. The spec says the names "ricalcano" TripTracker's, but they are
     snake_case against camelCase.
   - `PlanDay.title` → `Day.title`
   - `PlanStop.url` / `notes` / `address` / `kind` / `title` → the same names
   - `PlanBooking.vendor` / `phone` / `title` / `kind` → the same names
4. **TripTracker fields the planner never fills** (all optional, so this is valid):
   - `Trip.notes`: `Plan.summary` stays in the planner.
   - `Trip.baseLat` and `Trip.baseLon`: `LodgingOption` has lat/lon, but the Plan drops them.
     Consider adding `lodging_lat` and `lodging_lon`.
   - `Trip.icsSequence`, `Day.notes` (PlanDay has no notes), `Booking.leadDays`,
     `Booking.confirmationRef`.
5. **The day range is not validated by the Plan.**
   - TripTracker refines `endDate >= startDate`. That refine is not in the JSON Schema, so
     only `/import` would catch it.
   - TripTracker caps `days` at 120. The mapping generates one Day per date in the range,
     not per `PlanDay`. The binding limit is therefore `(end_date - start_date) + 1 <= 120`,
     which the Plan doesn't check. `Plan.days: max_length=120` doesn't cover it.
   - The spec doesn't define what happens to a `PlanDay` whose date is outside the range, or
     to two PlanDays with the same date. Recommendation: reject both in the Plan validator.
6. **Empty titles.** TripTracker requires `min(1)` on `Trip.title`, `Stop.title` and
   `Booking.title`. The Plan only has `max_length=120`, so `""` passes Pydantic and fails
   TripTracker. Add `min_length=1`. `Plan.destination` may be `""` in TripTracker and that is
   fine.
7. **Coordinates.** TripTracker bounds `lat` to [-90, 90] and `lon` to [-180, 180]. `PlanStop`
   has unbounded `float`. Add `ge`/`le`. The spec's rule "coordinate solo se presenti
   entrambe" is planner-side only, because TripTracker's schema does not enforce pairing.
8. **The default lead time has a different meaning.**
   - The spec's fallback is `dueAt = scheduled_for - default lead of the kind`.
   - The values match TripTracker exactly: restaurant 2, wellness 3, ticket 3, parking 1,
     transport 1, lodging 7, activity 2, other 2.
   - In TripTracker that number is the **reminder offset before `dueAt`**, not a deadline
     offset from `scheduledFor`.
   - Effect: when the planner leaves `leadDays` unset, the first alarm fires `lead` days
     before the computed `dueAt`. That is `2 × lead` before the event: 14 days before a
     lodging check-in, 2 days before a transport.
   - The table is module-private and not exported in `trip.json`, so the planner must
     hard-code it, and it won't notice a change. Suggestion for the TripTracker PR: export it,
     for example as a top-level `"x-defaultLeadDays"` in `trip.json`, or as
     `public/schema/booking-lead-days.json`.
9. **"Mai prima di domani" can invert the dates.**
   - Clamping a fallback `dueAt` to tomorrow gives `dueAt >= scheduledFor` when the event is
     tomorrow or earlier.
   - TripTracker accepts that, but the eval check ("nessuna prenotazione ha book_by uguale a
     scheduled_for o successivo") and CLAUDE rule 1 don't.
   - "Tomorrow" also needs a defined timezone: the trip's, not the server's.
10. **Booking notes overflow.**
    - The spec appends one line each for `price.status`, `price.source_url` and
      `book_by_reason`, plus FX details (amount, currency, rate, source), to `notes`.
    - `PlanBooking.notes` is already capped at 4000, which equals TripTracker's cap.
      `book_by_reason` and `source_url` have **no cap** in the Plan.
    - So the combined text can exceed 4000 and be rejected.
    - `plan_to_trip` needs a budget, for example truncating the free-text part first. The
      Plan validator should also cap `book_by_reason`.
11. **`stop_ref` resolution.** TripTracker does not check that `stopId` points to an existing
    stop. A dangling id passes and just never lights the amber dot. The spec doesn't say what
    an unknown `stop_ref` does. Recommendation: reject it in the Plan validator; tests
    already require "stopId risolto dallo stop_ref".
12. **Timezone.** TripTracker only requires a non-empty string, and `Plan.timezone` is a bare
    `str`. An invalid IANA name passes both schemas, then crashes TripTracker's
    `formatInTimeZone` on the bookings page. Validate it with
    `zoneinfo.ZoneInfo(timezone)`. Instants must be rendered in that zone; Pydantic prints
    offset 0 as `Z`, which is accepted.
13. **Currency.** `costCents` has no currency and is always formatted as EUR. This matches the
    spec's conversion rule. Non-EUR prices must be converted, or left out of `costCents`.
14. **null handling.** The spec doesn't mention it. TripTracker rejects `null` for every
    optional field, so dump with `exclude_none`.
15. **coverSeed.** The spec says "casuale". TripTracker uses [0, 9999]. Any int is valid, but
    use the same range.
16. **The single source of truth doesn't exist yet.**
    - The spec says TripTracker exports `public/schema/trip.json` at every build. At
      71be320 there is no `public/schema/` and no prebuild step: `"build": "next build"`.
      `tsx` is only a transitive dependency of drizzle-kit, not a direct devDependency.
    - Options for the PR:
      - A `prebuild` script with `tsx` added as a devDependency.
      - A statically rendered route handler at `/schema/trip.json`, which needs no build
        script.
    - Until then, the backend can't download it at startup. Use this fixture or a pinned copy
      as the fallback.
17. **The JSON Schema is not equivalent to Zod** (§7).
    - The refine is lost, unknown keys are rejected rather than stripped, and `\d` matches
      Unicode digits in Python.
    - So "rivalida comunque con Zod: è l'ultima parola" is necessary, not just a formality.
    - The backend could compile patterns with ASCII semantics. In practice the backend
      formats dates itself, so the digit issue is theoretical.

### B. TripTracker caps compared with the spec's Plan model caps

| TripTracker field (cap) | Plan field (cap) | Status |
|---|---|---|
| `Trip.title` (1..120) | `Plan.title` (≤120) | Max matches; **min 1 missing** |
| `Trip.destinationName` (≤200) | `Plan.destination` (≤200) | Matches |
| `Trip.baseName` (≤200) | `Plan.lodging_name` (≤200) | Matches |
| `Trip.baseAddress` (≤300) | `Plan.lodging_address` (≤300) | Matches |
| `Trip.baseLat` / `baseLon` (ranges) | none | Not produced |
| `Trip.notes` (≤4000) | none (`summary` ≤4000 stays in the planner) | Not produced |
| `Trip.days` (≤120 items) | `Plan.days` (≤120 items) | **Not equivalent**: TripTracker counts every date in `[start, end]`. The Plan must cap the range. |
| `Trip.timezone` (min 1) | `Plan.timezone` (str) | Add IANA validation |
| `Day.title` (≤120) | `PlanDay.title` (≤120) | Matches |
| `Day.notes` (≤4000) | none | Not produced |
| `Stop.title` (1..120) | `PlanStop.title` (≤120) | **min 1 missing** |
| `Stop.locationName` (≤200) | `PlanStop.location_name` (≤200) | Matches |
| `Stop.address` (≤300) | `PlanStop.address` (≤300) | Matches |
| `Stop.url` (≤2000) | `PlanStop.url` (≤2000) | Matches |
| `Stop.notes` (≤4000) | `PlanStop.notes` (≤4000) | Matches (nothing is appended to stop notes) |
| `Stop.lat` [-90, 90] / `lon` [-180, 180] | `PlanStop.lat` / `lon` (unbounded) | **Bounds missing** |
| `Stop.startTime` (`HH:mm` regex) | `PlanStop.start_time` (same regex) | Matches |
| `Stop.durationMin` (int > 0) | `PlanStop.duration_min` (`PositiveInt`) | Matches |
| `Booking.title` (1..120) | `PlanBooking.title` (≤120) | **min 1 missing** |
| `Booking.vendor` (≤200) | `PlanBooking.vendor` (≤200) | Matches |
| `Booking.phone` (≤40) | `PlanBooking.phone` (≤40) | Matches |
| `Booking.url` (≤2000) | `PlanBooking.link` (≤2000) | Matches (renamed) |
| `Booking.notes` (≤4000) | `PlanBooking.notes` (≤4000) + appended provenance lines (uncapped `book_by_reason`, `source_url`, FX line) | **Can overflow** |
| `Booking.costCents` (int ≥ 0) | `Price.amount_cents` (int ≥ 0) + FX conversion | Matches; rounding must stay an int |
| `Booking.confirmationRef` (≤120) | none | Not produced |
| `Booking.dueAt` / `scheduledFor` (instant with offset) | `book_by` / `scheduled_for` (`AwareDatetime`) | Matches; serialise in the trip timezone |
| `Booking.kind` (8 values) | `PlanBooking.kind` (the same 8 values) | Matches |
| `Stop.kind` (4 values) | `PlanStop.kind` (the same 4 values) | Matches |
| Unit of string length: code points (zod 4.5.4) | code points (Pydantic) | Matches |

### C. Other spec statements compared with TripTracker reality (auth and the PR)

1. **Cookie name.** `__Secure-better-auth.session_token` in production is correct. In local
   http dev the name has no prefix (`better-auth.session_token`). If `AUTH_MODE=local` is not
   used, the planner must accept both names.
2. **`get-session` returns `null` with status 200** when signed out, not 401. It returns 503
   when TripTracker's backend is unconfigured. The spec's `current_user()` must handle both.
3. **`crossSubDomainCookies` is absent today.** Spec: active only when `COOKIE_DOMAIN` is set.
   Migration risks after the PR:
   - Existing sessions keep a **host-only** cookie until Better Auth re-sets it, at the next
     daily refresh (`updateAge` = 1 day) or the next sign-in. Until then the planner gets no
     cookie, returns 401, and sends the user to `/accedi`.
   - `/accedi` shows "Sei già collegato" to an already signed-in user and doesn't re-issue the
     cookie, which can **loop**.
   - A host-only cookie and a `Domain=bellittim.com` cookie with the same name can coexist on
     `viaggi.`.
   - The PR should handle this: for example, re-issue the session cookie when `/accedi` is
     opened with a `returnTo`, or document "esci e rientra".
4. **`ORIGINI_FIDATE` is real and in production**, added by the HEAD commit. It currently
   lists only the old Vercel URL (see `.env.example`). It is consumed as Better Auth
   `trustedOrigins`.
   - It lives in a `server-only` module, so the **client** page `/accedi` can't read it to
     validate `returnTo`.
   - The PR needs a server component (for example, `page.tsx` reading `searchParams` and
     passing a validated `returnTo` to a client child) or a small route.
   - A cross-origin `returnTo` requires `window.location.assign`, not `router.replace`.
   - The "already signed in" branch must also honour `returnTo`.
   - Allowed targets should be the `BETTER_AUTH_URL` origin plus `originiFidate`. Compare
     exact origins, never prefixes.
5. **`EMAIL_AMMESSE` supports `"*"`** (everyone) and is case-insensitive. The spec says
   `PLANNER_ALLOWED_EMAILS` works "come EMAIL_AMMESSE", with empty meaning nobody. Decide
   explicitly whether `"*"` is supported; recommendation: don't support it. Compare emails
   lowercased and trimmed. `EMAIL_AMMESSE` gates sign-up only, so the planner's own allowlist
   check stays necessary.
6. **Routes.** TripTracker routes are Italian (`/accedi`, `/impostazioni`,
   `/trips/[tripId]/prenotazioni`). The new `/import` (English) and the existing `/trips/<id>`
   redirect target are consistent with the spec. `/import` is not in the service worker
   precache, which is fine: it needs the network anyway.
7. **`importTrip` must go through `update()`.** The spec requires it. Callers must wait for
   `status === "ready"`; `update()` returns `false` in `loading` and `corrupt`. They must also
   accept that a divergent tab keeps the import in memory only until the user resolves the
   banner (§5).
8. **The spec's Pinzolo backup exists:** `backup/pinzolo-2026-09.json`. It is store-shaped,
   with 1 trip, 6 days (the first with no stops), 19 stops and 5 bookings, all `planned` and
   `to_book`. Its ids are slugs, it has no coordinates, and its longest title is 43 chars.

## 9. The fixture (`backend/tests/fixtures/triptracker/valid_trip.json`)

- **Origin:** derived from the Pinzolo backup's shape: six days, an arrival day, all four stop
  kinds, bookings linked to stops, one booking with a phone, bookings with `costCents`. Names,
  places and dates were changed to "Lisbona, novembre", 2026-11-14 to 2026-11-19, timezone
  `Europe/Lisbon`.
- **Shaped like specified `plan_to_trip()` output:**
  - UUID v4 ids from a seeded RNG, so the file is deterministic.
  - `state: "planned"` and `status: "to_book"`.
  - `sortOrder` at `1000, 2000, ...` per day, and for bookings.
  - `dayIndex == position`, with `tripId` and `dayId` consistent.
  - `coverSeed` in [0, 9999].
  - No `null` values.
- **Coverage:**
  - 6 days, 19 stops and 8 bookings.
  - One Day (2026-11-18) has no title and no stops.
  - Some stops have no `startTime`; some have paired `lat`/`lon`, `url` or `address`.
  - Booking kinds covered: lodging, transport ×2, restaurant, ticket ×3, other.
  - One booking has no `stopId` and no `scheduledFor`, only a `dueAt`.
  - Two bookings share an explicit `dueAt` in **summer time**, `2026-10-20T20:00:00+01:00`,
    while the trip itself is in winter time (`+00:00`). This shows that offsets follow the
    date in the trip timezone.
  - Bookings without an explicit deadline use the spec's fallback, computed from
    `DEFAULT_LEAD_DAYS`. Example: lodging `scheduledFor 2026-11-14T15:00:00+00:00` gives
    `dueAt 2026-11-07T15:00:00+00:00`.
- **Provenance lines are illustrative.** Notes lines such as "Prezzo: stimato",
  "Fonte del prezzo: …" and "Perché entro questa data: …" are **not** a normative format. The
  real format belongs to `mapping.py`.
- **Real-world names:** vendors and landmarks are real public places or generic names. The
  phone number is a placeholder (`+351 21 000 0000`).
- **Absolute dates:** the earliest `dueAt` is 2026-10-20, written on 2026-10-12. Any test
  that compares the fixture with "now" (for example "dueAt never in the past") must freeze
  the clock.
- **Validated with:**
  - `tripSchema.parse(trip)` in the clone (`./node_modules/.bin/tsx`). The output equals the
    input (lossless).
  - `storeSchema.parse({schemaVersion: 1, trips: [trip]})`.
  - `uv run --no-project --with jsonschema python -c "...Draft202012Validator(schema).validate(trip)"`,
    which passes. `check_schema` passes too.
- **Useful negative mutations** for contract tests:
  - Each of these fails both validators: `title` of 121 chars, `baseName: null`, a `dueAt`
    without an offset, `durationMin: 0`, `lat: 91`.
  - An extra key fails the backend check only.
  - `endDate < startDate` fails Zod only.
