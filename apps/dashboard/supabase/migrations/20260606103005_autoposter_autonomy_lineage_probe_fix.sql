BEGIN;

ALTER TABLE IF EXISTS public.autoposter_post_performance_facts
  ADD COLUMN IF NOT EXISTS clone_family TEXT,
  ADD COLUMN IF NOT EXISTS quality_gate_lane TEXT,
  ADD COLUMN IF NOT EXISTS quality_gate_reason TEXT;

CREATE INDEX IF NOT EXISTS autoposter_performance_clone_family_idx
  ON public.autoposter_post_performance_facts(clone_family, views_24h DESC)
  WHERE clone_family IS NOT NULL;

CREATE INDEX IF NOT EXISTS autoposter_performance_quality_gate_lane_idx
  ON public.autoposter_post_performance_facts(quality_gate_lane, views_24h DESC)
  WHERE quality_gate_lane IS NOT NULL;

UPDATE public.autoposter_post_performance_facts f
SET
  clone_family = COALESCE(
    f.clone_family,
    p.metadata #>> '{winner_clone,clone_family}',
    p.metadata ->> 'clone_family',
    q.metadata #>> '{winner_clone,clone_family}',
    q.metadata ->> 'clone_family'
  ),
  quality_gate_lane = COALESCE(
    f.quality_gate_lane,
    p.metadata ->> 'quality_gate_lane',
    p.metadata #>> '{quality_gate,lane}',
    q.metadata ->> 'quality_gate_lane',
    q.metadata #>> '{quality_gate,lane}'
  ),
  quality_gate_reason = COALESCE(
    f.quality_gate_reason,
    p.metadata ->> 'quality_gate_reason',
    p.metadata #>> '{quality_gate,laneReason}',
    p.metadata #>> '{quality_gate,reason}',
    q.metadata ->> 'quality_gate_reason',
    q.metadata #>> '{quality_gate,laneReason}',
    q.metadata #>> '{quality_gate,reason}'
  ),
  strategy_recommendation_id = COALESCE(
    f.strategy_recommendation_id,
    p.strategy_recommendation_id,
    q.strategy_recommendation_id
  ),
  strategy_bucket = COALESCE(NULLIF(f.strategy_bucket, 'none'), p.strategy_bucket, q.strategy_bucket, f.strategy_bucket),
  source_pattern_id = COALESCE(f.source_pattern_id, p.source_pattern_id, q.source_pattern_id)
FROM public.posts p
LEFT JOIN public.auto_post_queue q
  ON q.id::text = COALESCE(p.auto_post_queue_id, p.metadata ->> 'autoPostQueueId')
WHERE f.post_id = p.id;

COMMIT;
