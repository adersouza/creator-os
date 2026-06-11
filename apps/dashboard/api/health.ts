/**
 * Health API Route — Thin Router
 * /api/health?action=<action>
 * Note: health/ping.ts remains as a separate file.
 */
import type { VercelRequest, VercelResponse } from "@vercel/node";
import { authenticatedRouteError } from "./_lib/apiResponse.js";

export default async function handler(req: VercelRequest, res: VercelResponse) {
	const action = (req.query.action as string) || "";
	switch (action) {
		case "jobs":
			return (await import("./_lib/handlers/health/jobs.js")).default(req, res);
		case "ping":
			return (await import("./_lib/handlers/health/ping-account.js")).default(
				req,
				res,
			);
		default:
			return authenticatedRouteError(req, res, 400, `Unknown action: ${action}`);
	}
}
