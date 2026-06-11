// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
/**
 * Sentry Tunnel Endpoint
 * Proxies Sentry events through our own domain to bypass Safari ITP
 * and ad-blockers that block direct requests to *.sentry.io.
 *
 * Only forwards to the configured Sentry project — rejects everything else.
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";
import { apiError, apiSuccess } from "./_lib/apiResponse.js";
import { checkRateLimit } from "./_lib/rateLimiter.js";

// Sentry envelopes contain full stack traces + breadcrumbs but rarely exceed
// 500KB even at the high end. The prior 5mb cap × 200/min/IP allowed up to
// 1GB/min outbound to our own Sentry project (cost-burn, not data leak).
// 1mb is still 2x normal envelope size, capping max abuse at 200MB/min/IP.
export const config = {
	api: {
		bodyParser: {
			sizeLimit: "1mb",
		},
	},
};

// Allowed Sentry host(s) — only forward to our own project
const SENTRY_HOST = "o4510910982914048.ingest.us.sentry.io";
const SENTRY_PROJECT_IDS = ["4510910992547840"];
const APP_ORIGIN =
	process.env.APP_URL ||
	(process.env.VERCEL_URL
		? `https://${process.env.VERCEL_URL}`
		: "https://juno33.com");

export default async function handler(req: VercelRequest, res: VercelResponse) {
	if (req.method === "OPTIONS") {
		res.setHeader("Access-Control-Allow-Origin", APP_ORIGIN);
		res.setHeader("Access-Control-Allow-Methods", "POST");
		res.setHeader("Access-Control-Allow-Headers", "Content-Type");
		return res.status(204).end();
	}

	// #640: Set CORS on all responses (not just OPTIONS)
	res.setHeader("Access-Control-Allow-Origin", APP_ORIGIN);

	if (req.method !== "POST") {
		return apiError(res, 405, "Method not allowed");
	}

	// Rate limit by IP: 200 req/min — Sentry batches envelopes but can burst during error storms.
	// fail-open: losing some Sentry events is better than blocking real users.
	const ip =
		(req.headers["x-forwarded-for"] as string)?.split(",")[0]?.trim() ||
		"unknown";
	const rl = await checkRateLimit({
		key: `sentry-tunnel:${ip}`,
		limit: 200,
		windowSeconds: 60,
		failMode: "open",
	});
	if (!rl.allowed) {
		// Retry-After tells Sentry SDK to back off instead of hammering
		res.setHeader("Retry-After", "60");
		return apiError(res, 429, "Too many requests");
	}

	try {
		// The body is a Sentry envelope: first line is JSON header with dsn
		const rawBody =
			typeof req.body === "string" ? req.body : JSON.stringify(req.body);
		const firstLine = rawBody.split("\n")[0];
		const header = JSON.parse(firstLine!);
		const dsn = new URL(header.dsn);

		// Validate the request is for our Sentry project. Pull the first
		// non-empty path segment as the projectId rather than concatenating
		// every slash-stripped char (which would silently transform
		// `/123/extra` into `123extra` and also `/123/` into `123` —
		// inconsistent matching across DSN URL shapes).
		const projectId = dsn.pathname.split("/").filter(Boolean)[0] ?? "";
		if (
			dsn.hostname !== SENTRY_HOST ||
			!SENTRY_PROJECT_IDS.includes(projectId)
		) {
			return apiError(res, 400, "Invalid Sentry project");
		}

		// Forward to Sentry
		const sentryUrl = `https://${SENTRY_HOST}/api/${projectId}/envelope/`;
		const response = await fetch(sentryUrl, {
			method: "POST",
			headers: { "Content-Type": "application/x-sentry-envelope" },
			body: rawBody,
			signal: AbortSignal.timeout(5_000),
		});

		return apiSuccess(res, { status: "ok" }, response.status);
	} catch {
		// Don't leak errors — Sentry tunnel failures are non-critical
		return apiSuccess(res, { status: "ok" });
	}
}
