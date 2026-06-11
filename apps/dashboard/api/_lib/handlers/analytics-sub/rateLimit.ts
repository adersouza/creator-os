import type { VercelResponse } from "@vercel/node";
import { apiError } from "../../apiResponse.js";
import { checkRateLimit } from "../../rateLimiter.js";

export async function enforceAnalyticsSubRateLimit(
	res: VercelResponse,
	options: {
		userId: string;
		action: string;
		limit?: number | undefined;
		windowSeconds?: number | undefined;
	},
): Promise<boolean> {
	const limit = options.limit ?? 30;
	const windowSeconds = options.windowSeconds ?? 60;
	const result = await checkRateLimit({
		key: `analytics-sub:${options.action}:${options.userId}`,
		limit,
		windowSeconds,
		failMode: "closed",
	});

	res.setHeader("X-RateLimit-Limit", String(limit));
	res.setHeader("X-RateLimit-Remaining", String(result.remaining));

	if (result.allowed) return true;

	res.setHeader(
		"Retry-After",
		String(result.retryAfterSeconds || windowSeconds),
	);
	apiError(
		res,
		429,
		result.reason === "redis_unavailable"
			? "Analytics is temporarily unavailable. Please try again shortly."
			: "Analytics rate limit exceeded. Please slow down.",
	);
	return false;
}
