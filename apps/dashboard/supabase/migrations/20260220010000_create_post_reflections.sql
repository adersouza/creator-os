-- Post-publish reflections: did this post meet expectations?
create table if not exists post_reflections (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  post_id uuid not null,
  met_expectations boolean not null,
  created_at timestamptz not null default now(),
  unique (user_id, post_id)
);

alter table post_reflections enable row level security;

create policy "Users can insert their own reflections"
  on post_reflections for insert
  with check (auth.uid() = user_id);

create policy "Users can read their own reflections"
  on post_reflections for select
  using (auth.uid() = user_id);
