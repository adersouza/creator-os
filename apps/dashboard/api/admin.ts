/**
 * Admin API Route — Thin Router
 *
 * /api/admin?action=<action>
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";
import { apiError } from "./_lib/apiResponse.js";
import { withAdminRole } from "./_lib/middleware.js";

// Defense-in-depth: wrap entire admin router with withAdminRole so that
// even unknown actions get a 403 instead of leaking that this is an admin endpoint.
export default withAdminRole(
	async (req: VercelRequest, res: VercelResponse) => {
		const action = (req.query.action as string) || "";
		switch (action) {
			case "health":
				return (await import("./_lib/handlers/admin/health.js")).default(
					req,
					res,
				);
			case "dead-letters":
				return (await import("./_lib/handlers/admin/dead-letters.js")).default(
					req,
					res,
				);
			case "feature-usage":
				return (await import("./_lib/handlers/admin/feature-usage.js")).default(
					req,
					res,
				);
			case "monthly-kpi":
				return (await import("./_lib/handlers/admin/monthly-kpi.js")).default(
					req,
					res,
				);
			case "north-star":
				return (await import("./_lib/handlers/admin/north-star.js")).default(
					req,
					res,
				);
			case "power-users":
				return (await import("./_lib/handlers/admin/power-users.js")).default(
					req,
					res,
				);
			case "arl":
				return (await import("./_lib/handlers/admin/arl.js")).default(req, res);
			case "token-health":
				return (await import("./_lib/handlers/admin/token-health.js")).default(
					req,
					res,
				);
			default:
				return apiError(res, 400, `Unknown action: ${action}`);
		}
	},
);
