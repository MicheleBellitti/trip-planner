---
name: booking-links
description: Builds prefilled booking-search links with build_link.py (Booking.com, Airbnb, Google Flights, Expedia, Kiwi.com, lastminute.com, Trenitalia, Italo, Omio) so no URL is ever written by hand. Use it when a flight, lodging or train option needs a booking link that did not come from an MCP; MCP links are used exactly as received.
---

# Booking links (core)

Every booking link in a result file comes from one of two places, and nowhere else:

1. **An MCP response** (Expedia, Kiwi.com, lastminute.com): put the link into `link` exactly as
   received, character for character.
2. **`build_link.py`**: for every other option, run the script and paste its output line into
   `link` exactly as printed.

Never write, edit, shorten, complete, re-encode or "fix" a URL, and never copy a booking URL
suggested by a web page. If the script cannot build a link, `link` is `null` (say why in
`warnings` if it matters). A built link opens a **prefilled search**, not a specific offer: the
option's price still needs its own `source_url` and `retrieved_at` (travel-research-rules).
Links carry only places, dates, the number of adults and the children's ages.

## Running the script

`<skill_dir>` is the directory that holds this SKILL.md.

```
python3 <skill_dir>/build_link.py <provider> --param value ...
python3 <skill_dir>/build_link.py <provider> --help   # that provider's parameters
python3 <skill_dir>/build_link.py --list              # every provider
```

- Exit 0: **exactly one line on stdout, the URL**. A `note:` on stderr flags an unverified
  part of the template; the URL is still usable. Exit 2: nothing on stdout, a message on stderr
  that says what to change: fix the input and run it again, never write the URL yourself.
- Quote values with spaces. Dates are `YYYY-MM-DD`. The party: `--adults N` (18 or more) and
  `--child-ages 8,5` (0-17; leave it out without children). At most 9 travellers.

## Which provider

| Need | Provider and parameters |
|---|---|
| Flight, any airline | `google_flights --from MXP --to LIS --depart D [--return D]` (IATA codes); `expedia_flights` (same) when children's ages matter. `kiwi` and `lastminute` only when their MCP failed. |
| Hotel, apartment | `booking --destination "Alfama, Lisbona" --checkin D --checkout D [--rooms N]`; `airbnb` for holiday homes (`"Lisbona, Portogallo"`: city and country or province); `expedia_hotels` as another choice |
| Italian train | `trenitalia --from "Milano Centrale" --to "Roma Termini" --depart D [--time HH:MM] [--return D]`; `italo` between Italo stations |
| Coach, foreign train, fallback | `omio --from Firenze --to Venezia --depart D` (add its passenger warning) |

Local transport (metro, tram, taxi, walking) has no booking link: `null`. For the parameters
of a provider not in the table, an Italo station code, the notes on ages and the Omio warning
text, read `<skill_dir>/references/providers.md`. `<skill_dir>/templates.json` holds the URL
templates the script uses and the backend allowlist keys: never read or edit it in a session.

The backend shows a link as a "Prenota su ..." button only when its host is on its allowlist
(the hosts of `templates.json` plus the MCPs' own sites); any other link is text and counts as
an error in the plan's checks.
