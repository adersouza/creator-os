-- Authoritative server-owned audit trail for operator dry-run, approval, and execute paths.

create table if not exists public.operator_action_audit_logs (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  actor_user_id uuid not null references auth.users(id) on delete cascade,
  phase text not null check (phase in ('dry-run', 'request-approval', 'execute')),
  action_name text not null,
  risk_level text,
  workspace_id text,
  group_id text,
  account_id text,
  scope jsonb not null default '{}'::jsonb,
  payload_hash text,
  body_hash text,
  content_hash text,
  intent_id uuid references public.agent_action_intents(id) on delete set null,
  approval_id uuid,
  idempotency_key text,
  outcome text not null check (outcome in ('attempted', 'success', 'failure')),
  message text,
  error text,
  request_method text,
  request_path text,
  ip_address text,
  user_agent text,
  request_id text,
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create index if not exists operator_action_audit_logs_user_created_idx
  on public.operator_action_audit_logs(user_id, created_at desc);
create index if not exists operator_action_audit_logs_intent_idx
  on public.operator_action_audit_logs(intent_id, created_at desc)
  where intent_id is not null;
create index if not exists operator_action_audit_logs_phase_outcome_idx
  on public.operator_action_audit_logs(phase, outcome, created_at desc);
create index if not exists operator_action_audit_logs_scope_idx
  on public.operator_action_audit_logs(user_id, workspace_id, group_id, account_id);

alter table public.operator_action_audit_logs enable row level security;

drop policy if exists "Users can read own operator action audit logs" on public.operator_action_audit_logs;
create policy "Users can read own operator action audit logs"
  on public.operator_action_audit_logs for select
  using ((select auth.uid()) = user_id);

-- The route marks pending intents as needs_review after an approval request is opened.
alter table public.agent_action_intents
  drop constraint if exists agent_action_intents_status_check;
alter table public.agent_action_intents
  add constraint agent_action_intents_status_check
  check (status in ('pending', 'needs_review', 'approved', 'rejected', 'expired', 'consumed'));

drop index if exists public.agent_action_intents_user_hash_idx;
create unique index agent_action_intents_user_hash_idx
  on public.agent_action_intents(user_id, action_name, payload_hash)
  where status in ('pending', 'needs_review', 'approved');
