-- Links redesign phases 1-2: block taxonomy storage, pixel metadata,
-- server-side block events, and visitor ordering signals.

ALTER TABLE public.smart_links
  ADD COLUMN IF NOT EXISTS items JSONB NOT NULL DEFAULT '[]'::jsonb,
  ADD COLUMN IF NOT EXISTS blocks JSONB NOT NULL DEFAULT '[]'::jsonb,
  ADD COLUMN IF NOT EXISTS utm JSONB NOT NULL DEFAULT '{}'::jsonb,
  ADD COLUMN IF NOT EXISTS theme TEXT,
  ADD COLUMN IF NOT EXISTS metadata JSONB NOT NULL DEFAULT '{}'::jsonb;

UPDATE public.smart_links
SET blocks = COALESCE(NULLIF(blocks, '[]'::jsonb), items, '[]'::jsonb)
WHERE blocks = '[]'::jsonb;

ALTER TABLE public.smart_link_clicks
  ADD COLUMN IF NOT EXISTS block_id TEXT,
  ADD COLUMN IF NOT EXISTS event_name TEXT,
  ADD COLUMN IF NOT EXISTS utm_content VARCHAR(100);

CREATE INDEX IF NOT EXISTS idx_smart_link_clicks_block_event
  ON public.smart_link_clicks(smart_link_id, block_id, event_name, clicked_at DESC);

ALTER TABLE public.link_clicks
  ADD COLUMN IF NOT EXISTS event_name TEXT;

CREATE TABLE IF NOT EXISTS public.link_visitor_signals (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  link_page_id UUID NOT NULL REFERENCES public.smart_links(id) ON DELETE CASCADE,
  fingerprint TEXT NOT NULL,
  referrer TEXT,
  visited_blocks TEXT[] DEFAULT '{}',
  last_seen TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_link_visitor_signals
  ON public.link_visitor_signals(link_page_id, fingerprint);

ALTER TABLE public.link_visitor_signals ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "service_role_all" ON public.link_visitor_signals;
CREATE POLICY "service_role_all" ON public.link_visitor_signals FOR ALL
  USING ((SELECT auth.jwt()->>'role') = 'service_role')
  WITH CHECK ((SELECT auth.jwt()->>'role') = 'service_role');
