/**
 * Threads API Route — Thin Router
 * /api/threads?action=<action>
 * Note: webhook.ts and webhook-subscribe.ts remain as separate files in threads/
 */
import type { VercelRequest, VercelResponse } from "@vercel/node";
import { authenticatedRouteError } from "./_lib/apiResponse.js";
import { withCors } from "./_lib/middleware.js";

export default withCors(async function handler(
	req: VercelRequest,
	res: VercelResponse,
) {
	const action = (req.query.action as string) || "";
	switch (action) {
		case "avatar":
			return (await import("./_lib/handlers/threads/avatar.js")).default(
				req,
				res,
			);
		case "profile":
			return (await import("./_lib/handlers/threads/profile.js")).default(
				req,
				res,
			);
		case "quota":
			return (await import("./_lib/handlers/threads/quota.js")).default(
				req,
				res,
			);
		case "reply-approvals":
			return (
				await import("./_lib/handlers/threads/reply-approvals.js")
			).default(req, res);
		default:
			return authenticatedRouteError(req, res, 400, `Unknown action: ${action}`);
	}
});
