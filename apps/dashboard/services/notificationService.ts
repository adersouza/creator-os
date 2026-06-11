/// <reference path="../vite-env.d.ts" />
/**
 * Notification Service
 * Handles fetching, creating, and managing user notifications
 */

import { subscribe } from "@/services/realtimeManager.js";
import type { Platform } from "../src/types/platform.js";
import {
	type Notification,
	type NotificationPriority,
	NotificationType,
} from "../types.js";
import {
	createServiceLogger,
	dbQuery,
	getUserIdAsync,
	supabase,
} from "./api/shared.js";

const log = createServiceLogger("NotificationService");

// Maximum notifications to fetch at once
const MAX_NOTIFICATIONS = 50;

class NotificationService {
	private unsubscribeRealtime: (() => void) | null = null;

	// Check if user is authenticated
	private isAuthenticated(): boolean {
		const storageKey =
			"sb-" +
			import.meta.env.VITE_SUPABASE_URL?.split("//")[1]?.split(".")[0] +
			"-auth-token";
		return !!localStorage.getItem(storageKey);
	}

	// Get current user ID
	private async getCurrentUserId(): Promise<string | null> {
		try {
			return await getUserIdAsync();
		} catch {
			return null;
		}
	}

	/**
	 * Subscribe to real-time notifications
	 * Returns unsubscribe function
	 */
	subscribeToNotifications(
		callback: (notifications: Notification[]) => void,
		onError?: (error: Error) => void,
	): () => void {
		if (!this.isAuthenticated()) {
			log.warn("User not authenticated");
			return () => {};
		}

		const fetchNotifications = async (userId: string) => {
			const { data, error } = await supabase
				.from("notifications")
				.select("*")
				.eq("user_id", userId)
				.order("created_at", { ascending: false })
				.limit(MAX_NOTIFICATIONS);

			if (error) {
				log.error("Fetch error:", error);
				onError?.(error as unknown as Error);
				return;
			}

			// biome-ignore lint/suspicious/noExplicitAny: Supabase row shape not fully typed
			const raw: Notification[] = (data || []).map((row: any) => ({
				id: row.id,
				type: row.type as NotificationType,
				title: row.title,
				message: row.message,
				priority:
					// biome-ignore lint/suspicious/noExplicitAny: row.data is a JSONB blob
					((row.data as any)?.priority as NotificationPriority) || "medium",
				read: row.read,
				createdAt: new Date(row.created_at),
				metadata: row.data || {},
			}));
			// Dedup: Meta webhooks can fire twice, creating duplicate notifications.
			// Keep the first (newest) occurrence per type+identifier key.
			const seen = new Set<string>();
			const notifications = raw.filter((n) => {
				const m = n.metadata as Record<string, unknown> | undefined;
				const dedupId =
					m?.replyId ?? m?.commentId ?? m?.mediaId ?? m?.conversationId;
				if (!dedupId) return true;
				const key = `${n.type}:${dedupId}`;
				if (seen.has(key)) return false;
				seen.add(key);
				return true;
			});
			callback(notifications);
		};

		// Clean up any previous subscription
		this.unsubscribeRealtime?.();

		let resolvedUserId: string | null = null;

		// Stable singleton key — refcount works correctly across mount races
		// and the factory still gates on auth before opening the channel. The
		// previous `notifications:${Date.now()}` defeated dedup entirely.
		this.unsubscribeRealtime = subscribe(
			"notifications:stream",
			async (signal) => {
				try {
					const userId = await this.getCurrentUserId();
					if (signal.aborted || !userId) return null;
					resolvedUserId = userId;

					await fetchNotifications(userId);
					if (signal.aborted) return null;

					return supabase
						.channel(`notifications-${userId}`)
						.on(
							"postgres_changes",
							{
								event: "*",
								schema: "public",
								table: "notifications",
								filter: `user_id=eq.${userId}`,
							},
							() => {
								fetchNotifications(userId);
							},
						)
						.subscribe();
				} catch (err) {
					log.error("Failed to setup subscription:", err);
					onError?.(err instanceof Error ? err : new Error(String(err)));
					return null;
				}
			},
			() => {
				if (resolvedUserId) fetchNotifications(resolvedUserId);
			},
		);

		return () => {
			this.unsubscribeRealtime?.();
			this.unsubscribeRealtime = null;
		};
	}

	/**
	 * Get all notifications (one-time fetch)
	 */
	async getNotifications(): Promise<Notification[]> {
		if (!this.isAuthenticated()) {
			log.warn("User not authenticated");
			return [];
		}

		try {
			const userId = await this.getCurrentUserId();
			if (!userId) return [];

			const data = await dbQuery(
				supabase
					.from("notifications")
					.select("*")
					.eq("user_id", userId)
					.order("created_at", { ascending: false })
					.limit(MAX_NOTIFICATIONS),
				"[NotificationService] Failed to get notifications",
				// biome-ignore lint/suspicious/noExplicitAny: dbQuery fallback array type
				[] as any[],
			);

			// biome-ignore lint/suspicious/noExplicitAny: Supabase row shape not fully typed
			const raw = (data || []).map((row: any) => ({
				id: row.id,
				type: row.type as NotificationType,
				title: row.title,
				message: row.message,
				priority:
					// biome-ignore lint/suspicious/noExplicitAny: row.data is a JSONB blob
					((row.data as any)?.priority as NotificationPriority) || "medium",
				read: row.read,
				createdAt: new Date(row.created_at),
				metadata: row.data || {},
			}));
			const seen = new Set<string>();
			return raw.filter((n: Notification) => {
				const m = n.metadata as Record<string, unknown> | undefined;
				const dedupId =
					m?.replyId ?? m?.commentId ?? m?.mediaId ?? m?.conversationId;
				if (!dedupId) return true;
				const key = `${n.type}:${dedupId}`;
				if (seen.has(key)) return false;
				seen.add(key);
				return true;
			});
		} catch (error) {
			log.error("Failed to get notifications:", error);
			return [];
		}
	}

	/**
	 * Get unread notification count
	 */
	async getUnreadCount(): Promise<number> {
		if (!this.isAuthenticated()) return 0;

		try {
			const userId = await this.getCurrentUserId();
			if (!userId) return 0;

			const { count, error } = await supabase
				.from("notifications")
				.select("*", { count: "exact", head: true })
				.eq("user_id", userId)
				.eq("read", false);

			if (error) {
				log.error("Failed to get unread count:", error);
				return 0;
			}

			return count || 0;
		} catch (error) {
			log.error("Failed to get unread count:", error);
			return 0;
		}
	}

	/**
	 * Mark a notification as read
	 */
	async markAsRead(notificationId: string): Promise<boolean> {
		if (!this.isAuthenticated()) {
			log.warn("markAsRead: Not authenticated");
			return false;
		}

		try {
			const userId = await this.getCurrentUserId();
			if (!userId) {
				log.warn("markAsRead: No user ID");
				return false;
			}

			log.log("Marking as read:", notificationId, "for user:", userId);

			const { data, error } = await supabase
				.from("notifications")
				.update({ read: true })
				.eq("id", notificationId)
				.eq("user_id", userId)
				.select();

			if (error) {
				log.error("markAsRead error:", error);
				throw error;
			}

			log.log("markAsRead result:", data);
			return true;
		} catch (error) {
			log.error("Failed to mark as read:", error);
			throw error;
		}
	}

	/**
	 * Mark all notifications as read
	 */
	async markAllAsRead(): Promise<boolean> {
		if (!this.isAuthenticated()) {
			log.warn("markAllAsRead: Not authenticated");
			return false;
		}

		try {
			const userId = await this.getCurrentUserId();
			if (!userId) {
				log.warn("markAllAsRead: No user ID");
				return false;
			}

			log.log("Marking all as read for user:", userId);

			const { data, error } = await supabase
				.from("notifications")
				.update({ read: true })
				.eq("user_id", userId)
				.eq("read", false)
				.select();

			if (error) {
				log.error("markAllAsRead error:", error);
				throw error;
			}

			log.log("markAllAsRead updated:", data?.length || 0, "notifications");
			return true;
		} catch (error) {
			log.error("Failed to mark all as read:", error);
			throw error;
		}
	}

	/**
	 * Delete a notification
	 */
	async deleteNotification(notificationId: string): Promise<void> {
		if (!this.isAuthenticated()) return;

		try {
			const userId = await this.getCurrentUserId();
			if (!userId) return;

			const { error } = await supabase
				.from("notifications")
				.delete()
				.eq("id", notificationId)
				.eq("user_id", userId);

			if (error) throw error;
		} catch (error) {
			log.error("Failed to delete notification:", error);
			throw error;
		}
	}

	/**
	 * Clear all notifications
	 */
	async clearAll(): Promise<void> {
		if (!this.isAuthenticated()) return;

		try {
			const userId = await this.getCurrentUserId();
			if (!userId) return;

			const { error } = await supabase
				.from("notifications")
				.delete()
				.eq("user_id", userId);

			if (error) throw error;
		} catch (error) {
			log.error("Failed to clear all:", error);
			throw error;
		}
	}

	/**
	 * Create a notification (for local/testing use - normally Cloud Functions handle this)
	 */
	async createNotification(
		type: NotificationType,
		title: string,
		message: string,
		priority: NotificationPriority = "medium",
		metadata?: Notification["metadata"],
	): Promise<string | null> {
		if (!this.isAuthenticated()) return null;

		try {
			const userId = await this.getCurrentUserId();
			if (!userId) return null;

			const { data, error } = await supabase
				.from("notifications")
				.insert({
					user_id: userId,
					type,
					title,
					message,
					read: false,
					data: { ...(metadata || {}), priority },
				})
				.select()
				.maybeSingle();

			if (error) throw error;
			return data?.id || null;
		} catch (error) {
			log.error("Failed to create notification:", error);
			return null;
		}
	}

	/**
	 * Insert approval notifications for multiple approver users (batch insert)
	 */
	async notifyApprovers(
		notifications: Array<{
			user_id: string;
			type: string;
			title: string;
			message: string;
			data: Record<string, unknown>;
		}>,
	): Promise<void> {
		const { error } = await supabase
			.from("notifications")
			.insert(notifications.map((n) => ({ ...n, read: false })));
		if (error) throw error;
	}

	/**
	 * Cleanup subscription on logout
	 */
	cleanup(): void {
		this.unsubscribeRealtime?.();
		this.unsubscribeRealtime = null;
	}

	// ==================== NOTIFICATION HELPERS ====================

	/**
	 * Create a post published notification
	 */
	async notifyPostPublished(
		accountHandle: string,
		postId?: string,
	): Promise<void> {
		await this.createNotification(
			NotificationType.POST_PUBLISHED,
			"Post Published!",
			`Your post to @${accountHandle} was published successfully.`,
			"medium",
			{ postId, accountHandle },
		);
	}

	/**
	 * Create a post scheduled notification
	 */
	async notifyPostScheduled(
		accountHandle: string,
		scheduledDate: string,
		postId?: string,
	): Promise<void> {
		const date = new Date(scheduledDate);
		const dateStr = date.toLocaleDateString([], {
			month: "short",
			day: "numeric",
		});
		const timeStr = date.toLocaleTimeString([], {
			hour: "2-digit",
			minute: "2-digit",
		});

		await this.createNotification(
			NotificationType.POST_SCHEDULED,
			"Post Scheduled",
			`Your post to @${accountHandle} is scheduled for ${dateStr} at ${timeStr}.`,
			"low",
			{ postId, accountHandle, scheduledDate },
		);
	}

	/**
	 * Create a post failed notification
	 */
	async notifyPostFailed(
		accountHandle: string,
		errorMessage: string,
		postId?: string,
	): Promise<void> {
		await this.createNotification(
			NotificationType.POST_FAILED,
			"Post Failed",
			`Failed to publish to @${accountHandle}: ${errorMessage}`,
			"high",
			{ postId, accountHandle, error: errorMessage },
		);
	}

	/**
	 * Create an account connected notification
	 */
	async notifyAccountConnected(
		accountHandle: string,
		accountId?: string,
	): Promise<void> {
		await this.createNotification(
			NotificationType.ACCOUNT_CONNECTED,
			"Account Connected",
			`@${accountHandle} has been connected successfully.`,
			"medium",
			{ accountId, accountHandle },
		);
	}

	/**
	 * Create a follower milestone notification
	 */
	async notifyFollowerMilestone(
		accountHandle: string,
		milestone: number,
		accountId?: string,
	): Promise<void> {
		await this.createNotification(
			NotificationType.FOLLOWER_MILESTONE,
			`${milestone.toLocaleString()} Followers!`,
			`Congratulations! @${accountHandle} reached ${milestone.toLocaleString()} followers.`,
			"high",
			{ accountId, accountHandle, milestone },
		);
	}

	/**
	 * Create a goal milestone notification (25%, 50%, 75%, 100%)
	 */
	async notifyGoalMilestone(
		goalName: string,
		milestone: number,
		currentValue: number,
		targetValue: number,
		goalId?: string,
	): Promise<void> {
		const messages: Record<number, string> = {
			25: `You're 25% of the way to "${goalName}"! Keep going! 🎯`,
			50: `Halfway there! "${goalName}" is ${currentValue.toLocaleString()}/${targetValue.toLocaleString()} 🔥`,
			75: `So close! "${goalName}" is 75% complete! 💪`,
			100: `🎉 Goal complete! You hit "${goalName}" (${targetValue.toLocaleString()})! 🏆`,
		};

		const priority = milestone === 100 ? "high" : "medium";
		const type =
			milestone === 100
				? NotificationType.GOAL_COMPLETED
				: NotificationType.GOAL_MILESTONE;
		const title =
			milestone === 100 ? "Goal Completed!" : `${milestone}% Complete`;

		await this.createNotification(
			type,
			title,
			messages[milestone] || `Progress update on "${goalName}"`,
			priority,
			{ goalId, goalName, milestone, currentValue, targetValue },
		);
	}

	/**
	 * Create a goal at risk notification (behind pace)
	 */
	async notifyGoalAtRisk(
		goalName: string,
		targetValue: number,
		projectedValue: number,
		goalId?: string,
	): Promise<void> {
		const shortfall = targetValue - projectedValue;
		const percentBehind = Math.round((shortfall / targetValue) * 100);

		await this.createNotification(
			NotificationType.GOAL_AT_RISK,
			"Goal At Risk",
			`"${goalName}" is ${percentBehind}% behind pace. You need ${shortfall.toLocaleString()} more to reach your target.`,
			"medium",
			{ goalId, goalName, targetValue, projectedValue, shortfall },
		);
	}

	/**
	 * Create a team member joined notification
	 */
	async notifyTeamMemberJoined(
		memberName: string,
		memberId?: string,
	): Promise<void> {
		await this.createNotification(
			NotificationType.TEAM_MEMBER_JOINED,
			"New Team Member",
			`${memberName} has joined your workspace.`,
			"medium",
			{ teamMemberId: memberId, teamMemberName: memberName },
		);
	}

	/**
	 * Create a trend spike notification
	 * Triggered when a tracked keyword/hashtag is trending significantly above normal
	 */
	async notifyTrendSpike(
		keyword: string,
		spikeMultiplier: number,
		accountHandle?: string,
	): Promise<void> {
		const multiplierText =
			spikeMultiplier >= 10
				? `${Math.round(spikeMultiplier)}x`
				: `${spikeMultiplier.toFixed(1)}x`;

		await this.createNotification(
			NotificationType.TREND_SPIKE,
			`Trending: ${keyword}`,
			`${keyword} is spiking ${multiplierText} above normal! Perfect time to post about it.`,
			"high",
			{
				keyword,
				spikeMultiplier,
				accountHandle,
				trendType: "spike",
			},
		);
	}

	/**
	 * Create an engagement spike notification
	 */
	async notifyEngagementSpike(
		accountHandle: string,
		metric: string,
		currentValue: number,
		multiplier: number,
		postId?: string,
	): Promise<void> {
		await this.createNotification(
			NotificationType.ENGAGEMENT_SPIKE,
			"Engagement Spike!",
			`Your post is getting ${multiplier}x more ${metric} than usual on @${accountHandle}.`,
			"high",
			{ accountHandle, metric, currentValue, multiplier, postId },
		);
	}

	/**
	 * Notify when an access token is expiring soon.
	 */
	async notifyTokenExpiring(
		accountHandle: string,
		platform: Platform,
		daysUntilExpiry: number,
	): Promise<void> {
		await this.createNotification(
			NotificationType.TOKEN_EXPIRING,
			"Token Expiring Soon",
			`The ${platform} token for @${accountHandle} expires in ${daysUntilExpiry} day${daysUntilExpiry !== 1 ? "s" : ""}. Reconnect to refresh it.`,
			"high",
			{ accountHandle, platform, daysUntilExpiry },
		);
	}

	/**
	 * Notify when a competitor post goes viral (5x their average).
	 */
	async notifyCompetitorViral(
		competitorHandle: string,
		postPreview: string,
		engagementMultiplier: number,
	): Promise<void> {
		await this.createNotification(
			NotificationType.COMPETITOR_VIRAL,
			"Competitor Went Viral",
			`@${competitorHandle} has a post with ${engagementMultiplier.toFixed(1)}x their average engagement: "${postPreview.substring(0, 80)}..."`,
			"medium",
			{ competitorHandle, engagementMultiplier, postPreview },
		);
	}

	/**
	 * Notify when auto-poster queue is running low.
	 */
	async notifyQueueLow(
		remainingItems: number,
		workspaceName?: string,
	): Promise<void> {
		await this.createNotification(
			NotificationType.QUEUE_LOW,
			"Auto-Poster Queue Running Low",
			`Only ${remainingItems} item${remainingItems !== 1 ? "s" : ""} left in the queue${workspaceName ? ` for ${workspaceName}` : ""}. Add more content to keep posting on schedule.`,
			"medium",
			{ remainingItems, workspaceName },
		);
	}

	/**
	 * Notify when a weekly/monthly report is ready.
	 */
	async notifyReportReady(
		reportType: "weekly" | "monthly",
		period: string,
	): Promise<void> {
		await this.createNotification(
			NotificationType.REPORT_READY,
			`${reportType === "weekly" ? "Weekly" : "Monthly"} Report Ready`,
			`Your ${reportType} performance report for ${period} is ready. Check your email or download it from Analytics.`,
			"low",
			{ reportType, period },
		);
	}

	/**
	 * Create sample notifications for testing
	 */
	async createSampleNotifications(): Promise<void> {
		if (!this.isAuthenticated()) return;

		// Create a variety of sample notifications
		await this.createNotification(
			NotificationType.POST_PUBLISHED,
			"Post Published!",
			"Your thread about productivity tips was published successfully.",
			"medium",
			{ accountHandle: "testaccount" },
		);

		await this.createNotification(
			NotificationType.POST_SCHEDULED,
			"Post Scheduled",
			"Your post is scheduled for tomorrow at 9:00 AM.",
			"low",
			{ accountHandle: "mybrand" },
		);

		await this.createNotification(
			NotificationType.FOLLOWER_MILESTONE,
			"1,000 Followers!",
			"Congratulations! @mybrand reached 1,000 followers.",
			"high",
			{ accountHandle: "mybrand", milestone: 1000 },
		);

		await this.createNotification(
			NotificationType.ENGAGEMENT_SPIKE,
			"Engagement Spike!",
			"Your recent post is getting 3x more engagement than usual.",
			"medium",
			{ accountHandle: "mybrand" },
		);

		await this.createNotification(
			NotificationType.FEATURE_UPDATE,
			"New Feature Available",
			"Check out our new AI-powered content suggestions in the post editor.",
			"low",
		);
	}
}

export const notificationService = new NotificationService();
