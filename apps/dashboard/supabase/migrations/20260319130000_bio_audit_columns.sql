-- Bio audit infrastructure
-- Add bio column to instagram_accounts (Threads accounts already have it)
-- Add bio_template to account_groups for per-group CTA enforcement
ALTER TABLE instagram_accounts ADD COLUMN IF NOT EXISTS bio TEXT;
ALTER TABLE account_groups ADD COLUMN IF NOT EXISTS bio_template JSONB;

-- bio_template schema: { "required_patterns": ["snap|sc:", "link\\.me"] }
-- Patterns are regex strings checked case-insensitively against account bios
