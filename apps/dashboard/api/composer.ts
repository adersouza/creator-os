import type { VercelRequest, VercelResponse } from "@vercel/node";
import { authenticatedRouteError } from "./_lib/apiResponse.js";

export const config = { maxDuration: 60 };

export default async function handler(req: VercelRequest, res: VercelResponse) {
	const action = (req.query.action as string) || "";
	switch (action) {
		case "health-pills":
			return (await import("./_lib/handlers/composer/health-pills.js")).default(req, res);
		case "variants":
			return (await import("./_lib/handlers/composer/variants.js")).default(req, res);
		case "critique":
			return (await import("./_lib/handlers/composer/critique.js")).default(req, res);
		case "diffs":
			return (await import("./_lib/handlers/composer/diffs.js")).default(req, res);
		case "voice-file":
			return (await import("./_lib/handlers/composer/voice-file.js")).default(req, res);
		case "ai-action-log":
			return (await import("./_lib/handlers/composer/ai-action-log.js")).default(req, res);
		default:
			return authenticatedRouteError(req, res, 400, `Unknown composer action: ${action}`);
	}
}
