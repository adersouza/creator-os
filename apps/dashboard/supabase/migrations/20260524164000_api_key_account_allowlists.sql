alter table public.api_keys
  add column if not exists allowed_account_ids text[] default null;

comment on column public.api_keys.allowed_account_ids is
  'Optional account allowlist for public API/MCP keys. Null or empty means all accounts owned by the key user; non-empty means only those account IDs are accessible.';

create index if not exists idx_api_keys_allowed_account_ids
  on public.api_keys using gin (allowed_account_ids);
