import type { HashtagSuggestion } from "../../types/aiContent.js";
import { supabase } from "../supabase.js";
import type { AIContext } from "./contextEngine.js";
import { contextToSystemPrompt } from "./contextEngine.js";
import { generateContent, parseAIJson } from "./core.js";

export const suggestHashtags = async (
	content: string,
	platform: string = "threads",
	accountId?: string,
	aiContext?: AIContext,
): Promise<HashtagSuggestion[]> => {
	// Fetch real performance data if accountId is available
	let realData: { tag: string; avgEngagement: number; postCount: number }[] =
		[];
	if (accountId && accountId !== "ALL") {
		try {
			realData = await analyzeHashtagPerformance(accountId);
		} catch {
			/* non-critical */
		}
	}

	const realDataContext =
		realData.length > 0
			? `\n\nThe user's top-performing hashtags (real engagement data from their posts):\n${realData
					.slice(0, 10)
					.map(
						(d) =>
							`- #${d.tag}: avg ${d.avgEngagement} engagement across ${d.postCount} posts`,
					)
					.join(
						"\n",
					)}\n\nFavor these proven hashtags when relevant. Base your reach/competition estimates on this real data.`
			: "";

	const aiContextSection = aiContext
		? `\n${contextToSystemPrompt(aiContext)}\n`
		: "";

	const prompt = `Analyze this ${platform} post and suggest 12-15 relevant hashtags. Group them into categories: "niche" (specific to topic), "broad" (wider audience), and "trending" (currently popular). For each hashtag estimate reach (low/medium/high) and competition (low/medium/high).
${aiContextSection}
Post: "${content}"${realDataContext}

Return ONLY a JSON array like:
[{"tag": "hashtag", "category": "niche", "estimatedReach": "medium", "competition": "low"}]

Do NOT include the # symbol in the tag field.`;

	try {
		const response = await generateContent(prompt);
		const tags = parseAIJson<HashtagSuggestion[]>(response);
		if (!Array.isArray(tags)) return [];

		// Cross-reference AI suggestions with real performance data
		if (realData.length > 0) {
			return tags.map((tag) => {
				const real = realData.find(
					(r) => r.tag.toLowerCase() === tag.tag.toLowerCase(),
				);
				if (real) {
					return {
						...tag,
						verified: true,
						realAvgEngagement: real.avgEngagement,
					};
				}
				return { ...tag, verified: false };
			});
		}
		return tags;
	} catch {
		return [];
	}
};

/**
 * Generate categorized hashtag sets for a niche
 */
export const generateHashtagSets = async (
	niche: string,
	platform: string = "threads",
): Promise<{ name: string; tags: string[] }[]> => {
	const prompt = `Generate 3 hashtag sets for the "${niche}" niche on ${platform}. Each set should have a name and 5-8 hashtags. Create:
1. A "Growth" set (maximize reach)
2. A "Community" set (engage with niche)
3. A "Trending" set (ride current trends)

Return ONLY a JSON array like:
[{"name": "Growth", "tags": ["tag1", "tag2"]}]

Do NOT include the # symbol in the tags.`;

	try {
		const response = await generateContent(prompt);
		const sets = parseAIJson<{ name: string; tags: string[] }[]>(response);
		return Array.isArray(sets) ? sets : [];
	} catch {
		return [];
	}
};

/**
 * Analyze which hashtags drove the most engagement from past posts
 */
export const analyzeHashtagPerformance = async (
	accountId: string,
): Promise<{ tag: string; avgEngagement: number; postCount: number }[]> => {
	if (!accountId || accountId === "ALL") return [];
	try {
		const { data: posts } = await supabase
			.from("posts")
			.select("topics, likes_count, replies_count")
			.eq("account_id", accountId)
			.eq("status", "published")
			.not("topics", "is", null)
			.order("created_at", { ascending: false })
			.limit(100);

		if (!posts || posts.length === 0) return [];

		const tagStats: Record<string, { totalEngagement: number; count: number }> =
			{};

		for (const post of posts) {
			const topics = post.topics as string[] | null;
			if (!topics) continue;
			const engagement =
				((post.likes_count as number) || 0) +
				((post.replies_count as number) || 0);
			for (const tag of topics) {
				if (!tagStats[tag]) tagStats[tag] = { totalEngagement: 0, count: 0 };
				tagStats[tag].totalEngagement += engagement;
				tagStats[tag].count += 1;
			}
		}

		return Object.entries(tagStats)
			.map(([tag, stats]) => ({
				tag,
				avgEngagement: Math.round(stats.totalEngagement / stats.count),
				postCount: stats.count,
			}))
			.sort((a, b) => b.avgEngagement - a.avgEngagement)
			.slice(0, 20);
	} catch {
		return [];
	}
};

/**
 * Split long text into thread parts with hook/body/cta labels
 */
