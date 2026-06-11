-- Co-Pilot session memory: stores extracted user preferences
create table if not exists copilot_memory (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  key text not null,
  value text not null,
  updated_at timestamptz not null default now(),
  unique (user_id, key)
);

-- RLS: users can only access their own rows
alter table copilot_memory enable row level security;

DO $$ BEGIN
  create policy "Users own their copilot memory"
    on copilot_memory for all
    using (auth.uid() = user_id)
    with check (auth.uid() = user_id);
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

-- Index for fast lookups
create index if not exists idx_copilot_memory_user_id on copilot_memory(user_id);
