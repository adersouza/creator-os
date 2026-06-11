-- P0-07: Hierarchical operator kill switches.
-- Core IDs are text; api_keys.id remains uuid.

create table if not exists public.operator_kill_switches (
  id uuid primary key default gen_random_uuid(),
  user_id text not null references public.profiles(id) on delete cascade,
  scope_type text not null check (scope_type in ('global', 'workspace', 'group', 'account', 'session', 'api_key')),
  scope_id text,
  action_name text,
  min_risk_level text check (min_risk_level in ('low', 'medium', 'high', 'critical')),
  reason text not null,
  is_active boolean not null default true,
  expires_at timestamptz,
  created_by text references public.profiles(id) on delete set null,
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint operator_kill_switches_scope_id_check check (
    (scope_type = 'global' and scope_id is null)
    or (scope_type <> 'global' and scope_id is not null)
  )
);

create index if not exists operator_kill_switches_user_active_idx
  on public.operator_kill_switches(user_id, is_active, scope_type, scope_id)
  where is_active = true;

create index if not exists operator_kill_switches_expiry_idx
  on public.operator_kill_switches(expires_at)
  where is_active = true and expires_at is not null;

create index if not exists operator_kill_switches_action_idx
  on public.operator_kill_switches(user_id, action_name, min_risk_level)
  where is_active = true;

alter table public.operator_kill_switches enable row level security;

drop policy if exists "Users manage own operator kill switches" on public.operator_kill_switches;
create policy "Users manage own operator kill switches"
  on public.operator_kill_switches for all
  using ((select auth.uid())::text = user_id)
  with check ((select auth.uid())::text = user_id);

grant select, insert, update, delete on public.operator_kill_switches to authenticated;
grant select, insert, update, delete on public.operator_kill_switches to service_role;

comment on table public.operator_kill_switches is
  'Hierarchical kill switches for operator-approved outbound/high-risk actions.';
comment on column public.operator_kill_switches.scope_type is
  'global, workspace, group, account, session, or api_key.';
comment on column public.operator_kill_switches.scope_id is
  'Null only for global scope; otherwise the matching workspace/group/account/session/api key id.';
comment on column public.operator_kill_switches.action_name is
  'Optional exact operator action name; null blocks every action at the matching scope.';
comment on column public.operator_kill_switches.min_risk_level is
  'Optional minimum risk level to block; null blocks all risk levels.';
