/**
 * Favicon Proxy with Redis Caching
 * GET /api/favicon?url=https://example.com
 *
 * Public endpoint — no auth required.
 * Fetches and caches favicon URLs for external domains.
 * Returns 302 redirect to the discovered favicon URL.
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";
import { apiError } from "./_lib/apiResponse.js";
import {
	fetchPublicUrlWithRedirects,
	validatePublicRedirectUrl,
} from "./_lib/outboundUrlSecurity.js";

const CACHE_TTL = 86400; // 24 hours
const FETCH_TIMEOUT = 3000; // 3 seconds
const MAX_HTML_BYTES = 50 * 1024; // 50KB

/** Fallback globe SVG as a data URI */
const FALLBACK_FAVICON =
	"data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%23888' stroke-width='2'%3E%3Ccircle cx='12' cy='12' r='10'/%3E%3Cpath d='M2 12h20M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z'/%3E%3C/svg%3E";

const CACHE_HEADERS = {
	"Cache-Control": "public, s-maxage=86400, stale-while-revalidate=604800",
};

/**
 * Attempt to get/set from Redis, failing open if Redis is unavailable.
 */
async function redisGet(key: string): Promise<string | null> {
	try {
		const { getRedis } = await import("./_lib/redis.js");
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
		const { getRedis } = await import("./_lib/redis.js");
		await getRedis().set(key, value, { ex: ttl });
	} catch {
		// fail-open
	}
}

/**
 * Parse <link rel="icon"> or <link rel="shortcut icon"> from HTML.
 * Returns the href attribute value or null.
 */
function parseFaviconFromHtml(html: string): string | null {
	// Match <link ... rel="icon" ... href="..." ...> or rel="shortcut icon"
	const linkRegex =
		/<link\s[^>]*rel\s*=\s*["'](?:shortcut\s+icon|icon)["'][^>]*>/gi;
	let match: RegExpExecArray | null;
	// biome-ignore lint/suspicious/noAssignInExpressions: regex exec loop
	while ((match = linkRegex.exec(html)) !== null) {
		const hrefMatch = /href\s*=\s*["']([^"']+)["']/.exec(match[0]);
		if (hrefMatch?.[1]) {
			return hrefMatch[1];
		}
	}

	// Also try href before rel (order varies)
	const linkRegex2 =
		/<link\s[^>]*href\s*=\s*["']([^"']+)["'][^>]*rel\s*=\s*["'](?:shortcut\s+icon|icon)["'][^>]*>/gi;
	// biome-ignore lint/suspicious/noAssignInExpressions: regex exec loop
	while ((match = linkRegex2.exec(html)) !== null) {
		if (match[1]) {
			return match[1];
		}
	}

	return null;
}

/**
 * Resolve a potentially relative favicon URL against the page origin.
 */
function resolveUrl(href: string, origin: string): string {
	try {
		return new URL(href, origin).href;
	} catch {
		return href;
	}
}

function redirect(res: VercelResponse, url: string): VercelResponse {
	for (const [k, v] of Object.entries(CACHE_HEADERS)) {
		res.setHeader(k, v);
	}
	return res.redirect(302, url);
}

export default async function handler(req: VercelRequest, res: VercelResponse) {
	if (req.method !== "GET") {
		return apiError(res, 405, "Method not allowed");
	}

	const url = req.query.url as string;
	if (!url) {
		return apiError(res, 400, "Missing url parameter");
	}

	if (await validatePublicRedirectUrl(url, "favicon-input")) {
		return apiError(res, 400, "Invalid or blocked URL");
	}

	let parsed: URL;
	try {
		parsed = new URL(url);
	} catch {
		return apiError(res, 400, "Invalid URL");
	}

	const domain = parsed.hostname;
	const origin = parsed.origin;
	const cacheKey = `favicon:${domain}`;

	// ── Step 1: Check Redis cache ──────────────────────────────────────────
	const cached = await redisGet(cacheKey);
	if (cached) {
		if (cached === FALLBACK_FAVICON) return sendFallback(res);
		if (!(await validatePublicRedirectUrl(cached, "favicon-cache"))) {
			return redirect(res, cached);
		}
		await redisSet(cacheKey, FALLBACK_FAVICON, 3600);
		return sendFallback(res);
	}

	// ── Step 2: Try /favicon.ico ───────────────────────────────────────────
	try {
		const controller = new AbortController();
		const timeout = setTimeout(() => controller.abort(), FETCH_TIMEOUT);

		const faviconUrl = `${origin}/favicon.ico`;
		const faviconRes = await fetchPublicUrlWithRedirects(
			faviconUrl,
			"favicon-ico",
			{
				signal: controller.signal,
				headers: { "User-Agent": "JunoFaviconBot/1.0" },
			},
		);
		clearTimeout(timeout);

		if (
			faviconRes?.ok &&
			faviconRes.headers.get("content-type")?.startsWith("image/")
		) {
			await redisSet(cacheKey, faviconUrl, CACHE_TTL);
			return redirect(res, faviconUrl);
		}
	} catch {
		// favicon.ico failed — try HTML parsing
	}

	// ── Step 3: Fetch page HTML and parse for <link rel="icon"> ────────────
	try {
		const controller = new AbortController();
		const timeout = setTimeout(() => controller.abort(), FETCH_TIMEOUT);

		const pageRes = await fetchPublicUrlWithRedirects(origin, "favicon-page", {
			signal: controller.signal,
			headers: { "User-Agent": "JunoFaviconBot/1.0" },
		});
		clearTimeout(timeout);

		if (pageRes?.ok) {
			// Read only up to MAX_HTML_BYTES
			const reader = pageRes.body?.getReader();
			if (reader) {
				let html = "";
				let totalBytes = 0;
				const decoder = new TextDecoder();

				while (true) {
					const { done, value } = await reader.read();
					if (done) break;
					totalBytes += value.byteLength;
					html += decoder.decode(value, { stream: true });
					if (totalBytes >= MAX_HTML_BYTES) break;
				}
				reader.cancel().catch(() => {});

				const href = parseFaviconFromHtml(html);
				if (href) {
					const resolved = resolveUrl(href, origin);
					if (await validatePublicRedirectUrl(resolved, "favicon-discovered")) {
						return sendFallback(res);
					}
					await redisSet(cacheKey, resolved, CACHE_TTL);
					return redirect(res, resolved);
				}
			}
		}
	} catch {
		// HTML parsing failed — fall through to fallback
	}

	// ── Step 4: Fallback to globe SVG ──────────────────────────────────────
	// Cache the fallback too (shorter TTL to allow re-check sooner)
	await redisSet(cacheKey, FALLBACK_FAVICON, 3600); // 1 hour for fallback
	return sendFallback(res);
}

function sendFallback(res: VercelResponse): VercelResponse {
	for (const [k, v] of Object.entries(CACHE_HEADERS)) {
		res.setHeader(k, v);
	}
	res.setHeader("Content-Type", "image/svg+xml; charset=utf-8");
	return res
		.status(200)
		.send(
			'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="#888" stroke-width="2"><circle cx="12" cy="12" r="10"/><path d="M2 12h20M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/></svg>',
		);
}
