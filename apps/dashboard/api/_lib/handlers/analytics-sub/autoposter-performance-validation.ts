/**
 * Autoposter performance validation.
 *
 * GET /api/analytics?action=autoposter-performance-validation
 *
 * Read-only pre/post comparison for the performance-first Threads autoposter
 * patch. This endpoint intentionally does not persist facts, recommendations,
 * winner patterns, or account strategy changes.
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";
import { apiError, apiSuccess } from "../../apiResponse.js";
import { withAuth } from "../../middleware.js";
import { getSupabaseAny } from "../../supabase.js";
import { parseQueryOrError } from "../../validation.js";
import { z } from "../../zodCompat.js";
import {
	buildPerformanceValidationReport,
	buildPerformanceValidationWindows,
	type AccountPerformanceStateLookup,
	type AutoposterPerformanceFact,
	type StrategyRecommendationLookup,
	type WinnerPatternLookup,
} from "../auto-post/performanceFirst.js";
import { verifyAccountOwnership } from "../helpers/verifyOwnership.js";

const QuerySchema = z.object({
	workspaceId: z.string().optional(),
	groupId: z.string().optional(),
	accountId: z.string().optional(),
	patchAppliedAt: z.string().optional(),
	preDays: z.coerce.number().int().min(1).max(180).optional().default(14),
	postDays: z.coerce.number().int().min(1).max(180).optional().default(14),
	limit: z.coerce.number().int().min(3).max(50).optional().default(20),
});

const db = () => getSupabaseAny();

function uniqueStrings(values: Array<string | null | undefined>): string[] {
	return [...new Set(values.filter((value): value is string => !!value))];
}

function objectMapById<T extends { id: string }>(rows: T[]) {
	return new Map(rows.map((row) => [row.id, row]));
}

export default withAuth(
	async (req: VercelRequest, res: VercelResponse, user) => {
		if (req.method !== "GET") return apiError(res, 405, "Method not allowed");

		const parsed = parseQueryOrError(res, QuerySchema, req.query);
		if (!parsed) return;

		const {
			workspaceId: requestedWorkspaceId,
			groupId,
			accountId,
			patchAppliedAt,
			preDays,
			postDays,
			limit,
		} = parsed;

		const workspaceId = requestedWorkspaceId || null;
		if (requestedWorkspaceId) {
			const { data: member, error } = await db()
				.from("workspace_members")
				.select("workspace_id")
				.eq("workspace_id", requestedWorkspaceId)
				.eq("user_id", user.id)
				.maybeSingle();
			if (error) {
				return apiError(res, 500, "Failed to verify workspace", {
					details: error.message,
				});
			}
			if (!member) return apiError(res, 404, "Workspace not found");
		}

		let accountIds: string[] | null = null;
		if (accountId) {
			const account = await verifyAccountOwnership(res, accountId, user.id, "id");
			if (!account) return;
			accountIds = [accountId];
		} else if (groupId) {
			const { data: group, error } = await db()
				.from("account_groups")
				.select("id, account_ids")
				.eq("id", groupId)
				.eq("user_id", user.id)
				.maybeSingle();
			if (error) {
				return apiError(res, 500, "Failed to verify group", {
					details: error.message,
				});
			}
			if (!group) return apiError(res, 404, "Group not found");
			accountIds = ((group.account_ids || []) as string[]).filter(Boolean);
		}

		const windows = buildPerformanceValidationWindows({
			patchAppliedAt,
			preDays,
			postDays,
			now: new Date(),
		});

		let factsQuery = db()
			.from("autoposter_post_performance_facts")
			.select("*")
			.eq("platform", "threads")
			.gte("published_at", windows.pre.start)
			.lt("published_at", windows.post.end)
			.order("published_at", { ascending: true });

		if (workspaceId) {
			factsQuery = factsQuery.eq("workspace_id", workspaceId);
		} else {
			factsQuery = factsQuery.eq("user_id", user.id);
		}
		if (groupId) factsQuery = factsQuery.eq("group_id", groupId);
		if (accountIds && accountIds.length > 0) {
			factsQuery = factsQuery.in("account_id", accountIds);
		}

		const { data: factRows, error: factsError } = await factsQuery;
		if (factsError) {
			return apiError(res, 500, "Failed to load performance facts", {
				details: factsError.message,
			});
		}

		const facts = (factRows || []) as AutoposterPerformanceFact[];
		const recommendationIds = uniqueStrings(
			facts.map((fact) => fact.strategy_recommendation_id),
		);
		const sourcePostIds = uniqueStrings([
			...facts.map((fact) => fact.source_pattern_id),
			...facts.map((fact) => fact.post_id),
		]);
		const accountStateIds = uniqueStrings(facts.map((fact) => fact.account_id));

		const [
			recommendationsResult,
			winnerPatternsResult,
			accountStatesResult,
		] = await Promise.all([
			recommendationIds.length > 0
				? db()
						.from("autoposter_strategy_recommendations")
						.select("id, pattern_type, metric_basis")
						.in("id", recommendationIds)
				: Promise.resolve({ data: [], error: null }),
			sourcePostIds.length > 0
				? db()
						.from("autoposter_winner_patterns")
						.select("source_post_id, clone_family")
						.in("source_post_id", sourcePostIds)
				: Promise.resolve({ data: [], error: null }),
			accountStateIds.length > 0
				? db()
						.from("account_autoposter_state")
						.select(
							"account_id, recommended_strategy_mode, recommended_posts_per_day, avg_views_24h_30d, posts_above_100_views_rate, last_performance_recomputed_at",
						)
						.in("account_id", accountStateIds)
				: Promise.resolve({ data: [], error: null }),
		]);

		if (recommendationsResult.error) {
			return apiError(res, 500, "Failed to load strategy recommendation context", {
				details: recommendationsResult.error.message,
			});
		}
		if (winnerPatternsResult.error) {
			return apiError(res, 500, "Failed to load winner pattern context", {
				details: winnerPatternsResult.error.message,
			});
		}
		if (accountStatesResult.error) {
			return apiError(res, 500, "Failed to load account performance state", {
				details: accountStatesResult.error.message,
			});
		}

		const recommendationsById = objectMapById(
			(recommendationsResult.data || []) as StrategyRecommendationLookup[],
		);
		const winnerPatternsByPostId = new Map(
			((winnerPatternsResult.data || []) as WinnerPatternLookup[])
				.filter((row) => row.source_post_id)
				.map((row) => [row.source_post_id as string, row]),
		);
		const accountStatesById = new Map(
			((accountStatesResult.data || []) as AccountPerformanceStateLookup[])
				.filter((row) => row.account_id)
				.map((row) => [row.account_id, row]),
		);

		const report = buildPerformanceValidationReport({
			facts,
			windows,
			limit,
			recommendationsById,
			winnerPatternsByPostId,
			accountStatesById,
		});

		return apiSuccess(res, {
			...report,
			principle:
				"Measurement only: this report does not create recommendations, generation changes, scoring changes, or account state changes.",
		});
	},
);
