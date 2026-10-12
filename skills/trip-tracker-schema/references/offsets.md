# Writing instants with the right offset

Read this when you write an instant (`book_by`, `scheduled_for`) and are not sure of the UTC
offset on that date.

The offset is the one in force in the trip's zone **on that date**. Daylight saving time
changes it during the year:

| Zones | Winter | Summer | Summer time 2026 | Summer time 2027 |
|---|---|---|---|---|
| `Europe/London`, `Europe/Lisbon`, `Europe/Dublin` | `+00:00` | `+01:00` | Mar 29 – Oct 25 | Mar 28 – Oct 31 |
| `Europe/Rome`, `Europe/Paris`, `Europe/Madrid`, `Europe/Berlin`, `Europe/Amsterdam`, `Europe/Vienna`, `Europe/Prague`, ... | `+01:00` | `+02:00` | Mar 29 – Oct 25 | Mar 28 – Oct 31 |
| `Europe/Athens`, `Europe/Helsinki` | `+02:00` | `+03:00` | Mar 29 – Oct 25 | Mar 28 – Oct 31 |
| `America/New_York` | `-05:00` | `-04:00` | Mar 8 – Nov 1 | Mar 14 – Nov 7 |
| `America/Los_Angeles` | `-08:00` | `-07:00` | Mar 8 – Nov 1 | Mar 14 – Nov 7 |
| `Asia/Tokyo` | `+09:00` | (none) | | |

Examples: a check-in at 15:00 in London on 2027-05-13 is `2027-05-13T15:00:00+01:00`; a booking
deadline at 20:00 in London on 2027-03-20 (before the change) is `2027-03-20T20:00:00+00:00`.
A flight leaving Milan at 07:10 (`+02:00`) for London is 06:10 London time: `scheduled_for`
`2027-05-13T06:10:00+01:00` and the stop's `start_time` `06:10`. For another zone, use the
offset the result files show for that destination and season.
