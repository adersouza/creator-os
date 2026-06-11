-- RLS policy for account_metrics_history.
-- Allows users to read history for their own accounts.
-- Uses the same join pattern as post_metric_history.

CREATE POLICY "Users can view own account history"
  ON account_metrics_history FOR SELECT
  USING (
    account_id IN (SELECT id FROM accounts WHERE user_id = auth.uid()::text)
  );
