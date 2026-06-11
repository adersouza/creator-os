/**
 * Backend mirror of src/lib/socialPlatform.ts.
 *
 * Duplicated because the API runs on Vercel's TS compiler and can't import
 * through Vite's `@/` alias. Values must stay in lockstep with the frontend
 * copy — if you change one, change both. The lists are short enough that
 * manual sync is cheaper than building a shared build target.
 */

export type Platform = "threads" | "instagram";
export type PlatformFilter = Platform | "all";

interface PlatformSpec {
	label: string;
	shortLabel: string;
	maxBodyChars: number;
	dailyPublishLimit: number;
	dailyReplyLimit: number;
	optimalBodyCharsMin: number;
	optimalBodyCharsMax: number;
	optimalHashtagCount: number;
	hashtagsHelpDiscovery: boolean;
	accountTable: "accounts" | "instagram_accounts";
	postTable: "posts";
	idColumnType: "text" | "uuid";
}

export const PLATFORM: Record<Platform, PlatformSpec> = {
	threads: {
		label: "Threads",
		shortLabel: "Threads",
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
export function parsePlatform(raw: unknown): Platform | null {
	if (raw === "threads" || raw === "instagram") return raw;
	return null;
}
export function parsePlatformFilter(raw: unknown): PlatformFilter | null {
	if (raw === "threads" || raw === "instagram" || raw === "all") return raw;
	return null;
}

export const PLATFORMS: readonly Platform[] = ["threads", "instagram"] as const;
