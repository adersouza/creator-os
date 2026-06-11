create or replace function public.claim_auto_post_queue_item_for_publish(
	p_queue_item_id text,
	p_schedule_nonce text default null,
	p_claim_token text default null,
	p_claim_expires_at timestamptz default null,
	p_now timestamptz default now()
)
returns table(id text)
language sql
set search_path = public
as $$
	update public.auto_post_queue q
	set
		status = 'publishing',
		claimed_at = p_now,
		claim_token = coalesce(p_claim_token, gen_random_uuid()::text),
		claim_expires_at = coalesce(
			p_claim_expires_at,
			p_now + interval '10 minutes'
		)
	where q.id = p_queue_item_id
		and to_regclass('public.auto_post_queue') is not null
		and q.status in ('pending', 'queued')
		and q.scheduled_for <= p_now
		and (q.next_retry_at is null or q.next_retry_at <= p_now)
		and (
			(p_schedule_nonce is null and q.schedule_nonce is null)
			or (p_schedule_nonce is not null and q.schedule_nonce = p_schedule_nonce)
		)
		and (
			q.claim_token is null
			or q.claim_expires_at is null
			or q.claim_expires_at <= p_now
		)
	returning q.id;
$$;

do $$
begin
	if to_regprocedure('public.claim_auto_post_queue_item_for_publish(text,text,text,timestamptz,timestamptz)') is not null then
		revoke all on function public.claim_auto_post_queue_item_for_publish(
			text,
			text,
			text,
			timestamptz,
			timestamptz
		) from public;

		grant execute on function public.claim_auto_post_queue_item_for_publish(
			text,
			text,
			text,
			timestamptz,
			timestamptz
		) to service_role;
	end if;
end $$;
