# Supabase Migration & Schema Guide

## Current Status (May 2026)
The database schema has reached a high level of complexity with 400+ incremental migration files. The repo still treats `supabase/schema.sql` as the intended baseline, but remote migration history must also be kept in lockstep with the committed migration files.

Recent staging investigation found migration drift:

- Production had 404 rows in `supabase_migrations.schema_migrations`.
- The repo had 416 local migration files before repair.
- The staging branch project had only 33 migration rows and three staging-only MCP patch migrations.
- Several production migrations had the same logical names as local files but different versions/timestamps.

The migration repair branch reconciles the first drift batch by matching local filenames to production versions and restoring production-history marker files where later local migrations had consolidated the SQL. Until the full migration chain is validated on an empty database, do not treat a passing preview smoke test as proof that a clean Supabase branch can be recreated from migrations.

### 1. The Source of Truth
The file `supabase/schema.sql` is the **authoritative reference** for the entire database structure. 
- All table definitions, RLS policies, and RPC functions must be reflected here.
- When onboarding a new developer or setting up a fresh environment, this file should be used to initialize the database.
- Before creating or rebasing Supabase branches, verify that the local migration files also match the remote migration history.

### 2. Migration Strategy: "The Periodic Squash"
To prevent "migration rot" (where dozens of files apply tiny changes), we periodically squash incremental migrations.

- **Incremental Phase:** Use standard `YYYYMMDD_name.sql` files for active development.
- **Squash Phase:** Once a feature set is stable, incorporate the changes into `schema.sql` and move the incremental files into an `archive/` folder (or delete them if they are fully captured).

### 3. Type Safety
We use the Supabase CLI to keep TypeScript types in sync with the production
schema.
- **Command:** `npm run types:db`
- **Source:** Production Supabase project `apsrvwxfoomhtswlhczo`
- **Destination:** `src/types/supabase.ts`
- **Rule:** Any schema-affecting migration must refresh and commit this file in
  the same PR.

### 4. Critical Conventions
- **ID Types:** Most core tables (`profiles`, `posts`, `accounts`) use `TEXT` IDs for compatibility with external social APIs. `instagram_accounts` uses `UUID`.
- **User References:** Always use `TEXT REFERENCES profiles(id)`.
- **Search Paths:** All RPC functions must explicitly set `SET search_path = public` for security.
- **RLS:** Every table must have RLS enabled with specific policies for `anon`, `authenticated`, and `service_role`.

### 5. Drift Checks
Run the local duplicate-version check before touching Supabase branches:

```bash
npm run check:migrations
```

Run the replay-safety lint before committing migration SQL:

```bash
npm run lint:migrations
```

The linter scans changed files under `supabase/migrations/**` for clean-replay
hazards. New migrations must not assume production state exists when a clean
branch replays from migration history.

To compare against an exported remote history, save the query result from:

```sql
select version, name
from supabase_migrations.schema_migrations
order by version;
```

Then run:

```bash
npm run check:migrations -- --remote-history=path/to/history.json
```

Remote-only versions or same-version name mismatches mean the repo cannot safely
recreate that remote project from migrations. Local-only versions are acceptable
only when they are newer than the newest remote migration and are intentionally
pending. A local migration version that is older than or equal to the newest
remote version but missing from remote history is a migration-history gap; repair
the Supabase ledger instead of treating it as pending work.

### 6. Clean Replay Rules
Every committed migration must be safe to replay into a fresh Supabase preview
branch. In practice:

- Use `ALTER TABLE IF EXISTS` or `to_regclass()` guards when a historical table
  may not exist.
- Use `DROP POLICY IF EXISTS`; guard `CREATE POLICY` and `ALTER POLICY` with
  `to_regclass()` plus `pg_policies` when the table or policy may be absent.
- Guard function grants, revokes, and alters with `pg_proc`,
  `to_regprocedure()`, or `oidvectortypes()` checks for the exact signature.
- Guard `ALTER VIEW` and publication membership changes with catalog checks.
- Function bodies that reference optional historical tables must either create
  those tables earlier in the same replay path or guard the dependency.
- A PR that changes migrations must pass the Supabase branch replay workflow
  before merge. That workflow creates a temporary branch from production,
  waits for replay to finish, prints action logs on failure, and deletes the
  branch afterward.
