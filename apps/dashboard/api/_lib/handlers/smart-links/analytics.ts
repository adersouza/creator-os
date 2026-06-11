/**
 * Smart link analytics — clicks, platforms, devices, countries, revenue.
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";
import { apiError, apiSuccess } from "../../apiResponse.js";
import { logger } from "../../logger.js";
import { getSupabaseAny } from "../../supabase.js";
import { AnalyticsQuerySchema, db } from "./shared.js";

export async function handleAnalytics(
	req: VercelRequest,
	res: VercelResponse,
	userId: string,
) {
	const parsed = AnalyticsQuerySchema.safeParse(req.query);
	if (!parsed.success) {
		return apiError(
			res,
			400,
			`Invalid input: ${parsed.error.issues[0]?.message}`,
		);
	}
	const { linkId, range } = parsed.data;

	// Verify ownership
	const { data: link } = await db()
		.from("smart_links")
		.select("id, click_count")
		.eq("id", linkId)
		.eq("user_id", userId)
		.maybeSingle();

	if (!link) return apiError(res, 404, "Smart link not found");

	// Parse range
	const days = range === "30d" ? 30 : range === "90d" ? 90 : 7;
	const since = new Date(Date.now() - days * 86400000).toISOString();

	// Server-side aggregation via RPC — no row limits, no silent truncation.
	// Falls back to empty data if RPC isn't deployed yet (e.g. local dev).
	const { data: agg, error: rpcErr } = await getSupabaseAny().rpc(
		"smart_link_analytics",
		{ p_link_id: linkId, p_since: since, p_user_id: userId },
	);

	if (rpcErr) {
		logger.error("[smart-links] Analytics RPC failed", {
			error: rpcErr.message,
		});
		return apiError(res, 500, "Failed to load analytics");
	}

	const clicksPerDay = agg?.clicks_by_day || [];
	const platforms = agg?.by_platform || [];
	const devices = agg?.by_device || [];
	const countries = agg?.by_country || [];
	const uniqueVisitorCount: number = agg?.unique_visitors ?? 0;
	const totalClicks: number = agg?.total_clicks ?? 0;
	const deepLinkAttempts: number = agg?.deep_link_attempts ?? 0;
	const actualConversions: number = agg?.conversions?.count ?? 0;
	const actualRevenue: number = agg?.conversions?.total_value ?? 0;

	const { data: eventRows, error: eventErr } = await getSupabaseAny()
		.from("smart_link_clicks")
		.select("event_name")
		.eq("smart_link_id", linkId)
		.gte("clicked_at", since);

	if (eventErr) {
		logger.error("[smart-links] Analytics event split failed", {
			error: eventErr.message,
		});
		return apiError(res, 500, "Failed to load analytics");
	}

	let interstitialViews = 0;
	let destinationClicks = 0;
	let directRedirects = 0;
	let legacyOutboundClicks = 0;
	for (const row of (eventRows || []) as Array<{ event_name: string | null }>) {
		if (row.event_name === "interstitial_view") interstitialViews += 1;
		else if (row.event_name === "destination_click") destinationClicks += 1;
		else if (row.event_name === "redirect") directRedirects += 1;
		else if (row.event_name === "click" || row.event_name == null)
			legacyOutboundClicks += 1;
	}
	if (typeof agg?.interstitial_views === "number") {
		interstitialViews = agg.interstitial_views;
	}
	if (typeof agg?.destination_clicks === "number") {
		destinationClicks = agg.destination_clicks;
	}
	if (typeof agg?.direct_redirects === "number") {
		directRedirects = agg.direct_redirects;
	}
	const eventRowCount = (eventRows || []).length;
	const outboundClicks =
		eventRowCount > 0 || destinationClicks > 0 || directRedirects > 0
			? destinationClicks + directRedirects + legacyOutboundClicks
			: totalClicks;
	const dropoffRate =
		interstitialViews > 0
			? Math.max(0, (interstitialViews - destinationClicks) / interstitialViews)
			: 0;

	// Fetch link's estimation fields for estimated revenue
	const { data: linkFull } = await db()
		.from("smart_links")
		.select("est_conversion_rate, est_conversion_value")
		.eq("id", linkId)
		.eq("user_id", userId)
		.maybeSingle();

	const estRate = parseFloat(String(linkFull?.est_conversion_rate ?? 0)) || 0;
	const estValue = parseFloat(String(linkFull?.est_conversion_value ?? 0)) || 0;
	const estimatedRevenue = outboundClicks * estRate * estValue;

	return apiSuccess(res, {
		total_clicks: link.click_count,
		period_clicks: outboundClicks,
		interstitial_views: interstitialViews,
		destination_clicks: destinationClicks,
		direct_redirects: directRedirects,
		dropoff_rate: dropoffRate,
		unique_visitors: uniqueVisitorCount,
		clicks_per_day: clicksPerDay,
		platforms,
		devices,
		countries,
		deep_link_ratio: {
			attempted: deepLinkAttempts,
			fallback: outboundClicks - deepLinkAttempts,
			total: outboundClicks,
		},
		revenue: {
			actual_conversions: actualConversions,
			actual_revenue: actualRevenue,
			estimated_revenue: estimatedRevenue,
		},
	});
}
