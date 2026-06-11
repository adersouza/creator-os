/**
 * Social-platform primitive — one place to encode the behavioral
 * differences between Threads and Instagram. Every constant that varies
 * (max caption length, daily cap, optimal hashtag count, account table
 * name, etc.) lives here.
 *
 * Named `socialPlatform` instead of `platform` because `src/lib/platform.ts`
 * is already taken by macOS/Windows detection helpers.
 *
 * Import `PLATFORM` for the table of values, or call the helper functions
 * for the common "given platform X, what's Y" questions. Avoid writing
 * `platform === 'threads' ? a : b` ternaries in product code — add a
 * helper here instead.
 *
 * Historical note: the codebase has ~200 existing ternaries scattered
 * across components. Migrating them all in one pass isn't worth the
 * churn. Pattern going forward: new code uses the helpers, existing
 * ternaries migrate opportunistically when the surrounding code changes.
 */

import type { Platform, PlatformFilter } from "@/types/platform";

export type { Platform, PlatformFilter };

interface PlatformSpec {
	label: string;
	shortLabel: string;
	/** Single-glyph badge for dense UI (post cards, calendar cells). */
	badgeLabel: string;
	/** Max caption/body character length per Meta's API. */
	maxBodyChars: number;
	/** Max daily publishes per account per Meta's quota. */
	dailyPublishLimit: number;
	/** Max daily replies per account per Meta's quota. */
	dailyReplyLimit: number;
	/** Optimal caption length range (inclusive) for engagement. */
	optimalBodyCharsMin: number;
	optimalBodyCharsMax: number;
	/** Optimal hashtag count. Threads doesn't use them much. */
	optimalHashtagCount: number;
	/** Does the platform reward hashtags in discovery? */
	hashtagsHelpDiscovery: boolean;
	/** Supabase table name for this platform's accounts. */
	accountTable: "accounts" | "instagram_accounts";
	/** Supabase table name for the per-post engagement rows. */
	postTable: "posts";
	/** Account ID column type — TEXT for Threads, UUID for IG. */
	idColumnType: "text" | "uuid";
}

/**
 * Source-of-truth table for platform-specific constants.
 * Values come from Meta's Content Publishing API docs (Threads v1.0,
 * Instagram v25.0) plus internal research on optimal caption length.
 */
export const PLATFORM: Record<Platform, PlatformSpec> = {
	threads: {
		label: "Threads",
		shortLabel: "Threads",
		badgeLabel: "T",
		maxBodyChars: 500,
		dailyPublishLimit: 250,
		dailyReplyLimit: 1000,
		optimalBodyCharsMin: 50,
		optimalBodyCharsMax: 280,
		optimalHashtagCount: 3,
		hashtagsHelpDiscovery: false,
		accountTable: "accounts",
		postTable: "posts",
		idColumnType: "text",
	},
	instagram: {
		label: "Instagram",
		shortLabel: "IG",
		badgeLabel: "IG",
		maxBodyChars: 2200,
		dailyPublishLimit: 25,
		dailyReplyLimit: 100,
		optimalBodyCharsMin: 100,
		optimalBodyCharsMax: 500,
		optimalHashtagCount: 8,
		hashtagsHelpDiscovery: true,
		accountTable: "instagram_accounts",
		postTable: "posts",
		idColumnType: "uuid",
	},
};

export function labelFor(platform: Platform): string {
	return PLATFORM[platform].label;
}

export function shortLabelFor(platform: Platform): string {
	return PLATFORM[platform].shortLabel;
}

export function badgeLabelFor(platform: Platform): string {
	return PLATFORM[platform].badgeLabel;
}

export function maxBodyChars(platform: Platform): number {
	return PLATFORM[platform].maxBodyChars;
}

export function dailyPublishLimit(platform: Platform): number {
	return PLATFORM[platform].dailyPublishLimit;
}

export function dailyReplyLimit(platform: Platform): number {
	return PLATFORM[platform].dailyReplyLimit;
}

export function accountTableFor(
	platform: Platform,
): "accounts" | "instagram_accounts" {
	return PLATFORM[platform].accountTable;
}

export function optimalHashtagCount(platform: Platform): number {
	return PLATFORM[platform].optimalHashtagCount;
}

export function optimalBodyChars(platform: Platform): {
	min: number;
	max: number;
} {
	return {
		min: PLATFORM[platform].optimalBodyCharsMin,
		max: PLATFORM[platform].optimalBodyCharsMax,
	};
}

export function parsePlatform(raw: unknown): Platform | null {
	if (raw === "threads" || raw === "instagram") return raw;
	return null;
}

export function parsePlatformFilter(raw: unknown): PlatformFilter | null {
	if (raw === "threads" || raw === "instagram" || raw === "all") return raw;
	return null;
}

export const PLATFORMS: readonly Platform[] = ["threads", "instagram"] as const;
