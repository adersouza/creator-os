-- Repair production storage drift by normalizing the public-serving buckets
-- and adding the user-scoped storage.objects policies expected by the app.

insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values
	(
		'media',
		'media',
		true,
		52428800,
		array['image/jpeg','image/png','image/gif','image/webp','video/mp4','video/quicktime','video/webm']
	),
	(
		'post-media',
		'post-media',
		true,
		104857600,
		array['image/jpeg','image/png','image/gif','image/webp','video/mp4','video/quicktime','video/webm']
	),
	(
		'avatars',
		'avatars',
		true,
		5242880,
		array['image/jpeg','image/png','image/webp']
	),
	(
		'whitelabel',
		'whitelabel',
		true,
		5242880,
		array['image/jpeg','image/png','image/webp','image/svg+xml']
	)
on conflict (id) do update set
	name = excluded.name,
	public = excluded.public,
	file_size_limit = excluded.file_size_limit,
	allowed_mime_types = excluded.allowed_mime_types;

drop policy if exists "Juno users upload own storage files" on storage.objects;
drop policy if exists "Juno users list own storage files" on storage.objects;
drop policy if exists "Juno users update own storage files" on storage.objects;
drop policy if exists "Juno users delete own storage files" on storage.objects;

create policy "Juno users upload own storage files"
on storage.objects for insert
to authenticated
with check (
	bucket_id in ('media', 'post-media', 'avatars', 'whitelabel')
	and (select auth.uid())::text = (storage.foldername(name))[1]
);

create policy "Juno users list own storage files"
on storage.objects for select
to authenticated
using (
	bucket_id in ('media', 'post-media', 'avatars', 'whitelabel')
	and (select auth.uid())::text = (storage.foldername(name))[1]
);

create policy "Juno users update own storage files"
on storage.objects for update
to authenticated
using (
	bucket_id in ('media', 'post-media', 'avatars', 'whitelabel')
	and (select auth.uid())::text = (storage.foldername(name))[1]
)
with check (
	bucket_id in ('media', 'post-media', 'avatars', 'whitelabel')
	and (select auth.uid())::text = (storage.foldername(name))[1]
);

create policy "Juno users delete own storage files"
on storage.objects for delete
to authenticated
using (
	bucket_id in ('media', 'post-media', 'avatars', 'whitelabel')
	and (select auth.uid())::text = (storage.foldername(name))[1]
);
