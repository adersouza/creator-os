-- Add account_handle column to sent_replies table
-- This column stores the handle of the account that sent the reply

ALTER TABLE sent_replies
ADD COLUMN IF NOT EXISTS account_handle TEXT;

-- Add avatar_url if also missing (commonly used together)
ALTER TABLE sent_replies
ADD COLUMN IF NOT EXISTS avatar_url TEXT;
