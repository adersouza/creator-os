/**
 * Threads Avatar Proxy
 *
 * GET /api/threads/avatar?accountId=xxx
 *
 * Fetches a fresh profile picture URL from Threads API and redirects to it.
 * Solves expired CDN URLs returning 403/CORS errors.
 * Caches the resolved URL for 1 hour.
 *
 * Uses withCors (no Bearer auth) because <img> tags cannot send
 * Authorization headers. The handler decrypts the stored token to call the
 * Threads API on behalf of that account, so an enumerated `accountId` could
 * burn an arbitrary user's API quota. To cap that blast radius, the route
 * enforces a per-IP rate limit fail-closed (Redis outage = reject). The
 * resolved data is just a public profile picture, matching the
 * competitor-avatar pattern.
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";
import { apiError } from "../../apiResponse.js";
import { withCors } from "../../middleware.js";
import {
	enforceRouteRateLimit,
	getClientIp,
} from "../../routeRateLimit.js";
import { handleAvatarProxy } from "../helpers/avatarProxy.js";

export default withCors(async (req: VercelRequest, res: VercelResponse) => {
	if (req.method !== "GET") return apiError(res, 405, "Method not allowed");

	const accountId = req.query.accountId as string;
	if (!accountId) return apiError(res, 400, "accountId required");

	const ip = getClientIp(req);
	const ok = await enforceRouteRateLimit(res, {
		key: `threads-avatar:${ip}`,
		limit: 120,
		windowSeconds: 60,
		failMode: "closed",
	});
	if (!ok) return undefined;

	return handleAvatarProxy(res, accountId, { platform: "threads" });
});
