/**
 * V1 API Route — Thin Router
 * /api/v1?action=<action>
 */
import type { VercelRequest, VercelResponse } from "@vercel/node";
import { apiError } from "./_lib/apiResponse.js";
import { withApiKey } from "./_lib/withApiKey.js";

export default async function handler(req: VercelRequest, res: VercelResponse) {
	const action = (req.query.action as string) || "";
	switch (action) {
		case "accounts":
			return (await import("./_lib/handlers/v1/accounts.js")).default(req, res);
		case "posts":
			return (await import("./_lib/handlers/v1/posts.js")).default(req, res);
		case "analytics":
			return (await import("./_lib/handlers/v1/analytics.js")).default(
				req,
				res,
			);
		case "insights":
			return (await import("./_lib/handlers/v1/insights.js")).default(req, res);
		default:
			return withApiKey(async (_req, authedRes) => {
				return apiError(authedRes, 400, `Unknown action: ${action}`);
			})(req, res);
	}
}
