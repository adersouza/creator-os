-- Add unique constraint on (user_id, threads_user_id) for the accounts table
-- Required for Supabase upsert onConflict: "user_id,threads_user_id" in the
-- Threads OAuth callback. Without this, the upsert fails with a DB error.
-- NULLs in threads_user_id are treated as distinct, so rows without a
-- threads_user_id are unaffected.

CREATE UNIQUE INDEX IF NOT EXISTS accounts_user_id_threads_user_id_key
ON public.accounts (user_id, threads_user_id);
