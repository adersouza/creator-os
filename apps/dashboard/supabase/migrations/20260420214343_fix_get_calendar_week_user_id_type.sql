-- Placeholder — applied directly on remote (out-of-band) on 2026-04-20.
-- Fix: original 20260418050000 declared v_user as uuid and compared against
-- text user_id columns, raising 42883 "operator does not exist: text = uuid"
-- every call. Remote version flipped v_user to text := auth.uid()::text.
--
-- This file exists so `supabase db push` sees a local-matches-remote history.
-- The authoritative function body lives on remote in pg_proc; fetch with
-- `supabase db query --linked "SELECT pg_get_functiondef(oid) FROM pg_proc
-- WHERE proname='get_calendar_week'"` if you need to reconstruct locally.
-- The local 20260418050000 file also still contains the original (broken)
-- body — that's fine because this remote fix always runs AFTER it on any
-- fresh environment, replacing the function with the correct text version.

SELECT 1 WHERE false;
