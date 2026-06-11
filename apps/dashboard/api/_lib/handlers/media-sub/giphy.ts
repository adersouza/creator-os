/**
 * GIPHY proxy — keeps API key server-side (CP-03)
 * GET /api/giphy?action=search&q=...
 * GET /api/giphy?action=trending
 * Merged from api/giphy.ts
 */

import { apiError, apiSuccess, rateLimited } from "../../apiResponse.js";
import { withAuth } from "../../middleware.js";
import { checkRateLimit } from "../../rateLimiter.js";
import { parseQueryOrError } from "../../validation.js";
import { z, zEnum } from "../../zodCompat.js";

const GiphyQuerySchema = z.object({
	action: zEnum(["search", "trending"]),
	q: z.string().optional(),
	limit: z.string().optional(),
});

const GIPHY_API_KEY = process.env.GIPHY_API_KEY || "";

export default withAuth(async (req, res, user) => {
	if (req.method !== "GET") return apiError(res, 405, "Method not allowed");

	if (!GIPHY_API_KEY) {
		return apiError(res, 500, "GIPHY API key not configured");
	}

	const rl = await checkRateLimit({
		key: `giphy:${user.id}`,
		limit: 30,
		windowSeconds: 60,
		failMode: "open",
	});
	if (!rl.allowed) return rateLimited(res);

	const parsed = parseQueryOrError(res, GiphyQuerySchema, req.query);
	if (!parsed) return;
	const { action, q, limit } = parsed;
	const safeLimit = Math.min(Number(limit) || 20, 50);

	let url: string;
	if (action === "search" && typeof q === "string" && q.trim()) {
		url = `https://api.giphy.com/v1/gifs/search?q=${encodeURIComponent(q)}&api_key=${GIPHY_API_KEY}&limit=${safeLimit}&rating=g`;
	} else if (action === "trending") {
		url = `https://api.giphy.com/v1/gifs/trending?api_key=${GIPHY_API_KEY}&limit=${safeLimit}&rating=g`;
	} else {
		return apiError(
			res,
			400,
			"Invalid action. Use ?action=search&q=... or ?action=trending",
		);
	}

	try {
		const response = await fetch(url);
		if (!response.ok) {
			return apiError(res, response.status, "GIPHY API error");
		}
		const data = await response.json();
		res.setHeader(
			"Cache-Control",
			"public, s-maxage=300, stale-while-revalidate=600",
		);
		return apiSuccess(res, data);
	} catch {
		return apiError(res, 502, "Failed to fetch from GIPHY");
	}
});
