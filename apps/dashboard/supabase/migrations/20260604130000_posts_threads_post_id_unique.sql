-- Enforce one canonical local posts row per externally published Threads post.
CREATE UNIQUE INDEX IF NOT EXISTS posts_threads_post_id_unique
ON public.posts(threads_post_id)
WHERE threads_post_id IS NOT NULL;
