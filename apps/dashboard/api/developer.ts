/**
 * Developer API Route — Thin Router
 * /api/developer?action=<action>
 */
import type { VercelRequest, VercelResponse } from "@vercel/node";
import { authenticatedRouteError } from "./_lib/apiResponse.js";

export default async function handler(req: VercelRequest, res: VercelResponse) {
	const action = (req.query.action as string) || "";
	switch (action) {
		case "keys":
			return (await import("./_lib/handlers/developer/keys.js")).default(
				req,
				res,
			);
		case "openapi":
			return (await import("./_lib/handlers/developer/openapi.js")).default(
				req,
				res,
			);
		default:
			return authenticatedRouteError(req, res, 400, `Unknown action: ${action}`);
	}
}
