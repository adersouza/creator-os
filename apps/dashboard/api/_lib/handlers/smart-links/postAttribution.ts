/**
 * Post attribution — top posts by smart link clicks/conversions.
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";
import { apiError, apiSuccess } from "../../apiResponse.js";
import { logger } from "../../logger.js";
import { db, fetchAllSmartLinkRows } from "./shared.js";

export async function handlePostAttribution(
	req: VercelRequest,
	res: VercelResponse,
	userId: string,
) {
	const requestedDays = parseInt(req.query.days as string, 10) || 30;
	const days = Math.min(Math.max(requestedDays, 1), 90);
	const since = new Date(Date.now() - days * 86400000).toISOString();

	// Get user's smart links that are attached to posts
	const { data: userLinks, error: linksErr } = await db()
		.from("smart_links")
		.select("id, post_id")
		.eq("user_id", userId)
		.not("post_id", "is", null)
		.limit(1000);

	if (linksErr) {
		logger.error("[smart-links] Post attribution links error", {
			error: String(linksErr),
		});
		return apiError(res, 500, "Failed to fetch smart links");
	}

	if (!userLinks || userLinks.length === 0) {
		return apiSuccess(res, { posts: [] });
	}

	const linkIds = userLinks.map((l: Record<string, unknown>) => l.id as string);
	const linkToPost = new Map<string, string>();
	for (const l of userLinks as Record<string, unknown>[]) {
		linkToPost.set(l.id as string, l.post_id as string);
	}

	let clicks: Record<string, unknown>[];
	let conversions: Record<string, unknown>[];
	try {
		[clicks, conversions] = await Promise.all([
			fetchAllSmartLinkRows({
				table: "smart_link_clicks",
				select: "smart_link_id",
				linkIds,
				dateColumn: "clicked_at",
				since,
				clickEventsOnly: true,
			}),
			fetchAllSmartLinkRows({
				table: "smart_link_conversions",
				select: "smart_link_id, conversion_value",
				linkIds,
				dateColumn: "converted_at",
				since,
			}),
		]);
	} catch (err) {
		logger.error("[smart-links] Post attribution event query error", {
			error: String(err),
		});
		return apiError(res, 500, "Failed to fetch smart link attribution");
	}

	// Aggregate by post_id
	const postStats = new Map<
		string,
		{ clicks: number; conversions: number; revenue: number }
	>();

	for (const c of clicks) {
		const postId = linkToPost.get(c.smart_link_id as string);
		if (!postId) continue;
		const entry = postStats.get(postId) || {
			clicks: 0,
			conversions: 0,
			revenue: 0,
		};
		entry.clicks++;
		postStats.set(postId, entry);
	}

	for (const c of conversions) {
		const postId = linkToPost.get(c.smart_link_id as string);
		if (!postId) continue;
		const entry = postStats.get(postId) || {
			clicks: 0,
			conversions: 0,
			revenue: 0,
		};
		entry.conversions++;
		entry.revenue += parseFloat(c.conversion_value as string) || 0;
		postStats.set(postId, entry);
	}

	// Sort by clicks descending, take top 10
	const topPostIds = Array.from(postStats.entries())
		.sort((a, b) => b[1].clicks - a[1].clicks)
		.slice(0, 10)
		.map(([postId]) => postId);

	if (topPostIds.length === 0) {
		return apiSuccess(res, { posts: [] });
	}

	// Fetch post content
	const { data: postRows } = await db()
		.from("posts")
		.select("id, content")
		.in("id", topPostIds)
		.eq("user_id", userId)
		.limit(10);

	const postContentMap = new Map<string, string>();
	for (const p of (postRows as Record<string, unknown>[] | null) || []) {
		postContentMap.set(p.id as string, (p.content as string) || "");
	}

	const posts = topPostIds.map((postId) => {
		const stats = postStats.get(postId) ?? {
			clicks: 0,
			conversions: 0,
			revenue: 0,
		};
		const content = postContentMap.get(postId) || "";
		return {
			post_id: postId,
			content_preview: content.substring(0, 100),
			clicks: stats.clicks,
			conversions: stats.conversions,
			revenue: stats.revenue,
			conv_rate: stats.clicks > 0 ? stats.conversions / stats.clicks : 0,
		};
	});

	return apiSuccess(res, { posts });
}
