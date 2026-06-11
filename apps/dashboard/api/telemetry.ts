/**
 * Privacy-safe client telemetry endpoint.
 * /api/telemetry?action=client-event
 */
import type { VercelRequest, VercelResponse } from "@vercel/node";
import { authenticatedRouteError } from "./_lib/apiResponse.js";

export default async function handler(req: VercelRequest, res: VercelResponse) {
	const action = (req.query.action as string) || "";
	switch (action) {
		case "client-event":
			return (await import("./_lib/handlers/telemetry/client-event.js")).default(
				req,
				res,
			);
		default:
			return authenticatedRouteError(req, res, 400, `Unknown action: ${action}`);
	}
}
