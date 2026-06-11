/**
 * Conversion Postback Endpoint
 * GET /api/go/convert?code=abc123&value=49.99&order_id=ORD-001&sig=...
 *
 * Public endpoint — no auth required.
 * Affiliate networks / tracking pixels ping this on sale.
 * Deduplicates via unique(smart_link_id, order_id).
 * Attributes to most recent click within 30-day window.
 *
 * HMAC-SHA256 signature verification: sig = HMAC(webhook_secret, code+order_id+value)
 * Conversion postbacks must be HMAC signed. Links missing a webhook_secret are
 * treated as not configured and rejected instead of accepting forged revenue.
 */

import * as crypto from "node:crypto";
import type { VercelRequest, VercelResponse } from "@vercel/node";
import { apiError, apiSuccess } from "../_lib/apiResponse.js";
import { logger } from "../_lib/logger.js";
import {
	getPrivilegedSupabase,
	PRIVILEGED_DB_REASONS,
} from "../_lib/privilegedDb.js";
import { checkRateLimit } from "../_lib/rateLimiter.js";

const MAX_CONVERSION_VALUE = 1_000_000;
const ORDER_ID_PATTERN = /^[a-zA-Z0-9._:-]{1,120}$/;
const CODE_PATTERN = /^[a-zA-Z0-9_-]{2,64}$/;
const SIG_PATTERN = /^[a-f0-9]{64}$/i;

export default async function handler(req: VercelRequest, res: VercelResponse) {
	if (req.method !== "GET") {
		return apiError(res, 405, "Method not allowed");
	}

	const appOrigin =
		process.env.APP_URL ||
		(process.env.VERCEL_URL
			? `https://${process.env.VERCEL_URL}`
			: "https://juno33.com");
	res.setHeader("Access-Control-Allow-Origin", appOrigin);

	const code = req.query.code as string;
	const valueStr = req.query.value as string;
	const orderId = req.query.order_id as string;
	const sig = req.query.sig as string | undefined;
	const currency = ((req.query.currency as string) || "USD")
		.toUpperCase()
		.slice(0, 3);
	const source = ((req.query.source as string) || "postback").slice(0, 50);

	if (!code || !orderId) {
		return apiError(res, 400, "code and order_id are required");
	}
	if (!CODE_PATTERN.test(code)) {
		return apiError(res, 400, "Invalid code");
	}
	if (!ORDER_ID_PATTERN.test(orderId)) {
		return apiError(res, 400, "Invalid order_id");
	}

	const value = parseFloat(valueStr || "0");
	if (!Number.isFinite(value) || value < 0 || value > MAX_CONVERSION_VALUE) {
		return apiError(res, 400, "Invalid value");
	}

	// Rate limit: 100/hour per IP (fail open)
	const ip =
		(req.headers["x-forwarded-for"] as string)?.split(",")[0]?.trim() ||
		"unknown";
	const rl = await checkRateLimit({
		key: `convert:${ip}`,
		limit: 100,
		windowSeconds: 3600,
		failMode: "open",
	});
	if (!rl.allowed) {
		return apiError(res, 429, "Too many requests");
	}

	try {
		const db = getPrivilegedSupabase(
			PRIVILEGED_DB_REASONS.publicLinkConversion,
		);

		// Look up smart link by code (include webhook_secret for HMAC verification)
		const { data: link, error: linkErr } = await db
			.from("smart_links")
			.select("id, webhook_secret")
			.eq("code", code)
			.eq("is_active", true)
			.maybeSingle();

		if (linkErr || !link) {
			return apiError(res, 404, "Smart link not found");
		}

		// HMAC-SHA256 signature verification
		if (!link.webhook_secret) {
			logger.warn("[convert] Rejected unsigned conversion for unconfigured link", {
				code,
				orderId,
			});
			return apiError(res, 403, "Conversion tracking is not configured");
		}
		if (!sig || !SIG_PATTERN.test(sig)) {
			return apiError(res, 401, "Missing or invalid signature");
		}
		const payload = `${code}${orderId}${valueStr || "0"}`;
		const expectedSig = crypto
			.createHmac("sha256", link.webhook_secret)
			.update(payload)
			.digest("hex");
		if (!crypto.timingSafeEqual(Buffer.from(sig), Buffer.from(expectedSig))) {
			return apiError(res, 403, "Invalid signature");
		}

		// Attribute to most recent click within 30-day window
		const thirtyDaysAgo = new Date(Date.now() - 30 * 86400000).toISOString();
		const { data: recentClick } = await db
			.from("smart_link_clicks")
			.select("id")
			.eq("smart_link_id", link.id)
			.gte("clicked_at", thirtyDaysAgo)
			.order("clicked_at", { ascending: false })
			.limit(1)
			.maybeSingle();

		// Insert conversion (dedup via unique constraint)
		const { error: insertErr } = await db
			.from("smart_link_conversions")
			.insert({
				smart_link_id: link.id,
				click_id: recentClick?.id || null,
				order_id: orderId,
				conversion_value: value,
				currency,
				source,
				ip_address: crypto
					.createHash("sha256")
					.update(ip)
					.digest("hex")
					.slice(0, 16),
			});

		if (insertErr) {
			// Check for unique constraint violation (duplicate order_id)
			if (insertErr.code === "23505") {
				return apiSuccess(res, { status: "duplicate", order_id: orderId });
			}
			logger.error("[convert] Insert error", {
				error: String(insertErr),
				code,
				orderId,
			});
			return apiError(res, 500, "Failed to record conversion");
		}

		return apiSuccess(res, { status: "recorded", order_id: orderId });
	} catch (err) {
		logger.error("[convert] Error", { error: String(err), code });
		return apiError(res, 500, "Internal server error");
	}
}
