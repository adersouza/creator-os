// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
/**
 * Shared utilities, schemas, and constants for smart-links handlers.
 */

import * as crypto from "node:crypto";
import { getSupabase } from "../../supabase.js";
import { z, zEnum, zLiteral, zRecord, zUnknown } from "../../zodCompat.js";

// smart_links tables not yet in auto-generated supabase.ts types
export const db = () => getSupabase() as ReturnType<typeof getSupabase>;

// ============================================================================
// Tier Limits
// ============================================================================
export const SMART_LINK_LIMITS: Record<string, number> = {
	free: 0,
	pro: 10,
	agency: 50,
	empire: 999,
};

// ============================================================================
// Code Generation
// ============================================================================
function generateShortCode(): string {
	const chars = "abcdefghijklmnopqrstuvwxyz0123456789";
	const length = 6 + (crypto.randomBytes(1)[0]! % 3); // 6-8 chars
	const randomBytes = crypto.randomBytes(length);
	let code = "";
	for (let i = 0; i < length; i++) {
		code += chars[randomBytes[i]! % chars.length];
	}
	return code;
}

export async function generateUniqueCode(): Promise<string> {
	for (let attempt = 0; attempt < 5; attempt++) {
		const code = generateShortCode();
		if (isReservedSmartLinkCode(code)) continue;
		const { data } = await db()
			.from("smart_links")
			.select("id")
			.eq("code", code)
			.maybeSingle();
		if (!data) return code;
	}
	// Fallback: cryptographically random — unpredictable and collision-resistant
	return crypto.randomBytes(4).toString("hex");
}

export function generateWebhookSecret(): string {
	return crypto.randomBytes(32).toString("hex");
}

export const RESERVED_SMART_LINK_CODES = new Set([
	"analytics",
	"api",
	"convert",
	"r",
	"redirect",
	"track",
	"www",
]);

export function isReservedSmartLinkCode(code: string): boolean {
	return RESERVED_SMART_LINK_CODES.has(code.toLowerCase());
}

// ============================================================================
// Deep Link Validation
// ============================================================================
const ALLOWED_DEEP_LINK_SCHEMES = [
	"https:",
	"instagram:",
	"barcelona:",
	"threads:", // legacy — barcelona:// is the actual Threads scheme
	"fb:",
	"twitter:",
	"vnd.youtube:",
	"snssdk1233:", // TikTok
	"spotify:",
];

/**
 * Validate a deep link URL: must be a parseable URL using an allowed scheme.
 * Rejects javascript:, data:, and other dangerous protocols.
 */
export function isValidDeepLink(val: string): boolean {
	try {
		const parsed = new URL(val);
		// Block dangerous schemes
		if (parsed.protocol === "javascript:" || parsed.protocol === "data:") {
			return false;
		}
		// Only allow known safe schemes
		return ALLOWED_DEEP_LINK_SCHEMES.includes(parsed.protocol);
	} catch {
		// Not a valid URL at all
		return false;
	}
}

/**
 * Validate a redirect/target URL: must use http or https scheme.
 * Rejects javascript:, data:, file:, and other dangerous protocols.
 */
export function isValidHttpUrl(val: string): boolean {
	try {
		const parsed = new URL(val);
		return parsed.protocol === "https:" || parsed.protocol === "http:";
	} catch {
		return false;
	}
}

// ============================================================================
// Cloaking Risk Warnings
// ============================================================================

/**
 * Compare hostnames of per-platform redirect URLs against the main target_url.
 * Returns warning strings for any mismatches so creators are aware of the
 * cloaking risk under Meta's spam policies.
 */
export function getCloakingWarnings(data: {
	target_url?: string | undefined;
	ig_redirect_url?: string | null | undefined;
	threads_redirect_url?: string | null | undefined;
}): string[] {
	const warnings: string[] = [];
	if (!data.target_url) return warnings;

	let targetHost: string;
	try {
		targetHost = new URL(data.target_url).hostname;
	} catch {
		return warnings;
	}

	for (const [field, label] of [
		["ig_redirect_url", "Instagram"] as const,
		["threads_redirect_url", "Threads"] as const,
	]) {
		const url = data[field];
		if (!url) continue;
		try {
			const redirectHost = new URL(url).hostname;
			if (redirectHost !== targetHost) {
				warnings.push(
					`${field} points to ${redirectHost} while target_url points to ${targetHost}. ${label} may flag this as cloaking if the content is substantially different.`,
				);
			}
		} catch {
			// Invalid URL — Zod already validates, so skip
		}
	}

	return warnings;
}

/**
 * Smart links support native app deep links, but web fallbacks must remain
 * canonical. Alternate web redirect URLs are rejected to prevent
 * platform/device-specific destination switching.
 */
export function getAlternateRedirectErrors(data: {
	target_url?: string | undefined;
	ig_redirect_url?: string | null | undefined;
	threads_redirect_url?: string | null | undefined;
	mobile_redirect_url?: string | null | undefined;
}): string[] {
	const errors: string[] = [];
	for (const [field, value] of [
		["ig_redirect_url", data.ig_redirect_url],
		["threads_redirect_url", data.threads_redirect_url],
		["mobile_redirect_url", data.mobile_redirect_url],
	] as const) {
		if (value) {
			errors.push(
				`${field} is no longer supported. Smart links now use one canonical web destination for all visitors.`,
			);
		}
	}
	return errors;
}

// ============================================================================
// Schemas
// ============================================================================
export const CreateSchema = z.object({
	code: z
		.string()
		.min(2)
		.max(20)
		.regex(/^[a-zA-Z0-9_-]+$/, "Code must be alphanumeric")
		.optional(),
	target_url: z
		.string()
		.url("Must be a valid URL")
		.refine(isValidHttpUrl, { message: "URL must use http or https scheme" }),
	title: z.string().max(255).optional(),
	ig_deep_link: z
		.string()
		.optional()
		.refine((val) => !val || isValidDeepLink(val), {
			message:
				"Deep link must be a valid URL using https, instagram, threads, fb, or twitter scheme",
		}),
	threads_deep_link: z
		.string()
		.optional()
		.refine((val) => !val || isValidDeepLink(val), {
			message:
				"Deep link must be a valid URL using https, instagram, threads, fb, or twitter scheme",
		}),
	ig_redirect_url: z
		.string()
		.url()
		.refine(isValidHttpUrl, { message: "URL must use http or https scheme" })
		.optional()
		.or(zLiteral("")),
	threads_redirect_url: z
		.string()
		.url()
		.refine(isValidHttpUrl, { message: "URL must use http or https scheme" })
		.optional()
		.or(zLiteral("")),
	mobile_redirect_url: z
		.string()
		.url()
		.refine(isValidHttpUrl, { message: "URL must use http or https scheme" })
		.optional()
		.or(zLiteral("")),
	enable_deep_links: z.boolean().optional(),
	post_id: z.string().optional().nullable(),
	est_conversion_rate: z.number().min(0).max(1).optional().nullable(),
	est_conversion_value: z.number().min(0).optional().nullable(),
	metadata: zRecord(z.string(), zUnknown()).optional(),
});

export const UpdateSchema = CreateSchema.partial().extend({
	id: z.string().uuid(),
	is_active: z.boolean().optional(),
});

export const AnalyticsQuerySchema = z.object({
	linkId: z.string().min(1, "linkId is required"),
	range: zEnum(["7d", "30d", "90d"]).optional().default("7d"),
});

export async function fetchAllSmartLinkRows(params: {
	table: "smart_link_clicks" | "smart_link_conversions";
	select: string;
	linkIds: string[];
	dateColumn: "clicked_at" | "converted_at";
	since?: string | undefined;
	clickEventsOnly?: boolean | undefined;
}): Promise<Record<string, unknown>[]> {
	const pageSize = 10_000;
	const rows: Record<string, unknown>[] = [];
	for (let offset = 0; ; offset += pageSize) {
		// biome-ignore lint/suspicious/noExplicitAny: dynamic table/select helper
		let query = (db() as any)
			.from(params.table)
			.select(params.select)
			.in("smart_link_id", params.linkIds)
			.order(params.dateColumn, { ascending: true });
		if (params.since) {
			query = query.gte(params.dateColumn, params.since);
		}
		if (params.clickEventsOnly) {
			query = query.or("event_name.is.null,event_name.eq.click,event_name.eq.redirect");
		}
		const { data, error } = await query.range(offset, offset + pageSize - 1);
		if (error) throw error;
		const page = (data as Record<string, unknown>[] | null) || [];
		rows.push(...page);
		if (page.length < pageSize) return rows;
	}
}
