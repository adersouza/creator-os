-- Reply Chain Pulse: track how deep the conversation goes on each Threads post.
--
-- Depth semantics:
--   1 = root post only (no replies)
--   2 = at least one direct reply to the root
--   3 = at least one reply-to-a-reply
--   N = longest chain of replies from root
--
-- Sync path (api/_lib/handlers/threads/replyChainSync.ts):
--   GET /v1.0/{threads-post-id}/conversation?fields=id,replied_to,timestamp
--   → build tree from replied_to.id edges → BFS depth from root = reply_depth
--
-- Surfaced in Analytics' Threads-filter block as "Reply Chain Pulse" — %% of
-- posts at depth >= 4 is the Mosseri-favored conversation-quality signal.

ALTER TABLE public.posts
  ADD COLUMN IF NOT EXISTS reply_depth SMALLINT,
  ADD COLUMN IF NOT EXISTS reply_chain_synced_at TIMESTAMPTZ;

-- Index to quickly find posts that need a fresh reply-chain sync.
-- now() can't live in the predicate (must be IMMUTABLE), so the 24h-stale
-- filter is applied at query time by the cron. Sort key is
-- (reply_chain_synced_at NULLS FIRST, published_at DESC) so the cron's
-- ORDER BY reply_chain_synced_at ASC NULLS FIRST picks the oldest-stale
-- row in O(log N) via a direct index scan.
CREATE INDEX IF NOT EXISTS idx_posts_reply_chain_stale
  ON public.posts (reply_chain_synced_at NULLS FIRST, published_at DESC)
  WHERE status = 'published'
    AND threads_post_id IS NOT NULL;

COMMENT ON COLUMN public.posts.reply_depth IS
  'Longest reply-chain depth for this Threads post. 1 = root only, 2 = direct reply, 3+ = nested. Synced via /v1.0/{id}/conversation. NULL until first sync.';
COMMENT ON COLUMN public.posts.reply_chain_synced_at IS
  'Last time reply_depth was refreshed from the Threads conversation endpoint. Sync job targets posts stale > 24h.';
