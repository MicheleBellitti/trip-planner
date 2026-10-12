---
name: booking-links
description: Builds prefilled booking-search links with build_link.py for Booking.com, Airbnb, Google Flights, Expedia (hotels and flights), Kiwi.com, lastminute.com, Trenitalia, Italo and Omio, so that no URL is ever written by hand. Use it whenever a flight, lodging or train option needs a booking link that did not come from an MCP; links returned by an MCP are used exactly as received.
---

# Booking links

Every booking link in a result file comes from one of two places, and nowhere else:

1. **An MCP response** (Expedia, Kiwi.com, lastminute.com): put the link the MCP returned into
   `link` exactly as received, character for character. Never rewrite it.
2. **`build_link.py`**: for every other option, run the script and paste its output line into
   `link` exactly as printed.

Never write, edit, shorten, complete, re-encode or "fix" a URL yourself, and never copy a
booking URL suggested by a web page. If the script cannot build a link for an option, the link
is `null`; say why in the result's `warnings` if it matters.

A built link opens a **prefilled search** (places, dates, party) on the provider's site, not a
specific offer. The option's price still needs its own source: `price.source_url` is the page
or MCP offer where you read the amount, with `retrieved_at` (travel-research-rules skill).

Links carry only places, dates, the number of adults and the children's ages. Never pass
names, e-mail addresses, phone numbers or any other personal data.

## Running the script

`<skill_dir>` is the directory that holds this SKILL.md (the path you read it from).

```
python3 <skill_dir>/build_link.py <provider> --param value ...
python3 <skill_dir>/build_link.py --list              # every provider and parameter
python3 <skill_dir>/build_link.py <provider> --help   # one provider
```

- Success: exit status 0 and **exactly one line on stdout, the URL**. A `note:` on stderr flags
  an unverified part of the template (see the table); the URL is still usable.
- Bad input: exit status 2, nothing on stdout, and a message on stderr that says what to
  change. Fix the input and run it again; never fall back to writing the URL.
- Quote every value with spaces: `--destination "Alfama, Lisbona"`.
- Dates are `YYYY-MM-DD` for every provider; the script converts them to each site's format.
- The party: `--adults N` (people aged 18 or more) and `--child-ages 8,5` (one age per child,
  0-17, comma-separated; leave it out when there are no children). The script maps the ages to
  each site's bands (for example Airbnb counts 13-17 as adults, Italo has Giovani and Bambini).
  At most 9 travellers; flight providers allow one child under 2 per adult.

Examples (real output):

```
$ python3 <skill_dir>/build_link.py booking --destination "Alfama, Lisbona" --checkin 2026-11-14 --checkout 2026-11-18 --adults 2 --child-ages 8,5
https://www.booking.com/searchresults.it.html?ss=Alfama%2C%20Lisbona&checkin=2026-11-14&checkout=2026-11-18&group_adults=2&group_children=2&age=8&age=5&no_rooms=1&selected_currency=EUR

$ python3 <skill_dir>/build_link.py google_flights --from MXP --to LIS --depart 2026-11-14 --return 2026-11-18 --adults 2 --child-ages 8,5
https://www.google.com/travel/flights?q=Flights%20to%20LIS%20from%20MXP%20on%202026-11-14%20through%202026-11-18%20for%202%20adults%20and%202%20children&hl=it&gl=IT&curr=EUR

$ python3 <skill_dir>/build_link.py trenitalia --from "Milano Centrale" --to "Roma Termini" --depart 2026-11-14 --time 08:00 --adults 2 --child-ages 8
https://www.lefrecce.it/Channels.Website.WEB/website/auth/handoff?action=searchTickets&lang=it&referrer=www.trenitalia.com&tripType=on&ynFlexibleDates=off&selectedTrainType=tutti&departureStation=Milano%20Centrale&arrivalStation=Roma%20Termini&departureDate=14-11-2026&departureTime=08&returnDate=14-11-2026&noOfAdults=2&noOfChildren=1

$ python3 <skill_dir>/build_link.py booking --destination "Lisbona" --checkin 2026-11-18 --checkout 2026-11-14 --adults 2
build_link.py: error: booking: --checkout (2026-11-14) must be after --checkin (2026-11-18)
```

## Providers

`[o]` marks an optional parameter. Every provider also takes `--adults` and `[o] --child-ages`,
except Omio.

| Provider | For | Parameters | Notes |
|---|---|---|---|
| `google_flights` | flights, any airline | `--from` `--to` IATA codes in upper case (`MXP`, or a city code like `MIL`), `--depart`, `[o] --return` | No ages: 12-17 count as adults, 0-11 as children with a seat. One way when `--return` is left out. |
| `expedia_flights` | flights | as google_flights | Sends every child's age. |
| `kiwi` | flights, fallback | `--from` `--to` as `"City, Country"` **in English** (`"Milan, Italy"`), `--depart`, `[o] --return` | Only when the Kiwi MCP fails. An unknown city slug makes Kiwi silently show the user's previous search. |
| `lastminute` | flights, fallback | as google_flights | Only when the lastminute MCP fails. Partly verified: one way and child ages unverified; prices shown in GBP. |
| `booking` | hotels, apartments | `--destination` (free text, Italian names work, most specific first: `"Alfama, Lisbona"`), `--checkin`, `--checkout`, `[o] --rooms` (default 1) | Sends every child's age. |
| `airbnb` | holiday homes | `--destination` as `"City, Province or Country"` (`"Lisbona, Portogallo"`, `"Reggio Emilia, RE"`), `--checkin`, `--checkout` | A bare city can resolve to the wrong place, so the second part is required. No ages: 13-17 count as adults, under 2 as infants. |
| `expedia_hotels` | hotels | `--destination`, `--checkin`, `--checkout`, `[o] --rooms` | Adults spread over the rooms; every child's age sent. |
| `trenitalia` | Frecce, Intercity, regional trains | `--from` `--to` official station names (`"Milano Centrale"`, `"Roma Termini"`, `"Firenze S. M. Novella"`, `"Napoli Centrale"`), `--depart`, `[o] --time HH:MM` (default 08:00), `[o] --return`, `[o] --return-time HH:MM` (only with `--return`, default 08:00) | Lands on the results page. 15-17 count as adults, 0-14 as "ragazzi". |
| `italo` | Italo high-speed trains | `--from` `--to`: an Italo station code or name from the table below, `--depart`, `[o] --return` | Lands on the results page. Children 14-17 Giovani, 3-13 Bambini, 0-2 infants. |
| `omio` | coaches, foreign trains, fallback | `--from` `--to` single Italian city names (`"Firenze"`, `"Venezia"`), `--depart` | No party and no return date: Omio opens the search form with one passenger. Add to the result's `warnings`: "Su Omio scegli il numero di passeggeri prima di cercare. Se la pagina non esiste, cerca la tratta da omio.it." |

Italo stations (the only ones the script knows): `MC_` Milano Centrale, `MPG` Milano Porta
Garibaldi, `RG_` Milano Rogoredo, `RRO` Milano Rho Fiera, `MI0` Milano (Tutte), `RMT` Roma
Termini, `RTB` Roma Tiburtina, `RM0` Roma (Tutte), `SMN` Firenze S.M.Novella, `NAC` Napoli
Centrale, `NAF` Napoli Afragola, `NA0` Napoli (Tutte). For any other station use `trenitalia`
or `omio`.

## Which provider

- **Flights**: the MCP's own link first. Otherwise `google_flights` (every airline), or
  `expedia_flights` when the children's ages matter. `kiwi` and `lastminute` only as a fallback
  when their MCP fails.
- **Lodging**: the Expedia MCP's link first. Otherwise `booking` for hotels and apartments
  (ages and rooms), `airbnb` for holiday homes, `expedia_hotels` as another choice.
- **Trains and coaches**: `trenitalia` for Trenitalia trains, `italo` for Italo trains between
  the stations above, `omio` for coaches, trains abroad or as a fallback. Local transport
  (metro, tram, taxi, walking) has no booking link: `null`.

## What the backend accepts

The backend shows a booking link as a "Prenota su ..." button only when its host is on a
per-provider allowlist: the hosts in `templates.json` plus the MCPs' own sites. Every host this
script produces is on it (the skill's tests check this). A link on any other site is shown only
as text, and the plan's checks count it as an error, so never put a link from another site in
`link`.

## templates.json

One entry per provider: the URL template, the allowed parameters with their types, the host,
the backend allowlist key, and the verification status. Every template was opened in a browser
on 2026-10-12 and the prefilled fields were read back (`verified`); `lastminute` is
`partly_verified`, and each entry lists its `unverified` parts. Sites change their URLs without
notice: the templates are re-checked at each release. Do not edit the file during a session.
