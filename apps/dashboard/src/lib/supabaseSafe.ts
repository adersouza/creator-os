/**
 * Null-safe Supabase query helpers (frontend copy).
 *
 * Mirror of api/_lib/supabaseSafe.ts — kept as a sibling instead of
 * shared because the frontend and backend use different Supabase client
 * types and cross-boundary imports break both Vite and Vercel's bundlers.
 *
 * Supabase's `.neq()` emits SQL `col <> 'val'`, which drops rows where
 * `col IS NULL` — see docs/claude/GOTCHAS.md.
 *
 *   // BEFORE (silently drops NULL rows):
 *   query.neq("status", "suspended");
 *
 *   // AFTER (keeps NULL rows):
 *   query = neqOrNull(query, "status", "suspended");
 */

// biome-ignore lint/suspicious/noExplicitAny: Supabase query builder type is version-fluid.
type Query = any;

export function neqOrNull(query: Query, column: string, value: string | number | boolean): Query {
	return query.or(`${column}.is.null,${column}.neq.${value}`);
}

export function neqStrict(query: Query, column: string, value: string | number | boolean): Query {
	return query.not(column, "is", null).neq(column, value);
}

export function eqOrNull(query: Query, column: string, value: string | number | boolean): Query {
	return query.or(`${column}.is.null,${column}.eq.${value}`);
}
