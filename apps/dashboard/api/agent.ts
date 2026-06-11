/**
 * Agent API Route — Thin Router
 *
 * /api/agent?action=<action>
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
		case "approvals":
			return (await import("./_lib/handlers/agent/approvals.js")).default(
				req,
				res,
			);
		case "cap-status":
			return (await import("./_lib/handlers/agent/cap-status.js")).default(
				req,
				res,
			);
		case "circuit-breaker":
			return (await import("./_lib/handlers/agent/circuit-breaker.js")).default(
				req,
				res,
			);
		case "content-strategy":
			return (
				await import("./_lib/handlers/agent/content-strategy.js")
			).default(req, res);
		case "groups":
			return (await import("./_lib/handlers/agent/groups.js")).default(
				req,
				res,
			);
		case "log":
			return (await import("./_lib/handlers/agent/log.js")).default(req, res);
		case "notes":
			return (await import("./_lib/handlers/agent/notes.js")).default(req, res);
		case "settings":
			return (await import("./_lib/handlers/agent/settings.js")).default(
				req,
				res,
			);
		case "weekly-state":
			return (await import("./_lib/handlers/agent/weekly-state.js")).default(
				req,
				res,
			);
		case "crisis-status":
			return (await import("./_lib/handlers/crisis/status.js")).default(
				req,
				res,
			);
		case "operator-snapshot":
			req.query.action = "snapshot";
			return (await import("./operator.js")).default(req, res);
		default:
			return authenticatedRouteError(req, res, 400, `Unknown action: ${action}`);
	}
});
