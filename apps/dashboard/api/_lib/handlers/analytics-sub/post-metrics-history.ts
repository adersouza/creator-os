// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
/**
 * Post Metrics History
 *
 * GET /api/analytics/post-metrics-history?accountId=...&postId=...&granularity=raw|daily&limit=100
 * Returns time-series snapshots from the existing post_metric_history table.
 * For granularity=daily: takes latest snapshot per post per day.
 * Includes computed deltas and velocity fields.
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";
import { apiError, apiSuccess } from "../../apiResponse.js";
import { withAuth } from "../../middleware.js";
import { getSupabase } from "../../supabase.js";
import { parseQueryOrError } from "../../validation.js";
import { z, zEnum } from "../../zodCompat.js";
import { verifyAccountOwnership } from "../helpers/verifyOwnership.js";

const QuerySchema = z.object({
	postId: z.string().optional(),
	accountId: z.string().optional(),
	startDate: z.string().optional(),
	endDate: z.string().optional(),
	granularity: zEnum(["raw", "daily"]).optional().default("raw"),
	limit: z.coerce.number().int().min(1).max(500).optional().default(100),
});

// biome-ignore lint/suspicious/noExplicitAny: table not yet in generated types
const db = (): any => getSupabase();

interface MetricRow {
	id: string;
	post_id: string;
	views_count: number | null;
	likes_count: number | null;
	replies_count: number | null;
	reposts_count: number | null;
	quotes_count: number | null;
	shares_count: number | null;
	saves_count: number | null;
	reach: number | null;
	snapshot_at: string;
}

interface SnapshotWithDelta {
	postId: string;
	recordedAt: string;
	views: number;
	likes: number;
	replies: number;
	reposts: number;
	quotes: number;
	shares: number;
	saves: number;
	reach: number;
	delta: {
		views: number;
		likes: number;
		replies: number;
		reposts: number;
		quotes: number;
		shares: number;
		saves: number;
		reach: number;
	} | null;
	velocity: {
		viewsPerHour: number;
		likesPerHour: number;
	} | null;
}

export default withAuth(
	async (req: VercelRequest, res: VercelResponse, user) => {
		if (req.method !== "GET") {
			return apiError(res, 405, "Method not allowed");
		}

		const userId = user.id;
		const parsed = parseQueryOrError(res, QuerySchema, req.query);
		if (!parsed) return;
		const { postId, accountId, startDate, endDate, granularity, limit } =
			parsed;

		if (!postId && !accountId) {
			return apiError(res, 400, "Either postId or accountId is required");
		}

		// Build query
		let query = db()
			.from("post_metric_history")
			.select(
				"id, post_id, views_count, likes_count, replies_count, reposts_count, quotes_count, shares_count, saves_count, reach, snapshot_at",
			)
			.order("snapshot_at", { ascending: true });

		if (postId) {
			const { data: post, error: postError } = await db()
				.from("posts")
				.select("id")
				.eq("id", postId)
				.eq("user_id", userId)
				.maybeSingle();

			if (postError) {
				return apiError(res, 500, "Failed to verify post", {
					details: postError.message,
				});
			}
			if (!post) return apiError(res, 404, "Post not found");

			query = query.eq("post_id", postId);
		}

		if (accountId) {
			// Verify account ownership
			const account = await verifyAccountOwnership(res, accountId, userId);
			if (!account) return;

			query = query.eq("account_id", accountId);
		}

		if (startDate) query = query.gte("snapshot_at", startDate);
		if (endDate) query = query.lte("snapshot_at", endDate);
		query = query.limit(limit);

		const { data: rows, error } = await query;

		if (error)
			return apiError(res, 500, "Failed to fetch metric history", {
				details: error.message,
			});

		const allRows: MetricRow[] = rows ?? [];

		if (allRows.length === 0) {
			return apiSuccess(res, { snapshots: [], count: 0 });
		}

		let processed: MetricRow[];

		if (granularity === "daily") {
			// Take latest snapshot per post per day
			const byPostDay = new Map<string, MetricRow>();
			for (const row of allRows) {
				const day = row.snapshot_at.split("T")[0]!;
				const key = `${row.post_id}:${day}`;
				// Since rows are ordered ascending, later rows overwrite earlier ones
				byPostDay.set(key, row);
			}
			processed = [...byPostDay.values()].sort(
				(a, b) =>
					new Date(a.snapshot_at).getTime() - new Date(b.snapshot_at).getTime(),
			);
		} else {
			processed = allRows;
		}

		// Compute deltas and velocity
		const prevByPost = new Map<string, MetricRow>();
		const snapshots: SnapshotWithDelta[] = processed.map((row) => {
			const prev = prevByPost.get(row.post_id);
			const v = (val: number | null) => val ?? 0;

			let delta: SnapshotWithDelta["delta"] = null;
			let velocity: SnapshotWithDelta["velocity"] = null;

			if (prev) {
				delta = {
					views: v(row.views_count) - v(prev.views_count),
					likes: v(row.likes_count) - v(prev.likes_count),
					replies: v(row.replies_count) - v(prev.replies_count),
					reposts: v(row.reposts_count) - v(prev.reposts_count),
					quotes: v(row.quotes_count) - v(prev.quotes_count),
					shares: v(row.shares_count) - v(prev.shares_count),
					saves: v(row.saves_count) - v(prev.saves_count),
					reach: v(row.reach) - v(prev.reach),
				};

				const hoursDiff =
					(new Date(row.snapshot_at).getTime() -
						new Date(prev.snapshot_at).getTime()) /
					3600000;
				if (hoursDiff > 0) {
					velocity = {
						viewsPerHour: Math.round((delta.views / hoursDiff) * 10) / 10,
						likesPerHour: Math.round((delta.likes / hoursDiff) * 10) / 10,
					};
				}
			}

			prevByPost.set(row.post_id, row);

			return {
				postId: row.post_id,
				recordedAt: row.snapshot_at,
				views: v(row.views_count),
				likes: v(row.likes_count),
				replies: v(row.replies_count),
				reposts: v(row.reposts_count),
				quotes: v(row.quotes_count),
				shares: v(row.shares_count),
				saves: v(row.saves_count),
				reach: v(row.reach),
				delta,
				velocity,
			};
		});

		return apiSuccess(res, {
			snapshots,
			count: snapshots.length,
			granularity,
		});
	},
);
