/**
 * Duplicate Content Detection
 *
 * Before publishing, checks if similar content was posted in the last 24 hours.
 * Uses a simple normalized string comparison (first 100 chars).
 */

import { supabase } from "@/services/supabase";

export interface DuplicateCheckResult {
	isDuplicate: boolean;
	hoursAgo?: number | undefined;
	matchedPostId?: string | undefined;
}

/**
 * Simple string hash for comparison.
 */
function normalizeText(text: string): string {
	return text
		.toLowerCase()
		.replace(/\s+/g, " ")
		.replace(/[^\w\s]/g, "") // Strip punctuation for fuzzy matching
		.trim();
}

/**
 * Check if similar content was posted in the last 24 hours for this account.
 */
export async function checkDuplicateContent(
	content: string,
	accountId: string,
): Promise<DuplicateCheckResult> {
	if (!accountId || accountId === "ALL") return { isDuplicate: false };
	if (!content.trim()) return { isDuplicate: false };

	const normalized = normalizeText(content);
	const twentyFourHoursAgo = new Date(
		Date.now() - 24 * 60 * 60 * 1000,
	).toISOString();

	const { data: recentPosts, error } = await supabase
		.from("posts")
		.select("id, content, published_at, created_at")
		.eq("account_id", accountId)
		.eq("status", "published")
		.gte("created_at", twentyFourHoursAgo)
		.order("created_at", { ascending: false })
		.limit(50);

	if (error || !recentPosts) return { isDuplicate: false };

	for (const post of recentPosts) {
		if (!post.content) continue;
		const postNormalized = normalizeText(post.content);
		if (postNormalized === normalized) {
			const postTime = new Date(
				post.published_at || post.created_at || Date.now(),
			).getTime();
			const hoursAgo = Math.round((Date.now() - postTime) / (1000 * 60 * 60));
			return {
				isDuplicate: true,
				hoursAgo: Math.max(1, hoursAgo),
				matchedPostId: post.id,
			};
		}
	}

	return { isDuplicate: false };
}
