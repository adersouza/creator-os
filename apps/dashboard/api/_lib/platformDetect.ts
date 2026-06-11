// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
/**
 * Platform / Device Detection Utilities
 *
 * Shared by:
 * - api/go/[code].ts (smart redirect)
 * - api/link-page/track.ts (click tracking)
 */

import * as crypto from "node:crypto";

export type SourcePlatform =
	| "instagram"
	| "threads"
	| "twitter"
	| "tiktok"
	| "facebook"
	| "whatsapp"
	| "snapchat"
	| "telegram"
	| "direct"
	| "unknown";

export type DeviceType = "ios" | "android" | "desktop" | "unknown";

/**
 * Detect source platform from User-Agent and Referrer.
 */
export function detectPlatform(ua: string, referrer?: string): SourcePlatform {
	const uaLower = (ua || "").toLowerCase();
	const ref = (referrer || "").toLowerCase();

	if (uaLower.includes("instagram")) return "instagram";
	if (
		uaLower.includes("threads") ||
		uaLower.includes("barcelona") ||
		ref.includes("threads.net") ||
		ref.includes("threads.com")
	)
		return "threads";
	if (
		uaLower.includes("twitter") ||
		ref.includes("t.co") ||
		ref.includes("twitter.com") ||
		ref.includes("x.com")
	)
		return "twitter";
	if (
		uaLower.includes("tiktok") ||
		uaLower.includes("bytedance") ||
		uaLower.includes("musical_ly")
	)
		return "tiktok";
	if (
		uaLower.includes("fban") ||
		uaLower.includes("fbav") ||
		uaLower.includes("fb_iab")
	)
		return "facebook";
	if (uaLower.includes("whatsapp")) return "whatsapp";
	if (uaLower.includes("snapchat")) return "snapchat";
	if (uaLower.includes("telegram")) return "telegram";

	// Check referrer for platform hints
	if (ref.includes("instagram.com")) return "instagram";
	if (ref.includes("facebook.com") || ref.includes("fb.com")) return "facebook";
	if (ref.includes("tiktok.com")) return "tiktok";

	// If there's a referrer but no match, it's from some other site
	if (ref && ref !== "") return "unknown";

	return "direct";
}

/**
 * Detect device type from User-Agent.
 */
export function detectDevice(ua: string): DeviceType {
	const uaStr = ua || "";
	if (/iphone|ipad|ipod/i.test(uaStr)) return "ios";
	if (/android/i.test(uaStr)) return "android";
	if (/mobile/i.test(uaStr)) return "unknown"; // generic mobile
	return "desktop";
}

/**
 * Check if the User-Agent is an in-app browser (IG, FB, TikTok, etc.).
 * In-app browsers don't support deep links — always use direct redirects.
 */
export function isInAppBrowser(ua: string): boolean {
	return /instagram|barcelona|fban|fbav|fb_iab|tiktok|musical_ly|bytedance|snapchat|twitter|telegram|messenger|line\//i.test(
		ua || "",
	);
}

/**
 * Check if the User-Agent is a crawler/bot (for analytics separation).
 */
export function isCrawler(ua: string): boolean {
	return /facebookexternalhit|facebot|facebookbot|meta-externalagent|meta-externalfetcher|twitterbot|telegrambot|linkedinbot|googlebot|bingbot|duckduckbot|discordbot|whatsapp|pinterest|applebot|slurp|yandex|baidu/i.test(
		ua || "",
	);
}

// ============================================================================
// Meta CIDR Ranges (AS32934 + secondary ASNs: AS63293, AS54115, AS399606)
//
// Used for ASN-verified bot detection. Meta does NOT publish an official
// crawler IP list, but these ranges are well-documented from AS32934.
// Last verified: March 2026. Review periodically for changes.
// ============================================================================

/** Parse an IPv4 address string to a 32-bit unsigned integer. Returns null on invalid input. */
function ipToInt(ip: string): number | null {
	const parts = ip.split(".");
	if (parts.length !== 4) return null;
	let result = 0;
	for (const part of parts) {
		const n = parseInt(part, 10);
		if (Number.isNaN(n) || n < 0 || n > 255) return null;
		result = (result << 8) | n;
	}
	// Convert to unsigned 32-bit
	return result >>> 0;
}

/** Pre-computed CIDR ranges as [networkInt, maskInt] tuples for fast lookup. */
const META_CIDR_ENTRIES: Array<[number, number]> = [
	// AS32934 primary ranges
	"57.144.0.0/14",
	"129.134.0.0/17",
	"157.240.0.0/17",
	"157.240.192.0/18",
	"163.70.128.0/17",
	"31.13.64.0/18",
	"31.13.96.0/19",
	"69.171.224.0/19",
	"173.252.64.0/19",
	"173.252.96.0/19",
	"66.220.144.0/20",
	"69.63.176.0/20",
].map((cidr) => {
	const [network, prefixStr] = cidr.split("/");
	const prefix = parseInt(prefixStr!, 10);
	const mask = prefix === 0 ? 0 : (~0 << (32 - prefix)) >>> 0;
	const parsedNetwork = ipToInt(network!);
	if (parsedNetwork === null) {
		throw new Error(`Invalid CIDR network: ${cidr}`);
	}
	const networkInt = parsedNetwork & mask;
	return [networkInt, mask] as [number, number];
});

/**
 * Check if an IPv4 address belongs to a known Meta ASN range.
 * Pure integer math — no external dependencies, no network lookups.
 */
export function isMetaIpRange(ip: string): boolean {
	const ipInt = ipToInt(ip);
	if (ipInt === null) return false;
	for (const [network, mask] of META_CIDR_ENTRIES) {
		if ((ipInt & mask) === network) return true;
	}
	return false;
}

/**
 * Detect Meta integrity bots specifically (for Shield Protection).
 *
 * Two-tier detection:
 * 1. Meta-verified: UA matches Meta crawler string AND IP is in Meta's CIDR ranges.
 *    Spoofed Meta UAs from non-Meta IPs are treated as normal users.
 * 2. Generic bot: Missing standard browser headers + bot-like UA patterns.
 *    No IP verification needed — these are clearly not real browsers.
 *
 * This is used for crawl monitoring ONLY — Shield logs when Meta bots visit
 * but NEVER alters page content. All visitors see the identical DOM.
 * (March 2026: content filtering removed after independent audits confirmed it constituted cloaking.)
 */
export function isMetaIntegrityBot(
	ua: string,
	headers: Record<string, string | string[] | undefined>,
	ip?: string,
): { isBot: boolean; botType: string | null } {
	const uaLower = (ua || "").toLowerCase();

	// Tier 1: Known Meta crawler UAs — require IP verification
	const isMetaUa =
		/facebookexternalhit|facebot|facebookbot|facebookcatalog|meta-externalagent|meta-externalfetcher/i.test(
			uaLower,
		);
	if (isMetaUa) {
		// Verify the request actually originates from Meta's infrastructure.
		// Without IP verification, anyone can spoof the UA to probe Shield behavior.
		if (ip && isMetaIpRange(ip)) {
			return { isBot: true, botType: "meta-verified" };
		}
		// Spoofed Meta UA from a non-Meta IP — treat as normal visitor
		return { isBot: false, botType: null };
	}

	// Tier 2: Generic bot signatures (headless browsers, curl, etc.)
	// that also lack standard browser headers — likely automated scanners.
	// Real browsers always send Accept-Language and Sec-Fetch-Dest.
	const hasAcceptLanguage = Boolean(headers["accept-language"]);
	const hasSecFetch = Boolean(
		headers["sec-fetch-dest"] || headers["sec-fetch-mode"],
	);

	if (!hasAcceptLanguage && !hasSecFetch) {
		// No browser fingerprint headers — check for bot-like UA patterns
		if (
			/bot|crawl|spider|scraper|headless|phantom|puppeteer|playwright/i.test(
				uaLower,
			)
		) {
			return { isBot: true, botType: "generic-bot" };
		}
		// Extremely short or missing UA with no browser headers
		if (uaLower.length < 20) {
			return { isBot: true, botType: "minimal-ua" };
		}
	}

	return { isBot: false, botType: null };
}

/**
 * Generate a privacy-safe fingerprint for attribution without cookies.
 * Hashed IP + UA + day — rotates daily, no PII stored.
 */
export function generateFingerprint(ip: string, ua: string): string {
	return crypto
		.createHash("sha256")
		.update(`${ip}|${ua}|${new Date().toISOString().split("T")[0]!}`)
		.digest("hex")
		.substring(0, 16);
}

/**
 * Extract UTM parameters from query string.
 */
export function parseUtmParams(query: Record<string, unknown>): {
	utm_source?: string | undefined;
	utm_medium?: string | undefined;
	utm_campaign?: string | undefined;
	utm_content?: string | undefined;
} {
	return {
		utm_source:
			typeof query.utm_source === "string" ? query.utm_source : undefined,
		utm_medium:
			typeof query.utm_medium === "string" ? query.utm_medium : undefined,
		utm_campaign:
			typeof query.utm_campaign === "string" ? query.utm_campaign : undefined,
		utm_content:
			typeof query.utm_content === "string" ? query.utm_content : undefined,
	};
}

/**
 * Append UTM parameters to a URL.
 */
export function appendUtms(
	targetUrl: string,
	utms: Record<string, string | undefined>,
): string {
	try {
		const url = new URL(targetUrl);
		// #699: Validate protocol to prevent open redirect to javascript: or data: URLs
		if (url.protocol !== "https:" && url.protocol !== "http:") {
			return targetUrl;
		}
		for (const [key, value] of Object.entries(utms)) {
			if (value && !url.searchParams.has(key)) {
				url.searchParams.set(key, value);
			}
		}
		return url.toString();
	} catch {
		return targetUrl;
	}
}
