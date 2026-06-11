/**
 * Beta API Route — Thin Router
 * /api/beta?action=<action>
 */
import type { VercelRequest, VercelResponse } from "@vercel/node";
import { authenticatedRouteError } from "./_lib/apiResponse.js";

export default async function handler(req: VercelRequest, res: VercelResponse) {
	const action = (req.query.action as string) || "";
	switch (action) {
		case "claim":
			return (await import("./_lib/handlers/beta/claim.js")).default(req, res);
		case "feedback":
			return (await import("./_lib/handlers/beta/feedback.js")).default(
				req,
				res,
			);
		case "status":
			return (await import("./_lib/handlers/beta/status.js")).default(req, res);
		default:
			return authenticatedRouteError(req, res, 400, `Unknown action: ${action}`);
	}
}
