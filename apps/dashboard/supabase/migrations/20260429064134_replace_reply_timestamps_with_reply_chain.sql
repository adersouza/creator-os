-- Replace reply_timestamps int8[] (added 20260429000000) with a richer
-- JSONB shape that supports both the velocity histogram (Bug 13) and
-- the text-bearing reply tree (Bug 15). No data has been written to
-- reply_timestamps yet — the cron change shipping the population code
-- never deployed — so dropping is non-destructive.
ALTER TABLE public.posts
  DROP COLUMN IF EXISTS reply_timestamps;

-- Cached reply chain from Threads /conversation endpoint. Stores per-reply
-- id / replied_to / timestamp / username / text. Sorted ascending by
-- timestamp. Powers two surfaces:
--   - Velocity histogram (ConvWinner tile)
--   - Text-bearing reply tree (ConvQuality tile)
-- Cron writes via SET on every sync (idempotent). NULL = never synced;
-- '[]' = synced but no replies.
ALTER TABLE public.posts
  ADD COLUMN IF NOT EXISTS reply_chain JSONB;

COMMENT ON COLUMN public.posts.reply_chain IS
  'Cached reply chain from Threads /conversation endpoint. JSONB array of {id, replied_to, timestamp, username, text}, sorted ascending by timestamp. NULL = never synced; ''[]'' = synced but no replies. Powers velocity histogram + reply-tree tile.';
