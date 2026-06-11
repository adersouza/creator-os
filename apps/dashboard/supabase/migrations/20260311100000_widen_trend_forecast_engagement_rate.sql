-- Widen avg_engagement_rate from DECIMAL(5,4) to DECIMAL(10,4)
-- DECIMAL(5,4) maxes at 9.9999 — small accounts can exceed 10% engagement,
-- causing numeric overflow on upsert.
ALTER TABLE trend_forecasts
  ALTER COLUMN avg_engagement_rate TYPE DECIMAL(10,4);
