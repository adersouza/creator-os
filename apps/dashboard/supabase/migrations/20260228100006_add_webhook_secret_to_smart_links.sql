-- #515: Add webhook_secret column to smart_links for HMAC-SHA256 conversion postback verification
-- convert.ts reads this column; defaults to NULL (backward compatible, allows unsigned postbacks)
ALTER TABLE smart_links ADD COLUMN IF NOT EXISTS webhook_secret TEXT DEFAULT NULL;

COMMENT ON COLUMN smart_links.webhook_secret IS 'Optional HMAC-SHA256 secret for verifying conversion postback signatures';
