-- Competitor metrics history — daily snapshots of competitor performance
CREATE TABLE IF NOT EXISTS competitor_metrics_history (
    id uuid DEFAULT gen_random_uuid() PRIMARY KEY,
    competitor_id text NOT NULL,
    user_id text NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    date date NOT NULL DEFAULT CURRENT_DATE,
    followers_count integer DEFAULT 0,
    avg_engagement_rate numeric(6,2) DEFAULT 0,
    total_posts integer DEFAULT 0,
    avg_views integer DEFAULT 0,
    avg_likes integer DEFAULT 0,
    top_post_engagement integer DEFAULT 0,
    created_at timestamptz DEFAULT now(),
    UNIQUE(competitor_id, date)
);

CREATE INDEX IF NOT EXISTS idx_competitor_metrics_history_competitor_date
    ON competitor_metrics_history(competitor_id, date);
CREATE INDEX IF NOT EXISTS idx_competitor_metrics_history_user_date
    ON competitor_metrics_history(user_id, date);

ALTER TABLE competitor_metrics_history ENABLE ROW LEVEL SECURITY;
