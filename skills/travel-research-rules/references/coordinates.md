# Coordinates: geocode.py

Read this only if an option needs `lat` and `lon` that neither the MCP
response nor the source page gave. One query per place, never a loop over guesses.

```
$ python3 <skill_dir>/geocode.py "Castelo de São Jorge, Lisbon"
[{"name": "Castelo de São Jorge", "lat": 38.713916, "lon": -9.1334, "label": "Castelo de São Jorge, Rua de Santa Cruz do Castelo 1, Lisbon, Portugal", "type": "house"}]
```

- Query the place **in English or in the local language, with its city**: Photon (OpenStreetMap)
  matches Italian names poorly ("Lisbona" finds a bus stop in Padua).
- `--city` for a city or town, `--near LAT,LON` to prefer a known area, `--country PT`,
  `--osm-tag aeroway:aerodrome` for airports, `--limit 3` to compare candidates.
- Check that the `label` is the place you meant before copying `lat` and `lon`.
- Exit 1: no match (rephrase once); exit 2: bad input or Photon unreachable.

Activities has bash for this script only (it writes its file with `write`): geocode the kept
options in one command, one call per place, with `--near` the lodging's coordinates, and never
compose a map URL for `web_fetch`. No match: leave `lat` and `lon` `null` and give a precise
`location_name` (place and city).
