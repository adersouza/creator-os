/**
 * Instagram API Route — Thin Router
 *
 * /api/instagram?action=<action>
 *
 * IMPORTANT: Handlers that use their own ?action= sub-routing MUST remain
 * as standalone files under api/instagram/<name>.ts — the Vercel rewrite
 * (/api/instagram/:action → /api/instagram?action=:action) drops the
 * original query string, so sub-actions would be lost.
 *
 * Standalone files (filesystem routes take priority over rewrites):
 *   auto-responders, collaboration, comments, dm-templates, hashtags,
 *   insights, media, mentions, messages, messenger-profile,
 *   webhook.ts, webhook-subscribe.ts
 *
 * Only handlers WITHOUT their own sub-routing belong in this switch.
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";
import { authenticatedRouteError } from "./_lib/apiResponse.js";

export const config = { maxDuration: 30 };

export default async function handler(req: VercelRequest, res: VercelResponse) {
	const action = (req.query.action as string) || "";
	switch (action) {
		case "avatar":
			return (await import("./_lib/handlers/instagram/avatar.js")).default(
				req,
				res,
			);
		case "flush-insights-cache":
			return (
				await import("./_lib/handlers/instagram/flush-insights-cache.js")
			).default(req, res);
		case "media-proxy":
			return (await import("./_lib/handlers/instagram/media-proxy.js")).default(
				req,
				res,
			);
		case "online-followers":
			return (
				await import("./_lib/handlers/instagram/online-followers.js")
			).default(req, res);
		case "saved-media":
			return (await import("./_lib/handlers/instagram/saved-media.js")).default(
				req,
				res,
			);
		case "stories":
			return (await import("./_lib/handlers/instagram/stories.js")).default(
				req,
				res,
			);
		default:
			return authenticatedRouteError(req, res, 400, `Unknown action: ${action}`);
	}
}
