-- Atomically finalize a Threads autoposter publish after Meta has accepted it.
-- This closes the gap where the external post exists but the local posts row
-- or queue status update is lost by a serverless crash or partial DB failure.

ALTER TABLE IF EXISTS public.auto_post_queue
  ADD COLUMN IF NOT EXISTS external_published_at TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS finalize_error TEXT;

ALTER TABLE IF EXISTS public.auto_post_queue
  DROP CONSTRAINT IF EXISTS auto_post_queue_status_check;

ALTER TABLE IF EXISTS public.auto_post_queue
  ADD CONSTRAINT auto_post_queue_status_check
  CHECK (status IN (
    'pending',
    'processing',
    'publishing',
    'posted',
    'published',
    'failed',
    'dead_letter',
    'cancelled',
    'rejected',
    'queued',
    'scheduled',
    'needs_review',
    'needs_reconciliation',
    'external_published_local_finalize_failed'
  ));

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
    metadata
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
    )
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

DO $$
BEGIN
  IF to_regprocedure(
    'public.finalize_autoposter_publish(text,text,text,text,text,text,text,jsonb,text,timestamptz)'
  ) IS NOT NULL THEN
    GRANT EXECUTE ON FUNCTION public.finalize_autoposter_publish(
      TEXT,
      TEXT,
      TEXT,
      TEXT,
      TEXT,
      TEXT,
      TEXT,
      JSONB,
      TEXT,
      TIMESTAMPTZ
    ) TO service_role;
  END IF;
END $$;

CREATE OR REPLACE FUNCTION public.reconcile_autoposter_publish(
  p_queue_item_id TEXT
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
BEGIN
  IF to_regclass('public.auto_post_queue') IS NULL
     OR to_regclass('public.posts') IS NULL
     OR to_regclass('public.workspaces') IS NULL THEN
    RAISE EXCEPTION 'reconcile_autoposter_publish dependencies are missing'
      USING ERRCODE = '42P01';
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

  IF v_queue.status NOT IN (
    'needs_reconciliation',
    'external_published_local_finalize_failed'
  ) THEN
    RAISE EXCEPTION 'queue item % is %, not reconcilable', p_queue_item_id, v_queue.status
      USING ERRCODE = '23514';
  END IF;

  IF v_queue.threads_post_id IS NULL
     OR v_queue.account_id IS NULL
     OR v_queue.external_published_at IS NULL THEN
    RAISE EXCEPTION 'queue item % is missing external publish evidence', p_queue_item_id
      USING ERRCODE = '23514';
  END IF;

  SELECT owner_id
    INTO v_owner_id
    FROM public.workspaces
    WHERE id = v_queue.workspace_id;

  IF v_owner_id IS NULL THEN
    RAISE EXCEPTION 'workspace % not found', v_queue.workspace_id
      USING ERRCODE = 'P0002';
  END IF;

  SELECT id
    INTO v_existing_post_id
    FROM public.posts
    WHERE threads_post_id = v_queue.threads_post_id
      AND user_id = v_owner_id
    LIMIT 1;

  IF v_existing_post_id IS NOT NULL THEN
    UPDATE public.auto_post_queue
      SET status = 'published',
          posted_at = v_queue.external_published_at,
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
    metadata
  ) VALUES (
    v_owner_id,
    v_queue.account_id,
    CASE
      WHEN length(COALESCE(v_queue.content, '')) > 500
        THEN substring(COALESCE(v_queue.content, '') FROM 1 FOR 497) || '...'
      ELSE COALESCE(v_queue.content, '')
    END,
    COALESCE(v_queue.media_urls, ARRAY[]::TEXT[]),
    CASE WHEN array_length(COALESCE(v_queue.media_urls, ARRAY[]::TEXT[]), 1) > 0 THEN 'image' ELSE 'text' END,
    'published',
    v_queue.threads_post_id,
    v_queue.external_published_at,
    'auto-poster-reconciled',
    v_queue.topic_tag,
    v_queue.group_id,
    jsonb_build_object(
      'autoPostQueueId', p_queue_item_id,
      'finalizedBy', 'reconcile_autoposter_publish'
    )
  )
  RETURNING id INTO v_post_id;

  UPDATE public.auto_post_queue
    SET status = 'published',
        posted_at = v_queue.external_published_at,
        finalize_error = NULL,
        claimed_at = NULL,
        claim_token = NULL,
        claim_expires_at = NULL
    WHERE id::text = p_queue_item_id;

  PERFORM public.increment_group_posts_today(v_queue.workspace_id, v_queue.group_id);

  PERFORM 1
    FROM public.check_and_increment_rate_limit(v_queue.account_id, 25, 250);

  post_id := v_post_id;
  inserted := TRUE;
  RETURN NEXT;
END;
$$;

DO $$
BEGIN
  IF to_regprocedure('public.reconcile_autoposter_publish(text)') IS NOT NULL THEN
    GRANT EXECUTE ON FUNCTION public.reconcile_autoposter_publish(TEXT) TO service_role;
  END IF;
END $$;
