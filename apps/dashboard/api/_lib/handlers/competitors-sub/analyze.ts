/**
 * POST /api/competitors/analyze — "Steal Their Strategy" AI feature
 *
 * Analyzes a competitor's content patterns, compares to user's style,
 * and generates 3 adapted content ideas.
 *
 * Body: { competitorId: string, accountId: string }
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";
import { getUserAIConfig } from "../../aiConfig.js";
import { apiError, apiSuccess } from "../../apiResponse.js";
import { logger } from "../../logger.js";
import { withAuth } from "../../middleware.js";
import { escapeForPrompt, sanitizeAIOutput } from "../../promptUtils.js";
import { checkRateLimit } from "../../rateLimiter.js";
import { describeValue } from "../../sanitizeForAI.js";
import { getSupabase } from "../../supabase.js";
import { generateWithProvider } from "../auto-post/aiProviders.js";
import {
	verifyAccountOwnership,
	verifyCompetitorOwnership,
} from "../helpers/verifyOwnership.js";

export default withAuth(
	async (req: VercelRequest, res: VercelResponse, user) => {
		if (req.method !== "POST") {
			return apiError(res, 405, "Method not allowed");
		}

		const { competitorId, accountId } = req.body || {};
		if (!competitorId || typeof competitorId !== "string") {
			return apiError(res, 400, "competitorId is required");
		}
		if (!accountId || typeof accountId !== "string") {
			return apiError(res, 400, "accountId is required");
		}

		// Rate limit: 5 per hour
		const rl = await checkRateLimit({
			key: `steal-strategy:${user.id}`,
			limit: 5,
			windowSeconds: 3600,
			failMode: "closed",
		});
		if (!rl.allowed) {
			return apiError(
				res,
				429,
				"Rate limit exceeded (5 per hour). Try again later.",
			);
		}

		// Verify account ownership (IDOR prevention)
		// biome-ignore lint/suspicious/noExplicitAny: competitor corpus columns may lead generated DB types
		const db = getSupabase() as any;
		const ownedAccount = await verifyAccountOwnership(res, accountId, user.id);
		if (!ownedAccount) return;

		const aiConfig = await getUserAIConfig(user.id);
		if (!aiConfig) {
			return apiError(
				res,
				503,
				"AI features temporarily unavailable. Add your own API key in Settings for immediate access.",
				{ code: "NO_API_KEY" },
			);
		}

		// Fetch competitor info
		const competitor = (await verifyCompetitorOwnership(
			res,
			competitorId,
			user.id,
			"id, username, display_name, follower_count, bio, platform",
		)) as {
			id: string;
			username: string;
			display_name: string;
			follower_count: number;
			bio: string;
			platform: string;
		} | null;
		if (!competitor) return;

		// Fetch competitor corpus. Threads competitor stats are usually
		// unavailable, so only rankable metric rows can be treated as estimated
		// performance evidence; otherwise this is a pattern analysis sample.
		const { data: competitorPosts } = await db
			.from("competitor_top_posts")
			.select(
				"content, media_type, like_count, reply_count, repost_count, view_count, engagement_score, published_at, scraped_at, metric_quality, hook_type, topic_label, format_type, emotional_frame, cta_style, content_length_bucket, media_style, posting_hour",
			)
			.eq("competitor_id", competitorId)
			.order("scraped_at", { ascending: false, nullsFirst: false })
			.limit(10);

		if (!competitorPosts || competitorPosts.length === 0) {
			return apiError(
				res,
				400,
				"No competitor posts available. Sync this competitor first.",
			);
		}

		// Fetch user's recent posts
		const { data: userPosts } = await db
			.from("posts")
			.select("text, media_type, published_at, performance")
			.eq("account_id", accountId)
			.order("published_at", { ascending: false })
			.limit(10);

		// Fetch user's voice profile from account_groups
		let voiceProfile = "";
		try {
			const { data: groups } = await db
				.from("account_groups")
				.select("voice_profile, account_ids")
				.eq("user_id", user.id)
				.not("voice_profile", "is", null);

			if (groups && groups.length > 0) {
				for (const group of groups) {
					const accountIds = (group.account_ids || []) as string[];
					if (accountIds.includes(accountId) && group.voice_profile) {
						const vp = group.voice_profile;
						voiceProfile =
							typeof vp === "string"
								? vp
								: ((vp as Record<string, unknown>).voice_profile as string) ||
									JSON.stringify(vp);
						break;
					}
				}
			}
		} catch (err) {
			logger.debug("Failed to fetch voice profile for competitor analysis", {
				accountId,
				error: String(err),
			});
			// Voice profile is optional
		}

		// Build the prompt
		const competitorPostsText = (competitorPosts as Array<{
			content?: string | null;
			media_type?: string | null;
			like_count?: number | null;
			reply_count?: number | null;
			repost_count?: number | null;
			view_count?: number | null;
			metric_quality?: string | null;
			hook_type?: string | null;
			topic_label?: string | null;
			format_type?: string | null;
			emotional_frame?: string | null;
			cta_style?: string | null;
			content_length_bucket?: string | null;
			media_style?: string | null;
			posting_hour?: number | null;
		}>)
			.map(
				(p, i) => {
					const quality = p.metric_quality || "stats_unavailable";
					const isRankable =
						quality === "valid_engagement" || quality === "scraper_estimated";
					const metrics =
						isRankable
							? `${quality} metrics: likes ${describeValue(p.like_count || 0)}, replies ${describeValue(p.reply_count || 0)}, reposts ${describeValue(p.repost_count || 0)}, views ${describeValue(p.view_count || 0)}`
							: `metric_quality: ${quality}; use as pattern corpus, not proof of performance`;
					return `${i + 1}. "${escapeForPrompt((p.content || "").slice(0, 300))}" [${p.media_type || "TEXT"}, ${metrics}, hook: ${p.hook_type || "unknown"}, topic: ${p.topic_label || "uncategorized"}, format: ${p.format_type || "unknown"}, media_style: ${p.media_style || "unknown"}, posting_hour: ${typeof p.posting_hour === "number" ? p.posting_hour : "unknown"}, frame: ${p.emotional_frame || "unknown"}, cta: ${p.cta_style || "none"}, length: ${p.content_length_bucket || "unknown"}]`;
				},
			)
			.join("\n");

		const userPostsText = (
			(userPosts as unknown as Array<{
				text?: string | null | undefined;
				media_type?: string | null | undefined;
			}>) || []
		)
			.map(
				(p, i: number) =>
					`${i + 1}. "${escapeForPrompt((p.text || "").slice(0, 300))}" [${p.media_type || "TEXT"}]`,
			)
			.join("\n");

		const prompt = `You are a social media strategist. Analyze a competitor's content patterns, compare them to the user's style, and generate 3 content ideas that adapt recurring patterns to the user's voice.

COMPETITOR: @${competitor.username} (${competitor.display_name}, ${(competitor.follower_count || 0).toLocaleString()} followers)
${competitor.bio ? `Bio: ${escapeForPrompt(competitor.bio)}` : ""}

COMPETITOR CORPUS SAMPLE:
${competitorPostsText}

Important: Treat rows with metric_quality other than valid_engagement or scraper_estimated as pattern evidence only. Do not claim they are top-performing or high-impression posts.

USER'S RECENT POSTS:
${userPostsText || "(No recent posts)"}

${voiceProfile ? `USER'S VOICE PROFILE:\n${escapeForPrompt(voiceProfile)}` : ""}

Generate exactly 3 content ideas. For each idea, provide:
1. topic: A clear topic/angle
2. format: Suggested format (Reel, Carousel, or Text Post)
3. caption: A full draft caption in the user's voice (or a natural engaging tone if no voice profile). Include relevant hashtags.
4. bestTimeToPost: Suggested day and time based on the competitor's posting patterns
5. reasoning: Brief explanation of why this works (what competitor pattern it adapts, not fake performance claims)

Respond ONLY with valid JSON in this exact format:
{
  "ideas": [
    {
      "topic": "...",
      "format": "Reel" | "Carousel" | "Text Post",
      "caption": "...",
      "bestTimeToPost": "...",
      "reasoning": "..."
    }
  ],
  "competitorInsight": "A 1-2 sentence summary of recurring competitor patterns and where valid metrics were or were not available"
}`;

		try {
			const modelId = aiConfig.model || "gemini-2.5-flash";
			const response = await generateWithProvider(prompt, {
				provider: aiConfig.provider,
				apiKey: aiConfig.apiKey,
				baseUrl: aiConfig.baseUrl,
				model: modelId,
				keySource: aiConfig.source,
				ideaCount: 3,
				useStructuredOutput: true,
				structuredOutputSchema: {
					type: "OBJECT",
					properties: {
						ideas: {
							type: "ARRAY",
							items: {
								type: "OBJECT",
								properties: {
									topic: { type: "STRING" },
									format: { type: "STRING" },
									caption: { type: "STRING" },
									bestTimeToPost: { type: "STRING" },
									reasoning: { type: "STRING" },
								},
								required: ["topic", "format", "caption", "bestTimeToPost", "reasoning"],
							},
						},
						competitorInsight: { type: "STRING" },
					},
					required: ["ideas", "competitorInsight"],
				},
				actionLog: {
					userId: user.id,
					accountId,
					surface: "analytics",
					actionType: "competitor_analysis",
					inputText: prompt.slice(0, 8000),
					metadata: {
						competitorId,
						competitorUsername: competitor.username,
						provider: aiConfig.provider,
					},
				},
			});

			const text = response || "";
			let parsed: {
				ideas?: {
                    					caption?: string | undefined;
                    					reasoning?: string | undefined;
                    					[key: string]: unknown;
                    				}[] | undefined;
				competitorInsight?: string | undefined;
			};
			try {
				parsed = JSON.parse(text);
			} catch (err) {
				logger.debug(
					"Failed to parse Gemini JSON response for competitor analysis",
					{ error: String(err) },
				);
				// Try to extract JSON from the response
				const jsonMatch = text.match(/\{[\s\S]*\}/);
				if (jsonMatch) {
					parsed = JSON.parse(jsonMatch[0]);
				} else {
					throw new Error("Failed to parse AI response");
				}
			}

			// Sanitize AI-generated text before returning to client
			const ideas = (parsed.ideas || []).map(
				(idea: {
					caption?: string | undefined;
					reasoning?: string | undefined;
					[key: string]: unknown;
				}) => ({
					...idea,
					caption: idea.caption ? sanitizeAIOutput(idea.caption) : "",
					reasoning: idea.reasoning ? sanitizeAIOutput(idea.reasoning) : "",
				}),
			);
			const competitorInsight = parsed.competitorInsight
				? sanitizeAIOutput(parsed.competitorInsight)
				: "";

			return apiSuccess(res, {
				ideas,
				competitorInsight,
				competitor: {
					username: competitor.username,
					displayName: competitor.display_name,
				},
			});
		} catch (error: unknown) {
			logger.error("[steal-strategy] AI generation failed", {
				error: String(error),
			});
			return apiError(res, 500, "AI analysis failed. Please try again.");
		}
	},
);
