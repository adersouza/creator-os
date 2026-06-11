import type { VercelRequest, VercelResponse } from "@vercel/node";
import { apiError, apiSuccess } from "../../apiResponse.js";
import { getSupabase } from "../../supabase.js";

export async function handleGetAnalytics(
	req: VercelRequest,
	res: VercelResponse,
	userId: string,
) {
	const supabase = getSupabase();
	const pageId = req.query.pageId as string;
	const days = parseInt(req.query.days as string, 10) || 30;

	if (!pageId) return apiError(res, 400, "pageId required");

	// Verify ownership
	const { data: page } = await supabase
		.from("link_pages")
		.select("id, view_count")
		.eq("id", pageId)
		.eq("user_id", userId)
		.maybeSingle();

	if (!page) return apiError(res, 404, "Page not found");

	const since = new Date(Date.now() - days * 24 * 60 * 60 * 1000).toISOString();
	const pageSize = 1000;

	let totalClicks = 0;
	let crawlerClicks = 0;
	const bySource: Record<string, number> = {};
	const byDevice: Record<string, number> = {};

	for (let offset = 0; ; offset += pageSize) {
		const { data: clicks, error } = await supabase
			.from("link_clicks")
			.select("source_app, device_type, is_crawler")
			.eq("page_id", pageId)
			.gte("clicked_at", since)
			.range(offset, offset + pageSize - 1);

		if (error) return apiError(res, 500, "Failed to load link analytics");
		if (!clicks || clicks.length === 0) break;

		for (const click of clicks) {
			if (click.is_crawler) {
				crawlerClicks++;
				continue;
			}

			totalClicks++;
			const src = click.source_app || "direct";
			const dev = click.device_type || "unknown";
			bySource[src] = (bySource[src] || 0) + 1;
			byDevice[dev] = (byDevice[dev] || 0) + 1;
		}

		if (clicks.length < pageSize) break;
	}

	return apiSuccess(res, {
		pageViews: page.view_count || 0,
		totalClicks,
		crawlerClicks,
		bySource,
		byDevice,
		period: `${days} days`,
	});
}
