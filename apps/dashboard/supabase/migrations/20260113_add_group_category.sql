-- Add category column to account_groups table for fleet categorization
-- Categories: personal, clients, high-performers, uncategorized

ALTER TABLE account_groups
ADD COLUMN IF NOT EXISTS category TEXT DEFAULT 'uncategorized';

-- Add check constraint for valid categories
ALTER TABLE account_groups
DROP CONSTRAINT IF EXISTS account_groups_category_check;

ALTER TABLE account_groups
ADD CONSTRAINT account_groups_category_check
CHECK (category IN ('personal', 'clients', 'high-performers', 'uncategorized'));

-- Create index for category filtering
CREATE INDEX IF NOT EXISTS idx_account_groups_category ON account_groups(category);
