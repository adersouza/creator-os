/**
 * Content Moderation — Lightweight client-side safety check
 *
 * Regex-based check for obviously problematic content before publish.
 * Returns a soft warning (not a hard block) — users can dismiss and proceed.
 *
 * NOT a replacement for server-side moderation or ML classifiers.
 * This is a safety net for obvious issues only.
 */

export interface ModerationResult {
	safe: boolean;
	reasons: string[];
}

// Hate speech / slur patterns (curated short list — obvious terms only)
const HATE_PATTERNS = [
	/\b(kys|kill\s*yourself)\b/i,
	/\b(go\s*die)\b/i,
	/\b(gas\s*the|ethnic\s*cleansing)\b/i,
];

// Excessive profanity threshold (more than 3 instances in a single post)
const PROFANITY_WORDS = [
	/\bf+u+c+k+/i,
	/\bs+h+i+t+/i,
	/\ba+s+s+h+o+l+e/i,
	/\bb+i+t+c+h/i,
];

// Suspicious URL patterns (phishing indicators)
const SUSPICIOUS_URL_PATTERNS = [
	/bit\.ly\/[a-z0-9]+.*(?:free|win|claim|urgent)/i,
	/(?:paypal|apple|google|amazon|bank).*\.(?:xyz|tk|ml|ga|cf)\b/i,
	/(?:login|verify|confirm|secure|update).*\.(?:xyz|tk|ml|ga|cf)\b/i,
];

// Platform policy violations
const POLICY_VIOLATION_PATTERNS = [
	/\b(?:buy|sell)\s*(?:followers|likes|views|engagement)\b/i,
	/\b(?:follow\s*for\s*follow|f4f|l4l|like\s*for\s*like)\b/i,
	/\b(?:get\s*rich\s*quick|guaranteed\s*income|financial\s*freedom\s*in\s*\d+\s*days)\b/i,
	/\b(?:dm\s*me\s*for\s*(?:free\s*money|investment|crypto\s*returns))\b/i,
];

/**
 * Check content for obvious moderation issues.
 * Returns { safe: true } if no issues found, or { safe: false, reasons: [...] } with flagged issues.
 */
export function checkContent(content: string): ModerationResult {
	if (!content || content.trim().length === 0) {
		return { safe: true, reasons: [] };
	}

	const reasons: string[] = [];

	// Check hate speech patterns
	for (const pattern of HATE_PATTERNS) {
		if (pattern.test(content)) {
			reasons.push("Contains potentially harmful or hateful language");
			break; // One reason per category is enough
		}
	}

	// Check excessive profanity (3+ instances)
	let profanityCount = 0;
	for (const pattern of PROFANITY_WORDS) {
		const matches = content.match(new RegExp(pattern.source, "gi"));
		if (matches) profanityCount += matches.length;
	}
	if (profanityCount >= 3) {
		reasons.push("Contains excessive profanity (may reduce reach)");
	}

	// Check suspicious URLs
	for (const pattern of SUSPICIOUS_URL_PATTERNS) {
		if (pattern.test(content)) {
			reasons.push("Contains a suspicious URL pattern");
			break;
		}
	}

	// Check platform policy violations
	for (const pattern of POLICY_VIOLATION_PATTERNS) {
		if (pattern.test(content)) {
			reasons.push("May violate platform guidelines (engagement manipulation)");
			break;
		}
	}

	return {
		safe: reasons.length === 0,
		reasons,
	};
}
