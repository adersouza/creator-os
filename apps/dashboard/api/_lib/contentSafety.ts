const BANNED_PATTERNS: RegExp[] = [
	/\bOnlyFans\b/i,
	/\bsubscribe to my OF\b/i,
	/\bhttps?:\/\/\S+/i,
	/\bwww\.\S+/i,
	/\bporn\b/i,
	/\bxxx\b/i,
	/\bnude[s]?\b/i,
	/\bsex tape\b/i,
	/\bescort[s]?\b/i,
];

export interface BannedWordsResult {
	flagged: boolean;
	matches: string[];
}

export function bannedWordsCheck(text: string): BannedWordsResult {
	const matches: string[] = [];
	for (const pattern of BANNED_PATTERNS) {
		const match = text.match(pattern);
		if (match) matches.push(match[0]);
	}
	return { flagged: matches.length > 0, matches };
}
