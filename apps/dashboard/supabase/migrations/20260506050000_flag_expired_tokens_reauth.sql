-- One-time repair for expired connected-account tokens that were still marked
-- publishable. Runtime guards in token-refresh + health-monitor keep this at 0.

DO $$
DECLARE
  target_table text;
  set_parts text[];
BEGIN
  FOREACH target_table IN ARRAY ARRAY['accounts', 'instagram_accounts']
  LOOP
    IF to_regclass(format('public.%I', target_table)) IS NULL THEN
      CONTINUE;
    END IF;

    IF NOT EXISTS (
      SELECT 1
      FROM information_schema.columns
      WHERE table_schema = 'public'
        AND table_name = target_table
        AND column_name IN ('token_expires_at', 'needs_reauth')
      GROUP BY table_name
      HAVING count(*) = 2
    ) THEN
      CONTINUE;
    END IF;

    set_parts := ARRAY['needs_reauth = true'];

    IF EXISTS (
      SELECT 1 FROM information_schema.columns
      WHERE table_schema = 'public' AND table_name = target_table AND column_name = 'status'
    ) THEN
      set_parts := array_append(set_parts, 'status = ''needs_reauth''');
    END IF;

    IF EXISTS (
      SELECT 1 FROM information_schema.columns
      WHERE table_schema = 'public' AND table_name = target_table AND column_name = 'is_active'
    ) THEN
      set_parts := array_append(set_parts, 'is_active = false');
    END IF;

    IF EXISTS (
      SELECT 1 FROM information_schema.columns
      WHERE table_schema = 'public' AND table_name = target_table AND column_name = 'updated_at'
    ) THEN
      set_parts := array_append(set_parts, 'updated_at = now()');
    END IF;

    EXECUTE format(
      'UPDATE public.%I SET %s WHERE token_expires_at < now() AND needs_reauth = false',
      target_table,
      array_to_string(set_parts, ', ')
    );
  END LOOP;
END $$;
