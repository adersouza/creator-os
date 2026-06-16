create table if not exists public.autoposter_control_events (
  id uuid primary key default gen_random_uuid(),
  workspace_id text not null references public.workspaces(id) on delete cascade,
  action text not null,
  old_state jsonb not null default '{}'::jsonb,
  new_state jsonb not null default '{}'::jsonb,
  reason text not null,
  actor text,
  dry_run boolean not null default true,
  created_at timestamptz not null default now()
);

create index if not exists idx_autoposter_control_events_workspace_created
  on public.autoposter_control_events(workspace_id, created_at desc);

alter table if exists public.autoposter_control_events enable row level security;

drop policy if exists "autoposter_control_events_owner_select" on public.autoposter_control_events;
do $$
begin
  if to_regclass('public.autoposter_control_events') is not null
    and not exists (
      select 1
      from pg_policies
      where schemaname = 'public'
        and tablename = 'autoposter_control_events'
        and policyname = 'autoposter_control_events_owner_select'
    )
  then
    execute $policy$
      create policy "autoposter_control_events_owner_select"
        on public.autoposter_control_events
        for select
        to authenticated
        using (
          workspace_id in (
            select id from public.workspaces where owner_id = (select auth.uid())::text
          )
        )
    $policy$;
  end if;
end $$;

grant select on public.autoposter_control_events to authenticated;
grant all on public.autoposter_control_events to service_role;

comment on table public.autoposter_control_events is
  'Audit trail for server-owned autoposter control-plane actions such as pause, resume, and drain.';
