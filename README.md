# Mountaya Agent Skills

Reusable skills for AI agents to integrate with [Mountaya](https://mountaya.com)
products:
- [Outdoor Intelligence](https://mountaya.com/en/outdoor-intelligence) → `mountaya-data-api`
- [Outdoor Tiles](https://mountaya.com/en/outdoor-tiles) → `mountaya-tiles-api`
- [Map Embedding](https://mountaya.com/en/map-studio#embedding) → `mountaya-embedding`

Follows the [Agent Skills Open Standard](https://agentskills.io) and works with
Claude Code, Cursor, GitHub Copilot, Windsurf, Gemini CLI, and other compatible
tools.

## Install

### Via skills CLI (recommended)

```bash
npx skills add mountayaapp/agent-skills
```

Or install specific skills:

```bash
npx skills add mountayaapp/agent-skills --skill mountaya-auth
npx skills add mountayaapp/agent-skills --skill mountaya-data-api
npx skills add mountayaapp/agent-skills --skill mountaya-tiles-api
npx skills add mountayaapp/agent-skills --skill mountaya-embedding
```

> **Note:** `mountaya-data-api` depends on `mountaya-auth` for session-token
> creation. If you install `mountaya-data-api` on its own, install `mountaya-auth`
> alongside it.

### Manual installation

#### Claude Code

```bash
git clone https://github.com/mountayaapp/agent-skills.git
cp -r agent-skills/skills/mountaya-auth ~/.claude/skills/
cp -r agent-skills/skills/mountaya-data-api ~/.claude/skills/
cp -r agent-skills/skills/mountaya-tiles-api ~/.claude/skills/
cp -r agent-skills/skills/mountaya-embedding ~/.claude/skills/
```

#### Other tools

Copy the skill directories into your tool's skills folder.

## Setup

Set your Mountaya API keys as environment variables so agents can authenticate:

```bash
export MOUNTAYA_PUBLISHABLE_KEY="pk_..."
export MOUNTAYA_SECRET_KEY="sk_..."
```

Create keys in your [organization's settings ](https://app.mountaya.com/organizations?tab=api_keys).
Enable the scopes your products need: `data` for Outdoor Intelligence,
`tiles` for Outdoor Tiles, `embedding` + `tiles` for Map Embedding.

- **Publishable key** (`pk_`): Identifies your organization. Required for all
  products.
- **Secret key** (`sk_`): Creates session tokens for the Data API. Keep
  server-side only.

Without these variables:

- **Script-backed skills** (`mountaya-auth`, `mountaya-data-api`) exit with a
  remediation message pointing at the API settings page.
- **No-script skills** (`mountaya-tiles-api`, `mountaya-embedding`) emit example
  code with a `pk_...` placeholder and ask you to configure the key before
  running it.

## Skills

| Skill | Product | Description |
|-------|---------|-------------|
| `mountaya-auth` | — | API authentication (publishable keys, session tokens, rate limits). Prerequisite for the others. |
| `mountaya-data-api` | Outdoor Intelligence (Data API) | GraphQL routing and geospatial analysis (directions, suggestions, matrix, isochrones). Requires `mountaya-auth`. |
| `mountaya-tiles-api` | Outdoor Tiles (Tile API) | Tile rendering with MapLibre GL JS (overlays, routes, collections). |
| `mountaya-embedding` | Map Embedding (Embedded Studio) | Iframe integration (properties, postMessage events, safety rules). |

## Support

Found a bug or have feedback? Open an issue at
[github.com/mountayaapp/agent-skills/issues](https://github.com/mountayaapp/agent-skills/issues).

## License

Repository licensed under the [MIT License](./LICENSE.md).
