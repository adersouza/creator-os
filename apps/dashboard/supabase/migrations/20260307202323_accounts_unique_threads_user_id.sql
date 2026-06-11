-- Applied via schema reconciliation 2026-03-07
-- Required for Supabase upsert onConflict: "user_id,threads_user_id" in Threads OAuth callback

CREATE UNIQUE INDEX IF NOT EXISTS accounts_user_id_threads_user_id_key
ON public.accounts (user_id, threads_user_id);
