/**
 * Bio-link funnel — clicks → conversions per smart_link.
 *
 * GET /api/analytics?action=bio-link-funnel&periodDays=30
 *
 * Mockup: new-widgets-2026.html #5 ("Bio-link funnel"). Reads existing
 * `smart_links`, `smart_link_clicks`, `smart_link_conversions` tables (all
 * already populated server-side by api/go/[code].ts and api/go/convert.ts).
 *
 * Returns per-link totals (clicks, by source_platform, conversions, est
 * revenue) plus a fleet-wide rollup. Frontend renders the funnel: clicks
 * total → device split → conversion count + revenue.
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";
import { apiError, apiSuccess } from "../../apiResponse.js";
import { withAuth } from "../../middleware.js";
import { getSupabase } from "../../supabase.js";
import { parseQueryOrError } from "../../validation.js";
import { z } from "../../zodCompat.js";

const QuerySchema = z.object({
	accountId: z.string().optional(),
	accountIds: z.string().optional(),
	platform: z.string().optional(),
	periodDays: z.coerce.number().int().min(1).max(90).optional().default(30),
	limit: z.coerce.number().int().min(1).max(50).optional().default(10),
});

// biome-ignore lint/suspicious/noExplicitAny: smart_link tables not in generated types
const db = (): any => getSupabase();

interface LinkRollup {
	smartLinkId: string;
	code: string;
	title: string | null;
	targetUrl: string;
	estConversionRate: number;
	estConversionValue: number;
	clicks: number;
	clicksBySource: Record<string, number>;
	deepLinkAttempts: number;
	interstitialViews: number;
	destinationClicks: number;
	directRedirects: number;
	dropoffRate: number;
	conversions: number;
	conversionValue: number;
}

export default withAuth(
	async (req: VercelRequest, res: VercelResponse, user) => {
		if (req.method !== "GET") return apiError(res, 405, "Method not allowed");

		const parsed = parseQueryOrError(res, QuerySchema, req.query);
		if (!parsed) return;
		const { accountId, accountIds, platform, periodDays, limit } = parsed;

		const cutoff = new Date(Date.now() - periodDays * 86_400_000).toISOString();

		// 1. The user's smart_links — drives ownership scoping.
		let linkQuery = db()
			.from("smart_links")
			.select(
				"id, code, title, target_url, est_conversion_rate, est_conversion_value, is_active, post_id",
			)
			.eq("user_id", user.id);
		const targetIds = accountIds
			? accountIds
					.split(",")
					.map((id) => id.trim())
					.filter(Boolean)
			: accountId && accountId !== "ALL"
				? [accountId]
				: [];
		if (targetIds.length > 0) {
			let postQuery = db()
				.from("posts")
				.select("id")
				.eq("user_id", user.id)
				.eq("status", "published");
			if (platform === "instagram") {
				postQuery = postQuery.in("instagram_account_id", targetIds);
			} else if (platform === "threads") {
				postQuery = postQuery.in("account_id", targetIds);
			} else {
				postQuery = postQuery.or(
					`account_id.in.(${targetIds.join(",")}),instagram_account_id.in.(${targetIds.join(",")})`,
				);
			}
			const { data: scopedPosts, error: scopedPostsErr } = await postQuery;
			if (scopedPostsErr) {
				return apiError(res, 500, "Failed to resolve scoped smart links", {
					details: scopedPostsErr.message,
				});
			}
			const postIds = ((scopedPosts || []) as Array<{ id: string }>).map(
				(post) => post.id,
			);
			if (postIds.length === 0) {
				return apiSuccess(res, {
					links: [],
					totals: emptyTotals(),
					periodDays,
					activeLinkCount: 0,
					totalLinkCount: 0,
				});
			}
			linkQuery = linkQuery.in("post_id", postIds);
		}

		const { data: linkRows, error: linksErr } = await linkQuery;

		if (linksErr) {
			return apiError(res, 500, "Failed to load smart links", {
				details: linksErr.message,
			});
		}
		const links = (linkRows || []) as Array<{
			id: string;
			code: string;
			title: string | null;
			target_url: string;
			est_conversion_rate: number | null;
			est_conversion_value: number | null;
			is_active: boolean;
			post_id: string | null;
		}>;

		if (links.length === 0) {
			return apiSuccess(res, {
				links: [],
				totals: emptyTotals(),
				periodDays,
			});
		}

		const linkIds = links.map((l) => l.id);
		const byId = new Map<string, LinkRollup>();
		for (const l of links) {
			byId.set(l.id, {
				smartLinkId: l.id,
				code: l.code,
				title: l.title,
				targetUrl: l.target_url,
				estConversionRate: Number(l.est_conversion_rate) || 0,
				estConversionValue: Number(l.est_conversion_value) || 0,
				clicks: 0,
				clicksBySource: {},
				deepLinkAttempts: 0,
				interstitialViews: 0,
				destinationClicks: 0,
				directRedirects: 0,
				dropoffRate: 0,
				conversions: 0,
				conversionValue: 0,
			});
		}

		// 2. Clicks in window.
		const { data: clickRows } = await db()
			.from("smart_link_clicks")
			.select("smart_link_id, source_platform, deep_link_attempted, event_name")
			.in("smart_link_id", linkIds)
			.gte("clicked_at", cutoff);

		for (const c of (clickRows || []) as Array<{
			smart_link_id: string;
			source_platform: string | null;
			deep_link_attempted: boolean | null;
			event_name: string | null;
		}>) {
			const r = byId.get(c.smart_link_id);
			if (!r) continue;
			const eventName = c.event_name;
			if (eventName === "interstitial_view") {
				r.interstitialViews += 1;
				continue;
			}
			if (eventName === "destination_click") r.destinationClicks += 1;
			else if (eventName === "redirect") r.directRedirects += 1;
			else if (eventName !== "click" && eventName !== null) continue;
			r.clicks += 1;
			const src = (c.source_platform ?? "other").toLowerCase();
			r.clicksBySource[src] = (r.clicksBySource[src] ?? 0) + 1;
			if (c.deep_link_attempted) r.deepLinkAttempts += 1;
		}

		// 3. Conversions in window.
		const { data: convRows } = await db()
			.from("smart_link_conversions")
			.select("smart_link_id, conversion_value")
			.in("smart_link_id", linkIds)
			.gte("converted_at", cutoff);

		for (const cv of (convRows || []) as Array<{
			smart_link_id: string;
			conversion_value: number | null;
		}>) {
			const r = byId.get(cv.smart_link_id);
			if (!r) continue;
			r.conversions += 1;
			r.conversionValue += Number(cv.conversion_value) || 0;
		}

		// 4. Sort + cap.
		const sorted = Array.from(byId.values())
			.filter((r) => r.clicks > 0 || r.conversions > 0)
			.sort((a, b) => b.clicks - a.clicks)
			.slice(0, limit);

		// 5. Fleet rollup across all the user's links (not just the top N).
		const totals = emptyTotals();
		for (const r of byId.values()) {
			r.dropoffRate =
				r.interstitialViews > 0
					? Math.max(
							0,
							(r.interstitialViews - r.destinationClicks) / r.interstitialViews,
						)
					: 0;
			totals.clicks += r.clicks;
			totals.conversions += r.conversions;
			totals.conversionValue += r.conversionValue;
			totals.deepLinkAttempts += r.deepLinkAttempts;
			totals.interstitialViews += r.interstitialViews;
			totals.destinationClicks += r.destinationClicks;
			totals.directRedirects += r.directRedirects;
			for (const [src, count] of Object.entries(r.clicksBySource)) {
				totals.clicksBySource[src] = (totals.clicksBySource[src] ?? 0) + count;
			}
		}
		totals.dropoffRate =
			totals.interstitialViews > 0
				? Math.max(
						0,
						(totals.interstitialViews - totals.destinationClicks) /
							totals.interstitialViews,
					)
				: 0;
		// Estimated revenue — when a smart_link has estimate fields set, use
		// clicks × est_conversion_rate × est_conversion_value. The actual
		// conversionValue from postbacks (smart_link_conversions) is the truth
		// when present; estimate is only a fallback for links without webhook.
		for (const r of byId.values()) {
			if (
				r.conversionValue === 0 &&
				r.clicks > 0 &&
				r.estConversionRate > 0 &&
				r.estConversionValue > 0
			) {
				totals.estimatedRevenue +=
					r.clicks * r.estConversionRate * r.estConversionValue;
			}
		}

		return apiSuccess(res, {
			links: sorted,
			totals,
			periodDays,
			activeLinkCount: links.filter((l) => l.is_active).length,
			totalLinkCount: links.length,
		});
	},
);

function emptyTotals() {
	return {
		clicks: 0,
		clicksBySource: {} as Record<string, number>,
		deepLinkAttempts: 0,
		interstitialViews: 0,
		destinationClicks: 0,
		directRedirects: 0,
		dropoffRate: 0,
		conversions: 0,
		conversionValue: 0,
		estimatedRevenue: 0,
	};
}
