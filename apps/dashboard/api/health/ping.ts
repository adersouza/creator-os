/**
 * Health Ping — Unauthenticated
 *
 * Returns a simple OK response for uptime monitoring.
 * No auth required. For detailed health, use /api/admin/health.
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";
import { apiSuccess } from "../_lib/apiResponse.js";

export default function handler(_req: VercelRequest, res: VercelResponse) {
	return apiSuccess(res, { status: "ok", timestamp: Date.now() });
}
