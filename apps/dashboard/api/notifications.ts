/**
 * Notifications API Route — Thin Router
 * /api/notifications?action=<action>
 */
import type { VercelRequest, VercelResponse } from "@vercel/node";
import { authenticatedRouteError } from "./_lib/apiResponse.js";

export default async function handler(req: VercelRequest, res: VercelResponse) {
	const action = (req.query.action as string) || "";
	switch (action) {
		case "test-push":
			return (await import("./_lib/handlers/notifications/test-push.js")).default(
				req,
				res,
			);
		default:
			return authenticatedRouteError(req, res, 400, `Unknown action: ${action}`);
	}
}
