// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
/**
 * Instagram webhook event processors.
 * Handles comments, live_comments, mentions, story_insights, messaging (DMs),
 * messaging_seen, message_reactions, message_edit, and follow events.
 */

import type { PostgrestError, SupabaseClient } from "@supabase/supabase-js";
import { logger, serializeError } from "../../logger.js";
import { getRedis } from "../../redis.js";
import { getSupabaseAny } from "../../supabase.js";
import type {
	IgAccountRow,
	IgAttachment,
	IgCommentPayload,
	IgMentionPayload,
	IgMessageReactionPayload,
	IgMessagingPayload,
	IgMessagingSeenPayload,
	IgWebhookEvent,
	PostOwnerRow,
	PostRow,
} from "./shared.js";

/**
 * Refresh post metrics from Meta API when a webhook event arrives.
 * Uses Redis debounce so multiple events for the same post within 60s
 * only trigger one API call.
 */
async function refreshIgPostMetricsFromWebhook(
	supabase: SupabaseClient,
	mediaId: string,
	igUserId: string,
): Promise<void> {
	try {
		// Redis debounce — skip if we already refreshed this post recently
		const redis = getRedis();
		const debounceKey = `ig-metric-refresh:${mediaId}`;
		const wasSet = await redis.set(debounceKey, "1", { nx: true, ex: 60 });
		if (wasSet !== "OK") {
			logger.debug("Skipping IG metric refresh (debounced)", { mediaId });
			return;
		}
	} catch {
		// Redis unavailable — proceed with refresh anyway
	}

	// Look up IG account credentials
	const { data: igAccount } = (await supabase
		.from("instagram_accounts")
		.select("id, instagram_access_token_encrypted, login_type")
		.eq("instagram_user_id", igUserId)
		.maybeSingle()) as {
		data: IgAccountRow | null;
		error: PostgrestError | null;
	};

	if (!igAccount?.instagram_access_token_encrypted) {
		logger.debug("No IG token for metric refresh", { igUserId });
		return;
	}

	// Look up post row to get media_type for Reel-specific metrics
	const { data: post } = (await supabase
		.from("posts")
		.select("id, media_type, ig_media_type, content_surface")
		.eq("instagram_post_id", mediaId)
		.maybeSingle()) as {
		data:
			| (PostRow & {
					media_type?: string | undefined;
					ig_media_type?: string | undefined;
					content_surface?: string | undefined;
			  })
			| null;
		error: PostgrestError | null;
	};

	const { getInstagramPostMetrics } = await import("../../instagramApi.js");
	const result = await getInstagramPostMetrics(
		igAccount.instagram_access_token_encrypted,
		mediaId,
		igAccount.login_type,
		post?.ig_media_type || post?.media_type,
		post?.content_surface,
	);

	if (!result.success || !result.metrics) {
		logger.debug("IG metric refresh returned no data", {
			mediaId,
			error: result.error,
		});
		return;
	}

	const m = result.metrics;

	if (!post) {
		logger.debug("No post row for metric refresh", { mediaId });
		return;
	}

	// Column mapping matches api/posts.ts:574-585
	// Monotonic guard: only overwrite if total engagement >= existing
	const igTotalEngagement =
		(m.impressions || 0) + (m.likes || 0) + (m.comments || 0) + (m.saved || 0);
	await supabase.rpc("update_ig_post_metrics_if_newer", {
		p_post_id: post.id,
		p_ig_impressions: m.impressions || 0,
		p_ig_reach: m.reach || 0,
		p_ig_saved: m.saved || 0,
		p_ig_shares: m.shares || 0,
		p_likes_count: m.likes || 0,
		p_replies_count: m.comments || 0,
		p_ig_plays: m.plays || 0,
		p_ig_video_views: m.video_views || 0,
		p_engagement_rate: m.engagementRate || 0,
		p_total_engagement: igTotalEngagement,
		p_ig_reels_avg_watch_time: m.ig_reels_avg_watch_time || 0,
		p_ig_crossposted_views: m.crossposted_views || 0,
		p_ig_facebook_views: m.facebook_views || 0,
		p_ig_reels_video_view_total_time: m.ig_reels_video_view_total_time || 0,
		p_ig_clips_replays_count: m.clips_replays_count || 0,
		p_ig_reels_aggregated_all_plays_count:
			m.ig_reels_aggregated_all_plays_count || 0,
	});

	logger.info("Refreshed IG post metrics from webhook", {
		mediaId,
		postId: post.id,
		reach: m.reach,
		likes: m.likes,
	});
}

async function processIgCommentEvent(
	supabase: SupabaseClient,
	event: IgWebhookEvent,
) {
	const payload = event.payload;
	if (!payload || typeof payload !== "object") {
		logger.warn("IG comment event has invalid payload, skipping", {
			eventId: event.id,
		});
		return;
	}
	const p = payload as IgCommentPayload;
	const commentId = p.id || p.comment_id;
	const mediaId = p.media_id || p.media?.id;
	const text = p.text;
	const username = p.from?.username || p.username;
	const timestamp = p.created_time || event.received_at;

	if (!commentId || !mediaId) {
		logger.warn("IG comment event missing commentId or mediaId, skipping");
		return;
	}

	const { data: post } = (await supabase
		.from("posts")
		.select("id, account_id")
		.eq("instagram_post_id", mediaId)
		.maybeSingle()) as { data: PostRow | null; error: PostgrestError | null };

	if (!post) {
		logger.warn("No matching post found for IG media", { mediaId });
		return;
	}

	const dbAny = getSupabaseAny();
	const { error: upsertError } = await dbAny.from("ig_comments").upsert(
		{
			comment_id: commentId,
			post_id: post.id,
			media_id: mediaId,
			text: text || "",
			username: username || "unknown",
			ig_user_id: event.ig_user_id,
			created_at: timestamp,
			// Enrich with additional fields if available in webhook payload
			// biome-ignore lint/suspicious/noExplicitAny: webhook payload has dynamic shape
			like_count: (p as any).like_count ?? 0,
			// biome-ignore lint/suspicious/noExplicitAny: webhook payload has dynamic shape
			parent_comment_id: (p as any).parent_id || null,
		},
		{ onConflict: "comment_id" },
	);

	if (upsertError) {
		logger.error("Failed to upsert IG comment", {
			commentId,
			error: upsertError.message,
		});
		return;
	}

	const { count } = await supabase
		.from("ig_comments")
		.select("*", { count: "exact", head: true })
		.eq("post_id", post.id);

	if (count !== null) {
		await supabase
			.from("posts")
			.update({ ig_comment_count: count })
			.eq("id", post.id);
	}

	// Get user_id for notification
	const { data: postOwner } = (await supabase
		.from("posts")
		.select("user_id")
		.eq("id", post.id)
		.maybeSingle()) as {
		data: PostOwnerRow | null;
		error: PostgrestError | null;
	};

	if (postOwner?.user_id) {
		const { createNotification } = await import("../../createNotification.js");
		await createNotification({
			userId: postOwner.user_id,
			type: "comment_received",
			title: "New comment on Instagram",
			message: username
				? `@${username} commented: ${(text || "").slice(0, 100)}`
				: "New comment on your post",
			data: { commentId, mediaId, postId: post.id },
		});
	}

	logger.info("Stored IG comment", { commentId, postId: post.id });

	// Track comment sentiment for post-level aggregation (fire-and-forget)
	if (post.id && text) {
		const { trackCommentSentiment } = await import("../../sentimentTracker.js");
		trackCommentSentiment(post.id, text as string).catch(() => {});
	}

	// ── Comment-to-DM funnel: send snap username via private reply ──
	// Fail-safe: errors never block webhook processing
	try {
		const { data: igAcct } = (await supabase
			.from("instagram_accounts")
			.select(
				"id, user_id, instagram_user_id, instagram_access_token_encrypted, login_type, username",
			)
			.eq("instagram_user_id", event.ig_user_id)
			.maybeSingle()) as {
			data: (IgAccountRow & { username?: string | undefined }) | null;
			error: PostgrestError | null;
		};

		if (igAcct?.instagram_access_token_encrypted && commentId && username) {
			const { processCommentForDm, resolveDmConfig } = await import(
				"../../commentToDm.js"
			);
			const dmConfig = await resolveDmConfig(event.ig_user_id, igAcct.user_id);
			if (dmConfig?.snapUsername) {
				// Fire and don't await — speed matters for <1min response, but
				// we still want to log failures. Use .catch() to keep it non-blocking
				// within the webhook processor's error budget.
				processCommentForDm(
					igAcct.instagram_user_id,
					commentId,
					username,
					igAcct.instagram_access_token_encrypted,
					dmConfig.snapUsername,
					igAcct.login_type,
					igAcct.username,
					text,
					dmConfig.dmTriggerKeywords,
				).catch((err: unknown) => {
					logger.warn("[comment-to-dm] Fire-and-forget failed", {
						commentId,
						error: err instanceof Error ? err.message : String(err),
					});
				});
			}
		}
	} catch (dmErr: unknown) {
		logger.warn("[comment-to-dm] Setup error (non-blocking)", {
			commentId,
			error: dmErr instanceof Error ? dmErr.message : String(dmErr),
		});
	}

	// Trigger a live metric refresh for this post
	await refreshIgPostMetricsFromWebhook(supabase, mediaId, event.ig_user_id);
}

async function processIgMentionEvent(
	supabase: SupabaseClient,
	event: IgWebhookEvent,
) {
	const payload = event.payload;
	if (!payload || typeof payload !== "object") {
		logger.warn("IG mention event has invalid payload, skipping", {
			eventId: event.id,
		});
		return;
	}
	const p = payload as IgMentionPayload;
	const mediaId = p.media_id || p.media?.id || p.id;
	const senderId = p.from?.id;
	const username = p.from?.username || p.username;
	const caption = p.caption || p.text;
	const permalink = p.permalink;
	const mediaType = p.media_type;
	const timestamp = p.timestamp || event.received_at;

	if (!mediaId) {
		logger.warn("IG mention event missing mediaId, skipping");
		return;
	}

	const { data: igAccount } = (await supabase
		.from("instagram_accounts")
		.select(
			"id, user_id, instagram_user_id, instagram_access_token_encrypted, login_type",
		)
		.eq("instagram_user_id", event.ig_user_id)
		.maybeSingle()) as {
		data: IgAccountRow | null;
		error: PostgrestError | null;
	};

	if (!igAccount) {
		// Unregistered account — app-level webhook sends events for all authorized
		// accounts, including ones never added to the platform. Skip silently.
		logger.info("IG event from unregistered account, skipping", {
			igUserId: event.ig_user_id,
			eventId: event.id,
		});
		return;
	}

	const { error: insertError } = await supabase.from("ig_mentions").upsert(
		{
			media_id: mediaId,
			ig_account_id: igAccount.id,
			user_id: igAccount.user_id,
			ig_user_id: event.ig_user_id,
			username: username || "unknown",
			caption: caption || "",
			permalink: permalink || null,
			media_type: mediaType || null,
			mentioned_at: timestamp,
		},
		{ onConflict: "media_id" },
	);

	if (insertError) {
		logger.error("Failed to store IG mention", {
			mediaId,
			error: insertError.message,
		});
		return;
	}

	// Notify user about IG mention
	if (igAccount?.user_id) {
		const { createNotification } = await import("../../createNotification.js");
		await createNotification({
			userId: igAccount.user_id,
			type: "mention_received",
			title: "You were mentioned on Instagram",
			message: username
				? `@${username} mentioned you`
				: "Someone mentioned you on Instagram",
			data: { mediaId, username, permalink },
		});
	}

	logger.info("Stored IG mention", { mediaId, accountId: igAccount.id });

	if (senderId && igAccount.instagram_access_token_encrypted) {
		const { data: responders } = await supabase
			.from("ig_auto_responders")
			.select("*")
			.eq("ig_account_id", igAccount.id)
			.eq("is_enabled", true)
			.eq("trigger_type", "mention");
		const responder = responders?.[0] as
			| {
					id: string;
					template_id?: string | null;
					custom_response?: string | null;
					delay_seconds?: number | null;
					use_ai_response?: boolean | null;
					ai_response_intent?: string | null;
					ai_system_prompt?: string | null;
			  }
			| undefined;
		if (responder) {
			const delayMs = (responder.delay_seconds || 2) * 1000;
			if (delayMs > 0) {
				await new Promise((resolve) =>
					setTimeout(resolve, Math.min(delayMs, 10000)),
				);
			}

			let responseText: string | null = null;
			if (responder.use_ai_response) {
				const { generateDMResponse } = await import(
					"../../../../services/aiService.js"
				);
				const responseIntent =
					responder.ai_response_intent === "redirect_to_link" ||
					responder.ai_response_intent === "polite_decline" ||
					responder.ai_response_intent === "flirty_tease"
						? responder.ai_response_intent
						: "engage";
				const result = await generateDMResponse(
					(caption || "Instagram mention").substring(0, 1000),
					[],
					responseIntent,
					undefined,
					responder.ai_system_prompt || undefined,
				);
				responseText = result.response;
			}
			if (!responseText && responder.template_id) {
				const { data: template } = await supabase
					.from("ig_dm_templates")
					.select("content")
					.eq("id", responder.template_id)
					.maybeSingle();
				responseText = template?.content || null;
			}
			responseText = responseText || responder.custom_response || null;
			if (responseText) {
				const { sendMessage } = await import("../../instagramApi.js");
				const sendResult = await sendMessage(
					igAccount.instagram_access_token_encrypted,
					igAccount.instagram_user_id,
					senderId,
					responseText.replace(/\{\{username\}\}/gi, username || "there"),
					igAccount.login_type || "",
				);
				if (!sendResult.success) {
					logger.error("Failed to send mention auto-responder DM", {
						error: sendResult.error,
						responderId: responder.id,
					});
				} else {
					logger.info("Sent mention auto-responder DM", {
						mediaId,
						responderId: responder.id,
					});
				}
			}
		}
	}

	// Trigger a live metric refresh for the mentioned post
	await refreshIgPostMetricsFromWebhook(supabase, mediaId, event.ig_user_id);
}

async function processIgStoryInsightsEvent(
	supabase: SupabaseClient,
	event: IgWebhookEvent,
) {
	const payload = event.payload;
	if (!payload || typeof payload !== "object") {
		logger.warn("IG story insights event has invalid payload, skipping", {
			eventId: event.id,
		});
		return;
	}
	const mediaId = payload.media_id || payload.id;
	// Read both old and new field names (Meta transition period)
	const views = payload?.views ?? payload?.impressions ?? 0;
	const impressions = payload?.impressions ?? payload?.views ?? 0;
	const reach = payload?.reach ?? 0;
	const replies = payload?.replies ?? 0;
	const navigation = payload?.navigation ?? null;
	const tapsForward = payload?.taps_forward ?? 0;
	const tapsBack = payload?.taps_back ?? 0;
	const exits = payload?.exits ?? 0;
	const follows = payload?.follows ?? 0;
	const shares = payload?.shares ?? 0;
	const totalInteractions = payload?.total_interactions ?? 0;

	if (!mediaId) {
		logger.warn("IG story insights event missing mediaId, skipping");
		return;
	}

	const { error: upsertError } = await supabase
		.from("ig_story_insights")
		.upsert(
			{
				media_id: mediaId,
				ig_user_id: event.ig_user_id,
				impressions,
				views,
				reach,
				replies,
				navigation,
				taps_forward: tapsForward,
				taps_back: tapsBack,
				exits,
				follows,
				shares,
				total_interactions: totalInteractions,
				recorded_at: new Date().toISOString(),
			},
			{ onConflict: "media_id" },
		);

	if (upsertError) {
		logger.error("Failed to store IG story insights", {
			mediaId,
			error: upsertError.message,
		});
		return;
	}

	logger.info("Stored IG story insights", { mediaId });
}

async function processIgMessagingEvent(
	supabase: SupabaseClient,
	event: IgWebhookEvent,
) {
	const payload = event.payload;
	if (!payload || typeof payload !== "object") {
		logger.warn("IG messaging event has invalid payload, skipping", {
			eventId: event.id,
		});
		return;
	}
	const p = payload as IgMessagingPayload;
	const senderId = p.sender?.id || p.from?.id;
	const messageText = p.message?.text || p.text;
	const conversationId = p.thread_id || p.conversation_id || senderId;

	// Handle attachments (ig_post shares, images, etc.)
	// Note: `share` and `media_share` types are deprecated as of Feb 2026; `ig_post` is the canonical type
	const attachments = p.message?.attachments || [];
	const igPostAttachment = (attachments as IgAttachment[]).find(
		(a) => a.type === "ig_post",
	);
	const hasStoryReplySignal = (attachments as IgAttachment[]).some((a) =>
		a.type.toLowerCase().includes("story"),
	);
	const attachmentUrl = igPostAttachment?.payload?.url || null;

	// Need either text or an attachment to process
	// Read receipts, typing indicators, and reactions have no text/attachment — expected, not a warning
	if (
		!senderId ||
		(!messageText && !igPostAttachment && !hasStoryReplySignal)
	) {
		logger.debug("IG messaging event has no actionable content, skipping", {
			eventId: event.id,
			hasSender: !!senderId,
			hasText: !!messageText,
			hasAttachment: attachments.length > 0,
			attachmentTypes:
				attachments.length > 0
					? (attachments as IgAttachment[]).map((a) => a.type)
					: undefined,
		});
		return;
	}

	const { data: igAccount } = (await supabase
		.from("instagram_accounts")
		.select(
			"id, user_id, instagram_user_id, instagram_access_token_encrypted, login_type",
		)
		.eq("instagram_user_id", event.ig_user_id)
		.maybeSingle()) as {
		data: IgAccountRow | null;
		error: PostgrestError | null;
	};

	if (!igAccount) {
		// Unregistered account — app-level webhook sends events for all authorized
		// accounts, including ones never added to the platform. Skip silently.
		logger.info("IG event from unregistered account, skipping", {
			igUserId: event.ig_user_id,
			eventId: event.id,
		});
		return;
	}

	// ── Local-first: store DM in DB on webhook receipt ──
	// Store BEFORE echo check — we want both incoming and outgoing messages in DB
	const isEcho = !!(p.message?.is_echo || senderId === event.ig_user_id);
	const messageId = p.message?.mid || `${conversationId}_${Date.now()}`;
	let isFirstInboundMessage = false;
	if (!isEcho) {
		const { count, error } = await supabase
			.from("inbox_dm_messages")
			.select("id", { count: "exact", head: true })
			.eq("conversation_id", conversationId)
			.eq("ig_account_id", igAccount.id)
			.eq("is_echo", false);
		if (error) {
			logger.warn("Could not verify first-message responder state", {
				accountId: igAccount.id,
				conversationId,
				error: error.message,
			});
		}
		isFirstInboundMessage = !error && (count ?? 0) === 0;
	}
	try {
		await supabase.from("inbox_dm_messages").upsert(
			{
				id: messageId,
				conversation_id: conversationId,
				ig_account_id: igAccount.id,
				user_id: igAccount.user_id,
				sender_id: senderId,
				message_text: messageText || null,
				attachment_type: igPostAttachment?.type || null,
				attachment_url: attachmentUrl,
				is_echo: isEcho,
				created_at: new Date().toISOString(),
			},
			{ onConflict: "id" },
		);

		// Update conversation summary for inbox list view
		await supabase.from("inbox_dm_cache").upsert(
			{
				id: conversationId,
				user_id: igAccount.user_id,
				account_id: igAccount.id,
				participant_id: senderId,
				last_message_text: messageText || "(attachment)",
				last_message_at: new Date().toISOString(),
				is_read: false,
				updated_at: new Date().toISOString(),
			},
			{ onConflict: "id" },
		);
	} catch (storeErr) {
		// Non-critical — don't fail webhook processing if DB store fails
		logger.warn("Failed to store DM in local DB", {
			error: String(storeErr),
			messageId,
			conversationId,
		});
	}

	// Skip notification + auto-responder for echoes (our own outgoing messages)
	if (isEcho) {
		return;
	}

	// Notify user about new DM
	const { createNotification } = await import("../../createNotification.js");
	const dmPreview = messageText
		? `New message: ${messageText.slice(0, 100)}`
		: igPostAttachment
			? "Shared a post with you"
			: "New message";
	await createNotification({
		userId: igAccount.user_id,
		type: "dm_received",
		title: "New Instagram DM",
		message: dmPreview,
		data: { senderId, conversationId, accountId: igAccount.id, attachmentUrl },
	});

	// #507: Check ALL enabled auto-responders (AI, template, and custom)
	const { data: responders } = await supabase
		.from("ig_auto_responders")
		.select("*")
		.eq("ig_account_id", igAccount.id)
		.eq("is_enabled", true);

	if (!responders || responders.length === 0) {
		return;
	}

	// Find matching responder. Story replies arrive through IG messaging webhooks
	// with story-specific attachment/referral markers, not as normal keyword DMs.
	let matchedResponder = null;
	for (const r of responders) {
		if (r.trigger_type === "first_message" && isFirstInboundMessage) {
			matchedResponder = r;
			break;
		}
		if (r.trigger_type === "story_reply" && hasStoryReplySignal) {
			matchedResponder = r;
			break;
		}
		if (r.trigger_type === "keyword" && r.trigger_keywords?.length) {
			const lowerMsg = (messageText || "").toLowerCase();
			const hasMatch = r.trigger_keywords.some((kw: string) =>
				lowerMsg.includes(kw.toLowerCase()),
			);
			if (hasMatch) {
				matchedResponder = r;
				break;
			}
		}
	}

	if (!matchedResponder) {
		return;
	}

	// Check DM rate limits (50/hour, 500/day — applies to all auto-responder types)
	const { data: rateLimit } = await supabase
		.from("ig_dm_ai_rate_limits")
		.select("*")
		.eq("account_id", igAccount.id)
		.maybeSingle();

	const now = new Date();
	let hourCount = rateLimit?.responses_this_hour || 0;
	let dayCount = rateLimit?.responses_today || 0;
	const hourReset = rateLimit?.hour_reset_at
		? new Date(rateLimit.hour_reset_at)
		: new Date(0);
	const dayReset = rateLimit?.day_reset_at
		? new Date(rateLimit.day_reset_at)
		: new Date(0);

	if (now > hourReset) hourCount = 0;
	if (now > dayReset) dayCount = 0;

	if (hourCount >= 50 || dayCount >= 500) {
		logger.warn("DM auto-responder rate limit reached", {
			accountId: igAccount.id,
		});
		return;
	}

	// #512: Enforce max_responses_per_user limit
	if (
		matchedResponder.max_responses_per_user &&
		matchedResponder.max_responses_per_user > 0
	) {
		const { count: userResponseCount } = await supabase
			.from("ig_dm_ai_responses")
			.select("*", { count: "exact", head: true })
			.eq("account_id", igAccount.id)
			.eq("conversation_id", conversationId);

		if ((userResponseCount ?? 0) >= matchedResponder.max_responses_per_user) {
			logger.info("Per-user auto-response limit reached", {
				accountId: igAccount.id,
				senderId,
				limit: matchedResponder.max_responses_per_user,
				count: userResponseCount,
			});
			return;
		}
	}

	// Apply configured delay (default 2s for natural feel)
	const delayMs = (matchedResponder.delay_seconds || 2) * 1000;
	if (delayMs > 0) {
		await new Promise((resolve) =>
			setTimeout(resolve, Math.min(delayMs, 10000)),
		);
	}

	const { sendMessage } = await import("../../instagramApi.js");

	// Branch: AI-generated vs template/custom response
	if (matchedResponder.use_ai_response) {
		// ---------- AI Response Path ----------
		const startTime = Date.now();
		try {
			const { generateDMResponse } = await import(
				"../../../../services/aiService.js"
			);

			const { data: igAccountConfig } = await supabase
				.from("instagram_accounts")
				.select("ai_config")
				.eq("id", igAccount.id)
				.maybeSingle();

			const voiceProfile = igAccountConfig?.ai_config || undefined;

			const sanitizedMessage = (messageText || "")
				.replace(/["""]/g, "'")
				.substring(0, 1000);

			const aiPromise = generateDMResponse(
				sanitizedMessage,
				[],
				matchedResponder.ai_response_intent || "engage",
				voiceProfile,
				matchedResponder.ai_system_prompt || undefined,
			);
			const timeoutPromise = new Promise<never>((_, reject) =>
				setTimeout(() => reject(new Error("AI DM generation timed out")), 8000),
			);

			// biome-ignore lint/suspicious/noImplicitAnyLet: type comes from lazy-imported generateDMResponse
			let result;
			try {
				result = await Promise.race([aiPromise, timeoutPromise]);
			} catch (timeoutErr) {
				logger.warn("AI DM generation failed/timed out", {
					error: String(timeoutErr),
				});
				return;
			}

			const responseTimeMs = Date.now() - startTime;

			const sendResult = await sendMessage(
				igAccount.instagram_access_token_encrypted || "",
				igAccount.instagram_user_id,
				senderId,
				result.response,
				igAccount.login_type || "",
			);

			if (!sendResult.success) {
				logger.error("Failed to send AI DM", { error: sendResult.error });
				return;
			}

			await supabase.from("ig_dm_ai_responses").insert({
				account_id: igAccount.id,
				conversation_id: conversationId,
				incoming_message: messageText,
				ai_response: result.response,
				response_intent: matchedResponder.ai_response_intent || "engage",
				voice_profile_used: !!voiceProfile,
				tokens_used: result.tokensUsed,
				response_time_ms: responseTimeMs,
			});

			logger.info("Sent AI DM response", {
				senderId,
				responseTimeMs,
				tokensUsed: result.tokensUsed,
			});
		} catch (err: unknown) {
			logger.error("AI DM generation failed", {
				error: serializeError(err),
			});
			throw err;
		}
	} else {
		// ---------- Template / Custom Response Path ----------
		let responseText: string | null = null;

		if (matchedResponder.template_id) {
			// Resolve template from ig_dm_templates
			const { data: template } = await supabase
				.from("ig_dm_templates")
				.select("content")
				.eq("id", matchedResponder.template_id)
				.maybeSingle();

			responseText = template?.content || null;
		}

		if (!responseText && matchedResponder.custom_response) {
			responseText = matchedResponder.custom_response;
		}

		if (!responseText) {
			logger.warn("Auto-responder matched but has no response content", {
				responderId: matchedResponder.id,
				triggerType: matchedResponder.trigger_type,
			});
			return;
		}

		// Simple variable substitution (match Threads auto-reply pattern)
		responseText = responseText.replace(/\{\{username\}\}/gi, "there");

		try {
			const sendResult = await sendMessage(
				igAccount.instagram_access_token_encrypted || "",
				igAccount.instagram_user_id,
				senderId,
				responseText,
				igAccount.login_type || "",
			);

			if (!sendResult.success) {
				logger.error("Failed to send template/custom DM", {
					error: sendResult.error,
				});
				return;
			}

			logger.info("Sent template/custom DM response", {
				senderId,
				responderId: matchedResponder.id,
				triggerType: matchedResponder.trigger_type,
			});
			await supabase.from("ig_dm_ai_responses").insert({
				account_id: igAccount.id,
				conversation_id: conversationId,
				incoming_message: messageText || "",
				ai_response: responseText,
				response_intent: `template:${matchedResponder.trigger_type}`,
				voice_profile_used: false,
				tokens_used: 0,
				response_time_ms: null,
			});
		} catch (err: unknown) {
			logger.error("Template DM send failed", {
				error: serializeError(err),
			});
			return;
		}
	}

	// Update rate limits (applies to all responder types)
	const nextHour = new Date(now.getTime() + 60 * 60 * 1000);
	const nextDay = new Date(now);
	nextDay.setHours(23, 59, 59, 999);

	await supabase.from("ig_dm_ai_rate_limits").upsert(
		{
			account_id: igAccount.id,
			responses_this_hour: hourCount + 1,
			responses_today: dayCount + 1,
			hour_reset_at: now > hourReset ? nextHour.toISOString() : hourReset,
			day_reset_at: now > dayReset ? nextDay.toISOString() : dayReset,
		},
		{ onConflict: "account_id" },
	);
}

async function processIgFollowEvent(
	supabase: SupabaseClient,
	event: IgWebhookEvent,
) {
	const payload = event.payload;
	if (!payload || typeof payload !== "object") {
		logger.warn("IG follow event has invalid payload, skipping", {
			eventId: event.id,
		});
		return;
	}

	const { data: igAccount } = (await supabase
		.from("instagram_accounts")
		.select("id, user_id, instagram_user_id")
		.eq("instagram_user_id", event.ig_user_id)
		.maybeSingle()) as {
		data: IgAccountRow | null;
		error: PostgrestError | null;
	};

	if (!igAccount) {
		// Unregistered account — app-level webhook sends events for all authorized
		// accounts, including ones never added to the platform. Skip silently.
		logger.info("IG event from unregistered account, skipping", {
			igUserId: event.ig_user_id,
			eventId: event.id,
		});
		return;
	}

	// Update follower count if provided in payload
	const followerCount = (payload.followed_by_count ?? payload.follower_count) as
		| number
		| undefined;
	if (followerCount !== undefined) {
		await supabase
			.from("instagram_accounts")
			.update({
				follower_count: followerCount,
				updated_at: new Date().toISOString(),
			})
			.eq("id", igAccount.id);
	}

	// Store in follower history for trend tracking (only if we have a real count)
	if (followerCount !== undefined && followerCount > 0) {
		await supabase.from("follower_history").upsert(
			{
				account_id: igAccount.id,
				platform: "instagram",
				date: new Date().toISOString().split("T")[0]!,
				follower_count: followerCount,
			},
			{ onConflict: "account_id,date" },
		);
	}

	if (igAccount?.user_id) {
		const { createNotification } = await import("../../createNotification.js");
		await createNotification({
			userId: igAccount.user_id,
			type: "follower_change",
			title: "New Instagram follower",
			message: payload.username
				? `@${payload.username} followed you`
				: "You have a new follower",
			data: { igUserId: event.ig_user_id, followerCount },
		});
	}

	logger.info("Processed IG follow event", {
		igAccountId: igAccount.id,
		followerCount,
	});
}

// ----------------------------------------------------------------------------
// Messaging Signal Handlers (read receipts, reactions, edits)
// Per Meta docs: each messaging event type has a distinct payload shape.
// These are separated from processIgMessagingEvent which handles actual DMs.
// ----------------------------------------------------------------------------

/**
 * Handle read receipts: { sender, recipient, timestamp, read: { mid } }
 * Updates inbox_dm_cache so the inbox UI reflects accurate read state.
 */
async function processIgMessagingSeenEvent(
	supabase: SupabaseClient,
	event: IgWebhookEvent,
) {
	const payload = event.payload as IgMessagingSeenPayload;
	const senderId = payload?.sender?.id;
	const readMid = payload?.read?.mid;

	if (!senderId) {
		logger.debug("IG messaging_seen event missing sender, skipping", {
			eventId: event.id,
		});
		return;
	}

	const { data: igAccount } = (await supabase
		.from("instagram_accounts")
		.select("id, user_id, instagram_user_id")
		.eq("instagram_user_id", event.ig_user_id)
		.maybeSingle()) as {
		data: IgAccountRow | null;
		error: PostgrestError | null;
	};

	if (!igAccount) return;

	// The sender read our message — mark the conversation as read in our cache.
	// We match on participant_id (the remote user) + account owner.
	const { error } = await supabase
		.from("inbox_dm_cache")
		.update({
			is_read: true,
			updated_at: new Date().toISOString(),
		})
		.eq("user_id", igAccount.user_id)
		.eq("participant_id", senderId);

	if (error) {
		logger.debug("Failed to update inbox_dm_cache for read receipt", {
			error: error.message,
			senderId,
		});
		return;
	}

	logger.debug("Processed IG messaging_seen event", {
		igAccountId: igAccount.id,
		senderId,
		readMid,
	});
}

/**
 * Handle reactions: { sender, recipient, timestamp, reaction: { mid, action, reaction, emoji } }
 * Notifies the account owner when someone reacts to their DM.
 */
async function processIgMessageReactionEvent(
	supabase: SupabaseClient,
	event: IgWebhookEvent,
) {
	const payload = event.payload as IgMessageReactionPayload;
	const senderId = payload?.sender?.id;
	const reaction = payload?.reaction;

	if (!senderId || !reaction) {
		logger.debug(
			"IG message_reactions event missing sender or reaction, skipping",
			{
				eventId: event.id,
			},
		);
		return;
	}

	const { data: igAccount } = (await supabase
		.from("instagram_accounts")
		.select("id, user_id, instagram_user_id")
		.eq("instagram_user_id", event.ig_user_id)
		.maybeSingle()) as {
		data: IgAccountRow | null;
		error: PostgrestError | null;
	};

	if (!igAccount) return;

	// Don't notify for our own reactions
	if (senderId === event.ig_user_id) return;

	// Only notify on "react", not "unreact"
	if (reaction.action === "react") {
		const { createNotification } = await import("../../createNotification.js");
		const emoji = reaction.emoji || reaction.reaction || "a message";
		await createNotification({
			userId: igAccount.user_id,
			type: "dm_received",
			title: "DM Reaction",
			message: `Someone reacted ${emoji} to your message`,
			data: {
				senderId,
				conversationId: senderId,
				accountId: igAccount.id,
				reactionMid: reaction.mid,
			},
		});
	}

	logger.debug("Processed IG message_reactions event", {
		igAccountId: igAccount.id,
		action: reaction.action,
		emoji: reaction.emoji,
	});
}

/**
 * Handle message edits: { sender, recipient, timestamp, message_edit: { mid, text } }
 * We don't store individual DM messages, so this is a no-op for now.
 */
async function processIgMessageEditEvent(
	_supabase: SupabaseClient,
	event: IgWebhookEvent,
) {
	logger.debug("IG message_edit event received (no-op, no DM message store)", {
		eventId: event.id,
		igUserId: event.ig_user_id,
	});
}

export async function handleIgWebhookEvent(
	supabase: SupabaseClient,
	event: IgWebhookEvent,
): Promise<void> {
	switch (event.event_type) {
		case "comments":
			await processIgCommentEvent(supabase, event);
			break;
		case "live_comments":
			// Treat live comments like regular comments (same payload shape)
			await processIgCommentEvent(supabase, event);
			break;
		case "mentions":
			await processIgMentionEvent(supabase, event);
			break;
		case "story_insights":
			await processIgStoryInsightsEvent(supabase, event);
			break;
		case "messages":
		case "messaging":
			await processIgMessagingEvent(supabase, event);
			break;
		case "messaging_seen":
			await processIgMessagingSeenEvent(supabase, event);
			break;
		case "message_reactions":
			await processIgMessageReactionEvent(supabase, event);
			break;
		case "message_edit":
			await processIgMessageEditEvent(supabase, event);
			break;
		case "messaging_postbacks":
		case "messaging_referral":
		case "messaging_optins":
		case "messaging_handover":
		case "standby":
		case "feed":
			logger.debug("IG webhook signal received (not actionable)", {
				eventType: event.event_type,
				igUserId: event.ig_user_id,
			});
			break;
		case "follow":
			await processIgFollowEvent(supabase, event);
			break;
		default:
			logger.warn("Unknown IG event type", {
				eventType: event.event_type,
				igUserId: event.ig_user_id,
			});
			break;
	}
}
