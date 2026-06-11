-- DB audit repair: reconcile live schema with app expectations after partial/manual
-- migration application. Keep this migration idempotent because several related
-- migrations were already applied outside Supabase migration history.

begin;

-- Campaign Factory graph mirror tables were present in local migrations but absent
-- from production. They are service-role writable and user-readable through linked
-- post ownership.
create table if not exists public.campaign_factory_entities (
  global_id text primary key,
  entity_type text not null,
  campaign_id text,
  local_table text,
  local_id text,
  payload jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists campaign_factory_entities_campaign_idx
  on public.campaign_factory_entities(campaign_id, entity_type);

create table if not exists public.campaign_factory_edges (
  id uuid primary key default gen_random_uuid(),
  from_global_id text not null references public.campaign_factory_entities(global_id) on delete cascade,
  to_global_id text not null references public.campaign_factory_entities(global_id) on delete cascade,
  relation_type text not null,
  campaign_id text,
  evidence jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  unique(from_global_id, to_global_id, relation_type)
);

create index if not exists campaign_factory_edges_from_idx
  on public.campaign_factory_edges(from_global_id, relation_type);

create index if not exists campaign_factory_edges_to_idx
  on public.campaign_factory_edges(to_global_id, relation_type);

create table if not exists public.campaign_factory_post_links (
  post_id text primary key references public.posts(id) on delete cascade,
  user_id text not null references public.profiles(id) on delete cascade,
  post_graph_id text,
  campaign_id text,
  campaign_graph_id text,
  source_asset_id text,
  source_asset_graph_id text,
  rendered_asset_id text,
  rendered_asset_graph_id text,
  audit_graph_id text,
  media_id text references public.media(id) on delete set null,
  status text,
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

alter table if exists public.campaign_factory_post_links
  add column if not exists draft_key text,
  add column if not exists media_key text,
  add column if not exists post_key text,
  add column if not exists export_run_id text;

create index if not exists campaign_factory_post_links_user_campaign_idx
  on public.campaign_factory_post_links(user_id, campaign_id);

create index if not exists campaign_factory_post_links_rendered_idx
  on public.campaign_factory_post_links(user_id, rendered_asset_id)
  where rendered_asset_id is not null;

create index if not exists campaign_factory_post_links_rendered_graph_idx
  on public.campaign_factory_post_links(user_id, rendered_asset_graph_id)
  where rendered_asset_graph_id is not null;

create index if not exists campaign_factory_post_links_post_graph_idx
  on public.campaign_factory_post_links(user_id, post_graph_id)
  where post_graph_id is not null;

create unique index if not exists campaign_factory_post_links_user_post_key_uniq
  on public.campaign_factory_post_links(user_id, post_key)
  where post_key is not null;

create index if not exists campaign_factory_post_links_export_run_idx
  on public.campaign_factory_post_links(user_id, export_run_id)
  where export_run_id is not null;

create unique index if not exists media_storage_path_uniq
  on public.media(storage_path)
  where storage_path is not null;

alter table if exists public.campaign_factory_entities enable row level security;
alter table if exists public.campaign_factory_edges enable row level security;
alter table if exists public.campaign_factory_post_links enable row level security;

do $$
begin
  if to_regclass('public.campaign_factory_entities') is not null then
    drop policy if exists "Users can view own campaign factory entities"
      on public.campaign_factory_entities;
    execute $policy$
      create policy "Users can view own campaign factory entities"
      on public.campaign_factory_entities
      for select
      to authenticated
      using (
        exists (
          select 1
          from public.campaign_factory_post_links l
          where l.user_id = (select auth.uid())::text
            and (
              l.campaign_graph_id = campaign_factory_entities.global_id
              or l.source_asset_graph_id = campaign_factory_entities.global_id
              or l.rendered_asset_graph_id = campaign_factory_entities.global_id
              or l.audit_graph_id = campaign_factory_entities.global_id
              or l.post_graph_id = campaign_factory_entities.global_id
            )
        )
      )
    $policy$;
  end if;

  if to_regclass('public.campaign_factory_edges') is not null then
    drop policy if exists "Users can view own campaign factory edges"
      on public.campaign_factory_edges;
    execute $policy$
      create policy "Users can view own campaign factory edges"
      on public.campaign_factory_edges
      for select
      to authenticated
      using (
        exists (
          select 1
          from public.campaign_factory_entities e
          join public.campaign_factory_post_links l
            on l.user_id = (select auth.uid())::text
           and (
              l.campaign_graph_id = e.global_id
              or l.source_asset_graph_id = e.global_id
              or l.rendered_asset_graph_id = e.global_id
              or l.audit_graph_id = e.global_id
              or l.post_graph_id = e.global_id
           )
          where e.global_id in (
            campaign_factory_edges.from_global_id,
            campaign_factory_edges.to_global_id
          )
        )
      )
    $policy$;
  end if;

  if to_regclass('public.campaign_factory_post_links') is not null then
    drop policy if exists "Users can view own campaign factory post links"
      on public.campaign_factory_post_links;
    execute $policy$
      create policy "Users can view own campaign factory post links"
      on public.campaign_factory_post_links
      for select
      to authenticated
      using ((select auth.uid())::text = user_id)
    $policy$;
  end if;
end $$;

grant all on public.campaign_factory_entities to service_role;
grant all on public.campaign_factory_edges to service_role;
grant all on public.campaign_factory_post_links to service_role;

-- The backend writes this structured explanation; production was missing the
-- column while code already inserts it.
alter table if exists public.queue_fill_log
  add column if not exists strategy_summary jsonb not null default '{}'::jsonb;

alter table if exists public.auto_post_queue
  add column if not exists updated_at timestamptz not null default now(),
  add column if not exists provenance jsonb not null default '{}'::jsonb;

-- These RPCs are only called from service-role API/cron code. Remove public
-- execution drift while preserving service-role access.
do $$
begin
  if to_regprocedure(
    'public.finalize_autoposter_publish(text,text,text,text,text,text,text,jsonb,text,timestamptz)'
  ) is not null then
    revoke execute on function public.finalize_autoposter_publish(
      text, text, text, text, text, text, text, jsonb, text, timestamptz
    ) from anon, authenticated, public;
    grant execute on function public.finalize_autoposter_publish(
      text, text, text, text, text, text, text, jsonb, text, timestamptz
    ) to service_role;
  end if;

  if to_regprocedure('public.reconcile_autoposter_publish(text)') is not null then
    revoke execute on function public.reconcile_autoposter_publish(text)
      from anon, authenticated, public;
    grant execute on function public.reconcile_autoposter_publish(text)
      to service_role;
  end if;
end $$;

-- These tables currently have RLS enabled with no user policies and are only
-- used by backend/service-role flows. Tighten table grants so later policy work
-- cannot accidentally expose rows through stale broad privileges.
revoke all on table public.creator_dna from anon, authenticated;
revoke all on table public.account_flavor from anon, authenticated;
do $$
begin
  if to_regclass('public.creator_identity_shape_usage') is not null then
    revoke all on table public.creator_identity_shape_usage from anon, authenticated;
  end if;
end $$;

grant all on table public.creator_dna to service_role;
grant all on table public.account_flavor to service_role;
do $$
begin
  if to_regclass('public.creator_identity_shape_usage') is not null then
    grant all on table public.creator_identity_shape_usage to service_role;
  end if;
end $$;

commit;
