-- Threads views-by-source capture (Analytics Wave 2 A1).
--
-- The native Threads API (since July 2025) exposes /me/threads_insights?metric=
-- views&breakdown=source with six source buckets: home, profile, search,
-- activity, ig, fb. This unlocks the "Views by source" evidence tile (spec
-- §2 / Threads + All) — previously a Wave 3 EmptyEvidenceTile because the
-- ingestion wasn't wired.
--
-- Stored as JSONB so we don't need a column per source; the shape is
-- { home, profile, search, activity, ig, fb } (any subset — absent keys
-- imply zero).
--
-- Companion: 20260425000001_upsert_analytics_atomic_v5.sql updates the RPC
-- to pass the new field through.

ALTER TABLE account_analytics
  ADD COLUMN IF NOT EXISTS threads_views_by_source JSONB DEFAULT NULL;
