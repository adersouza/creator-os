/**
 * Agent Circuit Breaker Status & Reset
 *
 * GET  /api/agent/circuit-breaker  — current breaker status + counters
 * POST /api/agent/circuit-breaker  — reset breaker (clear trip + counters)
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";
import { apiError, apiSuccess } from "../../apiResponse.js";
import { withAuth } from "../../middleware.js";

export default withAuth(
	async (req: VercelRequest, res: VercelResponse, user) => {
		if (req.method === "GET") {
			const { getStatus } = await import("../../agentCircuitBreaker.js");
			const status = await getStatus(user.id);
			return apiSuccess(res, status as unknown as Record<string, unknown>);
		}

		if (req.method === "POST") {
			const { reset } = await import("../../agentCircuitBreaker.js");
			await reset(user.id);
			return apiSuccess(res, { reset: true });
		}

		return apiError(res, 405, "Method not allowed");
	},
);
