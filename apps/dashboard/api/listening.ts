/**
 * Listening API Route — Thin Router
 * /api/listening?action=<action>
 */
import type { VercelRequest, VercelResponse } from "@vercel/node";
import { authenticatedRouteError } from "./_lib/apiResponse.js";

export default async function handler(req: VercelRequest, res: VercelResponse) {
	const action = (req.query.action as string) || "";
	switch (action) {
		case "alerts":
			return (await import("./_lib/handlers/listening/alerts.js")).default(
				req,
				res,
			);
		case "monitor":
			return (await import("./_lib/handlers/listening/monitor.js")).default(
				req,
				res,
			);
		default:
			return authenticatedRouteError(req, res, 400, `Unknown action: ${action}`);
	}
}
