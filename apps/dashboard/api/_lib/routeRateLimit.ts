import type { VercelRequest, VercelResponse } from "@vercel/node";
import { apiError } from "./apiResponse.js";
import { checkRateLimit } from "./rateLimiter.js";

type RateLimitFailMode = "open" | "closed";

export function getClientIp(req: VercelRequest): string {
	const forwardedFor = req.headers["x-forwarded-for"];
	const firstForwarded =
		typeof forwardedFor === "string"
			? forwardedFor.split(",")[0]?.trim()
			: Array.isArray(forwardedFor)
				? forwardedFor[0]?.split(",")[0]?.trim()
				: undefined;
	const realIp = req.headers["x-real-ip"];
	const normalizedRealIp = Array.isArray(realIp) ? realIp[0] : realIp;

	return firstForwarded || normalizedRealIp || "unknown";
}

export async function enforceRouteRateLimit(
	res: VercelResponse,
	options: {
		key: string;
		limit: number;
		windowSeconds: number;
		failMode: RateLimitFailMode;
		message?: string | undefined;
	},
): Promise<boolean> {
	const result = await checkRateLimit(options).catch((error) => ({
		allowed: options.failMode === "open",
		remaining: options.failMode === "open" ? options.limit : 0,
		retryAfterSeconds: options.failMode === "closed" ? 30 : undefined,
		reason: "redis_unavailable" as const,
		error,
	}));

	res.setHeader("X-RateLimit-Limit", String(options.limit));
	res.setHeader("X-RateLimit-Remaining", String(result.remaining));

	if (result.allowed) {
		return true;
	}

	res.setHeader(
		"Retry-After",
		String(result.retryAfterSeconds || options.windowSeconds),
	);

	apiError(
		res,
		429,
		options.message ||
			(result.reason === "redis_unavailable"
				? "Service temporarily unavailable. Please try again shortly."
				: "Rate limit exceeded"),
	);
	return false;
}
