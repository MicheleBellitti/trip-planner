---
name: trip-tracker-schema
description: How the coordinator composes the plan it submits with submit_plan so the backend accepts it and TripTracker imports it. This core carries the three rules that never break (book_by strictly before scheduled_for, instants with a UTC offset in the trip's time zone, TripTracker's caps), the links and prices rules and the pre-submit checklist; the references hold the field tables, the offsets and the error fixes, and example.json is a complete valid plan.
---

# Composing the plan for submit_plan (core)

You deliver the plan by calling `submit_plan` once, with the complete plan as its input. The
backend validates it, translates it into a TripTracker trip and validates that again; then the
user imports it with one click. `<skill_dir>` is the directory that holds this SKILL.md.

| When | Read |
|---|---|
| About to compose the plan | `<skill_dir>/example.json`: the shape of a complete valid plan (6 days, every stop kind, bookings of several kinds with both dates, EUR and GBP prices, alternatives, warnings, summary). Shape only: its places, prices, times and links are illustrative, never copy them |
| Composing `days`, `stops`, `alternatives`, `warnings`, `summary` and you need a field's rule | `<skill_dir>/references/plan-fields.md` |
| Composing `bookings`: fields, `book_by` derivation, links, prices | `<skill_dir>/references/bookings.md` |
| Unsure of the UTC offset on a date, or a flight crosses time zones | `<skill_dir>/references/offsets.md` |
| `submit_plan` rejected the plan | `<skill_dir>/references/submit-errors.md` |

Read each file once, just before you need it. A rejection is fixed from its own lines; read
the error reference only if they do not explain it.

## The three rules that never break

1. **Two separate dates per booking.** `scheduled_for` is when the thing happens ("Quando"):
   the departure, the check-in, the ticket's time slot. `book_by` is the deadline to book it
   ("Prenota entro"). `book_by` is **strictly before** `scheduled_for`, never equal, never
   copied from it, and never in the past. When the source gives no deadline, set `book_by` to
   null: the backend derives one from `scheduled_for`.
2. **Every instant carries a UTC offset, in the trip's time zone**: `2027-05-13T06:10:00+01:00`,
   never `2027-05-13T06:10:00`. Dates are `YYYY-MM-DD`; local times are `HH:MM` (24h) in the
   trip's zone. A naive instant is rejected.
3. **TripTracker's caps are met before you call submit_plan** (characters after trimming):
   title ≤ 120, name ≤ 200, address ≤ 300, URL ≤ 2000, notes ≤ 4000, `book_by_reason` ≤ 300,
   `phone` ≤ 40, at most 120 days. Titles are never empty.

## Essentials

- One `PlanDay` for every date from `start_date` to `end_date`, each with at least one stop,
  in date order; stop `ref`s unique across the plan (`d1-s1`); kinds `activity`, `meal`,
  `transfer` (flights, trains, taxis, walks between places) and `rest`.
- A booking for everything the user must book (journey, lodging, tickets, tours, tables,
  trains); `stop_ref` is a stop's `ref` or null. No other keys anywhere: an unknown key is
  rejected.
- **Links.** A booking's `link` is a URL from a result file, copied character for character
  (an MCP link or a `build_link.py` output) and only on Booking.com, Airbnb, Google Flights,
  Expedia, Kiwi.com, lastminute.com, Trenitalia, Italo or Omio. An official page (museum,
  restaurant, tour operator) goes in the related stop's `url`, never in `link`. Never write,
  edit, shorten or complete a URL. No link: null.
- **Prices.** Copy each `price` object from the result file unchanged (`amount_cents`,
  `currency`, `status`, `source_url`, `retrieved_at`). Never upgrade `estimated`, convert or
  round an amount, or invent a price; no sourced price means null. The backend converts
  non-EUR prices.
- **Language.** Everything the user reads is Italian (`title`, `destination`, day, stop and
  booking titles, `notes`, `book_by_reason`, `warnings`, `summary`); proper names and addresses
  stay as the source writes them. No personal data anywhere.
- **Length.** The plan is the coordinator's largest output: keep `notes` to one short
  sentence of practical advice, booking notes to a line, `summary` to three lines.

## Before you call submit_plan

- [ ] Every date has one day with at least one stop; every `ref` is unique; every `stop_ref`
      matches a `ref`.
- [ ] Every `book_by` is before its `scheduled_for`, not in the past, or null; never equal.
- [ ] Every `book_by` and `scheduled_for` has the offset of the trip's zone on its date.
- [ ] Caps respected (rule 3); prices copied unchanged; booking links only from the sites above.
- [ ] At most 6 short warnings, each changing a decision: estimated prices, any budget overrun
      (the word "budget", the total and the overrun), booking risks; no tool or error names.
- [ ] User-facing text in Italian, no personal data.

`Plan accepted.` (or `Plan already accepted.`) means done: end your turn with one short
Italian line and do not call submit_plan again. `Plan rejected: N validation errors` lists one
line per problem (`- <path>: <message> (got <value>)`): fix **every** line and call
`submit_plan` again with the **complete** corrected plan. The plan fails for good after three
rejected submissions.
