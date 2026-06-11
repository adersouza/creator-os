/**
 * User API Route — Thin Router
 * /api/user?action=<action>
 */
import type { VercelRequest, VercelResponse } from "@vercel/node";
import { authenticatedRouteError } from "./_lib/apiResponse.js";

export default async function handler(req: VercelRequest, res: VercelResponse) {
	const action = (req.query.action as string) || "";
	switch (action) {
		case "growth-journal":
			return (await import("./_lib/handlers/user/growth-journal.js")).default(
				req,
				res,
			);
		case "branding":
			return (await import("./_lib/handlers/user/branding.js")).default(
				req,
				res,
			);
		case "annual-recap":
			return (await import("./_lib/handlers/user/annual-recap.js")).default(
				req,
				res,
			);
		case "data-contribution":
			return (
				await import("./_lib/handlers/user/data-contribution.js")
			).default(req, res);
		case "delete":
			return (await import("./_lib/handlers/user/delete.js")).default(req, res);
		case "export-status":
			return (await import("./_lib/handlers/user/export-status.js")).default(
				req,
				res,
			);
		case "export":
			return (await import("./_lib/handlers/user/export.js")).default(req, res);
		case "rec-profile":
			return (await import("./_lib/handlers/user/rec-profile.js")).default(
				req,
				res,
			);
		default:
			return authenticatedRouteError(req, res, 400, `Unknown action: ${action}`);
	}
}
