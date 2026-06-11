# Envelope encryption — rollout plan

**Status (2026-04-18):** Phase 0 shipped. Helper + tests live; no call sites wired.
Author: Claude, 2026-04-18
Depends on (Phase 0.5+): AWS KMS key provisioned, IAM role/attached policy, runtime credentials wired to Vercel env.

## Shipped in Phase 0

- `api/_lib/envelope.ts` — `encryptEnvelope(plaintext, kms)` / `decryptEnvelope(wrapped, kms)` / `isEnvelope(s)` / `_resetDekCacheForTests()`.
- `KmsClient` interface as the testable seam (real AWS SDK binding deferred to Phase 1 to avoid pulling ~5 MB of `@aws-sdk/client-kms` into the graph before it's used).
- SHA-256-keyed DEK cache with TTL, cap of 500 entries, configurable via `ENVELOPE_DEK_CACHE_TTL_MS` (default 60 s).
- Wire format: `v3:<kek_version>:<base64(blob)>:<base64(iv)>:<base64(tag)>:<base64(payload)>`.
- Tamper resistance via GCM auth tag — both flipped payload bytes and flipped IV bytes reject.
- 17 tests in `tests/unit/envelope.test.ts` (round-trip, wire format, cache hit survives KMS outage, tamper, input validation). All green.

Nothing in the app imports `envelope.ts` yet. Flat AES-256-GCM (`api/_lib/encryption.ts`) remains authoritative for every OAuth token write.

## Why

Current flat AES-256-GCM (`api/_lib/encryption.ts`) derives a per-row key from `ENCRYPTION_KEY` + per-row salt via PBKDF2 (v2 = 600k iters). Strong, but:

- Every OAuth token on prod is protected by a **single long-lived secret**. Leak it once and every historical token is recoverable.
- No key rotation story. Rotating `ENCRYPTION_KEY` today means re-encrypting every token row in lockstep with an atomic secret flip — unsafe at prod volume.
- No audit trail. We can't prove "token X was decrypted at time Y by principal Z" for SOC 2.
- Compliance (P0 #2): envelope + KMS is table stakes for Type II.

Envelope encryption fixes all three: rotation is a key-version bump (old KEKs decrypt old DEKs), the master key lives in KMS (never exits), and KMS CloudTrail gives per-decrypt audit.

## Target shape

- **KEK** (key-encryption-key): AWS KMS CMK. Never leaves KMS. Versioned — rotation = new KEK version, old KEKs stay live to decrypt old rows.
- **DEK** (data-encryption-key): 256-bit random AES key, generated per row by `kms.GenerateDataKey`. KMS returns `{ Plaintext, CiphertextBlob }`. We encrypt the row with `Plaintext`, store `CiphertextBlob` alongside. Plaintext DEK is never persisted — lives in memory for the single request.
- **Row layout**: `v3:<kek_version>:<base64(ciphertext_blob)>:<base64(iv)>:<base64(tag)>:<base64(payload)>`
  - `ciphertext_blob` is the KMS-wrapped DEK
  - IV/tag/payload are AES-256-GCM output as today

On read: split the string → call `kms.Decrypt({ CiphertextBlob })` → get plaintext DEK → AES-GCM decrypt payload → zero the DEK buffer.

On write: call `kms.GenerateDataKey` → encrypt payload with plaintext DEK → persist wrapped DEK + ciphertext → drop plaintext DEK.

## Migration strategy — shadow-write first, never break OAuth

The risk is re-encrypting a token incorrectly and losing the ability to refresh it. Mitigation: additive columns, dual-decrypt on read, lazy re-encrypt, never block the request path on KMS availability.

### Phase 0 — scaffolding (no user impact) — ✅ shipped
- [done] Write `api/_lib/envelope.ts` with `encryptEnvelope` + `decryptEnvelope` + DEK cache (keyed by SHA-256 of the ciphertext blob).
- [done] Unit tests with mocked KMS.
- [deferred to 0.5] Provision KMS CMK, alias `alias/juno33-token-kek`.
- [deferred to 0.5] IAM: `kms:Encrypt`, `kms:Decrypt`, `kms:GenerateDataKey` for the Vercel runtime role.
- [deferred to 0.5] Env vars: `AWS_KMS_KEY_ID`, `AWS_REGION`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` (or OIDC federation if we wire it).
- [deferred to 0.5] Add `@aws-sdk/client-kms` to dependencies and bind a `createAwsKmsClient()` that satisfies `KmsClient`.

Phase 0.5 is ops-gated — requires AWS account access. Until then, the helper is testable with any `KmsClient`-shaped mock.

### Phase 1 — additive schema (no reads yet)
Single migration: `20260418000000_envelope_encryption.sql`
```sql
ALTER TABLE user_accounts
  ADD COLUMN IF NOT EXISTS threads_token_wrapped TEXT,
  ADD COLUMN IF NOT EXISTS refresh_token_wrapped TEXT;
ALTER TABLE ig_accounts
  ADD COLUMN IF NOT EXISTS instagram_token_wrapped TEXT;
-- No NOT NULL. Legacy columns stay authoritative.
```

### Phase 2 — dual-write
Modify every `encrypt(token)` call site to also write the envelope column:
- On write: write **both** legacy `*_encrypted` and new `*_wrapped`. Legacy stays authoritative for reads.
- On read: read legacy. If legacy missing but wrapped present (won't happen yet, future-proof), decrypt wrapped.
- Observability: count rows with `wrapped IS NOT NULL AND encrypted IS NOT NULL` daily. Expect it to climb with each token refresh.

Touch points (from `Grep` above):
- `api/_lib/tokenAccess.ts` (primary write path)
- `api/_lib/cron/token-refresh.ts` (lazy refresh rotates tokens)
- `api/auth/threads/` + `api/auth/instagram/` OAuth callbacks

### Phase 3 — backfill (async, rate-limited)
New cron: `api/cron/envelope-backfill.ts`, daily 04:00 UTC.
- Pulls `SELECT id, threads_access_token_encrypted FROM user_accounts WHERE threads_token_wrapped IS NULL LIMIT 500`
- For each: `decrypt(legacy)` → `encryptEnvelope(plain)` → `UPDATE ... SET threads_token_wrapped = $1`
- Rate limit: 500/day keeps KMS cost under $0.50/day at current scale (~80 accounts, probably done in one run)
- Idempotent — re-running is a no-op
- Kill switch: env flag `ENVELOPE_BACKFILL_ENABLED`, default `false` initially

### Phase 4 — flip reads
Once `wrapped IS NOT NULL` count == `encrypted IS NOT NULL` count for ≥7 consecutive days:
- Change read path: prefer `wrapped`, fall back to `encrypted` (still dual-decrypt)
- Stay here for 14 days. Any read that falls back gets logged — should be zero.

### Phase 5 — cutover
- Stop dual-writing. New writes only populate `wrapped`.
- Keep dual-read for one more cycle.

### Phase 6 — drop legacy
Migration: `ALTER TABLE ... DROP COLUMN *_encrypted`. Remove PBKDF2 code from `encryption.ts` (or keep as `decryptLegacy` for one more release, then delete).

## Rollout order / ship gates

| Phase | Gate to advance |
|---|---|
| 0 → 1 | Unit tests green, KMS integration test against dev key, helper code reviewed |
| 1 → 2 | Migration applied to prod, no schema breakage in CI |
| 2 → 3 | 48hr of dual-writes showing new rows getting both columns populated, zero decrypt failures in Sentry |
| 3 → 4 | Backfill complete — `COUNT(wrapped IS NULL)` = 0 for ≥3 days |
| 4 → 5 | 14 days of wrapped-read with zero fallbacks logged |
| 5 → 6 | 30 days of wrapped-only writes, zero incidents |

End-to-end estimate: **6 weeks** calendar, assuming 2 active deploys + observability windows. Don't compress this.

## Risks + mitigations

1. **KMS outage breaks OAuth**. Mitigation: (a) DEK cache keeps recently-used tokens decryptable for the cache TTL window, (b) background task warmer could proactively refresh hot DEKs, (c) Phase 4+ read path falls back to legacy until cutover.
2. **Cost blowup from per-request KMS calls**. Mitigation: DEK cache is essential — reuse the existing pattern from `encryption.ts`. Target: <10% of requests hit KMS. At 1M decrypts/month that's ~$3 (KMS is $0.03/10k). Cheap.
3. **IAM misconfiguration silently breaks writes**. Mitigation: health-check endpoint `GET /api/_health/kms` that does a roundtrip and reports latency + success. Wire to uptime pinger.
4. **Key deletion**. KMS has a 7-day delete window by default; set it to 30 days. Tag the CMK so ops can't accidentally schedule deletion. Backup via KMS multi-region key if budget permits.
5. **Mixed state during backfill**. Mitigation: dual-write for the whole backfill period. A row is never in an "only old" or "only new" state when written; backfill moves it from "only old" to "both".

## What this does NOT ship

- Key rotation automation. Phase 0–6 gets us to envelope. Rotation is a Phase 7 follow-up: add `kek_version` column, schedule KMS key-rotation, lazy re-wrap on read.
- Per-tenant KEKs. Single KMS CMK is correct for current scale. Per-tenant only matters for enterprise tier.
- HSM. KMS is FIPS 140-2 Level 2 via CloudHSM-backed keys if we need it — not needed yet.

## Open questions before implementation

1. **AWS vs Supabase Vault vs GCP KMS?** AWS KMS is the default for SOC 2 familiarity and CloudTrail. Supabase Vault is tempting for closeness to the DB but it's pre-GA and we don't want to be an early adopter for the most critical path. Pick AWS.
2. **OIDC federation vs long-lived access keys?** OIDC (via Vercel's OIDC provider) is better — no stored secrets to rotate. Check Vercel docs for current support before implementation.
3. **Region?** `us-east-1` matches current Supabase region, minimizes latency.
4. **Backup / DR?** KMS multi-region keys add ~$1/mo. Decide during Phase 0.

## Definition of done

- Every new OAuth token write produces an envelope-encrypted payload
- Every read path auto-picks the right format
- Backfill has moved all historical tokens to envelope
- CloudTrail shows the KMS decrypt audit log
- Legacy columns and PBKDF2 code are removed
- Runbook exists for KMS key rotation + for "KMS is down, what do we do"
