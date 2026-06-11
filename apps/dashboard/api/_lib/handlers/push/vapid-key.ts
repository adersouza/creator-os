/**
 * VAPID Public Key Endpoint — GET /api/push/vapid-key
 *
 * Returns the VAPID public key needed by the frontend to
 * subscribe to push notifications. No auth required (public key is not secret).
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";
import { apiError, apiSuccess, methodNotAllowed } from "../../apiResponse.js";

export default async function handler(
	req: VercelRequest,
	res: VercelResponse,
): Promise<VercelResponse> {
	if (req.method !== "GET") {
		return methodNotAllowed(res);
	}

	const key = process.env.VAPID_PUBLIC_KEY;
	if (!key) {
		return apiError(res, 503, "Push notifications not configured");
	}

	// #693: Reduced cache TTL from 1 hour to 5 minutes to limit staleness,
	// and support a ?bust query param that bypasses cache for key rotation scenarios
	const bustCache = req.query?.bust !== undefined;
	if (bustCache) {
		res.setHeader("Cache-Control", "no-store");
	} else {
		res.setHeader("Cache-Control", "public, max-age=300");
	}
	return apiSuccess(res, { key });
}
