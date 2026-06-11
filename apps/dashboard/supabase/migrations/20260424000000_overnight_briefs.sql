-- Overnight briefs — cron-generated "what moved overnight" narratives.
--
-- Populated by /api/cron/overnight-brief at 1:55 AM UTC (between daily-orchestrator-late
-- and analytics-pipeline). The dashboard's AIMorningBriefing widget reads the latest
-- non-expired row for the logged-in user; when no fresh row exists, the widget falls
-- back to its existing live-compute path so first-time / free-tier users still see content.
--
-- One row per generation per user. Not upsert-on-user — we keep history so users can
-- see "yesterday's brief" if the cron skipped (no meaningful overnight change).
-- 30h TTL covers the overnight-to-next-overnight window plus a buffer for late readers.

CREATE TABLE IF NOT EXISTS public.overnight_briefs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id text NOT NULL REFERENCES public.profiles(id) ON DELETE CASCADE,
  workspace_id text,
  generated_at timestamptz NOT NULL DEFAULT now(),
  narrative_text text NOT NULL,
  moves_jsonb jsonb NOT NULL DEFAULT '[]'::jsonb,
  anomalies_jsonb jsonb NOT NULL DEFAULT '[]'::jsonb,
  window_start timestamptz NOT NULL,
  window_end timestamptz NOT NULL,
  expires_at timestamptz NOT NULL DEFAULT (now() + interval '30 hours'),
  ai_provider text,
  ai_model text
);

-- Lookup: latest non-expired brief for a user. (user_id, generated_at DESC) beats
-- (user_id, expires_at) because the dashboard always asks for "most recent"; the
-- expires_at filter is a cheap predicate on top of that.
CREATE INDEX IF NOT EXISTS idx_overnight_briefs_user_recent
  ON public.overnight_briefs (user_id, generated_at DESC);

-- Housekeeping: let an eventual cleanup cron delete expired rows efficiently.
-- Plain btree, not partial — Postgres rejects now() in index predicates
-- (not marked IMMUTABLE). Range predicate `expires_at < now()` at query time
-- still uses this index fine.
CREATE INDEX IF NOT EXISTS idx_overnight_briefs_expires_at
  ON public.overnight_briefs (expires_at);

ALTER TABLE public.overnight_briefs ENABLE ROW LEVEL SECURITY;

-- Users can SELECT their own briefs only. No INSERT/UPDATE/DELETE policies —
-- writes go through the service-role client inside the cron, which bypasses RLS.
CREATE POLICY "own_overnight_briefs_select"
  ON public.overnight_briefs
  FOR SELECT
  USING (auth.uid()::text = user_id);

COMMENT ON TABLE public.overnight_briefs IS
  'Cron-generated morning briefs (narrative + moves + anomalies). Read by AIMorningBriefing widget; written by /api/cron/overnight-brief at 1:55 AM UTC.';
