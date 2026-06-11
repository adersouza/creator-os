# Key Gotchas

| Error | Fix |
|-------|-----|
| `FUNCTION_INVOCATION_FAILED` | Use lazy imports, `import * as crypto` |
| Zod `.enum()`, `.record()` type errors on Vercel | Import from `./_lib/zod` shim (not `'zod'` directly). The shim types match Vercel's bundled TS 5.9. |
| `column accounts.voice_profile does not exist` | It's on `account_groups` |
| `operator does not exist: text = uuid` | Core IDs are TEXT, instagram_accounts is UUID |
| Stale chunks after deploy | `lazyWithRetry()` handles auto-reload |
| Circular RLS recursion | workspace tables use SECURITY DEFINER helpers |
| accountId "ALL" causing 404s | Guard with `accountId === "ALL"` check |
| DEV guards blocking sync | Removed from analytics, competitor, media services — proxy handles dev |
| `account_analytics.date` off by one | Dates are UTC — `toISOString().split("T")[0]`. Not user-local. |
| Supabase `.neq()` excludes NULLs | Use `neqOrNull(query, col, val)` from `@/src/lib/supabase-safe` — emits `.or("col.is.null,col.neq.val")` |
| Scheduled posts not publishing | Check `approval_status` — must be NULL-safe. Check `is_active` on joined account. |
| Meta `OAuthException` killing accounts | `"An unknown error has occurred (code=1, type=OAuthException)"` is Meta's **transient 500**, NOT a dead token. All publish paths exclude this before flagging `needs_reauth`. See `queue.ts:isOAuthError()` for the canonical check. |
| Lazy route import points at non-existent file | `scripts/check-lazy-routes.ts` catches this at CI — run via `npm run compat:check` |

## Platform-specific Notes

### Webhooks
- Threads: `THREADS_APP_SECRET` (NOT `META_APP_SECRET`). IG: 8 fields, per-account config.
- Dedup: `UNIQUE (event_type, user_id, payload_id)`. HMAC-SHA256 verification.
- Async-first only (200 → QStash nudge → webhook-processor cron).

### Cross-browser
- **`randomUUID()`**: Always import from `@/src/lib/uuid` — never call `crypto.randomUUID()` directly.
- **`Array.at(-n)`**: Banned. Use `arr[arr.length - n]` instead.
- **Enforcement**: `npm run compat:check`.
- **Targets**: Chrome 92+, Firefox 95+, Safari 15.2+, Edge 92+.
- **`@theme inline`**: Tailwind v4 — valid in this project.

### Meta API versions
- Threads = v1.0, Instagram/Facebook = v25.0

### Tailwind & tokens
- Tokens live primarily in `src/index.css` via Tailwind v4 `@theme`.
- There is no `tailwind.config.js`; use `color-mix(in srgb, ...)` or Tailwind v4 alpha helpers for opacity.
- ~2,400 `var(--td-*)` usages work correctly. CSS definition files are bridge layer — do NOT remove.
