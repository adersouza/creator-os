/**
 * Anomaly feed — ranked list of unresolved alerts for a user.
 *
 * GET /api/analytics?action=anomaly-feed&periodHours=24
 * Optional: &filter=reach-suppression restricts to shadowban_suspected +
 * reach_anomaly alert_types (plan widget #11 — reach suppression signal).
 *
 * Reads anomaly_alerts (written by anomalyDetector and audienceShiftDetector
 * crons). Dismissed alerts are excluded. Sorted by severity rank then
 * freshness — the triage order operators actually want.
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";
import { z } from "../../zodCompat.js";
import { apiError, apiSuccess } from "../../apiResponse.js";
import { withAuth } from "../../middleware.js";
import { getSupabase } from "../../supabase.js";
import { parseQueryOrError } from "../../validation.js";
import { getAccountIdsForContext } from "../../workspaceAccounts.js";

const QuerySchema = z.object({
	periodHours: z.coerce.number().int().min(1).max(168).optional().default(24),
	filter: z.string().optional(),
	limit: z.coerce.number().int().min(1).max(50).optional().default(10),
	accountId: z.string().optional(),
	accountIds: z.string().optional(),
	platform: z.string().optional(),
	workspaceId: z.string().optional(),
});

const REACH_SUPPRESSION_TYPES = ["shadowban_suspected", "reach_anomaly"];

const SEVERITY_RANK: Record<string, number> = {
	critical: 4,
	high: 3,
	medium: 2,
	low: 1,
};

// biome-ignore lint/suspicious/noExplicitAny: anomaly_alerts columns aren't fully typed
const db = (): any => getSupabase();

export default withAuth(
	async (req: VercelRequest, res: VercelResponse, user) => {
		if (req.method !== "GET") return apiError(res, 405, "Method not allowed");

		const parsed = parseQueryOrError(res, QuerySchema, req.query);
		if (!parsed) return;
		const { periodHours, filter, limit, accountId, accountIds, platform, workspaceId } = parsed;

		const cutoff = new Date(Date.now() - periodHours * 60 * 60 * 1000);

		let query = db()
			.from("anomaly_alerts")
			.select(
				"id, account_id, instagram_account_id, platform, alert_type, severity, title, description, ai_analysis, data, created_at",
			)
			.eq("user_id", user.id)
			.is("dismissed_at", null)
			.gte("created_at", cutoff.toISOString());

		if (filter === "reach-suppression") {
			query = query.in("alert_type", REACH_SUPPRESSION_TYPES);
		}
		let targetIds = accountIds
			? accountIds.split(",").map((id) => id.trim()).filter(Boolean)
			: accountId
				? [accountId]
				: [];
		const allowedIds = new Set(
			await getAccountIdsForContext(
				user.id,
				workspaceId ?? null,
				platform === "instagram" || platform === "threads" ? platform : undefined,
			),
		);
		targetIds =
			targetIds.length > 0
				? targetIds.filter((id) => allowedIds.has(id))
				: Array.from(allowedIds);
		if (targetIds.length === 0) {
			return apiSuccess(res, {
				alerts: [],
				periodHours,
				filter: filter || null,
				total: 0,
			});
		}
		if (targetIds.length > 0) {
			if (platform === "instagram") {
				query = query.in("instagram_account_id", targetIds);
			} else if (platform === "threads") {
				query = query.in("account_id", targetIds);
			} else {
				query = query.or(
					`account_id.in.(${targetIds.join(",")}),instagram_account_id.in.(${targetIds.join(",")})`,
				);
			}
		}

		const { data: rows } = await query;

		const alerts = ((rows || []) as Array<{
			id: string;
			account_id: string | null;
			instagram_account_id: string | null;
			platform: string;
			alert_type: string;
			severity: string;
			title: string;
			description: string | null;
			ai_analysis: string | null;
			data: Record<string, unknown> | null;
			created_at: string | null;
		}>)
			.map((a) => ({
				id: a.id,
				accountId: a.account_id,
				instagramAccountId: a.instagram_account_id,
				platform: a.platform,
				alertType: a.alert_type,
				severity: a.severity,
				title: a.title,
				description: a.description,
				aiAnalysis: a.ai_analysis,
				data: a.data,
				createdAt: a.created_at,
			}))
			.sort((a, b) => {
				const sa = SEVERITY_RANK[a.severity] ?? 0;
				const sb = SEVERITY_RANK[b.severity] ?? 0;
				if (sa !== sb) return sb - sa;
				const ta = a.createdAt ? Date.parse(a.createdAt) : 0;
				const tb = b.createdAt ? Date.parse(b.createdAt) : 0;
				return tb - ta;
			})
			.slice(0, limit);

		return apiSuccess(res, {
			alerts,
			periodHours,
			filter: filter || null,
			total: alerts.length,
		});
	},
);
