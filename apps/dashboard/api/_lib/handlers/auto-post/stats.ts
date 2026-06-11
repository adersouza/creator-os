/**
 * Auto-Post Stats API
 * GET /api/auto-post?action=stats&periodDays=7
 *
 * Returns KPI metrics, per-group breakdown, and content source distribution
 * for auto-posted content within the specified period.
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";
import { apiError, apiSuccess } from "../../apiResponse.js";
import { logger } from "../../logger.js";
import { getSupabase } from "../../supabase.js";

export default async function handleAutoPostStats(
	req: VercelRequest,
	res: VercelResponse,
	userId: string,
) {
	if (req.method !== "GET") {
		return apiError(res, 405, "Method not allowed");
	}

	const periodDays = Number(req.query.periodDays) || 7;
	const workspaceId = req.query.workspaceId as string | undefined;

	const db = getSupabase();
	const cutoff = new Date(Date.now() - periodDays * 86_400_000).toISOString();
	const prevCutoff = new Date(
		Date.now() - periodDays * 2 * 86_400_000,
	).toISOString();

	try {
		// Get workspace ID from auto_post_config (uses a different ID format than workspaces table)
		let wsId = workspaceId;
		if (!wsId) {
			const { data: config } = await db
				.from("auto_post_config")
				.select("workspace_id")
				.limit(1)
				.maybeSingle();
			wsId = config?.workspace_id;
		}

		if (!wsId) {
			return apiSuccess(res, { kpis: null, groups: [], sources: [] });
		}

		// ── KPIs: current period ──────────────────────────────────────────
		const { data: currentRows } = (await (db as ReturnType<typeof getSupabase>)
			.from("auto_post_queue")
			.select(
				"id, views_at_24h, engagement_rate, source_type, group_id, posted_at",
			)
			.eq("workspace_id", wsId)
			.eq("status", "published")
			// biome-ignore lint/suspicious/noExplicitAny: auto_post_queue columns not in generated Supabase types
			.gte("posted_at", cutoff)) as { data: any[] | null };

		const current = currentRows || [];

		// ── KPIs: previous period (for deltas) ───────────────────────────
		const { data: prevRows } = (await (db as ReturnType<typeof getSupabase>)
			.from("auto_post_queue")
			.select("id, views_at_24h, engagement_rate")
			.eq("workspace_id", wsId)
			.eq("status", "published")
			.gte("posted_at", prevCutoff)
			// biome-ignore lint/suspicious/noExplicitAny: auto_post_queue columns not in generated Supabase types
			.lt("posted_at", cutoff)) as { data: any[] | null };

		const prev = prevRows || [];

		// ── Compute KPIs ─────────────────────────────────────────────────
		const postsPublished = current.length;
		const totalViews = current.reduce(
			// biome-ignore lint/suspicious/noExplicitAny: reduce callback on untyped Supabase rows
			(s: number, r: any) => s + ((r.views_at_24h as number) || 0),
			0,
		);
		const avgER =
			current.length > 0
				? current.reduce(
						// biome-ignore lint/suspicious/noExplicitAny: reduce callback on untyped Supabase rows
						(s: number, r: any) => s + ((r.engagement_rate as number) || 0),
						0,
					) / current.length
				: 0;

		// Get reply counts from posts table for auto-posted content
		const { data: postRows } = (await (db as ReturnType<typeof getSupabase>)
			.from("posts")
			.select("replies_count")
			.eq("user_id", userId)
			.gte("published_at", cutoff)
			.eq("status", "published")
			// biome-ignore lint/suspicious/noExplicitAny: posts columns not fully in generated Supabase types
			.eq("source", "auto-poster")) as { data: any[] | null };

		const totalReplies = (postRows || []).reduce(
			// biome-ignore lint/suspicious/noExplicitAny: reduce callback on untyped Supabase rows
			(s: number, r: any) => s + ((r.replies_count as number) || 0),
			0,
		);

		// Previous period metrics for deltas
		const prevPosts = prev.length;
		const prevViews = prev.reduce(
			// biome-ignore lint/suspicious/noExplicitAny: reduce callback on untyped Supabase rows
			(s: number, r: any) => s + ((r.views_at_24h as number) || 0),
			0,
		);
		const prevAvgER =
			prev.length > 0
				? prev.reduce(
						// biome-ignore lint/suspicious/noExplicitAny: reduce callback on untyped Supabase rows
						(s: number, r: any) => s + ((r.engagement_rate as number) || 0),
						0,
					) / prev.length
				: 0;

		const computeDelta = (curr: number, previous: number): string => {
			if (previous <= 0 && curr === 0) return "0%";
			if (previous <= 0) return curr > 0 ? "New" : "0%";
			const pct = ((curr - previous) / previous) * 100;
			if (Math.abs(pct) < 0.1) return "0%";
			return `${pct >= 0 ? "+" : ""}${pct.toFixed(1)}%`;
		};

		// ── Per-group breakdown ──────────────────────────────────────────
		const { data: groups } = await db
			.from("account_groups")
			.select("id, name")
			.eq("user_id", userId);

		const groupMap = new Map(
			(groups || []).map((g: { id: string; name: string }) => [g.id, g.name]),
		);

		const groupStats = new Map<
			string,
			{
				name: string;
				posts: number;
				views: number;
				totalER: number;
				topViewPost: { content: string; views: number } | null;
			}
		>();

		for (const row of current) {
			const gid = row.group_id || "ungrouped";
			const existing = groupStats.get(gid) || {
				name: groupMap.get(gid) || "Ungrouped",
				posts: 0,
				views: 0,
				totalER: 0,
				topViewPost: null,
			};

			existing.posts++;
			existing.views += row.views_at_24h || 0;
			existing.totalER += row.engagement_rate || 0;

			groupStats.set(gid, existing);
		}

		const groupBreakdown = Array.from(groupStats.entries())
			.map(([groupId, stats]) => ({
				groupId,
				name: stats.name,
				posts: stats.posts,
				views: stats.views,
				avgER:
					stats.posts > 0
						? Math.round((stats.totalER / stats.posts) * 100) / 100
						: 0,
			}))
			.sort((a, b) => b.views - a.views);

		// ── Content source distribution ──────────────────────────────────
		const sourceCounts: Record<string, number> = {};
		for (const row of current) {
			const src = row.source_type || "unknown";
			sourceCounts[src] = (sourceCounts[src] || 0) + 1;
		}

		const sources = Object.entries(sourceCounts)
			.map(([type, count]) => ({
				type,
				count,
				pct:
					postsPublished > 0 ? Math.round((count / postsPublished) * 100) : 0,
			}))
			.sort((a, b) => b.count - a.count);

		// ── Queue health ─────────────────────────────────────────────────
		const { count: pendingCount } = await db
			.from("auto_post_queue")
			.select("id", { count: "exact" })
			.eq("workspace_id", wsId)
			.in("status", ["pending", "queued"]);

		const { count: failedCount } = await db
			.from("auto_post_queue")
			.select("id", { count: "exact" })
			.eq("workspace_id", wsId)
			.eq("status", "failed")
			.gte("created_at", cutoff);

		return apiSuccess(res, {
			kpis: {
				postsPublished,
				totalViews,
				avgEngagementRate: Math.round(avgER * 100) / 100,
				totalReplies,
				queueDepth: pendingCount || 0,
				failedCount: failedCount || 0,
				deltas: {
					posts: computeDelta(postsPublished, prevPosts),
					views: computeDelta(totalViews, prevViews),
					engagement: computeDelta(avgER, prevAvgER),
				},
			},
			groups: groupBreakdown,
			sources,
			periodDays,
		});
	} catch (error) {
		logger.error("Auto-post stats error", { error: String(error) });
		return apiError(res, 500, "Failed to compute auto-post stats");
	}
}
