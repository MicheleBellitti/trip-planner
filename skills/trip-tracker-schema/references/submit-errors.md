# Reading submit_plan's answer

Read this only after `submit_plan` has rejected the plan.

- `Plan accepted.` — done. End your turn with a short Italian summary; do not call
  submit_plan again. (`Plan already accepted.` means the same.)
- `Plan rejected: N validation errors. ...` — one line per problem: `- <path>: <message>
  (got <value>)`. Paths point into your input: `days[2].stops[0].start_time` is the first stop
  of the third day; `bookings[1].price.currency` is the second booking's price currency.
  Fix **every** line, then call submit_plan again with the **complete** corrected plan (never a
  partial one). The plan fails for good after three rejected submissions.
- Checks run in layers: problems between fields (duplicate refs, dates outside the trip,
  unknown `stop_ref`, `book_by` not before `scheduled_for`) appear only once every field is
  well formed. Check those rules yourself before resubmitting, so one round fixes everything.
- A rejection that says the **translated TripTracker trip** failed TripTracker's schema uses
  TripTracker's names: `days[i]` counts every date from `start_date` (not your `days` list),
  `startTime` is `start_time`, `durationMin` `duration_min`, `locationName` `location_name`,
  `dueAt` `book_by`, `scheduledFor` `scheduled_for`, `url` a booking's `link` or a stop's `url`,
  `costCents` the price, `baseName`/`baseAddress` `lodging_name`/`lodging_address`. Fix the
  plan field it comes from.

Common problems and their fixes:

| Message contains | Fix |
|---|---|
| `Input should have timezone info` | add the offset of the trip's zone: `+01:00` |
| `must be strictly before scheduled_for` | an earlier deadline from the sources, or null |
| `is in the past` | a future deadline (at least tomorrow), or null |
| `at most 120 characters` (or 200, 300, 2000, 4000) | shorten the text; keep proper names whole |
| `at least 1 character` | write the missing title or summary |
| `Extra inputs are not permitted` | remove the key (`price.amount`, `link` on a stop, `date` on a booking ...) |
| `should match pattern '^([01]\d\|2[0-3]):[0-5]\d$'` | `start_time` as `09:30`, not `9:30` or `9.30` |
| `should match pattern '^[A-Z]{3}$'` | `currency` in upper case: `EUR` |
| `valid integer, got a number with a fractional part` | `amount_cents` as an integer: `12.5` € is `1250` |
| `is not an IANA time zone name` | the exact zone name the message suggests: `Europe/London` |
| `already used by` / `already appears at` | a new unique `ref` / merge the two days into one |
| `outside the trip` | move the stops to a date in range, or fix `start_date`/`end_date` |
| `matches no stop ref` | the `ref` of an existing stop, or null |
| `url must be an absolute https:// URL` | the full `https://` page from the result file, or null |
| `Input should be 'activity', 'meal', 'transfer' or 'rest'` | a flight is a `transfer` stop; its booking is `transport` |
| `valid URL` on `source_url` | the full source URL from the result file |
