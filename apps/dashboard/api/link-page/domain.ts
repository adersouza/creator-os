// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
/**
 * Custom Domain Resolver
 * GET /api/link-page/domain
 *
 * Vercel rewrites custom domain requests here via host-based rewrite.
 * Looks up the domain in link_pages.custom_domain or smart_links.custom_domain,
 * then renders the public page/link by delegating to the canonical handlers.
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";
import { apiError } from "../_lib/apiResponse.js";
import { logger } from "../_lib/logger.js";
import {
	getPrivilegedSupabaseAny,
	PRIVILEGED_DB_REASONS,
} from "../_lib/privilegedDb.js";
import { checkRateLimit } from "../_lib/rateLimiter.js";

export default async function handler(req: VercelRequest, res: VercelResponse) {
	if (req.method !== "GET" && req.method !== "POST") {
		return apiError(res, 405, "Method not allowed");
	}

	// Rate limit public domain lookups by IP (60 req/min, fail-open)
	const ip =
		(req.headers["x-forwarded-for"] as string)?.split(",")[0]?.trim() ||
		"unknown";
	const rl = await checkRateLimit({
		key: `link-domain:${ip}`,
		limit: 60,
		windowSeconds: 60,
		failMode: "open",
	});
	if (!rl.allowed) {
		return apiError(res, 429, "Too many requests");
	}

	// Extract domain from Host header or query param
	const host = (req.headers.host || "").split(":")[0]!.toLowerCase();
	const domain = host;

	if (!domain || domain === "juno33.com" || domain === "localhost") {
		return res.status(404).send("Not found");
	}

	const supabase = getPrivilegedSupabaseAny(
		PRIVILEGED_DB_REASONS.publicLinkDomain,
	);

	// Look up page by custom domain
	const { data: page } = await supabase
		.from("link_pages")
		.select("slug")
		.eq("custom_domain", domain)
		.eq("domain_verified", true)
		.eq("is_published", true)
		.maybeSingle();

	if (page?.slug && isLinkPageTrackRequest(req)) {
		return proxyPublicHandler(req, res, {
			domain,
			urlPath: withOriginalQuery(req, "/api/link-page/track"),
			cacheControl: "private, no-cache",
		});
	}

	if (!page?.slug) {
		const { data: smartLink } = await supabase
			.from("smart_links")
			.select("code")
			.eq("custom_domain", domain)
			.eq("domain_verified", true)
			.eq("is_active", true)
			.maybeSingle();

		if (!smartLink?.code) {
			logger.warn("[domain] No page found for custom domain", { domain });
			return res.status(404).send("Page not found for this domain");
		}

		return proxyPublicHandler(req, res, {
			domain,
			urlPath: withOriginalQuery(
				req,
				`/api/go/${encodeURIComponent(smartLink.code)}`,
			),
			cacheControl: "private, no-cache",
		});
	}

	// Redirect internally to the slug-based handler
	// Using 307 to preserve method; the [slug] handler renders the HTML
	return proxyPublicHandler(req, res, {
		domain,
		urlPath: withOriginalQuery(req, `/api/link-page/${page.slug}`),
		cacheControl: "public, s-maxage=60, stale-while-revalidate=300",
	});
}

function isLinkPageTrackRequest(req: VercelRequest): boolean {
	return (
		req.method === "POST" &&
		(getOriginalPathname(req) === "/api/link-page/track" ||
			hasLinkPageTrackBody(req.body))
	);
}

function hasLinkPageTrackBody(body: unknown): boolean {
	if (!body) return false;
	if (typeof body === "object" && !Array.isArray(body)) {
		return (
			"pageId" in body &&
			("linkId" in body || "variantId" in body || "token" in body)
		);
	}
	if (typeof body === "string") {
		try {
			return hasLinkPageTrackBody(JSON.parse(body));
		} catch {
			return false;
		}
	}
	return false;
}

function getOriginalPathname(req: VercelRequest): string {
	const rawPath =
		typeof req.headers["x-original-path"] === "string"
			? req.headers["x-original-path"]
			: typeof req.headers["x-forwarded-uri"] === "string"
				? req.headers["x-forwarded-uri"]
				: req.url || "/";
	try {
		return new URL(rawPath, "https://custom-domain.local").pathname;
	} catch {
		return "/";
	}
}

function withOriginalQuery(req: VercelRequest, targetPath: string): string {
	const search = getOriginalSearch(req);
	return search ? `${targetPath}${search}` : targetPath;
}

function getOriginalSearch(req: VercelRequest): string {
	const candidates = [
		typeof req.headers["x-original-path"] === "string"
			? req.headers["x-original-path"]
			: "",
		typeof req.headers["x-forwarded-uri"] === "string"
			? req.headers["x-forwarded-uri"]
			: "",
		req.url || "",
	];
	for (const candidate of candidates) {
		try {
			const search = new URL(
				candidate || "/",
				"https://custom-domain.local",
			).search;
			if (search) return search;
		} catch {
			// Try the next source.
		}
	}
	return "";
}

function getRequestBody(req: VercelRequest): string | null {
	if (req.body == null) return null;
	if (typeof req.body === "string") {
		return req.body;
	}
	if (req.body instanceof Uint8Array || req.body instanceof ArrayBuffer) {
		return new TextDecoder().decode(req.body);
	}
	return JSON.stringify(req.body);
}

async function proxyPublicHandler(
	req: VercelRequest,
	res: VercelResponse,
	{
		domain,
		urlPath,
		cacheControl,
	}: { domain: string; urlPath: string; cacheControl: string },
) {
	const baseUrl =
		process.env.APP_URL ||
		(process.env.VERCEL_URL
			? `https://${process.env.VERCEL_URL}`
			: "https://juno33.com");
	const targetUrl = `${baseUrl}${urlPath}`;
	try {
		const forwardedProto =
			typeof req.headers["x-forwarded-proto"] === "string" &&
			(req.headers["x-forwarded-proto"] === "http" ||
				req.headers["x-forwarded-proto"] === "https")
				? req.headers["x-forwarded-proto"]
				: "https";
		const contentType =
			typeof req.headers["content-type"] === "string"
				? req.headers["content-type"]
				: "application/json";
		const fetchInit: RequestInit = {
			method: req.method || "GET",
			headers: {
				"User-Agent": String(req.headers["user-agent"] || ""),
				Accept: String(req.headers.accept || "text/html"),
				"Content-Type": contentType,
				"X-Forwarded-For": String(req.headers["x-forwarded-for"] || ""),
				"X-Vercel-IP-Country": String(req.headers["x-vercel-ip-country"] || ""),
				"X-Public-Link-Origin": `${forwardedProto}://${domain}`,
			},
		};
		if (req.method === "POST") {
			const requestBody = getRequestBody(req);
			if (requestBody !== null) fetchInit.body = requestBody;
		}
		const response = await fetch(targetUrl, fetchInit);
		const body = await response.text();
		res.setHeader(
			"Content-Type",
			response.headers.get("content-type") || "text/html; charset=utf-8",
		);
		res.setHeader("Cache-Control", cacheControl);
		return res.status(response.status).send(body);
	} catch (fetchError) {
		logger.error("[domain] Failed to proxy custom domain", {
			domain,
			urlPath,
			error: String(fetchError),
		});
		return res.status(500).send("Internal error");
	}
}
