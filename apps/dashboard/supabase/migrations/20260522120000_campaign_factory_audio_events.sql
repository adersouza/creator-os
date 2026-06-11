-- Durable native-audio state history for Campaign Factory draft/review posts.

create table if not exists public.campaign_factory_audio_events (
  id uuid primary key default gen_random_uuid(),
  user_id text not null references public.profiles(id) on delete cascade,
  post_id text not null references public.posts(id) on delete cascade,
  campaign_id text,
  rendered_asset_id text,
  action text not null check (
    action in (
      'apply_first_recommendation',
      'selected',
      'attached',
      'verified',
      'skipped',
      'blocked'
    )
  ),
  previous_status text,
  next_status text,
  platform_audio_id text,
  platform_url text,
  proof_complete boolean not null default false,
  note text,
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create index if not exists campaign_factory_audio_events_user_created_idx
  on public.campaign_factory_audio_events(user_id, created_at desc);

create index if not exists campaign_factory_audio_events_post_created_idx
  on public.campaign_factory_audio_events(post_id, created_at desc);

create index if not exists campaign_factory_audio_events_campaign_idx
  on public.campaign_factory_audio_events(user_id, campaign_id)
  where campaign_id is not null;

create index if not exists campaign_factory_audio_events_asset_idx
  on public.campaign_factory_audio_events(user_id, rendered_asset_id)
  where rendered_asset_id is not null;

alter table public.campaign_factory_audio_events enable row level security;

drop policy if exists "Users read own Campaign Factory audio events"
  on public.campaign_factory_audio_events;
create policy "Users read own Campaign Factory audio events"
  on public.campaign_factory_audio_events for select
  using (auth.uid()::text = user_id);

drop policy if exists "Users insert own Campaign Factory audio events"
  on public.campaign_factory_audio_events;
create policy "Users insert own Campaign Factory audio events"
  on public.campaign_factory_audio_events for insert
  with check (auth.uid()::text = user_id);
