/**
 * Public Link Redirect
 * GET /api/go/r/{redirectId}
 *
 * Public endpoint — no auth required.
 * Resolves a masked link redirect_id to the actual URL and 302 redirects.
 * Click tracking via increment_link_click RPC (same as link-page track).
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";
import { apiError } from "../../_lib/apiResponse.js";
import { validatePublicRedirectUrl } from "../../_lib/outboundUrlSecurity.js";
import {
	detectDevice,
	detectPlatform,
	isCrawler,
} from "../../_lib/platformDetect.js";

const CACHE_TTL = 300; // 5 minutes
const VALID_REDIRECT_ID = /^[a-zA-Z0-9]{1,12}$/;

interface RedirectCacheEntry {
	url: string;
	linkId: string;
	pageId: string;
}

function notFoundHtml(baseUrl: string): string {
	return `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Link Not Found</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{background:#09090b;color:#fff;font-family:-apple-system,BlinkMacSystemFont,sans-serif;display:flex;align-items:center;justify-content:center;min-height:100vh;text-align:center}
.c{padding:24px}
h1{font-size:48px;margin-bottom:8px;color:#71717a}
p{color:#a1a1aa;font-size:16px;margin-bottom:24px}
a{color:#3b82f6;text-decoration:none;font-size:14px}
</style>
</head>
<body>
<div class="c">
<h1>404</h1>
<p>This link could not be found.</p>
<a href="${baseUrl}">Go to Juno</a>
</div>
</body>
</html>`;
}

/**
 * Attempt to get from Redis, failing open if unavailable.
 */
async function redisGet(key: string): Promise<string | null> {
	try {
		const { getRedis } = await import("../../_lib/redis.js");
		const val = await getRedis().get(key);
		return typeof val === "string" ? val : null;
	} catch {
		return null;
	}
}

async function redisSet(
	key: string,
	value: string,
	ttl: number,
): Promise<void> {
	try {
		const { getRedis } = await import("../../_lib/redis.js");
		await getRedis().set(key, value, { ex: ttl });
	} catch {
		// fail-open
	}
}

function parseRedirectCache(value: string): RedirectCacheEntry | null {
	try {
		const parsed = JSON.parse(value) as Partial<RedirectCacheEntry>;
		if (
			typeof parsed.url === "string" &&
			typeof parsed.linkId === "string" &&
			typeof parsed.pageId === "string"
		) {
			return {
				url: parsed.url,
				linkId: parsed.linkId,
				pageId: parsed.pageId,
			};
		}
	} catch {
		// Older cache entries stored only the URL; ignore them so the DB path can
		// refresh cache with analytics metadata.
	}
	return null;
}

export default async function handler(req: VercelRequest, res: VercelResponse) {
	const baseUrl =
		process.env.APP_URL ||
		(process.env.VERCEL_URL
			? `https://${process.env.VERCEL_URL}`
			: "https://juno33.com");

	if (req.method !== "GET") {
		return apiError(res, 405, "Method not allowed");
	}

	const redirectId = req.query.redirectId as string;
	if (!redirectId || !VALID_REDIRECT_ID.test(redirectId)) {
		res.setHeader("Content-Type", "text/html; charset=utf-8");
		return res.status(404).send(notFoundHtml(baseUrl));
	}

	const cacheKey = `redirect:${redirectId}`;

	// ── Step 1: Check Redis cache ──────────────────────────────────────────
	const cachedValue = await redisGet(cacheKey);
	const cached = cachedValue ? parseRedirectCache(cachedValue) : null;
	if (cached) {
		if (await validatePublicRedirectUrl(cached.url, "masked-link-cache")) {
			res.setHeader("Content-Type", "text/html; charset=utf-8");
			return res.status(404).send(notFoundHtml(baseUrl));
		}
		trackRedirectClick(cached, req).catch(() => {});
		res.setHeader("Cache-Control", "private, no-cache");
		return res.redirect(302, cached.url);
	}

	// ── Step 2: Query Supabase ─────────────────────────────────────────────
	try {
		const { getPrivilegedSupabaseAny, PRIVILEGED_DB_REASONS } = await import(
			"../../_lib/privilegedDb.js"
		);
		const supabase = getPrivilegedSupabaseAny(
			PRIVILEGED_DB_REASONS.publicLinkRedirect,
		);

		const { data: item, error } = await supabase
			.from("link_items")
			.select("id, url, page_id")
			.eq("redirect_id", redirectId)
			.maybeSingle();

		if (error || !item) {
			res.setHeader("Content-Type", "text/html; charset=utf-8");
			return res.status(404).send(notFoundHtml(baseUrl));
		}

		if (await validatePublicRedirectUrl(item.url, "masked-link-item")) {
			res.setHeader("Content-Type", "text/html; charset=utf-8");
			return res.status(404).send(notFoundHtml(baseUrl));
		}

		// ── Step 3: Cache the URL ──────────────────────────────────────────
		await redisSet(
			cacheKey,
			JSON.stringify({ url: item.url, linkId: item.id, pageId: item.page_id }),
			CACHE_TTL,
		);

		// ── Step 4: Track click ────────────────────────────────────────────
		trackRedirectClick(
			{ url: item.url, linkId: item.id, pageId: item.page_id },
			req,
		).catch(() => {});

		// ── Step 5: Redirect ───────────────────────────────────────────────
		res.setHeader("Cache-Control", "private, no-cache");
		return res.redirect(302, item.url);
	} catch (err) {
		const { logger } = await import("../../_lib/logger.js");
		logger.error("[redirect] Error", {
			error: String(err),
			redirectId,
		});
		res.setHeader("Content-Type", "text/html; charset=utf-8");
		return res.status(500).send("Internal server error");
	}
}

async function trackRedirectClick(
	entry: RedirectCacheEntry,
	req: VercelRequest,
): Promise<void> {
	const userAgent = (req.headers["user-agent"] as string) || "";
	const crawlerDetected = isCrawler(userAgent);
	const { getPrivilegedSupabaseAny, PRIVILEGED_DB_REASONS } = await import(
		"../../_lib/privilegedDb.js"
	);
	const supabase = getPrivilegedSupabaseAny(
		PRIVILEGED_DB_REASONS.publicLinkRedirect,
	);

	if (!crawlerDetected) {
		await supabase.rpc("increment_link_click", { p_link_id: entry.linkId });
	}

	await supabase.from("link_clicks").insert({
		link_id: entry.linkId,
		page_id: entry.pageId,
		referrer: safeReferrerOrigin(req.headers.referer as string),
		user_agent: userAgent.substring(0, 500),
		country: (req.headers["x-vercel-ip-country"] as string) || null,
		is_crawler: crawlerDetected,
		device_type: detectDevice(userAgent),
		source_app: detectPlatform(userAgent, (req.headers.referer as string) || ""),
		event_name: "redirect",
	});
}

/** Extract only the origin from a referrer URL to avoid storing PII */
function safeReferrerOrigin(ref: string | null | undefined): string | null {
	if (!ref) return null;
	try {
		return new URL(ref).origin;
	} catch {
		return null;
	}
}
