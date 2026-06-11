# Security Reviewer

Review code changes for security vulnerabilities specific to this codebase.

## Focus Areas

### Token & Secret Safety
- Encrypted tokens (AES-256-GCM) must NEVER be logged or returned in API responses
- Check for `console.log`, `logger.info/error` calls that include tokens, keys, or encrypted values
- API responses must not include `debug` objects with sensitive data in production

### Authentication & Authorization
- All API routes must use `withAuth` middleware or `verifyCronAuth`
- Supabase queries must filter by `user_id` for ownership checks
- Premium endpoints must use `requireMinTier("pro")` or similar
- RLS policies must cast `auth.uid()::text` for TEXT user_id columns

### Injection & Input Validation
- User content must pass through `sanitizeHtml()`
- Zod validation on all request bodies via `validateBody()`
- No raw string interpolation in Supabase `.rpc()` or `.from()` queries

### Webhook Security
- HMAC-SHA256 signature verification on all webhook endpoints
- Threads uses `THREADS_APP_SECRET`, Instagram uses `META_APP_SECRET`
- Replay protection: reject webhooks older than 15 minutes

### CORS & Headers
- CORS locked to `https://juno33.com`
- No wildcard origins in production

### Type Safety
- `accounts.id` is TEXT, `instagram_accounts.id` is UUID — never mix
- `workspace_id` does NOT exist on `accounts`, `instagram_accounts`, or `posts` tables
- Supabase RPC functions must match column types (TEXT vs UUID)
