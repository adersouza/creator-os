// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
/**
 * Threads Webhook Event Processors
 *
 * Handles all Threads-platform webhook events: replies, mentions, publish, delete.
 */

import type { PostgrestError, SupabaseClient } from "@supabase/supabase-js";
import { processAutoReplyRules } from "../../autoReplyEngine.js";
import { logger } from "../../logger.js";
import { calculateEngagementRate } from "../../metricCalculators.js";
import { getRedis } from "../../redis.js";
import type {
	AccountRow,
	PostRow,
	ThreadsMentionPayload,
	ThreadsPublishPayload,
	ThreadsReplyPayload,
	ThreadsWebhookEvent,
} from "./types.js";
import { getAccountToken, parseWebhookTimestamp } from "./utils.js";

/**
 * Refresh Threads post metrics from API when a webhook event arrives.
 * Uses Redis debounce so multiple events for the same post within 60s
 * only trigger one API call.
 */
export async function refreshThreadsPostMetricsFromWebhook(
	supabase: SupabaseClient,
	threadsPostId: string,
	accountId: string,
): Promise<void> {
	try {
		const redis = getRedis();
		const debounceKey = `threads-metric-refresh:${threadsPostId}`;
		const wasSet = await redis.set(debounceKey, "1", { nx: true, ex: 60 });
		if (wasSet !== "OK") {
			logger.debug("Skipping Threads metric refresh (debounced)", {
				threadsPostId,
			});
			return;
		}
	} catch {
		// Redis unavailable — proceed with refresh anyway
	}

	const encryptedToken = await getAccountToken(supabase, accountId);
	if (!encryptedToken) {
		logger.debug("No Threads token for metric refresh", { accountId });
		return;
	}

	const { getPostMetrics } = await import("../../threadsApi.js");
	const result = await getPostMetrics(encryptedToken, threadsPostId);

	if (!result.success || !result.metrics) {
		logger.debug("Threads metric refresh returned no data", {
			threadsPostId,
			error: result.error,
		});
		return;
	}

	const m = result.metrics;
	const views = m.views || 0;
	const engagementRate = calculateEngagementRate(
		{
			views,
			likes: m.likes || 0,
			replies: m.replies || 0,
			reposts: m.reposts || 0,
			quotes: m.quotes || 0,
			shares: m.shares || 0,
		},
		"threads",
	);

	// Column mapping matches accountSync.ts:614-624
	// Monotonic guard: only overwrite if our total engagement >= existing (prevents
	// stale cron data from overwriting fresher webhook data or vice-versa).
	const totalEngagement =
		(m.views || 0) + (m.likes || 0) + (m.replies || 0) + (m.reposts || 0);
	await supabase.rpc("update_post_metrics_if_newer", {
		p_threads_post_id: threadsPostId,
		p_views_count: m.views || 0,
		p_likes_count: m.likes || 0,
		p_replies_count: m.replies || 0,
		p_reposts_count: m.reposts || 0,
		p_quotes_count: m.quotes || 0,
		p_shares_count: m.shares || 0,
		p_engagement_rate: engagementRate,
		p_total_engagement: totalEngagement,
	});

	logger.info("Refreshed Threads post metrics from webhook", {
		threadsPostId,
		views: m.views,
		likes: m.likes,
	});
}

async function processThreadsReplyEvent(
	supabase: SupabaseClient,
	event: ThreadsWebhookEvent,
) {
	const payload = event.payload;
	if (!payload || typeof payload !== "object") {
		logger.warn("Threads reply event has invalid payload, skipping", {
			eventId: event.id,
		});
		return;
	}

	const p = payload as ThreadsReplyPayload;
	const replyId = p.id;
	const text = p.text;
	const timestamp = p.timestamp;
	// Per Threads webhook docs, username/profile_picture_url are top-level fields (not nested in `from`)
	const authorId = p.from?.id || null;
	const authorUsername = p.username || p.from?.username || null;
	const repliedToId = p.replied_to?.id || null;
	const profilePictureUrl =
		p.profile_picture_url || p.from?.profile_picture_url || null;

	if (!replyId) {
		logger.warn("Threads reply event missing replyId, skipping", {
			eventId: event.id,
		});
		return;
	}

	// For reply events, event.threads_user_id may contain a media ID (from target_id/entry.id)
	// rather than the actual Threads user ID. Use root_post.owner_id from payload as primary lookup.
	const rootOwnerIdFromPayload = p.root_post?.owner_id;
	const lookupId = rootOwnerIdFromPayload || event.threads_user_id;

	const { data: account } = (await supabase
		.from("accounts")
		.select("id, user_id")
		.eq("threads_user_id", lookupId)
		.maybeSingle()) as {
		data: AccountRow | null;
		error: PostgrestError | null;
	};

	if (!account) {
		logger.warn(
			"No account found for threads_user_id, marking as dead letter",
			{
				threadsUserId: lookupId,
				eventThreadsUserId: event.threads_user_id,
				rootOwnerId: rootOwnerIdFromPayload,
				eventId: event.id,
			},
		);
		await supabase
			.from("threads_webhook_events")
			.update({
				processed: true,
				processed_at: new Date().toISOString(),
				dead_letter: true,
				dead_letter_at: new Date().toISOString(),
				dead_letter_reason: "Account not found or deleted",
			})
			.eq("id", event.id);
		return;
	}

	let postId: string | null = null;
	// Try replied_to.id first, then fall back to root_post.id
	const repliedToLookupId = repliedToId || p.root_post?.id || null;
	if (repliedToLookupId) {
		const { data: post } = (await supabase
			.from("posts")
			.select("id")
			.eq("threads_post_id", repliedToLookupId)
			.maybeSingle()) as { data: PostRow | null; error: PostgrestError | null };

		if (post) {
			postId = post.id;
		}
	}

	// post_id is NOT NULL — skip reply if we can't find the parent post (reply to untracked content)
	if (!postId) {
		logger.info("Skipping reply — parent post not found in DB", {
			replyId,
			repliedToId: repliedToLookupId,
			rootPostId: p.root_post?.id,
		});
		return;
	}

	// threads_user_id is NOT NULL — webhook payloads often omit from.id,
	// fall back to event.threads_user_id (media ID) or reply ID as last resort
	const replyAuthorId = authorId || event.threads_user_id || replyId;

	const { error: upsertError } = await supabase.from("post_replies").upsert(
		{
			threads_reply_id: replyId,
			post_id: postId,
			threads_user_id: replyAuthorId,
			username: authorUsername || "unknown",
			avatar_url: profilePictureUrl || null,
			content: text || "",
			created_at: timestamp
				? parseWebhookTimestamp(timestamp as string | number)
				: new Date().toISOString(),
			is_read: false,
			synced_at: new Date().toISOString(),
		},
		{ onConflict: "threads_reply_id" },
	);

	if (upsertError) {
		logger.error("Failed to upsert reply", {
			replyId,
			error: upsertError.message,
		});
		return;
	}

	// Mark account as receiving replies via webhook (skip polling in sync-worker)
	await supabase
		.from("accounts")
		.update({
			webhook_replies_active: true,
			last_webhook_reply_at: new Date().toISOString(),
		})
		.eq("id", account.id);

	if (postId) {
		const { count } = await supabase
			.from("post_replies")
			.select("*", { count: "exact", head: true })
			.eq("post_id", postId);

		if (count !== null) {
			await supabase
				.from("posts")
				.update({ replies_count: count })
				.eq("id", postId);
		}
	}

	// Notify user about new reply — dedup on notification table to prevent TOCTOU race
	// when Meta sends duplicate webhooks in quick succession
	if (account?.user_id) {
		const { count: existingNotifCount } = await supabase
			.from("notifications")
			.select("*", { count: "exact", head: true })
			.eq("user_id", account.user_id)
			.eq("type", "reply_received")
			.filter("data->>replyId", "eq", String(replyId));

		if (!existingNotifCount) {
			const { createNotification } = await import(
				"../../createNotification.js"
			);
			await createNotification({
				userId: account.user_id,
				type: "reply_received",
				title: "New reply on Threads",
				message: authorUsername
					? `@${authorUsername}: ${(text || "").slice(0, 100)}`
					: "New reply on your post",
				data: { replyId, postId, authorUsername },
			});
		}
	}

	logger.info("Stored Threads reply", { replyId, authorUsername });

	// Process auto-reply rules for incoming replies
	// Use replyAuthorId (line 478 fallback) since Meta often omits from.id
	if (account && replyId && replyAuthorId) {
		await processAutoReplyRules(supabase, {
			accountId: account.id,
			threadsUserId: event.threads_user_id,
			encryptedAccessToken: await getAccountToken(supabase, account.id),
			eventType: "replies",
			text: (text as string) || "",
			replyToId: replyId as string,
			authorId: replyAuthorId as string,
			authorUsername: authorUsername || "unknown",
		});
	}

	// Trigger a live metric refresh for the parent post that received a reply
	if (repliedToId && account) {
		await refreshThreadsPostMetricsFromWebhook(
			supabase,
			repliedToId,
			account.id,
		);
	}
}

async function processThreadsMentionEvent(
	supabase: SupabaseClient,
	event: ThreadsWebhookEvent,
) {
	const payload = event.payload;
	if (!payload || typeof payload !== "object") {
		logger.warn("Threads mention event has invalid payload, skipping", {
			eventId: event.id,
		});
		return;
	}

	const p = payload as ThreadsMentionPayload;
	const postId = p.id;
	const text = p.text;
	const timestamp = p.timestamp;
	// Per Threads webhook docs, username/profile_picture_url are top-level fields (not nested in `from`)
	const mentioningUsername = p.username || p.from?.username || null;
	const permalink = p.permalink;
	const profilePictureUrl =
		p.profile_picture_url || p.from?.profile_picture_url || null;

	if (!postId) {
		logger.warn("Threads mention event missing postId, skipping", {
			eventId: event.id,
		});
		return;
	}

	const { data: account } = (await supabase
		.from("accounts")
		.select("id, user_id")
		.eq("threads_user_id", event.threads_user_id)
		.maybeSingle()) as {
		data: AccountRow | null;
		error: PostgrestError | null;
	};

	if (!account) {
		logger.warn(
			"No account found for threads_user_id, marking as dead letter",
			{ threadsUserId: event.threads_user_id, eventId: event.id },
		);
		await supabase
			.from("threads_webhook_events")
			.update({
				processed: true,
				processed_at: new Date().toISOString(),
				dead_letter: true,
				dead_letter_at: new Date().toISOString(),
				dead_letter_reason: "Account not found or deleted",
			})
			.eq("id", event.id);
		return;
	}

	const { error: upsertError } = await supabase.from("mentions").upsert(
		{
			threads_post_id: postId,
			account_id: account.id,
			user_id: account.user_id,
			mentioned_by_username: mentioningUsername || "unknown",
			mentioned_by_avatar: profilePictureUrl || null,
			content: text || "",
			permalink: permalink,
			mentioned_at: timestamp
				? parseWebhookTimestamp(timestamp as string | number)
				: new Date().toISOString(),
			is_read: false,
		},
		{ onConflict: "threads_post_id" },
	);

	if (upsertError) {
		logger.error("Failed to upsert mention", {
			postId,
			error: upsertError.message,
		});
		return;
	}

	// Notify user about mention
	if (account?.user_id) {
		const { createNotification } = await import("../../createNotification.js");
		await createNotification({
			userId: account.user_id,
			type: "mention_received",
			title: "You were mentioned on Threads",
			message: mentioningUsername
				? `@${mentioningUsername} mentioned you: ${(text || "").slice(0, 100)}`
				: "Someone mentioned you",
			data: { postId, mentioningUsername, permalink },
		});
	}

	logger.info("Stored Threads mention", { mentioningUsername });

	// Process auto-reply rules for mentions
	if (account && postId) {
		const mentioningUserId = p.from?.id || p.id;
		if (mentioningUserId) {
			await processAutoReplyRules(supabase, {
				accountId: account.id,
				threadsUserId: event.threads_user_id,
				encryptedAccessToken: await getAccountToken(supabase, account.id),
				eventType: "mentions",
				text: (text as string) || "",
				replyToId: postId as string,
				authorId: mentioningUserId as string,
				authorUsername: mentioningUsername || "unknown",
			});
		}
	}
}

async function processThreadsPublishEvent(
	supabase: SupabaseClient,
	event: ThreadsWebhookEvent,
) {
	const payload = event.payload;
	if (!payload || typeof payload !== "object") {
		logger.warn("Threads publish event has invalid payload, skipping", {
			eventId: event.id,
		});
		return;
	}

	const p = payload as ThreadsPublishPayload;
	const postId = p.id;
	const text = p.text;
	const timestamp = p.timestamp;
	const mediaType = p.media_type;
	const mediaUrl = p.media_url;
	const permalink = p.permalink;

	if (!postId) {
		logger.warn("Threads publish event missing postId, skipping", {
			eventId: event.id,
		});
		return;
	}

	const { data: account } = (await supabase
		.from("accounts")
		.select("id, user_id")
		.eq("threads_user_id", event.threads_user_id)
		.maybeSingle()) as {
		data: AccountRow | null;
		error: PostgrestError | null;
	};

	if (!account) {
		logger.warn(
			"No account found for threads_user_id, marking as dead letter",
			{ threadsUserId: event.threads_user_id, eventId: event.id },
		);
		await supabase
			.from("threads_webhook_events")
			.update({
				processed: true,
				processed_at: new Date().toISOString(),
				dead_letter: true,
				dead_letter_at: new Date().toISOString(),
				dead_letter_reason: "Account not found or deleted",
			})
			.eq("id", event.id);
		return;
	}

	const { data: existingPost } = await supabase
		.from("posts")
		.select("id")
		.eq("threads_post_id", postId)
		.maybeSingle();

	if (existingPost) {
		logger.info("Threads post already exists, skipping", { postId });
		return;
	}

	// If webhook has no text, the auto-poster/scheduler will insert the post record
	// with full content. Inserting here with empty content creates a "No content" bug.
	if (!text) {
		logger.info(
			"Threads publish webhook has no text — deferring to publisher insert",
			{
				postId,
				accountId: account.id,
			},
		);
		return;
	}

	const { error: insertError } = await supabase.from("posts").insert({
		threads_post_id: postId,
		account_id: account.id,
		user_id: account.user_id,
		content: text,
		media_type: mediaType?.toLowerCase() || "text",
		media_urls: mediaUrl ? [mediaUrl] : [],
		permalink: permalink,
		status: "published",
		published_at: timestamp
			? parseWebhookTimestamp(timestamp as string | number)
			: new Date().toISOString(),
		source: "external",
		platform: "threads",
	});

	if (insertError) {
		logger.error("Failed to insert Threads post", {
			postId,
			error: insertError.message,
		});
		throw insertError;
	}

	logger.info("Synced external Threads post", { postId });

	// Fetch initial metrics for the newly synced post
	await refreshThreadsPostMetricsFromWebhook(
		supabase,
		postId as string,
		account.id,
	);

	// Update account_analytics post count for today
	const today = new Date().toISOString().split("T")[0]!;
	const { data: existingAnalytics } = await supabase
		.from("account_analytics")
		.select("id, post_count")
		.eq("account_id", account.id)
		.eq("date", today)
		.maybeSingle();

	if (existingAnalytics) {
		await supabase
			.from("account_analytics")
			.update({
				post_count: (existingAnalytics.post_count || 0) + 1,
				updated_at: new Date().toISOString(),
			})
			.eq("id", existingAnalytics.id);
	} else {
		const { data: latestRow } = await supabase
			.from("account_analytics")
			.select("followers_count")
			.eq("account_id", account.id)
			.order("date", { ascending: false })
			.limit(1)
			.maybeSingle();

		await supabase.from("account_analytics").insert({
			account_id: account.id,
			user_id: account.user_id,
			date: today,
			post_count: 1,
			followers_count: latestRow?.followers_count || 0,
			platform: "threads",
		});
	}

	// Invalidate Redis-cached dashboard data
	const { invalidateDashboard } = await import("../../dashboardCache.js");
	await invalidateDashboard(account.id);
}

async function processThreadsDeleteEvent(
	supabase: SupabaseClient,
	event: ThreadsWebhookEvent,
) {
	const payload = event.payload;
	if (!payload || typeof payload !== "object") {
		logger.warn("Threads delete event has invalid payload, skipping", {
			eventId: event.id,
		});
		return;
	}

	const postId = payload.id;
	if (!postId) {
		logger.warn("Threads delete event missing postId, skipping", {
			eventId: event.id,
		});
		return;
	}

	const { data: post, error: updateError } = await supabase
		.from("posts")
		.update({ status: "deleted", updated_at: new Date().toISOString() })
		.eq("threads_post_id", postId)
		.select("id, account_id")
		.maybeSingle();

	if (updateError) {
		logger.error("Failed to mark post as deleted", {
			threadsPostId: postId,
			error: updateError.message,
		});
		return;
	}

	if (!post) {
		logger.info("Threads delete event — no matching post found", {
			threadsPostId: postId,
			threadsUserId: event.threads_user_id,
		});
		return;
	}

	logger.info("Marked Threads post as deleted via webhook", {
		threadsPostId: postId,
		internalPostId: post.id,
		threadsUserId: event.threads_user_id,
	});

	// Decrement today's account_analytics post count (floor at 0)
	const today = new Date().toISOString().split("T")[0]!;
	const { data: todayAnalytics } = await supabase
		.from("account_analytics")
		.select("id, post_count")
		.eq("account_id", post.account_id)
		.eq("date", today)
		.maybeSingle();

	if (todayAnalytics && (todayAnalytics.post_count || 0) > 0) {
		await supabase
			.from("account_analytics")
			.update({
				post_count: todayAnalytics.post_count - 1,
				updated_at: new Date().toISOString(),
			})
			.eq("id", todayAnalytics.id);
	}
}

export async function handleThreadsWebhookEvent(
	supabase: SupabaseClient,
	event: ThreadsWebhookEvent,
): Promise<void> {
	switch (event.event_type) {
		case "replies":
			await processThreadsReplyEvent(supabase, event);
			break;
		case "mentions":
			await processThreadsMentionEvent(supabase, event);
			break;
		case "publish":
			await processThreadsPublishEvent(supabase, event);
			break;
		case "delete":
			await processThreadsDeleteEvent(supabase, event);
			break;
		default:
			logger.warn("Unknown Threads event type", {
				eventType: event.event_type,
				threadsUserId: event.threads_user_id,
			});
			break;
	}
}
