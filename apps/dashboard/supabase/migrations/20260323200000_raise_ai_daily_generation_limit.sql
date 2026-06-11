-- Raise ai_daily_generation_limit from 10 to 200.
-- With 15 groups × 6 accounts each, the old limit of 10 fill calls/day
-- only produced ~20 posts total — starving 13 of 15 groups.

UPDATE auto_post_config
SET ai_daily_generation_limit = 200
WHERE ai_daily_generation_limit IS NULL OR ai_daily_generation_limit <= 10;
