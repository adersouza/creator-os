-- Persist live AI/operator eval snapshots for regression tracking.

create table if not exists public.ai_eval_snapshots (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  workspace_id text,
  group_id text,
  account_id text,
  suite_name text not null,
  case_id text not null,
  category text not null,
  prompt text not null,
  prompt_hash text not null,
  provider text not null,
  model text not null,
  model_version text,
  parameters jsonb not null default '{}'::jsonb,
  candidate_outputs jsonb not null default '[]'::jsonb,
  filter_results jsonb not null default '[]'::jsonb,
  judge_scores jsonb not null default '[]'::jsonb,
  selected_output jsonb,
  selected_output_id text,
  inserted_ids text[] not null default '{}'::text[],
  scheduled_ids text[] not null default '{}'::text[],
  performance_snapshot jsonb not null default '{}'::jsonb,
  regression_score numeric,
  passed boolean not null default false,
  failures jsonb not null default '[]'::jsonb,
  metadata jsonb not null default '{}'::jsonb,
  captured_at timestamptz not null default now(),
  created_at timestamptz not null default now()
);

create index if not exists ai_eval_snapshots_user_suite_idx
  on public.ai_eval_snapshots(user_id, suite_name, captured_at desc);

create index if not exists ai_eval_snapshots_prompt_hash_idx
  on public.ai_eval_snapshots(user_id, prompt_hash, captured_at desc);

create index if not exists ai_eval_snapshots_scope_idx
  on public.ai_eval_snapshots(user_id, workspace_id, group_id, account_id);

alter table public.ai_eval_snapshots enable row level security;

drop policy if exists "Users read own AI eval snapshots" on public.ai_eval_snapshots;
create policy "Users read own AI eval snapshots"
  on public.ai_eval_snapshots for select
  using (auth.uid() = user_id);

drop policy if exists "Users insert own AI eval snapshots" on public.ai_eval_snapshots;
create policy "Users insert own AI eval snapshots"
  on public.ai_eval_snapshots for insert
  with check (auth.uid() = user_id);
