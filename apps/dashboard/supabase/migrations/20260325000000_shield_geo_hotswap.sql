-- =============================================================================
-- Migration: Shield Protection, Geo Filter, Link Hot-Swap
-- =============================================================================

BEGIN;

-- -----------------------------------------------------------------------------
-- 1. Shield Protection
--    Configurable bot filtering mode for link pages.
--    off  = no shielding (default, all tiers)
--    soft = hide adult-flagged links from Meta bots (Pro+)
--    strict = show only profile card to Meta bots (Agency+)
-- -----------------------------------------------------------------------------
ALTER TABLE link_pages ADD COLUMN IF NOT EXISTS shield_mode VARCHAR(10) DEFAULT 'off'
  CHECK (shield_mode IN ('off', 'soft', 'strict'));

-- Optional: custom list of domains to hide in soft mode (overrides default list)
ALTER TABLE link_pages ADD COLUMN IF NOT EXISTS shield_config JSONB DEFAULT NULL;

-- Shield activation log for analytics
CREATE TABLE IF NOT EXISTS shield_log (
  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  page_id TEXT NOT NULL REFERENCES link_pages(id) ON DELETE CASCADE,
  bot_type TEXT NOT NULL,
  shield_mode VARCHAR(10) NOT NULL,
  country TEXT,
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_shield_log_page_id ON shield_log(page_id);

-- RLS: shield_log is insert-only from API (service role), read by page owner
ALTER TABLE shield_log ENABLE ROW LEVEL SECURITY;

CREATE POLICY shield_log_select ON shield_log
  FOR SELECT USING (
    page_id IN (SELECT id FROM link_pages WHERE user_id = auth.uid()::text)
  );

-- -----------------------------------------------------------------------------
-- 2. Geo Filter
--    Country-based redirect or block rules per link page.
--    JSONB schema: { rules: [{ countries: ["FR"], action: "redirect"|"block",
--                               redirect_url?: string, message?: string }],
--                    default: "allow" }
-- -----------------------------------------------------------------------------
ALTER TABLE link_pages ADD COLUMN IF NOT EXISTS geo_rules JSONB DEFAULT NULL;

-- -----------------------------------------------------------------------------
-- 3. Link Hot-Swap (cache busting)
--    Timestamp set when any link on the page is updated.
--    Link page renderer uses this to decide cache strategy.
-- -----------------------------------------------------------------------------
ALTER TABLE link_pages ADD COLUMN IF NOT EXISTS cache_bust BIGINT DEFAULT 0;

COMMIT;
