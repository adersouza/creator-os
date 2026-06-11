// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
import { randomUUID } from "@/src/lib/uuid.js";
import { logger } from "@/utils/logger";
import type { AIContext } from "./contextEngine.js";
import { contextToSystemPrompt } from "./contextEngine.js";
import { generateContent } from "./core.js";
import { calculateViralScore } from "./scoring.js";
import type { PostIdea, UserEngagementStats, VoiceProfile } from "./types.js";

export { calculateTrendBonus } from "./scoring.js";
// Re-export shared types for backward compatibility
export type { PostIdea, UserEngagementStats, VoiceProfile } from "./types.js";

export interface PostIdeasInput {
	topPosts: {
		content: string;
		likes: number;
		replies: number;
		shares: number;
	}[];
	competitorPosts?: { content: string; username: string; engagement: number }[] | undefined;
	trendingTopics?: string[] | undefined;
	userStyle?: "casual" | "professional" | "witty" | "inspirational" | "edgy" | undefined;
	goals?: ("followers" | "engagement" | "shares" | "replies")[] | undefined;
	niche?: string | undefined;
	avoidTopics?: string[] | undefined;
	voiceProfile?: VoiceProfile | undefined; // Per-account voice customization
}

/**
 * Generate a unique ID for post ideas
 */
const generateIdeaId = (): string => `idea-${randomUUID()}`;

/**
 * Calculate Jaccard similarity between two strings (0-1, where 1 is identical)
 */
const calculateJaccardSimilarity = (str1: string, str2: string): number => {
	const words1 = str1.toLowerCase().split(/\s+/);
	const words2 = str2.toLowerCase().split(/\s+/);
	const set1 = new Set(words1);
	const set2 = new Set(words2);

	const intersection = new Set([...set1].filter((x) => set2.has(x)));
	const union = new Set([...set1, ...set2]);

	return intersection.size / union.size; // Jaccard similarity
};

/**
 * Remove duplicate/similar ideas from array
 */
const deduplicateIdeas = (
	ideas: PostIdea[],
	similarityThreshold = 0.6,
): PostIdea[] => {
	const unique: PostIdea[] = [];

	for (const idea of ideas) {
		const isDuplicate = unique.some(
			(existing) =>
				calculateJaccardSimilarity(idea.content, existing.content) >
				similarityThreshold,
		);

		if (!isDuplicate) {
			unique.push(idea);
		}
	}

	return unique;
};

export const generatePostIdeas = async (
	input: PostIdeasInput,
	count: number = 8,
	aiContext?: AIContext,
): Promise<PostIdea[]> => {
	// Build context from top performing posts
	const topPostsContext = input.topPosts
		.slice(0, 5)
		.map(
			(p, i) =>
				`${i + 1}. "${p.content.slice(0, 150)}..." (${p.likes} likes, ${p.replies} replies)`,
		)
		.join("\n");

	// Competitor insights
	const competitorContext =
		input.competitorPosts && input.competitorPosts.length > 0
			? `\n\nTRENDING FROM COMPETITORS:\n${input.competitorPosts
					.slice(0, 3)
					.map(
						(p) =>
							`- @${p.username}: "${p.content.slice(0, 100)}..." (${p.engagement} engagement)`,
					)
					.join("\n")}`
			: "";

	// Trending topics with volume and priority context
	const trendsContext =
		input.trendingTopics && input.trendingTopics.length > 0
			? `\n\nTRENDING NOW (HOT TOPICS - USE THESE!):\n${input.trendingTopics
					.slice(0, 5)
					.map((topic) => {
						if (typeof topic === "string") {
							// Legacy format support
							return `• ${topic} 🔥`;
						}
						// New format with metadata
						const {
							topic: topicName,
							searchVolume,
							trending,
						} = topic as {
							topic: string;
							searchVolume: number;
							trending: boolean;
						};
						const heat =
							searchVolume >= 80
								? "🔥🔥🔥"
								: searchVolume >= 60
									? "🔥🔥"
									: "🔥";
						const badge = trending ? " [TRENDING]" : "";
						return `• ${topicName} (${searchVolume}% popularity)${badge} ${heat}`;
					})
					.join(
						"\n",
					)}\n\n💡 TIP: Subtly weave these topics into your posts for +10-15% viral score boost. Don't force it - make it feel natural!`
			: "";

	// Style and goals
	const styleMap: Record<string, string> = {
		casual: "conversational, relatable, everyday language",
		professional: "polished, authoritative, industry-focused",
		witty: "clever, playful, unexpected twists",
		inspirational: "motivational, uplifting, empowering",
		edgy: "provocative, bold, challenges status quo",
	};

	const goalsContext =
		input.goals && input.goals.length > 0
			? `\n\nOPTIMIZE FOR: ${input.goals.join(", ")}`
			: "";

	// Build voice profile context for personalized content
	let voiceContext = "";
	if (input.voiceProfile) {
		const vp = input.voiceProfile;
		const parts: string[] = [];

		if (vp.voice_profile) {
			parts.push(`VOICE/PERSONA: ${vp.voice_profile}`);
		}
		if (vp.focus_topics && vp.focus_topics.length > 0) {
			parts.push(`FOCUS TOPICS: ${vp.focus_topics.join(", ")}`);
		}
		if (vp.avoid_topics && vp.avoid_topics.length > 0) {
			parts.push(`AVOID TOPICS: ${vp.avoid_topics.join(", ")}`);
		}
		if (vp.avoid_words && vp.avoid_words.length > 0) {
			parts.push(`NEVER USE THESE WORDS: ${vp.avoid_words.join(", ")}`);
		}
		if (vp.emoji_usage) {
			const emojiGuide: Record<string, string> = {
				none: "NO emojis at all",
				minimal: "Very few emojis (0-1 per post)",
				moderate: "Moderate emoji use (2-3 per post)",
				heavy: "Use emojis liberally to add personality",
			};
			parts.push(`EMOJI STYLE: ${emojiGuide[vp.emoji_usage]}`);
		}
		if (vp.cta_style && vp.cta_style !== "none") {
			const ctaGuide: Record<string, string> = {
				link_in_bio: "End with 'link in bio' CTA",
				dm_me: "End with 'DM me' CTA",
				subscribe: "End with subscribe/follow CTA",
			};
			parts.push(`CTA STYLE: ${ctaGuide[vp.cta_style]}`);
		}

		// Add extracted style DNA if available (this is the detailed writing pattern analysis)
		// PRIORITIZED by impact: hooks > vocabulary > tone > length > formatting
		if (vp.extracted_style) {
			const es = vp.extracted_style;
			const styleParts: string[] = [];

			// 1. HOOKS - highest impact, always first
			if (es.hooks?.patterns?.length > 0) {
				styleParts.push(
					`🎯 HOOK PATTERNS (START posts with these): ${es.hooks.patterns.join(" | ")}`,
				);
			}
			if (es.hooks?.examples?.length > 0) {
				styleParts.push(
					`   Examples: "${es.hooks.examples.slice(0, 3).join('" | "')}"`,
				);
			}

			// 2. VOCABULARY - signature words make content recognizable
			if (es.vocabulary?.signature_words?.length > 0) {
				styleParts.push(
					`🗣️ SIGNATURE PHRASES (weave these in): ${es.vocabulary.signature_words.join(", ")}`,
				);
			}
			if (es.vocabulary?.tone_markers?.length > 0) {
				styleParts.push(
					`   Tone markers: ${es.vocabulary.tone_markers.join(", ")}`,
				);
			}

			// 3. TONE & VIBE - overall feel
			if (es.tone?.vibe) {
				styleParts.push(
					`🎭 VIBE: ${es.tone.vibe} (${es.tone.energy || "moderate"} energy)`,
				);
			}

			// 4. LENGTH - keep posts consistent
			if (es.length?.typical_chars) {
				styleParts.push(
					`📏 LENGTH: ${es.length.typical_chars} chars typical (${es.length.preference})`,
				);
			}

			// 5. SENTENCE STYLE
			if (es.sentence_patterns) {
				styleParts.push(
					`✍️ SENTENCES: ${es.sentence_patterns.avg_length}, ${es.sentence_patterns.structure}. ${es.sentence_patterns.rhythm}`,
				);
			}

			// 6. EMOJI
			if (es.emoji_usage) {
				const emojiDetails = [];
				if (es.emoji_usage.frequency)
					emojiDetails.push(es.emoji_usage.frequency);
				if (es.emoji_usage.placement)
					emojiDetails.push(`at ${es.emoji_usage.placement}`);
				if (es.emoji_usage.favorites?.length > 0) {
					emojiDetails.push(`prefer: ${es.emoji_usage.favorites.join(" ")}`);
				}
				if (emojiDetails.length > 0) {
					styleParts.push(`😊 EMOJIS: ${emojiDetails.join(", ")}`);
				}
			}

			// 7. PUNCTUATION QUIRKS
			if (es.punctuation?.quirks?.length > 0) {
				styleParts.push(`❗ PUNCTUATION: ${es.punctuation.quirks.join(", ")}`);
			}

			// 8. FORMATTING
			if (es.formatting) {
				const formatDetails = [];
				if (es.formatting.line_breaks)
					formatDetails.push(`${es.formatting.line_breaks} line breaks`);
				if (es.formatting.lists) formatDetails.push("uses lists");
				if (es.formatting.caps_usage && es.formatting.caps_usage !== "none") {
					formatDetails.push(`caps for ${es.formatting.caps_usage}`);
				}
				if (formatDetails.length > 0) {
					styleParts.push(`📐 FORMAT: ${formatDetails.join(", ")}`);
				}
			}

			// 9. CLOSINGS
			if (es.closings?.patterns?.length > 0) {
				styleParts.push(`🔚 CLOSINGS: ${es.closings.patterns.join(", ")}`);
			}

			// 10. AVOID (from vocabulary)
			if (es.vocabulary?.avoid_words?.length > 0) {
				styleParts.push(
					`🚫 NEVER USE: ${es.vocabulary.avoid_words.join(", ")}`,
				);
			}

			if (styleParts.length > 0) {
				// Add violation avoidance clause
				const violationClause = `\n⛔ VIOLATIONS (do NOT add these):
- Motivational quotes or inspirational fluff
- Corporate jargon or buzzwords
- Long explanations or disclaimers
- Questions unless they appear in the hook patterns above
- Generic phrases like "Let me know what you think"
Stick STRICTLY to this DNA. Write as if you ARE this person.`;

				parts.push(
					`\n📝 WRITING DNA (extracted from top posts - MATCH EXACTLY):\n${styleParts.join("\n")}${violationClause}`,
				);
			}
		}

		if (parts.length > 0) {
			voiceContext = `\n\n🎭 VOICE PROFILE (CRITICAL - MATCH THIS EXACTLY):\n${parts.join("\n")}`;
		}
	}

	// Load feedback context for personalization
	let feedbackContext = "";
	try {
		const { buildFeedbackContext } = await import(
			"../../utils/buildFeedbackContext.js"
		);
		feedbackContext = await buildFeedbackContext("post_idea");
	} catch {
		/* non-critical */
	}

	// If unified AI context is provided, use it as additional context preamble
	const aiContextPreamble = aiContext
		? `${contextToSystemPrompt(aiContext)}\n\n`
		: "";

	// Build the prompt - voice profile takes priority if present
	const hasVoiceProfile = voiceContext.length > 0;

	const prompt = hasVoiceProfile
		? `You are a social media content creator. CRITICAL: You MUST write in this specific voice/persona - this is NON-NEGOTIABLE:
${voiceContext}

Generate ${count} post ideas that PERFECTLY match this voice. Every single post must sound like it was written by this persona.

REFERENCE - Their top performing posts:
${topPostsContext || "No historical data available"}
${competitorContext}
${trendsContext}
${goalsContext}
${feedbackContext}

REQUIREMENTS:
1. Each post MUST match the voice profile above - this is the #1 priority
2. Keep posts under 500 characters
3. Make every first line attention-grabbing
4. Posts should feel authentic to the persona
5. Include a mix of content types but always in-character

Return ONLY a JSON array with ${count} objects in this exact format:`
		: `You are an elite social media strategist creating viral Threads posts. Generate ${count} highly engaging post ideas based on this data:

YOUR TOP PERFORMING POSTS:
${topPostsContext || "No historical data available"}
${competitorContext}
${trendsContext}
${goalsContext}
${feedbackContext}

STYLE: ${styleMap[input.userStyle || "casual"]}
${input.niche ? `NICHE: ${input.niche}` : ""}
${input.avoidTopics?.length ? `AVOID: ${input.avoidTopics.join(", ")}` : ""}

REQUIREMENTS:
1. Each post must be under 500 characters
2. Use patterns from top-performing posts but make them FRESH
3. Include a mix of: hooks, questions, stories, lists, controversial takes
4. Make every first line SCROLL-STOPPING
5. Natural emoji usage (1-3 per post max)
6. Vary the formats and tones
7. Each idea should feel immediately postable

Return ONLY a JSON array with ${count} objects in this exact format:`;

	const jsonFormat = `
[
  {
    "content": "The full post text here...",
    "category": "hook|story|question|list|controversial|educational|personal",
    "mediaType": "text|image|carousel|video",
    "mediaSuggestion": "Optional: describe ideal visual if not text-only",
    "inspiration": "What pattern/insight inspired this",
    "hooks": ["Alternative hook 1", "Alternative hook 2"],
    "hashtags": ["relevant", "hashtags"],
    "tone": "casual|professional|witty|inspirational|edgy"
  }
]`;

	const fullPrompt = aiContextPreamble + prompt + jsonFormat;

	try {
		const response = await generateContent(fullPrompt);

		// Parse JSON from response with fallback handling
		let jsonStr = response;
		if (response.includes("```json")) {
			jsonStr = response.split("```json")[1]!.split("```")[0]!.trim();
		} else if (response.includes("```")) {
			jsonStr = response.split("```")[1]!.split("```")[0]!.trim();
		}

		let rawIdeas: Omit<PostIdea, "id" | "viralScore" | "estimatedEngagement">[];
		try {
			rawIdeas = JSON.parse(jsonStr);
		} catch (parseError) {
			logger.error(
				"JSON parse failed, attempting to extract array:",
				parseError,
			);
			// Try to find JSON array in the response
			const arrayMatch = jsonStr.match(/\[\s*\{[\s\S]*\}\s*\]/);
			if (arrayMatch) {
				try {
					rawIdeas = JSON.parse(arrayMatch[0]);
				} catch (retryError) {
					logger.error("Retry JSON parse failed:", retryError);
					return [];
				}
			} else {
				return [];
			}
		}

		if (!Array.isArray(rawIdeas) || rawIdeas.length === 0) {
			logger.error("Invalid or empty ideas array");
			return [];
		}

		// Compute user's real average engagement from their top posts for calibrated estimates
		const userStats: UserEngagementStats = {
			avgLikes: 0,
			avgReplies: 0,
			avgShares: 0,
		};
		if (input.topPosts.length > 0) {
			const posts = input.topPosts;
			userStats.avgLikes = Math.round(
				posts.reduce((s, p) => s + (p.likes || 0), 0) / posts.length,
			);
			userStats.avgReplies = Math.round(
				posts.reduce((s, p) => s + (p.replies || 0), 0) / posts.length,
			);
			userStats.avgShares = Math.round(
				posts.reduce((s, p) => s + (p.shares || 0), 0) / posts.length,
			);
		}

		// Enrich with viral scores and IDs
		const enrichedIdeas = rawIdeas.map((idea, _index) => {
			const hasQuestion = idea.content.includes("?");
			const isControversial =
				idea.category === "controversial" ||
				/^(unpopular|hot take|controversial)/i.test(idea.content);
			const hasMedia = idea.mediaType !== "text";

			// Estimate hook strength from content patterns
			let hookStrength = 5;
			if (/^[A-Z]/.test(idea.content)) hookStrength += 1;
			if (idea.content.length < 50) hookStrength += 1; // Short punchy start
			if (/^(stop|don't|here's|the truth|nobody|unpopular)/i.test(idea.content))
				hookStrength += 2;
			if (/^(i |my |we )/i.test(idea.content)) hookStrength += 1; // Personal

			// Normalize trending topics to the expected format
			const normalizedTrending = input.trendingTopics?.map((topic) =>
				typeof topic === "string"
					? { topic, searchVolume: 50, trending: false }
					: topic,
			);

			let viralScore = calculateViralScore(
				idea.content,
				hasMedia,
				idea.category as PostIdea["category"],
				isControversial,
				hasQuestion,
				Math.min(hookStrength, 10),
				normalizedTrending,
				userStats,
			);

			// Validate and clamp viral score to 0-100
			if (Number.isNaN(viralScore) || viralScore < 0) viralScore = 0;
			if (viralScore > 100) viralScore = 100;

			// Estimate engagement calibrated to user's real metrics
			// Instead of arbitrary multipliers, scale relative to their actual averages
			const hasRealData = userStats.avgLikes > 0;
			const scoreRatio = viralScore / 50; // 1.0 = average post, >1 = above average
			const estimatedEngagement = hasRealData
				? {
						likes: Math.round(
							userStats.avgLikes * scoreRatio * (hasMedia ? 1.2 : 1),
						),
						replies: Math.round(
							userStats.avgReplies * scoreRatio * (hasQuestion ? 1.5 : 1),
						),
						shares: Math.round(
							userStats.avgShares * scoreRatio * (isControversial ? 1.5 : 1),
						),
					}
				: {
						// Fallback for users with no post data yet
						likes: Math.round(viralScore * 0.5),
						replies: Math.round(viralScore * 0.1 * (hasQuestion ? 1.5 : 1)),
						shares: Math.round(viralScore * 0.05 * (isControversial ? 1.5 : 1)),
					};

			return {
				...idea,
				id: generateIdeaId(),
				viralScore,
				estimatedEngagement,
				category: idea.category as PostIdea["category"],
				mediaType: idea.mediaType as PostIdea["mediaType"],
			};
		});

		// Deduplicate similar ideas and sort by viral score
		const uniqueIdeas = deduplicateIdeas(enrichedIdeas, 0.6);
		return uniqueIdeas.sort((a, b) => b.viralScore - a.viralScore);
	} catch (error) {
		logger.error("Post ideas generation error:", error);
		return [];
	}
};

/**
 * Regenerate variations of a specific post idea
 */
export const regeneratePostIdea = async (
	originalIdea: PostIdea,
	style?: "shorter" | "punchier" | "controversial" | "question" | "story",
): Promise<PostIdea | null> => {
	const styleInstructions: Record<string, string> = {
		shorter:
			"Make it more concise and punchy. Cut unnecessary words. Max 200 chars.",
		punchier:
			"Add more energy, stronger verbs, bolder claims. Make it impossible to ignore.",
		controversial:
			"Add a controversial angle or hot take. Challenge common assumptions.",
		question: "Reframe as an engaging question that invites responses.",
		story: "Rewrite as a short personal story or anecdote format.",
	};

	const prompt = `Transform this Threads post while keeping the core message:

Original: "${originalIdea.content}"

Style: ${styleInstructions[style || "punchier"]}

Requirements:
1. Keep under 500 characters
2. Must feel completely fresh, not a minor edit
3. Include 1-2 emojis naturally
4. Make the first line a hook

Return ONLY a JSON object:
{
  "content": "The new post text",
  "category": "hook|story|question|list|controversial|educational|personal",
  "mediaType": "text|image|carousel|video",
  "hooks": ["Alternative hook 1", "Alternative hook 2"],
  "hashtags": ["relevant", "tags"],
  "tone": "casual|professional|witty|inspirational|edgy"
}`;

	try {
		const response = await generateContent(prompt);

		let jsonStr = response;
		if (response.includes("```json")) {
			jsonStr = response.split("```json")[1]!.split("```")[0]!.trim();
		} else if (response.includes("```")) {
			jsonStr = response.split("```")[1]!.split("```")[0]!.trim();
		}

		// biome-ignore lint/suspicious/noExplicitAny: JSON.parse result typed after validation
		let newIdea: any;
		try {
			newIdea = JSON.parse(jsonStr);
		} catch (parseError) {
			logger.error(
				"JSON parse failed in regenerate, attempting to extract object:",
				parseError,
			);
			// Try to find JSON object in the response
			const objectMatch = jsonStr.match(/\{\s*"[\s\S]*\}/);
			if (objectMatch) {
				try {
					newIdea = JSON.parse(objectMatch[0]);
				} catch (retryError) {
					logger.error("Retry JSON parse failed:", retryError);
					return null;
				}
			} else {
				return null;
			}
		}

		const hasQuestion = newIdea.content.includes("?");
		const isControversial = newIdea.category === "controversial";
		const hasMedia = newIdea.mediaType !== "text";

		const viralScore = calculateViralScore(
			newIdea.content,
			hasMedia,
			newIdea.category,
			isControversial,
			hasQuestion,
			7, // Regenerated ideas tend to have better hooks
			undefined, // Trending topics not available for regeneration
		);

		return {
			...newIdea,
			id: generateIdeaId(),
			viralScore,
			inspiration: `Regenerated from: "${originalIdea.content.slice(0, 50)}..."`,
			mediaSuggestion: originalIdea.mediaSuggestion,
			estimatedEngagement: {
				// Use conservative fallback multipliers for regenerated ideas
				// (no top post data available in this context)
				likes: Math.round(viralScore * 0.5),
				replies: Math.round(viralScore * 0.1 * (hasQuestion ? 1.5 : 1)),
				shares: Math.round(viralScore * 0.05 * (isControversial ? 1.5 : 1)),
			},
		};
	} catch (error) {
		logger.error("Regenerate post idea error:", error);
		return null;
	}
};

// ===== LIVE FEED ADAPT IDEA FUNCTION =====
