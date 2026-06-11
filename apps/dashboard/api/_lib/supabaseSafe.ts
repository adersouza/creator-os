/**
 * Null-safe Supabase query helpers.
 *
 * Supabase's `.neq()` emits SQL `col <> 'val'`, which in Postgres evaluates
 * to NULL for rows where `col IS NULL` — and NULL rows are then silently
 * excluded from the result set. That behavior has bitten us multiple times
 * (analytics filters losing active accounts, cron jobs skipping un-labeled
 * rows). See docs/claude/GOTCHAS.md.
 *
 * These helpers wrap the PostgREST string-builder so the intent is obvious
 * at the call site:
 *
 *   // BEFORE (silently drops NULL rows):
 *   query.neq("status", "suspended");
 *
 *   // AFTER (keeps NULL rows):
 *   query = neqOrNull(query, "status", "suspended");
 *
 * The helpers are untyped on the query parameter because Supabase's
 * PostgrestFilterBuilder generic signature changes between versions and
 * we don't want to couple to it.
 */

// biome-ignore lint/suspicious/noExplicitAny: Supabase query builder type is version-fluid.
type Query = any;

/**
 * Filter `col != value` while keeping rows where `col IS NULL`.
 * Emits PostgREST `or=(col.is.null,col.neq.value)`.
 *
 * Use this for nullable columns where "not the forbidden value" should
 * include unset rows — e.g. `status != 'suspended'` should match accounts
 * with no status yet.
 */
export function neqOrNull(query: Query, column: string, value: string | number | boolean): Query {
	return query.or(`${column}.is.null,${column}.neq.${value}`);
}

/**
 * Filter `col != value` AND `col IS NOT NULL`.
 * Use this when NULL is meaningless and should be excluded — e.g. comparing
 * two IDs where a NULL target ID is a bug, not a match.
 */
export function neqStrict(query: Query, column: string, value: string | number | boolean): Query {
	return query.not(column, "is", null).neq(column, value);
}

/**
 * Filter `col = value OR col IS NULL`.
 * Use when the column is optional and absence should be treated as a match
 * (e.g., `approval_status = 'approved' OR NULL` means "not rejected").
 */
export function eqOrNull(query: Query, column: string, value: string | number | boolean): Query {
	return query.or(`${column}.is.null,${column}.eq.${value}`);
}
