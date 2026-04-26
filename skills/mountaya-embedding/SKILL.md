---
name: mountaya-embedding
description: >-
  Mountaya Map Embedding (Embedded Studio) for embedding interactive 3D
  maps via iframe. Use when embedding collections, routes, itineraries,
  and drawings with terrain, weather overlays, and user interactivity.
  Covers iframe properties, postMessage events, safety rules, and
  default props.
metadata:
  author: mountaya
  version: "1.0"
compatibility: >-
  Requires MOUNTAYA_PUBLISHABLE_KEY environment variable (publishable key
  with both embedding and tiles scopes).
---

# Mountaya Map Embedding

Embed interactive 3D maps on any website with a single `<iframe>` tag. Display collections, routes, itineraries, and drawings with terrain, weather overlays, and user interactivity.

## Agent usage policy

**These rules are mandatory. They exist to protect the user's organization usage and data.**

1. **Minimize tile requests.** Every iframe loads tiles from the organization's quota. Leave overlay/terrain selections unset so the org defaults apply, don't re-issue postMessage updates that re-fetch tiles, and never enable layers the user didn't ask for.

2. **Ask before enabling overlays or extra terrains.** Weather overlays (including upcoming variants: live, forecast, past day, same date last year), POI overlays, and additional terrains must be opt-in. Don't pre-enable them via the `with_overlays`, `with_terrains`, or `overlay` URL parameters, and don't push them later via `mountaya:setItinerary`/`setRoute` postMessage updates without explicit user confirmation. Each enabled layer fetches its own tile pyramid on every pan and zoom.

3. **The only allowed write against `MOUNTAYA_SESSION_BASE_URL` is `POST /v1/sessions`.** That endpoint (used by the `mountaya-auth` skill to mint session tokens) is the single permitted mutation. No other POST/PUT/PATCH/DELETE against the internal session API.

4. **Never create, update, or delete Mountaya resources.** Agents MUST NOT create, modify, or delete routes, itineraries, collections, drawings, or any other user-owned resource through any Mountaya API. All skills are strictly read-only aside from session token creation.

## Base URL

`https://app.mountaya.com/studio/embed`

## Authentication

Authentication uses **URL query parameters**, not HTTP headers.

- `publishable_key` — publishable key (`pk_...`) with **both** `embedding` and `tiles` scopes enabled (required).
- `session_token` — session token (`sess_...`), **optional** unless the organization's `require_session_token` safety rule is enabled.

See the `mountaya-auth` skill for how to create session tokens. If the `MOUNTAYA_PUBLISHABLE_KEY` environment variable is set, use its value for the `publishable_key` parameter. Otherwise, use the placeholder `pk_...` and instruct the user to configure it.

```html
<iframe
  src="https://app.mountaya.com/studio/embed
    ?publishable_key=pk_...
    &session_token=sess_...
    &collection_id=0e9788ba-f680-4a74-8354-e7b7fe5ee061
    &route_id=b61e7f93-fa79-4326-9a30-937e53d110c6
    #view=11.50/45.88796/6.97656/176.3/59">
</iframe>
```

## Properties (URL query parameters)

All properties except `view` are query parameters (`?`, joined with `&`). The `view` property is a URL fragment (`#`) and must come last.

### Content selection

| Parameter | Type | Description |
|-----------|------|-------------|
| `collection_id` | uuid | Collection to load. Required if `route_id` or `itinerary_id` is set. |
| `route_id` | uuid | Default active route. Mutually exclusive with `itinerary_id` (itinerary wins). |
| `itinerary_id` | uuid | Default active itinerary. Mutually exclusive with `route_id`. |
| `overlay` | string | Default active overlay (e.g., `temperature-perceived`, `wind`). |
| `activity` | string | Default activity slug. |

### Map state

| Parameter | Type | Description |
|-----------|------|-------------|
| `terrain` | string | Default terrain (e.g., `topo`, `satellite`, `winter`). |
| `terrain_variant` | `"light"` \| `"dark"` | Terrain appearance variant. |
| `view` | fragment | Map position: `#view=zoom/lat/lon/bearing/pitch`. Example: `#view=11.50/45.88796/6.97656/176.3/59`. |

### User preferences

**Locked** (cannot be changed by users in the Preferences panel):

| Parameter | Values | Description |
|-----------|--------|-------------|
| `preferred_language` | `en`, `fr`, `de`, `es`, `it`, `ja`, `zh` | Interface language. |
| `preferred_theme` | `light`, `dark`, `auto` | Color theme. |

**Editable** (user can change via Preferences panel if `with_preferences_control` is enabled; changes persist across all iframes in the session):

| Parameter | Values | Description |
|-----------|--------|-------------|
| `preferred_unit_length` | `metric`, `imperial` | Distance unit. |
| `preferred_unit_slope` | `degrees`, `percentage` | Slope unit. |
| `preferred_unit_temperature` | `celsius`, `fahrenheit` | Temperature unit. |

### Display controls (boolean)

All default to the organization's default props (`false` on a fresh org — see "Default props (fresh-org values)" below). Set `true` or `false` per iframe.

| Parameter | Description |
|-----------|-------------|
| `with_profile_headline` | Route/itinerary summary header. |
| `with_profile_elevation` | Elevation profile. |
| `with_profile_characteristics` | Route characteristics. |
| `with_profile_analysis` | Terrain analysis (requires `with_profile_elevation`). |
| `with_collection_drawings` | Drawings from the collection. |
| `with_collection_itineraries` | Itineraries from the collection. |
| `with_collection_routes` | Routes from the collection. |
| `with_interaction_control` | Map interactivity (zoom, pan, pitch). |
| `with_navigation_control` | Zoom/bearing controls (disabled if `with_interaction_control` is false). |
| `with_scale_control` | Scale indicator. |
| `with_download_control` | Download button (GPX/GeoJSON export). |
| `with_flyover_control` | Flyover button — cinematic camera tour of the active route/itinerary, video export, and social share. |
| `with_preferences_control` | Preferences panel. |
| `with_overlays_control` | History/forecast layer control. |
| `with_streetview_control` | Street View button. |

### Array controls (repeatable)

| Parameter | Type | Description |
|-----------|------|-------------|
| `with_overlays` | string[] \| `["*"]` | Enabled overlays. Repeat param for multiple: `?with_overlays=wind&with_overlays=snowdepth`. Use `["*"]` for all. |
| `with_terrains` | string[] \| `["*"]` | Enabled terrains. Same pattern as overlays. |

If both `with_overlays` and `with_terrains` are empty, the Layers panel is hidden.

**Confirm with the user before setting `with_overlays`, `with_terrains`, or `overlay`.** The iframe will fetch tiles for every enabled overlay/terrain — leaving them unset (so the org defaults apply) avoids extra usage when the user did not explicitly ask for those layers.

## Property resolution order

1. URL parameter value (if explicitly set)
2. Organization default prop

Organization default props are configured in the organization settings dashboard. They set defaults for all iframes without requiring URL overrides.

### Default props (fresh-org values)

Every boolean is opt-in — you must explicitly enable each feature via URL parameter, postMessage, or a customized org default prop. A newly created organization starts with the values below:

| Property | Default | Notes |
|----------|---------|-------|
| `preferred_language` | `en` | Locked — users cannot change via Preferences panel. |
| `preferred_theme` | `light` | Locked — users cannot change via Preferences panel. |
| `preferred_unit_length` | `metric` | Editable via Preferences panel. |
| `preferred_unit_slope` | `degrees` | Editable via Preferences panel. |
| `preferred_unit_temperature` | `celsius` | Editable via Preferences panel. |
| `terrain` | `topo` | Base map terrain slug. |
| `terrain_variant` | `light` | `light` or `dark`. |
| `with_overlays` | `[]` | Empty = no overlays enabled. |
| `with_terrains` | `[]` | Empty = Layers panel hidden (unless `with_overlays` is also non-empty). |
| All other `with_*` booleans | `false` | Every display/collection/profile control (including `with_flyover_control`) is off by default. |

## Organization safety rules

Safety rules are **hard caps** set at the organization level. They cannot be overridden by URL parameters or postMessage events. These same rules also apply to the Tile API.

The full set (schema `EmbeddedStudioSafetyRules`):

| Rule | Type | Effect |
|------|------|--------|
| `require_session_token` | bool | When `true`, `session_token` param is mandatory. Fresh-org default: `true`. |
| `domains` | string[] | Allowlist of embedding domains (CSP frame-ancestors). Requests from unlisted domains are blocked. Empty = blocked everywhere until configured. |
| `boundaries` | `Boundaries[]` | Named geographic bounding boxes (`{ name, bbox: [[sw_lng, sw_lat], [ne_lng, ne_lat]] }`, WGS 84). Restricts map panning area. Empty = no geographic restriction. |
| `zoom_min` / `zoom_max` | int | Zoom level caps. Tile requests outside the range return `400`. Fresh-org default: both `7` (i.e., no zooming until the org opens the range). |
| `with_overlays` | string[] | Allowlist of overlay slugs (e.g., `["wind", "snowdepth"]` or `["*"]`). Non-listed overlays are hidden and return `403` at the tile layer. |
| `with_overlays_control` | bool | Cap: prevents the overlay time-travel control (`timestamp` param) even if the iframe enables it. |
| `with_collection_drawings` | bool | Cap: disables drawings even if the iframe enables them. |
| `with_collection_itineraries` | bool | Cap: disables itineraries even if the iframe enables them. |
| `with_collection_routes` | bool | Cap: disables routes even if the iframe enables them. |
| `with_profile_analysis` | bool | Cap: prevents the terrain analysis panel. |
| `with_profile_elevation` | bool | Cap: prevents the elevation profile. |

**Fresh-org defaults are intentionally restrictive**: `require_session_token: true`, `zoom_min/max: 7`, empty `domains`/`boundaries`/`with_overlays`, all caps off. An organization that hasn't been configured by the Mountaya team cannot embed anything until the allowlists and zoom range are opened up.

## Events (postMessage API)

Switch content, terrains, overlays, and controls at runtime without reloading the iframe.

**The same confirmation rule applies to runtime updates**: do not push `withOverlays`, `withTerrains`, or `overlay` changes via postMessage unless the user explicitly asked to enable those layers. Each new overlay triggers fresh tile fetches.

### Message structure

```javascript
iframe.contentWindow.postMessage({
  type: "mountaya:setItinerary",    // or "mountaya:setRoute"
  itineraryId: "uuid",               // required for setItinerary
  // All other fields optional — omitted = unchanged
  terrain: "winter",
  withOverlays: ["*"],
  withTerrains: ["topo", "satellite"],
  withCollectionRoutes: true,
  withProfileElevation: true,
  withStreetviewControl: false,
}, "https://app.mountaya.com");       // targetOrigin required
```

### Required fields

| Field | Type | Description |
|-------|------|-------------|
| `type` | `"mountaya:setItinerary"` \| `"mountaya:setRoute"` | Action to perform. |
| `itineraryId` | uuid | Itinerary to display (required when type is `setItinerary`). |
| `routeId` | uuid | Route to display (required when type is `setRoute`). |

### Optional fields

All optional. Omitted fields are left unchanged from the previous state.

| Field | Type | Description |
|-------|------|-------------|
| `terrain` | string | Switch terrain. |
| `withOverlays` | string[] \| `["*"]` | Overlay allowlist for Layers panel. |
| `withTerrains` | string[] \| `["*"]` | Terrain allowlist for Layers panel. |
| `withCollectionDrawings` | boolean | Show/hide collection drawings. |
| `withCollectionItineraries` | boolean | Show/hide collection itineraries. |
| `withCollectionRoutes` | boolean | Show/hide collection routes. |
| `withDownloadControl` | boolean | Show/hide download button. |
| `withFlyoverControl` | boolean | Show/hide flyover button (camera tour + video export + share). |
| `withInteractionControl` | boolean | Enable/disable map interactivity. |
| `withNavigationControl` | boolean | Show/hide zoom/bearing controls. |
| `withOverlaysControl` | boolean | Show/hide layer time control. |
| `withPreferencesControl` | boolean | Show/hide preferences panel. |
| `withProfileAnalysis` | boolean | Show/hide terrain analysis. |
| `withProfileCharacteristics` | boolean | Show/hide route characteristics. |
| `withProfileElevation` | boolean | Show/hide elevation profile. |
| `withProfileHeadline` | boolean | Show/hide route summary header. |
| `withProfilePhotos` | boolean | Show/hide photos section. |
| `withScaleControl` | boolean | Show/hide scale indicator. |
| `withStreetviewControl` | boolean | Show/hide Street View button. |

### Outbound events (iframe → parent)

The iframe also emits messages back to the parent window. Attach a `message` listener on `window` to react to them. **Always validate `event.origin === "https://app.mountaya.com"` before acting on a message.**

#### `mountaya:ready`

Emitted when the map finishes loading its current content. Fires once on initial load, then again after each `mountaya:setItinerary` / `mountaya:setRoute` once the new content has rendered. Useful to disable tabs/segmented controls while the map is loading and re-enable them afterward.

```ts
{
  type: "mountaya:ready",
  itineraryId: string | null,
  routeId: string | null,
  terrain: string,
  bounds: [west: number, south: number, east: number, north: number] | null,
  error?: "timeout" | "not_found",
}
```

- `bounds` is `null` only when the map failed to resolve a successful load (see `error`).
- `error` is absent on success. `"timeout"` = the 10s safety timeout fired. `"not_found"` = the requested route/itinerary could not be located.

```javascript
window.addEventListener("message", (event) => {
  if (event.origin !== "https://app.mountaya.com") return;
  if (event.data?.type !== "mountaya:ready") return;

  const { itineraryId, routeId, terrain, bounds, error } = event.data;
  if (error) return; // handle timeout / not_found

  // Map is ready — re-enable UI, sync parent state, etc.
});
```

### Example: tabbed itineraries

```javascript
const EMBED_ORIGIN = "https://app.mountaya.com/studio/embed";
const iframe = document.querySelector("iframe");

const tabs = [
  {
    itineraryId: "bb908a79-dcc1-4db2-aba8-7238dd8f15fc",
    terrain: "topo",
    withOverlays: ["hillshade", "avalanche", "wind"],
    withTerrains: ["topo", "satellite"],
  },
  {
    itineraryId: "1b2a36f4-2ef4-49bc-89db-814ee7de3ebc",
    terrain: "winter",
    withOverlays: ["*"],
    withTerrains: ["winter"],
  },
];

function switchTab(index) {
  iframe.contentWindow.postMessage({
    type: "mountaya:setItinerary",
    ...tabs[index],
  }, EMBED_ORIGIN);
}
```

## Gotchas

- `view` is a URL **fragment** (`#`), not a query parameter — it must come last in the URL.
- `itinerary_id` and `route_id` are mutually exclusive. If both are set, `itinerary_id` takes priority.
- `with_profile_analysis` requires `with_profile_elevation` to be enabled.
- `with_navigation_control` is disabled when `with_interaction_control` is disabled.
- Safety rules are hard caps — a URL parameter cannot override a safety rule set to false.
- postMessage fields use **camelCase** (e.g., `withCollectionRoutes`), URL parameters use **snake_case** (e.g., `with_collection_routes`).
- `preferred_language` and `preferred_theme` are locked — users cannot change them. `preferred_unit_*` preferences are editable and persist across all iframes in the session.
- The publishable key needs **both** `embedding` and `tiles` scopes. Missing the `tiles` scope will prevent tile loading.
- Embedding domain must be in the org's `domains` safety rule allowlist.
- Fresh organizations ship with `require_session_token: true`, `zoom_min/max: 7`, and empty `domains`/`boundaries`/`with_overlays` — embedding is effectively disabled until the org's safety rules are opened up.
- `with_flyover_control` enables a cinematic camera tour *and* a video export path — video export can pull many tiles; treat it like overlays when deciding whether to enable it.
