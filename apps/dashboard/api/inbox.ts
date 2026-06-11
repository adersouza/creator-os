/**
 * Inbox API Route — Thin Router
 * /api/inbox?action=<action>
 */
import type { VercelRequest, VercelResponse } from "@vercel/node";
import {
	authenticatedRouteError,
	getAuthUserOrError,
} from "./_lib/apiResponse.js";
import { enforceRouteRateLimit } from "./_lib/routeRateLimit.js";

const WRITE_ACTIONS = new Set([
	"assign",
	"mark-read",
	"rules",
	"suggestions",
]);

const READ_ACTIONS = new Set(["unified", "check-contradiction"]);

export default async function handler(req: VercelRequest, res: VercelResponse) {
	const action = (req.query.action as string) || "";
	if (WRITE_ACTIONS.has(action) || READ_ACTIONS.has(action)) {
		const user = await getAuthUserOrError(req, res);
		if (!user) return;

		const isWrite = WRITE_ACTIONS.has(action);
		const allowed = await enforceRouteRateLimit(res, {
			key: `inbox-${isWrite ? "write" : "read"}:user:${user.id}:minute`,
			limit: isWrite ? 30 : 120,
			windowSeconds: 60,
			failMode: isWrite ? "closed" : "open",
			message: isWrite
				? "Too many inbox write requests. Try again shortly."
				: "Too many inbox read requests. Try again shortly.",
		});
		if (!allowed) return;
	}

	switch (action) {
		case "assign":
			return (await import("./_lib/handlers/inbox/assign.js")).default(
				req,
				res,
			);
		case "mark-read":
			return (await import("./_lib/handlers/inbox/mark-read.js")).default(
				req,
				res,
			);
		case "unified":
			return (await import("./_lib/handlers/inbox/unified.js")).default(
				req,
				res,
			);
		case "rules":
			return (await import("./_lib/handlers/inbox/rules.js")).default(req, res);
		case "suggestions":
			return (await import("./_lib/handlers/inbox/suggestions.js")).default(
				req,
				res,
			);
		case "check-contradiction":
			return (await import("./_lib/handlers/inbox/check-contradiction.js")).default(
				req,
				res,
			);
		default:
			return authenticatedRouteError(req, res, 400, `Unknown action: ${action}`);
	}
}
