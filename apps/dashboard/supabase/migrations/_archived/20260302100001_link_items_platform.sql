-- Add platform detection and deep link fields to link_items
ALTER TABLE link_items ADD COLUMN IF NOT EXISTS platform TEXT;
ALTER TABLE link_items ADD COLUMN IF NOT EXISTS deep_link_url TEXT;
