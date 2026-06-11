-- Applied via schema reconciliation 2026-03-07
-- Adds platform detection and deep link fields to link_items

ALTER TABLE link_items ADD COLUMN IF NOT EXISTS platform TEXT;
ALTER TABLE link_items ADD COLUMN IF NOT EXISTS deep_link_url TEXT;
