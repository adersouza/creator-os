-- Backfill autoposter post lineage from queue rows for both finalizer and legacy direct-insert paths.

CREATE OR REPLACE FUNCTION public.copy_autoposter_post_lineage_fields()
RETURNS TRIGGER
LANGUAGE plpgsql
SET search_path = public
AS $$
DECLARE
  v_queue_id TEXT;
  v_queue public.auto_post_queue%ROWTYPE;
BEGIN
  v_queue_id := COALESCE(NEW.auto_post_queue_id, NEW.metadata->>'autoPostQueueId');

  IF v_queue_id IS NULL THEN
    NEW.strategy_bucket := COALESCE(NEW.strategy_bucket, 'none');
    RETURN NEW;
  END IF;

  SELECT *
    INTO v_queue
    FROM public.auto_post_queue
    WHERE id::text = v_queue_id
    LIMIT 1;

  IF NOT FOUND THEN
    NEW.strategy_bucket := COALESCE(NEW.strategy_bucket, 'none');
    RETURN NEW;
  END IF;

  NEW.auto_post_queue_id := COALESCE(NEW.auto_post_queue_id, v_queue.id::text);
  NEW.hook_type := COALESCE(NEW.hook_type, v_queue.hook_type);
  NEW.topic_label := COALESCE(NEW.topic_label, v_queue.topic_label, v_queue.topic_tag);
  NEW.format_type := COALESCE(NEW.format_type, v_queue.format_type);
  NEW.emotional_frame := COALESCE(NEW.emotional_frame, v_queue.emotional_frame);
  NEW.reply_mechanism := COALESCE(NEW.reply_mechanism, v_queue.reply_mechanism);
  NEW.content_length_bucket := COALESCE(NEW.content_length_bucket, v_queue.content_length_bucket);
  NEW.media_style := COALESCE(NEW.media_style, v_queue.media_style);
  NEW.posting_hour := COALESCE(NEW.posting_hour, v_queue.posting_hour);
  NEW.prompt_version := COALESCE(NEW.prompt_version, v_queue.prompt_version);
  NEW.template_id := COALESCE(NEW.template_id, v_queue.template_id);
  NEW.model_provider := COALESCE(NEW.model_provider, v_queue.model_provider, v_queue.ai_provider);
  NEW.source_pattern_id := COALESCE(NEW.source_pattern_id, v_queue.source_pattern_id, v_queue.source_id);
  NEW.strategy_recommendation_id := COALESCE(NEW.strategy_recommendation_id, v_queue.strategy_recommendation_id);
  NEW.strategy_bucket := COALESCE(NULLIF(NEW.strategy_bucket, 'none'), v_queue.strategy_bucket, 'none');
  NEW.dna_id := COALESCE(NEW.dna_id, v_queue.dna_id);
  NEW.dna_version := COALESCE(NEW.dna_version, v_queue.dna_version);
  NEW.dna_fit_score := COALESCE(NEW.dna_fit_score, v_queue.dna_fit_score);
  NEW.voice_fit_score := COALESCE(NEW.voice_fit_score, v_queue.voice_fit_score);
  NEW.topic_fit_score := COALESCE(NEW.topic_fit_score, v_queue.topic_fit_score);
  NEW.mood_fit_score := COALESCE(NEW.mood_fit_score, v_queue.mood_fit_score);
  NEW.uniqueness_score := COALESCE(NEW.uniqueness_score, v_queue.uniqueness_score);
  NEW.sibling_collision_score := COALESCE(NEW.sibling_collision_score, v_queue.sibling_collision_score);
  NEW.genericness_score := COALESCE(NEW.genericness_score, v_queue.genericness_score);
  NEW.dna_decision := COALESCE(NEW.dna_decision, v_queue.dna_decision);
  NEW.dna_reasons := COALESCE(NEW.dna_reasons, v_queue.dna_reasons);
  NEW.active_arc_id := COALESCE(NEW.active_arc_id, v_queue.active_arc_id);
  NEW.arc_beat_id := COALESCE(NEW.arc_beat_id, v_queue.arc_beat_id);

  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_posts_copy_autoposter_post_lineage_fields
  ON public.posts;

CREATE TRIGGER trg_posts_copy_autoposter_post_lineage_fields
  BEFORE INSERT OR UPDATE OF auto_post_queue_id, metadata
  ON public.posts
  FOR EACH ROW
  EXECUTE FUNCTION public.copy_autoposter_post_lineage_fields();

UPDATE public.posts p
SET metadata = p.metadata
FROM public.auto_post_queue q
WHERE q.id::text = COALESCE(p.auto_post_queue_id, p.metadata->>'autoPostQueueId')
  AND (
    p.auto_post_queue_id IS NULL
    OR p.dna_id IS NULL
    OR p.hook_type IS NULL
    OR p.topic_label IS NULL
    OR p.strategy_bucket IS NULL
  );
