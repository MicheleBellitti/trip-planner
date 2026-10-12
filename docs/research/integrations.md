# External integrations: research notes

Research date: 2026-10-12 (checks run 2026-10-11 23:50Z to 2026-10-12 00:40Z). Spec sections this
covers: "Skills personalizzate" (booking-links), "Sicurezza e privacy" (domain check on MCP links),
"Conversione delle valute" (`backend/app/fx.py`), "Ambiente" (`allowed_hosts`) and "MCP e permessi".

How the evidence was gathered:

- Booking sites were opened with plain GET navigations in a real browser pane, and the
  prefilled form fields were read back from the DOM. No form was submitted, nothing was clicked
  except one Google consent page, where "Rifiuta tutto" was chosen (the decline option), and two
  harmless UI toggles. No cookie banner was accepted.
- The FX, Photon and Open-Meteo APIs were called with `curl` (GET only, free public APIs).
- No MCP server was contacted. Section 4 relies only on public pages and the MCP directory
  listing.

Status tags used below:

| Tag | Meaning |
|-----|---------|
| **[V]** | Verified. Observed directly on the research date, either a page prefilled with the expected values or an API response. |
| **[D]** | Documented. Stated by an official page or doc but not observed working. |
| **[U]** | Unverified. Inferred, from a third-party page, or not testable offline. |

Sites change their URL schemes without notice (the spec rates this risk as "media nel tempo"). Re-run
the checks in the "Day-1 / release checklist" at each release.

---

## 1. Booking deep links

### 1.1 Quick reference

| Provider | Template status | Place format | Date format | Children with ages | Rooms |
|---|---|---|---|---|---|
| Booking.com | **[V]** | free text (`ss`), Italian names OK | `YYYY-MM-DD` | yes: `group_children` + repeated `age` | `no_rooms` |
| Airbnb | **[V]** | path slug (`Lisbona--Portogallo`) | `YYYY-MM-DD` | counts only (`children` 2–12, `infants` <2) | n/a |
| Google Flights | **[V]** | IATA or city inside `q` | `YYYY-MM-DD` inside `q` | counts only, in `q` | n/a |
| Expedia hotels | **[V]** | free text `destination` | `YYYY-MM-DD` | yes: `children=<room>_<age>,…` | `rooms` + per-room `adults` |
| Expedia flights | **[V]** | IATA (airport or metro code) | `YYYY-MM-DD` + `TANYT` | yes: `children:N[a;b]` | n/a |
| Kiwi.com | **[V]** | city slug matching the URL locale; raw IATA fails | `YYYY-MM-DD` path segment | counts only | n/a |
| lastminute.com | **[V]** (www.lastminute.com) / **[U]** (Italian host) | IATA airport or metro code | `YYYYMMDD` | children count **[V]**; age param **[U]** | n/a |
| Trenitalia | **[V]** | station name | `DD-MM-YYYY` + hour | counts only (adults, ragazzi) | n/a |
| Italo | **[V]** | Italo station code (`MC_`, `RMT`) | `DD/MM/YYYY` | by age band (`chd`, `yng`, `inf`) | n/a |
| Omio | **[V]** (prefilled form, not results) | route slug or numeric position ID | `DD/MM/YYYY` | not prefillable **[V]** | n/a |

Placeholders below use `{name}` and are URL-encoded with `urllib.parse.quote` unless stated. All
examples were the exact URLs tested.

### 1.2 Booking.com: verified

```
https://www.booking.com/searchresults.it.html?ss={destination}&checkin={YYYY-MM-DD}&checkout={YYYY-MM-DD}
  &group_adults={adults}&group_children={n_children}[&age={age_1}&age={age_2}…]&no_rooms={rooms}&selected_currency=EUR
```

- **[V]** Tested `…searchresults.it.html?ss=Lisbona&checkin=2026-11-14&checkout=2026-11-18&group_adults=2&group_children=2&age=8&age=5&no_rooms=1&selected_currency=EUR`.
  The page heading read "Lisbona: 2.482 strutture trovate". The search bar showed "sab 14 nov" /
  "mer 18 nov" / "2 adulti · 2 bambini · 1 camera". The occupancy popup had the two child-age
  selects set to 8 and 5.
- **[V]** The spec's template also works:
  `searchresults.html?ss=Pinzolo&checkin=2026-12-27&checkout=2026-12-30&group_adults=2&group_children=0&no_rooms=1&lang=it&selected_currency=EUR`
  showed "Pinzolo: 2 strutture trovate", "dom 27 dic"/"mer 30 dic" and "2 adulti · 0 bambini · 1 camera".
  The language comes from either `.it.html` or `lang=it`.
- `age`: one repeated parameter per child, in order. The picker offers 0–17 and labels the age
  "obbligatoria" (age at check-out). **[V]**
- `ss` accepts Italian exonyms ("Lisbona"). **[V]**
- Booking adds `chal_t=…&force_referer=` after its bot challenge. Plain `curl` gets an AWS WAF
  challenge (HTTP 202), so `build_link.py` tests must check URL structure, not fetch the page. **[V]**

### 1.3 Airbnb: verified

```
https://www.airbnb.it/s/{place_slug}/homes?checkin={YYYY-MM-DD}&checkout={YYYY-MM-DD}&adults={adults}&children={n_2_to_12}&infants={n_under_2}&pets=0
```

- **[V]** Tested `https://www.airbnb.it/s/Lisbona--Portogallo/homes?checkin=2026-11-14&checkout=2026-11-18&adults=2&children=2&infants=0&pets=0`.
  The page heading read "Oltre 1.000 alloggi: Lisbona", the filters "14–18 nov, 4 ospiti" and the
  prices were "… € in totale".
- **[V]** With `adults=2&children=1&infants=1` the page shows "3 ospiti": infants do not count as
  guests.
- `place_slug`: comma-separated parts joined with `--`, spaces become `-` ("Reggio Emilia, RE" →
  `Reggio-Emilia--RE`). **[V]** `/s/homes?query=Reggio%20Emilia%2C%20Italia` was rewritten by
  Airbnb to `/s/Reggio-Emilia--Italia/homes`, which confirms the rule. It also resolved to the
  wrong place ("Italia in miniatura"). `Reggio-Emilia--RE` resolved correctly. **The agent must
  pass the most specific place it can (city + province or country).**
- No child ages in the URL. Airbnb's age bands are infants under 2 and children 2–12 (Airbnb help
  article 433 mentions "under the age of 2"; the 2–12 band is **[U]**, from the guest picker as
  commonly shown). Teenagers aged 13–17 should be counted as `adults`.
- The spec's template (`/s/{dest}/homes?checkin=&checkout=&adults=`) is correct.

### 1.4 Google Flights: verified (English query)

```
https://www.google.com/travel/flights?q={q}&hl=it&gl=IT&curr=EUR
q (round trip): "Flights to {TO} from {FROM} on {YYYY-MM-DD} through {YYYY-MM-DD} for {a} adults and {c} children"
q (one way):    "One way flights to {TO} from {FROM} on {YYYY-MM-DD} for {a} adult(s)"
```

- **[V]** `q=Flights to LIS from MXP on 2026-11-14 through 2026-11-18&hl=it&gl=IT&curr=EUR` gave
  "Andata e ritorno", "Milano MXP" → "Lisbona LIS", "sab 14 nov" / "mer 18 nov". Adding
  `for 2 adults and 2 children` gave "4 passeggeri".
- **[V]** `q=One way flights to FCO from LHR on 2026-12-03 for 1 adult` gave "Sola andata",
  "Londra LHR" → "Roma FCO", "gio 3 dic", "1 passeggero".
- **[V], with a caveat:** the spec's Italian query `q=voli da Milano a Lisbona il 2026-11-14` parsed
  the cities and the date, but kept the trip type "Andata e ritorno" and a return date left over
  from the previous query in the same browser. **Use the English form with an explicit trip type.**
- Children are "bambino dai 2 agli 11 anni" in Google's picker **[V]**. Ages cannot be passed. The
  phrasing for infants is **[U]**.
- `hl`, `gl` and `curr` set the language, country and currency **[V]** (the page rendered in
  Italian). Google can show a consent interstitial at `consent.google.com` first. A user's own
  browser normally already has consent stored.
- `google.com/travel/flights?tfs=…` (protobuf) also exists. Do not use it: it is undocumented and opaque.

### 1.5 Expedia hotels and flights: verified on www.expedia.it

Hotels:

```
https://www.expedia.it/Hotel-Search?destination={destination}&startDate={YYYY-MM-DD}&endDate={YYYY-MM-DD}
  &rooms={n_rooms}&adults={adults_room1}[,{adults_room2}…]&children={room}_{age}[,{room}_{age}…]
```

- **[V]** `destination=Lisbona, Portogallo&startDate=2026-11-14&endDate=2026-11-18&adults=2&children=1_8,1_5&rooms=1`
  showed "405 strutture a Lisbona … Check-in il giorno 14 novembre 2026, check-out il giorno 18
  novembre 2026" and "Persone, 4 persone, 1 camera", with child-age selects at 8 and 5.
- **[V]** Multi-room: `adults=2,1&children=1_8,2_5&rooms=2` gave "5 persone, 2 camere" (room 1:
  2 adults + child 8; room 2: 1 adult + child 5).
- Expedia rewrites the URL, adding `regionId=2080&sort=RECOMMENDED…`.

Flights:

```
https://www.expedia.it/Flights-Search?trip=roundtrip
  &leg1=from:{FROM},to:{TO},departure:{YYYY-MM-DD}TANYT
  &leg2=from:{TO},to:{FROM},departure:{YYYY-MM-DD}TANYT
  &passengers=adults:{a},children:{c}[{age_1};{age_2}],seniors:0,infantinlap:N
  &options=cabinclass:economy&mode=search
(one way: trip=oneway and only leg1)
```

- **[V]** Round trip MXP⇄LIS 2026-11-14/18 with `children:2[8;5]` gave the title "Voli da MXP a
  LIS", "sab 14 nov - mer 18 nov", "4 persone, Economy", child-age selects at 8 and 5, and results
  ("Scegli il volo di andata per Lisbona").
- **[V]** One way `trip=oneway&leg1=from:FCO,to:BCN,departure:2026-12-03TANYT&passengers=adults:1,…`
  gave "Voli da FCO a BCN", "Data, gio 3 dic", "1 persona, Economy".
- ISO dates work on the Italian site **[V]**. The characters `:`, `,`, `[`, `;` were sent
  unencoded and worked.
- `curl` gets HTTP 429 from expedia.*, so tests must check URL structure only.

### 1.6 Kiwi.com: verified (city slugs)

```
https://www.kiwi.com/en/search/results/{from_slug}/{to_slug}/{YYYY-MM-DD}/{YYYY-MM-DD | no-return}?adults={a}&children={c}&infants={i}
```

- **[V]** `/it/search/results/milano-italia/lisbona-portogallo/2026-11-14/2026-11-18?adults=2&children=2&infants=0&bags=0.0-0.0&sortBy=price`
  gave "Milano → Lisbona", outbound "sab 14 nov", return "mer 18 nov", 4 passengers and results.
- **[V]** `/en/search/results/milan-italy/lisbon-portugal/2026-12-05/no-return?adults=1&children=1&infants=1`
  gave "Milan → Lisbon", "Sat 5 Dec", one way and 3 passengers.
- **[V] Slugs must match the locale in the path:** `/en/` takes English slugs, `/it/` takes
  Italian slugs. Raw IATA codes (`/MXP/LIS/`) and English slugs under `/it/` do **not** resolve.
  Worse, Kiwi then silently restores the *previous* search from browser storage, so the user would
  see a prefill that looks plausible but is wrong. Recommendation: always `/en/` with English
  `{city}-{country}` slugs, lowercase and hyphenated.
- Kiwi rewrites the URL with a trailing `/` before the query. Airport-level slugs are **[U]**.

### 1.7 lastminute.com: verified on www.lastminute.com

```
https://www.lastminute.com/s/flights/search/v2/results?passengers.adults={a}&passengers.children={c}
  &itinerary.type=ROUND_TRIP
  &itinerary.path[0].departure={FROM}&itinerary.path[0].arrival={TO}&itinerary.path[0].date={YYYYMMDD}
  &itinerary.path[1].departure={TO}&itinerary.path[1].arrival={FROM}&itinerary.path[1].date={YYYYMMDD}
```

- The template was found in links on lastminute's own route page
  (`https://www.lastminute.com/flights/ac_luton--lisbon`), which also carry
  `businessProfile=LMNUK_SEOCOUK&bfSubSource=…`.
- **[V]** `passengers.adults=2&passengers.children=1&passengers.childrenAge[0]=8&itinerary.type=ROUND_TRIP&…MIL…LIS…20261114…20261118`
  gave the title "Milan – Lisbon | lastminute.com", "Milan (MIL) – Lisbon (LIS)", "14 – 18 Nov",
  "3 passengers" and results. Prices were shown in **GBP** on the .com host.
- **[U]** `passengers.childrenAge[0]` is a guess: the page did not complain, but the age was not
  read back. One way is probably `itinerary.type=ONE_WAY` with a single path, also **[U]**.
- **[V]** `https://www.lastminute.it/` returns 301 to `https://www.it.lastminute.com/`. The same
  results URL on lastminute.it redirected to `www.it.lastminute.com` and the tab title became
  "Milan – Lisbon | lastminute.com". The page content could not be read there (that host was not
  approved for the browser tool), so treat the Italian market host as **[U]**. The older
  `/s/flights/search?…&url=search3.do` links on the same site return an empty page on direct
  navigation **[V]**: do not use them.
- Not in the spec's `build_link.py` provider list. It is useful only as a fallback when the
  lastminute MCP is down.

### 1.8 Trenitalia: verified (lands on the results page)

```
https://www.lefrecce.it/Channels.Website.WEB/website/auth/handoff?action=searchTickets&lang=it&referrer=www.trenitalia.com
  &tripType=on&ynFlexibleDates=off&selectedTrainType=tutti
  &departureStation={station_name}&arrivalStation={station_name}
  &departureDate={DD-MM-YYYY}&departureTime={HH}
  &returnDate={DD-MM-YYYY}            # one way: SAME as departureDate (required)
  [&isRoundTrip=true&returnTime={HH}] # round trip only
  &noOfAdults={a}&noOfChildren={ragazzi}
```

- These fields mirror the hidden form that trenitalia.com's own search widget sends to this
  handoff endpoint. It sends them as POST, but the endpoint also accepts GET. Field names and the
  date format come from trenitalia.com's `clientlib-site` JS: `departureDate` is
  `DD-MM-YYYY`, and when there is no return trip it sets `returnDate = departureDate` and drops
  `isRoundTrip`.
- **[V]** One way, Milano Centrale → Roma Termini, 14-11-2026 08:00, 2 adults + 1 child. The page
  redirected to an encrypted `#/handoff?data=…` and then to `#/search-results`, showing
  "VIAGGIO DI ANDATA", "Viaggio da Milano Centrale a Roma Termini" and Frecciarossa 9611 at 08:00.
- **[V]** Round trip, Firenze S. M. Novella → Napoli Centrale, 20-11-2026 09h / 22-11-2026 17h,
  showed outbound results from 09:04. The return leg is chosen in a later step, so the return date
  could not be observed **[U]**.
- **[V] Failure mode:** without `returnDate` the SPA spins forever (console error
  "search-request-builders returnDate invalid").
- Stations are resolved by lefrecce's own lookup (`/Channels.Website.BFF.WEB/website/locations/search?name=…&limit=1`,
  first match), so pass official station names ("Milano Centrale", "Roma Termini", "Firenze S. M.
  Novella", "Napoli Centrale").
- Child discounts per trenitalia.com's own passenger help text **[V]**. National trains: under 4
  free without a seat; ages 4–14 get 50% off Base. Regional trains: under 12 get 50% off.
  `noOfChildren` counts "ragazzi" (under 15).
- The final page URL (`#/search-results?handoff=true…`) is generic. Only the handoff link itself
  can be shared.

### 1.9 Italo: verified (lands on the results page)

```
https://biglietti.italotreno.com/it/booking/ricerca-treni?osc={station_code}&dsc={station_code}
  &jt=single|return&od={DD/MM/YYYY}[&id={DD/MM/YYYY}]
  &adt={adults}&yng={14_29}&chd={3_13}&snr={60_plus}&inf={infants}&pet=0&lang=it&startSearch=true
```

- italotreno.com's own search form (`#main-search-engine`) does a **GET** to this URL with exactly
  these fields **[V]**.
- **[V]** `osc=MC_&dsc=RMT&jt=single&od=14/11/2026&adt=2&chd=1` landed on
  `/it/booking/selezione-treno-andata` with Milano Centrale → Roma Termini, "14-Nov-2026",
  "3 passeggeri" and departures from 05:40.
- **[V]** `osc=SMN&dsc=NAC&jt=return&od=20/11/2026&id=22/11/2026&adt=1` showed the steps
  "1. Andata, 2. Ritorno…" with dates 20-Nov-2026 and 22-Nov-2026.
- Station codes come from `https://www.italotreno.com/api/getStations?includeWhiteLabel=true&lang=it&ntvAjaxControlAction=getStations`
  (internal JSON, about 3.4 MB, 2541 stations; **[U]** whether it stays stable). Codes seen:
  `MC_` Milano Centrale, `MPG` Milano Porta Garibaldi, `RG_` Milano Rogoredo, `RRO` Milano Rho
  Fiera, `MI0` Milano (Tutte), `RMT` Roma Termini, `RTB` Roma Tiburtina, `RM0` Roma (Tutte),
  `SMN` Firenze S.M.Novella, `NAC` Napoli Centrale, `NAF` Napoli Afragola, `NA0` Napoli (Tutte).
  Ship a small static table in `templates.json` instead of fetching at runtime.
- Age bands from the italotreno.com passenger picker **[V]**: Senior "Over 60", Giovani "14-29
  anni", Bambini "3-13 anni". The `inf` band (presumably 0–2) is **[U]**.

### 1.10 Omio: verified (prefilled search form; the user presses "Cerca")

Option A, the route landing page (no IDs needed, recommended):

```
https://www.omio.it/treni/{from_slug}/{to_slug}?departure_date={DD/MM/YYYY}
```

- **[V]** `/treni/firenze/venezia?departure_date=20/11/2026` prefilled "Firenze, Italia" →
  "Venezia, Italia", `departure_date=20/11/2026` and `travel_mode=train`.
- **[V]** An unknown route slug (`/treni/xyzabc/roma`) shows the 404 page "Questa pagina non
  esiste". `build_link.py` cannot detect this offline, so the agent's note must say "se la pagina
  non esiste, cerca da omio.it".

Option B, the home page with position IDs:

```
https://www.omio.it/?departure_fk={position_id}&arrival_fk={position_id}&departure_date={DD/MM/YYYY}[&return_date={DD/MM/YYYY}]&travel_mode=train
```

- **[V]** `departure_fk=388252&arrival_fk=388498&departure_date=14/11/2026&return_date=18/11/2026&travel_mode=train`
  prefilled "Milano, Italia" → "Roma, Italia", "sab 14 nov" / "mer 18 nov".
- IDs seen on the site: Milano 388252, Roma 388498, Firenze 388058, Venezia 388743. Omio does not
  publish an ID lookup (a Travelpayouts help page refers to a "Deep link Creator" file, but that
  page returned 403).
- **[V] Passengers cannot be prefilled:** `passengerages[0]=35&passengerages[1]=8` was ignored and
  the form kept its default one passenger (`passengerages[0]=26:57:`).
- Omio's own search is a **POST** to `/growth/search-trigger/search` **[V]**. Omio has no GET
  results URL, so these links stop at a prefilled form.

### 1.11 Proposed `templates.json` shape (input for the booking-links skill)

Proposal only: the booking-links agent owns the file and its final shape.

```json
{
  "booking":        {"url": "https://www.booking.com/searchresults.it.html", "query": {"ss": "{destination}", "checkin": "{checkin:%Y-%m-%d}", "checkout": "{checkout:%Y-%m-%d}", "group_adults": "{adults}", "group_children": "{children_count}", "age": "{children_ages[]}", "no_rooms": "{rooms}", "selected_currency": "EUR"}},
  "airbnb":         {"url": "https://www.airbnb.it/s/{place_slug}/homes", "query": {"checkin": "{checkin:%Y-%m-%d}", "checkout": "{checkout:%Y-%m-%d}", "adults": "{adults_incl_13_17}", "children": "{count_age_2_12}", "infants": "{count_age_0_1}", "pets": "0"}},
  "google_flights": {"url": "https://www.google.com/travel/flights", "query": {"q": "{english_query}", "hl": "it", "gl": "IT", "curr": "EUR"}},
  "expedia_hotels": {"url": "https://www.expedia.it/Hotel-Search", "query": {"destination": "{destination}", "startDate": "{checkin:%Y-%m-%d}", "endDate": "{checkout:%Y-%m-%d}", "rooms": "{rooms}", "adults": "{adults_per_room,}", "children": "{room_age_pairs,}"}},
  "expedia_flights":{"url": "https://www.expedia.it/Flights-Search", "query": {"trip": "roundtrip|oneway", "leg1": "from:{from_iata},to:{to_iata},departure:{depart:%Y-%m-%d}TANYT", "leg2": "from:{to_iata},to:{from_iata},departure:{return:%Y-%m-%d}TANYT", "passengers": "adults:{adults},children:{children_count}[{ages;}],seniors:0,infantinlap:N", "options": "cabinclass:economy", "mode": "search"}},
  "kiwi":           {"url": "https://www.kiwi.com/en/search/results/{from_slug_en}/{to_slug_en}/{depart:%Y-%m-%d}/{return:%Y-%m-%d|no-return}", "query": {"adults": "{adults}", "children": "{children}", "infants": "{infants}"}},
  "trenitalia":     {"url": "https://www.lefrecce.it/Channels.Website.WEB/website/auth/handoff", "query": {"action": "searchTickets", "lang": "it", "referrer": "www.trenitalia.com", "tripType": "on", "ynFlexibleDates": "off", "selectedTrainType": "tutti", "departureStation": "{from_station}", "arrivalStation": "{to_station}", "departureDate": "{depart:%d-%m-%Y}", "departureTime": "{depart_hour:%H}", "returnDate": "{return_or_depart:%d-%m-%Y}", "noOfAdults": "{adults}", "noOfChildren": "{children_under_15}"}},
  "italo":          {"url": "https://biglietti.italotreno.com/it/booking/ricerca-treni", "query": {"osc": "{from_code}", "dsc": "{to_code}", "jt": "single|return", "od": "{depart:%d/%m/%Y}", "id": "{return:%d/%m/%Y}", "adt": "{adults}", "yng": "{count_14_29}", "chd": "{count_3_13}", "snr": "{count_60_plus}", "inf": "{count_0_2}", "pet": "0", "lang": "it", "startSearch": "true"}},
  "omio":           {"url": "https://www.omio.it/treni/{from_slug_it}/{to_slug_it}", "query": {"departure_date": "{depart:%d/%m/%Y}"}, "note_it": "Su Omio scegli il numero di passeggeri prima di cercare."}
}
```

Rules for `build_link.py`:

- Validate inputs: ISO dates, IATA `^[A-Z]{3}$`, child ages 0–17.
- Never put personal data in the URL. Only places, dates, counts and ages, as the spec requires.
- Build with `urllib.parse.urlencode(..., quote_via=quote)` and repeat keys for lists (Booking
  `age`).
- Tests should assert host, path and decoded query, never fetch: every provider blocks `curl`
  (Booking 202 WAF, Expedia 429, Omio 403, lastminute 403).

### 1.12 Canonical host allowlist (backend domain check for MCP links and build_link output)

Matching rule:

- Parse with `urllib.parse.urlsplit`.
- Require `scheme == "https"`, no userinfo, and port absent or 443.
- Take `hostname.lower()` (IDNA) and match it **exactly** against `hosts`, or check
  `host == suffix or host.endswith("." + suffix)` for entries in `suffixes`.
- Never use substring checks: `booking.com.evil.example` must fail.
- For Google, also require the path to start with `/travel/flights`.

As built (`backend/app/links.py` `check_link`, backend-interfaces decision 13a) the check is
**stricter** than this rule, because browsers do not always open a URL where `urlsplit` says:

- A URL longer than 2000 characters (TripTracker's URL cap) is rejected.
- Spaces, ASCII control characters, DEL and backslashes anywhere in the URL are rejected before
  the host is read (browsers read `\` as `/`, so `https://evil.example\.kiwi.com/` would open
  evil.example). A real MCP link with a raw space is therefore shown as text.
- The host must be a plain lower-case ASCII DNS name. Non-ASCII (IDN) hosts and any `xn--`
  label are rejected even under an allowed suffix, instead of being IDNA-encoded and compared:
  every allowed host is plain ASCII, so a lookalike never matches. IP addresses, a trailing dot
  and empty labels are rejected too.
- Under Google's `/travel/flights` the path must be the prefix or below it at a segment
  boundary, with no `.` or `..` segment, plain or percent-encoded (`/travel/flights/../../url`
  would reach Google's open redirect).

| Provider key | `hosts` (exact) | `suffixes` | Evidence |
|---|---|---|---|
| `booking` | `www.booking.com`, `booking.com` | – | **[V]** booking.com → 301 www.booking.com |
| `airbnb` | `www.airbnb.it`, `airbnb.it`, `www.airbnb.com`, `airbnb.com` | – | **[V]** airbnb.it → 301 www.airbnb.it |
| `google_flights` | `www.google.com`, `www.google.it` (path `/travel/flights*`) | – | **[V]** |
| `expedia` | `www.expedia.com`, `expedia.com`, `www.expedia.it`, `expedia.it`, plus `www.expedia.{ae, at, be, ca, ch, co.id, co.in, co.jp, co.kr, co.nz, co.th, co.uk, com.ar, com.au, com.br, com.hk, com.my, com.ph, com.sg, com.tw, com.vn, de, dk, es, fi, fr, ie, mx, nl, no, sa, se}` | – | **[V]** the 34 `www.expedia.*` hosts linked from expedia.it (country switcher/hreflang); expedia.com → 301 www.expedia.com |
| `kiwi` | `www.kiwi.com`, `kiwi.com` | `kiwi.com` (any subdomain; MCP booking links are "shortened, dedicated" and their host is unknown) | **[V]** kiwi.com → 302 www.kiwi.com; short-link host **[U]** |
| `lastminute` | `www.lastminute.it`, `lastminute.it`, `www.lastminute.de`, `www.lastminute.ie`, `www.lastminute.be`, `fr.lastminute.be` | `lastminute.com` (covers `www.lastminute.com`, `www.it.lastminute.com`, `secure.lastminute.com`, `it-ch.lastminute.com`, …) | **[V]** hosts linked from www.lastminute.com; lastminute.it → 301 www.it.lastminute.com |
| `trenitalia` | `www.trenitalia.com`, `trenitalia.com`, `www.lefrecce.it`, `lefrecce.it` | – | **[V]** |
| `italo` | `www.italotreno.com`, `italotreno.com`, `biglietti.italotreno.com`, `www.italotreno.it` | – | **[V]** italotreno.it → 301 www.italotreno.com |
| `omio` | `www.omio.it`, `omio.it`, `www.omio.com`, `omio.com` | – | **[V]** www.omio.it/.com reachable in a browser |

The MCP link check needs only `expedia`, `kiwi` and `lastminute`. Section 4 lists the
link-producing servers. On day 1, log the actual host of every MCP link seen in the test session
and narrow the `kiwi` and `lastminute` suffixes if possible.

---

## 2. FX rates (`backend/app/fx.py`)

Both sources quote **units of foreign currency per 1 EUR**, so `eur_cents = amount_cents / rate`
as the spec says. **[V]** for both (cross-check in 2.2).

### 2.1 Banca d'Italia daily reference rates (primary)

Official doc: "Exchange Rates – REST API (Version 1.0)", the PDF
`https://tassidicambio.bancaditalia.it/terzevalute-wf-ui-web/assets/files/Operating_Instructions.pdf`
**[D]**.

Endpoint **[V]**:

```
GET https://tassidicambio.bancaditalia.it/terzevalute-wf-web/rest/v1.0/dailyRates
    ?referenceDate=YYYY-MM-DD
    &baseCurrencyIsoCode=USD&baseCurrencyIsoCode=GBP&baseCurrencyIsoCode=CHF   (repeatable; omit = all ~171)
    &currencyIsoCode=EUR                                                        (quote basis: EUR | USD | ITL)
    &lang=en                                                                    (it | en; only changes labels)
Accept: application/json
```

- **Parameter names are counter-intuitive:** `baseCurrencyIsoCode` is the currency you want, and
  `currencyIsoCode` is the reference ("per 1 X"). **[V]** Swapping them
  (`baseCurrencyIsoCode=EUR&currencyIsoCode=USD`) returns EUR per 1 USD (0.8924).
- **`Accept: application/json` is mandatory.** Without it the service returns CSV with a
  `# DISCLAIMER` footer **[V]**. Other media types are `application/pdf`, `text/csv` and
  `application/vnd.ms-excel` **[D]**.
- No auth, no key **[V]**. Responses carry `Access-Control-Allow-Origin: *`,
  `Cache-Control: no-cache, no-store`, and set a `TS01…` load-balancer cookie that can be ignored
  **[V]**.

Response shape, fixture `bdi_daily_2026-10-09.json` **[V]**:

```json
{
  "resultsInfo": {"totalRecords": 3, "timezoneReference": "Dates refer to the Central European Time Zone", "notice": "DISCLAIMER: …"},
  "rates": [
    {"country": "UNITED STATES", "currency": "U.S. Dollar", "isoCode": "USD", "uicCode": "001",
     "avgRate": "1.1206", "exchangeConvention": "Foreign currency amount for 1 Euro.",
     "exchangeConventionCode": "C", "referenceDate": "2026-10-09"}
  ]
}
```

- `avgRate` is a **string**. Parse it with `Decimal`. It can be `"N.A."`: on 2026-10-09 BYN, IRR,
  KPW and RUB had `"N.A."` **[V]**. Treat that as missing.
- `exchangeConventionCode`:
  - `"C"` means "Foreign currency amount for 1 <reference>". All 171 currencies against EUR on
    2026-10-09 were `C` **[V]**.
  - `"I"` means the inverse, "<reference> amount per 1 unit of foreign currency". It was seen with
    `currencyIsoCode=ITL` (all 183 rows on 1998-01-05) and for 11 currencies against USD (e.g. GBP
    1.3220 USD per GBP) **[V]**.
  - **Assert `C` or invert on `I`**, and key on the code, not on the localized text (with
    `lang=it` the text is "Quantita' di valuta estera per 1 Dollaro.").
- Results come sorted by country name, not in request order **[V]**.

Behaviour on non-publication days **[V]**:

| Date queried | Result |
|---|---|
| Weekend (2026-10-10 Sat, 2026-10-11 Sun) | HTTP 200, `{"resultsInfo":{"totalRecords":0,"notice":…},"rates":[]}` (fixture `bdi_daily_2026-10-10.json`) |
| TARGET holidays 2025-12-25, 2025-12-26, 2026-01-01, 2026-04-03 (Good Friday), 2026-04-06 (Easter Monday), 2026-05-01 | HTTP 200, empty `rates` |
| Italian-only holiday 2026-06-02 (Festa della Repubblica) | rates **are** published |
| Future date (2026-10-20) | HTTP 200, empty `rates` |
| Today 2026-10-12, 01:57 CEST | empty; `latestRates` reports 2026-10-09. Same-day publication time is **[U]**: the ECB concertation is in the early afternoon CET. |

Errors **[V]**:

- HTTP 400 with a `text/plain` body such as `WARNING! Parameter referenceDate required`,
  `WARNING! Invalid value for parameter referenceDate. Parameter referenceDate format is: yyyy-MM-dd`,
  `WARNING! Parameter currencyIsoCode can take the value of: EUR, USD or ITL`,
  `WARNING! Invalid date range`.
- **The doc says ISO codes are case-insensitive, but `baseCurrencyIsoCode=usd` → HTTP 400
  "Incorrect format".** Always send upper case.
- Unknown well-formed codes (`ZZZ`) are dropped silently.
- Documented codes are 200/400/404/408/500/503 **[D]**.

Other endpoints:

- `GET /dailyTimeSeries?startDate=&endDate=&baseCurrencyIsoCode=USD&currencyIsoCode=EUR&lang=en`:
  one currency (not repeatable) over a range. Returns
  `resultsInfo{currency,isoCode,uicCode,exchangeConventionCode}` and
  `rates[{referenceDate, avgRate, exchangeConvention}]` with business days only **[V]**. Fixture
  `bdi_timeseries_USD_2026-10-03_2026-10-12.json` holds 5 rows, 10-05 to 10-09. It is the cheapest
  way to get "the latest rate on or before D" in one call.
- `GET /latestRates?lang=en`: `latestRates[{…, eurRate, usdRate, usdExchangeConvention, referenceDate}]`
  for all currencies on the latest complete day **[V]**.
- `GET /monthlyAverageRates?month=9&year=2026&…`, `/annualAverageRates`, `/currencies` **[V]**.
  `/monthlyTimeSeries` and `/annualTimeSeries` **[D]**.

### 2.2 EU InforEuro monthly accounting rates (fallback)

What it is: the Commission's monthly accounting rate, "the market rates for the second to last day
of the previous month as quoted by the European Central Bank" **[D]**
(https://commission.europa.eu/funding-tenders/procedures-guidelines-tenders/information-contractors-and-beneficiaries/exchange-rate-inforeuro_en).
One rate per currency for the whole calendar month.

**Cross-check [V]:** InforEuro October 2026 gives USD 1.1355. Banca d'Italia's 2026-09-29 (the
penultimate business day of September) also gives USD 1.1355. This confirms both the convention
(USD per 1 EUR) and the publication rule.

Endpoint **[V]**. It is undocumented: no official API documentation was found. The path was taken
from the official InforEuro web app's JS (`https://ec.europa.eu/budg/inforeuro/js/minified-script.js`)
and the `/public/` variant was then confirmed by GET:

```
GET https://ec.europa.eu/budg/inforeuro/api/public/monthly-rates?year=2026&month=10   (lang=EN default; FR etc. localize names)
Accept: application/json   (optional; JSON is returned either way)
```

Response, fixture `inforeuro_2026-10.json`: a bare JSON **array** with 152 elements and one row per
currency (no duplicate `isoA3Code` in 2026-10) **[V]**:

```json
[
  {"country": "Belgium", "currency": "Euro", "isoA3Code": "EUR", "isoA2Code": "BE", "value": 1, "comment": "The euro is the currency of …"},
  {"country": "United States", "currency": "United States dollar", "isoA3Code": "USD", "isoA2Code": "US", "value": 1.1355, "comment": "US dollar: Also in use for …"},
  {"country": "United Kingdom", "currency": "Pound sterling", "isoA3Code": "GBP", "isoA2Code": "GB", "value": 0.85718, "comment": "…"},
  {"country": "Switzerland", "currency": "Swiss franc", "isoA3Code": "CHF", "isoA2Code": "CH", "value": 0.9461, "comment": "…"}
]
```

- `value` is a JSON **number**, so parse with `json.loads(text, parse_float=Decimal)` to keep the
  exact decimal. `EUR` has the int `1`. No currency filter exists: fetch the month and pick.
- **Month not yet published** (2026-11 as of 2026-10-12), or an invalid month: **HTTP 500**,
  `{"code":5,"exception":"Exception","message":"No rates published for period 2026/11"}`
  (fixture `inforeuro_2026-11_error.json`). Bad input such as `year=abc` returns HTTP 500 with
  `{"code":1,…,"message":"Wrong input"}` **[V]**. Treat `code` 5 as "no data" and do not retry it.
  Retry other 5xx responses.
- `month` omitted returns some month (seen: the current one). Do not rely on it.
- Per-currency history **[V]**:
  `GET https://ec.europa.eu/budg/inforeuro/api/public/currencies/USD` returns
  `[{"currencyIso":"USD","refCurrencyIso":"EUR","amount":1.1355,"dateStart":"01/10/2026","dateEnd":"31/10/2026"}, …]`,
  newest first, with dates as `DD/MM/YYYY`. Lower-case ISO codes are accepted here.
- Do **not** use the app-internal `https://ec.europa.eu/budg/inforeuro/api/monthly-rates?lang=EN&year=&month=`.
  It has an XSSI prefix `)]}',`, a `{"rates":[…]}` wrapper, header rows with `value: null` and
  numeric footnote markers in `comment` **[V]**.

### 2.3 Recommended `to_eur_cents()` algorithm

1. `currency == "EUR"` → return `amount_cents` unchanged.
2. Look in `fx_rates` for the newest row with `currency = X` and `date <= on_date` and
   `date >= on_date - 7 days`, preferring `source = "bdi_daily"`. On a hit, use it.
3. Otherwise call BdI `dailyTimeSeries` for `[on_date - 7 days, on_date]`. Take the last row whose
   `avgRate` is numeric and whose code is `C`, and cache it **under its actual `referenceDate`**
   (one rate per currency per day, as the spec requires). This covers weekends, TARGET holidays and
   "today before publication".
4. If BdI fails (network/5xx/empty after 7 days), call InforEuro `monthly-rates` for `on_date`'s
   year and month. If that month returns `code 5`, try the previous month. Cache it as
   `source = "inforeuro_monthly"`, dated the first day of the month.
5. If both fail: no conversion. Keep the original amount and currency in `notes` and add a warning
   (spec).
6. Use `Decimal` throughout and `quantize(Decimal(1), ROUND_HALF_UP)`. Python's `round()` uses
   banker's rounding, but on these vectors it gives the same results.

**As built, step 2 is narrower** (`backend/app/fx.py`, backend-interfaces decision 15a). Step 2
as written would let a rate cached on Monday morning answer for Tuesday, when Banca d'Italia
already publishes Tuesday's rate, and would let a cached monthly InforEuro row count as a daily
hit and stop Banca d'Italia from being asked for the rest of the week. The code differs in
these ways:

- `on_date` is first clamped to today: no source publishes future rates.
- Only `bdi_daily` rows count in step 2. The newest one in the 7-day window is a hit only when
  no publication day falls after its date, up to `on_date`. A publication day is Monday to
  Friday except the TARGET holidays (1 January, Good Friday, Easter Monday, 1 May, 25 and 26
  December); Italian-only holidays such as 2 June have rates. So Friday's rate still answers
  for Saturday and Sunday.
- An older cached daily row is kept as the fallback of step 3: when Banca d'Italia fails or has
  no usable row, that row is used before InforEuro (it is still a Banca d'Italia rate, newer
  than any monthly one).
- Step 4 looks for the cached `inforeuro_monthly` row of the month first, then calls InforEuro.
  The same applies to the previous month after `code 5`.
- Offline mode (`app.cli replay`, the local demo) makes no request: any cached daily row of the
  window whatever its age, then the cached InforEuro row of the month, then of the month
  before.
- Every request has a 10 s timeout, and each source as a whole has a 20 s deadline
  (`SOURCE_DEADLINE_SECONDS`), at most 2 retries included. So a submission waits about 40 s at
  worst when both hosts hang. The consumer's `prefetch` never raises (except on
  cancellation): a missing rate leaves the amount unconverted with the warning of step 5.

Which date to pass as `on_date`: the spec does not fix it. The price's `retrieved_at` date in
Europe/Rome is the natural choice, because travel dates are in the future and have no rate yet.

Test vectors from the fixtures **[V]** (amount in source cents → EUR cents, half-up):

| Source | Currency | Rate | 10000 → | 12345 → |
|---|---|---|---|---|
| BdI 2026-10-09 | USD | 1.1206 | 8924 | 11016 |
| BdI 2026-10-09 | GBP | 0.84763 | 11798 | 14564 |
| BdI 2026-10-09 | CHF | 0.9313 | 10738 | 13256 |
| InforEuro 2026-10 | USD | 1.1355 | 8807 | 10872 |
| InforEuro 2026-10 | GBP | 0.85718 | 11666 | 14402 |
| InforEuro 2026-10 | CHF | 0.9461 | 10570 | 13048 |

### 2.4 Fixtures in `backend/tests/fixtures/fx/`

All were fetched 2026-10-11T23:57:37Z, then pretty-printed (`indent=2`, UTF-8). They are
JSON-equal to the raw bodies and every numeric literal is unchanged.

| File | Request |
|---|---|
| `bdi_daily_2026-10-09.json` | `GET …/rest/v1.0/dailyRates?referenceDate=2026-10-09&baseCurrencyIsoCode=USD&baseCurrencyIsoCode=GBP&baseCurrencyIsoCode=CHF&currencyIsoCode=EUR&lang=en` with `Accept: application/json` |
| `bdi_daily_2026-10-10.json` | same for `referenceDate=2026-10-10` (Saturday): empty `rates` |
| `bdi_timeseries_USD_2026-10-03_2026-10-12.json` | `GET …/dailyTimeSeries?startDate=2026-10-03&endDate=2026-10-12&baseCurrencyIsoCode=USD&currencyIsoCode=EUR&lang=en` |
| `inforeuro_2026-10.json` | `GET https://ec.europa.eu/budg/inforeuro/api/public/monthly-rates?year=2026&month=10` |
| `inforeuro_2026-11_error.json` | same for `month=11`: body of the HTTP **500** response |

---

## 3. Photon geocoding and Open-Meteo (skills scripts, `web_fetch`)

Hosts for `environment.yaml` `allowed_hosts`:

| Host | Use | Required |
|---|---|---|
| `photon.komoot.io` | geocoding (`/api`, `/reverse`) | yes (spec) |
| `api.open-meteo.com` | forecast (`/v1/forecast`) | yes (spec) |
| `archive-api.open-meteo.com` | historical weather for trips more than 16 days out | optional |
| `geocoding-api.open-meteo.com` | city → lat/lon + IANA timezone, understands Italian names | optional |

The FX hosts (`tassidicambio.bancaditalia.it`, `ec.europa.eu`) are called by the backend only.
They do not belong in the agents' environment.

### 3.1 Photon (https://photon.komoot.io)

API docs: https://github.com/komoot/photon/blob/master/docs/api-v1.md **[D]**. Server status
**[V]**: `GET /status` returned `{"status":"Ok","import_date":"2026-10-03T23:01:00Z","version":"1.3.0",…}`.

- `GET https://photon.komoot.io/api/?q={text}&limit={n}&lang=en[&lat=&lon=&zoom=&location_bias_scale=][&bbox=minLon,minLat,maxLon,maxLat][&layer=city&layer=…][&osm_tag=key:value][&countrycode=IT]`
- `GET https://photon.komoot.io/reverse?lat={lat}&lon={lon}&lang=en&limit=1[&radius=km]`
- Also `/structured?city=&street=&housenumber=&postcode=&countrycode=…` **[D]**.
- Response: GeoJSON `FeatureCollection`. Each feature has `geometry.coordinates = [lon, lat]`
  (**lon first**) and `properties{name, type (house|street|locality|district|city|county|state|country|other), osm_key, osm_value, osm_type, osm_id, street, housenumber, postcode, city, district, county, state, country, countrycode, extent?, extra?}`
  **[V]**.
- **`lang=it` is rejected on the public instance:** HTTP 400
  `{"lang":[{"message":"Language is not supported. Supported are: default, de, en, fr",…}]}`
  **[V]**. Use `lang=en` (or `default` for local names). If `lang` is omitted, `Accept-Language`
  decides and unsupported languages fall back to local names without error **[V]**.
- **Italian exonyms match poorly** **[V]**:
  - `q=Lisbona&lang=en` returned a bus stop in Padua first.
  - `q=Lisbona&layer=city` returned Lisbon first.
  - `q=Monaco di Baviera` returned only a street in Carate Brianza.

  So scripts should query English or local names, and add `layer=city` for places or a
  `lat`/`lon` bias for POIs (verified: `q=Rossio Lisbon&lat=38.7223&lon=-9.1393` → Rossio station;
  `q=Lisbon Airport&osm_tag=aeroway:aerodrome` → Lisbon Airport).
- The public instance caps results at 50 (`limit=100` returned 50) **[V]**.
- Usage policy: "You are welcome to use the API for your project as long as the number of requests
  stay in a reasonable limit. Extensive usage will be throttled or completely banned." **[D]**
  (komoot/photon README). Send a descriptive `User-Agent`.

### 3.2 Open-Meteo forecast (https://api.open-meteo.com)

Docs: https://open-meteo.com/en/docs **[D]**. Terms: https://open-meteo.com/en/terms **[D]**. Free
use is non-commercial only, with limits of 600 calls/min, 5,000/hour, 10,000/day and
300,000/month, under the CC BY 4.0 licence. No API key.

```
GET https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}
    &daily=weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max,precipitation_sum,sunrise,sunset
    &timezone=auto|{IANA}&start_date={YYYY-MM-DD}&end_date={YYYY-MM-DD}     (or forecast_days=0..16)
```

- **[V]** The response has `latitude`, `longitude` (snapped to the grid, e.g. 38.746044/-9.175565
  for 38.7077/-9.1366), `utc_offset_seconds`, `timezone` ("Europe/Lisbon" with `timezone=auto`),
  `timezone_abbreviation`, `elevation`, `daily_units{…}` and
  `daily{time:[YYYY-MM-DD…], <var>:[…]}`. Arrays are parallel to `daily.time`.
- **[V]** The horizon is today plus 15 days. `forecast_days=17` → HTTP 400
  `{"error":true,"reason":"Forecast days is invalid. Allowed range 0 to 16. Given 16."}`.
  `start_date=2026-11-14` → HTTP 400
  `{"error":true,"reason":"Parameter 'start_date' is out of allowed range from 2026-07-10 to 2026-10-26"}`.
  Requests must be clamped, or skipped when the trip is beyond the horizon.
- **[V]** `sunrise`/`sunset` are **local wall-clock without offset** (`"2026-10-14T07:44"`).
  **`utc_offset_seconds` is one value for the whole response and does not follow DST across the
  range.** The archive call for Lisbon in November 2025 still reported `GMT+1`/3600, although
  Lisbon is on UTC+0 then. To produce the plan's offset-aware instants, localize with
  `zoneinfo.ZoneInfo(timezone)` per date and never apply `utc_offset_seconds`.
- `weather_code` is the WMO code. Error responses are `{"error": true, "reason": "…"}` with
  HTTP 400 **[V]**.
- Beyond 16 days, use
  `https://archive-api.open-meteo.com/v1/archive?latitude=&longitude=&start_date=&end_date=&daily=…&timezone=`
  with the same dates one year earlier, as a "typical weather" hint (label it as such in Italian
  text) **[V]**.
- Optional geocoder:
  `https://geocoding-api.open-meteo.com/v1/search?name=Lisbona&count=1&language=it&format=json`
  returned Lisbona/PT with `timezone: "Europe/Lisbon"`. It handles Italian names, unlike Photon **[V]**.

---

## 4. Travel MCP servers (public information only; none were contacted)

| | Expedia | Kiwi.com | lastminute.com |
|---|---|---|---|
| URL | `https://www.expedia.com/mcp` | `https://mcp.kiwi.com` (directory lists `https://mcp.kiwi.com/`) | `https://mcp.lastminute.com/mcp` |
| Transport | remote HTTP **[U]** (not stated) | streamable HTTP: README `claude mcp add --transport http kiwi-com-flight-search https://mcp.kiwi.com` **[D]** | remote HTTP; docs show `npx mcp-remote` for Claude Desktop **[D]** |
| Auth | Claude directory: "Not required" **[D]**. The Expedia help page says "No Expedia account is needed — Claude will confirm the connection and redirect you back automatically", which suggests a connect/redirect handshake (possibly OAuth without a login) that may not work in a headless session **[U]** | "Not required" (Claude directory, README, crox.io) **[D]** | "Not required" (Claude directory) **[D]** |
| Tools (exact names) | `search_hotels`, `search_flights`, `get_hotel_pdp_offers` (Claude directory and MCP registry) **[D]** | `search-flight` (hyphen), `feedback-to-devs` **[D]** | `search_flights` **[D]**. The docs also describe hotel-only and flight+hotel package search, but only `search_flights` is listed. |
| Enable (spec: search only, `always_allow`) | `search_flights`, `search_hotels`, `get_hotel_pdp_offers` (spec: "ricerca voli, ricerca hotel, offerte hotel") | `search-flight` only. **Keep `feedback-to-devs` disabled**: it writes free text (≤3,000 chars) to Kiwi's developers and is annotated `idempotentHint: false` **[U]** (agentman.ai). | `search_flights` (+ any hotel/package tool if `tools/list` shows one) |
| Inputs (public description) | Flights: origin and destination as city name or airport code, departure date in natural format, optional return date, travellers (adults, children ages 2–17, infants), cabin, airline, stops, price range, sort. Hotels: destination, check-in/out, guests (adults + children's ages), price range, stars, guest rating, amenities, property type, sort, deals only. **[D]** expedia.com/playground/mcp/doc | round trip or one way, city or airport, dates, flexibility up to ±3 days, adults/children/infants, cabin class **[D]** (README). Dates `dd/mm/yyyy`, `departureDateFlexDays`/`returnDateFlexDays`, `allow_self_transfer` **[U]** (agentman.ai, third party) | IATA codes or city names, dates, adults/children with ages, time windows HH:MM, max price in cents, airports, max stops, airlines include/exclude, max duration. Hotels: stars, type IDs, facility IDs. **[D]** technology.lastminute.com/mcp |
| Output / links | "a direct link to complete the booking on Expedia's website" **[D]** | Output `{query, currency, passengers, resultsCount, itineraries, searchTimeMs}` **[U]** (agentman.ai). Each result has a "shortened, dedicated booking link" (alpic.ai blog) whose host is unknown **[U]** | "Booking links (deeplinks to lastminute.com)", "Final booking occurs on lastminute.com website" **[D]** |
| Market limits | "currently available for users in the United States. Availability in other countries is coming soon." **[D]**. This is a real risk for an Italian user and for EUR prices. | – | Languages EN, IT, ES, FR, DE, NL, PL, SE, DK, NO, FI; currencies EUR and ISO 4217 **[D]** |
| Docs | https://www.expedia.com/playground/mcp/doc/ | https://www.kiwi.com/en/pages/mcp/ , https://github.com/alpic-ai/kiwi-mcp-server-public | https://mcp.lastminute.com/docs → 302 https://technology.lastminute.com/mcp/ ; https://technology.lastminute.com/openai-doc/ |

All three are listed as "Anthropic verified" in the Claude connector directory
(claude.com/connectors/{expedia, kiwi-com, lastminute-com}) **[D]**. Whether they accept
connections from a Managed Agents session is the spec's main day-1 risk. It cannot be checked
offline.

---

## 5. Day-1 / release checklist (what is still unverified)

1. **MCP (spec risk #1):** run `tools/list` on all three servers from a development session.
   Record the exact tool names and input schemas, check whether any auth or redirect handshake
   blocks Expedia, and check Expedia's US-only restriction. Log the host of every booking link
   returned (Kiwi's short-link host, Expedia's POS domain) and finalize section 1.12's allowlist.
2. lastminute: confirm the results URL on `www.it.lastminute.com` (EUR, Italian), the one-way
   `itinerary.type` value and the child-age parameter name.
3. Airbnb: confirm the 2–12 / under-2 age bands in the guest picker.
4. Google Flights: find the phrasing for infants, if they are needed.
5. Italo: confirm the `inf` age band. Decide whether to ship a static station-code table, which is
   recommended.
6. Trenitalia: confirm the return-leg date on the second step of a round trip.
7. Omio: route slugs exist only for known routes. Decide on the home page with position IDs, or
   the route page with an Italian note on how to recover.
8. Banca d'Italia: the same-day publication time (affects "today" lookups; the fallback already
   covers it).

## 6. Sources

- Spec: `docs/spec/implementation-doc.it.md` (booking-links table p.9, FX p.14, environment p.7, MCP p.6–7, security p.24).
- Banca d'Italia REST API doc (PDF): https://tassidicambio.bancaditalia.it/terzevalute-wf-ui-web/assets/files/Operating_Instructions.pdf
- Banca d'Italia base URL: https://tassidicambio.bancaditalia.it/terzevalute-wf-web/rest/v1.0
- InforEuro description: https://commission.europa.eu/funding-tenders/procedures-guidelines-tenders/information-contractors-and-beneficiaries/exchange-rate-inforeuro_en
- InforEuro app and JS: https://ec.europa.eu/budg/inforeuro/ , https://ec.europa.eu/budg/inforeuro/js/minified-script.js
- InforEuro public API (undocumented, verified): https://ec.europa.eu/budg/inforeuro/api/public/monthly-rates , https://ec.europa.eu/budg/inforeuro/api/public/currencies/{ISO}
- Photon API doc: https://github.com/komoot/photon/blob/master/docs/api-v1.md ; README (usage policy): https://github.com/komoot/photon
- Open-Meteo docs: https://open-meteo.com/en/docs ; terms: https://open-meteo.com/en/terms
- Expedia MCP doc: https://www.expedia.com/playground/mcp/doc/ ; directory: https://claude.com/connectors/expedia
- Kiwi MCP: https://www.kiwi.com/en/pages/mcp/ ; https://github.com/alpic-ai/kiwi-mcp-server-public ; https://claude.com/connectors/kiwi-com ; third party: https://agentman.ai/agentskills/connections/mcp-server/kiwi-com , https://crox.io/servers/kiwi-com/ , https://alpic.ai/blog/behind-the-kiwi-com-mcp-server-deploying-an-agentic-flight-booking-service
- lastminute MCP: https://technology.lastminute.com/mcp/ ; https://technology.lastminute.com/openai-doc/ ; https://claude.com/connectors/lastminute-com
- Airbnb help (children/infants): https://www.airbnb.com/help/article/433
- Omio affiliate deep links (403 on fetch, cited from search snippet only): https://support.travelpayouts.com/hc/en-us/articles/360006719812-Omio-links
- Booking-site evidence: the exact URLs in section 1, opened 2026-10-12 in a browser (GET only).
