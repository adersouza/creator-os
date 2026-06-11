BEGIN;

ALTER TABLE public.auto_post_queue
  ADD COLUMN IF NOT EXISTS hook_type TEXT,
  ADD COLUMN IF NOT EXISTS topic_label TEXT,
  ADD COLUMN IF NOT EXISTS format_type TEXT,
  ADD COLUMN IF NOT EXISTS emotional_frame TEXT,
  ADD COLUMN IF NOT EXISTS reply_mechanism TEXT,
  ADD COLUMN IF NOT EXISTS content_length_bucket TEXT,
  ADD COLUMN IF NOT EXISTS media_style TEXT,
  ADD COLUMN IF NOT EXISTS posting_hour INTEGER,
  ADD COLUMN IF NOT EXISTS prompt_version TEXT,
  ADD COLUMN IF NOT EXISTS template_id TEXT,
  ADD COLUMN IF NOT EXISTS model_provider TEXT,
  ADD COLUMN IF NOT EXISTS source_pattern_id TEXT;

ALTER TABLE public.posts
  ADD COLUMN IF NOT EXISTS hook_type TEXT,
  ADD COLUMN IF NOT EXISTS topic_label TEXT,
  ADD COLUMN IF NOT EXISTS format_type TEXT,
  ADD COLUMN IF NOT EXISTS emotional_frame TEXT,
  ADD COLUMN IF NOT EXISTS reply_mechanism TEXT,
  ADD COLUMN IF NOT EXISTS content_length_bucket TEXT,
  ADD COLUMN IF NOT EXISTS media_style TEXT,
  ADD COLUMN IF NOT EXISTS posting_hour INTEGER,
  ADD COLUMN IF NOT EXISTS prompt_version TEXT,
  ADD COLUMN IF NOT EXISTS template_id TEXT,
  ADD COLUMN IF NOT EXISTS model_provider TEXT,
  ADD COLUMN IF NOT EXISTS source_pattern_id TEXT,
  ADD COLUMN IF NOT EXISTS auto_post_queue_id TEXT;

ALTER TABLE public.auto_post_queue
  DROP CONSTRAINT IF EXISTS auto_post_queue_posting_hour_check;
ALTER TABLE public.auto_post_queue
  ADD CONSTRAINT auto_post_queue_posting_hour_check
  CHECK (posting_hour IS NULL OR posting_hour BETWEEN 0 AND 23);

ALTER TABLE public.posts
  DROP CONSTRAINT IF EXISTS posts_posting_hour_check;
ALTER TABLE public.posts
  ADD CONSTRAINT posts_posting_hour_check
  CHECK (posting_hour IS NULL OR posting_hour BETWEEN 0 AND 23);

UPDATE public.auto_post_queue q
SET
  content_length_bucket = CASE
    WHEN length(COALESCE(q.content, '')) = 0 THEN 'empty'
    WHEN length(COALESCE(q.content, '')) <= 40 THEN 'micro'
    WHEN length(COALESCE(q.content, '')) <= 120 THEN 'short'
    WHEN length(COALESCE(q.content, '')) <= 280 THEN 'medium'
    ELSE 'long'
  END,
  hook_type = COALESCE(q.hook_type, CASE
    WHEN COALESCE(q.content, '') ~ '\?$' THEN 'question'
    WHEN COALESCE(q.content, '') ~* '\b(unpopular opinion|hot take|be honest|controversial)\b' THEN 'hot_take'
    WHEN COALESCE(q.content, '') ~* '^\s*(i|we|my|today|yesterday|last night)\b' THEN 'personal_statement'
    WHEN COALESCE(q.content, '') ~* '\b([0-9]+\.|top [0-9]+|reasons|ways)\b' THEN 'list'
    WHEN length(COALESCE(q.content, '')) <= 40 THEN 'short_statement'
    ELSE 'statement'
  END),
  topic_label = COALESCE(NULLIF(q.topic_label, ''), NULLIF(q.topic_tag, ''), 'uncategorized'),
  emotional_frame = COALESCE(q.emotional_frame, CASE
    WHEN COALESCE(q.content, '') ~* '\b(lonely|miss|sad|cry|hurt|anxious|scared)\b' THEN 'vulnerable'
    WHEN COALESCE(q.content, '') ~* '\b(happy|excited|love|cute|pretty|sweet)\b' THEN 'warm'
    WHEN COALESCE(q.content, '') ~* '\b(annoyed|mad|angry|hate|tired)\b' THEN 'frustrated'
    WHEN COALESCE(q.content, '') ~* '\b(would you|do you|am i|be honest|tell me)\b' THEN 'inviting'
    ELSE 'neutral'
  END),
  reply_mechanism = COALESCE(q.reply_mechanism, CASE
    WHEN COALESCE(q.content, '') ~* '\b(would you|do you|am i|should i|be honest)\b' THEN 'direct_prompt'
    WHEN COALESCE(q.content, '') ~ '\?$' THEN 'question'
    WHEN COALESCE(q.content, '') ~* '\b(confession|i admit|not gonna lie)\b' THEN 'confession'
    ELSE 'none'
  END),
  media_style = COALESCE(q.media_style, CASE
    WHEN COALESCE(array_length(q.media_urls, 1), 0) > 0 THEN 'image'
    ELSE 'text_only'
  END),
  format_type = COALESCE(q.format_type, CASE
    WHEN COALESCE(array_length(q.media_urls, 1), 0) > 0 THEN 'media_post'
    WHEN q.hook_type = 'list' THEN 'list_post'
    WHEN q.hook_type = 'question' THEN 'question_post'
    WHEN q.hook_type = 'hot_take' THEN 'hot_take_post'
    ELSE 'text_post'
  END),
  posting_hour = COALESCE(
    q.posting_hour,
    CASE
      WHEN COALESCE(q.scheduled_for, q.posted_at, q.created_at) IS NULL THEN NULL
      ELSE EXTRACT(HOUR FROM COALESCE(q.scheduled_for, q.posted_at, q.created_at))::integer
    END
  )
WHERE q.hook_type IS NULL
   OR q.topic_label IS NULL
   OR q.format_type IS NULL
   OR q.emotional_frame IS NULL
   OR q.reply_mechanism IS NULL
   OR q.content_length_bucket IS NULL
   OR q.media_style IS NULL
   OR q.posting_hour IS NULL;

UPDATE public.posts p
SET
  auto_post_queue_id = COALESCE(p.auto_post_queue_id, p.metadata->>'autoPostQueueId'),
  hook_type = COALESCE(p.hook_type, q.hook_type),
  topic_label = COALESCE(p.topic_label, q.topic_label, NULLIF(p.topic_tag, ''), 'uncategorized'),
  format_type = COALESCE(p.format_type, q.format_type),
  emotional_frame = COALESCE(p.emotional_frame, q.emotional_frame),
  reply_mechanism = COALESCE(p.reply_mechanism, q.reply_mechanism),
  content_length_bucket = COALESCE(p.content_length_bucket, q.content_length_bucket),
  media_style = COALESCE(p.media_style, q.media_style),
  posting_hour = COALESCE(
    p.posting_hour,
    q.posting_hour,
    CASE
      WHEN p.published_at IS NULL THEN NULL
      ELSE EXTRACT(HOUR FROM p.published_at)::integer
    END
  ),
  prompt_version = COALESCE(p.prompt_version, q.prompt_version),
  template_id = COALESCE(p.template_id, q.template_id),
  model_provider = COALESCE(p.model_provider, q.model_provider, q.ai_provider),
  source_pattern_id = COALESCE(p.source_pattern_id, q.source_pattern_id, q.source_id)
FROM public.auto_post_queue q
WHERE q.id::text = COALESCE(p.auto_post_queue_id, p.metadata->>'autoPostQueueId');

UPDATE public.posts p
SET
  content_length_bucket = CASE
    WHEN length(COALESCE(p.content, '')) = 0 THEN 'empty'
    WHEN length(COALESCE(p.content, '')) <= 40 THEN 'micro'
    WHEN length(COALESCE(p.content, '')) <= 120 THEN 'short'
    WHEN length(COALESCE(p.content, '')) <= 280 THEN 'medium'
    ELSE 'long'
  END,
  hook_type = COALESCE(p.hook_type, CASE
    WHEN COALESCE(p.content, '') ~ '\?$' THEN 'question'
    WHEN COALESCE(p.content, '') ~* '\b(unpopular opinion|hot take|be honest|controversial)\b' THEN 'hot_take'
    WHEN COALESCE(p.content, '') ~* '^\s*(i|we|my|today|yesterday|last night)\b' THEN 'personal_statement'
    WHEN COALESCE(p.content, '') ~* '\b([0-9]+\.|top [0-9]+|reasons|ways)\b' THEN 'list'
    WHEN length(COALESCE(p.content, '')) <= 40 THEN 'short_statement'
    ELSE 'statement'
  END),
  topic_label = COALESCE(p.topic_label, NULLIF(p.topic_tag, ''), 'uncategorized'),
  emotional_frame = COALESCE(p.emotional_frame, CASE
    WHEN COALESCE(p.content, '') ~* '\b(lonely|miss|sad|cry|hurt|anxious|scared)\b' THEN 'vulnerable'
    WHEN COALESCE(p.content, '') ~* '\b(happy|excited|love|cute|pretty|sweet)\b' THEN 'warm'
    WHEN COALESCE(p.content, '') ~* '\b(annoyed|mad|angry|hate|tired)\b' THEN 'frustrated'
    WHEN COALESCE(p.content, '') ~* '\b(would you|do you|am i|be honest|tell me)\b' THEN 'inviting'
    ELSE 'neutral'
  END),
  reply_mechanism = COALESCE(p.reply_mechanism, CASE
    WHEN COALESCE(p.content, '') ~* '\b(would you|do you|am i|should i|be honest)\b' THEN 'direct_prompt'
    WHEN COALESCE(p.content, '') ~ '\?$' THEN 'question'
    WHEN COALESCE(p.content, '') ~* '\b(confession|i admit|not gonna lie)\b' THEN 'confession'
    ELSE 'none'
  END),
  media_style = COALESCE(p.media_style, CASE
    WHEN COALESCE(array_length(p.media_urls, 1), 0) > 0 THEN 'image'
    ELSE 'text_only'
  END),
  format_type = COALESCE(p.format_type, CASE
    WHEN COALESCE(array_length(p.media_urls, 1), 0) > 0 THEN 'media_post'
    WHEN p.hook_type = 'list' THEN 'list_post'
    WHEN p.hook_type = 'question' THEN 'question_post'
    WHEN p.hook_type = 'hot_take' THEN 'hot_take_post'
    ELSE 'text_post'
  END),
  posting_hour = COALESCE(
    p.posting_hour,
    CASE
      WHEN p.published_at IS NULL THEN NULL
      ELSE EXTRACT(HOUR FROM p.published_at)::integer
    END
  )
WHERE p.hook_type IS NULL
   OR p.topic_label IS NULL
   OR p.format_type IS NULL
   OR p.emotional_frame IS NULL
   OR p.reply_mechanism IS NULL
   OR p.content_length_bucket IS NULL
   OR p.media_style IS NULL
   OR p.posting_hour IS NULL;

CREATE INDEX IF NOT EXISTS idx_posts_autoposter_pattern_account
  ON public.posts(account_id, hook_type, topic_label, published_at DESC)
  WHERE status = 'published';

CREATE INDEX IF NOT EXISTS idx_posts_autoposter_pattern_group
  ON public.posts(cross_post_group_id, format_type, posting_hour, published_at DESC)
  WHERE status = 'published';

CREATE INDEX IF NOT EXISTS idx_auto_post_queue_pattern_group
  ON public.auto_post_queue(workspace_id, group_id, hook_type, topic_label, scheduled_for DESC);

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
    source_pattern_id
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
    COALESCE(v_queue.source_pattern_id, v_queue.source_id)
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
    source_pattern_id
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
    ),
    p_queue_item_id,
    v_queue.hook_type,
    COALESCE(v_queue.topic_label, v_queue.topic_tag, 'uncategorized'),
    v_queue.format_type,
    v_queue.emotional_frame,
    v_queue.reply_mechanism,
    v_queue.content_length_bucket,
    v_queue.media_style,
    COALESCE(v_queue.posting_hour, EXTRACT(HOUR FROM v_queue.external_published_at)::integer),
    v_queue.prompt_version,
    v_queue.template_id,
    COALESCE(v_queue.model_provider, v_queue.ai_provider),
    COALESCE(v_queue.source_pattern_id, v_queue.source_id)
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

GRANT EXECUTE ON FUNCTION public.reconcile_autoposter_publish(TEXT) TO service_role;

COMMIT;
