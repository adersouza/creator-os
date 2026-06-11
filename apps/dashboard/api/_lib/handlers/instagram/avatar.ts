/**
 * Instagram Avatar Proxy
 *
 * GET /api/instagram/avatar?accountId=xxx
 *
 * Fetches a fresh profile picture URL from IG API and redirects to it.
 * Solves expired CDN URLs returning 403/CORS errors.
 * Caches the resolved URL for 1 hour.
 */

import { apiError } from "../../apiResponse.js";
import { withAuth } from "../../middleware.js";
import { handleAvatarProxy } from "../helpers/avatarProxy.js";

export default withAuth(async (req, res, user) => {
	if (req.method !== "GET") return apiError(res, 405, "Method not allowed");

	const accountId = req.query.accountId as string;
	if (!accountId) return apiError(res, 400, "accountId required");

	return handleAvatarProxy(res, accountId, { platform: "instagram" }, user.id);
});
