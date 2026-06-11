/**
 * Public Click Tracking
 * POST /api/link-page/track
 *
 * No auth required — called via navigator.sendBeacon from public link pages.
 * Records clicks to Supabase link_clicks table.
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";
import { apiError, apiSuccess } from "../../apiResponse.js";
import { verifyLinkTrackingToken } from "../../linkTrackingToken.js";
import { logger } from "../../logger.js";
import {
	detectDevice,
	detectPlatform,
	isCrawler,
} from "../../platformDetect.js";
import { checkRateLimit } from "../../rateLimiter.js";
import { getSupabase, getSupabaseAny } from "../../supabase.js";
import { z } from "../../zodCompat.js";

const TrackClickSchema = z.object({
	linkId: z.string().optional(),
	pageId: z.string().min(1, "pageId is required"),
	variantId: z.string().optional(),
	sourceApp: z.string().optional(),
	deviceType: z.string().optional(),
	referrer: z.string().optional(),
	eventName: z.string().max(80).optional(),
	token: z.string().min(1).optional(),
});

interface DbResult<T> {
	data: T | null;
	error?: { message?: string } | null;
}

interface QueryBuilder<T = Record<string, unknown>> {
	select(columns: string): QueryBuilder<T>;
	eq(field: string, value: unknown): QueryBuilder<T>;
	maybeSingle(): Promise<DbResult<T>>;
}

interface SupabaseLike {
	from(table: string): QueryBuilder;
}

// Allowed CORS origins for the track endpoint.
// sendBeacon does not always send an Origin header, so we still process
// requests without one — we just omit the CORS header in that case.
const APP_ORIGIN =
	process.env.APP_URL ||
	(process.env.VERCEL_URL
		? `https://${process.env.VERCEL_URL}`
		: "https://juno33.com");
const ALLOWED_ORIGINS = new Set([APP_ORIGIN]);
try {
	const appHost = new URL(APP_ORIGIN).hostname;
	if (appHost.startsWith("www.")) {
		ALLOWED_ORIGINS.add(APP_ORIGIN.replace("://www.", "://"));
	} else {
		ALLOWED_ORIGINS.add(APP_ORIGIN.replace("://", "://www."));
	}
} catch {
	/* ignore invalid app origin */
}
// Also allow Cloudflare Worker domains if configured
const CF_WORKER_URL = process.env.CLOUDFLARE_WORKER_URL;
if (CF_WORKER_URL) {
	try {
		ALLOWED_ORIGINS.add(new URL(CF_WORKER_URL).origin);
	} catch {
		/* ignore invalid */
	}
}

export default async function handler(req: VercelRequest, res: VercelResponse) {
	// CORS — restrict to known origins. sendBeacon may omit Origin header,
	// so we still process the request but only set CORS headers for known origins.
	const origin = req.headers.origin as string | undefined;
	if (origin && ALLOWED_ORIGINS.has(origin)) {
		res.setHeader("Access-Control-Allow-Origin", origin);
		res.setHeader("Access-Control-Allow-Methods", "POST, OPTIONS");
		res.setHeader("Access-Control-Allow-Headers", "Content-Type");
	}

	if (req.method === "OPTIONS") return res.status(200).end();
	if (req.method !== "POST")
		return apiError(res, 405, "Method not allowed");

	// Rate limit: 100 clicks per hour per IP (fail open — public endpoint)
	const ip =
		(req.headers["x-forwarded-for"] as string)?.split(",")[0]?.trim() ||
		"unknown";
	const rateLimit = await checkRateLimit({
		key: `link-click:${ip}`,
		limit: 100,
		windowSeconds: 3600,
		failMode: "open",
	});
	if (!rateLimit.allowed) {
		return apiError(res, 429, "Too many requests");
	}

	try {
		const body =
			typeof req.body === "string" ? JSON.parse(req.body) : req.body;
		const parsed = TrackClickSchema.safeParse(body);
		if (!parsed.success) {
			return apiError(
				res,
				400,
				`Invalid input: ${parsed.error.issues[0]?.message}`,
			);
		}
		const {
			linkId,
			pageId,
			variantId,
			referrer,
			eventName,
			token,
		} = parsed.data;

		const supabase = getSupabase();
		const serviceDb = getSupabaseAny();

		// Detect platform, device, and crawler using shared utils
		const userAgent = (req.headers["user-agent"] as string) || "";
		const refHeader = (req.headers.referer as string) || "";
		const crawlerDetected = isCrawler(userAgent);
		const detectedPlatform = detectPlatform(userAgent, refHeader);
		const detectedDevice = detectDevice(userAgent);

		if (
			!verifyLinkTrackingToken(token, {
				pageId,
				linkId: linkId || null,
				variantId: variantId || null,
			})
		) {
			logger.warn("[track] Ignoring unsigned or invalid link tracking event", {
				pageId,
				linkId,
				variantId,
			});
			return apiSuccess(res, { ok: true, skipped: true });
		}

		// Extract only referrer origin (strip path + query to avoid storing PII)
		let safeReferrer: string | null = null;
		if (referrer) {
			try {
				safeReferrer = new URL(referrer).origin;
			} catch {
				/* invalid URL */
			}
		}

		const ownership = await validateTrackingOwnership(serviceDb, {
			pageId,
			linkId,
			variantId,
		});
		if (!ownership.valid) {
			logger.warn("[track] Ignoring invalid link tracking ownership", {
				pageId,
				linkId,
				variantId,
				reason: ownership.reason,
			});
			return apiSuccess(res, { ok: true, skipped: true });
		}

		// Insert click record
		const { error: clickErr } = await serviceDb.from("link_clicks").insert({
			link_id: linkId || null,
			page_id: pageId,
			variant_id: variantId || null,
			is_crawler: crawlerDetected,
			referrer: safeReferrer,
			user_agent: userAgent.substring(0, 500),
			country: (req.headers["x-vercel-ip-country"] as string) || null,
			device_type: detectedDevice,
			source_app: detectedPlatform,
			event_name: eventName || null,
		});
		if (clickErr) {
			logger.warn("[track] Failed to insert link_clicks", {
				pageId,
				error: clickErr.message,
			});
		}

		// Increment link click count (fire and forget)
		if (linkId && !crawlerDetected) {
			Promise.resolve(
				supabase.rpc("increment_link_click", { p_link_id: linkId }),
			).catch((err: unknown) =>
				logger.warn("[track] Failed to increment_link_click", {
					error: String(err),
				}),
			);
		}

		// Thompson Sampling: record click as conversion for the variant
		if (variantId && !crawlerDetected) {
			Promise.resolve(
				supabase.rpc(
					"record_variant_click" as never,
					{
						p_variant_id: variantId,
					} as never,
				),
			).catch((err: unknown) =>
				logger.warn("[track] Failed to record_variant_click", {
					error: String(err),
				}),
			);
		}

		return apiSuccess(res, { ok: true });
	} catch (error) {
		// Don't fail the beacon — always return 200
		logger.error("Link page track error", { error: String(error) });
		return apiSuccess(res, { ok: true });
	}
}

async function validateTrackingOwnership(
	supabase: unknown,
	params: {
		pageId: string;
		linkId?: string | undefined;
		variantId?: string | undefined;
	},
): Promise<{ valid: true } | { valid: false; reason: string }> {
	const client = supabase as SupabaseLike;
	const pageResult = await client
		.from("link_pages")
		.select("id")
		.eq("id", params.pageId)
		.eq("is_published", true)
		.maybeSingle();
	if (typeof pageResult.data?.id !== "string")
		return { valid: false, reason: "page_not_found" };

	if (params.linkId) {
		const linkResult = await client
			.from("link_items")
			.select("id")
			.eq("id", params.linkId)
			.eq("page_id", params.pageId)
			.maybeSingle();
		if (typeof linkResult.data?.id !== "string")
			return { valid: false, reason: "link_page_mismatch" };
	}

	if (params.variantId) {
		const variantResult = await client
			.from("link_page_variants")
			.select("id")
			.eq("id", params.variantId)
			.eq("page_id", params.pageId)
			.eq("is_active", true)
			.maybeSingle();
		if (typeof variantResult.data?.id !== "string")
			return { valid: false, reason: "variant_page_mismatch" };
	}

	return { valid: true };
}
