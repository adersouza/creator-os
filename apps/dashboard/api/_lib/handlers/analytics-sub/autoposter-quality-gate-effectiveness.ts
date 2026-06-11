/**
 * Autoposter quality gate effectiveness.
 *
 * GET /api/analytics?action=autoposter-quality-gate-effectiveness
 *
 * Read-only counterfactual report that asks whether the current/stored quality
 * gate would preserve historical winners and filter historical losers.
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";
import { apiError, apiSuccess } from "../../apiResponse.js";
import { withAuth } from "../../middleware.js";
import { getSupabaseAny } from "../../supabase.js";
import { parseQueryOrError } from "../../validation.js";
import { z } from "../../zodCompat.js";
import {
	buildQualityGateEffectivenessReport,
	DEFAULT_GATE_EFFECTIVENESS_DAYS,
	type QualityGateQueueContext,
} from "../auto-post/qualityGateEffectiveness.js";
import type { AutoposterPerformanceFact } from "../auto-post/performanceFirst.js";
import { verifyAccountOwnership } from "../helpers/verifyOwnership.js";

const QuerySchema = z.object({
	workspaceId: z.string().optional(),
	groupId: z.string().optional(),
	accountId: z.string().optional(),
	days: z.coerce
		.number()
		.int()
		.min(1)
		.max(365)
		.optional()
		.default(DEFAULT_GATE_EFFECTIVENESS_DAYS),
	winnerViews: z.coerce.number().int().min(1).max(1_000_000).optional(),
	loserViews: z.coerce.number().int().min(0).max(1_000_000).optional(),
	limit: z.coerce.number().int().min(3).max(50).optional().default(20),
});

const db = () => getSupabaseAny();

function uniqueStrings(values: Array<string | null | undefined>): string[] {
	return [...new Set(values.filter((value): value is string => !!value))];
}

function queueIdFromMetricNotes(fact: AutoposterPerformanceFact): string | null {
	const notes = fact.metric_notes || {};
	const value = notes.queueId || notes.autoPostQueueId;
	return typeof value === "string" && value.trim() ? value.trim() : null;
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
			days,
			winnerViews,
			loserViews,
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

		const now = new Date();
		const start = new Date(now.getTime() - days * 86_400_000).toISOString();
		let factsQuery = db()
			.from("autoposter_post_performance_facts")
			.select("*")
			.eq("platform", "threads")
			.gte("published_at", start)
			.lte("published_at", now.toISOString())
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
		const queueIds = uniqueStrings(facts.map(queueIdFromMetricNotes));
		const queueResult =
			queueIds.length > 0
				? await db()
						.from("auto_post_queue")
						.select(
							"id, source_type, source_content, source_competitor_id, predicted_viral_score, metadata",
						)
						.in("id", queueIds)
				: { data: [], error: null };

		if (queueResult.error) {
			return apiError(res, 500, "Failed to load quality gate queue context", {
				details: queueResult.error.message,
			});
		}

		const queueById = new Map(
			((queueResult.data || []) as QualityGateQueueContext[]).map((row) => [
				row.id,
				row,
			]),
		);
		const report = buildQualityGateEffectivenessReport({
			facts,
			queueById,
			now,
			days,
			winnerViews,
			loserViews,
			limit,
		});

		return apiSuccess(res, {
			...report,
			principle:
				"Measurement only: this report does not change quality gate thresholds, queue rows, recommendations, or generation behavior.",
		});
	},
);
