/**
 * UnifiedLinkService - Attribution Intelligence for Links & Collabs
 *
 * Aggregates data from Link-in-Bio pages and Smart Links to provide
 * true ROI and business value metrics.
 */

import { getSupabaseAny, logger } from "./api/shared.js";

interface UnifiedLinkRoiRow {
	page_views?: number | null | undefined;
	total_redirect_clicks?: number | null | undefined;
	estimated_revenue?: number | null | undefined;
}

interface SmartLinkClickRow {
	click_count?: number | null | undefined;
	threads_redirect_url?: string | null | undefined;
	ig_redirect_url?: string | null | undefined;
}

export interface LinkROIMetrics {
	totalClicks: number;
	totalRevenue: number;
	avgEPC: number; // Earnings Per Click
	platformSplit: {
		threads: number;
		instagram: number;
	};
	funnel: {
		impressions: number;
		clicks: number;
		conversions: number;
	};
}

export const unifiedLinkService = {
	/**
	 * Fetch consolidated ROI metrics for the Revenue Ribbon
	 */
	async getROISummary(userId: string): Promise<LinkROIMetrics> {
		const db = getSupabaseAny();

		try {
			// 1. Fetch raw data from our new Unified View
			const { data: roiData, error } = await db
				.from("unified_link_roi")
				.select("*")
				.eq("user_id", userId);

			if (error) throw error;

			// 2. Fetch platform-specific click data from Smart Links
			const { data: platformData } = await db
				.from("smart_links")
				.select("click_count, threads_redirect_url, ig_redirect_url")
				.eq("user_id", userId);

			// 3. Aggregate metrics
			const totalViews =
				roiData?.reduce(
					(sum: number, item: UnifiedLinkRoiRow) =>
						sum + (item.page_views || 0),
					0,
				) || 0;
			const totalClicks =
				roiData?.reduce(
					(sum: number, item: UnifiedLinkRoiRow) =>
						sum + (item.total_redirect_clicks || 0),
					0,
				) || 0;
			const totalRevenue =
				roiData?.reduce(
					(sum: number, item: UnifiedLinkRoiRow) =>
						sum + (item.estimated_revenue || 0),
					0,
				) || 0;

			// Platform split logic (Simplified attribution)
			let threadsClicks = 0;
			let igClicks = 0;
			platformData?.forEach((link: SmartLinkClickRow) => {
				if (link.threads_redirect_url)
					threadsClicks += (link.click_count || 0) * 0.4; // Weighted estimation
				if (link.ig_redirect_url) igClicks += (link.click_count || 0) * 0.6;
			});

			return {
				totalClicks,
				totalRevenue,
				avgEPC: totalClicks > 0 ? totalRevenue / totalClicks : 0,
				platformSplit: {
					threads: threadsClicks,
					instagram: igClicks,
				},
				funnel: {
					impressions: totalViews,
					clicks: totalClicks,
					conversions: Math.round(totalClicks * 0.03), // Estimated 3% conversion floor
				},
			};
		} catch (err) {
			logger.error("[UnifiedLinkService] Failed to fetch ROI metrics", err);
			return this.getFallbackMetrics();
		}
	},

	async createUnifiedLink(params: {
		userId: string;
		workspaceId: string | null;
		name: string;
		type: string;
		sourceId: string;
	}): Promise<void> {
		const db = getSupabaseAny();
		const { error } = await db.from("unified_links").insert({
			user_id: params.userId,
			workspace_id: params.workspaceId,
			name: params.name,
			type: params.type,
			source_id: params.sourceId,
		});
		if (error) throw error;
	},

	getFallbackMetrics(): LinkROIMetrics {
		return {
			totalClicks: 0,
			totalRevenue: 0,
			avgEPC: 0,
			platformSplit: { threads: 0, instagram: 0 },
			funnel: { impressions: 0, clicks: 0, conversions: 0 },
		};
	},
};
