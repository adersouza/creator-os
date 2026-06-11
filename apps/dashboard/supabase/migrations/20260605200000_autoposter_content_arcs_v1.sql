-- Content Arcs v1: minimal durable narrative arc lineage for Threads autoposter.

CREATE TABLE IF NOT EXISTS public.account_content_arcs (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id TEXT NOT NULL,
  group_id TEXT,
  account_id TEXT NOT NULL,
  title TEXT NOT NULL,
  mood TEXT NOT NULL DEFAULT 'neutral',
  status TEXT NOT NULL DEFAULT 'active',
  current_beat_index INTEGER NOT NULL DEFAULT 0,
  next_suggested_beat TEXT,
  cooldown_until TIMESTAMPTZ,
  payoff_status TEXT NOT NULL DEFAULT 'not_due',
  source_summary JSONB NOT NULL DEFAULT '{}'::jsonb,
  started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  completed_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT account_content_arcs_status_check
    CHECK (status IN ('draft', 'active', 'cooldown', 'payoff_pending', 'completed', 'retired')),
  CONSTRAINT account_content_arcs_payoff_status_check
    CHECK (payoff_status IN ('not_due', 'due', 'posted', 'skipped'))
);

CREATE TABLE IF NOT EXISTS public.arc_beats (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  arc_id UUID NOT NULL REFERENCES public.account_content_arcs(id) ON DELETE CASCADE,
  workspace_id TEXT NOT NULL,
  group_id TEXT,
  account_id TEXT NOT NULL,
  beat_index INTEGER NOT NULL,
  beat_title TEXT NOT NULL,
  beat_prompt TEXT NOT NULL,
  mood TEXT,
  status TEXT NOT NULL DEFAULT 'pending',
  queue_item_id TEXT REFERENCES public.auto_post_queue(id) ON DELETE SET NULL,
  post_id TEXT REFERENCES public.posts(id) ON DELETE SET NULL,
  suggested_after TIMESTAMPTZ,
  posted_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT arc_beats_status_check
    CHECK (status IN ('pending', 'queued', 'posted', 'skipped')),
  CONSTRAINT arc_beats_unique_index UNIQUE (arc_id, beat_index)
);

ALTER TABLE IF EXISTS public.auto_post_queue
  ADD COLUMN IF NOT EXISTS active_arc_id UUID REFERENCES public.account_content_arcs(id) ON DELETE SET NULL,
  ADD COLUMN IF NOT EXISTS arc_beat_id UUID REFERENCES public.arc_beats(id) ON DELETE SET NULL;

ALTER TABLE IF EXISTS public.posts
  ADD COLUMN IF NOT EXISTS active_arc_id UUID REFERENCES public.account_content_arcs(id) ON DELETE SET NULL,
  ADD COLUMN IF NOT EXISTS arc_beat_id UUID REFERENCES public.arc_beats(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS account_content_arcs_active_idx
  ON public.account_content_arcs(workspace_id, group_id, account_id, status, updated_at DESC);

CREATE INDEX IF NOT EXISTS arc_beats_arc_status_idx
  ON public.arc_beats(arc_id, status, beat_index);

CREATE INDEX IF NOT EXISTS auto_post_queue_active_arc_idx
  ON public.auto_post_queue(active_arc_id, arc_beat_id)
  WHERE active_arc_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS posts_active_arc_idx
  ON public.posts(active_arc_id, arc_beat_id, published_at DESC)
  WHERE active_arc_id IS NOT NULL;

ALTER TABLE public.account_content_arcs ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.arc_beats ENABLE ROW LEVEL SECURITY;

CREATE POLICY account_content_arcs_workspace_read ON public.account_content_arcs
  FOR SELECT USING (
    EXISTS (
      SELECT 1 FROM public.workspace_members wm
      WHERE wm.workspace_id::text = account_content_arcs.workspace_id
        AND wm.user_id = auth.uid()::text
    )
  );

CREATE POLICY arc_beats_workspace_read ON public.arc_beats
  FOR SELECT USING (
    EXISTS (
      SELECT 1 FROM public.workspace_members wm
      WHERE wm.workspace_id::text = arc_beats.workspace_id
        AND wm.user_id = auth.uid()::text
    )
  );

CREATE OR REPLACE FUNCTION public.finalize_autoposter_publish(
  p_queue_item_id TEXT,
  p_claim_token TEXT,
  p_threads_post_id TEXT,
  p_account_id TEXT,
  p_workspace_id TEXT,
  p_group_id TEXT,
  p_content TEXT,
  p_media_urls JSONB DEFAULT '[]'::jsonb,
  p_source_type TEXT DEFAULT 'auto-poster',
  p_published_at TIMESTAMPTZ DEFAULT NOW()
) RETURNS TABLE(post_id TEXT, inserted BOOLEAN)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
  v_queue auto_post_queue%ROWTYPE;
  v_owner_id TEXT;
  v_existing_post_id TEXT;
  v_post_id TEXT;
  v_media_urls TEXT[];
BEGIN
  IF to_regclass('public.auto_post_queue') IS NULL
     OR to_regclass('public.posts') IS NULL
     OR to_regclass('public.workspaces') IS NULL THEN
    RAISE EXCEPTION 'finalize_autoposter_publish dependencies are missing'
      USING ERRCODE = '42P01';
  END IF;

  IF p_threads_post_id IS NULL OR length(trim(p_threads_post_id)) = 0 THEN
    RAISE EXCEPTION 'threads_post_id is required'
      USING ERRCODE = '22023';
  END IF;

  SELECT *
    INTO v_queue
    FROM public.auto_post_queue
    WHERE id::text = p_queue_item_id
    FOR UPDATE;

  IF NOT FOUND THEN
    RAISE EXCEPTION 'queue item % not found', p_queue_item_id
      USING ERRCODE = 'P0002';
  END IF;

  SELECT owner_id
    INTO v_owner_id
    FROM public.workspaces
    WHERE id = p_workspace_id;

  IF v_owner_id IS NULL THEN
    RAISE EXCEPTION 'workspace % not found', p_workspace_id
      USING ERRCODE = 'P0002';
  END IF;

  IF v_queue.workspace_id IS DISTINCT FROM p_workspace_id
     OR v_queue.group_id IS DISTINCT FROM p_group_id THEN
    RAISE EXCEPTION 'queue item % does not belong to workspace/group', p_queue_item_id
      USING ERRCODE = '23514';
  END IF;

  SELECT id
    INTO v_existing_post_id
    FROM public.posts
    WHERE threads_post_id = p_threads_post_id
      AND user_id = v_owner_id
    LIMIT 1;

  IF v_queue.status = 'published'
     AND v_queue.threads_post_id = p_threads_post_id
     AND v_existing_post_id IS NOT NULL THEN
    post_id := v_existing_post_id;
    inserted := FALSE;
    RETURN NEXT;
    RETURN;
  END IF;

  IF v_queue.status <> 'publishing' THEN
    RAISE EXCEPTION 'queue item % is %, not publishing', p_queue_item_id, v_queue.status
      USING ERRCODE = '23514';
  END IF;

  IF v_queue.claim_token IS DISTINCT FROM p_claim_token THEN
    RAISE EXCEPTION 'claim token mismatch for queue item %', p_queue_item_id
      USING ERRCODE = '23514';
  END IF;

  IF v_existing_post_id IS NOT NULL THEN
    UPDATE public.auto_post_queue
      SET status = 'published',
          account_id = p_account_id,
          threads_post_id = p_threads_post_id,
          posted_at = p_published_at,
          external_published_at = p_published_at,
          finalize_error = NULL,
          claimed_at = NULL,
          claim_token = NULL,
          claim_expires_at = NULL
      WHERE id::text = p_queue_item_id;

    post_id := v_existing_post_id;
    inserted := FALSE;
    RETURN NEXT;
    RETURN;
  END IF;

  SELECT COALESCE(array_agg(value), ARRAY[]::TEXT[])
    INTO v_media_urls
    FROM jsonb_array_elements_text(COALESCE(p_media_urls, '[]'::jsonb)) AS value;

  INSERT INTO public.posts (
    user_id,
    account_id,
    content,
    media_urls,
    media_type,
    status,
    threads_post_id,
    published_at,
    source,
    topic_tag,
    cross_post_group_id,
    metadata,
    auto_post_queue_id,
    hook_type,
    topic_label,
    format_type,
    emotional_frame,
    reply_mechanism,
    content_length_bucket,
    media_style,
    posting_hour,
    prompt_version,
    template_id,
    model_provider,
    source_pattern_id,
    strategy_recommendation_id,
    strategy_bucket,
    dna_id,
    dna_version,
    dna_fit_score,
    voice_fit_score,
    topic_fit_score,
    mood_fit_score,
    uniqueness_score,
    sibling_collision_score,
    genericness_score,
    dna_decision,
    dna_reasons,
    active_arc_id,
    arc_beat_id
  ) VALUES (
    v_owner_id,
    p_account_id,
    CASE
      WHEN length(COALESCE(p_content, '')) > 500
        THEN substring(COALESCE(p_content, '') FROM 1 FOR 497) || '...'
      ELSE COALESCE(p_content, '')
    END,
    v_media_urls,
    CASE WHEN array_length(v_media_urls, 1) > 0 THEN 'image' ELSE 'text' END,
    'published',
    p_threads_post_id,
    p_published_at,
    COALESCE(NULLIF(p_source_type, ''), 'auto-poster'),
    v_queue.topic_tag,
    p_group_id,
    jsonb_build_object(
      'autoPostQueueId', p_queue_item_id,
      'finalizedBy', 'finalize_autoposter_publish'
    ),
    p_queue_item_id,
    v_queue.hook_type,
    COALESCE(v_queue.topic_label, v_queue.topic_tag, 'uncategorized'),
    v_queue.format_type,
    v_queue.emotional_frame,
    v_queue.reply_mechanism,
    v_queue.content_length_bucket,
    v_queue.media_style,
    COALESCE(v_queue.posting_hour, EXTRACT(HOUR FROM p_published_at)::integer),
    v_queue.prompt_version,
    v_queue.template_id,
    COALESCE(v_queue.model_provider, v_queue.ai_provider),
    COALESCE(v_queue.source_pattern_id, v_queue.source_id),
    v_queue.strategy_recommendation_id,
    v_queue.strategy_bucket,
    v_queue.dna_id,
    v_queue.dna_version,
    v_queue.dna_fit_score,
    v_queue.voice_fit_score,
    v_queue.topic_fit_score,
    v_queue.mood_fit_score,
    v_queue.uniqueness_score,
    v_queue.sibling_collision_score,
    v_queue.genericness_score,
    v_queue.dna_decision,
    v_queue.dna_reasons,
    v_queue.active_arc_id,
    v_queue.arc_beat_id
  )
  RETURNING id INTO v_post_id;

  UPDATE public.auto_post_queue
    SET status = 'published',
        account_id = p_account_id,
        threads_post_id = p_threads_post_id,
        posted_at = p_published_at,
        external_published_at = p_published_at,
        finalize_error = NULL,
        claimed_at = NULL,
        claim_token = NULL,
        claim_expires_at = NULL
    WHERE id::text = p_queue_item_id;

  UPDATE public.arc_beats
    SET status = 'posted',
        post_id = v_post_id,
        queue_item_id = v_queue.id,
        posted_at = p_published_at,
        updated_at = now()
    WHERE id = v_queue.arc_beat_id;

  PERFORM public.increment_group_posts_today(p_workspace_id, p_group_id);

  PERFORM 1
    FROM public.check_and_increment_rate_limit(p_account_id, 25, 250);

  post_id := v_post_id;
  inserted := TRUE;
  RETURN NEXT;
END;
$$;

GRANT EXECUTE ON FUNCTION public.finalize_autoposter_publish(
  TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, JSONB, TEXT, TIMESTAMPTZ
) TO service_role;
