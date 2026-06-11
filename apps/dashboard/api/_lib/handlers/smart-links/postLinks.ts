/**
 * List smart links for a post, with conversion counts.
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";
import { apiError, apiSuccess } from "../../apiResponse.js";
import { logger } from "../../logger.js";
import { db, fetchAllSmartLinkRows } from "./shared.js";

export async function handlePostLinks(
	req: VercelRequest,
	res: VercelResponse,
	userId: string,
) {
	const postId = (req.query.postId || req.body?.postId) as string;
	if (!postId) return apiError(res, 400, "postId is required");

	const { data: post, error: postError } = await db()
		.from("posts")
		.select("id")
		.eq("id", postId)
		.eq("user_id", userId)
		.maybeSingle();

	if (postError) {
		logger.error("[smart-links] Post ownership check error", {
			error: String(postError),
		});
		return apiError(res, 500, "Failed to verify post");
	}
	if (!post) return apiError(res, 404, "Post not found");

	const { data: links, error } = await db()
		.from("smart_links")
		.select("*")
		.eq("user_id", userId)
		.eq("post_id", postId)
		.order("created_at", { ascending: false })
		.limit(500);

	if (error) {
		logger.error("[smart-links] Post links error", { error: String(error) });
		return apiError(res, 500, "Failed to fetch post links");
	}

	const linkRows = (links || []) as Record<string, unknown>[];
	const linkIds = linkRows
		.map((link) => link.id)
		.filter((id): id is string => typeof id === "string");

	const conversionStats = new Map<
		string,
		{ conversion_count: number; total_revenue: number }
	>();
	if (linkIds.length > 0) {
		let convs: Record<string, unknown>[];
		try {
			convs = await fetchAllSmartLinkRows({
				table: "smart_link_conversions",
				select: "smart_link_id, conversion_value, converted_at",
				linkIds,
				dateColumn: "converted_at",
			});
		} catch (error) {
			logger.error("[smart-links] Post link conversions error", {
				error: String(error),
			});
			return apiError(res, 500, "Failed to fetch link conversions");
		}

		for (const conversion of convs) {
			const linkId = conversion.smart_link_id;
			if (typeof linkId !== "string") continue;
			const existing = conversionStats.get(linkId) || {
				conversion_count: 0,
				total_revenue: 0,
			};
			existing.conversion_count++;
			existing.total_revenue +=
				parseFloat(String(conversion.conversion_value ?? "")) || 0;
			conversionStats.set(linkId, existing);
		}
	}

	const enriched = linkRows.map((link) => {
		const stats = conversionStats.get(link.id as string) || {
			conversion_count: 0,
			total_revenue: 0,
		};
		return { ...link, ...stats };
	});

	return apiSuccess(res, { links: enriched });
}
