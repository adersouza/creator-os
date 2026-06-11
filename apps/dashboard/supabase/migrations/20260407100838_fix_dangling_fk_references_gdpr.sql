-- Reconstructed from schema_migrations on prod (remote-only).
-- version: 20260407100838
-- applied-by: fix_dangling_fk_references_gdpr migration row


DO $$
BEGIN
  DROP VIEW IF EXISTS public.instagram_posts;

  IF to_regclass('public.posts') IS NOT NULL THEN
    ALTER TABLE public.posts DROP CONSTRAINT IF EXISTS posts_approved_by_fkey;
    ALTER TABLE public.posts DROP CONSTRAINT IF EXISTS posts_rejected_by_fkey;

    IF EXISTS (
      SELECT 1
      FROM information_schema.columns
      WHERE table_schema = 'public'
        AND table_name = 'posts'
        AND column_name = 'approved_by'
    ) THEN
      ALTER TABLE public.posts
        ALTER COLUMN approved_by TYPE text USING approved_by::text;

      IF to_regclass('public.profiles') IS NOT NULL THEN
        BEGIN
          ALTER TABLE public.posts
            ADD CONSTRAINT posts_approved_by_fkey
            FOREIGN KEY (approved_by) REFERENCES public.profiles(id) ON DELETE SET NULL;
        EXCEPTION
          WHEN duplicate_object OR datatype_mismatch OR undefined_column THEN
            NULL;
        END;
      END IF;
    END IF;

    IF EXISTS (
      SELECT 1
      FROM information_schema.columns
      WHERE table_schema = 'public'
        AND table_name = 'posts'
        AND column_name = 'rejected_by'
    ) AND to_regclass('public.profiles') IS NOT NULL THEN
      BEGIN
        ALTER TABLE public.posts
          ADD CONSTRAINT posts_rejected_by_fkey
          FOREIGN KEY (rejected_by) REFERENCES public.profiles(id) ON DELETE SET NULL;
      EXCEPTION
        WHEN duplicate_object OR datatype_mismatch OR undefined_column THEN
          NULL;
      END;
    END IF;

    IF EXISTS (
      SELECT 1
      FROM information_schema.columns
      WHERE table_schema = 'public'
        AND table_name = 'posts'
        AND column_name = 'platform'
    ) THEN
      EXECUTE 'CREATE OR REPLACE VIEW public.instagram_posts AS SELECT * FROM public.posts WHERE platform = ''instagram''';
    END IF;
  END IF;

  IF to_regclass('public.workspace_invites') IS NOT NULL THEN
    ALTER TABLE public.workspace_invites DROP CONSTRAINT IF EXISTS workspace_invites_invited_by_fkey;

    IF EXISTS (
      SELECT 1
      FROM information_schema.columns
      WHERE table_schema = 'public'
        AND table_name = 'workspace_invites'
        AND column_name = 'invited_by'
    ) AND to_regclass('public.profiles') IS NOT NULL THEN
      BEGIN
        ALTER TABLE public.workspace_invites
          ADD CONSTRAINT workspace_invites_invited_by_fkey
          FOREIGN KEY (invited_by) REFERENCES public.profiles(id) ON DELETE SET NULL;
      EXCEPTION
        WHEN duplicate_object OR datatype_mismatch OR undefined_column THEN
          NULL;
      END;
    END IF;
  END IF;

  IF to_regclass('public.workspace_members') IS NOT NULL THEN
    ALTER TABLE public.workspace_members DROP CONSTRAINT IF EXISTS workspace_members_invited_by_fkey;

    IF EXISTS (
      SELECT 1
      FROM information_schema.columns
      WHERE table_schema = 'public'
        AND table_name = 'workspace_members'
        AND column_name = 'invited_by'
    ) AND to_regclass('public.profiles') IS NOT NULL THEN
      BEGIN
        ALTER TABLE public.workspace_members
          ADD CONSTRAINT workspace_members_invited_by_fkey
          FOREIGN KEY (invited_by) REFERENCES public.profiles(id) ON DELETE SET NULL;
      EXCEPTION
        WHEN duplicate_object OR datatype_mismatch OR undefined_column THEN
          NULL;
      END;
    END IF;
  END IF;
END $$;
