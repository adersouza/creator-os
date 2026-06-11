-- 1. Create the unified_links table to act as a parent for all click-based assets
-- NOTE: Changed user_id and workspace_id to TEXT to match existing table types
CREATE TABLE IF NOT EXISTS unified_links (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id TEXT REFERENCES profiles(id) ON DELETE CASCADE,
    workspace_id TEXT REFERENCES workspaces(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    type TEXT NOT NULL CHECK (type IN ('page', 'redirect')),
    source_id UUID NOT NULL, -- Points to either link_pages.id or smart_links.id
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

-- 2. Add target_smart_link_id to link_items
ALTER TABLE link_items ADD COLUMN IF NOT EXISTS target_smart_link_id UUID REFERENCES smart_links(id) ON DELETE SET NULL;

-- 3. Create the Real-time Revenue View
-- Using TEXT casting for ID comparisons to ensure compatibility
CREATE OR REPLACE VIEW unified_link_roi AS
SELECT 
    lp.user_id,
    lp.id as page_id,
    lp.title as page_title,
    lp.view_count as page_views,
    (SELECT COUNT(*) FROM link_items li WHERE li.page_id = lp.id) as button_count,
    COALESCE(SUM(sl.click_count), 0) as total_redirect_clicks,
    COALESCE(SUM(sl.est_conversion_value * sl.click_count * sl.est_conversion_rate), 0) as estimated_revenue
FROM link_pages lp
LEFT JOIN link_items li ON li.page_id = lp.id
LEFT JOIN smart_links sl ON sl.id = li.target_smart_link_id
GROUP BY lp.id, lp.user_id, lp.title, lp.view_count;

-- 4. Industry Benchmarks for Estimated Revenue (Fallback logic)
CREATE TABLE IF NOT EXISTS link_benchmarks (
    niche TEXT PRIMARY KEY,
    threads_epc DECIMAL DEFAULT 0.45, -- Earnings per click
    instagram_epc DECIMAL DEFAULT 0.85
);

INSERT INTO link_benchmarks (niche, threads_epc, instagram_epc)
VALUES 
    ('Lifestyle', 0.60, 1.10),
    ('Tech', 0.85, 0.95),
    ('B2B', 1.50, 2.50)
ON CONFLICT (niche) DO NOTHING;
