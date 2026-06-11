-- Close cross-tenant RLS gaps surfaced by the round-3 DB audit.
--
-- Four tables either had `FOR ALL USING (true)` policies (any authenticated
-- user could SELECT every other workspace's rows) or no RLS at all. All
-- four are operational/aggregated data written by cron jobs via the
-- service-role client; user-facing UI doesn't read them directly. The
-- service role bypasses RLS by design, so locking them down doesn't break
-- the cron writers.
--
-- Audit refs:
--   H1 — follower_history + reply_response_times: FOR ALL USING (true)
--   H2 — scheduler_decisions + account_schedule: no RLS at all

-- 1. follower_history — replace the open policy with one that scopes to
--    accounts owned by the requesting user. account_id is TEXT and may
--    refer to either accounts.id (threads) or instagram_accounts.id
--    (instagram), so the policy unions both.
DO $$
BEGIN
	IF to_regclass('public.follower_history') IS NOT NULL THEN
		EXECUTE 'DROP POLICY IF EXISTS "Service can manage follower history" ON public.follower_history';

		IF NOT EXISTS (
			SELECT 1
			FROM pg_policies
			WHERE schemaname = 'public'
				AND tablename = 'follower_history'
				AND policyname = 'Users access own follower history'
		) THEN
			EXECUTE $policy$
				CREATE POLICY "Users access own follower history" ON public.follower_history
					FOR ALL
					USING (
						EXISTS (
							SELECT 1 FROM accounts a
							WHERE a.id = follower_history.account_id
								AND a.user_id = auth.uid()::text
						)
						OR EXISTS (
							SELECT 1 FROM instagram_accounts ia
							WHERE ia.id::text = follower_history.account_id
								AND ia.user_id = auth.uid()::text
						)
					)
					WITH CHECK (
						EXISTS (
							SELECT 1 FROM accounts a
							WHERE a.id = follower_history.account_id
								AND a.user_id = auth.uid()::text
						)
						OR EXISTS (
							SELECT 1 FROM instagram_accounts ia
							WHERE ia.id::text = follower_history.account_id
								AND ia.user_id = auth.uid()::text
						)
					)
			$policy$;
		END IF;
	END IF;
END $$;

-- 2. reply_response_times — same shape; account_id has a real FK to accounts
--    so the join is simpler.
DO $$
BEGIN
	IF to_regclass('public.reply_response_times') IS NOT NULL THEN
		EXECUTE 'DROP POLICY IF EXISTS "Service can manage reply times" ON public.reply_response_times';

		IF NOT EXISTS (
			SELECT 1
			FROM pg_policies
			WHERE schemaname = 'public'
				AND tablename = 'reply_response_times'
				AND policyname = 'Users access own reply times'
		) THEN
			EXECUTE $policy$
				CREATE POLICY "Users access own reply times" ON public.reply_response_times
					FOR ALL
					USING (
						EXISTS (
							SELECT 1 FROM accounts a
							WHERE a.id = reply_response_times.account_id
								AND a.user_id = auth.uid()::text
						)
					)
					WITH CHECK (
						EXISTS (
							SELECT 1 FROM accounts a
							WHERE a.id = reply_response_times.account_id
								AND a.user_id = auth.uid()::text
						)
					)
			$policy$;
		END IF;
	END IF;
END $$;

-- 3. scheduler_decisions — created post-RLS-sweep with no policies. It's a
--    decision-log table written only by the unified scheduler cron, which
--    uses the service role. Enable RLS with no permissive policy: the
--    service role bypasses RLS so cron writes still work; authenticated
--    and anon get zero rows.
ALTER TABLE IF EXISTS scheduler_decisions ENABLE ROW LEVEL SECURITY;

-- 4. account_schedule — same shape: workspace-scoped operational config
--    written by the scheduler cron. Lock down to service-role only.
ALTER TABLE IF EXISTS account_schedule ENABLE ROW LEVEL SECURITY;

-- 5. group_analytics — flagged with the same FOR ALL USING (true) shape
--    in the audit (less PII-sensitive but worth tightening for consistency).
--    Skipped here because the audit notes its risk is low; do this in a
--    follow-up if the table becomes user-facing.
