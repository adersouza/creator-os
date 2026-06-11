export interface DiscoverabilitySafeContentResult {
	discoverabilitySafe: boolean;
	blockedTerms: Array<{ reason: string; matchedText: string }>;
	blockedReason: string;
}

const DISCOVERABILITY_SAFE_CONTENT_PATTERNS: Array<[string, RegExp]> = [
	["url", /https?:\/\/|www\./i],
	["dm_reference", /\b(dm|dms|direct\s+message|message\s+me|inbox\s+me)\b/i],
	["link_reference", /\b(link|link\s*in\s*bio|bio\s*link|tap\s+link|click\s+link)\b/i],
	["subscription_cta", /\b(join\s+my\s+page|subscribe\s+here)\b/i],
	["of_reference", /\b(onlyfans|fansly)\b/i],
	["of_reference", /(^|[^A-Za-z0-9_])#?OF(?![A-Za-z0-9_])/],
	[
		"off_platform_reference",
		/\b(snapchat|snap\s+me|telegram|whatsapp|linktree|beacons)\b/i,
	],
];

export function validateDiscoverabilitySafeContent(
	...values: unknown[]
): DiscoverabilitySafeContentResult {
	const blockedTerms: Array<{ reason: string; matchedText: string }> = [];
	const seen = new Set<string>();
	for (const value of values) {
		if (typeof value !== "string" || !value.trim()) continue;
		for (const [reason, pattern] of DISCOVERABILITY_SAFE_CONTENT_PATTERNS) {
			const match = pattern.exec(value);
			if (!match?.[0]) continue;
			const key = `${reason}:${match[0].toLowerCase()}`;
			if (seen.has(key)) continue;
			seen.add(key);
			blockedTerms.push({ reason, matchedText: match[0] });
		}
	}
	return {
		discoverabilitySafe: blockedTerms.length === 0,
		blockedTerms,
		blockedReason:
			blockedTerms.length > 0
				? "discoverability_risk_link_dm_or_off_platform_reference"
				: "",
	};
}
