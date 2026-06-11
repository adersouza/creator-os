-- Add missing columns for growth journal feature
ALTER TABLE recommendation_dismissals
  ADD COLUMN IF NOT EXISTS action text DEFAULT 'dismissed',
  ADD COLUMN IF NOT EXISTS actioned_at timestamptz,
  ADD COLUMN IF NOT EXISTS recommendation_text text,
  ADD COLUMN IF NOT EXISTS icon text DEFAULT '🏆',
  ADD COLUMN IF NOT EXISTS platform text DEFAULT 'threads';

-- Index for journal queries (actioned entries)
CREATE INDEX IF NOT EXISTS idx_rec_dismissals_actioned
  ON recommendation_dismissals(user_id, account_id, action)
  WHERE action = 'actioned';
