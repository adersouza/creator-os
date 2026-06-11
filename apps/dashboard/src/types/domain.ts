/**
 * Re-export canonical domain types from their sources.
 *
 * This module exists as a convenient import point for the data pipeline types.
 * The actual types live in their original locations for backward compatibility.
 *
 * The table-row aliases at the bottom wrap the auto-generated 8k-line
 * supabase.ts so callers don't have to write
 * `Database['public']['Tables']['posts']['Row']` every time they touch a
 * Supabase row — that verbosity made imports noisy and hid intent in the
 * pages layer. Prefer these aliases in new code; the Database type stays
 * available for advanced narrowing.
 */

import type { Database } from "./supabase";

export type { InstagramAccount, PostStatus, ThreadPost } from "./index";
export type {
	AccountAnalyticsRow,
	AnalyticsStats,
	MappedAnalyticsRow,
	PostPerformance,
} from "./analytics";

type Tables = Database["public"]["Tables"];

export type Post = Tables["posts"]["Row"];
export type PostInsert = Tables["posts"]["Insert"];
export type PostUpdate = Tables["posts"]["Update"];

export type Account = Tables["accounts"]["Row"];
export type AccountInsert = Tables["accounts"]["Insert"];
export type AccountUpdate = Tables["accounts"]["Update"];

export type InstagramAccountRow = Tables["instagram_accounts"]["Row"];
export type InstagramAccountInsert = Tables["instagram_accounts"]["Insert"];
export type InstagramAccountUpdate = Tables["instagram_accounts"]["Update"];

export type AccountGroup = Tables["account_groups"]["Row"];
export type AccountGroupInsert = Tables["account_groups"]["Insert"];
export type AccountGroupUpdate = Tables["account_groups"]["Update"];

export type AccountAnalytics = Tables["account_analytics"]["Row"];
export type AccountMetricsHistory = Tables["account_metrics_history"]["Row"];
