// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
/// <reference path="../vite-env.d.ts" />
/**
 * Data Service
 * @deprecated Legacy root service retained for server-side and backwards-compatible
 * import paths. Prefer `src/services/*` for frontend code and API handlers for
 * new writes so scoped validation, idempotency, and audit gates are not bypassed.
 *
 * High-level data operations using Supabase
 * Wraps apiService with error handling and business logic
 * Caching consolidated into swrCache (stale-while-revalidate)
 */

import type { Platform, PlatformFilter } from "../src/types/platform.js";
import {
	type Group,
	type GroupCategory,
	PostStatus,
	type ThreadAccount,
	type ThreadPost,
} from "../types.js";
import { apiService } from "./api/index.js";
import { createServiceLogger, getUserIdAsync, supabase } from "./api/shared.js";
import { clearBestTimesCache } from "./bestTimesCache.js";
import { notificationService } from "./notificationService.js";
import { swrCache } from "./swrCache.js";

const log = createServiceLogger("DataService");

class DataService {
	// Check if user is authenticated
	private isAuthenticated(): boolean {
		// Supabase stores session in localStorage
		const session = localStorage.getItem(
			"sb-" +
				import.meta.env.VITE_SUPABASE_URL?.split("//")[1]?.split(".")[0] +
				"-auth-token",
		);
		return !!session;
	}

	// Get current user ID
	private async getCurrentUserId(): Promise<string | null> {
		try {
			return await getUserIdAsync();
		} catch {
			return null;
		}
	}

	// Wait for auth to be ready
	async waitForAuth(): Promise<boolean> {
		const {
			data: { session },
		} = await supabase.auth.getSession();
		return !!session;
	}

	// Prefetch data for a view (call on hover/focus)
	async prefetch(
		view: "dashboard" | "calendar" | "posts" | "analytics",
		accountId: string = "ALL",
	): Promise<void> {
		if (!this.isAuthenticated()) return;

		try {
			switch (view) {
				case "dashboard":
					// Prefetch stats and recent posts independently
					this.getAnalyticsStats(accountId).catch((error) => {
						log.warn(
							`Prefetch stats failed for dashboard view (account: ${accountId}):`,
							{ error: String(error) },
						);
					});
					this.getPosts(accountId).catch((error) => {
						log.warn(
							`Prefetch posts failed for dashboard view (account: ${accountId}):`,
							{ error: String(error) },
						);
					});
					// Trigger background sync if data is stale (15-min cooldown server-side)
					this.triggerDashboardSync().catch(() => {});
					break;
				case "calendar":
				case "posts":
					this.getPosts(accountId).catch((error) => {
						log.warn(
							`Prefetch failed for ${view} view (account: ${accountId}):`,
							{ error: String(error) },
						);
					});
					break;
				case "analytics":
					this.getAnalyticsStats(accountId).catch((error) => {
						log.warn(
							`Prefetch failed for analytics view (account: ${accountId}):`,
							{ error: String(error) },
						);
					});
					break;
			}
		} catch (error) {
			log.warn(`Prefetch error for ${view}:`, error);
		}
	}

	// Trigger background sync on dashboard open (server deduplicates with 15-min cooldown)
	private async triggerDashboardSync(): Promise<void> {
		try {
			const {
				data: { session },
			} = await supabase.auth.getSession();
			if (!session) return;
			// Skip if token is expired — avoids 401 during session recovery
			if (
				session.expires_at &&
				session.expires_at < Math.floor(Date.now() / 1000)
			)
				return;
			await fetch("/api/analytics?action=queue-sync", {
				method: "POST",
				headers: {
					"Content-Type": "application/json",
					Authorization: `Bearer ${session.access_token}`,
				},
				body: JSON.stringify({ trigger: "dashboard-open" }),
			});
		} catch {
			// Silent — non-critical background sync
		}
	}

	// Invalidate cache when data changes
	invalidateCache(type: "posts" | "accounts" | "stats" | "all" = "all"): void {
		if (type === "all") {
			swrCache.invalidatePattern(".*");
		} else if (type === "posts") {
			swrCache.invalidatePattern("^posts");
		} else if (type === "accounts") {
			swrCache.invalidatePattern("^accounts");
		} else if (type === "stats") {
			swrCache.invalidatePattern("^stats|^dashboard-stats");
		}
	}

	// --- ACCOUNTS ---
	async getAccounts(): Promise<ThreadAccount[]> {
		try {
			if (!this.isAuthenticated()) {
				return [];
			}
			return await swrCache.get("accounts", () => apiService.getAccounts());
		} catch (error) {
			log.error("Failed to fetch accounts:", error);
			return [];
		}
	}

	async getAccount(id: string): Promise<ThreadAccount | undefined> {
		try {
			if (!this.isAuthenticated()) {
				return undefined;
			}
			return await apiService.getAccount(id);
		} catch (error) {
			log.error("Failed to fetch account:", error);
			return undefined;
		}
	}

	async syncAccount(id: string): Promise<void> {
		try {
			await apiService.syncAccount(id);
		} catch (error) {
			log.error("Failed to sync account:", error);
			throw error;
		}
	}

	// --- POSTS ---
	// Paginated posts fetching with total count
	async getPostsPaginated(
		accountId: string | "ALL" = "ALL",
		page: number = 1,
		pageSize: number = 50,
		forceRefresh: boolean = false,
		platformFilter?: PlatformFilter,
		statusFilter?: string,
	): Promise<{ posts: ThreadPost[]; total: number }> {
		try {
			if (!this.isAuthenticated()) {
				return { posts: [], total: 0 };
			}
			const statusKey =
				statusFilter && statusFilter !== "All" ? `:status=${statusFilter}` : "";
			const cacheKey = `posts:${accountId}:page=${page}:size=${pageSize}${platformFilter && platformFilter !== "all" ? `:platform=${platformFilter}` : ""}${statusKey}`;
			if (forceRefresh) swrCache.invalidate(cacheKey);
			return await swrCache.get(cacheKey, () =>
				apiService.getPosts(
					accountId,
					page,
					pageSize,
					platformFilter,
					undefined,
					statusFilter,
				),
			);
		} catch (error) {
			log.error("Failed to fetch paginated posts:", error);
			return { posts: [], total: 0 };
		}
	}

	// Legacy method for backward compatibility (used by calendar, dashboard, etc.)
	// Set forceRefresh=true when switching accounts to bypass cache
	async getPosts(
		accountId: string | "ALL" = "ALL",
		forceRefresh: boolean = false,
		platformFilter?: PlatformFilter,
		since?: string, // ISO date — only fetch posts after this date
	): Promise<ThreadPost[]> {
		try {
			if (!this.isAuthenticated()) {
				return [];
			}
			const sinceKey = since ? `:since=${since.split("T")[0]!}` : "";
			const platformKey =
				platformFilter && platformFilter !== "all"
					? `:platform=${platformFilter}`
					: "";
			const cacheKey = `posts:${accountId}${platformKey}${sinceKey}`;
			if (forceRefresh) swrCache.invalidate(cacheKey);
			return await swrCache.get(cacheKey, async () => {
				const pageSize = since ? 200 : 2000;
				const { posts } = await apiService.getPosts(
					accountId,
					1,
					pageSize,
					platformFilter,
					since,
				);
				return posts;
			});
		} catch (error) {
			log.error("Failed to fetch posts:", error);
			return [];
		}
	}

	async getPublishedPostsForAI(options: {
		accountId?: string | "ALL" | undefined;
		platformFilter?: PlatformFilter | undefined;
		since?: string | undefined;
		limit?: number | undefined;
	} = {}): Promise<ThreadPost[]> {
		try {
			if (!this.isAuthenticated()) return [];
			const limit = Math.max(1, Math.min(options.limit ?? 500, 500));
			const { posts, total } = await apiService.getPosts(
				options.accountId ?? "ALL",
				1,
				limit,
				options.platformFilter,
				options.since,
				"published",
			);
			if (total > limit) {
				log.warn("[DataService] AI post sample capped", {
					total,
					limit,
					accountId: options.accountId ?? "ALL",
					platformFilter: options.platformFilter ?? "all",
				});
			}
			return posts.filter(
				(post) =>
					post.status === PostStatus.PUBLISHED ||
					(post.status as string) === "published" ||
					(post.status as string) === "PUBLISHED",
			);
		} catch (error) {
			log.error("Failed to fetch scoped published posts for AI:", error);
			return [];
		}
	}

	// Get cached posts synchronously (for enriching replies with parent post data)
	// Returns empty array if cache is empty - does not trigger a fetch
	getCachedPosts(accountId: string | "ALL" = "ALL"): ThreadPost[] {
		try {
			return swrCache.peek<ThreadPost[]>(`posts:${accountId}`) || [];
		} catch (error) {
			log.error("Failed to get cached posts:", error);
			return [];
		}
	}

	// Real-time posts subscription - auto-updates when posts are created/updated
	subscribeToPostsRealtime(
		accountId: string | "ALL" = "ALL",
		onUpdate: (posts: ThreadPost[]) => void,
		platformFilter?: PlatformFilter,
	): (() => void) | null {
		try {
			if (!this.isAuthenticated()) {
				return null;
			}

			const unsubscribe = apiService.subscribeToPostsRealtime(
				accountId,
				(posts: ThreadPost[]) => {
					// Update SWR cache with new data
					swrCache.store(`posts:${accountId}`, posts);
					// Call the update callback
					onUpdate(posts);
				},
				platformFilter,
			);

			return unsubscribe;
		} catch (error) {
			log.error("Failed to subscribe to posts:", error);
			return null;
		}
	}

	async createPost(
		post: Omit<ThreadPost, "id" | "likes" | "replies">,
	): Promise<ThreadPost> {
		try {
			const result = await apiService.createPost(post);
			this.invalidateCache("posts");
			clearBestTimesCache(post.accountId);
			return result;
		} catch (error) {
			log.error("Failed to create post:", error);
			throw error;
		}
	}

	// @deprecated Legacy batch helper. Prefer the backend bulk schedule handlers,
	// which run publish preflight, exact-time dispatch, and per-row validation.
	// When posting to multiple accounts, we add random delays to avoid rate limiting
	async batchCreatePosts(
		content: string,
		mediaUrls: string[],
		status: PostStatus,
		scheduledDate: string | undefined,
		accountIds: string[],
		onProgress?: (
			current: number,
			total: number,
			accountHandle: string,
		) => void,
	): Promise<void> {
		try {
			// For scheduled posts, we can create them all at once (they won't be published simultaneously)
			// For immediate publishing, we need to stagger them with random delays
			if (status === PostStatus.SCHEDULED || status === PostStatus.DRAFT) {
				// Create all posts at the exact requested scheduled time. Backend
				// dispatch/rate-limit controls handle publish-time pacing.
				const accountHandles: string[] = [];
				const promises = accountIds.map(async (accountId) => {
					const account = await this.getAccount(accountId);
					const handle = account?.handle || account?.username || "";
					accountHandles.push(handle);

					return apiService.createPost({
						content,
						mediaUrls,
						status,
						scheduledDate,
						accountId,
						accountHandle: handle,
					});
				});
				await Promise.all(promises);

				// Create notifications for scheduled posts
				if (status === PostStatus.SCHEDULED && scheduledDate) {
					for (const handle of accountHandles) {
						notificationService
							.notifyPostScheduled(handle, scheduledDate)
							.catch(log.error);
					}
				}
			} else {
				// For immediate publishing, stagger posts with 30-90 second random delays
				for (let i = 0; i < accountIds.length; i++) {
					const accountId = accountIds[i];
					const account = await this.getAccount(accountId!);
					const handle = account?.handle || account?.username || "";

					// Report progress before posting
					if (onProgress) {
						onProgress(i + 1, accountIds.length, handle);
					}

					await apiService.createPost({
						content,
						mediaUrls,
						status,
						scheduledDate,
						accountId,
						accountHandle: handle,
					});

					// Create notification for published post
					notificationService.notifyPostPublished(handle).catch(log.error);

					// Add random delay between posts (30-90 seconds) except for the last one
					if (i < accountIds.length - 1) {
						const delayMs = Math.floor(Math.random() * 60000) + 30000; // 30-90 seconds
						log.debug(
							`Waiting ${Math.round(delayMs / 1000)}s before next account...`,
						);
						await new Promise((resolve) => setTimeout(resolve, delayMs));
					}
				}
			}
		} catch (error) {
			log.error("Failed to batch create posts:", error);
			throw error;
		}
	}

	async updatePost(updatedPost: ThreadPost): Promise<void> {
		try {
			await apiService.updatePost(updatedPost.id, updatedPost);
			this.invalidateCache("posts");
			clearBestTimesCache(updatedPost.accountId);
		} catch (error) {
			log.error("Failed to update post:", error);
			throw error;
		}
	}

	async unschedulePost(postId: string): Promise<void> {
		const { error } = await supabase
			.from("posts")
			.update({
				status: "draft",
				scheduled_for: null,
				updated_at: new Date().toISOString(),
			})
			.eq("id", postId);
		if (error) throw error;
		swrCache.invalidatePattern("^posts");
	}

	async deletePost(id: string): Promise<void> {
		try {
			await apiService.deletePost(id);
			this.invalidateCache("posts");
			clearBestTimesCache(); // No accountId available, clear all
		} catch (error) {
			log.error("Failed to delete post:", error);
			throw error;
		}
	}

	async batchDeletePosts(postIds: string[]): Promise<void> {
		const userId = await this.getCurrentUserId();
		if (!userId) throw new Error("User not authenticated");

		// Delete in batches of 100 (Supabase recommended)
		const batchSize = 100;
		for (let i = 0; i < postIds.length; i += batchSize) {
			const batchIds = postIds.slice(i, i + batchSize);
			const { error } = await supabase
				.from("posts")
				.delete()
				.eq("user_id", userId)
				.in("id", batchIds);

			if (error) {
				log.error("Failed to batch delete posts:", error);
				throw error;
			}
		}

		this.invalidateCache("posts");
		clearBestTimesCache(); // Multiple accounts possible, clear all
	}

	async batchUpdatePosts(
		updates: Array<{ id: string; data: Partial<ThreadPost> }>,
	): Promise<void> {
		const userId = await this.getCurrentUserId();
		if (!userId) throw new Error("User not authenticated");

		// Update one by one (Supabase doesn't have batch update like Firestore)
		for (const update of updates) {
			const updateData: Record<string, unknown> = {
				updated_at: new Date().toISOString(),
			};

			// Map camelCase to snake_case
			if (update.data.content !== undefined)
				updateData.content = update.data.content;
			if (update.data.status !== undefined)
				updateData.status = update.data.status;
			if (update.data.scheduledDate !== undefined)
				updateData.scheduled_for = update.data.scheduledDate;

			const { error } = await supabase
				.from("posts")
				.update(updateData)
				.eq("id", update.id)
				.eq("user_id", userId);

			if (error) {
				log.error("Failed to update post:", error);
				throw error;
			}
		}

		this.invalidateCache("posts");
		clearBestTimesCache(); // Multiple accounts possible, clear all
	}

	async insertCrossPostDraft(params: {
		userId: string;
		content: string;
		accountId: string;
		platform: string;
		sourcePostId: string;
		sourcePlatform: string;
	}): Promise<void> {
		const { error } = await supabase.from("posts").insert({
			content: params.content,
			account_id: params.accountId,
			user_id: params.userId,
			platform: params.platform,
			status: "draft",
			metadata: {
				cross_posted_from: params.sourcePostId,
				original_platform: params.sourcePlatform,
			},
		});
		if (error) throw error;
	}

	async duplicatePost(id: string): Promise<void> {
		try {
			await apiService.duplicatePost(id);
		} catch (error) {
			log.error("Failed to duplicate post:", error);
			throw error;
		}
	}

	// @deprecated Legacy publish helper. Prefer backend publish handlers so direct
	// writes stay behind preflight, idempotency, rate limits, and audit logging.
	async publishPostNow(postId: string): Promise<void> {
		try {
			await apiService.publishPostNow(postId);
		} catch (error) {
			log.error("Failed to publish post:", error);
			throw error;
		}
	}

	// --- ANALYTICS ---
	async getAnalyticsStats(
		accountId: string | "ALL",
		forceRefresh: boolean = false,
		platform: Platform = "threads",
	): Promise<{
		totalFollowers: number;
		totalLikes: number;
		totalReplies: number;
		totalReposts: number;
		totalQuotes: number;
		totalShares: number;
		totalClicks: number;
		scheduledCount: number;
		totalViews: number;
		totalIgImpressions: number;
		totalIgReach: number;
		totalIgSaved: number;
		totalIgShares: number;
	}> {
		try {
			if (!this.isAuthenticated()) {
				return {
					totalFollowers: 0,
					totalLikes: 0,
					totalReplies: 0,
					totalReposts: 0,
					totalQuotes: 0,
					totalShares: 0,
					totalClicks: 0,
					scheduledCount: 0,
					totalViews: 0,
					totalIgImpressions: 0,
					totalIgReach: 0,
					totalIgSaved: 0,
					totalIgShares: 0,
				};
			}
			const cacheKey = `stats:${accountId}:${platform}`;
			if (forceRefresh) swrCache.invalidate(cacheKey);
			return await swrCache.get(cacheKey, async () => {
				const stats = await apiService.getAnalyticsStats(accountId, platform);
				return {
					totalFollowers: stats.totalFollowers || 0,
					totalLikes: stats.totalLikes || 0,
					totalReplies: stats.totalReplies || 0,
					totalReposts: stats.totalReposts || 0,
					totalQuotes: stats.totalQuotes || 0,
					totalShares: stats.totalShares || 0,
					totalClicks: stats.totalClicks || 0,
					scheduledCount: stats.scheduledCount || 0,
					totalViews: stats.totalViews || 0,
					totalIgImpressions: stats.totalIgImpressions || 0,
					totalIgReach: stats.totalIgReach || 0,
					totalIgSaved: stats.totalIgSaved || 0,
					totalIgShares: stats.totalIgShares || 0,
				};
			});
		} catch (error) {
			log.error("Failed to fetch analytics stats:", error);
			return {
				totalFollowers: 0,
				totalLikes: 0,
				totalReplies: 0,
				totalReposts: 0,
				totalQuotes: 0,
				totalShares: 0,
				totalClicks: 0,
				scheduledCount: 0,
				totalViews: 0,
				totalIgImpressions: 0,
				totalIgReach: 0,
				totalIgSaved: 0,
				totalIgShares: 0,
			};
		}
	}

	async getAnalyticsWithDeltas(
		accountId: string | "ALL" = "ALL",
		periodDays: number = 7,
		_forceRefresh: boolean = false,
		customRange?: { start: string; end: string },
		platform: Platform = "threads",
		scopeAccountIds?: string[],
	) {
		try {
			if (!this.isAuthenticated()) {
				return this._emptyStatsWithDeltas();
			}
			const scopeKey = scopeAccountIds?.length
				? `:scope=${scopeAccountIds.sort().join(",")}`
				: "";
			const cacheKey = customRange
				? `stats-deltas:${accountId}:${platform}:custom:${customRange.start}:${customRange.end}${scopeKey}`
				: `stats-deltas:${accountId}:${platform}:${periodDays}d${scopeKey}`;
			// Always fetch fresh analytics stats — correctness > caching speed.
			// SWR stale data caused hero cards to show wrong follower/metric values.
			swrCache.invalidate(cacheKey);
			return await swrCache.get(cacheKey, () =>
				apiService.getAnalyticsWithDeltas(
					accountId,
					periodDays,
					platform,
					undefined,
					scopeAccountIds,
				),
			);
		} catch (error) {
			log.error("Failed to fetch analytics with deltas:", error);
			return this._emptyStatsWithDeltas();
		}
	}

	/**
	 * Fetch follower history from account_analytics for chart/sparkline data.
	 * Returns chronologically-ordered array of { v, date } entries.
	 */
	async getFollowerHistory(
		accountId: string,
		periodDays: number = 30,
	): Promise<{ v: number; date: string }[]> {
		if (!accountId || accountId === "ALL") return [];
		try {
			const cutoff = new Date();
			cutoff.setDate(cutoff.getDate() - (periodDays > 0 ? periodDays : 90));
			const cutoffStr = cutoff.toISOString().split("T")[0]!;

			// Prefer account_metrics_history (append-only, accurate)
			// Falls back to account_analytics if history table has insufficient data
			const { data: historyRows } = await supabase
				.from("account_metrics_history")
				.select("date, followers_count")
				.eq("account_id", accountId)
				.gte("date", cutoffStr)
				.order("date", { ascending: true });

			if (historyRows && historyRows.length >= 2) {
				return historyRows.map((row) => ({
					v: (row as { followers_count?: number | undefined }).followers_count ?? 0,
					date: new Date((row as { date: string }).date).toLocaleDateString(
						"en-US",
						{
							month: "short",
							day: "numeric",
						},
					),
				}));
			}

			// Fallback: account_analytics (overwritten each sync, less reliable)
			const { data: analyticsRows } = await supabase
				.from("account_analytics")
				.select("date, followers_count")
				.eq("account_id", accountId)
				.gte("date", cutoffStr)
				.order("date", { ascending: true });

			if (!analyticsRows || analyticsRows.length < 2) return [];
			return analyticsRows.map((row) => ({
				v: row.followers_count ?? 0,
				date: new Date(row.date).toLocaleDateString("en-US", {
					month: "short",
					day: "numeric",
				}),
			}));
		} catch (error) {
			log.error("getFollowerHistory failed:", error);
			return [];
		}
	}

	/**
	 * Fetch aggregate follower history across multiple accounts.
	 * Sums followers_count by date for all given account IDs.
	 */
	async getAggregateFollowerHistory(
		accountIds: string[],
		periodDays: number = 30,
	): Promise<{ v: number; date: string }[]> {
		if (!accountIds.length) return [];
		if (accountIds.length === 1)
			return this.getFollowerHistory(accountIds[0]!, periodDays);
		try {
			const cutoff = new Date();
			cutoff.setDate(cutoff.getDate() - (periodDays > 0 ? periodDays : 90));
			const cutoffStr = cutoff.toISOString().split("T")[0]!;

			// Prefer account_metrics_history (append-only, accurate)
			const { data: historyRows } = await supabase
				.from("account_metrics_history")
				.select("date, followers_count")
				.in("account_id", accountIds)
				.gte("date", cutoffStr)
				.order("date", { ascending: true });

			const sourceRows =
				historyRows && historyRows.length >= 2 ? historyRows : null;

			if (!sourceRows) {
				// Fallback: account_analytics
				const { data: analyticsRows } = await supabase
					.from("account_analytics")
					.select("date, followers_count")
					.in("account_id", accountIds)
					.gte("date", cutoffStr)
					.order("date", { ascending: true });

				if (!analyticsRows?.length) return [];

				const byDate = new Map<string, number>();
				for (const row of analyticsRows) {
					const d = row.date;
					byDate.set(d, (byDate.get(d) ?? 0) + (row.followers_count ?? 0));
				}
				const sorted = [...byDate.entries()].sort(([a], [b]) =>
					a.localeCompare(b),
				);
				if (sorted.length < 2) return [];
				return sorted.map(([date, v]) => ({
					v,
					date: new Date(date).toLocaleDateString("en-US", {
						month: "short",
						day: "numeric",
					}),
				}));
			}

			// Group history rows by date and sum followers
			const byDate = new Map<string, number>();
			for (const row of sourceRows) {
				const d = row.date;
				byDate.set(d, (byDate.get(d) ?? 0) + (row.followers_count ?? 0));
			}
			const sorted = [...byDate.entries()].sort(([a], [b]) =>
				a.localeCompare(b),
			);
			if (sorted.length < 2) return [];
			return sorted.map(([date, v]) => ({
				v,
				date: new Date(date).toLocaleDateString("en-US", {
					month: "short",
					day: "numeric",
				}),
			}));
		} catch (error) {
			log.error("getAggregateFollowerHistory failed:", error);
			return [];
		}
	}

	/**
	 * Fetch daily activity data (views, likes, replies, posts per day)
	 * from post_metric_history via server-side aggregation.
	 */
	async getDailyActivity(
		accountId: string = "ALL",
		periodDays: number = 30,
		accountIds?: string[],
	) {
		try {
			if (!this.isAuthenticated()) return [];
			return await apiService.getDailyActivity(
				accountId,
				periodDays,
				accountIds,
			);
		} catch (error) {
			log.error("getDailyActivity failed:", error);
			return [];
		}
	}

	private _emptyStatsWithDeltas() {
		return {
			current: {
				totalFollowers: 0,
				totalLikes: 0,
				totalReplies: 0,
				totalReposts: 0,
				totalViews: 0,
				scheduledCount: 0,
				totalIgReach: 0,
				totalIgSaved: 0,
				totalIgShares: 0,
			},
			previous: {
				totalFollowers: 0,
				totalLikes: 0,
				totalReplies: 0,
				totalReposts: 0,
				totalViews: 0,
				totalIgReach: 0,
				totalIgSaved: 0,
				totalIgShares: 0,
			},
			deltas: {
				followers: "—",
				likes: "—",
				replies: "—",
				reposts: "—",
				views: "—",
				clicks: "—",
				reach: "—",
				saves: "—",
				shares: "—",
				engagement: "—",
			},
		};
	}

	async syncAnalytics(accountId: string): Promise<void> {
		try {
			await apiService.syncAnalytics(accountId);
		} catch (error) {
			log.error("Failed to sync analytics:", error);
			throw error;
		}
	}

	async syncAllAnalytics(): Promise<void> {
		try {
			await apiService.syncAllAnalytics();
		} catch (error) {
			log.error("Failed to sync all analytics:", error);
			throw error;
		}
	}

	// --- AUTHENTICATION ---
	async initiateLogin(): Promise<string> {
		try {
			const { authUrl } = await apiService.initiateLogin();
			return authUrl;
		} catch (error) {
			log.error("Failed to initiate login:", error);
			throw error;
		}
	}

	async initiateInstagramLogin(): Promise<string> {
		try {
			const { authUrl } = await apiService.initiateInstagramLogin();
			return authUrl;
		} catch (error) {
			log.error("Failed to initiate Instagram login:", error);
			throw error;
		}
	}

	async getInstagramAccounts(): Promise<import("../types.js").InstagramAccount[]> {
		try {
			if (!this.isAuthenticated()) return [];
			return await apiService.getInstagramAccounts();
		} catch (error) {
			log.error("Failed to fetch Instagram accounts:", error);
			return [];
		}
	}

	async checkAuthStatus(accountId: string): Promise<boolean> {
		try {
			const status = await apiService.checkAuthStatus(accountId);
			return status.isAuthenticated && !status.isExpired;
		} catch (error) {
			log.error("Failed to check auth status:", error);
			return false;
		}
	}

	// Exchange OAuth code for token
	async exchangeOAuthCode(
		code: string,
		state: string,
	): Promise<{ success: boolean; error?: string | undefined }> {
		try {
			return await apiService.exchangeToken(code, state);
		} catch (error) {
			log.error("Failed to exchange OAuth code:", error);
			throw error;
		}
	}

	// --- GROUPS ---
	// Get all groups for the current user
	async getGroups(): Promise<Group[]> {
		try {
			if (!this.isAuthenticated()) return [];

			const userId = await this.getCurrentUserId();
			if (!userId) return [];

			const { data, error } = await supabase
				.from("account_groups")
				.select("*")
				.eq("user_id", userId)
				.order("created_at", { ascending: false });

			if (error) {
				log.error("Failed to fetch groups:", error);
				return [];
			}

			return (data || []).map((row) => ({
				id: row.id,
				name: row.name,
				accountIds: row.account_ids || [],
				category: (row.category || "uncategorized") as GroupCategory,
				voiceProfile: (row.voice_profile as Record<string, unknown>) || null,
				createdAt: new Date(row.created_at),
				updatedAt: new Date(row.updated_at),
			}));
		} catch (error) {
			log.error("Failed to fetch groups:", error);
			return [];
		}
	}

	// Get a single group by ID
	async getGroup(groupId: string): Promise<Group | null> {
		try {
			if (!this.isAuthenticated()) return null;

			const userId = await this.getCurrentUserId();
			if (!userId) return null;

			const { data, error } = await supabase
				.from("account_groups")
				.select("*")
				.eq("id", groupId)
				.eq("user_id", userId)
				.maybeSingle();

			if (error || !data) return null;

			return {
				id: data.id,
				name: data.name,
				accountIds: data.account_ids || [],
				category: (data.category || "uncategorized") as GroupCategory,
				voiceProfile: (data.voice_profile as Record<string, unknown>) || null,
				createdAt: new Date(data.created_at),
				updatedAt: new Date(data.updated_at),
			};
		} catch (error) {
			log.error("Failed to fetch group:", error);
			return null;
		}
	}

	// Create a new group
	async createGroup(
		name: string,
		category: GroupCategory = "uncategorized",
	): Promise<Group> {
		try {
			if (!this.isAuthenticated()) throw new Error("Not authenticated");

			const userId = await this.getCurrentUserId();
			if (!userId) throw new Error("Not authenticated");

			const { data, error } = await supabase
				.from("account_groups")
				.insert({
					user_id: userId,
					name,
					category,
					account_ids: [],
				})
				.select()
				.maybeSingle();

			if (error || !data) {
				log.error("Failed to create group:", error);
				throw error || new Error("Failed to create group");
			}

			return {
				id: data.id,
				name: data.name,
				accountIds: [],
				category: (data.category || "uncategorized") as GroupCategory,
				createdAt: new Date(data.created_at),
				updatedAt: new Date(data.updated_at),
			};
		} catch (error) {
			log.error("Failed to create group:", error);
			throw error;
		}
	}

	// Update a group's name and/or category
	async updateGroup(
		groupId: string,
		updates: Partial<Pick<Group, "name" | "category">>,
	): Promise<void> {
		try {
			if (!this.isAuthenticated()) throw new Error("Not authenticated");

			const userId = await this.getCurrentUserId();
			if (!userId) throw new Error("Not authenticated");

			const { error } = await supabase
				.from("account_groups")
				.update({
					...updates,
					updated_at: new Date().toISOString(),
				})
				.eq("id", groupId)
				.eq("user_id", userId);

			if (error) {
				log.error("Failed to update group:", error);
				throw error;
			}
		} catch (error) {
			log.error("Failed to update group:", error);
			throw error;
		}
	}

	// Delete a group (unassigns all accounts first)
	async deleteGroup(groupId: string): Promise<void> {
		try {
			if (!this.isAuthenticated()) throw new Error("Not authenticated");

			const userId = await this.getCurrentUserId();
			if (!userId) throw new Error("Not authenticated");

			const group = await this.getGroup(groupId);
			if (!group) throw new Error("Group not found");

			// Unassign all accounts from this group
			if (group.accountIds.length > 0) {
				await supabase
					.from("accounts")
					.update({ group_id: null })
					.eq("user_id", userId)
					.in("id", group.accountIds);
			}

			// Delete the group
			const { error } = await supabase
				.from("account_groups")
				.delete()
				.eq("id", groupId)
				.eq("user_id", userId);

			if (error) {
				log.error("Failed to delete group:", error);
				throw error;
			}

			this.invalidateCache("accounts");
		} catch (error) {
			log.error("Failed to delete group:", error);
			throw error;
		}
	}

	// Assign accounts to a group
	async assignAccountsToGroup(
		groupId: string,
		accountIds: string[],
	): Promise<void> {
		try {
			if (!this.isAuthenticated()) throw new Error("Not authenticated");

			const userId = await this.getCurrentUserId();
			if (!userId) throw new Error("Not authenticated");

			// Get current group to find accounts to unassign
			const group = await this.getGroup(groupId);
			const currentAccountIds = group?.accountIds || [];

			// Find accounts that are being removed from this group
			const removedAccountIds = currentAccountIds.filter(
				(id) => !accountIds.includes(id),
			);

			// Unassign removed accounts
			if (removedAccountIds.length > 0) {
				await supabase
					.from("accounts")
					.update({ group_id: null })
					.eq("user_id", userId)
					.in("id", removedAccountIds);
			}

			// Assign new accounts to this group
			if (accountIds.length > 0) {
				const { error: assignError } = await supabase
					.from("accounts")
					.update({ group_id: groupId })
					.eq("user_id", userId)
					.in("id", accountIds);

				if (assignError) {
					log.error("Failed to update accounts.group_id:", assignError);
				}
			}

			// Update the group's account_ids array
			log.info(`Saving ${accountIds.length} account IDs to group ${groupId}`);
			const { error: groupUpdateError } = await supabase
				.from("account_groups")
				.update({
					account_ids: accountIds,
					updated_at: new Date().toISOString(),
				})
				.eq("id", groupId)
				.eq("user_id", userId);

			if (groupUpdateError) {
				log.error(
					"Failed to update account_groups.account_ids:",
					groupUpdateError,
				);
			}

			this.invalidateCache("accounts");
		} catch (error) {
			log.error("Failed to assign accounts to group:", error);
			throw error;
		}
	}

	// Get accounts by group ID
	async getAccountsByGroup(groupId: string): Promise<ThreadAccount[]> {
		try {
			const accounts = await this.getAccounts();
			return accounts.filter((acc) => acc.groupId === groupId);
		} catch (error) {
			log.error("Failed to get accounts by group:", error);
			return [];
		}
	}

	// Get unassigned accounts (not belonging to any group)
	async getUnassignedAccounts(): Promise<ThreadAccount[]> {
		try {
			const accounts = await this.getAccounts();
			return accounts.filter((acc) => !acc.groupId);
		} catch (error) {
			log.error("Failed to get unassigned accounts:", error);
			return [];
		}
	}

	// Get group stats (total followers, account count)
	async getGroupStats(
		groupId: string,
	): Promise<{ totalFollowers: number; accountCount: number }> {
		try {
			const accounts = await this.getAccountsByGroup(groupId);
			const totalFollowers = accounts.reduce(
				(sum, acc) => sum + (acc.followers || 0),
				0,
			);
			return {
				totalFollowers,
				accountCount: accounts.length,
			};
		} catch (error) {
			log.error("Failed to get group stats:", error);
			return { totalFollowers: 0, accountCount: 0 };
		}
	}

	// Assign a single account to a group (race-condition safe)
	// Uses a server-side RPC to atomically remove from old group + add to new group
	// in a single transaction, eliminating fetch-modify-write race conditions.
	async assignSingleAccountToGroup(
		accountId: string,
		groupId: string | null,
	): Promise<void> {
		try {
			if (!this.isAuthenticated()) throw new Error("Not authenticated");

			const userId = await this.getCurrentUserId();
			if (!userId) throw new Error("Not authenticated");

			const {
				data: { session },
			} = await supabase.auth.getSession();
			if (!session?.access_token) throw new Error("Not authenticated");

			const response = await fetch("/api/accounts?action=assign-group", {
				method: "POST",
				headers: {
					"Content-Type": "application/json",
					Authorization: `Bearer ${session.access_token}`,
				},
				body: JSON.stringify({ accountId, groupId }),
			});

			if (!response.ok) {
				const error = await response.json().catch(() => ({}));
				log.error("Account group assignment failed:", error);
				throw new Error(error.error || "Failed to assign account to group");
			}

			this.invalidateCache("accounts");
		} catch (error) {
			log.error("Failed to assign account to group:", error);
			throw error;
		}
	}

	// Get comprehensive insights for a group
	async getGroupInsights(
		groupId: string,
		accounts: ThreadAccount[],
	): Promise<{
		totalFollowers: number;
		totalViews: number;
		totalLikes: number;
		totalReplies: number;
		totalReposts: number;
		engagementRate: number;
		followerGrowth: number;
		avgEngagementPerAccount: number;
		topPerformingAccountId?: string | undefined;
		topPerformingAccountHandle?: string | undefined;
		postCount: number;
	}> {
		try {
			// Filter accounts belonging to this group
			const groupAccounts = accounts.filter((acc) => acc.groupId === groupId);

			if (groupAccounts.length === 0) {
				return {
					totalFollowers: 0,
					totalViews: 0,
					totalLikes: 0,
					totalReplies: 0,
					totalReposts: 0,
					engagementRate: 0,
					followerGrowth: 0,
					avgEngagementPerAccount: 0,
					postCount: 0,
				};
			}

			// Aggregate stats from all accounts in parallel
			const statsPromises = groupAccounts.map((acc) =>
				this.getAnalyticsStats(acc.id).catch(() => ({
					totalFollowers: 0,
					totalLikes: 0,
					totalReplies: 0,
					scheduledCount: 0,
					totalViews: 0,
				})),
			);

			const allStats = await Promise.all(statsPromises);

			// Get posts for all accounts to count and calculate engagement
			const posts = await this.getPosts("ALL");
			const groupPosts = posts.filter(
				(post) =>
					groupAccounts.some((acc) => acc.id === post.accountId) &&
					post.status === "published",
			);

			// Aggregate totals
			let totalViews = 0;
			let totalLikes = 0;
			let totalReplies = 0;
			let totalReposts = 0;

			allStats.forEach((stats) => {
				totalViews += stats.totalViews || 0;
				totalLikes += stats.totalLikes || 0;
				totalReplies += stats.totalReplies || 0;
			});

			// Calculate from posts if stats are low
			groupPosts.forEach((post) => {
				totalReposts += post.performance?.reposts || 0;
			});

			// Calculate total followers
			const totalFollowers = groupAccounts.reduce(
				(sum, acc) => sum + (acc.followers || 0),
				0,
			);

			// Calculate engagement rate (likes + replies + reposts) / views * 100
			const totalEngagement = totalLikes + totalReplies + totalReposts;
			const engagementRate =
				totalViews > 0 ? (totalEngagement / totalViews) * 100 : 0;

			// Calculate average engagement per account
			const avgEngagementPerAccount =
				groupAccounts.length > 0 ? totalEngagement / groupAccounts.length : 0;

			// Find top performing account (by followers for now, could be by engagement)
			let topPerformingAccount = groupAccounts[0];
			groupAccounts.forEach((acc) => {
				if ((acc.followers || 0) > (topPerformingAccount?.followers || 0)) {
					topPerformingAccount = acc;
				}
			});

			// Calculate follower growth from account_analytics historical data
			let followerGrowth = 0;
			try {
				const accountIds = groupAccounts.map((acc) => acc.id);

				// Get latest analytics for each account to sum follower_growth
				const { data: analyticsData } = await supabase
					.from("account_analytics")
					.select("account_id, followers_count, follower_growth, date")
					.in("account_id", accountIds)
					.order("date", { ascending: false });

				if (analyticsData && analyticsData.length > 0) {
					// Get the most recent entry for each account
					const latestByAccount = new Map<
						string,
						{ followers_count: number; follower_growth: number }
					>();
					for (const row of analyticsData) {
						if (!latestByAccount.has(row.account_id)) {
							latestByAccount.set(row.account_id, {
								followers_count: row.followers_count || 0,
								follower_growth: row.follower_growth || 0,
							});
						}
					}

					// Sum follower growth across all accounts
					let totalGrowth = 0;
					let totalPreviousFollowers = 0;
					for (const [, data] of latestByAccount) {
						totalGrowth += data.follower_growth;
						totalPreviousFollowers += Math.max(
							0,
							data.followers_count - data.follower_growth,
						);
					}

					// Calculate growth percentage
					if (totalPreviousFollowers > 0) {
						followerGrowth = (totalGrowth / totalPreviousFollowers) * 100;
					} else if (totalGrowth > 0) {
						followerGrowth = 100; // All new followers
					}
				}
			} catch (e) {
				log.error("Failed to calculate group follower growth:", e);
			}

			return {
				totalFollowers,
				totalViews,
				totalLikes,
				totalReplies,
				totalReposts,
				engagementRate: Math.min(engagementRate, 100), // Cap at 100%
				followerGrowth,
				avgEngagementPerAccount,
				topPerformingAccountId: topPerformingAccount?.id,
				topPerformingAccountHandle: topPerformingAccount?.handle,
				postCount: groupPosts.length,
			};
		} catch (error) {
			log.error("Failed to get group insights:", error);
			return {
				totalFollowers: 0,
				totalViews: 0,
				totalLikes: 0,
				totalReplies: 0,
				totalReposts: 0,
				engagementRate: 0,
				followerGrowth: 0,
				avgEngagementPerAccount: 0,
				postCount: 0,
			};
		}
	}

	// --- GROUP VOICE PROFILES ---

	// Update a group's voice profile
	async updateGroupVoiceProfile(
		groupId: string,
		profile: Record<string, unknown> | null,
	): Promise<void> {
		try {
			if (!this.isAuthenticated()) throw new Error("Not authenticated");

			const userId = await this.getCurrentUserId();
			if (!userId) throw new Error("Not authenticated");

			// biome-ignore lint/suspicious/noExplicitAny: Supabase type narrowing for voice_profile column
			const { error } = await (supabase.from("account_groups") as any)
				.update({
					voice_profile: profile,
					updated_at: new Date().toISOString(),
				})
				.eq("id", groupId)
				.eq("user_id", userId);

			if (error) {
				log.error("Failed to update group voice profile:", error);
				throw error;
			}
		} catch (error) {
			log.error("Failed to update group voice profile:", error);
			throw error;
		}
	}

	// Bulk copy voice profile from one account to multiple target accounts
	// Preserves each target's extracted_style and warmup
	async bulkCopyVoiceProfile(
		sourceAccountId: string,
		targetAccountIds: string[],
	): Promise<{ copied: number; failed: number }> {
		try {
			if (!this.isAuthenticated()) throw new Error("Not authenticated");

			const userId = await this.getCurrentUserId();
			if (!userId) throw new Error("Not authenticated");

			// Fetch source account's ai_config
			const { data: sourceData, error: sourceError } = await supabase
				.from("accounts")
				.select("ai_config")
				.eq("id", sourceAccountId)
				.eq("user_id", userId)
				.maybeSingle();

			if (sourceError || !sourceData?.ai_config) {
				throw new Error("Source account has no voice profile");
			}

			const sourceConfig = sourceData.ai_config as Record<string, unknown>;

			// Extract voice fields to copy (exclude extracted_style and warmup)
			const voiceFields: Record<string, unknown> = {};
			const copyKeys = [
				"voice_profile",
				"focus_topics",
				"avoid_topics",
				"avoid_words",
				"emoji_usage",
				"cta_style",
			];
			for (const key of copyKeys) {
				if (sourceConfig[key] !== undefined) {
					voiceFields[key] = sourceConfig[key];
				}
			}

			let copied = 0;
			let failed = 0;

			for (const targetId of targetAccountIds) {
				try {
					// Fetch target's existing ai_config to preserve extracted_style and warmup
					const { data: targetData } = await supabase
						.from("accounts")
						.select("ai_config")
						.eq("id", targetId)
						.eq("user_id", userId)
						.maybeSingle();

					const existingConfig =
						(targetData?.ai_config as Record<string, unknown>) || {};

					// Merge: copy voice fields, preserve target's extracted_style and warmup
					const mergedConfig = {
						...existingConfig,
						...voiceFields,
						// Preserve target-specific fields
						extracted_style: existingConfig.extracted_style,
						warmup: existingConfig.warmup,
					};

					// biome-ignore lint/suspicious/noExplicitAny: Supabase type narrowing for ai_config column
					const { error } = await (supabase.from("accounts") as any)
						.update({ ai_config: mergedConfig })
						.eq("id", targetId)
						.eq("user_id", userId);

					if (error) {
						log.error(
							`Failed to copy voice profile to account ${targetId}:`,
							error,
						);
						failed++;
					} else {
						copied++;
					}
				} catch {
					failed++;
				}
			}

			this.invalidateCache("accounts");
			return { copied, failed };
		} catch (error) {
			log.error("Failed to bulk copy voice profile:", error);
			throw error;
		}
	}

	// --- RATE LIMIT STATUS ---
	/**
	 * Get rate limit status for an account
	 * Threads API limits: 3 posts/hour, 20 posts/day per account
	 */
	async getRateLimitStatus(
		accountId: string,
		timezone?: string,
	): Promise<{
		postsThisHour: number;
		postsToday: number;
		maxPerHour: number;
		maxPerDay: number;
		nextAvailableSlot: Date | null;
		canPostNow: boolean;
	}> {
		try {
			const posts = await this.getPosts(accountId);
			const now = new Date();
			const oneHourAgo = new Date(now.getTime() - 60 * 60 * 1000);
			let startOfDay: Date;
			if (timezone) {
				const parts = new Intl.DateTimeFormat("en-US", {
					timeZone: timezone,
					year: "numeric",
					month: "2-digit",
					day: "2-digit",
				}).formatToParts(now);
				const year = parseInt(
					parts.find((p) => p.type === "year")?.value ?? "0",
					10,
				);
				const month =
					parseInt(parts.find((p) => p.type === "month")?.value ?? "0", 10) - 1;
				const day = parseInt(
					parts.find((p) => p.type === "day")?.value ?? "0",
					10,
				);
				const localMidnight = new Date(year, month, day);
				const tzOffset = localMidnight.getTimezoneOffset();
				const targetDate = new Date(
					now.toLocaleString("en-US", { timeZone: timezone }),
				);
				const targetOffset = (now.getTime() - targetDate.getTime()) / 60000;
				startOfDay = new Date(
					localMidnight.getTime() + (tzOffset + targetOffset) * 60000,
				);
			} else {
				startOfDay = new Date(now);
				startOfDay.setHours(0, 0, 0, 0);
			}

			// Filter for published and scheduled posts
			const recentPosts = posts.filter((p) => {
				const postDate = p.publishedAt
					? new Date(p.publishedAt as string)
					: p.scheduledDate
						? new Date(p.scheduledDate)
						: null;
				if (!postDate) return false;
				return (
					(p.status === "published" || p.status === "scheduled") &&
					p.accountId === accountId
				);
			});

			// Count posts in last hour
			const postsThisHour = recentPosts.filter((p) => {
				const postDate = p.publishedAt
					? new Date(p.publishedAt as string)
					: p.scheduledDate
						? new Date(p.scheduledDate)
						: null;
				return postDate && postDate >= oneHourAgo;
			}).length;

			// Count posts today
			const postsToday = recentPosts.filter((p) => {
				const postDate = p.publishedAt
					? new Date(p.publishedAt as string)
					: p.scheduledDate
						? new Date(p.scheduledDate)
						: null;
				return postDate && postDate >= startOfDay;
			}).length;

			const maxPerHour = 3;
			const maxPerDay = 20;
			const canPostNow = postsThisHour < maxPerHour && postsToday < maxPerDay;

			// Calculate next available slot
			let nextAvailableSlot: Date | null = null;
			if (!canPostNow) {
				if (postsThisHour >= maxPerHour) {
					// Find oldest post in the hour window and add 1 hour
					const oldestInHour = recentPosts
						.filter((p) => {
							const postDate = p.publishedAt
								? new Date(p.publishedAt as string)
								: p.scheduledDate
									? new Date(p.scheduledDate)
									: null;
							return postDate && postDate >= oneHourAgo;
						})
						.sort((a, b) => {
							const aDate = (a.publishedAt as string) || a.scheduledDate || "";
							const bDate = (b.publishedAt as string) || b.scheduledDate || "";
							return new Date(aDate).getTime() - new Date(bDate).getTime();
						})[0];

					if (oldestInHour) {
						const oldestDate = new Date(
							(oldestInHour.publishedAt as string) ||
								oldestInHour.scheduledDate ||
								now,
						);
						nextAvailableSlot = new Date(oldestDate.getTime() + 60 * 60 * 1000);
					}
				} else if (postsToday >= maxPerDay) {
					// Next slot is tomorrow
					nextAvailableSlot = new Date(startOfDay);
					nextAvailableSlot.setDate(nextAvailableSlot.getDate() + 1);
				}
			}

			return {
				postsThisHour,
				postsToday,
				maxPerHour,
				maxPerDay,
				nextAvailableSlot,
				canPostNow,
			};
		} catch (error) {
			log.error("Failed to get rate limit status:", error);
			return {
				postsThisHour: 3,
				postsToday: 20,
				maxPerHour: 3,
				maxPerDay: 20,
				nextAvailableSlot: null,
				canPostNow: false,
			};
		}
	}
}

export const dataService = new DataService();
