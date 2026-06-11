# Critical Patterns

## Token Encryption
```typescript
import * as crypto from "crypto";  // Use * as for Vercel
// NEVER decrypt on frontend - only in API routes
```

## Lazy Imports (API routes)
```typescript
const { getPostMetrics } = await import("./_lib/threadsApi");
```

## accountId === "ALL" — Workspace-Scoped Resolver
```typescript
// Backend: use the workspace-scoped resolver (api/_lib/workspaceAccounts.ts)
import { getAccountIdsForContext } from './_lib/workspaceAccounts';
const accountIds = await getAccountIdsForContext(userId, workspaceId, platform);

// Frontend: guard with early return when no specific account selected
if (!accountId || accountId === "ALL") {
  setData(null);
  return;
}
```

## Zod Schemas (API routes)
Two options:
```typescript
// Option A: named helpers — import zEnum/zLiteral/zUnknown/zRecord from zodCompat,
// use stock `z` for everything else.
import { z } from 'zod';
import { zEnum } from './_lib/zodCompat';
const S = z.object({ platform: zEnum(['threads', 'instagram']) });

// Option B: drop-in `z` namespace — proxies to stock Zod with the 4 broken
// methods shimmed. No need to think about which methods are broken.
import { z } from './_lib/zodCompat';
const S = z.object({ platform: z.enum(['threads', 'instagram']) });
```
The `(z as any)` workaround is banned — `npm run compat:check` catches it.

## Meta API Retry
```typescript
import { withRetry, isRetryableMetaError } from './_lib/retryUtils';
const data = await withRetry(() => fetchFromMeta(url), { isRetryable: isRetryableMetaError });
```

## Standardized API Responses
```typescript
import { apiError, apiSuccess, getAuthUserOrError, verifyCronAuth } from './_lib/apiResponse';
```

## AI Streaming
Three AI endpoints stream tokens via SSE: `copilot`, `investigate`, `nl-query`.
```typescript
// Backend: stream with server-sent events
import { streamGemini } from './_lib/geminiStream';
await streamGemini(res, prompt, { temperature: 0.4 });

// Frontend: consume via useEventSource
import { useAiStream } from '@/hooks/useAiStream';
const { text, done, error } = useAiStream('/api/ai?action=investigate', payload);
```

## Supabase null-safe queries
```typescript
// Frontend:
import { neqOrNull } from '@/lib/supabaseSafe';
// Backend:
import { neqOrNull } from './_lib/supabaseSafe';

// INSTEAD of: .neq('col', 'val')  — loses NULL rows
query = neqOrNull(query, 'col', 'val');
```
`.neq()` in PostgREST produces `col <> 'val'` which evaluates NULL for NULL rows, dropping them. `neqOrNull` emits `.or("col.is.null,col.neq.val")`. Also available: `neqStrict` (excludes NULL explicitly) and `eqOrNull` (match value OR NULL).

## Backend DB access
Authenticated user CRUD should use `withAuthDb()` from `api/_lib/middleware.ts`
and `context.userDb`, which is created with the request Bearer token and respects
RLS. Use `context.adminDb` / `context.adminDbAny` only for explicit privileged
branches such as cron, webhooks, OAuth callbacks, billing/webhook processing,
token refresh, publishing workers, admin repair, and background jobs. Do not
import `getSupabaseAny()` directly in newly migrated user routes.

## Social platform primitive
Don't write `platform === 'threads' ? X : Y` ternaries for values that vary by platform. Use the primitive:
```typescript
// Frontend:
import { maxBodyChars, dailyPublishLimit, labelFor, PLATFORMS } from '@/lib/socialPlatform';
// Backend:
import { maxBodyChars, dailyPublishLimit } from './_lib/socialPlatform';

maxBodyChars('threads')      // 500
dailyPublishLimit('instagram') // 25
labelFor('threads')          // "Threads"
```
The primitive tables max body length, daily limits, optimal caption ranges, hashtag count, account table name, and ID column type. Add to `PLATFORM` spec if you find yourself adding a new ternary.

## AI streaming (SSE)
Three AI endpoints support `?stream=true`: `copilot`, `investigate`. The NL-query endpoint returns JSON directly (no benefit from streaming). Shared helper at `api/_lib/geminiStream.ts`:
```typescript
import { streamGemini, writeSseHeaders, sendDone, sendError } from './_lib/geminiStream';

writeSseHeaders(res);
const result = await streamGemini(res, { apiKey, model, prompt, maxOutputTokens, temperature });
sendDone(res, { /* structured payload */ });
```
Frontend consumers read via `fetch` + `ReadableStream` (EventSource can't send POST bodies or auth headers) — see `src/hooks/useInvestigate.ts` for the consumer pattern.

## Shared Publish Helpers
```typescript
// Media UUID → URL resolution (used by all publish paths)
import { resolveMediaUrls } from './handlers/posts/shared';
const { urls, items } = await resolveMediaUrls(mediaIds, userId);

// Engagement sync at 1h/6h/24h after publish (used by all publish paths)
import { schedulePostPublishSyncs } from './qstashSchedule';
schedulePostPublishSyncs(postId, accountId, userId, "instagram", "immediate");
```

## Auto-Attach Media
`bulk_schedule_groups` auto-attaches media from group library when `mediaIds` omitted. IG always gets media. Threads ~30% (configurable via `media_attachment_chance` on `auto_post_group_config`). Disable with `autoAttachMedia: false`.

## Card Section Headers
```typescript
import { SectionHeader } from "@/src/components/ui/SectionHeader";
<SectionHeader icon={<Users className="h-4 w-4" />}>Audience Activity</SectionHeader>
// Standard: text-xs font-semibold uppercase tracking-[0.25em] text-foreground/50
```
