-- Approval workflow columns on posts table
-- Adds approval metadata for team-based post review

ALTER TABLE posts ADD COLUMN IF NOT EXISTS approved_by UUID REFERENCES auth.users(id);
ALTER TABLE posts ADD COLUMN IF NOT EXISTS approved_at TIMESTAMPTZ;
ALTER TABLE posts ADD COLUMN IF NOT EXISTS approval_notes TEXT;
ALTER TABLE posts ADD COLUMN IF NOT EXISTS rejected_by UUID REFERENCES auth.users(id);
ALTER TABLE posts ADD COLUMN IF NOT EXISTS rejected_at TIMESTAMPTZ;
ALTER TABLE posts ADD COLUMN IF NOT EXISTS rejection_notes TEXT;
