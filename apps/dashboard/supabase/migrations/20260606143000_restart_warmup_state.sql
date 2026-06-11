alter table public.account_autoposter_state
	add column if not exists restart_warmup_status text not null default 'none',
	add column if not exists restart_warmup_started_at timestamptz,
	add column if not exists restart_warmup_day integer,
	add column if not exists restart_warmup_allowed_posts_per_day integer,
	add column if not exists restart_warmup_reason text,
	add column if not exists restart_warmup_next_ramp_at timestamptz,
	add column if not exists restart_warmup_last_post_views integer,
	add column if not exists restart_warmup_last_evaluated_at timestamptz;

alter table public.account_autoposter_state
	drop constraint if exists account_autoposter_restart_warmup_status_check;

alter table public.account_autoposter_state
	add constraint account_autoposter_restart_warmup_status_check
	check (
		restart_warmup_status in (
			'none',
			'warming',
			'held',
			'completed',
			'suppressed'
		)
	);

create index if not exists account_autoposter_restart_warmup_idx
	on public.account_autoposter_state (
		workspace_id,
		group_id,
		restart_warmup_status,
		restart_warmup_next_ramp_at
	);
