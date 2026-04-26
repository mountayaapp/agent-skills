---
name: mountaya-data-api
description: >-
  Mountaya Outdoor Intelligence (GraphQL Data API) for outdoor routing
  and geospatial analysis. Use when computing directions, generating
  route suggestions, analyzing geometry, computing time-distance
  matrices, or generating isochrones for activities like hiking,
  running, and skiing.
metadata:
  author: mountaya
  version: "1.0"
compatibility: >-
  Requires MOUNTAYA_PUBLISHABLE_KEY and MOUNTAYA_SECRET_KEY environment
  variables. Requires Python 3. Requires the mountaya-auth skill
  installed alongside (this skill invokes mountaya-auth/scripts/session.py).
---

# Mountaya Outdoor Intelligence

GraphQL API for geospatial routing and analysis of outdoor activities.

## Agent usage policy

**These rules are mandatory. They exist to protect the user's organization usage and data.**

1. **Minimize API calls.** Every GraphQL call counts against the organization's quota. Reuse a single session token across all queries in one task (5-minute TTL — `session.py` caches it on disk), run `references/introspect.py` at most once per task (it caches the schema for 24 h), batch via `matrix`, request only the fields you need, and never re-fetch data you already have.

2. **Ask before fetching enrichment resources.** When returning a geometry (route, isochrone, analyzed track) or giving advice/recommendations, DO NOT automatically call `matrix`, `isochrones`, `analyzeGeometry`, POI overlays, or weather overlays (including upcoming weather variants: live, forecast, past day, same date last year). Present them as opt-in follow-ups and wait for the user's explicit confirmation before issuing the calls.

3. **The only allowed write against `MOUNTAYA_SESSION_BASE_URL` is `POST /v1/sessions`.** That endpoint (used by `mountaya-auth/scripts/session.py` to mint session tokens) is the single permitted mutation. No other POST/PUT/PATCH/DELETE against the internal session API.

4. **Never create, update, or delete Mountaya resources.** Agents MUST NOT create, modify, or delete routes, itineraries, collections, drawings, or any other user-owned resource through any Mountaya API. All skills are strictly read-only aside from session token creation.

## Endpoint

`POST https://data.mountaya.com/graphql`

## Authentication

Use the bundled script to handle session token creation and query execution in one step:

```bash
python3 scripts/query.py '{ directions(input: { activity: HIKING_AND_TRAIL, waypoints: [[6.1294, 45.8992], [6.2169, 45.8458]] }) { routes { distance duration summary } } }'
```

The script delegates authentication to the `mountaya-auth` skill's `session.py` (which caches the session token on disk and reuses it within its 5-minute TTL), then sends the GraphQL query and outputs the JSON response.

For long queries, prefer `--file` or stdin to avoid shell-escaping issues:

```bash
python3 scripts/query.py --file queries/hike.graphql
# or:
cat queries/hike.graphql | python3 scripts/query.py -
```

Run `python3 scripts/query.py --help` for full usage details.

Requires `MOUNTAYA_SECRET_KEY` and `MOUNTAYA_PUBLISHABLE_KEY` environment variables. See the `mountaya-auth` skill for full authentication details.

## Schema reference

Run the introspection script to get the full, up-to-date GraphQL schema — all types, fields, arguments, enums, and descriptions:

```bash
python3 references/introspect.py
# or, to force a refetch past the 24 h cache:
python3 references/introspect.py --no-cache
```

Use this to discover all available input parameters and response fields for any operation. Output is cached on disk for 24 hours per Data API endpoint so repeated calls across a task don't consume quota.

## Returning geometries to the user

**IMPORTANT**: After returning a geometry, do NOT automatically call `matrix`, `isochrones`, `analyzeGeometry`, or fetch POIs / weather overlays. These add significant organization usage. List them as opt-in follow-ups and wait for the user's explicit confirmation before running them.

Whenever a query returns geometry (directions, suggestions, isochrones, analyzeGeometry), always offer the user the option to download the result as **GPX** or **GeoJSON** (offering incurs no additional API calls — the geometry is already in the response).

- **GeoJSON**: The `geometry` field in API responses is already a GeoJSON geometry object. Wrap it in a Feature to create a valid GeoJSON file:
  ```json
  { "type": "Feature", "geometry": <geometry from API>, "properties": {} }
  ```

- **GPX**: Convert the coordinate array to GPX XML. Route geometries use 3D coordinates `[longitude, latitude, elevation]`:
  ```xml
  <?xml version="1.0" encoding="UTF-8"?>
  <gpx version="1.1" creator="Mountaya Data API">
    <trk>
      <trkseg>
        <trkpt lat="45.8372" lon="6.1060"><ele>1699</ele></trkpt>
        <trkpt lat="45.8400" lon="6.1100"><ele>1650</ele></trkpt>
      </trkseg>
    </trk>
  </gpx>
  ```

Note: GPX uses `lat`/`lon` attribute order (reversed from the API's `[longitude, latitude]` array order).

## Coordinate convention

**CRITICAL**: All coordinates use `[longitude, latitude]` order (WGS 84) — NOT `[lat, lon]`.

- Annecy (lakefront): `[6.1294, 45.8992]`
- Talloires (east lakeshore): `[6.2169, 45.8458]`
- Le Semnoz (summit): `[6.1060, 45.8372]`

**Response geometries include elevation**: Route geometries from `directions` and `suggestions` return 3D coordinates `[longitude, latitude, elevation]` where elevation is in meters above sea level.

## Units

- Distances: **meters**
- Durations: **seconds**
- Elevations: **meters above sea level**
- Gradients: **degrees** (positive = uphill, negative = downhill)
- Speeds: **km/h**

## Available queries

### directions

Compute a route between two or more waypoints.

```bash
python3 scripts/query.py '{ directions(input: { activity: HIKING_AND_TRAIL, waypoints: [[6.1294, 45.8992], [6.2169, 45.8458]] }) { routes { distance duration summary elevation { altitude { min max } ascent descent gradient { min max } } geometry analysis { surfaceInfo { fromIndex toIndex value } waytypeInfo { fromIndex toIndex value } } } } }'
```

### suggestions

Generate loop or point-to-point route candidates matching a target distance.

```bash
python3 scripts/query.py '{ suggestions(input: { activity: HIKING_AND_TRAIL, start: [6.1294, 45.8992], distance: 20000, candidates: 3 }) { routes { distance duration summary seed elevation { ascent descent } geometry } } }'
```

- Omit `end` for a loop route; provide `end` for point-to-point.
- Use `seeds: { include: [<seed>] }` to pin a previously-returned `seed` back into the result (pair with `candidates: 1` to get only that route). Use `seeds: { exclude: [...] }` to filter seeds out of the fresh candidate pool.
- Use `ascent` to target a specific elevation gain.
- Use `points` (2-10) to control loop roundness.

### matrix

Compute time and/or distance between multiple locations.

```bash
python3 scripts/query.py '{ matrix(input: { activity: RUNNING, locations: [[6.1294, 45.8992], [6.2232, 45.7773], [6.1946, 45.8683]], metrics: [DURATION, DISTANCE] }) { durations distances } }'
```

- Use `sources: [0]` to compute from only the first location to all others.
- Null values in the grid mean the pair is unreachable.

### isochrones

Compute reachability polygons from one or more locations.

```bash
python3 scripts/query.py '{ isochrones(input: { activity: HIKING_AND_TRAIL, locations: [[6.1294, 45.8992]], range: [1800, 3600], rangeType: TIME }) { isochrones { value area geometry } } }'
```

- `range` is in **seconds** for `TIME`, **meters** for `DISTANCE`.
- Multiple values produce concentric polygons.

### analyzeGeometry

Analyze surface type, way type, and slope of an existing geometry.

```bash
python3 scripts/query.py '{ analyzeGeometry(input: { activity: HIKING_AND_TRAIL, coordinates: [[6.1294, 45.8992], [6.1500, 45.8900], [6.1700, 45.8800]] }) { surfaceInfo { fromIndex toIndex value } waytypeInfo { fromIndex toIndex value } slopeInfo { fromIndex toIndex value } } }'
```

## Activity slugs

The GraphQL enum form (below) is the one to pass to Data API inputs. The Tile API uses a lowercase unseparated form of the same slug (e.g., `HIKING_AND_TRAIL` ↔ `hikingandtrail`) at `/v1/activities/{slug}/...`.

| GraphQL enum | Tile API slug | Use case | Default speed |
|--------------|---------------|----------|---------------|
| `HIKING_AND_TRAIL` | `hikingandtrail` | Hiking, trekking, trail running | ~4.5 km/h |
| `RUNNING` | `running` | Road and path running | ~10 km/h |
| `SKI_TOURING` | `skitouring` | Ski touring (uphill + downhill) | ~4 km/h |
| `BACKCOUNTRY_SKIING` | `backcountryskiing` | Ungroomed backcountry skiing | ~4 km/h |
| `CROSS_COUNTRY_SKIING` | `crosscountryskiing` | Groomed trail skiing | ~8 km/h |
| `SNOWSHOE_WALKING` | `snowshoewalking` | Snowshoe hiking | ~3.5 km/h |

## Query optimization

Every API call counts against the organization's quota. Apply these rules to keep usage minimal:

- **Introspect once per task.** Run `python3 references/introspect.py` at most once and reuse the cached schema for the rest of the task.
- **Reuse one session token.** Session tokens have a 5-minute TTL — share one token across every query in a task instead of creating a new one per call.
- **Batch matrix requests.** Use `matrix` with all locations in a single call (and `sources: [0]` if you only need distances from one origin) rather than looping per pair.
- **Request only what you need.** GraphQL lets you select fields — skip `geometry` when you only need distance/duration, skip `analysis` when you only need `summary`, etc.
- **Get all suggestions in one call.** For `suggestions`, request the maximum `candidates` you might need in one call, not several incremental calls.
- **Never re-fetch.** If you already have a result in the conversation, reuse it instead of re-querying.

## Common patterns

Each of the patterns below chains multiple queries. **Run the second query only after the user explicitly asks for it** — do not chain automatically.

- **Compute then analyze**: Use `directions` to get a route. Run `analyzeGeometry` on its coordinates only after the user asks for a surface/slope breakdown.
- **Find closest point**: Use `matrix` with `sources: [0]` to find distances from one location to many others. Only run after the user has asked for distance comparisons.
- **Generate loop options**: Use `suggestions` with `candidates: 3-5` to get multiple loop options in a single call, then let the user pick.
- **Reproduce a route**: Save the `seed` returned on a `SuggestionRoute`, pass it back via `seeds: { include: [<seed>] }` with `candidates: 1` to get the same route again. Reproducing also requires passing the same `start`/`end`/`distance`/`points` — mismatched inputs produce a different route even with the same seed.

## Rate limiting

GraphQL requests are rate-limited per organization across all keys and return `429 Too Many Requests` when exceeded. Session-token creation shares the same quota.

- **Backoff**: retry with waits of `2s`, `4s`, `8s` (exponential, max 4 attempts). If the response includes a `Retry-After` header, honor it instead, clamped to `15s`.
- Do not retry other 4xx responses (400/401/403 indicate a scope, key, payload, or expired-token problem that retrying will not fix — for 401 on an expired session token, mint a fresh one via `mountaya-auth` instead of retrying).
- On 5xx, retry once after 2 s, then fail.

## Gotchas

- Coordinates are `[longitude, latitude]` — NOT `[lat, lon]`.
- `waypoints` requires at least 2 points.
- `range` units depend on `rangeType`: seconds for `TIME`, meters for `DISTANCE`.
- The `summary` field returns a human-readable string (e.g., "15.2 km, ~4h12m, +720m / -430m elevation, 62% unpaved.").
- All responses use GeoJSON geometry objects with `type` and `coordinates` fields. Route geometries (`directions`, `suggestions`) return 3D coordinates `[lng, lat, elevation]`.
- Run `python3 references/introspect.py` to discover all available fields and types.
