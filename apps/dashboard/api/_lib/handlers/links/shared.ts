/**
 * Shared schemas, constants, and helpers for the links API handlers.
 */
import {
	deletePageFromCloudflare,
	syncPageToCloudflare,
} from "../../linkSync.js";
import { logger } from "../../logger.js";
import type { getSupabase } from "../../supabase.js";
import { getUserTier as getUserTierFromGate } from "../../tierGate.js";
import { z, zEnum } from "../../zodCompat.js";

/* ── Plan-based limits for Link in Bio ─────────────────────────── */
export const LINK_LIMITS = {
	free: {
		maxPages: 1,
		maxLinksPerPage: 5,
		customBranding: false,
		deeplinkEscape: false,
		perLinkStyling: false,
		ageGating: false,
		trackingPixels: false,
		shieldModes: ["off"] as readonly string[],
		geoFilter: false,
	},
	pro: {
		maxPages: 3,
		maxLinksPerPage: 25,
		customBranding: true,
		deeplinkEscape: true,
		perLinkStyling: true,
		ageGating: true,
		trackingPixels: true,
		shieldModes: ["off", "soft"] as readonly string[],
		geoFilter: true,
	},
	agency: {
		maxPages: 10,
		maxLinksPerPage: 50,
		customBranding: true,
		deeplinkEscape: true,
		perLinkStyling: true,
		ageGating: true,
		trackingPixels: true,
		shieldModes: ["off", "soft", "strict"] as readonly string[],
		geoFilter: true,
	},
	empire: {
		maxPages: 99,
		maxLinksPerPage: 999,
		customBranding: true,
		deeplinkEscape: true,
		perLinkStyling: true,
		ageGating: true,
		trackingPixels: true,
		shieldModes: ["off", "soft", "strict"] as readonly string[],
		geoFilter: true,
	},
} as const;

export type PlanTier = keyof typeof LINK_LIMITS;

export async function getUserTier(userId: string): Promise<PlanTier> {
	const tier = await getUserTierFromGate(userId);
	return (tier in LINK_LIMITS ? tier : "free") as PlanTier;
}

/**
 * Retry wrapper for Cloudflare KV sync.
 * Tries once, retries after 1s on failure. Logs warning if both attempts fail.
 * Full retry queue is overkill for KV sync -- this is pragmatic.
 */
export async function syncWithRetry(
	supabase: ReturnType<typeof getSupabase>,
	pageId: string,
): Promise<{ synced: boolean }> {
	let result = await syncPageToCloudflare(supabase, pageId);
	if (
		!result.synced &&
		result.error &&
		!result.error.includes("not configured")
	) {
		await new Promise((r) => setTimeout(r, 1000));
		result = await syncPageToCloudflare(supabase, pageId);
		if (!result.synced) {
			logger.warn("[links] Cloudflare sync failed after retry", {
				pageId,
				error: result.error,
			});
		}
	}
	return { synced: result.synced };
}

export async function deleteFromCloudflareWithRetry(
	slug: string,
): Promise<void> {
	try {
		await deletePageFromCloudflare(slug);
	} catch {
		await new Promise((r) => setTimeout(r, 1000));
		try {
			await deletePageFromCloudflare(slug);
		} catch (retryErr: unknown) {
			logger.warn("[links] Cloudflare delete failed after retry", {
				slug,
				error: String(retryErr),
			});
		}
	}
}

/** Validate hex color strings to prevent CSS injection */
export function isValidHexColor(c: string): boolean {
	return /^#[0-9a-fA-F]{3,8}$/.test(c);
}

/**
 * Block dangerous URL schemes and validate URL structure.
 * Uses the URL constructor to parse, then checks protocol is http(s).
 */
export function isSafeUrl(url: string): boolean {
	try {
		const parsed = new URL(url.trim());
		if (parsed.protocol !== "http:" && parsed.protocol !== "https:") {
			return false;
		}
		// Block localhost and private IPs
		const hostname = parsed.hostname.toLowerCase();
		if (
			hostname === "localhost" ||
			hostname === "127.0.0.1" ||
			hostname === "0.0.0.0" ||
			hostname.startsWith("192.168.") ||
			hostname.startsWith("10.") ||
			hostname.startsWith("172.") ||
			hostname === "[::1]"
		) {
			return false;
		}
		return true;
	} catch {
		return false;
	}
}

const DANGEROUS_DEEP_LINK_SCHEMES = new Set([
	"javascript:",
	"data:",
	"vbscript:",
	"file:",
	"about:",
	"chrome:",
	"chrome-extension:",
	"googlechrome:",
	"googlechromes:",
	"intent:",
	"itms-services:",
	"jar:",
	"market:",
	"shortcuts:",
	"x-safari-http:",
	"x-safari-https:",
]);

const ALLOWED_DEEP_LINK_SCHEMES = new Set([
	"http:",
	"https:",
	"barcelona:",
	"fb:",
	"instagram:",
	"snssdk1233:",
	"snapchat:",
	"spotify:",
	"telegram:",
	"tg:",
	"threads:",
	"tiktok:",
	"twitter:",
	"vnd.youtube:",
	"whatsapp:",
	"x:",
	"youtube:",
]);

export function isSafeDeepLinkUrl(url: string): boolean {
	try {
		const parsed = new URL(url.trim());
		const protocol = parsed.protocol.toLowerCase();
		if (DANGEROUS_DEEP_LINK_SCHEMES.has(protocol)) {
			return false;
		}
		return ALLOWED_DEEP_LINK_SCHEMES.has(protocol);
	} catch {
		return false;
	}
}

/* ── Zod Schemas ─────────────────────────────────────────────── */

export const TrackingPixelsSchema = z
	.object({
		metaPixelId: z.string().optional(),
		tiktokPixelId: z.string().optional(),
		ga4MeasurementId: z.string().optional(),
		xPixelId: z.string().optional(),
		snapchatPixelId: z.string().optional(),
		gtmContainerId: z.string().optional(),
	})
	.optional();

export const CreatePageSchema = z.object({
	slug: z
		.string()
		.min(1, "slug is required")
		.max(50)
		.regex(
			/^[a-z0-9\-_]+$/i,
			"Slug must contain only letters, numbers, hyphens, and underscores",
		),
	title: z.string().optional(),
	bio: z.string().optional(),
	avatarUrl: z.string().optional(),
	backgroundColor: z
		.string()
		.refine((s) => !s || isValidHexColor(s), "Must be a valid hex color")
		.optional(),
	brandColor: z
		.string()
		.refine((s) => !s || isValidHexColor(s), "Must be a valid hex color")
		.optional(),
	promoText: z.string().optional(),
	enableDeeplinkEscape: z.boolean().optional(),
	ageGate: z.boolean().optional(),
	ageGateMessage: z.string().max(200).optional(),
	trackingPixels: TrackingPixelsSchema,
});

/** Validate ISO 3166-1 alpha-2 country code (2 uppercase letters) */
const CountryCodeSchema = z
	.string()
	.regex(/^[A-Z]{2}$/, "Must be a 2-letter ISO country code");

const GeoRuleSchema = z.object({
	countries: z.array(CountryCodeSchema).min(1),
	action: zEnum(["redirect", "block"]),
	redirect_url: z.string().url().optional(),
	message: z.string().max(200).optional(),
});

export const GeoRulesSchema = z
	.object({
		rules: z.array(GeoRuleSchema).max(20),
		default: zEnum(["allow", "block"]).optional(),
	})
	.optional()
	.nullable();

export const ShieldConfigSchema = z
	.object({
		adult_domains: z.array(z.string().max(100)).max(50).optional(),
	})
	.optional()
	.nullable();

export const UpdatePageSchema = z.object({
	pageId: z.string().min(1, "pageId is required"),
	title: z.string().optional(),
	bio: z.string().optional(),
	avatarUrl: z.string().optional(),
	backgroundColor: z
		.string()
		.refine((s) => !s || isValidHexColor(s), "Must be a valid hex color")
		.optional(),
	brandColor: z
		.string()
		.refine((s) => !s || isValidHexColor(s), "Must be a valid hex color")
		.optional(),
	promoText: z.string().optional(),
	showOnlineBadge: z.boolean().optional(),
	isPublished: z.boolean().optional(),
	enableDeeplinkEscape: z.boolean().optional(),
	ageGate: z.boolean().optional(),
	ageGateMessage: z.string().max(200).optional(),
	trackingPixels: TrackingPixelsSchema,
	shieldMode: zEnum(["off", "soft", "strict"]).optional(),
	shieldConfig: ShieldConfigSchema,
	geoRules: GeoRulesSchema,
});

/** Allow HTTPS Universal/App Links and a narrow set of known app schemes. */
const safeUrlSchema = z.string().refine(isSafeDeepLinkUrl, "Invalid URL scheme");

export const LinkStyleSchema = z
	.object({
		bgColor: z.string().optional(),
		textColor: z.string().optional(),
		borderRadius: z.number().min(0).max(50).optional(),
		animation: zEnum(["pulse", "shake", "glow", "bounce"]).optional(),
		imageUrl: z.string().optional(),
		imageMode: zEnum(["button", "card", "background"]).optional(),
	})
	.optional();

export const DeepLinkConfigSchema = z
	.object({
		iosDeepLink: safeUrlSchema.optional(),
		androidDeepLink: safeUrlSchema.optional(),
		fallbackUrl: safeUrlSchema.optional(),
		enableDeepLink: z.boolean().optional(),
	})
	.optional();

export const AddLinkSchema = z.object({
	pageId: z.string().min(1, "pageId is required"),
	title: z.string().min(1, "title is required").max(100, "Title too long"),
	url: z.string().url("url must be a valid URL"),
	icon: z
		.string()
		.max(50)
		.refine((s) => !/<|>/.test(s), "Invalid icon")
		.optional(),
	isPrimary: z.boolean().optional(),
	platform: z.string().max(50).optional(),
	deepLinkUrl: z.string().max(500).optional(),
	style: LinkStyleSchema,
	deepLinkConfig: DeepLinkConfigSchema,
});

export const UpdateLinkSchema = z.object({
	linkId: z.string().min(1, "linkId is required"),
	title: z.string().optional(),
	url: z.string().url("url must be a valid URL").optional(),
	icon: z
		.string()
		.max(50)
		.refine((s) => !/<|>/.test(s), "Invalid icon")
		.optional(),
	isVisible: z.boolean().optional(),
	isPrimary: z.boolean().optional(),
	platform: z.string().max(50).optional(),
	deepLinkUrl: z.string().max(500).optional(),
	style: LinkStyleSchema,
	deepLinkConfig: DeepLinkConfigSchema,
});

export const ReorderSchema = z.object({
	pageId: z.string().min(1, "pageId is required"),
	linkIds: z.array(z.string()).min(1, "linkIds must be a non-empty array"),
});

export const DeleteLinkSchema = z.object({
	linkId: z.string().min(1, "linkId is required"),
});

export const DeletePageSchema = z.object({
	pageId: z.string().min(1, "pageId is required"),
});
