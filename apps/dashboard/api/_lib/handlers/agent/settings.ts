/**
 * Agent Settings
 *
 * GET   /api/agent/settings — read agent settings (agent_paused flag)
 * PATCH /api/agent/settings — toggle agent_paused
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";
import { apiError, apiSuccess } from "../../apiResponse.js";
import { withAuthDb } from "../../middleware.js";

export default withAuthDb(
	async (req: VercelRequest, res: VercelResponse, { user, userDb }) => {
		if (req.method === "GET") {
			const { data, error } = await userDb
				.from("profiles")
				.select("agent_paused")
				.eq("id", user.id)
				.maybeSingle();

			if (error) return apiError(res, 500, "Failed to fetch agent settings");
			return apiSuccess(res, { agent_paused: data?.agent_paused ?? false });
		}

		if (req.method === "PATCH") {
			const { agent_paused } = req.body ?? {};
			if (typeof agent_paused !== "boolean") {
				return apiError(res, 400, "agent_paused must be a boolean");
			}

			const { error } = await userDb
				.from("profiles")
				.update({ agent_paused })
				.eq("id", user.id);

			if (error) return apiError(res, 500, "Failed to update agent settings");

			// On unpause, reset circuit breaker counters so agent isn't immediately re-tripped
			if (!agent_paused) {
				try {
					const { reset } = await import("../../agentCircuitBreaker.js");
					await reset(user.id);
				} catch {
					// Non-fatal — counters will expire naturally
				}
			}

			return apiSuccess(res, { agent_paused });
		}

		return apiError(res, 405, "Method not allowed");
	},
);
