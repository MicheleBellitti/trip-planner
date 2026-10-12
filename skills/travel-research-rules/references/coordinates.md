# Coordinates: geocode.py

Read this only if you have bash and an option needs `lat` and `lon` that neither the MCP
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

Without bash (activities) you cannot geocode: `web_fetch` refuses a URL you build, so never
compose a Photon or map query. Copy `lat` and `lon` only from a page you fetched or a search
result that shows the place's own coordinates, in the text or in a map link such as
`@38.7139,-9.1334` or `mlat=38.7139&mlon=-9.1334`; otherwise leave both `null` and give a
precise `location_name` (place and city).
