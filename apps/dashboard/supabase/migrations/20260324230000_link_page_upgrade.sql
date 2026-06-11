-- =============================================================================
-- Migration: Link Page Upgrade (7 features)
-- Adds age gate, tracking pixels, URL masking, per-link styling, deep links
-- =============================================================================

BEGIN;

-- -----------------------------------------------------------------------------
-- 1. link_pages: Age gate toggle + custom message
--    Allows page owners to require visitors to confirm they are 18+
--    before viewing the page. Optional custom message overrides the default.
-- -----------------------------------------------------------------------------
ALTER TABLE link_pages ADD COLUMN IF NOT EXISTS age_gate BOOLEAN DEFAULT false;
ALTER TABLE link_pages ADD COLUMN IF NOT EXISTS age_gate_message TEXT DEFAULT NULL;

-- -----------------------------------------------------------------------------
-- 2. link_pages: Tracking pixels
--    JSONB blob storing analytics pixel IDs for third-party platforms.
--    Expected shape: { meta_pixel_id, tiktok_pixel_id, ga4_measurement_id,
--                      x_pixel_id, snap_pixel_id, gtm_container_id }
-- -----------------------------------------------------------------------------
ALTER TABLE link_pages ADD COLUMN IF NOT EXISTS tracking_pixels JSONB DEFAULT NULL;

-- -----------------------------------------------------------------------------
-- 3. link_items: Short redirect code for URL masking
--    Used by the /go/r/{redirectId} redirect endpoint so outbound URLs
--    are opaque to the visitor (hides affiliate params, etc.).
--    VARCHAR(12) with UNIQUE constraint; NULL means no redirect alias.
-- -----------------------------------------------------------------------------
ALTER TABLE link_items ADD COLUMN IF NOT EXISTS redirect_id VARCHAR(12) UNIQUE DEFAULT NULL;

-- -----------------------------------------------------------------------------
-- 4. link_items: Per-link styling overrides
--    JSONB blob for custom visual treatment of individual links.
--    Expected shape: { bg_color, text_color, border_radius, animation,
--                      image_url, image_mode }
-- -----------------------------------------------------------------------------
ALTER TABLE link_items ADD COLUMN IF NOT EXISTS style JSONB DEFAULT NULL;

-- -----------------------------------------------------------------------------
-- 5. link_items: Deep link configuration
--    Per-platform deep link overrides so mobile users open the native app
--    instead of a web browser.
--    Expected shape: { ios_deep_link, android_deep_link, fallback_url,
--                      enable_deep_link }
-- -----------------------------------------------------------------------------
ALTER TABLE link_items ADD COLUMN IF NOT EXISTS deep_link_config JSONB DEFAULT NULL;

-- -----------------------------------------------------------------------------
-- 6. Backfill redirect_id for all existing link_items
--    Generates an 8-character hex code from md5(random + id) so every
--    existing link gets a redirect alias retroactively.
--    Only fills rows where redirect_id is still NULL (safe to re-run).
-- -----------------------------------------------------------------------------
UPDATE link_items
SET redirect_id = substring(md5(random()::text || id::text) FROM 1 FOR 8)
WHERE redirect_id IS NULL;

-- -----------------------------------------------------------------------------
-- 7. Index on redirect_id for fast redirect lookups
--    The /go/r/{redirectId} endpoint needs sub-ms lookup by this column.
--    Partial index excludes NULLs (rows without a redirect alias).
-- -----------------------------------------------------------------------------
CREATE INDEX IF NOT EXISTS idx_link_items_redirect_id
  ON link_items (redirect_id)
  WHERE redirect_id IS NOT NULL;

COMMIT;
