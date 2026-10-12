# Bookings: fields, dates, links, prices

Read this when you compose `bookings` and `alternatives`. The core SKILL.md has the rules that
never break.

One `PlanBooking` for everything the user must book: the journey, the lodging, tickets that
must be bought ahead, guided tours, restaurant tables, trains and transfers that are booked in
advance, insurance. Link it to its stop with `stop_ref` (the stop's `ref`, or null).

| Booking field | TripTracker | Rule |
|---|---|---|
| `title` | `title` | Italian, 1-120: "Volo Milano Malpensa → Lisbona", "Ingressi al Castelo, ore 10:30" |
| `kind` | `kind` | `transport` (flights, trains, ferries, transfers, car hire), `lodging`, `ticket` (entry to a sight or museum), `activity` (tour, experience), `restaurant`, `wellness`, `parking`, `other` (insurance and the rest) |
| `vendor` | `vendor` | who sells it, ≤ 200, as the source writes it |
| `book_by` | `dueAt` | deadline to book, instant with offset, strictly before `scheduled_for`, not in the past; or null |
| `book_by_reason` | a line of `notes` | why this deadline, Italian, ≤ 300, one line: "Cancellazione gratuita fino al 6 maggio" |
| `scheduled_for` | `scheduledFor` | when it happens, instant with offset in the trip's zone; or null (insurance) |
| `link` | `url` | booking link, ≤ 2000 (see "Links") |
| `phone` | `phone` | the vendor's booking number with country code, ≤ 40 |
| `price` | `costCents` + `notes` lines | see "Prices" |
| `stop_ref` | `stopId` | a stop `ref` that exists in `days`, or null |
| `notes` | `notes` | Italian, ≤ 4000; keep them short (see below) |

The backend appends provenance lines to each booking's notes in TripTracker (price verified or
estimated, the price's source URL, `book_by_reason`, the original amount and exchange rate of a
converted price, a link to verify). The total is capped at 4000 characters and your notes are
shortened first, so keep booking notes to a few lines.

### Dates

- `scheduled_for`: the start of the booked thing, in the trip's zone: departure time of the
  outbound flight, check-in time (15:00 if the source gives none), the ticket's slot, the
  table's time. A round trip booked together uses the outbound departure; say the return in
  `notes`.
- `book_by`: take it from the sources: free cancellation until, fare valid until, tickets that
  sell out, a booking window that opens. Say why in `book_by_reason`. Pick a sensible local
  time on that date (e.g. 20:00), at least tomorrow (today's date is in the request).
- No deadline in the sources: `book_by` null, no `book_by_reason`. The backend sets the
  deadline to `scheduled_for` minus TripTracker's default lead for the kind, never earlier
  than tomorrow:

  | kind | restaurant | wellness | ticket | parking | transport | lodging | activity | other |
  |---|---|---|---|---|---|---|---|---|
  | days before `scheduled_for` | 2 | 3 | 3 | 1 | 1 | 7 | 2 | 2 |

  If even tomorrow is not before `scheduled_for`, the booking gets "Da prenotare subito"
  and a warning instead of a deadline. Never work around this by copying `scheduled_for`.
- `scheduled_for` null is allowed only when nothing happens at a time (insurance); then
  `book_by` should be set.

### Links

- `link` is a URL from a result file, copied character for character: a link an MCP returned
  (Expedia, Kiwi.com, lastminute.com) or a URL printed by the booking-links skill's
  `build_link.py`. Never write, edit, shorten, complete or "clean" a URL yourself.
- Only these sites count as booking links: Booking.com, Airbnb, Google Flights, Expedia,
  Kiwi.com, lastminute.com, Trenitalia (lefrecce.it), Italo, Omio. A link to any other site
  (an official ticket page, a restaurant's site, a tour operator) is not a booking link: put it
  in the related stop's `url` and leave the booking's `link` null. The plan's checks fail on a
  booking link outside that list, and TripTracker would show it only as text to verify.
- No link: null.

### Prices

- Copy each `price` object from the result file unchanged: `amount_cents`, `currency`,
  `status`, `source_url`, `retrieved_at`. Never upgrade `estimated` to `verified`, never
  convert or round an amount, never invent a price. No sourced price: `price` null.
- `amount_cents` is an integer: the total for the whole party times 100 (12,50 € is `1250`;
  3000 JPY is `300000`). `currency` is the ISO code in upper case.
- Leave non-EUR prices in their currency: the backend converts them to euro for TripTracker
  (Banca d'Italia rate of the `retrieved_at` date) and keeps the original amount in the notes.
- `retrieved_at` keeps the offset the subagent wrote (UTC is fine); rule 2 about the trip's
  zone concerns `book_by` and `scheduled_for`.
