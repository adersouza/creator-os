/**
 * Shared outbound URL guardrails for redirects and server-side fetches.
 *
 * Anything persisted by users or third-party APIs is treated as untrusted at
 * use time too. Creation-time validation is not enough because legacy rows,
 * cache entries, and CDN redirects can all drift.
 */

import { logger } from "./logger.js";
import { validateUrlNotPrivate } from "./ssrfProtection.js";

const PLATFORM_MEDIA_HOST_SUFFIXES = [
	"fbcdn.net",
	"cdninstagram.com",
	"threads.net",
	"instagram.com",
];

function hostMatches(hostname: string, allowed: string[]): boolean {
	const host = hostname.toLowerCase();
	return allowed.some(
		(suffix) => host === suffix || host.endsWith(`.${suffix}`),
	);
}

export function parseHttpUrl(url: string): URL | null {
	try {
		const parsed = new URL(url);
		if (parsed.protocol !== "https:" && parsed.protocol !== "http:")
			return null;
		return parsed;
	} catch {
		return null;
	}
}

export function isAllowedPlatformMediaUrl(url: string): boolean {
	const parsed = parseHttpUrl(url);
	if (!parsed) return false;
	return hostMatches(parsed.hostname, PLATFORM_MEDIA_HOST_SUFFIXES);
}

export function isAllowedSupabasePublicUrl(url: string): boolean {
	const parsed = parseHttpUrl(url);
	if (!parsed || parsed.protocol !== "https:") return false;

	if (process.env.SUPABASE_URL) {
		try {
			const supabaseHost = new URL(process.env.SUPABASE_URL).hostname;
			if (parsed.hostname === supabaseHost) return true;
		} catch {
			// Fall through to suffix check.
		}
	}

	return hostMatches(parsed.hostname, ["supabase.co"]);
}

export async function validatePublicRedirectUrl(
	url: string,
	context: string,
): Promise<string | null> {
	const parsed = parseHttpUrl(url);
	if (!parsed) return "URL must use http or https";

	const ssrfError = await validateUrlNotPrivate(url);
	if (ssrfError) {
		logger.warn("[outbound-url] Blocked public redirect", {
			context,
			host: parsed.hostname,
			reason: ssrfError,
		});
		return ssrfError;
	}

	return null;
}

export async function fetchAllowedMediaUrl(
	url: string,
	init: RequestInit = {},
	maxRedirects = 3,
): Promise<Response | null> {
	let current = url;

	for (let i = 0; i <= maxRedirects; i++) {
		if (
			!isAllowedPlatformMediaUrl(current) &&
			!isAllowedSupabasePublicUrl(current)
		) {
			logger.warn("[outbound-url] Blocked media fetch", { url: current });
			return null;
		}

		const response = await fetch(current, {
			...init,
			redirect: "manual",
		});

		if (
			response.status >= 300 &&
			response.status < 400 &&
			response.headers.has("location")
		) {
			const location = response.headers.get("location");
			if (!location) return null;
			try {
				current = new URL(location, current).toString();
			} catch {
				return null;
			}
			continue;
		}

		return response;
	}

	logger.warn("[outbound-url] Blocked media fetch redirect loop", { url });
	return null;
}

export async function fetchPublicUrlWithRedirects(
	url: string,
	context: string,
	init: RequestInit = {},
	maxRedirects = 3,
): Promise<Response | null> {
	let current = url;

	for (let i = 0; i <= maxRedirects; i++) {
		const blocked = await validatePublicRedirectUrl(current, context);
		if (blocked) return null;

		const response = await fetch(current, {
			...init,
			redirect: "manual",
		});

		if (
			response.status >= 300 &&
			response.status < 400 &&
			response.headers.has("location")
		) {
			const location = response.headers.get("location");
			if (!location) return null;
			try {
				current = new URL(location, current).toString();
			} catch {
				return null;
			}
			continue;
		}

		return response;
	}

	logger.warn("[outbound-url] Blocked public fetch redirect loop", {
		context,
		url,
	});
	return null;
}
