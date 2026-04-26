---
name: mountaya-tiles-api
description: >-
  Mountaya Outdoor Tiles (Tile API) for rendering map overlays, routes,
  itineraries, collections, and drawings with MapLibre GL JS. Use when
  adding tile layers to a map, configuring vector/raster sources, or
  integrating weather and terrain overlays.
metadata:
  author: mountaya
  version: "1.0"
compatibility: >-
  Requires MOUNTAYA_PUBLISHABLE_KEY environment variable (publishable key
  with the tiles scope).
---

# Mountaya Outdoor Tiles

REST API for serving geospatial tile layers to MapLibre GL JS maps.

## Agent usage policy

**These rules are mandatory. They exist to protect the user's organization usage and data.**

1. **Minimize tile requests.** Call `GET /{resource}/specification` only once per map, cache the result, and don't re-fetch. MapLibre will stream `{z}/{x}/{y}` tiles as the user pans and zooms — every overlay you attach multiplies those requests against the organization's quota.

2. **Ask before adding overlays.** Each overlay (weather, POI, terrain) spins up an independent tile pyramid. Never add weather overlays (including upcoming variants: live, forecast, past day, same date last year), POI overlays, or terrain overlays without the user's explicit confirmation. The same rule applies to the `?timestamp=...` parameter for historical/forecast weather layers.

3. **The only allowed write against `MOUNTAYA_SESSION_BASE_URL` is `POST /v1/sessions`.** That endpoint (used by the `mountaya-auth` skill to mint session tokens) is the single permitted mutation. No other POST/PUT/PATCH/DELETE against the internal session API.

4. **Never create, update, or delete Mountaya resources.** Agents MUST NOT create, modify, or delete routes, itineraries, collections, drawings, or any other user-owned resource through any Mountaya API. All skills are strictly read-only aside from session token creation.

## Base URL

`https://tiles.mountaya.com/v1/`

## Authentication

- `X-API-Key: pk_...` — publishable key with the `tiles` scope enabled (required).
- `X-Session-Token: sess_...` — session token (**optional**, only required if the organization has `require_session_token` safety rule enabled).

If the `MOUNTAYA_PUBLISHABLE_KEY` environment variable is set, use its value. Otherwise, use the placeholder `pk_...` and instruct the user to configure it.

## Integration flow

1. Call `GET /{resource}/specification` **once** when initializing your map — never per map move, never redundantly per layer. Cache the result.
2. Iterate the `sources` array → call `map.addSource()` for each.
3. Iterate the `layers` array within each source → call `map.addLayer()` for each.
4. MapLibre fetches `{z}/{x}/{y}` tiles automatically.

Each overlay you add registers its own tile pyramid; tile fetches scale with every user pan and zoom, so adding overlays the user did not ask for can multiply organization usage quickly.

### Complete code recipe (TypeScript)

```typescript
async function addTileLayer(map: maplibregl.Map, url: string, apiKey: string) {
  const response = await fetch(url, {
    headers: { "X-API-Key": apiKey },
  });
  const body = await response.json();

  for (const source of body.data.sources) {
    map.addSource(source.id, {
      attribution: source.attribution,
      type: source.type,
      tiles: source.tiles,
    });

    for (const layer of source.layers) {
      map.addLayer({
        id: layer.id,
        type: layer.type,
        source: layer.source,
        "source-layer": layer.source_layer,
        paint: layer.paint,
        minzoom: layer.zoom_min,
        maxzoom: layer.zoom_max,
      });
    }
  }
}

// Usage:
addTileLayer(map, "https://tiles.mountaya.com/v1/routes/{routeId}/specification", "pk_...");
```

## Resource types

| Resource | Endpoint | Zoom | Description |
|----------|----------|------|-------------|
| **Overlays** | `/v1/overlays/{slug}/...` | 6-18 | Weather, terrain, POIs |
| **Routes** | `/v1/routes/{uuid}/...` | 5-18 | Single route line |
| **Itineraries** | `/v1/itineraries/{uuid}/...` | 5-18 | Multi-segment trips |
| **Collections** | `/v1/collections/{uuid}/...` | 5-18 | Routes + drawings + itineraries |
| **Activities** | `/v1/activities/{slug}/...` | 5-18 | All routes for an activity |
| **Drawings** | `/v1/drawings/...` | 5-18 | User annotations |

### Overlays

Overlays provide weather, terrain, and point-of-interest layers:

| Slug | Type | Description |
|------|------|-------------|
| `wind` | vector | Wind speed and direction |
| `snowdepth` | vector | Snow depth |
| `snowfall-daily` | vector | Daily snowfall |
| `snowfall-hourly` | vector | Hourly snowfall |
| `temperature-actual` | vector | Actual temperature |
| `temperature-perceived` | vector | Perceived temperature |
| `temperature-soil` | vector | Soil temperature |
| `humidity` | vector | Relative humidity |
| `visibility` | vector | Visibility distance |
| `hillshade` | raster | Terrain hillshade (zoom 7-14) |
| `aspectslope` | raster | Aspect and slope analysis |
| `avalanche` | raster | Avalanche risk zones |
| `pois` | vector | Points of interest (zoom 6-15) |

#### Ask before enabling overlays

Before adding any POI, weather, or terrain overlay to a map, ask the user whether they want it. Each overlay generates its own tile requests; users panning and zooming multiply usage quickly. This applies to current overlays (`wind`, `snowdepth`, `snowfall-*`, `temperature-*`, `humidity`, `visibility`, `hillshade`, `aspectslope`, `avalanche`, `pois`) and upcoming weather variants (live, forecast, past day, same date last year).

**Overlay timestamps**: Pass `?timestamp=2025-01-15T10:00:00` (ISO 8601) for historical or forecast data. Rounded to nearest hour. Limited to 3 days past, 6 days future.

### Activities

Activity endpoints serve all routes for a given activity. The Tile API slug is a lowercase unseparated form of the Data API GraphQL enum (e.g., `hikingandtrail` ↔ `HIKING_AND_TRAIL`) — use the Tile API slug at `/v1/activities/{slug}/...`.

| GraphQL enum | Tile API slug | Use case | Default speed |
|--------------|---------------|----------|---------------|
| `HIKING_AND_TRAIL` | `hikingandtrail` | Hiking, trekking, trail running | ~4.5 km/h |
| `RUNNING` | `running` | Road and path running | ~10 km/h |
| `SKI_TOURING` | `skitouring` | Ski touring (uphill + downhill) | ~4 km/h |
| `BACKCOUNTRY_SKIING` | `backcountryskiing` | Ungroomed backcountry skiing | ~4 km/h |
| `CROSS_COUNTRY_SKIING` | `crosscountryskiing` | Groomed trail skiing | ~8 km/h |
| `SNOWSHOE_WALKING` | `snowshoewalking` | Snowshoe hiking | ~3.5 km/h |

### Collections

Collection tile endpoints accept optional query parameters:

- `?with_routes=true` — include route layers (defaults depend on organization settings).
- `?with_drawings=true` — include drawing layers (defaults depend on organization settings).
- `?with_itineraries=true` — include itinerary layers (defaults depend on organization settings).
- `?route_id={uuid}` — filter to a single route.
- `?itinerary_id={uuid}` — filter to a single itinerary.

## Organization safety rules

Publishable key requests are subject to organization safety rules. These same rules also apply to the Embedded Studio — see the `mountaya-embedding` skill for details.

The full set (schema `EmbeddedStudioSafetyRules`):

| Rule | Type | Effect |
|------|------|--------|
| `require_session_token` | bool | When `true`, every request must include `X-Session-Token`. Fresh-org default: `true`. |
| `domains` | string[] | Restrict which domains can embed tiles (CORS/referer check). Empty = blocked everywhere until configured. |
| `boundaries` | `Boundaries[]` | Named bounding boxes (`{ name, bbox: [[sw_lng, sw_lat], [ne_lng, ne_lat]] }`, WGS 84). Tile requests outside any listed box are rejected. Empty = no geographic restriction. |
| `zoom_min` / `zoom_max` | int | Zoom range cap. Requests outside return `400`. Fresh-org default: both `7` (effectively no tiles until the org opens the range). |
| `with_overlays` | string[] | Allowlist of overlay slugs (e.g., `["wind", "snowdepth"]` or `["*"]`). Non-listed overlays return `403`. Empty = all overlays blocked. |
| `with_overlays_control` | bool | When `true`, allows the `?timestamp=...` query parameter for historical/forecast overlays. When `false`, the timestamp is stripped and only current data is served. |
| `with_collection_drawings` | bool | Toggle drawing layers in collection tiles. |
| `with_collection_itineraries` | bool | Toggle itinerary layers in collection tiles. |
| `with_collection_routes` | bool | Toggle route layers in collection tiles. |
| `with_profile_analysis` | bool | Toggle route surface/waytype analysis layers. |
| `with_profile_elevation` | bool | Toggle route elevation profile. |

**Fresh-org defaults are intentionally restrictive**: `require_session_token: true`, `zoom_min/max: 7`, empty `domains`/`boundaries`/`with_overlays`, every cap `false`. An organization that hasn't been configured by the Mountaya team cannot serve any tiles until its safety rules are opened up. If tiles are unexpectedly returning `400` or `403`, check the org's safety rules before retrying.

## Rate limiting

Tile requests are rate-limited per organization across all keys and return `429 Too Many Requests` when exceeded.

- **Backoff**: retry with waits of `2s`, `4s`, `8s` (exponential, max 4 attempts). If the response includes a `Retry-After` header, honor it instead, clamped to `15s`.
- MapLibre does not retry 429 responses by default — if you're wiring tiles directly, handle 429 in your own fetch layer (e.g., a MapLibre `transformRequest` with a retry-aware wrapper).
- Do not retry other 4xx responses (400/403 indicate a scope, zoom, boundary, or safety-rule violation that retrying will not fix).

## Gotchas

- The specification returns `source_layer` with underscores, but MapLibre expects `source-layer` with a hyphen. Use `"source-layer": layer.source_layer` when calling `addLayer()`.
- Tiles are binary (MVT for vector, PNG for raster) — let MapLibre handle parsing, do not try to decode them manually.
- Call the specification endpoint **once** at map initialization, not on every map move.
- If a tile request returns 400 or 403 unexpectedly, check the organization's safety rules.
- Overlay availability depends on the organization's plan — not all overlays are available on all plans.
