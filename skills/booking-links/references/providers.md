# Providers of build_link.py

Read this when the provider you need is not in the core SKILL.md's quick table, or when a
parameter's rules matter (ages, station names, notes). `python3 <skill_dir>/build_link.py
<provider> --help` prints one provider's parameters, and `--list` all of them.

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

## Examples (real output)

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

## templates.json

One entry per provider: the URL template, the allowed parameters with their types, the host,
the backend allowlist key, and the verification status. Every template was opened in a browser
on 2026-10-12 and the prefilled fields were read back (`verified`); `lastminute` is
`partly_verified`, and each entry lists its `unverified` parts. Sites change their URLs without
notice: the templates are re-checked at each release. Do not edit the file during a session.
