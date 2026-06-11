# MCP Server Tracker

## Overview
Custom MCP server (`mcp-server/`) giving Claude full control over ThreadsDashboard (juno33.com).
- **154 tools** across 24 domain modules
- **Two transports**: Stdio (local) + HTTP/SSE (remote)
- **Auth**: Supabase JWT or `juno_ak_*` API key via Bearer header

## HTTP Endpoint (Live)
- **URL**: `https://juno33.com/api/mcp`
- **Transport**: MCP Streamable HTTP (stateless, SSE responses)
- **Auth**: `Authorization: Bearer <jwt_or_api_key>`
- **Accept header required**: `application/json, text/event-stream`
- **File**: `api/mcp.ts` (Vercel serverless, 60s maxDuration)
- **Concurrency safety**: `AsyncLocalStorage` isolates per-request auth tokens on warm containers
- **CORS**: Open (`*`) for MCP client compatibility
- **Module caching**: Tool modules loaded once per warm container, reused across requests

### Connecting an MCP Client
```json
{
  "mcpServers": {
    "threadsdashboard": {
      "url": "https://juno33.com/api/mcp",
      "headers": {
        "Authorization": "Bearer juno_ak_YOUR_KEY_HERE"
      }
    }
  }
}
```

### Testing with curl
```bash
# Initialize
curl -X POST https://juno33.com/api/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -H "Authorization: Bearer juno_ak_..." \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"test","version":"1.0.0"}}}'

# List tools
curl -X POST https://juno33.com/api/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -H "Authorization: Bearer juno_ak_..." \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}'

# Call a tool
curl -X POST https://juno33.com/api/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -H "Authorization: Bearer juno_ak_..." \
  -d '{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"health_ping","arguments":{}}}'
```

## Architecture Decisions
- **Single server, modular files** — `src/tools/*.ts` split by domain (not multiple MCP servers)
- **Granular tools** — one tool per action, no multi-action `manage_*` tools
- **Structured errors** — `{ ok, data, error }` responses with `isError: true` MCP pattern
- **Destructive safety** — `dryRun` flag on delete/remove tools, defaults to `true`
- **Auth passthrough** — HTTP endpoint uses `AsyncLocalStorage` to pass caller's token through to backend API calls, concurrency-safe on Vercel warm containers
- **Stateless HTTP** — `sessionIdGenerator: undefined` (no session tracking needed, each request is self-contained)

## Tool Modules (24)
| Module | Tools | Description |
|--------|-------|-------------|
| accounts | 6 | list, sync threads/ig, bulk sync, bulk cap status, check subscription |
| posts | 17 | publish, schedule, draft, delete, import, get, evergreen, draft folders, templates |
| media | 4 | upload, random, share folder, refresh URLs |
| ai | 8 | generate, copilot, image gen, vision score, autopsy, growth sim, analytics advisor, feedback |
| analytics | 9 | get analytics, IG insights (2), demographics, recap, quotas (2), growth journal (2) |
| inbox | 10 | unified inbox, reply, IG comments (4), inbox rules (4) |
| competitors | 6 | list, add, remove, bulk remove, analyze, get media |
| autoposter | 7 | health, configs, upsert, toggle, queue, fetch engagement, sync engagement |
| listening | 4 | list, create, update, delete alerts |
| reports | 1 | generate report |
| links | 10 | pages (5), bio links (4), URL shortener |
| team | 2 | invite, stats |
| discovery | 8 | search, trends, inspiration, IG hashtags (3), Threads profile (2) |
| quickwins | 3 | get, dismiss, bulk apply |
| system | 6 | health, dead letters (3), KPIs, ping |
| strategy | — | content strategy CRUD |
| groups | — | account groups CRUD |
| smart-links | — | tracked links with UTM/deep links |
| benchmarks | — | tier benchmarks |
| influencer-collabs | — | collab tracking + ROI |
| referrals | — | referral stats |
| crisis | — | crisis detection |
| branding | — | agency white-label |
| trending-config | — | trending topics config |

## Refactor History

### Phase 1: Modularize + Split Tools — DONE
### Phase 2: Structured Error Handling — DONE
### Phase 3: Destructive Action Safety — DONE
### Phase 4: Live Testing & Bug Fixes — DONE (2026-03-06)
### Phase 5: API Key Auth — DONE (2026-03-08)
- `api_keys` table with SHA-256 hashed keys (`juno_ak_*` prefix)
- Validated in `api/mcp.ts` and `api/_lib/withApiKey.ts`
- JWT fallback for backward compatibility

### Phase 6: HTTP/SSE Transport — DONE (2026-03-12)
- `api/mcp.ts` — Vercel serverless endpoint
- `@modelcontextprotocol/sdk` StreamableHTTPServerTransport (stateless)
- `AsyncLocalStorage` for concurrency-safe auth isolation
- CORS headers for `/api/mcp` in `vercel.json`
- Build pipeline: `cd mcp-server && npm ci && npm run build && cd .. && npm run build`
- All 4 tests passing: no-auth 401, initialize, tools/list (151 tools), tools/call health_ping

### Phase 7: Bulk Operations — DONE (2026-03-12)
- `bulk_sync_accounts` — QStash fan-out sync for group or explicit IDs (200 cap), `POST /api/analytics?action=bulk-sync`
- `bulk_cap_status` — check daily publish caps for group/account list (200 cap), `POST /api/accounts/bulk-cap-status`
- `bulk_remove_competitors` — remove multiple competitors with dryRun (100 cap), `POST /api/competitors?action=bulk-remove`
- Also backfilled missing single `remove` handler (`POST /api/competitors?action=remove`)

## Files
- `mcp-server/src/index.ts` — server bootstrap (imports 24 modules, stdio transport)
- `mcp-server/src/helpers.ts` — api(), respond(), error(), success(), dryRunResponse(), runWithAuthToken(), getAuthToken()
- `mcp-server/src/tools/*.ts` — 24 domain modules (154 tools total)
- `api/mcp.ts` — HTTP/SSE endpoint (Vercel serverless)
- `.mcp.json` — Claude Code MCP registration (stdio)
- `vercel.json` — CORS + maxDuration config for `/api/mcp`

## Key Patterns
- Critical: most endpoints read `req.query.action`, only `/links.ts` + `/admin/dead-letters.ts` read from body
- Column gotcha: `accounts.followers_count` (plural) vs `instagram_accounts.follower_count` (singular)
- JWT fallback in `withApiKey.ts` allows v1 endpoints to accept Bearer JWTs (not just API keys)
