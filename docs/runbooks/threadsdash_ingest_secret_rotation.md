# ThreadsDashboard Ingest Secret Rotation

Creator OS exports Campaign Factory drafts to the external ThreadsDashboard
ingest endpoint. ThreadsDashboard accepts a current secret plus temporary
previous/extra secrets; Creator OS sends one active write secret.

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
5. Run a Campaign Factory draft export dry run, then one draft ingest smoke test.
6. Remove the old value from ThreadsDashboard previous/extra secret variables
   after the smoke test and one normal export window pass.

Do not rotate by changing Creator OS first; that creates an ingest outage until
ThreadsDashboard accepts the new value.

## Verification

- Invalid secrets return `CAMPAIGN_FACTORY_INGEST_UNAUTHORIZED`.
- Current and previous secrets are accepted during the rotation window.
- Creator OS exports still target `/api/campaign-factory/drafts/ingest`.
