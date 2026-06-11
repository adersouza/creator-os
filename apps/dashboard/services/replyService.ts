// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
/// <reference path="../vite-env.d.ts" />
/**
 * Reply Service
 * Handles fetching and posting replies via Vercel API routes
 */

import type { ThreadMention, ThreadReply } from "../types.js";
import type { ConversationThread, SentimentType } from "../types/analytics.js";
import type { VoiceProfile } from "../types/voice.js";
import { analyzeSentiment } from "../utils/sentiment.js";

import { createServiceLogger, getUserIdAsync, supabase } from "./api/shared.js";

const log = createServiceLogger("replyService");

// Type definition for unsubscribe function
type Unsubscribe = () => void;

// Interface for sent replies (replies made by the user)
export interface SentReply {
	id: string;
	content: string;
	// biome-ignore lint/suspicious/noExplicitAny: ISO string or Date, not enforced at DB level
	timestamp: any;
	accountId: string;
	accountHandle: string;
	avatarUrl?: string | undefined;
	replyToUsername: string;
	replyToPostId: string;
	// Metrics (fetched from Threads API)
	likeCount?: number | undefined;
	replyCount?: number | undefined;
	repostCount?: number | undefined;
	// biome-ignore lint/suspicious/noExplicitAny: ISO string or Date, not enforced at DB level
	metricsUpdatedAt?: any | undefined;
}

class ReplyService {
	// Get current user ID (async)
	private async getUserIdAsync(): Promise<string> {
		return getUserIdAsync();
	}

	/**
	 * Centralized POST helper for /api/replies.
	 * Attaches the current JWT, retries once with a refreshed token on 401.
	 */
	private async repliesPost(
		action: string,
		body?: Record<string, unknown>,
	): Promise<Response> {
		const {
			data: { session },
		} = await supabase.auth.getSession();
		if (!session) throw new Error("User not authenticated");

		const headers: Record<string, string> = {
			"Content-Type": "application/json",
			Authorization: `Bearer ${session.access_token}`,
		};
		const url = `/api/replies?action=${action}`;
		const init: RequestInit = {
			method: "POST",
			headers,
			...(body ? { body: JSON.stringify(body) } : {}),
		};

		let response = await fetch(url, init);

		// Session expired server-side — refresh once and retry
		if (response.status === 401) {
			const {
				data: { session: refreshed },
			} = await supabase.auth.refreshSession();
			if (!refreshed) throw new Error("Session expired. Please log in again.");
			response = await fetch(url, {
				...init,
				headers: {
					...headers,
					Authorization: `Bearer ${refreshed.access_token}`,
				},
			});
		}

		return response;
	}

	/**
	 * Fetch replies for a specific post from Threads API
	 * This triggers a fresh fetch from the API and stores in database
	 */
	async fetchRepliesFromAPI(
		postId: string,
		accountId: string,
	): Promise<ThreadReply[]> {
		const response = await this.repliesPost("sync", { postId, accountId });

		if (!response.ok) {
			const error = await response.json();
			throw new Error(error.error || "Failed to fetch replies");
		}

		const data = await response.json();
		return data.replies || [];
	}

	/**
	 * Get all replies from database (previously fetched)
	 * Optionally filter by account
	 * @param forceRefresh - If true, bypass cache and fetch from server
	 */
	async getReplies(
		accountId: string = "ALL",
		limitCount: number = 100,
		forceRefresh: boolean = false,
		ascending: boolean = false,
	): Promise<ThreadReply[]> {
		const userId = await this.getUserIdAsync();

		log.log(
			`📥 getReplies (Supabase): accountId=${accountId}, forceRefresh=${forceRefresh}`,
		);

		// Step 1: Get post IDs that belong to the user (PostgREST doesn't support filtering on joined tables)
		let postsQuery = supabase
			.from("posts")
			.select("id, account_id, content")
			.eq("user_id", userId)
			.eq("status", "published");

		if (accountId !== "ALL") {
			postsQuery = postsQuery.eq("account_id", accountId);
		}

		const { data: postsData, error: postsError } = await postsQuery;

		if (postsError || !postsData || postsData.length === 0) {
			log.log("No published posts found for user");
			return [];
		}

		const postIds = postsData.map((p) => p.id);
		const postsMap = new Map(postsData.map((p) => [p.id, p]));

		log.log(`Found ${postIds.length} published posts, fetching replies...`);

		// Step 2: Get replies for those posts in batches to avoid URL length limits
		// Supabase REST API has URL length limits, so we batch the requests
		const BATCH_SIZE = 50;
		// biome-ignore lint/suspicious/noExplicitAny: Supabase row shape not fully typed
		let allReplies: any[] = [];

		try {
			for (let i = 0; i < postIds.length; i += BATCH_SIZE) {
				const batchIds = postIds.slice(i, i + BATCH_SIZE);
				const { data, error } = await supabase
					.from("post_replies")
					.select("*")
					.in("post_id", batchIds)
					.order("created_at", { ascending });

				if (error) {
					log.warn(
						`Failed to fetch replies batch ${i / BATCH_SIZE + 1}:`,
						error,
					);
					// Continue with other batches instead of failing completely
					continue;
				}

				if (data) {
					allReplies = allReplies.concat(data);
				}
			}
		} catch (error) {
			log.warn("Failed to fetch replies from Supabase:", error);
			return [];
		}

		// Sort all replies by created_at and limit
		allReplies.sort((a, b) => {
			const diff =
				new Date(a.created_at).getTime() - new Date(b.created_at).getTime();
			return ascending ? diff : -diff;
		});
		const data = allReplies.slice(0, limitCount);

		// biome-ignore lint/suspicious/noExplicitAny: Supabase row shape not fully typed
		const replies: ThreadReply[] = (data || []).map((row: any) => {
			const post = postsMap.get(row.post_id);
			return {
				id: row.id,
				postId: row.post_id,
				threadsReplyId: row.threads_reply_id || row.id,
				text: row.content || "",
				username: row.username || "unknown",
				profilePicUrl: row.avatar_url || undefined,
				timestamp: row.created_at,
				likeCount: row.likes_count || 0,
				replyCount: row.replies_count || 0,
				isRead: row.is_read || false,
				isHidden: false,
				accountId: post?.account_id || "",
				accountHandle: row.username || "",
				originalPostContent: post?.content?.substring(0, 100) || "",
			};
		});

		log.log(`✅ Returning ${replies.length} replies from Supabase`);
		return replies;
	}

	/**
	 * Get unread reply count
	 */
	async getUnreadCount(accountId: string = "ALL"): Promise<number> {
		const replies = await this.getReplies(accountId, 100);
		return replies.filter((r) => !r.isRead).length;
	}

	/**
	 * Mark a reply as read
	 */
	async markAsRead(postId: string, replyId: string): Promise<void> {
		log.log(`📖 markAsRead: replyId=${replyId}, postId=${postId}`);

		const response = await this.repliesPost("mark-read", { replyId });

		if (!response.ok) {
			const error = await response.json().catch(() => ({}));
			log.error(`Failed to mark reply ${replyId} as read:`, error);
		} else {
			log.log(`✅ markAsRead: Successfully marked reply ${replyId} as read`);
		}
	}

	/**
	 * Mark all replies as read for a specific post or all posts
	 */
	async markAllAsRead(postId?: string): Promise<void> {
		log.log(`📖 markAllAsRead: postId=${postId || "all user posts"}`);

		const response = await this.repliesPost("mark-all-read", { postId });

		if (!response.ok) {
			const error = await response.json().catch(() => ({}));
			log.error("Failed to mark all replies as read:", error);
		} else {
			const data = await response.json().catch(() => ({ updatedCount: 0 }));
			log.log(
				`✅ markAllAsRead: Successfully marked ${data.updatedCount || 0} replies as read`,
			);
		}
	}

	/**
	 * Hide or unhide a reply on Threads
	 * Uses the manage_reply endpoint to hide/show replies
	 */
	async hideReply(
		accountId: string,
		replyId: string,
		_postId: string,
		hide: boolean,
	): Promise<{ success: boolean; error?: string | undefined }> {
		try {
			const response = await this.repliesPost("manage", {
				accountId,
				replyId,
				hide,
			});

			if (!response.ok) {
				const error = await response.json();
				return {
					success: false,
					error: error.error || "Failed to manage reply",
				};
			}

			// Note: post_replies table doesn't have is_hidden column
			// The hide/unhide is done via Threads API, we don't track it locally
			return response.json();
		} catch (error: unknown) {
			return {
				success: false,
				error: error instanceof Error ? error.message : String(error),
			};
		}
	}

	/**
	 * Post a reply to a Threads post
	 */
	async postReply(
		accountId: string,
		replyToId: string,
		content: string,
		replyToUsername?: string,
		accountHandle?: string,
		avatarUrl?: string,
	): Promise<{ success: boolean; replyId?: string | undefined; error?: string | undefined }> {
		try {
			// Note: Server-side sanitization applied in API handler via sanitizeMessage()
			const response = await this.repliesPost("post", {
				accountId,
				replyToId,
				content,
			});

			if (!response.ok) {
				const error = await response.json();
				return { success: false, error: error.error || "Failed to post reply" };
			}

			const data = await response.json();

			// If successful, store the sent reply locally
			// Note: Content was already sanitized server-side before publishing
			if (data.success) {
				try {
					const {
						data: { session },
					} = await supabase.auth.getSession();
					const userId = session?.user?.id;
					if (userId) {
						await supabase.from("sent_replies").insert({
							user_id: userId,
							content,
							account_id: accountId,
							account_handle: accountHandle || "",
							avatar_url: avatarUrl || "",
							reply_to_username: replyToUsername || "",
							reply_to_post_id: replyToId,
							threads_reply_id: data.replyId || null,
						});
					}
				} catch (storeError) {
					log.warn("Failed to store sent reply locally:", storeError);
					// Don't fail the whole operation if storing fails
				}
			}

			return data;
		} catch (error: unknown) {
			return {
				success: false,
				error: error instanceof Error ? error.message : String(error),
			};
		}
	}

	/**
	 * Get sent replies (replies made by the user)
	 */
	async getSentReplies(
		accountId: string = "ALL",
		limitCount: number = 100,
	): Promise<SentReply[]> {
		try {
			const userId = await this.getUserIdAsync();

			let query = supabase
				.from("sent_replies")
				.select("*")
				.eq("user_id", userId)
				.order("created_at", { ascending: false })
				.limit(limitCount);

			if (accountId !== "ALL") {
				query = query.eq("account_id", accountId);
			}

			const { data, error } = await query;

			if (error) {
				log.warn("Failed to fetch sent replies from Supabase:", error);
				return [];
			}

			// biome-ignore lint/suspicious/noExplicitAny: Supabase row shape not fully typed
			return (data || []).map((row: any) => ({
				id: row.id,
				content: row.content || "",
				timestamp: row.created_at,
				accountId: row.account_id || "",
				accountHandle: "", // Not stored in table, will be looked up separately if needed
				avatarUrl: "", // Not stored in table
				replyToUsername: row.reply_to_username || "",
				replyToPostId: row.reply_to_post_id || "",
				likeCount: row.likes_count || 0, // Column is likes_count not like_count
				replyCount: row.replies_count || 0, // Column is replies_count not reply_count
				repostCount: row.reposts_count || 0, // Column is reposts_count not repost_count
				metricsUpdatedAt: row.metrics_synced_at, // Column is metrics_synced_at not metrics_updated_at
			}));
		} catch (error) {
			log.warn("Failed to fetch sent replies:", error);
			return [];
		}
	}

	/**
	 * Sync metrics for sent replies from Threads API
	 * Fetches like count, reply count, etc. for replies the user has sent
	 */
	async syncSentReplyMetrics(): Promise<{
		success: boolean;
		message: string;
		updatedCount: number;
	}> {
		try {
			const response = await this.repliesPost("sync-metrics");

			if (!response.ok) {
				const error = await response.json();
				return {
					success: false,
					message: error.error || "Failed to sync metrics",
					updatedCount: 0,
				};
			}

			return response.json();
		} catch (error: unknown) {
			return {
				success: false,
				message: error instanceof Error ? error.message : String(error),
				updatedCount: 0,
			};
		}
	}

	/**
	 * Sync all replies from Threads API
	 * Fetches replies for all published posts
	 */
	async syncAllReplies(): Promise<{
		success: boolean;
		message: string;
		repliesFound: number;
	}> {
		try {
			const response = await this.repliesPost("sync");

			if (!response.ok) {
				const error = await response.json();
				return {
					success: false,
					message: error.error || "Failed to sync replies",
					repliesFound: 0,
				};
			}

			return response.json();
		} catch (error: unknown) {
			return {
				success: false,
				message: error instanceof Error ? error.message : String(error),
				repliesFound: 0,
			};
		}
	}

	/**
	 * Create a thread chain (multiple connected posts)
	 */
	async createThreadChain(
		accountId: string,
		posts: string[],
	): Promise<{ success: boolean; postIds?: string[] | undefined; error?: string | undefined }> {
		try {
			const {
				data: { session },
			} = await supabase.auth.getSession();
			if (!session) throw new Error("User not authenticated");

			const response = await fetch("/api/posts?action=thread-chain", {
				method: "POST",
				headers: {
					"Content-Type": "application/json",
					Authorization: `Bearer ${session.access_token}`,
				},
				body: JSON.stringify({ accountId, posts }),
			});

			if (!response.ok) {
				const error = await response.json();
				return {
					success: false,
					error: error.error || "Failed to create thread chain",
				};
			}

			return response.json();
		} catch (error: unknown) {
			return {
				success: false,
				error: error instanceof Error ? error.message : String(error),
			};
		}
	}

	/**
	 * Subscribe to real-time reply updates.
	 *
	 * INTENTIONALLY returns a no-op unsubscribe function.
	 *
	 * WHY: Supabase Realtime subscriptions on post_replies triggered infinite
	 * re-render loops because each update caused a state change that triggered
	 * another query, which produced another Realtime event. The nested
	 * collection structure (posts -> post_replies) makes it especially fragile.
	 *
	 * ALTERNATIVE: useInboxData.ts implements a lightweight 60-second polling
	 * interval that only fires when the browser tab is visible and no sync is
	 * in progress. This provides near-real-time updates without the infinite
	 * loop risk. If true real-time is needed in the future, consider using
	 * Supabase Realtime with a debounced handler and a generation counter to
	 * discard stale events.
	 */
	subscribeToReplies(
		_accountId: string = "ALL",
		_onUpdate: (replies: ThreadReply[]) => void,
	): Unsubscribe {
		return () => {};
	}

	/**
	 * Fetch mentions from Threads API
	 * Gets posts where the user's account was mentioned
	 */
	async fetchMentionsFromAPI(
		accountId: string,
	): Promise<{ success: boolean; message: string; mentionsFound: number }> {
		try {
			const response = await this.repliesPost("fetch-mentions", { accountId });

			if (!response.ok) {
				const error = await response.json();
				return {
					success: false,
					message: error.error || "Failed to fetch mentions",
					mentionsFound: 0,
				};
			}

			return response.json();
		} catch (error: unknown) {
			return {
				success: false,
				message: error instanceof Error ? error.message : String(error),
				mentionsFound: 0,
			};
		}
	}

	/**
	 * Fetch mentions for multiple accounts in a single API call.
	 * The API queues a batch job server-side instead of 1 request per account.
	 */
	async fetchMentionsBatch(
		accountIds: string[],
	): Promise<{ success: boolean; message: string; mentionsFound: number }> {
		try {
			const response = await this.repliesPost("fetch-mentions", { accountIds });

			if (!response.ok) {
				const error = await response.json();
				return {
					success: false,
					message: error.error || "Failed to fetch mentions",
					mentionsFound: 0,
				};
			}

			return response.json();
		} catch (error: unknown) {
			return {
				success: false,
				message: error instanceof Error ? error.message : String(error),
				mentionsFound: 0,
			};
		}
	}

	/**
	 * Get all mentions from database
	 * Optionally filter by account
	 */
	async getMentions(
		accountId: string = "ALL",
		limitCount: number = 100,
	): Promise<ThreadMention[]> {
		try {
			const userId = await this.getUserIdAsync();

			let query = supabase
				.from("mentions")
				.select("*")
				.eq("user_id", userId)
				.order("mentioned_at", { ascending: false })
				.limit(limitCount);

			if (accountId !== "ALL") {
				query = query.eq("account_id", accountId);
			}

			const { data, error } = await query;

			if (error) {
				log.warn("Failed to fetch mentions from Supabase:", error);
				return [];
			}

			// biome-ignore lint/suspicious/noExplicitAny: Supabase row shape not fully typed
			return (data || []).map((row: any) => ({
				id: row.id,
				threadsMentionId: row.threads_post_id || row.id,
				text: row.content || "",
				username: row.mentioned_by_username || "unknown",
				timestamp: row.mentioned_at,
				mediaType: null,
				mediaUrl: row.media_urls?.[0] || null,
				permalink: row.permalink || null,
				isReply: false,
				accountId: row.account_id || "",
				accountHandle: "",
				isRead: row.is_read ?? false,
				fetchedAt: row.created_at,
			}));
		} catch (error) {
			log.warn("Failed to fetch mentions:", error);
			return [];
		}
	}

	/**
	 * Get unread mention count
	 */
	async getUnreadMentionCount(accountId: string = "ALL"): Promise<number> {
		const mentions = await this.getMentions(accountId, 100);
		return mentions.filter((m) => !m.isRead).length;
	}

	/**
	 * Mark a mention as read
	 */
	async markMentionAsRead(mentionId: string): Promise<void> {
		const userId = await this.getUserIdAsync();
		const { error } = await supabase
			.from("mentions")
			.update({ is_read: true })
			.eq("id", mentionId)
			.eq("user_id", userId);

		if (error) {
			log.warn("Failed to mark mention as read:", error);
			throw error;
		}
	}

	/**
	 * Mark all mentions as read
	 */
	async markAllMentionsAsRead(): Promise<void> {
		const userId = await this.getUserIdAsync();
		const { error } = await supabase
			.from("mentions")
			.update({ is_read: true })
			.eq("user_id", userId)
			.eq("is_read", false);

		if (error) {
			log.warn("Failed to mark all mentions as read:", error);
			throw error;
		}
	}

	/**
	 * Get conversation summaries grouped by post
	 * Shows threads with reply counts, sentiment, and top repliers
	 */
	async getConversationSummaries(
		accountId?: string,
		limit: number = 5,
	): Promise<ConversationThread[]> {
		try {
			const userId = await this.getUserIdAsync();

			// Step 1: Get user's published posts
			let postsQuery = supabase
				.from("posts")
				.select("id, account_id, content, threads_post_id")
				.eq("user_id", userId)
				.eq("status", "published")
				.order("created_at", { ascending: false });

			if (accountId && accountId !== "ALL") {
				postsQuery = postsQuery.eq("account_id", accountId);
			}

			const { data: postsData, error: postsError } = await postsQuery;

			if (postsError || !postsData || postsData.length === 0) {
				log.log("No published posts found for conversation summaries");
				return [];
			}

			const postIds = postsData.map((p) => p.id);
			const postsMap = new Map(postsData.map((p) => [p.id, p]));

			// Step 2: Get all replies for these posts in batches to avoid URL length limits
			const BATCH_SIZE = 50;
			// biome-ignore lint/suspicious/noExplicitAny: Supabase row shape not fully typed
			let repliesData: any[] = [];

			try {
				for (let i = 0; i < postIds.length; i += BATCH_SIZE) {
					const batchIds = postIds.slice(i, i + BATCH_SIZE);
					const { data, error } = await supabase
						.from("post_replies")
						.select("*")
						.in("post_id", batchIds)
						.order("created_at", { ascending: false });

					if (error) {
						log.warn(
							`Failed to fetch replies batch ${i / BATCH_SIZE + 1}:`,
							error,
						);
						// Continue with other batches instead of failing completely
						continue;
					}

					if (data) {
						repliesData = repliesData.concat(data);
					}
				}
			} catch (error) {
				log.warn("Failed to fetch replies for conversations:", error);
				// Return empty array but don't fail the whole function
			}

			// Step 3: Get sent replies count per post
			const { data: sentRepliesData } = await supabase
				.from("sent_replies")
				.select("reply_to_post_id")
				.eq("user_id", userId);

			const sentRepliesCountMap = new Map<string, number>();
			// biome-ignore lint/suspicious/noExplicitAny: Supabase row shape not fully typed
			(sentRepliesData || []).forEach((sr: any) => {
				const postId = sr.reply_to_post_id;
				sentRepliesCountMap.set(
					postId,
					(sentRepliesCountMap.get(postId) || 0) + 1,
				);
			});

			// Step 4: Group replies by post and build conversation threads
			// biome-ignore lint/suspicious/noExplicitAny: Supabase row shape not fully typed
			const repliesByPost = new Map<string, any[]>();
			// biome-ignore lint/suspicious/noExplicitAny: Supabase row shape not fully typed
			(repliesData || []).forEach((reply: any) => {
				const postId = reply.post_id;
				if (!repliesByPost.has(postId)) {
					repliesByPost.set(postId, []);
				}
				repliesByPost.get(postId)?.push(reply);
			});

			// Build conversation threads
			const threads: ConversationThread[] = [];

			for (const [postId, replies] of repliesByPost) {
				const post = postsMap.get(postId);
				if (!post || replies.length === 0) continue;

				// Analyze sentiments of all replies
				const sentimentTags: SentimentType[] = [];
				const sentimentCounts = {
					positive: 0,
					negative: 0,
					neutral: 0,
					question: 0,
				};

				// biome-ignore lint/suspicious/noExplicitAny: Supabase row shape not fully typed
				replies.forEach((reply: any) => {
					const sentiment = analyzeSentiment(reply.content || "");
					sentimentCounts[sentiment]++;
				});

				// Add dominant sentiments
				if (sentimentCounts.positive > 0) sentimentTags.push("positive");
				if (sentimentCounts.negative > 0) sentimentTags.push("negative");
				if (sentimentCounts.question > 0) sentimentTags.push("question");
				if (sentimentTags.length === 0) sentimentTags.push("neutral");

				// Find top repliers
				const replierCounts = new Map<
					string,
					{ count: number; avatarUrl?: string | undefined }
				>();
				// biome-ignore lint/suspicious/noExplicitAny: Supabase row shape not fully typed
				replies.forEach((reply: any) => {
					const username = reply.username || "unknown";
					const current = replierCounts.get(username) || {
						count: 0,
						avatarUrl: reply.avatar_url,
					};
					replierCounts.set(username, {
						count: current.count + 1,
						avatarUrl: current.avatarUrl || reply.avatar_url,
					});
				});

				const topRepliers = Array.from(replierCounts.entries())
					.sort((a, b) => b[1].count - a[1].count)
					.slice(0, 3)
					.map(([username, data]) => ({
						username,
						avatarUrl: data.avatarUrl,
						replyCount: data.count,
					}));

				// Find latest reply timestamp
				// biome-ignore lint/suspicious/noExplicitAny: Supabase row shape not fully typed
				const latestReply = replies.reduce((latest: any, reply: any) => {
					const replyDate = new Date(reply.created_at);
					const latestDate = latest ? new Date(latest.created_at) : new Date(0);
					return replyDate > latestDate ? reply : latest;
				}, null);

				// Count unread replies
				// biome-ignore lint/suspicious/noExplicitAny: Supabase row shape not fully typed
				const unreadCount = replies.filter((r: any) => !r.is_read).length;

				threads.push({
					id: postId,
					postId: post.threads_post_id || postId,
					accountId: post.account_id || "",
					postContent: (post.content || "").substring(0, 100),
					latestReplyContent: latestReply
						? (latestReply.content || "").substring(0, 150)
						: undefined,
					latestReplyId: latestReply?.threads_reply_id,
					replyCount: replies.length,
					sentRepliesCount: sentRepliesCountMap.get(postId) || 0,
					sentimentTags,
					latestReplyAt: latestReply
						? new Date(latestReply.created_at)
						: new Date(),
					unreadCount,
					topRepliers,
				});
			}

			// Sort by latest reply and limit
			threads.sort(
				(a, b) => b.latestReplyAt.getTime() - a.latestReplyAt.getTime(),
			);

			return threads.slice(0, limit);
		} catch (error) {
			log.warn("Failed to get conversation summaries:", error);
			return [];
		}
	}

	/**
	 * Generate an AI reply draft using Gemini
	 * Uses voice profile for consistent tone
	 */
	async generateAIReplyDraft(
		threadContext: { postContent: string; recentReplies: string[] },
		replyToUsername: string,
		voiceProfile?: VoiceProfile,
	): Promise<string> {
		// Use the new options method and return the first option
		const options = await this.generateAIReplyOptions(
			threadContext,
			replyToUsername,
			voiceProfile,
		);
		return options[0]?.text || "Thanks for your reply!";
	}

	/**
	 * Generate multiple AI reply options for selection
	 * Returns structured options with different styles
	 */
	async generateAIReplyOptions(
		threadContext: { postContent: string; recentReplies: string[] },
		replyToUsername: string,
		voiceProfile?: VoiceProfile,
	): Promise<{ text: string; style: string }[]> {
		try {
			const aiServiceModule = await import("./aiService.js");
			const { generateContent } = aiServiceModule;

			// Load feedback context for personalization
			let feedbackContext = "";
			try {
				const { buildFeedbackContext } = await import(
					"../utils/buildFeedbackContext.js"
				);
				feedbackContext = await buildFeedbackContext("reply_suggestion");
			} catch {
				/* non-critical */
			}

			// Build voice context
			let voiceContext = "";
			if (voiceProfile) {
				const toneDescriptions: string[] = [];
				if (voiceProfile.tone) toneDescriptions.push(voiceProfile.tone);

				voiceContext = `Voice: ${toneDescriptions.join(", ") || "conversational"}, ${voiceProfile.voice_profile || "engaging"}`;
			}

			const prompt = `Generate 3 short reply options to @${replyToUsername} on Threads.

Their message: "${threadContext.postContent.substring(0, 200)}"

${voiceContext ? `Style: ${voiceContext}` : ""}${feedbackContext}

Return ONLY valid JSON array (no markdown, no explanation):
[
  {"text": "brief friendly reply", "style": "friendly"},
  {"text": "brief witty reply", "style": "witty"},
  {"text": "brief enthusiastic reply", "style": "enthusiastic"}
]

Rules:
- Each reply max 100 characters
- Sound human, not robotic
- 0-1 emojis per reply
- No hashtags`;

			const result = await generateContent(prompt);

			// Parse JSON from response
			let jsonStr = result.trim();

			// Remove markdown code blocks if present
			if (jsonStr.includes("```json")) {
				jsonStr = jsonStr.split("```json")[1]!.split("```")[0]!.trim();
			} else if (jsonStr.includes("```")) {
				jsonStr = jsonStr.split("```")[1]!.split("```")[0]!.trim();
			}

			// Find JSON array
			const jsonMatch = jsonStr.match(/\[[\s\S]*\]/);
			if (!jsonMatch) {
				log.warn("Could not find JSON array in AI response");
				return this.getDefaultReplyOptions(replyToUsername);
			}

			const parsed = JSON.parse(jsonMatch[0]);

			if (Array.isArray(parsed) && parsed.length > 0) {
				return parsed
					.slice(0, 3)
					.map((item: { text?: string | undefined; style?: string | undefined }) => ({
						text: String(item.text || "").substring(0, 280),
						style: String(item.style || "friendly"),
					}))
					.filter((item) => item.text.length > 0);
			}

			return this.getDefaultReplyOptions(replyToUsername);
		} catch (error) {
			log.error("Failed to generate AI reply options:", error);
			return this.getDefaultReplyOptions(replyToUsername);
		}
	}

	/**
	 * Default options when AI fails
	 */
	private getDefaultReplyOptions(
		username: string,
	): { text: string; style: string }[] {
		return [
			{ text: `Thanks for sharing! Really appreciate it`, style: "friendly" },
			{ text: `Love this perspective @${username}!`, style: "enthusiastic" },
			{ text: `Great point! What made you think of this?`, style: "curious" },
		];
	}
}

export const replyService = new ReplyService();
