/**
 * Data mappers — normalize Supabase row shapes into canonical domain types.
 *
 * Column name variants (views_count vs views, likes_count vs likes, etc.)
 * are resolved ONCE here, not scattered across consumers.
 */

import type { InstagramAccount, PostStatus, ThreadPost } from "@/types/index";

// ─── Post Row → ThreadPost ──────────────────────────────────────────────────

/**
 * Map a raw Supabase `posts` row into a ThreadPost.
 * Handles all known column name variants (views_count/views, etc.)
 */
export function mapPostRow(row: Record<string, unknown>): ThreadPost {
	// For Threads: views_count is the primary metric
	// For Instagram: ig_reach/ig_impressions is the equivalent — fold it into views
	// so WeeklyRecap and other components that read performance.views work cross-platform
	const rawViews = Number(row.views_count ?? row.views ?? 0);
	const igReachVal = Number(row.ig_reach ?? 0);
	const views = rawViews > 0 ? rawViews : igReachVal;
	const likes = Number(row.likes_count ?? row.likes ?? 0);
	const replies = Number(
		row.replies_count ?? row.ig_comment_count ?? row.replies ?? 0,
	);
	const reposts = Number(row.reposts_count ?? row.reposts ?? 0);
	const quotes = Number(row.quotes_count ?? row.quotes ?? 0);
	const shares = Number(row.shares_count ?? row.ig_shares ?? 0);

	return {
		// Spread raw row first so domain fields override snake_case duplicates
		...row,

		id: String(row.id ?? ""),
		content: String(row.content ?? ""),
		status: (row.status as PostStatus) ?? ("draft" as PostStatus),
		platform: (row.platform as ThreadPost["platform"]) ?? undefined,
		accountId: String(row.account_id ?? ""),
		accountHandle: (row.account_handle as string) ?? undefined,
		scheduledDate: (row.scheduled_for as string) ?? undefined,
		publishedAt: (row.published_at as string) ?? undefined,
		createdAt: (row.created_at as string) ?? undefined,
		media: (row.media_urls as string[]) ?? [],
		mediaUrls: (row.media_urls as string[]) ?? [],
		topics: (row.hashtags as string[]) ?? [],

		// Top-level metric shortcuts
		views,
		likes,
		replies,

		// Structured metrics
		performance: {
			views,
			likes,
			replies,
			reposts,
			quotes,
			shares,
		},

		// Thread-specific
		threadId: (row.threads_post_id as string) ?? undefined,
		permalink: (row.permalink as string) ?? undefined,

		// Instagram-specific
		instagramPostId: (row.instagram_post_id as string) ?? undefined,
		instagramAccountId: (row.instagram_account_id as string) ?? undefined,
		igMediaType: (row.ig_media_type as ThreadPost["igMediaType"]) ?? undefined,
		altText: (row.alt_text as string) ?? undefined,
		igImpressions: Number(row.ig_impressions ?? 0),
		igReach: Number(row.ig_reach ?? 0),
		igSaved: Number(row.ig_saved ?? 0),
		igShares: Number(row.ig_shares ?? 0),
		igPlays: Number(row.ig_plays ?? 0),
		igReplays: Number(row.ig_replays ?? 0),
		igReelsAvgWatchTime: Number(row.ig_reels_avg_watch_time ?? 0),
		igClipsReplays: Number(row.ig_clips_replays ?? 0),
		storyExpiresAt: row.story_expires_at
			? new Date(row.story_expires_at as string)
			: null,
		contentCategory: (row.content_category as string) ?? undefined,
		metadata: (row.metadata as Record<string, unknown>) ?? null,
	} as ThreadPost;
}

// ─── Instagram Account Row → InstagramAccount ───────────────────────────────

/**
 * Map a raw Supabase `instagram_accounts` row into an InstagramAccount.
 * Note: `follower_count` (singular) on IG vs `followers_count` (plural) on Threads.
 */
export function mapInstagramAccountRow(
	row: Record<string, unknown>,
): InstagramAccount {
	const followerCount = Number(row.follower_count ?? 0);
	return {
		id: String(row.id ?? ""),
		platform: "instagram",
		handle: String(row.username ?? ""),
		username: (row.username as string) ?? undefined,
		displayName: (row.display_name as string) ?? undefined,
		avatarUrl: String(row.avatar_url ?? ""),
		followers: followerCount,
		followersCount: followerCount,
		isActive: (row.is_active as boolean) ?? true,
		status: (row.status as "active" | "suspended" | "pending") ?? "active",
		accountType: (row.account_type as string) ?? undefined,
		followingCount: Number(row.following_count ?? 0),
		mediaCount: Number(row.media_count ?? 0),
		instagramUserId: String(row.instagram_user_id ?? ""),
		loginType: (row.login_type as "instagram" | "facebook") ?? undefined,
		facebookPageId: (row.facebook_page_id as string) ?? undefined,
		createdAt: (row.created_at as string) ?? undefined,
		updatedAt: (row.updated_at as string) ?? undefined,
		lastSyncedAt: row.last_synced_at
			? new Date(row.last_synced_at as string)
			: undefined,
		needsReauth: (row.needs_reauth as boolean) ?? false,
		tokenExpiresAt: row.token_expires_at
			? new Date(row.token_expires_at as string)
			: undefined,
	};
}
