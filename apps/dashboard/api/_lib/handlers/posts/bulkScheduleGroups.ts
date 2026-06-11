// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
/**
 * Handler: POST /api/posts?action=bulk-schedule-groups
 *
 * Schedule up to 100 posts across multiple account groups in a single request.
 * Distributes posts across accounts within each group using round-robin.
 * Respects per-account daily publish cap (10/day).
 *
 * Body: {
 *   posts: [{
 *     groupId: string,
 *     platform: "threads" | "instagram",
 *     content: string,
 *     scheduledFor: string (ISO 8601),
 *     mediaIds?: string[],
 *     mediaType?: string (IG only),
 *     pollOptions?: string[] (Threads only),
 *     quotePostId?: string (Threads only),
 *     linkUrl?: string (Threads only),
 *     gifAttachment?: object (Threads only),
 *     textAttachment?: object (Threads only),
 *     locationId?: string,
 *   }]
 * }
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";
import { publishableAccountFilters } from "../../accountEligibility.js";
import { apiError, apiSuccess } from "../../apiResponse.js";
import { checkDailyCap, DAILY_CAP } from "../../dailyCap.js";
import { normalizeIGMediaType } from "../../instagram/shared.js";
import { logger } from "../../logger.js";
import {
	type PreflightAccountStatus,
	type PreflightInput,
	type PreflightMediaItem,
	runPublishPreflight,
} from "../../publishPreflight.js";
import { sanitizeHtml } from "../../sanitize.js";
import { getSupabase } from "../../supabase.js";
import { parseBodyOrError } from "../../validation.js";
import { z, zEnum, zRecord, zUnknown } from "../../zodCompat.js";
import {
	checkSubscriptionPostLimit,
	normalizePostMediaType,
	resolveMediaUrls,
} from "./shared.js";

const MAX_POSTS = 100;

const PostItemSchema = z.object({
	groupId: z.string().min(1),
	platform: zEnum(["threads", "instagram"]),
	content: z.string().min(1),
	scheduledFor: z.string().min(1),
	mediaIds: z.array(z.string()).optional(),
	mediaType: z.string().optional(),
	pollOptions: z.array(z.string()).optional(),
	quotePostId: z.string().optional(),
	linkUrl: z.string().optional(),
	gifAttachment: zRecord(zUnknown()).optional(),
	textAttachment: zRecord(zUnknown()).optional(),
	locationId: z.string().optional(),
	topicTag: z.string().optional(),
	textSpoilers: zRecord(zUnknown()).optional(),
	isSpoilerMedia: z.boolean().optional(),
	altText: z.string().optional(),
	collaborators: z.array(z.string()).max(3).optional(),
	trialReels: z.boolean().optional(),
	isTrialReel: z.boolean().optional(),
	trialGraduationStrategy: zEnum(["MANUAL", "SS_PERFORMANCE"]).optional(),
	coverUrl: z.string().optional(),
	shareToFeed: z.boolean().optional(),
	userTags: z.array(zRecord(zUnknown())).optional(),
	brandedContentSponsorIds: z.array(z.string()).max(2).optional(),
	isPaidPartnership: z.boolean().optional(),
	firstComment: z.string().optional(),
});

const BulkScheduleGroupsSchema = z.object({
	posts: z
		.array(PostItemSchema)
		.min(1, "At least 1 post required")
		.max(MAX_POSTS, `Max ${MAX_POSTS} posts per request`),
	autoAttachMedia: z.boolean().optional(),
});

// biome-ignore lint/suspicious/noExplicitAny: Vercel TS 5.9 z.infer workaround
type PostItem = any;

// biome-ignore lint/suspicious/noExplicitAny: new columns not in generated types
const db = (): any => getSupabase();

interface ScheduledResult {
	index: number;
	postId: string;
	groupId: string;
	accountId: string;
	platform: string;
	scheduledFor: string;
	exactDispatchScheduled: boolean;
	qstashMessageId?: string | undefined;
	mediaAttached?: boolean | undefined;
	mediaDescription?: string | null | undefined;
}

interface FailedResult {
	index: number;
	groupId: string;
	reason: string;
	postId?: string | undefined;
	code?: string | undefined;
}

interface BulkScheduleAccountRow {
	id: string;
	instagram_user_id?: string | null;
	instagram_access_token_encrypted?: string | null;
	facebook_page_access_token_encrypted?: string | null;
	threads_user_id?: string | null;
	threads_access_token_encrypted?: string | null;
	login_type?: string | null;
	is_active?: boolean | null;
	needs_reauth?: boolean | null;
	status?: string | null;
	token_expires_at?: string | null;
	follower_count?: number | null;
}

const MIN_SCHEDULE_LEAD_MS = 2 * 60 * 1000;
const MAX_SCHEDULE_MONTHS = 6;

function addMonths(date: Date, months: number): Date {
	const next = new Date(date.getTime());
	next.setMonth(next.getMonth() + months);
	return next;
}

function parseScheduleWindow(scheduledFor: string): {
	date: Date | null;
	error?: string | undefined;
	code?: string | undefined;
} {
	const date = new Date(scheduledFor);
	if (Number.isNaN(date.getTime())) {
		return {
			date: null,
			error: "scheduledFor must be a valid ISO date",
			code: "INVALID_SCHEDULE_DATE",
		};
	}
	const now = new Date();
	if (date <= now) {
		return {
			date: null,
			error: "scheduledFor must be in the future",
			code: "SCHEDULE_IN_PAST",
		};
	}
	if (date.getTime() - now.getTime() < MIN_SCHEDULE_LEAD_MS) {
		return {
			date: null,
			error: "scheduledFor must be at least 2 minutes in the future",
			code: "SCHEDULE_TOO_SOON",
		};
	}
	if (date > addMonths(now, MAX_SCHEDULE_MONTHS)) {
		return {
			date: null,
			error: "scheduledFor cannot be more than 6 months in the future",
			code: "SCHEDULE_TOO_FAR",
		};
	}
	return { date };
}

function accountToPreflightStatus(
	platform: "threads" | "instagram",
	account: BulkScheduleAccountRow | null,
): PreflightAccountStatus {
	if (!account) return { found: false };
	if (platform === "instagram") {
		return {
			found: true,
			isActive: account.is_active,
			needsReauth: account.needs_reauth,
			status: account.status,
			tokenExpiresAt: account.token_expires_at,
				hasAccessToken: !!account.instagram_access_token_encrypted,
				hasPlatformUserId: !!account.instagram_user_id,
				loginType: account.login_type,
				followerCount: account.follower_count,
			};
	}
	return {
		found: true,
		isActive: account.is_active,
		needsReauth: account.needs_reauth,
		status: account.status,
		tokenExpiresAt: account.token_expires_at,
		hasAccessToken: !!account.threads_access_token_encrypted,
		hasPlatformUserId: !!account.threads_user_id,
	};
}

async function fetchBulkScheduleAccount(
	userId: string,
	platform: "threads" | "instagram",
	accountId: string,
): Promise<BulkScheduleAccountRow | null> {
	const table = platform === "instagram" ? "instagram_accounts" : "accounts";
	const select =
		platform === "instagram"
			? "id, instagram_user_id, instagram_access_token_encrypted, facebook_page_access_token_encrypted, login_type, is_active, needs_reauth, status, token_expires_at, follower_count"
			: "id, threads_user_id, threads_access_token_encrypted, is_active, needs_reauth, status, token_expires_at";
	const { data } = await db()
		.from(table)
		.select(select)
		.eq("id", accountId)
		.eq("user_id", userId)
		.maybeSingle();
	return (data as BulkScheduleAccountRow | null) ?? null;
}

function pollAttachmentFromOptions(
	pollOptions: string[] | null | undefined,
): PreflightInput["pollAttachment"] {
	return (pollOptions?.length ?? 0) > 0 ? { options: pollOptions ?? [] } : null;
}

/**
 * Resolve **eligible** accounts for a group + platform.
 * Uses the shared publishableAccountFilters() so scheduler and publisher
 * agree on which accounts can post.
 * Caches results for reuse within the batch.
 */
async function getGroupAccounts(
	userId: string,
	groupId: string,
	platform: "threads" | "instagram",
	cache: Map<string, string[]>,
): Promise<string[]> {
	const cacheKey = `${groupId}:${platform}`;
	if (cache.has(cacheKey)) return cache.get(cacheKey) ?? [];

	const table = platform === "instagram" ? "instagram_accounts" : "accounts";
	const baseQuery = db()
		.from(table)
		.select("id")
		.eq("user_id", userId)
		.eq("group_id", groupId);

	const { data } = await publishableAccountFilters(baseQuery);

	const ids = ((data ?? []) as { id: string }[]).map((a) => a.id);
	cache.set(cacheKey, ids);
	return ids;
}

export async function handleBulkScheduleGroups(
	req: VercelRequest,
	res: VercelResponse,
	userId: string,
) {
	const parsed = parseBodyOrError(res, BulkScheduleGroupsSchema, req.body);
	if (!parsed) return;

	const { posts, autoAttachMedia } = parsed;

	logger.info("Bulk schedule groups", {
		userId,
		count: posts.length,
	});

	// Verify all referenced groups belong to user
	const uniqueGroupIds = [
		...new Set(posts.map((p: PostItem) => p.groupId as string)),
	];
	const { data: ownedGroups } = await db()
		.from("account_groups")
		.select("id")
		.eq("user_id", userId)
		.in("id", uniqueGroupIds);

	const ownedGroupSet = new Set(
		((ownedGroups ?? []) as { id: string }[]).map((g) => g.id),
	);

	const postsByDay = new Map<string, { date: Date; count: number }>();
	for (const post of posts as PostItem[]) {
		if (!ownedGroupSet.has(post.groupId)) continue;
		const { date: scheduledDate } = parseScheduleWindow(post.scheduledFor);
		if (!scheduledDate) {
			continue;
		}
		const dayKey = new Date(scheduledDate).toISOString().slice(0, 10);
		const existing = postsByDay.get(dayKey);
		if (existing) existing.count += 1;
		else postsByDay.set(dayKey, { date: scheduledDate, count: 1 });
	}
	for (const { date, count } of postsByDay.values()) {
		const tierCheck = await checkSubscriptionPostLimit(userId, {
			targetDate: date,
			mode: "schedule",
			additionalCount: count,
		});
		if (!tierCheck.allowed) {
			logger.info("Bulk schedule daily post limit reached", {
				userId,
				tier: tierCheck.tier,
				used: tierCheck.used,
				requested: count,
				limit: tierCheck.limit,
				targetDate: date.toISOString(),
			});
			return apiError(
				res,
				403,
				`Daily post limit reached for ${date.toISOString().slice(0, 10)} (${tierCheck.used}/${tierCheck.limit} used, ${count} requested).`,
				{ code: "DAILY_POST_LIMIT_EXCEEDED" },
			);
		}
	}

	// Fetch group configs for crossreshare + media attachment settings
	// biome-ignore lint/suspicious/noExplicitAny: Supabase deep-type TS2589
	const { data: groupConfigs } = await (db() as any)
		.from("auto_post_group_config")
		.select(
			"group_id, crossreshare_to_ig, crossreshare_to_ig_dark_mode, media_attachment_chance",
		)
		.in("group_id", uniqueGroupIds);
	const groupCrossreshareMap = new Map<
		string,
		{ normal: boolean; darkMode: boolean }
	>();
	const groupMediaChanceMap = new Map<string, number>();
	for (const gc of (groupConfigs ?? []) as {
		group_id: string;
		crossreshare_to_ig: boolean | null;
		crossreshare_to_ig_dark_mode: boolean | null;
		media_attachment_chance: number | null;
	}[]) {
		if (gc.crossreshare_to_ig || gc.crossreshare_to_ig_dark_mode) {
			groupCrossreshareMap.set(gc.group_id, {
				normal: !!gc.crossreshare_to_ig,
				darkMode: !!gc.crossreshare_to_ig_dark_mode,
			});
		}
		if (gc.media_attachment_chance != null) {
			groupMediaChanceMap.set(gc.group_id, gc.media_attachment_chance);
		}
	}

	// Account cache and round-robin counters
	const accountCache = new Map<string, string[]>();
	const roundRobinIndex = new Map<string, number>();

	// Track per-account cap usage within this batch
	const batchCapUsage = new Map<string, number>();

	const scheduled: ScheduledResult[] = [];
	const failed: FailedResult[] = [];

	for (let i = 0; i < posts.length; i++) {
		const post = posts[i] as PostItem;
		const { groupId, platform, content, scheduledFor } = post;

		// Validate group ownership
		if (!ownedGroupSet.has(groupId)) {
			failed.push({
				index: i,
				groupId,
				reason: "Group not found or not owned",
			});
			continue;
		}

		// Validate the same schedule window enforced by the single-post path.
		const scheduleWindow = parseScheduleWindow(scheduledFor);
		if (scheduleWindow.error || !scheduleWindow.date) {
			failed.push({
				index: i,
				groupId,
				reason: scheduleWindow.error || "Invalid scheduledFor date",
				code: scheduleWindow.code,
			});
			continue;
		}
		const scheduledDate = scheduleWindow.date;

		// Validate content
		if (!content?.trim()) {
			failed.push({ index: i, groupId, reason: "Content is required" });
			continue;
		}

		// Get accounts for this group + platform
		const accounts = await getGroupAccounts(
			userId,
			groupId,
			platform,
			accountCache,
		);
		if (accounts.length === 0) {
			failed.push({
				index: i,
				groupId,
				reason: `No active ${platform} accounts in group (check is_active, suspended, needs_reauth)`,
			});
			continue;
		}

		// Auto-attach media from group library when mediaIds not explicitly provided
		let autoMedia: {
			url: string;
			id: string;
			description: string | null;
			isVideo?: boolean | undefined;
		} | null = null;
		if (autoAttachMedia !== false && post.mediaIds === undefined) {
			const isInstagram = platform === "instagram";
			let shouldAttach = false;

			if (isInstagram) {
				shouldAttach = true;
			} else {
				const mediaChance = groupMediaChanceMap.get(groupId) ?? 0;
				shouldAttach = mediaChance > 0 && Math.random() * 100 < mediaChance;
			}

			if (shouldAttach) {
				try {
					const { getRandomMediaWithContext } = await import(
						"../../handlers/auto-post/publisher.js"
					);
					const mediaResult = await getRandomMediaWithContext(
						userId,
						"all",
						groupId,
					);
					if (mediaResult) {
						autoMedia = {
							url: mediaResult.url,
							id: mediaResult.id,
							description: mediaResult.description,
							isVideo: mediaResult.isVideo,
						};
					} else if (isInstagram) {
						failed.push({
							index: i,
							groupId,
							reason:
								"Instagram requires media but no media found in group library",
						});
						continue;
					}
				} catch {
					// Best-effort — proceed text-only for Threads, fail for IG
					if (isInstagram) {
						failed.push({
							index: i,
							groupId,
							reason: "Instagram requires media but media selection failed",
						});
						continue;
					}
				}
			}
		}

		// Round-robin: pick next account in rotation
		const rrKey = `${groupId}:${platform}`;
		const currentIdx = roundRobinIndex.get(rrKey) ?? 0;

		// Try each account in the group until we find one under cap
		let assigned = false;
		for (let attempt = 0; attempt < accounts.length; attempt++) {
			const accountIdx = (currentIdx + attempt) % accounts.length;
			const accountId = accounts[accountIdx];

			// Check daily cap for the target day (DB + batch-local usage)
			const capResult = await checkDailyCap(accountId!, platform, scheduledDate);
			const batchUsed = batchCapUsage.get(accountId!) ?? 0;
			const totalUsed = capResult.used + batchUsed;

			if (totalUsed >= DAILY_CAP) {
				continue; // Try next account in group
			}

			// Build insert record — only columns that exist on the posts table
			const cleanContent = sanitizeHtml(content);
			const now = new Date().toISOString();

			// biome-ignore lint/suspicious/noExplicitAny: Supabase insert type workaround
			const insertData: any = {
				user_id: userId,
				content: cleanContent,
				platform,
				status: "scheduled",
				scheduled_for: scheduledDate.toISOString(),
				created_at: now,
				updated_at: now,
			};

			if (platform === "instagram") {
				const canonicalIgMediaType =
					normalizeIGMediaType(post.mediaType) || "IMAGE";
				insertData.instagram_account_id = accountId;
				insertData.account_id = null;
				insertData.ig_media_type = canonicalIgMediaType;
				insertData.media_type = normalizePostMediaType(
					canonicalIgMediaType,
					"image",
				);
				if (post.altText) insertData.alt_text = post.altText;
				if (post.locationId) insertData.location_id = post.locationId;
			} else {
				insertData.account_id = accountId;
				// Preliminary media_type — may be overridden below after media validation
				// (videos forced to single, carousels photos-only)
				insertData.media_type = normalizePostMediaType(
					post.mediaIds?.length > 1
						? "CAROUSEL"
						: post.mediaIds?.length === 1
							? "IMAGE"
							: "TEXT",
				);
				if (post.pollOptions?.length >= 2)
					insertData.poll_options = post.pollOptions;
				if (post.linkUrl) insertData.link_url = post.linkUrl;
			}

			let preflightMedia: PreflightMediaItem[] = [];
			if (post.mediaIds?.length > 0) {
				// Validate media ownership — only allow user's own media
				// biome-ignore lint/suspicious/noExplicitAny: file_type not in generated types
				const { data: ownedMedia } = await (db() as any)
					.from("media")
					.select("id, file_type")
					.in("id", post.mediaIds)
					.eq("user_id", userId);
				const ownedMap = new Map<string, string>();
				for (const m of (ownedMedia ?? []) as {
					id: string;
					file_type?: string | undefined;
				}[]) {
					ownedMap.set(m.id, m.file_type || "");
				}
				const validMediaIds = (post.mediaIds as string[]).filter((id: string) =>
					ownedMap.has(id),
				);
				if (validMediaIds.length > 0) {
					preflightMedia = (
						await resolveMediaUrls(validMediaIds, userId)
					).items;
					// Videos are ALWAYS single, carousels are PHOTOS ONLY
					const hasVideo = validMediaIds.some((id) =>
						(ownedMap.get(id) || "").toLowerCase().startsWith("video"),
					);
					if (hasVideo && validMediaIds.length > 1) {
						// Force single video — pick only the first video
						const firstVideoId = validMediaIds.find((id) =>
							(ownedMap.get(id) || "").toLowerCase().startsWith("video"),
						);
						insertData.media_urls = [firstVideoId || validMediaIds[0]];
						insertData.media_ids = [firstVideoId || validMediaIds[0]];
						if (platform === "threads") {
							insertData.media_type = "video";
						}
					} else {
						insertData.media_urls = validMediaIds;
						insertData.media_ids = validMediaIds;
					}
				}
			}
			// Apply auto-selected media if no explicit mediaIds were provided
			if (autoMedia && !insertData.media_urls) {
				insertData.media_urls = [autoMedia.url];
				insertData.media_ids = [autoMedia.id];
				preflightMedia = [
					{
						url: autoMedia.url,
						type: autoMedia.isVideo ? "video" : "image",
					},
				];
				if (platform === "threads") {
					// Videos are always single — detect from isVideo flag or URL extension
					const isAutoVideo =
						autoMedia.isVideo || /\.(mp4|mov)(\?|$)/i.test(autoMedia.url);
					insertData.media_type = isAutoVideo ? "video" : "image";
				}
			}
			if (post.topicTag) insertData.topic_tag = post.topicTag;
			// Text spoilers: only from request body (manually set). No auto-detect.
			const resolvedTextSpoilers = post.textSpoilers || null;

			// Resolve crossreshare: per-post explicit > group config default
			const groupCfg =
				platform === "threads" ? groupCrossreshareMap.get(groupId) : undefined;
			const crossreshareToIg =
				(post as Record<string, unknown>).crossreshareToIg ??
				(post as Record<string, unknown>).crossreshareToIgDarkMode ??
				groupCfg?.normal ??
				groupCfg?.darkMode ??
				false;
			const crossreshareToIgDarkMode =
				(post as Record<string, unknown>).crossreshareToIgDarkMode ??
				groupCfg?.darkMode ??
				false;

			// Build metadata with all optional features
			const metaObj: Record<string, unknown> = {
				...(resolvedTextSpoilers ? { textSpoilers: resolvedTextSpoilers } : {}),
				...(post.isSpoilerMedia ? { isSpoiler: true } : {}),
				...(crossreshareToIgDarkMode
					? { crossreshareToIgDarkMode: true }
					: crossreshareToIg
						? { crossreshareToIg: true }
						: {}),
				// IG-specific features
				...(post.collaborators?.length > 0
					? { collaborators: post.collaborators }
					: {}),
				...(post.coverUrl ? { coverUrl: post.coverUrl } : {}),
				...(post.shareToFeed !== undefined
					? { shareToFeed: post.shareToFeed }
					: {}),
				...(post.userTags?.length > 0 ? { userTags: post.userTags } : {}),
				...(post.trialReels ? { trialReels: true } : {}),
				...(post.isTrialReel ? { isTrialReel: true } : {}),
				...(post.trialReels
					? { trialGraduationStrategy: post.trialGraduationStrategy || "MANUAL" }
					: {}),
				...(post.brandedContentSponsorIds?.length > 0
					? { brandedContentSponsorIds: post.brandedContentSponsorIds }
					: {}),
				...(post.isPaidPartnership ? { isPaidPartnership: true } : {}),
				...(post.firstComment ? { firstComment: post.firstComment } : {}),
				...(autoMedia?.description
					? { mediaDescription: autoMedia.description }
					: {}),
				...((post as Record<string, unknown>).thumbOffset !== undefined
					? { thumbOffset: (post as Record<string, unknown>).thumbOffset }
					: {}),
				...((post as Record<string, unknown>).audioName
					? { audioName: (post as Record<string, unknown>).audioName }
					: {}),
				...((post as Record<string, unknown>).productTags
					? { productTags: (post as Record<string, unknown>).productTags }
					: {}),
				...((post as Record<string, unknown>).commentEnabled !== undefined
					? { commentEnabled: (post as Record<string, unknown>).commentEnabled }
					: {}),
			};
			if (Object.keys(metaObj).length > 0) {
				insertData.metadata = metaObj;
				if (resolvedTextSpoilers) {
					insertData.text_spoilers = resolvedTextSpoilers;
				}
			}

			const account = await fetchBulkScheduleAccount(userId, platform, accountId!);
			const preflight = await runPublishPreflight(
				{
					platform,
					mode: "api",
					accountId: platform === "threads" ? accountId : undefined,
					instagramAccountId:
						platform === "instagram" ? accountId : undefined,
					content,
					media: preflightMedia,
					igMediaType:
						platform === "instagram"
							? insertData.ig_media_type || post.mediaType
							: undefined,
					mediaType: insertData.media_type || post.mediaType,
					collaborators: post.collaborators,
					isTrialReel: post.isTrialReel,
					trialReels: post.trialReels,
					brandedContentSponsorIds: post.brandedContentSponsorIds,
					isPaidPartnership: post.isPaidPartnership,
					linkUrl: post.linkUrl,
					gifAttachment: post.gifAttachment,
					pollAttachment: pollAttachmentFromOptions(post.pollOptions),
					textAttachment: post.textAttachment,
					topicTag: post.topicTag,
					crossreshareToIg: Boolean(crossreshareToIg),
					crossreshareToIgDarkMode: Boolean(crossreshareToIgDarkMode),
					coverUrl: post.coverUrl,
					shareToFeed: post.shareToFeed,
					userTags: post.userTags,
					productTags: (post as Record<string, unknown>).productTags as
						| unknown[]
						| undefined,
					thumbOffset: (post as Record<string, unknown>).thumbOffset as
						| number
						| undefined,
					audioName: (post as Record<string, unknown>).audioName as
						| string
						| undefined,
					commentEnabled: (post as Record<string, unknown>).commentEnabled as
						| boolean
						| undefined,
					firstComment: post.firstComment,
					textSpoilers: Array.isArray(resolvedTextSpoilers)
						? resolvedTextSpoilers
						: undefined,
					metadata: Object.keys(metaObj).length > 0 ? metaObj : undefined,
				},
				{
					account: accountToPreflightStatus(platform, account),
					checkMediaUrls: true,
				},
			);
			if (!preflight.ok) {
				failed.push({
					index: i,
					groupId,
					code: "PUBLISH_PREFLIGHT_FAILED",
					reason: `Publish preflight failed: ${preflight.issues
						.filter((issue) => issue.severity === "error")
						.map((issue) => issue.message)
						.join("; ") || "Review publishing requirements"}`,
				});
				continue;
			}

			const { data: newPost, error: insertErr } = await db()
				.from("posts")
				.insert(insertData)
				.select("id")
				.maybeSingle();

			if (insertErr || !newPost) {
				logger.error("[bulk-schedule] DB insert failed", {
					error: insertErr?.message,
					code: insertErr?.code,
					hint: insertErr?.hint,
					details: insertErr?.details,
					groupId,
					platform,
					accountId,
				});
				failed.push({
					index: i,
					groupId,
					reason: `DB insert failed: ${insertErr?.message || "no row returned"}`,
				});
			} else {
				const newPostId = (newPost as { id: string }).id;
				let qstashMessageId: string | null = null;
				try {
					const { dispatchPostPublish } = await import(
						"../../qstashSchedule.js"
					);
					qstashMessageId = await dispatchPostPublish(newPostId, scheduledDate);
				} catch (error) {
					logger.warn("[bulk-schedule] Exact dispatch failed", {
						postId: newPostId,
						groupId,
						platform,
						accountId,
						error: String(error),
					});
				}
				if (!qstashMessageId) {
					await db()
						.from("posts")
						.update({
							status: "draft",
							scheduled_for: null,
							error_message:
								"Exact-time scheduler unavailable. Schedule this post again once QStash is healthy.",
							updated_at: new Date().toISOString(),
						})
						.eq("id", newPostId)
						.eq("user_id", userId);
					failed.push({
						index: i,
						groupId,
						postId: newPostId,
						code: "EXACT_SCHEDULE_UNAVAILABLE",
						reason:
							"Exact-time scheduler unavailable. The post was saved as a draft; try scheduling again shortly.",
					});
					assigned = true;
					break;
				}
				scheduled.push({
					index: i,
					postId: newPostId,
					groupId,
					accountId: accountId!,
					platform,
					scheduledFor: scheduledDate.toISOString(),
					exactDispatchScheduled: true,
					qstashMessageId,
					...(autoMedia
						? { mediaAttached: true, mediaDescription: autoMedia.description }
						: {}),
				});

				// Track batch usage
				batchCapUsage.set(accountId!, batchUsed + 1);
				// Advance round-robin for this group+platform
				roundRobinIndex.set(rrKey, (accountIdx + 1) % accounts.length);
			}

			assigned = true;
			break;
		}

		if (!assigned && !failed.some((f) => f.index === i)) {
			failed.push({
				index: i,
				groupId,
				reason: `All ${platform} accounts in group at daily cap (${DAILY_CAP}/day)`,
			});
		}
	}

	return apiSuccess(res, {
		scheduled,
		failed,
		totalRequested: posts.length,
		scheduledCount: scheduled.length,
		failedCount: failed.length,
	});
}
