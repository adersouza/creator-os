-- Cached autoposter account health signals.
-- account_autoposter_state is the scheduler/publisher read model, so these
-- columns let selection prefer resilient accounts without recomputing history.

ALTER TABLE IF EXISTS public.account_autoposter_state
  ADD COLUMN IF NOT EXISTS account_health_score INTEGER NOT NULL DEFAULT 100,
  ADD COLUMN IF NOT EXISTS account_health_reason TEXT,
  ADD COLUMN IF NOT EXISTS last_health_recomputed_at TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS idx_aas_group_health_score
  ON public.account_autoposter_state(group_id, account_health_score DESC, status)
  WHERE status <> 'inactive';

COMMENT ON COLUMN public.account_autoposter_state.account_health_score IS
  'Cached autoposter publish health score, 0-100. 80+ normal, 60-79 deprioritized, 40-59 warming, <40 suppressed for non-manual autoposter selection.';
COMMENT ON COLUMN public.account_autoposter_state.account_health_reason IS
  'Machine-readable scoring signal summary, e.g. oauth_failures:1;dead_letters:2.';
COMMENT ON COLUMN public.account_autoposter_state.last_health_recomputed_at IS
  'Timestamp when autoposter health score was last recomputed.';
