/**
 * Revenue trend — 60-day trend with current vs previous period comparison.
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";
import { apiError, apiSuccess } from "../../apiResponse.js";
import { logger } from "../../logger.js";
import { db, fetchAllSmartLinkRows } from "./shared.js";

export async function handleRevenueTrend(
	_req: VercelRequest,
	res: VercelResponse,
	userId: string,
) {
	const now = Date.now();
	const sixtyDaysAgo = new Date(now - 60 * 86400000).toISOString();
	const thirtyDaysAgo = new Date(now - 30 * 86400000).toISOString();

	// Get all user's smart link IDs
	const { data: userLinks, error: linksErr } = await db()
		.from("smart_links")
		.select("id, title, code")
		.eq("user_id", userId)
		.limit(1000);

	if (linksErr) {
		logger.error("[smart-links] Revenue trend links error", {
			error: String(linksErr),
		});
		return apiError(res, 500, "Failed to fetch smart links");
	}

	if (!userLinks || userLinks.length === 0) {
		return apiSuccess(res, {
			trend: [],
			topLinks: [],
			previousPeriod: { clicks: 0, conversions: 0, revenue: 0 },
		});
	}

	const linkIds = userLinks.map((l: Record<string, unknown>) => l.id as string);

	let clicks: Record<string, unknown>[];
	let conversions: Record<string, unknown>[];
	try {
		[clicks, conversions] = await Promise.all([
			fetchAllSmartLinkRows({
				table: "smart_link_clicks",
				select: "smart_link_id, clicked_at",
				linkIds,
				dateColumn: "clicked_at",
				since: sixtyDaysAgo,
				clickEventsOnly: true,
			}),
			fetchAllSmartLinkRows({
				table: "smart_link_conversions",
				select: "smart_link_id, converted_at, conversion_value",
				linkIds,
				dateColumn: "converted_at",
				since: sixtyDaysAgo,
			}),
		]);
	} catch (error) {
		logger.error("[smart-links] Revenue trend event query error", {
			error: String(error),
		});
		return apiError(res, 500, "Failed to fetch revenue trend");
	}

	// Build daily trend (60 days)
	const dailyMap = new Map<string, { clicks: number; conversions: number }>();
	for (const c of clicks) {
		const day = (c.clicked_at as string | undefined)?.split("T")[0];
		if (!day) continue;
		const entry = dailyMap.get(day) || { clicks: 0, conversions: 0 };
		entry.clicks++;
		dailyMap.set(day, entry);
	}
	for (const c of conversions) {
		const day = (c.converted_at as string | undefined)?.split("T")[0];
		if (!day) continue;
		const entry = dailyMap.get(day) || { clicks: 0, conversions: 0 };
		entry.conversions++;
		dailyMap.set(day, entry);
	}

	const trend = Array.from(dailyMap.entries())
		.map(([date, data]) => ({
			date,
			clicks: data.clicks,
			conversions: data.conversions,
		}))
		.sort((a, b) => a.date.localeCompare(b.date));

	// Top 3 links by revenue
	const linkRevenueMap = new Map<string, number>();
	for (const c of conversions) {
		const id = c.smart_link_id as string;
		linkRevenueMap.set(
			id,
			(linkRevenueMap.get(id) || 0) +
				(parseFloat(c.conversion_value as string) || 0),
		);
	}
	const linkLookup = new Map(
		userLinks.map((l: Record<string, unknown>) => [
			l.id,
			(l.title as string) || (l.code as string),
		]),
	);
	const topLinks = Array.from(linkRevenueMap.entries())
		.map(([id, revenue]) => ({ name: linkLookup.get(id) || id, revenue }))
		.sort((a, b) => b.revenue - a.revenue)
		.slice(0, 3);

	// Previous period (days 31-60)
	const previousClicks = clicks.filter(
		(c) => (c.clicked_at as string) < thirtyDaysAgo,
	).length;
	const prevConversions = conversions.filter(
		(c) => (c.converted_at as string) < thirtyDaysAgo,
	);
	const previousConvCount = prevConversions.length;
	const previousRevenue = prevConversions.reduce(
		(sum: number, c: Record<string, unknown>) =>
			sum + (parseFloat(c.conversion_value as string) || 0),
		0,
	);

	return apiSuccess(res, {
		trend,
		topLinks,
		previousPeriod: {
			clicks: previousClicks,
			conversions: previousConvCount,
			revenue: previousRevenue,
		},
	});
}
