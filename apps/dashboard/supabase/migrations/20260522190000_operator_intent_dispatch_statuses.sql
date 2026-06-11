-- Allow approved operator intents to be claimed before side effects and marked failed.

alter table public.agent_action_intents
  drop constraint if exists agent_action_intents_status_check;

alter table public.agent_action_intents
  add constraint agent_action_intents_status_check
  check (status in (
    'pending',
    'needs_review',
    'approved',
    'dispatching',
    'failed',
    'rejected',
    'expired',
    'consumed'
  ));

drop index if exists public.agent_action_intents_user_hash_idx;
create unique index agent_action_intents_user_hash_idx
  on public.agent_action_intents(user_id, action_name, payload_hash)
  where status in ('pending', 'needs_review', 'approved', 'dispatching');
