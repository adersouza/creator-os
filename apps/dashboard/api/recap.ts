/**
 * Recap API Route — Thin Router
 * /api/recap?action=<action>
 */
import type { VercelRequest, VercelResponse } from "@vercel/node";
import { authenticatedRouteError } from "./_lib/apiResponse.js";

export const config = { maxDuration: 30 };

export default async function handler(req: VercelRequest, res: VercelResponse) {
	const action = (req.query.action as string) || "";
	switch (action) {
		case "generate":
			return (await import("./_lib/handlers/recap/generate.js")).default(
				req,
				res,
			);
		case "image":
			return (await import("./_lib/handlers/recap/image.js")).default(req, res);
		default:
			return authenticatedRouteError(req, res, 400, `Unknown action: ${action}`);
	}
}
