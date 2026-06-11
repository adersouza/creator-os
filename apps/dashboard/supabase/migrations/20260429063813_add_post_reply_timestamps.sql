-- Reply timestamp persistence for the velocity-histogram tile.
--
-- The replyChainSync cron already fetches reply timestamps from
-- /v1.0/{id}/conversation?fields=id,replied_to,timestamp but discards
-- them after computing reply_depth. This column persists the timestamp
-- array so /api/analytics?action=reply-depth-leaders can return a
-- per-hour velocity histogram for the winner thread without making
-- additional Threads API calls per dashboard render.
--
-- Storage: BIGINT[] of unix epoch seconds, sorted ascending.
-- Idempotency: cron overwrites the array on every sync (SET, not append).
-- NULL = never synced. '{}' = synced but no replies.

ALTER TABLE public.posts
  ADD COLUMN IF NOT EXISTS reply_timestamps BIGINT[];

COMMENT ON COLUMN public.posts.reply_timestamps IS
  'Sorted array of reply timestamps (unix epoch seconds) for this Threads post. Synced by replyChainSync cron alongside reply_depth. NULL = never synced; ''{}'' = synced but no replies.';
