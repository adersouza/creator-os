/**
 * Crisis Status — GET /api/crisis/status
 *
 * Returns active and recently resolved crisis events.
 * Response: { active_crises, resolved_recent, current_level }
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";
import { apiError, apiSuccess } from "../../apiResponse.js";
import { withAuthDb } from "../../middleware.js";
import { checkRateLimit } from "../../rateLimiter.js";

export default withAuthDb(
	async (req: VercelRequest, res: VercelResponse, { user, userDb }) => {
		if (req.method !== "GET") return apiError(res, 405, "Method not allowed");

		// #694: Rate limit crisis status endpoint
		const rl = await checkRateLimit({
			key: `crisis-status:${user.id}`,
			limit: 30,
			windowSeconds: 60,
			failMode: "open",
		});
		if (!rl.allowed) return apiError(res, 429, "Rate limit exceeded");

		// Active (unresolved) crises
		const { data: activeCrises } = await userDb
			.from("crisis_events")
			.select("*")
			.eq("user_id", user.id)
			.is("resolved_at", null)
			.order("created_at", { ascending: false });

		// Recently resolved (last 7 days)
		const sevenDaysAgo = new Date(
			Date.now() - 7 * 24 * 60 * 60 * 1000,
		).toISOString();
		const { data: resolvedRecent } = await userDb
			.from("crisis_events")
			.select("*")
			.eq("user_id", user.id)
			.not("resolved_at", "is", null)
			.gte("resolved_at", sevenDaysAgo)
			.order("resolved_at", { ascending: false });

		// Determine current level
		const active = activeCrises || [];
		let currentLevel: "normal" | "warning" | "severe" = "normal";
		if (active.some((c: { severity?: string | undefined }) => c.severity === "severe")) {
			currentLevel = "severe";
		} else if (active.length > 0) {
			currentLevel = "warning";
		}

		return apiSuccess(res, {
			active_crises: active,
			resolved_recent: resolvedRecent || [],
			current_level: currentLevel,
		});
	},
);
