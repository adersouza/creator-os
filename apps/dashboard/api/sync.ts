/**
 * Sync API Route — Thin Router
 * /api/sync?action=<action>
 */
import type { VercelRequest, VercelResponse } from "@vercel/node";
import { authenticatedRouteError } from "./_lib/apiResponse.js";

export const config = { maxDuration: 60 };

export default async function handler(req: VercelRequest, res: VercelResponse) {
	const action = (req.query.action as string) || "";
	switch (action) {
		case "threads-account":
			return (await import("./_lib/handlers/sync/threads-account.js")).default(
				req,
				res,
			);
		case "ig-account":
			return (await import("./_lib/handlers/sync/ig-account.js")).default(
				req,
				res,
			);
		case "post-engagement":
			return (await import("./_lib/handlers/sync/post-engagement.js")).default(
				req,
				res,
			);
		default:
			return authenticatedRouteError(req, res, 400, `Unknown action: ${action}`);
	}
}
