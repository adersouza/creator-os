-- Operator control plane foundation for the 10/10 agent manager roadmap.

create table if not exists public.agent_action_intents (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  workspace_id text,
  group_id text,
  account_id text,
  action_name text not null,
  risk_level text not null default 'medium',
  status text not null default 'pending' check (status in ('pending', 'approved', 'rejected', 'expired', 'consumed')),
  normalized_payload jsonb not null default '{}'::jsonb,
  payload_hash text not null,
  content_hash text,
  idempotency_key text,
  approval_id uuid,
  required_reviewer_role text,
  expires_at timestamptz not null default (now() + interval '24 hours'),
  consumed_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists agent_action_intents_user_status_idx
  on public.agent_action_intents(user_id, status, expires_at desc);
create unique index if not exists agent_action_intents_user_hash_idx
  on public.agent_action_intents(user_id, action_name, payload_hash)
  where status in ('pending', 'approved');

alter table public.agent_action_intents enable row level security;

drop policy if exists "Users can read own agent action intents" on public.agent_action_intents;
create policy "Users can read own agent action intents"
  on public.agent_action_intents for select
  using (auth.uid() = user_id);

create table if not exists public.operator_tasks (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  workspace_id text,
  group_id text,
  account_id text,
  source text not null,
  source_id text,
  title text not null,
  description text,
  priority text not null default 'medium' check (priority in ('low', 'medium', 'high', 'critical')),
  status text not null default 'open' check (status in ('open', 'assigned', 'in_progress', 'snoozed', 'resolved', 'ignored')),
  assigned_to uuid,
  due_at timestamptz,
  sla_at timestamptz,
  snoozed_until timestamptz,
  recommended_action jsonb not null default '{}'::jsonb,
  linked_entity_type text,
  linked_entity_id text,
  resolution_reason text,
  resolved_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists operator_tasks_user_status_priority_idx
  on public.operator_tasks(user_id, status, priority, due_at nulls last);
create index if not exists operator_tasks_scope_idx
  on public.operator_tasks(user_id, workspace_id, group_id, account_id);
create unique index if not exists operator_tasks_user_source_unique_idx
  on public.operator_tasks(user_id, source, source_id)
  where source_id is not null and status not in ('resolved', 'ignored');

alter table public.operator_tasks enable row level security;

drop policy if exists "Users manage own operator tasks" on public.operator_tasks;
create policy "Users manage own operator tasks"
  on public.operator_tasks for all
  using (auth.uid() = user_id)
  with check (auth.uid() = user_id);

create table if not exists public.manager_goals (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  workspace_id text,
  group_id text,
  account_id text,
  metric text not null,
  baseline numeric,
  target numeric,
  deadline date,
  priority text not null default 'medium',
  constraints jsonb not null default '{}'::jsonb,
  status text not null default 'active' check (status in ('active', 'paused', 'completed', 'archived')),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.manager_cycles (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  objective text not null,
  status text not null default 'open' check (status in ('open', 'running', 'blocked', 'completed', 'cancelled')),
  started_at timestamptz not null default now(),
  completed_at timestamptz,
  evidence_snapshot jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create table if not exists public.manager_plans (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  cycle_id uuid references public.manager_cycles(id) on delete set null,
  goal_id uuid references public.manager_goals(id) on delete set null,
  title text not null,
  status text not null default 'draft' check (status in ('draft', 'pending_approval', 'approved', 'running', 'completed', 'cancelled')),
  confidence numeric,
  risk_level text not null default 'medium',
  expected_outcome jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.manager_plan_items (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  plan_id uuid not null references public.manager_plans(id) on delete cascade,
  title text not null,
  status text not null default 'pending' check (status in ('pending', 'blocked', 'approved', 'running', 'completed', 'failed', 'cancelled')),
  selected_action jsonb not null default '{}'::jsonb,
  alternatives jsonb not null default '[]'::jsonb,
  confidence numeric,
  risk_level text not null default 'medium',
  approval_id uuid,
  intent_id uuid references public.agent_action_intents(id) on delete set null,
  expected_outcome jsonb not null default '{}'::jsonb,
  actual_outcome jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.manager_decisions (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  plan_item_id uuid references public.manager_plan_items(id) on delete set null,
  scope jsonb not null default '{}'::jsonb,
  decision_type text not null,
  options_json jsonb not null default '[]'::jsonb,
  selected_option jsonb not null default '{}'::jsonb,
  evidence_refs jsonb not null default '[]'::jsonb,
  confidence numeric,
  risk_level text not null default 'medium',
  approval_id uuid,
  action_hash text,
  expected_outcome jsonb not null default '{}'::jsonb,
  actual_outcome jsonb,
  review_status text not null default 'unreviewed' check (review_status in ('unreviewed', 'accepted', 'rejected', 'needs_followup')),
  created_at timestamptz not null default now()
);

alter table public.manager_goals enable row level security;
alter table public.manager_cycles enable row level security;
alter table public.manager_plans enable row level security;
alter table public.manager_plan_items enable row level security;
alter table public.manager_decisions enable row level security;

drop policy if exists "Users manage own manager goals" on public.manager_goals;
create policy "Users manage own manager goals" on public.manager_goals for all using (auth.uid() = user_id) with check (auth.uid() = user_id);
drop policy if exists "Users manage own manager cycles" on public.manager_cycles;
create policy "Users manage own manager cycles" on public.manager_cycles for all using (auth.uid() = user_id) with check (auth.uid() = user_id);
drop policy if exists "Users manage own manager plans" on public.manager_plans;
create policy "Users manage own manager plans" on public.manager_plans for all using (auth.uid() = user_id) with check (auth.uid() = user_id);
drop policy if exists "Users manage own manager plan items" on public.manager_plan_items;
create policy "Users manage own manager plan items" on public.manager_plan_items for all using (auth.uid() = user_id) with check (auth.uid() = user_id);
drop policy if exists "Users manage own manager decisions" on public.manager_decisions;
create policy "Users manage own manager decisions" on public.manager_decisions for all using (auth.uid() = user_id) with check (auth.uid() = user_id);
