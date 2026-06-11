/**
 * Overnight brief read handler
 *
 * GET /api/analytics?action=overnight-brief
 *
 * Returns the latest non-expired brief for the authenticated user. When no fresh
 * brief exists (new user, cron hasn't run yet, or skipped under the no-change
 * gate), returns { brief: null, fallback: "live" } — the dashboard widget then
 * computes a live brief from fleet metrics, preserving the pre-cron behavior.
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";
import { apiError, apiSuccess } from "../../apiResponse.js";
import { withAuth } from "../../middleware.js";
import { getSupabase } from "../../supabase.js";

interface BriefRow {
	id: string;
	narrative_text: string;
	moves_jsonb: unknown;
	anomalies_jsonb: unknown;
	generated_at: string;
	window_start: string;
	window_end: string;
	ai_model: string | null;
}

export default withAuth(
	async (req: VercelRequest, res: VercelResponse, user) => {
		if (req.method !== "GET") return apiError(res, 405, "Method not allowed");

		const supabase = getSupabase() as unknown as {
			// biome-ignore lint/suspicious/noExplicitAny: overnight_briefs table not in generated Supabase types
			from: (t: string) => any;
		};

		const { data, error } = await supabase
			.from("overnight_briefs")
			.select(
				"id, narrative_text, moves_jsonb, anomalies_jsonb, generated_at, window_start, window_end, ai_model",
			)
			.eq("user_id", user.id)
			.gt("expires_at", new Date().toISOString())
			.order("generated_at", { ascending: false })
			.limit(1)
			.maybeSingle();

		if (error) {
			return apiError(res, 500, "Failed to load brief", {
				details: String(error),
			});
		}

		if (!data) {
			return apiSuccess(res, { brief: null, fallback: "live" });
		}

		const row = data as BriefRow;
		return apiSuccess(res, {
			brief: {
				id: row.id,
				narrative: row.narrative_text,
				moves: Array.isArray(row.moves_jsonb) ? row.moves_jsonb : [],
				anomalies: Array.isArray(row.anomalies_jsonb)
					? row.anomalies_jsonb
					: [],
				generatedAt: row.generated_at,
				windowStart: row.window_start,
				windowEnd: row.window_end,
				aiModel: row.ai_model,
			},
			fallback: null,
		});
	},
);
