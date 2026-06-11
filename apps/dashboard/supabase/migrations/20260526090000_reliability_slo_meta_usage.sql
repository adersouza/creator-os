-- Reliability Center rollups and Meta API usage telemetry.
-- These tables are written by service-role API handlers and read through
-- authenticated API routes, not directly by browser clients.

create table if not exists public.reliability_slo_snapshots (
	id uuid primary key default gen_random_uuid(),
	user_id text not null,
	workspace_id text,
	window_start timestamptz not null,
	window_end timestamptz not null,
	window_hours integer not null default 24,
	scheduled_total integer not null default 0,
	published_total integer not null default 0,
	failed_total integer not null default 0,
	on_time_60s integer not null default 0,
	late_over_5m integer not null default 0,
	success_rate numeric(6,2) not null default 100,
	on_time_rate numeric(6,2) not null default 100,
	p50_drift_seconds integer not null default 0,
	p95_drift_seconds integer not null default 0,
	p99_drift_seconds integer not null default 0,
	max_drift_seconds integer not null default 0,
	avg_drift_seconds integer not null default 0,
	qstash_failures integer not null default 0,
	dlq_count integer not null default 0,
	backlog_count integer not null default 0,
	impacted_account_ids text[] not null default '{}',
	tone text not null default 'healthy' check (tone in ('healthy', 'warning', 'critical')),
	created_at timestamptz not null default now(),
	updated_at timestamptz not null default now(),
	unique (user_id, window_start, window_end)
);

create index if not exists idx_reliability_slo_snapshots_user_window
	on public.reliability_slo_snapshots (user_id, window_end desc);

alter table public.reliability_slo_snapshots enable row level security;

drop policy if exists "Users can read own reliability slo snapshots" on public.reliability_slo_snapshots;
create policy "Users can read own reliability slo snapshots"
	on public.reliability_slo_snapshots
	for select
	to authenticated
	using (user_id = (select auth.uid())::text);

drop policy if exists "Service role manages reliability slo snapshots" on public.reliability_slo_snapshots;
create policy "Service role manages reliability slo snapshots"
	on public.reliability_slo_snapshots
	for all
	to service_role
	using (true)
	with check (true);

create table if not exists public.meta_api_usage_snapshots (
	id uuid primary key default gen_random_uuid(),
	user_id text,
	workspace_id text,
	account_id text,
	platform text not null check (platform in ('instagram', 'threads', 'meta')),
	endpoint_family text not null,
	status integer,
	meta_code text,
	meta_subcode text,
	app_usage jsonb,
	business_usage jsonb,
	usage_percent numeric(6,2),
	retry_after_seconds integer,
	request_id text,
	tone text not null default 'healthy' check (tone in ('healthy', 'warning', 'critical')),
	captured_at timestamptz not null default now()
);

create index if not exists idx_meta_api_usage_snapshots_user_captured
	on public.meta_api_usage_snapshots (user_id, captured_at desc);

create index if not exists idx_meta_api_usage_snapshots_account_captured
	on public.meta_api_usage_snapshots (account_id, captured_at desc);

alter table public.meta_api_usage_snapshots enable row level security;

drop policy if exists "Users can read own meta api usage snapshots" on public.meta_api_usage_snapshots;
create policy "Users can read own meta api usage snapshots"
	on public.meta_api_usage_snapshots
	for select
	to authenticated
	using (user_id = (select auth.uid())::text or user_id is null);

drop policy if exists "Service role manages meta api usage snapshots" on public.meta_api_usage_snapshots;
create policy "Service role manages meta api usage snapshots"
	on public.meta_api_usage_snapshots
	for all
	to service_role
	using (true)
	with check (true);
