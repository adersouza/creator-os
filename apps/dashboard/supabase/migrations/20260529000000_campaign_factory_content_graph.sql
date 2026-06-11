-- Campaign Factory canonical content graph mirror.
-- Campaign Factory remains the source of truth; these tables make the graph
-- queryable inside ThreadsDashboard for filters, analytics joins, and future UI.

CREATE TABLE IF NOT EXISTS public.campaign_factory_entities (
  global_id TEXT PRIMARY KEY,
  entity_type TEXT NOT NULL,
  campaign_id TEXT,
  local_table TEXT,
  local_id TEXT,
  payload JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS campaign_factory_entities_campaign_idx
  ON public.campaign_factory_entities(campaign_id, entity_type);

CREATE TABLE IF NOT EXISTS public.campaign_factory_edges (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  from_global_id TEXT NOT NULL REFERENCES public.campaign_factory_entities(global_id) ON DELETE CASCADE,
  to_global_id TEXT NOT NULL REFERENCES public.campaign_factory_entities(global_id) ON DELETE CASCADE,
  relation_type TEXT NOT NULL,
  campaign_id TEXT,
  evidence JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE(from_global_id, to_global_id, relation_type)
);

CREATE INDEX IF NOT EXISTS campaign_factory_edges_from_idx
  ON public.campaign_factory_edges(from_global_id, relation_type);

CREATE INDEX IF NOT EXISTS campaign_factory_edges_to_idx
  ON public.campaign_factory_edges(to_global_id, relation_type);

CREATE TABLE IF NOT EXISTS public.campaign_factory_post_links (
  post_id TEXT PRIMARY KEY REFERENCES public.posts(id) ON DELETE CASCADE,
  user_id TEXT NOT NULL REFERENCES public.profiles(id) ON DELETE CASCADE,
  post_graph_id TEXT,
  campaign_id TEXT,
  campaign_graph_id TEXT,
  source_asset_id TEXT,
  source_asset_graph_id TEXT,
  rendered_asset_id TEXT,
  rendered_asset_graph_id TEXT,
  audit_graph_id TEXT,
  media_id UUID REFERENCES public.media(id) ON DELETE SET NULL,
  status TEXT,
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS campaign_factory_post_links_user_campaign_idx
  ON public.campaign_factory_post_links(user_id, campaign_id);

CREATE INDEX IF NOT EXISTS campaign_factory_post_links_rendered_idx
  ON public.campaign_factory_post_links(user_id, rendered_asset_id)
  WHERE rendered_asset_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS campaign_factory_post_links_rendered_graph_idx
  ON public.campaign_factory_post_links(user_id, rendered_asset_graph_id)
  WHERE rendered_asset_graph_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS campaign_factory_post_links_post_graph_idx
  ON public.campaign_factory_post_links(user_id, post_graph_id)
  WHERE post_graph_id IS NOT NULL;

ALTER TABLE public.campaign_factory_entities ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.campaign_factory_edges ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.campaign_factory_post_links ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Users can view own campaign factory entities"
  ON public.campaign_factory_entities;
CREATE POLICY "Users can view own campaign factory entities"
  ON public.campaign_factory_entities FOR SELECT
  USING (
    EXISTS (
      SELECT 1
      FROM public.campaign_factory_post_links l
      WHERE l.user_id = auth.uid()::text
        AND (
          l.campaign_graph_id = campaign_factory_entities.global_id
          OR l.source_asset_graph_id = campaign_factory_entities.global_id
          OR l.rendered_asset_graph_id = campaign_factory_entities.global_id
          OR l.audit_graph_id = campaign_factory_entities.global_id
          OR l.post_graph_id = campaign_factory_entities.global_id
        )
    )
  );

DROP POLICY IF EXISTS "Users can view own campaign factory edges"
  ON public.campaign_factory_edges;
CREATE POLICY "Users can view own campaign factory edges"
  ON public.campaign_factory_edges FOR SELECT
  USING (
    EXISTS (
      SELECT 1
      FROM public.campaign_factory_entities e
      JOIN public.campaign_factory_post_links l
        ON l.user_id = auth.uid()::text
       AND (
          l.campaign_graph_id = e.global_id
          OR l.source_asset_graph_id = e.global_id
          OR l.rendered_asset_graph_id = e.global_id
          OR l.audit_graph_id = e.global_id
          OR l.post_graph_id = e.global_id
       )
      WHERE e.global_id IN (campaign_factory_edges.from_global_id, campaign_factory_edges.to_global_id)
    )
  );

DROP POLICY IF EXISTS "Users can view own campaign factory post links"
  ON public.campaign_factory_post_links;
CREATE POLICY "Users can view own campaign factory post links"
  ON public.campaign_factory_post_links FOR SELECT
  USING (auth.uid()::text = user_id);

GRANT ALL ON public.campaign_factory_entities TO service_role;
GRANT ALL ON public.campaign_factory_edges TO service_role;
GRANT ALL ON public.campaign_factory_post_links TO service_role;
