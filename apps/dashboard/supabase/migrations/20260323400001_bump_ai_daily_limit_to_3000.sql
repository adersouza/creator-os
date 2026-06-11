-- Bump ai_daily_generation_limit from 2000 to 3000.
-- Math: 96 accounts × 6 posts/day = 576 posts needed.
-- At ~50% content filter pass rate, need ~1200 generations.
-- 3000 gives headroom if rejection rate spikes higher.

UPDATE auto_post_config
SET ai_daily_generation_limit = 3000
WHERE ai_daily_generation_limit <= 2000;
