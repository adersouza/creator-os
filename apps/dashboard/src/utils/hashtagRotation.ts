/**
 * Hashtag Rotation Warning System
 * Detects overused hashtag sets and suggests alternatives.
 */
import { supabase } from "@/services/supabase";

export interface HashtagRotationResult {
	repeated: string[];
	usageCount: number;
	warning: string | null;
	suggestions: string[];
}

/** Extract #hashtags from a caption string */
export function extractHashtags(text: string): string[] {
	const matches = text.match(/#[\w\u00C0-\u024F]+/g);
	if (!matches) return [];
	return [...new Set(matches.map((h) => h.toLowerCase()))];
}

/** Calculate overlap ratio between two hashtag sets */
function overlapRatio(a: string[], b: string[]): number {
	if (a.length === 0 || b.length === 0) return 0;
	const setB = new Set(b);
	const overlap = a.filter((h) => setB.has(h)).length;
	return overlap / Math.max(a.length, b.length);
}

export async function checkHashtagRepetition(
	accountId: string,
	hashtags: string[],
): Promise<HashtagRotationResult> {
	const result: HashtagRotationResult = {
		repeated: [],
		usageCount: 0,
		warning: null,
		suggestions: [],
	};

	if (!accountId || accountId === "ALL") return result;
	if (hashtags.length === 0) return result;

	const normalizedInput = hashtags.map((h) =>
		h.startsWith("#") ? h.toLowerCase() : `#${h.toLowerCase()}`,
	);

	// Get posts from last 7 days
	const sevenDaysAgo = new Date();
	sevenDaysAgo.setDate(sevenDaysAgo.getDate() - 7);

	const { data: recentPosts } = await supabase
		.from("posts")
		.select("id, content, published_at")
		.eq("account_id", accountId)
		.gte("published_at", sevenDaysAgo.toISOString())
		.order("published_at", { ascending: false });

	if (!recentPosts || recentPosts.length === 0) return result;

	// Check overlap with each recent post's hashtags
	let matchCount = 0;
	const allUsedHashtags = new Map<string, number>();

	for (const post of recentPosts) {
		const postHashtags = extractHashtags(post.content || "");
		for (const h of postHashtags) {
			allUsedHashtags.set(h, (allUsedHashtags.get(h) || 0) + 1);
		}
		if (overlapRatio(normalizedInput, postHashtags) >= 0.7) {
			matchCount++;
		}
	}

	// Find repeated hashtags (used 3+ times in 7 days)
	result.repeated = normalizedInput.filter(
		(h) => (allUsedHashtags.get(h) || 0) >= 3,
	);
	result.usageCount = matchCount;

	if (matchCount >= 3) {
		result.warning = `⚠️ You've used this hashtag set ${matchCount} times in 7 days. Meta may reduce your reach.`;
	}

	// Suggest high-performing hashtags not in current set
	try {
		const { data: hashtagPerf } = await supabase
			.from("ig_hashtag_tracking")
			.select("hashtag, avg_reach")
			.eq("account_id", accountId)
			.order("avg_reach", { ascending: false })
			.limit(20);

		if (hashtagPerf) {
			const inputSet = new Set(normalizedInput);
			result.suggestions = hashtagPerf
				.map((h: { hashtag: string }) =>
					(h.hashtag.startsWith("#")
						? h.hashtag
						: `#${h.hashtag}`
					).toLowerCase(),
				)
				.filter((h: string) => !inputSet.has(h))
				.slice(0, 5);
		}
	} catch {
		// Hashtag tracking table may not exist for all accounts
	}

	return result;
}
