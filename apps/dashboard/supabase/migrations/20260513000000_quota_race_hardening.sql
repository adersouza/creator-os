-- Advisory-lock-backed create RPCs for quota-sensitive link objects.
-- Keeps the quota check and insert in one transaction.

BEGIN;

CREATE OR REPLACE FUNCTION public.create_smart_link_with_quota(
  p_user_id text,
  p_limit integer,
  p_payload jsonb
)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $function$
DECLARE
  v_row public.smart_links%ROWTYPE;
BEGIN
  PERFORM pg_advisory_xact_lock(hashtext('smart_links:' || p_user_id));

  IF (
    SELECT COUNT(*) FROM public.smart_links WHERE user_id = p_user_id
  ) >= p_limit THEN
    RAISE EXCEPTION 'QUOTA_EXCEEDED: smart link limit reached';
  END IF;

  INSERT INTO public.smart_links (
    user_id,
    code,
    target_url,
    title,
    ig_deep_link,
    threads_deep_link,
    ig_redirect_url,
    threads_redirect_url,
    mobile_redirect_url,
    enable_deep_links,
    webhook_secret,
    post_id,
    est_conversion_rate,
    est_conversion_value
  )
  VALUES (
    p_user_id,
    p_payload->>'code',
    p_payload->>'target_url',
    NULLIF(p_payload->>'title', ''),
    NULLIF(p_payload->>'ig_deep_link', ''),
    NULLIF(p_payload->>'threads_deep_link', ''),
    NULL,
    NULL,
    NULL,
    COALESCE((p_payload->>'enable_deep_links')::boolean, true),
    p_payload->>'webhook_secret',
    NULLIF(p_payload->>'post_id', ''),
    NULLIF(p_payload->>'est_conversion_rate', '')::numeric,
    NULLIF(p_payload->>'est_conversion_value', '')::numeric
  )
  RETURNING * INTO v_row;

  RETURN to_jsonb(v_row);
END;
$function$;

CREATE OR REPLACE FUNCTION public.create_link_page_with_quota(
  p_user_id text,
  p_limit integer,
  p_payload jsonb
)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $function$
DECLARE
  v_row public.link_pages%ROWTYPE;
BEGIN
  PERFORM pg_advisory_xact_lock(hashtext('link_pages:' || p_user_id));

  IF (
    SELECT COUNT(*) FROM public.link_pages WHERE user_id = p_user_id
  ) >= p_limit THEN
    RAISE EXCEPTION 'QUOTA_EXCEEDED: link page limit reached';
  END IF;

  INSERT INTO public.link_pages (
    user_id,
    slug,
    title,
    bio,
    avatar_url,
    background_color,
    brand_color,
    promo_text,
    enable_deeplink_escape,
    age_gate,
    age_gate_message,
    tracking_pixels
  )
  VALUES (
    p_user_id,
    p_payload->>'slug',
    p_payload->>'title',
    NULLIF(p_payload->>'bio', ''),
    NULLIF(p_payload->>'avatar_url', ''),
    COALESCE(NULLIF(p_payload->>'background_color', ''), '#0a0a0b'),
    COALESCE(NULLIF(p_payload->>'brand_color', ''), '#ff6b9d'),
    NULLIF(p_payload->>'promo_text', ''),
    COALESCE((p_payload->>'enable_deeplink_escape')::boolean, false),
    COALESCE((p_payload->>'age_gate')::boolean, false),
    NULLIF(p_payload->>'age_gate_message', ''),
    p_payload->'tracking_pixels'
  )
  RETURNING * INTO v_row;

  RETURN to_jsonb(v_row);
END;
$function$;

CREATE OR REPLACE FUNCTION public.create_link_item_with_quota(
  p_user_id text,
  p_page_id uuid,
  p_limit integer,
  p_payload jsonb
)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $function$
DECLARE
  v_position integer;
  v_row public.link_items%ROWTYPE;
BEGIN
  PERFORM pg_advisory_xact_lock(hashtext('link_items:' || p_page_id::text));

  IF NOT EXISTS (
    SELECT 1 FROM public.link_pages
    WHERE id = p_page_id AND user_id = p_user_id
  ) THEN
    RAISE EXCEPTION 'NOT_FOUND: link page not found';
  END IF;

  SELECT COUNT(*) INTO v_position
  FROM public.link_items
  WHERE page_id = p_page_id;

  IF v_position >= p_limit THEN
    RAISE EXCEPTION 'QUOTA_EXCEEDED: link item limit reached';
  END IF;

  INSERT INTO public.link_items (
    page_id,
    title,
    url,
    icon,
    position,
    is_primary,
    platform,
    deep_link_url,
    redirect_id,
    style,
    deep_link_config
  )
  VALUES (
    p_page_id,
    p_payload->>'title',
    p_payload->>'url',
    NULLIF(p_payload->>'icon', ''),
    v_position,
    COALESCE((p_payload->>'is_primary')::boolean, false),
    NULLIF(p_payload->>'platform', ''),
    NULLIF(p_payload->>'deep_link_url', ''),
    p_payload->>'redirect_id',
    p_payload->'style',
    p_payload->'deep_link_config'
  )
  RETURNING * INTO v_row;

  RETURN to_jsonb(v_row);
END;
$function$;

REVOKE EXECUTE ON FUNCTION public.create_smart_link_with_quota(text, integer, jsonb) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.create_link_page_with_quota(text, integer, jsonb) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.create_link_item_with_quota(text, uuid, integer, jsonb) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.create_smart_link_with_quota(text, integer, jsonb) TO service_role;
GRANT EXECUTE ON FUNCTION public.create_link_page_with_quota(text, integer, jsonb) TO service_role;
GRANT EXECUTE ON FUNCTION public.create_link_item_with_quota(text, uuid, integer, jsonb) TO service_role;

COMMIT;
