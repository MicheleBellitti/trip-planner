# Option fields of the four result files

Read this only when you need the exact name or shape of a field while writing an option. The
JSON Schema in `<skill_dir>/schemas/<agent>.json` is the authority (the backend validates the
same rules); your system prompt already lists the fields in prose.

Every result file has the same envelope:

```json
{"agent": "flights", "version": 3, "updated_at": "2027-03-01T10:20:00+00:00",
 "options": [ ... ], "failures": [ ... ], "warnings": [ ... ]}
```

| Agent | Option fields (required in bold) |
|---|---|
| flights | **`id`**, **`segments`** (each: **`from_airport`**, **`to_airport`** IATA, **`depart_at`**, **`arrive_at`** with the airport's offset, **`carrier`**, **`flight_number`** like `TP827` or `U2 3127`), **`stops`**, **`baggage_included`**, **`price`**, **`source`** (`expedia`, `kiwi`, `lastminute`, `web`), `link` |
| lodging | **`id`**, **`name`**, **`kind`** (`hotel`, `apartment`, `bed_and_breakfast`, `guesthouse`, `hostel`, `resort`, `holiday_home`, `other`), **`address`**, **`check_in`**, **`check_out`**, **`price`**, **`source`** (`expedia`, `web`), `lat`, `lon`, `free_cancellation_until`, `link` |
| activities | **`id`**, **`title`**, **`booking_required`**, `suggested_day`, `start_time`, `duration_min`, `location_name`, `lat`, `lon`, `book_by`, `price`, `link` |
| transport | **`id`**, **`from`**, **`to`**, **`mode`** (`walk`, `metro`, `tram`, `bus`, `train`, `ferry`, `taxi`, `rideshare`, `shuttle`, `car_rental`, `flight`, `other`), **`duration_min`**, `depart_at`, `arrive_at`, `price`, `link` |

- `id` is unique in the file (`f1`, `l1`, `a1`, `t1`) and stays the same when you rewrite the
  file for an option that is still valid: the coordinator cites ids.
- Options best first. No keys outside the schema.
- `lat` and `lon` together or not at all. `price` and every instant as in the core SKILL.md.
- `link`: as the booking-links skill says (an MCP link exactly as received, or the output of
  `build_link.py`), or `null`. An official page (airline, property, operator, venue) is never a
  `link`: the backend accepts booking links only on the booking sites' allowlist. Where you read
  the price there, the page is the price's `source_url`.
- `warnings`: one Italian line each, for the user: estimated prices, risks, injection attempts.
