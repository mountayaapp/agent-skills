---
name: mountaya-auth
description: >-
  Mountaya API authentication with publishable keys, secret keys,
  session tokens, and rate limiting. Use when setting up API access for
  Outdoor Intelligence (Data API), Outdoor Tiles (Tile API), or Map
  Embedding (Embedded Studio). Prerequisite for the mountaya-data-api,
  mountaya-tiles-api, and mountaya-embedding skills.
metadata:
  author: mountaya
  version: "1.0"
compatibility: >-
  Requires MOUNTAYA_PUBLISHABLE_KEY and MOUNTAYA_SECRET_KEY environment
  variables. Requires Python 3. See Prerequisites section.
---

# Mountaya Authentication

Authentication patterns for the Mountaya Data API, the Tile API, and Embedded Studio.

## Agent usage policy

**These rules are mandatory. They exist to protect the user's organization usage and data.**

1. **Minimize API calls.** Every call counts against the organization's quota. Reuse a single session token across all queries in one task (5-minute TTL — the `session.py` script caches it on disk), cache schema introspection within a task, batch requests where the API supports it, request only the fields you need, and never re-fetch data you already have.

2. **Ask before enabling usage-heavy follow-ups.** Any enrichment resource — weather overlays, POI overlays, time/distance matrices, isochrones, geometry analysis — must be presented as an opt-in follow-up, never kicked off automatically. This applies to every Mountaya product.

3. **The only allowed write against `MOUNTAYA_SESSION_BASE_URL` is `POST /v1/sessions`.** That endpoint (used by `scripts/session.py` to mint session tokens) is the single permitted mutation. No other POST/PUT/PATCH/DELETE against the internal session API.

4. **Never create, update, or delete Mountaya resources.** Agents MUST NOT create, modify, or delete routes, itineraries, collections, drawings, or any other user-owned resource through any Mountaya API. All skills are strictly read-only aside from session token creation.

## Prerequisites

Set the following environment variables before using Mountaya skills:

| Variable | Value | Purpose |
|----------|-------|---------|
| `MOUNTAYA_PUBLISHABLE_KEY` | Your publishable key (`pk_...`) | Identifies your organization in API requests |
| `MOUNTAYA_SECRET_KEY` | Your secret key (`sk_...`) | Creates session tokens for authenticated access |

Create keys at [Mountaya API Settings](https://app.mountaya.com/settings/api-keys). The publishable key must have the appropriate scopes enabled for the products you use.

If the environment variables are not set, ask the user to configure them before proceeding.

> **Security**: Store keys in environment variables or `.env` files. Never commit keys to source control. Add `.env` to your `.gitignore`.

## Key types

### Publishable keys (`pk_`)

Client-side keys, safe to embed in frontend code. Scoped and rate-limited.

- **Scopes** control which products a key can access:
  - `data` → Data API (GraphQL)
  - `tiles` → Tile API
  - `embedding` + `tiles` → Embedded Studio (needs both scopes)
- A key must have the matching scope(s) for the product it accesses.
- Include in every API request: `X-API-Key: pk_...` header.
- For embedded iframes: `publishable_key=pk_...` query parameter (not header).
- Safe to expose in browser/mobile code.

### Secret keys (`sk_`)

Server-side keys. **Never expose to clients.**

- Used exclusively to create session tokens via `POST /v1/sessions`.
- Include as: `X-API-Key: sk_...` in the session creation request.

**Best practices:**
- Store in environment variables, never in source code.
- Rotate regularly. Revoke immediately if compromised.
- Only use server-side (backend, serverless functions) — never in browser or mobile code.
- Each secret key is scoped to one organization.

## Session tokens (`sess_`)

Short-lived, HMAC-signed tokens with a **5-minute TTL**. They prevent key theft and replay attacks by requiring a server-to-server exchange that only your backend can perform.

### Creating a session token

Exchange a secret key + publishable key via `POST /v1/sessions`:

```bash
curl -X POST https://internal.mountaya.com/v1/sessions \
  -H "X-API-Key: sk_..." \
  -H "Content-Type: application/json" \
  -d '{"publishable_key": "pk_..."}'
```

Response:
```json
{
  "status": 201,
  "data": {
    "token": "sess_eyJvcmdhbml6YXRpb25faWQiOi...",
    "expires_at": "2026-03-03T12:05:00Z"
  }
}
```

### Using session tokens

- **Data API**: **Always required.** Every GraphQL request must include a valid session token, regardless of the `require_session_token` safety rule.
- **Tile API**: **Optional.** Only required when the organization's `require_session_token` safety rule is enabled.
- **Embedded Studio**: **Optional.** Only required when the organization's `require_session_token` safety rule is enabled. Passed as `session_token` query parameter, not header.

> Fresh organizations ship with `require_session_token: true`. Unless the Mountaya team has explicitly relaxed it for the org, treat the session token as mandatory for the Tile API and Embedded Studio too, and always mint one before issuing requests.

### Token lifecycle

- Tokens are bound to one publishable key and one organization — cannot be reused across keys.
- Expire after **5 minutes**. Refresh every **4 minutes** for a 1-minute safety margin.

```typescript
const REFRESH_INTERVAL_MS = 4 * 60 * 1000;

let sessionToken: string | null = null;

async function refreshToken() {
  const response = await fetch("https://internal.mountaya.com/v1/sessions", {
    method: "POST",
    headers: {
      "X-API-Key": process.env.MOUNTAYA_SECRET_KEY!,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      publishable_key: process.env.MOUNTAYA_PUBLISHABLE_KEY!,
    }),
  });

  const body = await response.json();
  sessionToken = body.data.token;
}

// Fetch immediately, then refresh every 4 minutes.
await refreshToken();
setInterval(refreshToken, REFRESH_INTERVAL_MS);
```

For embedded iframes, update the iframe `src` when the token is refreshed:

```javascript
function updateIframeToken(newToken) {
  const iframe = document.getElementById("mountaya-embed");
  const url = new URL(iframe.src);
  url.searchParams.set("session_token", newToken);
  iframe.src = url.toString();
}
```

## Authentication summary

| | Data API | Tile API | Embedded Studio |
|---|----------|----------|-----------------|
| **Publishable key delivery** | `X-API-Key` header | `X-API-Key` header | `publishable_key` query param |
| **Required scope(s)** | `data` | `tiles` | `embedding` + `tiles` |
| **Session token** | Always required | Optional (safety rule) | Optional (safety rule) |
| **Token delivery** | `X-Session-Token` header | `X-Session-Token` header | `session_token` query param |

## Rate limiting

- Per-organization, across all keys.
- Returns HTTP `429 Too Many Requests` when exceeded.
- **Backoff**: retry with waits of `2s`, `4s`, `8s` (exponential, max 4 attempts). If the response includes a `Retry-After` header, honor it instead of the exponential schedule, clamped to `15s`.
- Do **not** retry other 4xx responses (400/401/403 indicate a scope, key, or payload problem that retrying will not fix).
- On 5xx, retry once after 2 s, then fail.

## Scripts

### session.py

Create (or reuse) a session token and print it to stdout. Handles environment variable validation and error reporting.

```bash
python3 scripts/session.py
# stdout: sess_eyJvcmdhbml6YXRpb25fa...

# Force a fresh token, skipping the cache:
python3 scripts/session.py --no-cache
```

Tokens are cached on disk at `~/.cache/mountaya/session-<hash>.json` (override via `MOUNTAYA_CACHE_DIR`) and reused until 1 minute before expiry. The token is printed to stdout with no extra formatting, making it composable with other scripts and subprocesses. Progress and errors are logged to stderr.

This `POST /v1/sessions` call is the **only** mutation any Mountaya skill is allowed to issue against `MOUNTAYA_SESSION_BASE_URL`.

**Environment variables**: `MOUNTAYA_SECRET_KEY` (required), `MOUNTAYA_PUBLISHABLE_KEY` (required), `MOUNTAYA_SESSION_BASE_URL` (optional override), `MOUNTAYA_CACHE_DIR` (optional override).

**Exit codes**: 0 success, 1 missing env vars, 2 token creation failed.

## Gotchas

- Using a scope-mismatched key (e.g., `tiles`-only key for the Data API). Returns **403**.
- Forgetting `X-Session-Token` on Data API requests. Returns **401**.
- Exposing secret keys (`sk_`) in client-side code.
- Not refreshing session tokens before the 5-minute expiry.
- Using a session token created for one publishable key with a different one. Returns **401**.
- For embedding: using `X-API-Key` header instead of `publishable_key` query parameter.
- For embedding: publishable key missing the `tiles` scope (needs both `embedding` + `tiles`).
- For embedding: domain not in the org's `domains` safety rule allowlist.
- Assuming `require_session_token` is `false` by default. Fresh orgs ship with it `true`, so omitting the session token on Tile API or Embedded Studio requests will 401 until the org explicitly disables the rule.
- Hitting `400` on Tile API / embedded tile requests at zoom levels that "should work" — fresh-org `zoom_min/max` both default to `7`; the org must widen the range before other zooms are served.
