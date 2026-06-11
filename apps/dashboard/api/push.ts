/**
 * Push API Route — Thin Router
 * /api/push?action=<action>
 */
import type { VercelRequest, VercelResponse } from "@vercel/node";
import { authenticatedRouteError } from "./_lib/apiResponse.js";

export default async function handler(req: VercelRequest, res: VercelResponse) {
	const action = (req.query.action as string) || "";
	switch (action) {
		case "subscribe":
			return (await import("./_lib/handlers/push/subscribe.js")).default(
				req,
				res,
			);
		case "vapid-key":
			return (await import("./_lib/handlers/push/vapid-key.js")).default(
				req,
				res,
			);
		default:
			return authenticatedRouteError(req, res, 400, `Unknown action: ${action}`);
	}
}
