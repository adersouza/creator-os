// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
/**
 * IG Content Type Breakdown — week-over-week deltas
 *
 * GET /api/analytics?action=content-type-trend&accountId=X
 *
 * Surfaces "Reels reach -40% WoW vs. feed +12%" from the JSONB snapshots
 * we already store in account_analytics.ig_content_type_breakdown. No new
 * tracking — just diffing what's already there.
 *
 * Shape of the stored JSONB:
 *   { feed?: Record<metric, number>, reels?: Record<metric, number>, story?: Record<metric, number> }
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";
import { z } from "../../zodCompat.js";
import { apiError, apiSuccess } from "../../apiResponse.js";
import { withAuth } from "../../middleware.js";
import { getSupabase } from "../../supabase.js";
import { parseQueryOrError } from "../../validation.js";

const QuerySchema = z.object({
	accountId: z.string().optional(),
	accountIds: z.string().optional(),
	groupId: z.string().optional(),
	periodDays: z.coerce.number().int().min(7).max(90).optional().default(30),
});

// biome-ignore lint/suspicious/noExplicitAny: JSONB column not statically typed
const db = (): any => getSupabase();

type ContentBuckets = Record<string, Record<string, number>>;
type TrailPoint = {
	weekStart: string;
	reelsPct: number;
	feedPct: number;
	storyPct: number;
	totalReach: number;
};

type PostMixRow = {
	published_at: string;
	media_type: string | null;
	ig_media_type: string | null;
	ig_reach: number | null;
	ig_views: number | null;
	likes_count: number | null;
	replies_count: number | null;
	ig_shares: number | null;
	shares_count: number | null;
	ig_saved: number | null;
};

function sumBreakdowns(rows: Array<{ ig_content_type_breakdown: unknown }>): ContentBuckets {
	const out: ContentBuckets = {};
	for (const row of rows) {
		const bd = row.ig_content_type_breakdown as ContentBuckets | null;
		if (!bd || typeof bd !== "object") continue;
		for (const [mediaType, metrics] of Object.entries(bd)) {
			if (!metrics || typeof metrics !== "object") continue;
			out[mediaType] = out[mediaType] || {};
			for (const [metric, value] of Object.entries(metrics)) {
				if (typeof value !== "number") continue;
				out[mediaType][metric] = (out[mediaType][metric] || 0) + value;
			}
		}
	}
	return out;
}

function mediaBucket(row: Pick<PostMixRow, "media_type" | "ig_media_type">): "reels" | "feed" | "story" {
	const raw = String(row.ig_media_type || row.media_type || "").toLowerCase();
	if (raw.includes("reel") || raw === "video") return "reels";
	if (raw.includes("stor")) return "story";
	return "feed";
}

function sumPostRows(rows: PostMixRow[]): ContentBuckets {
	const out: ContentBuckets = {};
	for (const row of rows) {
		const bucket = mediaBucket(row);
		out[bucket] = out[bucket] || {};
		out[bucket].reach = (out[bucket].reach || 0) + (row.ig_reach || 0);
		out[bucket].views = (out[bucket].views || 0) + (row.ig_views || 0);
		out[bucket].likes = (out[bucket].likes || 0) + (row.likes_count || 0);
		out[bucket].comments = (out[bucket].comments || 0) + (row.replies_count || 0);
		out[bucket].shares =
			(out[bucket].shares || 0) + (row.ig_shares || row.shares_count || 0);
		out[bucket].saves = (out[bucket].saves || 0) + (row.ig_saved || 0);
	}
	return out;
}

function postMixSelect(): string {
	return "published_at, media_type, ig_media_type, ig_reach, ig_views, likes_count, replies_count, ig_shares, shares_count, ig_saved";
}

export function shouldUseUnscopedPostFallback(
	hasSelectedScope: boolean,
	scopedPostCount: number,
): boolean {
	return !hasSelectedScope && scopedPostCount === 0;
}

function weekStartIso(dateValue: string): string {
	const d = new Date(`${dateValue}T00:00:00.000Z`);
	const day = d.getUTCDay();
	const diff = (day + 6) % 7; // Monday start
	d.setUTCDate(d.getUTCDate() - diff);
	return d.toISOString().split("T")[0]!;
}

function toTrailPoint(
	weekStart: string,
	rows: Array<{ ig_content_type_breakdown: unknown }>,
): TrailPoint | null {
	const buckets = sumBreakdowns(rows);
	const reels = buckets.reels?.reach ?? 0;
	const feed = buckets.feed?.reach ?? 0;
	const story = buckets.story?.reach ?? 0;
	const totalReach = reels + feed + story;
	if (totalReach <= 0) return null;
	return {
		weekStart,
		reelsPct: (reels / totalReach) * 100,
		feedPct: (feed / totalReach) * 100,
		storyPct: (story / totalReach) * 100,
		totalReach,
	};
}

export default withAuth(
	async (req: VercelRequest, res: VercelResponse, user) => {
		if (req.method !== "GET") return apiError(res, 405, "Method not allowed");

		const parsed = parseQueryOrError(res, QuerySchema, req.query);
		if (!parsed) return;
		const { accountId, accountIds: accountIdsStr, groupId, periodDays } = parsed;

		const hasSelectedScope =
			!!accountIdsStr || !!groupId || (!!accountId && accountId !== "ALL");
		let targetAccountIds: string[] = [];
		if (accountIdsStr) {
			targetAccountIds = accountIdsStr.split(",").filter(Boolean);
		} else if (accountId && accountId !== "ALL") {
			targetAccountIds = [accountId];
		} else if (groupId) {
			const { data: group, error: groupError } = await db()
				.from("account_groups")
				.select("account_ids")
				.eq("id", groupId)
				.eq("user_id", user.id)
				.maybeSingle();
			if (groupError) {
				return apiError(res, 500, "Failed to resolve account group", {
					details: groupError.message,
				});
			}
			targetAccountIds = ((group?.account_ids ?? []) as string[]).filter(Boolean);
		}

		if (targetAccountIds.length === 0 && hasSelectedScope) {
			return apiSuccess(res, { current: {}, previous: {}, deltas: {}, trail: [] });
		}

		if (targetAccountIds.length === 0) {
			const { data: igAccounts } = await db()
				.from("instagram_accounts")
				.select("id")
				.eq("user_id", user.id);
			targetAccountIds = (igAccounts || []).map((a: { id: string }) => a.id);
		} else {
			const { data: owned } = await db()
				.from("instagram_accounts")
				.select("id")
				.eq("user_id", user.id)
				.in("id", targetAccountIds);
			targetAccountIds = (owned || []).map((a: { id: string }) => a.id);
		}

		if (targetAccountIds.length === 0) {
			return apiSuccess(res, { current: {}, previous: {}, deltas: {}, trail: [] });
		}

		const today = new Date();
		const currentStart = new Date(today);
		currentStart.setDate(currentStart.getDate() - periodDays);
		const previousStart = new Date(today);
		previousStart.setDate(previousStart.getDate() - periodDays * 2);

		const iso = (d: Date) => d.toISOString().split("T")[0]!;

		const { data: currentRows } = await db()
			.from("account_analytics")
			.select("ig_content_type_breakdown")
			.in("account_id", targetAccountIds)
			.gte("date", iso(currentStart))
			.lte("date", iso(today));

		const { data: previousRows } = await db()
			.from("account_analytics")
			.select("ig_content_type_breakdown")
			.in("account_id", targetAccountIds)
			.gte("date", iso(previousStart))
			.lt("date", iso(currentStart));

		const trailStart = new Date(today);
		trailStart.setDate(trailStart.getDate() - 84);
		const { data: trailRows } = await db()
			.from("account_analytics")
			.select("ig_content_type_breakdown, date")
			.in("account_id", targetAccountIds)
			.gte("date", iso(trailStart))
			.lte("date", iso(today));

		let current = sumBreakdowns(currentRows || []);
		let previous = sumBreakdowns(previousRows || []);

		const currentHasReach =
			(current.reels?.reach || 0) +
				(current.feed?.reach || 0) +
				(current.story?.reach || 0) >
			0;
		if (!currentHasReach) {
			const fetchPostRows = async (start: Date) => {
				const scoped = await db()
					.from("posts")
					.select(postMixSelect())
					.in("instagram_account_id", targetAccountIds)
					.eq("status", "published")
					.gte("published_at", start.toISOString())
					.lte("published_at", today.toISOString());

				if ((scoped.data || []).length > 0) return scoped.data as PostMixRow[];
				if (!shouldUseUnscopedPostFallback(hasSelectedScope, scoped.data?.length ?? 0)) {
					return [];
				}

				const byUser = await db()
					.from("posts")
					.select(postMixSelect())
					.eq("user_id", user.id)
					.eq("platform", "instagram")
					.eq("status", "published")
					.gte("published_at", start.toISOString())
					.lte("published_at", today.toISOString());

				return (byUser.data || []) as PostMixRow[];
			};

			const posts = await fetchPostRows(previousStart);
			current = sumPostRows(
				posts.filter((p) => new Date(p.published_at) >= currentStart),
			);
			previous = sumPostRows(
				posts.filter((p) => {
					const publishedAt = new Date(p.published_at);
					return publishedAt >= previousStart && publishedAt < currentStart;
				}),
			);

			const trailByWeek = new Map<string, PostMixRow[]>();
			const trailPostRows = await fetchPostRows(trailStart);

			for (const row of trailPostRows) {
				const wk = weekStartIso(row.published_at.split("T")[0]!);
				const list = trailByWeek.get(wk) || [];
				list.push(row);
				trailByWeek.set(wk, list);
			}
			const postTrail = Array.from(trailByWeek.entries())
				.sort(([a], [b]) => a.localeCompare(b))
				.map(([weekStart, rows]) =>
					toTrailPoint(weekStart, rows.map((row) => ({
						ig_content_type_breakdown: sumPostRows([row]),
					}))),
				)
				.filter((p): p is TrailPoint => p != null)
				.slice(-12);

			if (postTrail.length > 0) {
				return apiSuccess(res, { current, previous, deltas: buildDeltas(current, previous), trail: postTrail });
			}
		}

		// deltas: { [mediaType]: { [metric]: { current, previous, delta, pctChange } } }
		const deltas = buildDeltas(current, previous);

		const byWeek = new Map<string, Array<{ ig_content_type_breakdown: unknown }>>();
		for (const row of (trailRows || []) as Array<{
			ig_content_type_breakdown: unknown;
			date: string;
		}>) {
			const wk = weekStartIso(row.date);
			const list = byWeek.get(wk) || [];
			list.push(row);
			byWeek.set(wk, list);
		}
		const trail = Array.from(byWeek.entries())
			.sort(([a], [b]) => a.localeCompare(b))
			.map(([weekStart, rows]) => toTrailPoint(weekStart, rows))
			.filter((p): p is TrailPoint => p != null)
			.slice(-12);

		return apiSuccess(res, { current, previous, deltas, trail });
	},
);

function buildDeltas(
	current: ContentBuckets,
	previous: ContentBuckets,
): Record<
	string,
	Record<
		string,
		{ current: number; previous: number; delta: number; pctChange: number | null }
	>
> {
	const deltas: Record<
		string,
		Record<
			string,
			{ current: number; previous: number; delta: number; pctChange: number | null }
		>
	> = {};
	const mediaTypes = new Set([...Object.keys(current), ...Object.keys(previous)]);
	for (const mt of mediaTypes) {
		deltas[mt] = {};
		const metrics = new Set([
			...Object.keys(current[mt] || {}),
			...Object.keys(previous[mt] || {}),
		]);
		for (const metric of metrics) {
			const c = current[mt]?.[metric] || 0;
			const p = previous[mt]?.[metric] || 0;
			deltas[mt][metric] = {
				current: c,
				previous: p,
				delta: c - p,
				pctChange: p > 0 ? ((c - p) / p) * 100 : null,
			};
		}
	}
	return deltas;
}
