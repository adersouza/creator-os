// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
/**
 * Competitor Growth Patterns
 *
 * GET /api/analytics/competitor-patterns?accountId=...&competitorId=...&days=30
 * Analyzes competitor follower growth and posting frequency from snapshots.
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";
import { apiError, apiSuccess } from "../../apiResponse.js";
import { withAuth } from "../../middleware.js";
import { getSupabase } from "../../supabase.js";
import { parseAnalyticsQuery } from "../helpers/parseAnalyticsQuery.js";
import { verifyAccountOwnership } from "../helpers/verifyOwnership.js";

// biome-ignore lint/suspicious/noExplicitAny: table not yet in generated types
const db = (): any => getSupabase();

export default withAuth(
	async (req: VercelRequest, res: VercelResponse, user) => {
		if (req.method !== "GET") {
			return apiError(res, 405, "Method not allowed");
		}

		const userId = user.id;
		const { accountId, days } = parseAnalyticsQuery(req.query);
		const competitorId = req.query.competitorId as string | undefined;

		if (!accountId) return apiError(res, 400, "accountId is required");

		// Verify account belongs to user
		const account = await verifyAccountOwnership(res, accountId, userId);
		if (!account) return;

		// `competitors` is user-scoped, not account-scoped — schema has
		// `user_id` + `threads_user_id` only, no `account_id` column.
		// Past `.eq("account_id", accountId)` was a phantom filter that made
		// the endpoint always return "No tracked competitors". `accountId` is
		// already verified above as caller-owned and is kept for context (e.g.,
		// downstream platform-mix decisions); competitor list itself is the
		// caller's full tracked set.
		let compQuery = db()
			.from("competitors")
			.select("id, username, platform, threads_user_id, added_at")
			.eq("user_id", userId);

		if (competitorId) {
			compQuery = compQuery.eq("id", competitorId);
		}

		const { data: competitors, error: compError } = await compQuery;
		if (compError)
			return apiError(res, 500, "Failed to fetch competitors", {
				details: compError.message,
			});

		if (!competitors || competitors.length === 0) {
			return apiSuccess(res, {
				periodDays: days,
				competitors: [],
				message: competitorId
					? "Competitor not found"
					: "No tracked competitors for this account",
			});
		}

		const cutoff = new Date(Date.now() - days * 86_400_000).toISOString();
		const competitorIds = competitors.map((c: { id: string }) => c.id);

		// Get snapshots for all competitors in range
		const { data: snapshots, error: snapError } = await db()
			.from("competitor_snapshots")
			.select("id, competitor_id, followers_count, posts_count, created_at")
			.in("competitor_id", competitorIds)
			.gte("created_at", cutoff)
			.order("created_at", { ascending: true });

		if (snapError)
			return apiError(res, 500, "Failed to fetch snapshots", {
				details: snapError.message,
			});

		const allSnapshots = snapshots ?? [];

		// Group snapshots by competitor
		const snapshotsByComp: Record<
			string,
			Array<{
				followers_count: number;
				posts_count: number;
				created_at: string;
			}>
		> = {};

		for (const s of allSnapshots) {
			if (!snapshotsByComp[s.competitor_id])
				snapshotsByComp[s.competitor_id] = [];
			snapshotsByComp[s.competitor_id]!.push(s);
		}

		// Analyze per competitor
		const results = competitors.map(
			(comp: { id: string; username: string; platform: string }) => {
				const compSnapshots = snapshotsByComp[comp.id] ?? [];

				if (compSnapshots.length < 2) {
					return {
						competitorId: comp.id,
						username: comp.username,
						platform: comp.platform,
						snapshotCount: compSnapshots.length,
						followerGrowth: null,
						postingFrequency: null,
						message: "Insufficient snapshots for analysis",
					};
				}

				const first = compSnapshots[0];
				const last = compSnapshots[compSnapshots.length - 1];

				// Follower growth
				const followerDelta =
					(last!.followers_count ?? 0) - (first!.followers_count ?? 0);
				const followerGrowthPercent =
					first!.followers_count > 0
						? Math.round((followerDelta / first!.followers_count) * 1000) / 10
						: 0;

				// Posting frequency (posts delta / days elapsed)
				const daysElapsed = Math.max(
					(new Date(last!.created_at).getTime() -
						new Date(first!.created_at).getTime()) /
						86_400_000,
					1,
				);
				const postsDelta = (last!.posts_count ?? 0) - (first!.posts_count ?? 0);
				const postsPerDay = Math.round((postsDelta / daysElapsed) * 100) / 100;

				return {
					competitorId: comp.id,
					username: comp.username,
					platform: comp.platform,
					snapshotCount: compSnapshots.length,
					followerGrowth: {
						startFollowers: first!.followers_count ?? 0,
						endFollowers: last!.followers_count ?? 0,
						delta: followerDelta,
						growthPercent: followerGrowthPercent,
					},
					postingFrequency: {
						startPosts: first!.posts_count ?? 0,
						endPosts: last!.posts_count ?? 0,
						newPosts: postsDelta,
						postsPerDay,
						daysTracked: Math.round(daysElapsed),
					},
				};
			},
		);

		return apiSuccess(res, {
			periodDays: days,
			competitors: results,
		});
	},
);
