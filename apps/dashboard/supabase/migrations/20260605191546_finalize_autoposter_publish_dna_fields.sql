BEGIN;

ALTER TABLE IF EXISTS public.auto_post_queue
  ADD COLUMN IF NOT EXISTS dna_id UUID REFERENCES public.account_dna(id) ON DELETE SET NULL,
  ADD COLUMN IF NOT EXISTS dna_version INTEGER,
  ADD COLUMN IF NOT EXISTS dna_fit_score NUMERIC,
  ADD COLUMN IF NOT EXISTS voice_fit_score NUMERIC,
  ADD COLUMN IF NOT EXISTS topic_fit_score NUMERIC,
  ADD COLUMN IF NOT EXISTS mood_fit_score NUMERIC,
  ADD COLUMN IF NOT EXISTS uniqueness_score NUMERIC,
  ADD COLUMN IF NOT EXISTS sibling_collision_score NUMERIC,
  ADD COLUMN IF NOT EXISTS genericness_score NUMERIC,
  ADD COLUMN IF NOT EXISTS dna_decision TEXT,
  ADD COLUMN IF NOT EXISTS dna_reasons JSONB;

ALTER TABLE IF EXISTS public.posts
  ADD COLUMN IF NOT EXISTS dna_id UUID REFERENCES public.account_dna(id) ON DELETE SET NULL,
  ADD COLUMN IF NOT EXISTS dna_version INTEGER,
  ADD COLUMN IF NOT EXISTS dna_fit_score NUMERIC,
  ADD COLUMN IF NOT EXISTS voice_fit_score NUMERIC,
  ADD COLUMN IF NOT EXISTS topic_fit_score NUMERIC,
  ADD COLUMN IF NOT EXISTS mood_fit_score NUMERIC,
  ADD COLUMN IF NOT EXISTS uniqueness_score NUMERIC,
  ADD COLUMN IF NOT EXISTS sibling_collision_score NUMERIC,
  ADD COLUMN IF NOT EXISTS genericness_score NUMERIC,
  ADD COLUMN IF NOT EXISTS dna_decision TEXT,
  ADD COLUMN IF NOT EXISTS dna_reasons JSONB;

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
    dna_reasons
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
    v_queue.dna_reasons
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

  PERFORM public.increment_group_posts_today(p_workspace_id, p_group_id);

  PERFORM 1
    FROM public.check_and_increment_rate_limit(p_account_id, 25, 250);

  post_id := v_post_id;
  inserted := TRUE;
  RETURN NEXT;
END;
$$;

COMMIT;
