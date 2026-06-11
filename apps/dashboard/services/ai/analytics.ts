// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
import { logger } from "@/utils/logger";
import { generateContent } from "./core.js";

// Re-export for backward compatibility
export { calculateViralScore } from "./scoring.js";

export const calculateSimilarity = (
	original: string,
	adapted: string,
): number => {
	const normalize = (str: string) =>
		str
			.toLowerCase()
			.replace(/[^\w\s]/g, "")
			.split(/\s+/);

	const originalWords = new Set(normalize(original));
	const adaptedWords = normalize(adapted);

	let matchCount = 0;
	adaptedWords.forEach((word) => {
		if (originalWords.has(word) && word.length > 3) {
			// Only count words > 3 chars
			matchCount++;
		}
	});

	const similarity = (matchCount / Math.max(adaptedWords.length, 1)) * 100;
	return Math.min(similarity, 100);
};

// ===== GROWTH SIMULATOR AI FUNCTIONS =====

// Re-export shared types for backward compatibility
export type { UserEngagementStats } from "./types.js";

/**
 * Generate AI-powered post ideas based on performance data and trends
 */

export interface PostAnalysisInput {
	content: string;
	views: number;
	likes: number;
	replies: number;
	reposts: number;
	shares: number;
	engagementRate: number;
	publishedAt: string;
	mediaType: "text" | "image" | "video" | "carousel" | "reels";
	topics?: string[] | undefined;
	accountHandle?: string | undefined;
	// Optional context about the account
	accountAvgEngagement?: number | undefined;
	accountFollowers?: number | undefined;
}

/**
 * Analyze why a post performed the way it did
 * Returns detailed, actionable insights
 */
export const analyzePostPerformance = async (
	post: PostAnalysisInput,
): Promise<string | null> => {
	const erPercent = (post.engagementRate * 100).toFixed(2);

	// Determine performance level
	const performanceLevel =
		post.engagementRate > 0.05
			? "exceptional"
			: post.engagementRate > 0.03
				? "strong"
				: post.engagementRate > 0.015
					? "average"
					: "below average";

	// Analyze content patterns
	const hasQuestion = post.content.includes("?");
	const hasEmoji = /[\u{1F300}-\u{1F9FF}]/u.test(post.content);
	const hasHashtags = post.topics && post.topics.length > 0;
	const contentLength = post.content.length;
	const hasLineBreaks = post.content.includes("\n");

	// Parse time
	const publishDate = new Date(post.publishedAt);
	const dayOfWeek = publishDate.toLocaleDateString("en-US", {
		weekday: "long",
	});
	const hour = publishDate.getHours();
	const timeOfDay = hour < 12 ? "morning" : hour < 17 ? "afternoon" : "evening";

	const prompt = `You are an expert Threads content strategist. Analyze why this post performed the way it did and provide actionable insights.

POST DETAILS:
Content: "${post.content}"
Media Type: ${post.mediaType}
Posted: ${dayOfWeek} ${timeOfDay} (${hour}:00)
Topics/Hashtags: ${post.topics?.join(", ") || "None"}

PERFORMANCE METRICS:
- Views: ${post.views.toLocaleString()}
- Likes: ${post.likes.toLocaleString()}
- Replies: ${post.replies.toLocaleString()}
- Reposts: ${post.reposts.toLocaleString()}
- Shares: ${post.shares.toLocaleString()}
- Engagement Rate: ${erPercent}% (${performanceLevel})
${post.accountAvgEngagement ? `- Account Average ER: ${(post.accountAvgEngagement * 100).toFixed(2)}%` : ""}

CONTENT PATTERNS DETECTED:
- Contains question: ${hasQuestion ? "Yes" : "No"}
- Contains emoji: ${hasEmoji ? "Yes" : "No"}
- Uses hashtags: ${hasHashtags ? "Yes" : "No"}
- Content length: ${contentLength} characters
- Uses line breaks: ${hasLineBreaks ? "Yes" : "No"}

TASK: Provide a concise analysis (3-4 paragraphs max) covering:

1. KEY FACTORS: What specific elements made this post ${performanceLevel === "exceptional" || performanceLevel === "strong" ? "succeed" : "underperform"}? Be specific about the content, timing, and format.

2. WHAT WORKED: Even for underperforming posts, identify what aspects were done well.

3. IMPROVEMENT OPPORTUNITIES: What could be done differently next time?

4. REPLICATION TIP: One specific, actionable way to replicate this post's success (or improve on it).

Write in a direct, analytical tone. Use specific observations from the content. Don't be generic.`;

	try {
		const response = await generateContent(prompt);

		return response.trim();
	} catch (error) {
		logger.error("Post analysis error:", error);
		return null;
	}
};

/**
 * Generate similar post drafts based on a successful post
 * Creates variations that capture the essence of what worked
 */
export const replicatePost = async (
	originalPost: PostAnalysisInput,
	variations: number = 3,
	userStyle?: "casual" | "professional" | "witty" | "inspirational" | "edgy",
): Promise<string[] | null> => {
	const styleGuide = userStyle
		? {
				casual: "Conversational, friendly, relatable",
				professional: "Polished but approachable, clear value",
				witty: "Clever wordplay, unexpected twists, subtle humor",
				inspirational: "Uplifting, motivating, visionary",
				edgy: "Bold, provocative, challenges conventions",
			}[userStyle]
		: "Natural and engaging";

	// Analyze what made the original work
	const hasQuestion = originalPost.content.includes("?");
	const hasEmoji = /[\u{1F300}-\u{1F9FF}]/u.test(originalPost.content);
	const contentLength = originalPost.content.length;
	const structure = originalPost.content.includes("\n")
		? "Uses line breaks for readability"
		: "Single block of text";

	const prompt = `You are a viral content creator for Threads. Create ${variations} NEW post drafts inspired by this successful post.

ORIGINAL POST (${(originalPost.engagementRate * 100).toFixed(2)}% engagement rate):
"${originalPost.content}"

WHAT MADE IT WORK:
- Format: ${structure}
- Length: ~${contentLength} characters
- Uses question: ${hasQuestion ? "Yes - this drives replies" : "No"}
- Uses emoji: ${hasEmoji ? "Yes - adds personality" : "No"}
- Topics: ${originalPost.topics?.join(", ") || "None specified"}
- Metrics: ${originalPost.views} views, ${originalPost.likes} likes, ${originalPost.replies} replies

STYLE GUIDE: ${styleGuide}

REQUIREMENTS:
1. Each post MUST be under 500 characters
2. Capture the ESSENCE of what made the original work (hook style, structure, tone)
3. Use DIFFERENT topics/angles - don't just rephrase the same thing
4. ${hasQuestion ? "Include an engaging question" : "Use a strong hook"}
5. ${hasEmoji ? "Include 1-2 relevant emojis" : "Keep it text-focused"}
6. Each variation should feel fresh and distinct

Return EXACTLY ${variations} posts, separated by "---". No numbering, explanations, or other text.`;

	try {
		const response = await generateContent(prompt);

		// Parse variations
		const drafts = response
			.split("---")
			.map((d) => d.trim())
			.filter((d) => d.length > 0 && d.length <= 500);

		return drafts.length > 0 ? drafts : null;
	} catch (error) {
		logger.error("Post replication error:", error);
		return null;
	}
};

/**
 * Analyze why a post went viral
 * Deep-dive into the factors that made a post exceptionally successful
 */
export interface ViralPostInput {
	content: string;
	views: number;
	likes: number;
	replies: number;
	reposts: number;
	shares: number;
	engagementRate: number;
	publishedAt: string;
	mediaType: "text" | "image" | "video" | "carousel" | "reels";
	viralMultiplier: number; // How many times above average
	avgViews: number;
	avgEngagement: number;
	topics?: string[] | undefined;
	accountHandle?: string | undefined;
}

export const analyzeViralPost = async (
	post: ViralPostInput,
): Promise<string | null> => {
	const totalEngagement =
		post.likes + post.replies + post.reposts + post.shares;
	const erPercent = (post.engagementRate * 100).toFixed(2);

	// Analyze content patterns
	const hasQuestion = post.content.includes("?");
	const hasEmoji = /[\u{1F300}-\u{1F9FF}]/u.test(post.content);
	const hasHashtags = post.topics && post.topics.length > 0;
	const contentLength = post.content.length;
	const hasLineBreaks = post.content.includes("\n");
	const hasMention = post.content.includes("@");
	const hasNumber = /\d+/.test(post.content);

	// Detect content type hints
	const isOpinion =
		/I think|I believe|IMO|In my opinion|Unpopular opinion/i.test(post.content);
	const isStory = /story|happened|yesterday|today|realized|learned/i.test(
		post.content,
	);
	const isAdvice = /tip|how to|secret|hack|don't|never|always|you should/i.test(
		post.content,
	);
	const isControversial =
		/controversial|debate|fight me|hot take|unpopular/i.test(post.content);
	const isHumor = /lol|lmao|😂|🤣|funny|joke/i.test(post.content);

	// Parse time
	const publishDate = new Date(post.publishedAt);
	const dayOfWeek = publishDate.toLocaleDateString("en-US", {
		weekday: "long",
	});
	const hour = publishDate.getHours();
	const timeOfDay = hour < 12 ? "morning" : hour < 17 ? "afternoon" : "evening";

	const prompt = `You are a viral content expert analyzing why this Threads post went VIRAL (${post.viralMultiplier.toFixed(1)}x above average performance).

VIRAL POST:
"${post.content}"

EXCEPTIONAL METRICS:
- Views: ${post.views.toLocaleString()} (${post.viralMultiplier.toFixed(1)}x avg of ${post.avgViews.toLocaleString()})
- Likes: ${post.likes.toLocaleString()}
- Replies: ${post.replies.toLocaleString()}
- Reposts: ${post.reposts.toLocaleString()}
- Shares: ${post.shares.toLocaleString()}
- Engagement Rate: ${erPercent}%
- Total Engagement: ${totalEngagement.toLocaleString()}

POST DETAILS:
- Media: ${post.mediaType}
- Posted: ${dayOfWeek} ${timeOfDay}
- Length: ${contentLength} characters
- Topics: ${post.topics?.join(", ") || "None tagged"}

CONTENT SIGNALS DETECTED:
${hasQuestion ? "✓ Contains engaging question" : ""}
${hasEmoji ? "✓ Uses emoji" : ""}
${hasHashtags ? "✓ Uses hashtags" : ""}
${hasLineBreaks ? "✓ Structured with line breaks" : ""}
${hasMention ? "✓ Mentions other users" : ""}
${hasNumber ? "✓ Contains numbers/stats" : ""}
${isOpinion ? "✓ Personal opinion/take" : ""}
${isStory ? "✓ Storytelling element" : ""}
${isAdvice ? "✓ Advice/tips format" : ""}
${isControversial ? "✓ Controversial angle" : ""}
${isHumor ? "✓ Humor/entertainment" : ""}

TASK: Analyze what made this post go viral. Be SPECIFIC and ACTIONABLE. Format your response as:

🔥 THE VIRAL TRIGGER
[2-3 sentences on the single most powerful element that drove virality]

⚡ KEY SUCCESS FACTORS
[3-4 bullet points on specific content/format choices that worked]

📊 ALGORITHM SIGNALS
[What likely triggered Threads' algorithm to boost this post]

🎯 HOW TO REPLICATE
[1 specific, actionable tip to recreate this success]

Keep the total response under 250 words. Be direct and insightful.`;

	try {
		const response = await generateContent(prompt);

		return response.trim();
	} catch (error) {
		logger.error("Viral analysis error:", error);
		return null;
	}
};

// ===== GOAL TRACKER AI COACHING FUNCTIONS =====

export interface TopPostStructure {
	hookLength: number;
	totalLength: number;
	emojiCount: number;
	emojiPositions: ("start" | "middle" | "end")[];
	sentenceCount: number;
	avgSentenceLength: number;
	hasQuestion: boolean;
	hasCTA: boolean;
	ctaType?: "question" | "action" | "invite" | "none" | undefined;
	lineBreaks: number;
	hashtagCount: number;
	tone: "casual" | "professional" | "inspirational" | "edgy" | "witty";
	structure:
		| "hook-body-cta"
		| "story"
		| "list"
		| "question-answer"
		| "single-punch";
}

/**
 * Analyze the structure of a top-performing post
 */
export const analyzeTopPostStructure = (
	postContent: string,
): TopPostStructure => {
	const lines = postContent.split("\n").filter((l) => l.trim());
	const sentences = postContent.split(/[.!?]+/).filter((s) => s.trim());
	const emojis =
		postContent.match(/[\p{Emoji_Presentation}\p{Extended_Pictographic}]/gu) ||
		[];
	const hashtags = postContent.match(/#\w+/g) || [];

	// Detect emoji positions
	const emojiPositions: ("start" | "middle" | "end")[] = [];
	const firstThird = postContent.length / 3;
	const lastThird = (postContent.length * 2) / 3;

	emojis.forEach((emoji) => {
		const pos = postContent.indexOf(emoji);
		if (pos < firstThird) emojiPositions.push("start");
		else if (pos > lastThird) emojiPositions.push("end");
		else emojiPositions.push("middle");
	});

	// Detect hook (first line or sentence)
	const hook = lines[0] || sentences[0] || "";

	// Detect CTA patterns
	const ctaPatterns = {
		question: /\?$/,
		action: /\b(click|tap|swipe|check|follow|share|save|comment|dm|link)\b/i,
		invite:
			/\b(let me know|drop a|tell me|thoughts\??|agree\??|what do you)\b/i,
	};

	let ctaType: "question" | "action" | "invite" | "none" = "none";
	const lastLine = lines[lines.length - 1] || "";
	if (ctaPatterns.question.test(lastLine)) ctaType = "question";
	else if (ctaPatterns.action.test(lastLine)) ctaType = "action";
	else if (ctaPatterns.invite.test(lastLine)) ctaType = "invite";

	// Detect structure type
	let structure: TopPostStructure["structure"] = "hook-body-cta";
	if (lines.length === 1) structure = "single-punch";
	else if (
		postContent.includes("1.") ||
		postContent.includes("•") ||
		postContent.includes("-")
	)
		structure = "list";
	else if (postContent.split("?").length > 2) structure = "question-answer";
	else if (lines.length > 3 && !ctaType) structure = "story";

	// Detect tone (simplified heuristic)
	let tone: TopPostStructure["tone"] = "casual";
	const exclamations = (postContent.match(/!/g) || []).length;
	const caps = (postContent.match(/[A-Z]{3,}/g) || []).length;
	if (exclamations > 2 || caps > 1) tone = "edgy";
	else if (/\b(believe|dream|achieve|inspire|success)\b/i.test(postContent))
		tone = "inspirational";
	else if (/\b(actually|honestly|real talk|truth)\b/i.test(postContent))
		tone = "witty";
	else if (/\b(strategy|data|research|analysis)\b/i.test(postContent))
		tone = "professional";

	return {
		hookLength: hook.length,
		totalLength: postContent.length,
		emojiCount: emojis.length,
		emojiPositions: [...new Set(emojiPositions)],
		sentenceCount: sentences.length,
		avgSentenceLength:
			sentences.length > 0
				? Math.round(postContent.length / sentences.length)
				: postContent.length,
		hasQuestion: postContent.includes("?"),
		hasCTA: ctaType !== "none",
		ctaType,
		lineBreaks: lines.length - 1,
		hashtagCount: hashtags.length,
		tone,
		structure,
	};
};

/**
 * Match the style of a top post - transforms content to mirror successful patterns
 */

export const analyzeABTestResults = (
	variants: {
		label: string;
		views: number;
		likes: number;
		replies: number;
		reposts: number;
	}[],
): {
	winner: string | null;
	confidence: number;
	insights: string[];
	recommendation: string;
} => {
	if (variants.length < 2) {
		return {
			winner: null,
			confidence: 0,
			insights: [],
			recommendation: "Need at least 2 variants",
		};
	}

	const results = variants.map((v) => ({
		...v,
		engagementRate:
			v.views > 0 ? (v.likes + v.replies + v.reposts) / v.views : 0,
	}));

	results.sort((a, b) => b.engagementRate - a.engagementRate);

	const best = results[0];
	const secondBest = results[1];

	const totalViews = results.reduce((sum, v) => sum + v.views, 0);
	const minViews = 100;

	let confidence = 0;
	if (totalViews >= minViews) {
		const diff = best!.engagementRate - secondBest!.engagementRate;
		const relDiff =
			secondBest!.engagementRate > 0 ? diff / secondBest!.engagementRate : 1;
		confidence = Math.min(0.99, 0.5 + relDiff * 0.5);
	}

	const insights: string[] = [];
	if (best!.replies > secondBest!.replies * 1.2) {
		insights.push(`Variant ${best!.label} drives 20%+ more replies`);
	}
	if (best!.reposts > secondBest!.reposts * 1.2) {
		insights.push(`Variant ${best!.label} gets shared more`);
	}
	if (best!.likes > secondBest!.likes * 1.2) {
		insights.push(`Variant ${best!.label} gets 20%+ more likes`);
	}

	return {
		winner: confidence >= 0.8 ? best!.label : null,
		confidence,
		insights,
		recommendation:
			confidence >= 0.8
				? `Use Variant ${best!.label} - ${((best!.engagementRate - secondBest!.engagementRate) * 100).toFixed(1)}% higher engagement`
				: totalViews < minViews
					? `Need more data (${totalViews}/${minViews} views)`
					: "Results inconclusive - continue testing",
	};
};

/**
 * Generate contextual DM response using voice profile
 */

export const identifyEvergreenPosts = (
	posts: Array<{
		published_at?: string | null | undefined;
		created_at?: string | null | undefined;
		status?: string | null | undefined;
		likes?: number | null | undefined;
		replies?: number | null | undefined;
		reposts?: number | null | undefined;
		quotes?: number | null | undefined;
		[key: string]: unknown;
	}>,
	minAgeDays: number = 30,
	avgEngagement?: number,
): Array<{
	post: {
		published_at?: string | null | undefined;
		created_at?: string | null | undefined;
		status?: string | null | undefined;
		likes?: number | null | undefined;
		replies?: number | null | undefined;
		reposts?: number | null | undefined;
		quotes?: number | null | undefined;
		[key: string]: unknown;
	};
	evergreenScore: number;
	suggestedRepostTime: string;
}> => {
	const now = Date.now();
	const msPerDay = 86400000;
	const cutoff = now - minAgeDays * msPerDay;

	// Filter posts older than minAgeDays and published
	const candidates = posts.filter((p) => {
		const published = p.published_at || p.created_at;
		if (!published) return false;
		return new Date(published).getTime() < cutoff && p.status === "published";
	});

	if (candidates.length === 0) return [];

	// Calculate average engagement if not provided
	const calcEngagement = (p: {
		likes?: number | null | undefined;
		replies?: number | null | undefined;
		reposts?: number | null | undefined;
		quotes?: number | null | undefined;
	}) =>
		(p.likes || 0) +
		(p.replies || 0) * 2 +
		(p.reposts || 0) * 3 +
		(p.quotes || 0) * 4;

	const avg =
		avgEngagement ??
		candidates.reduce((sum, p) => sum + calcEngagement(p), 0) /
			candidates.length;

	// Score and filter
	return candidates
		.map((post) => {
			const engagement = calcEngagement(post);
			const ratio = avg > 0 ? engagement / avg : 0;
			const publishedAt = post.published_at || post.created_at;
			if (!publishedAt) return null;
			// Evergreen score: engagement ratio * decay factor (older posts get slight bonus)
			const ageDays = (now - new Date(publishedAt).getTime()) / msPerDay;
			const decayBonus = Math.min(ageDays / 90, 1.5); // Max 1.5x for 90+ day old posts
			const evergreenScore = Math.round(ratio * decayBonus * 100) / 100;

			// Suggest repost at a good time (next weekday at 9 AM local)
			const suggestedDate = new Date();
			suggestedDate.setDate(suggestedDate.getDate() + 1);
			while (suggestedDate.getDay() === 0 || suggestedDate.getDay() === 6) {
				suggestedDate.setDate(suggestedDate.getDate() + 1);
			}
			suggestedDate.setHours(9, 0, 0, 0);

			return {
				post,
				evergreenScore,
				suggestedRepostTime: suggestedDate.toISOString(),
			};
		})
		.filter((item): item is NonNullable<typeof item> => item !== null)
		.filter((item) => item.evergreenScore >= 1.0) // Only above-average posts
		.sort((a, b) => b.evergreenScore - a.evergreenScore)
		.slice(0, 20);
};
