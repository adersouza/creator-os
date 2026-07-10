# ThreadsDashboard Ingest Secret Rotation

Creator OS exports Campaign Factory drafts to the external ThreadsDashboard
ingest endpoint. The request body, Unix timestamp, and one-time nonce are signed
with HMAC-SHA256. The raw key is never sent. ThreadsDashboard accepts a current
key plus temporary previous/extra keys during rotation; Creator OS signs with
one active key.

Use at least 32 cryptographically random bytes for every key. Keep the key in a
credential store; never put it in a URL, log, error, or request body.

## One-Time HMAC Protocol Cutover

The legacy raw-header sender and HMAC-only receiver are not wire-compatible.
For the first rollout, pause Campaign Factory draft exports, apply the
ThreadsDashboard nonce-replay migration and deploy its HMAC receiver, then
deploy or restart Creator OS with the HMAC sender using the same key. Run one
signed smoke ingest before resuming exports. Do not deploy either protocol half
alone while exports are active.

## Environment Variables

Creator OS:
- `THREADSDASH_CAMPAIGN_FACTORY_INGEST_URL`
- `CAMPAIGN_FACTORY_INGEST_SECRET`

ThreadsDashboard:
- `CAMPAIGN_FACTORY_INGEST_SECRET`
- `CAMPAIGN_FACTORY_INGEST_SECRET_PREVIOUS`
- `CAMPAIGN_FACTORY_INGEST_SECRET_EXTRA`
- `CAMPAIGN_FACTORY_INGEST_SECRETS`

## Rotation Order

1. Put the current ThreadsDashboard secret into
   `CAMPAIGN_FACTORY_INGEST_SECRET_PREVIOUS`.
2. Put the new secret into ThreadsDashboard `CAMPAIGN_FACTORY_INGEST_SECRET`.
3. Deploy or restart ThreadsDashboard.
4. Update Creator OS `CAMPAIGN_FACTORY_INGEST_SECRET` to the new value.
5. Run a Campaign Factory draft export dry run and one signed draft ingest
   smoke test.
6. Remove the old value from ThreadsDashboard previous/extra secret variables
   after the smoke test and one normal export window pass.

Do not rotate by changing Creator OS first; that creates an ingest outage until
ThreadsDashboard accepts the new value.

## Verification

- Invalid signatures, stale timestamps, and malformed nonces return the same
  `CAMPAIGN_FACTORY_INGEST_UNAUTHORIZED` response without exposing why.
- Current and previous keys validate signatures during the rotation window.
- A repeated nonce returns `CAMPAIGN_FACTORY_INGEST_REPLAYED` and performs no
  draft write.
- Creator OS exports still target `/api/campaign-factory/drafts/ingest`.
- Signed writes send `X-Campaign-Factory-Signature`,
  `X-Campaign-Factory-Timestamp`, and `X-Campaign-Factory-Nonce`; they never send
  the HMAC key. Cross-host redirects are refused before authenticated headers
  can be forwarded.
