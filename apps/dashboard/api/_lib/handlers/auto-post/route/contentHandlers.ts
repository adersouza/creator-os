/**
 * Content handler modules for auto-post API.
 * Handles: bulk update group configs, account bios, bulk set content strategy,
 *          competitor posts sample, variants, promote variant
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";
import { apiError, apiSuccess } from "../../../apiResponse.js";
import { logger } from "../../../logger.js";
import { requireMinTier } from "../../../tierGate.js";
import { verifyAnyAccountOwnership } from "../../helpers/verifyOwnership.js";
import { retryQueueItem } from "../queueState.js";
import { db, verifyWorkspaceAccess } from "./routeHelpers.js";

export async function handleBulkUpdateGroupConfigs(
	req: VercelRequest,
	res: VercelResponse,
	userId: string,
) {
	if (!(await requireMinTier(userId, "empire", res))) return;

	const { workspaceId, updates } = req.body;
	if (!workspaceId) return apiError(res, 400, "workspaceId is required");
	if (!Array.isArray(updates) || updates.length === 0)
		return apiError(res, 400, "updates array is required");
	if (updates.length > 30) return apiError(res, 400, "Max 30 groups per call");
	if (!(await verifyWorkspaceAccess(userId, workspaceId, res))) return;

	const results: Array<{ groupId: string; ok: boolean; error?: string | undefined }> = [];

	for (const update of updates) {
		const { groupId, ...configFields } = update as {
			groupId: string;
			[key: string]: unknown;
		};
		if (!groupId) {
			results.push({ groupId: "unknown", ok: false, error: "missing groupId" });
			continue;
		}

		// Map camelCase → snake_case
		const mapping: Record<string, string> = {
			enabled: "enabled",
			postsPerAccountPerDay: "posts_per_account_per_day",
			minIntervalMinutes: "min_interval_minutes",
			maxIntervalMinutes: "max_interval_minutes",
			activeHoursStart: "active_hours_start",
			activeHoursEnd: "active_hours_end",
			platform: "platform",
			useSmartTiming: "use_smart_timing",
			crossreshareToIg: "crossreshare_to_ig",
			crossreshareToIgDarkMode: "crossreshare_to_ig_dark_mode",
		};

		const config: Record<string, unknown> = {};
		for (const [camel, snake] of Object.entries(mapping)) {
			if (configFields[camel] !== undefined)
				config[snake] = configFields[camel];
		}

		if (Object.keys(config).length === 0) {
			results.push({ groupId, ok: false, error: "no valid config fields" });
			continue;
		}

		const { error } = await db()
			.from("auto_post_group_config")
			.update(config)
			.eq("workspace_id", workspaceId)
			.eq("group_id", groupId);

		results.push({ groupId, ok: !error, error: error?.message });
	}

	return apiSuccess(res, {
		results,
		updated: results.filter((r) => r.ok).length,
		failed: results.filter((r) => !r.ok).length,
	});
}

export async function handleGetAccountBios(
	_req: VercelRequest,
	res: VercelResponse,
	userId: string,
) {
	const { data: accounts, error } = await db()
		.from("accounts")
		.select(
			"id, username, threads_user_id, biography, followers_count, is_active, is_retired, is_shadowbanned, needs_reauth",
		)
		.eq("user_id", userId)
		.order("username");

	if (error) {
		logger.error("[contentHandlers] Failed to fetch accounts for bio audit", { error: String(error) });
		return apiError(res, 500, "Failed to fetch accounts");
	}

	// Also get account group assignments
	const { data: groups } = await db()
		.from("account_groups")
		.select("id, name, account_ids")
		.eq("user_id", userId);

	const groupMap = new Map<string, string>();
	for (const g of (groups || []) as Array<{
		id: string;
		name: string;
		account_ids: string[];
	}>) {
		for (const aid of g.account_ids || []) {
			groupMap.set(aid, g.name);
		}
	}

	const bios = ((accounts || []) as Array<Record<string, unknown>>).map(
		(a) => ({
			username: a.username,
			bio: a.biography || null,
			bio_length: ((a.biography as string) || "").length,
			followers: a.followers_count,
			group: groupMap.get(a.id as string) || null,
			status: a.is_retired
				? "retired"
				: a.needs_reauth
					? "needs_reauth"
					: a.is_shadowbanned
						? "shadowbanned"
						: a.is_active
							? "active"
							: "inactive",
		}),
	);

	return apiSuccess(res, { accounts: bios, count: bios.length });
}

export async function handleBulkSetContentStrategy(
	req: VercelRequest,
	res: VercelResponse,
	userId: string,
) {
	const { strategies } = req.body;
	if (!Array.isArray(strategies) || strategies.length === 0)
		return apiError(res, 400, "strategies array is required");
	if (strategies.length > 30)
		return apiError(res, 400, "Max 30 groups per call");

	const results: Array<{ groupId: string; ok: boolean; error?: string | undefined }> = [];

	for (const entry of strategies) {
		const {
			groupId,
			toneNotes,
			pillars,
			weeklyTarget,
			topicsToAvoid,
			ctaRotation,
			competitorIds,
		} = entry as Record<string, unknown>;
		if (!groupId) {
			results.push({ groupId: "unknown", ok: false, error: "missing groupId" });
			continue;
		}

		// Verify ownership
		const { data: existing } = await db()
			.from("account_groups")
			.select("id, content_strategy")
			.eq("id", groupId)
			.eq("user_id", userId)
			.maybeSingle();
		if (!existing) {
			results.push({
				groupId: groupId as string,
				ok: false,
				error: "not found or not authorized",
			});
			continue;
		}

		const existingStrategy =
			(existing.content_strategy as Record<string, unknown>) || {};
		const merged: Record<string, unknown> = { ...existingStrategy };
		if (toneNotes !== undefined) merged.tone_notes = toneNotes;
		if (pillars !== undefined) merged.pillars = pillars;
		if (weeklyTarget !== undefined) merged.weekly_target = weeklyTarget;
		if (topicsToAvoid !== undefined) merged.topics_to_avoid = topicsToAvoid;
		if (ctaRotation !== undefined) merged.cta_rotation = ctaRotation;
		if (competitorIds !== undefined) merged.competitor_ids = competitorIds;

		const { error } = await db()
			.from("account_groups")
			.update({ content_strategy: merged })
			.eq("id", groupId)
			.eq("user_id", userId);

		results.push({
			groupId: groupId as string,
			ok: !error,
			error: error?.message,
		});
	}

	return apiSuccess(res, {
		results,
		updated: results.filter((r) => r.ok).length,
		failed: results.filter((r) => !r.ok).length,
	});
}

export async function handleCompetitorPostsSample(
	req: VercelRequest,
	res: VercelResponse,
	userId: string,
) {
	const { competitorCount, postsPerCompetitor } = req.body;
	const maxCompetitors = Math.min(
		Math.max(Number(competitorCount) || 10, 1),
		30,
	);
	const maxPosts = Math.min(Math.max(Number(postsPerCompetitor) || 5, 1), 20);

	// Get all human-verified competitors
	const { data: competitors, error: compErr } = await db()
		.from("competitors")
		.select("id, username, platform, follower_count")
		.eq("user_id", userId)
		.eq("human_verified", true)
		.order("follower_count", { ascending: false });

	if (compErr) return apiError(res, 500, "Failed to fetch competitors");
	if (!competitors || competitors.length === 0)
		return apiSuccess(res, {
			competitors: [],
			message: "No human-verified competitors found",
		});

	// Randomly sample competitors
	const shuffled = (competitors as Array<Record<string, unknown>>).sort(
		() => Math.random() - 0.5,
	);
	const sampled = shuffled.slice(0, maxCompetitors);

	const competitorIds = sampled.map((c) => c.id) as string[];

	// Fetch recent posts for sampled competitors
	const { data: posts, error: postsErr } = await db()
		.from("competitor_top_posts")
		.select(
			"competitor_id, content, engagement_score, reply_count, view_count, repost_count, created_at, scraped_at, metric_quality, hook_type, topic_label, emotional_frame, cta_style, content_length_bucket",
		)
		.in("competitor_id", competitorIds)
		.not("content", "is", null)
		.order("scraped_at", { ascending: false, nullsFirst: false })
		.limit(maxCompetitors * maxPosts * 3); // Over-fetch to allow per-competitor slicing

	if (postsErr) {
		logger.error("[contentHandlers] Failed to fetch competitor posts sample", { error: String(postsErr) });
		return apiError(res, 500, "Failed to fetch competitor posts");
	}

	// Group by competitor and take top N per competitor
	const byCompetitor = new Map<string, Array<Record<string, unknown>>>();
	for (const p of (posts || []) as Array<Record<string, unknown>>) {
		const cid = p.competitor_id as string;
		if (!byCompetitor.has(cid)) byCompetitor.set(cid, []);
		const arr = byCompetitor.get(cid) ?? [];
		if (arr.length < maxPosts) arr.push(p);
	}

	const result = sampled.map((c) => ({
		username: c.username,
		platform: c.platform,
		followers: c.follower_count,
		posts: (byCompetitor.get(c.id as string) || []).map((p) => ({
			content: p.content,
			engagement_score: p.engagement_score,
			metric_quality: p.metric_quality,
			hook_type: p.hook_type,
			topic_label: p.topic_label,
			emotional_frame: p.emotional_frame,
			cta_style: p.cta_style,
			content_length_bucket: p.content_length_bucket,
			replies: p.reply_count,
			views: p.view_count,
			reposts: p.repost_count,
		})),
	}));

	return apiSuccess(res, {
		competitors: result,
		competitorCount: result.length,
		totalPosts: result.reduce((s, c) => s + c.posts.length, 0),
	});
}

// ============================================================================
// A/B Variant Management
// ============================================================================

type QueueOwnershipRow = {
	id: string;
	workspace_id: string | null;
	group_id: string | null;
	account_id: string | null;
};

async function authorizeQueueRow(
	res: VercelResponse,
	row: QueueOwnershipRow,
	userId: string,
): Promise<boolean> {
	if (row.workspace_id) {
		return verifyWorkspaceAccess(userId, row.workspace_id, res);
	}

	if (row.group_id) {
		const { data: group, error } = await db()
			.from("account_groups")
			.select("id")
			.eq("id", row.group_id)
			.eq("user_id", userId)
			.maybeSingle();

		if (error) {
			logger.error("[auto-post] Failed to verify queue group ownership", {
				error: String(error),
				queueItemId: row.id,
			});
			apiError(res, 500, "Failed to verify queue item");
			return false;
		}

		if (!group) {
			apiError(res, 404, "Queue item not found");
			return false;
		}

		return true;
	}

	if (row.account_id) {
		return !!(await verifyAnyAccountOwnership(res, row.account_id, userId));
	}

	apiError(res, 404, "Queue item not found");
	return false;
}

export async function handleGetVariants(
	req: VercelRequest,
	res: VercelResponse,
	userId: string,
) {
	const postId = (req.query.postId as string) || (req.body?.postId as string);
	if (!postId) return apiError(res, 400, "postId is required");

	// Fetch and authorize the original post before exposing related variants.
	const { data: original } = await db()
		.from("auto_post_queue")
		.select(
			"id, content, status, predicted_viral_score, content_type, metadata, views_at_24h, engagement_rate, workspace_id, group_id, account_id",
		)
		.eq("id", postId)
		.maybeSingle();

	if (!original) return apiError(res, 404, "Post not found");
	if (!(await authorizeQueueRow(res, original as QueueOwnershipRow, userId)))
		return;

	let variantsQuery = db()
		.from("auto_post_queue")
		.select(
			"id, content, status, predicted_viral_score, content_type, metadata, created_at, workspace_id, group_id, account_id",
		)
		.eq("source_type", "ai_variant")
		.filter("metadata->>variant_of", "eq", postId);

	variantsQuery = original.workspace_id
		? variantsQuery.eq("workspace_id", original.workspace_id)
		: variantsQuery.is("workspace_id", null);
	variantsQuery = original.group_id
		? variantsQuery.eq("group_id", original.group_id)
		: variantsQuery.is("group_id", null);
	variantsQuery = original.account_id
		? variantsQuery.eq("account_id", original.account_id)
		: variantsQuery.is("account_id", null);

	const { data: variants, error } = await variantsQuery
		.order("created_at", { ascending: false })
		.limit(10);

	if (error) {
		logger.error("[auto-post] Failed to fetch variants", {
			error: error.message,
			postId,
		});
		return apiError(res, 500, "Failed to fetch variants");
	}

	const stripOwnership = ({
		workspace_id: _workspaceId,
		group_id: _groupId,
		account_id: _accountId,
		...item
	}: Record<string, unknown>) => item;

	return apiSuccess(res, {
		original: stripOwnership(original as Record<string, unknown>),
		variants: (variants || []).map((variant) =>
			stripOwnership(variant as Record<string, unknown>),
		),
		variantCount: variants?.length || 0,
	});
}

export async function handlePromoteVariant(
	req: VercelRequest,
	res: VercelResponse,
	userId: string,
) {
	const { variantId, scheduledFor } = req.body || {};
	if (!variantId) return apiError(res, 400, "variantId is required");

	// Verify the variant exists and is a draft
	const { data: variant, error: fetchErr } = await db()
		.from("auto_post_queue")
		.select("id, content, status, source_type, workspace_id, group_id, account_id")
		.eq("id", variantId)
		.maybeSingle();

	if (fetchErr || !variant) return apiError(res, 404, "Variant not found");
	if (variant.status !== "draft")
		return apiError(
			res,
			400,
			`Variant status is '${variant.status}', expected 'draft'`,
		);
	if (variant.source_type !== "ai_variant")
		return apiError(res, 400, "Not an A/B variant");

	if (!(await authorizeQueueRow(res, variant as QueueOwnershipRow, userId)))
		return;

	const scheduleTime =
		scheduledFor || new Date(Date.now() + 30 * 60 * 1000).toISOString();

	await retryQueueItem(variantId, scheduleTime, {
		workspaceId: variant.workspace_id,
	});

	return apiSuccess(res, {
		promoted: true,
		variantId,
		scheduledFor: scheduleTime,
		content: variant.content,
	});
}
