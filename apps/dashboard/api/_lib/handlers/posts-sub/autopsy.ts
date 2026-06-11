// Meta Platform Terms: Do not send exact API metrics to third-party AI services
/**
 * POST /api/posts/autopsy — AI analysis of why a post performed above/below average
 * Accepts { postId: string }
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";
import { getUserAIConfig } from "../../aiConfig.js";
import {
	AI_CACHE_TTL,
	buildAICacheKey,
	getCachedAIResponse,
	setCachedAIResponse,
} from "../../aiCache.js";
import { apiError, apiSuccess } from "../../apiResponse.js";
import { logger } from "../../logger.js";
import { withAuth } from "../../middleware.js";
import { escapeForPrompt, sanitizeAIOutput } from "../../promptUtils.js";
import { checkRateLimit } from "../../rateLimiter.js";
import {
	describeRelativePerformance,
	sanitizeMetrics,
} from "../../sanitizeForAI.js";
import { getSupabase } from "../../supabase.js";
import { generateWithProvider } from "../auto-post/aiProviders.js";

export default withAuth(
	async (req: VercelRequest, res: VercelResponse, user) => {
		if (req.method !== "POST") {
			return apiError(res, 405, "Method not allowed");
		}

		const { postId } = req.body || {};
		if (!postId || typeof postId !== "string") {
			return apiError(res, 400, "postId is required");
		}

		// Rate limit
		const rl = await checkRateLimit({
			key: `autopsy:${user.id}`,
			limit: 20,
			windowSeconds: 60,
			failMode: "closed",
		});
		if (!rl.allowed) {
			return apiError(res, 429, "Rate limit exceeded");
		}

		const aiConfig = await getUserAIConfig(user.id);
		if (!aiConfig) {
			return apiError(
				res,
				503,
				"AI features temporarily unavailable. Add your own API key in Settings for immediate access.",
				{ code: "NO_API_KEY" },
			);
		}

		const supabase = getSupabase();

		// Fetch the post (IDOR fix: scope to authenticated user)
		const { data: post, error: postError } = await supabase
			.from("posts")
			.select("*")
			.eq("id", postId)
			.eq("user_id", user.id)
			.maybeSingle();

		if (postError || !post) {
			return apiError(res, 404, "Post not found");
		}

		// Fetch account averages (exclude the post being analyzed; 90-day rolling window)
		const ninetyDaysAgo = new Date(Date.now() - 90 * 24 * 60 * 60 * 1000).toISOString();
		const { data: avgData } = await supabase
			.from("posts")
			.select(
				"views_count, likes_count, replies_count, reposts_count, engagement_rate",
			)
			.eq("account_id", post.account_id ?? "")
			.neq("id", postId)
			.gte("published_at", ninetyDaysAgo)
			.not("views_count", "is", null);

		const accountAvgs = {
			avgViews: 0,
			avgLikes: 0,
			avgReplies: 0,
			avgReposts: 0,
			avgEngagement: 0,
			totalPosts: 0,
		};

		if (avgData && avgData.length > 0) {
			accountAvgs.totalPosts = avgData.length;
			accountAvgs.avgViews =
				avgData.reduce((s, p) => s + (p.views_count || 0), 0) / avgData.length;
			accountAvgs.avgLikes =
				avgData.reduce((s, p) => s + (p.likes_count || 0), 0) / avgData.length;
			accountAvgs.avgReplies =
				avgData.reduce((s, p) => s + (p.replies_count || 0), 0) /
				avgData.length;
			accountAvgs.avgReposts =
				avgData.reduce((s, p) => s + (p.reposts_count || 0), 0) /
				avgData.length;
			accountAvgs.avgEngagement =
				avgData.reduce((s, p) => s + (p.engagement_rate || 0), 0) /
				avgData.length;
		}

		const postViews = post.views_count || 0;
		const performanceLabel =
			postViews > accountAvgs.avgViews ? "above" : "below";

		// Sanitize metrics: use relative descriptions instead of exact Meta API numbers
		const postMetricsDesc = sanitizeMetrics({
			views: postViews,
			likes: post.likes_count || 0,
			replies: post.replies_count || 0,
			reposts: post.reposts_count || 0,
		});
		const relativeViews = describeRelativePerformance(
			postViews,
			accountAvgs.avgViews,
			"views",
		);
		const relativeLikes = describeRelativePerformance(
			post.likes_count || 0,
			accountAvgs.avgLikes,
			"likes",
		);
		const relativeReplies = describeRelativePerformance(
			post.replies_count || 0,
			accountAvgs.avgReplies,
			"replies",
		);

		const prompt = `Analyze why this ${post.platform || "threads"} post performed ${performanceLabel} average.

Post data:
- Caption: "${escapeForPrompt((post.content || "").slice(0, 500))}"
- Performance: ${postMetricsDesc}
- Content type: ${post.media_type || "TEXT"}
- Posted at: ${post.published_at || "unknown"}

Relative performance vs account average (${accountAvgs.totalPosts} posts):
- ${relativeViews}
- ${relativeLikes}
- ${relativeReplies}

Base your analysis ONLY on the post content, time, and relative performance data above. Do not speculate about algorithm behavior, external trends, or platform mechanics.

Provide exactly 3 specific factors that explain this post's ${performanceLabel}-average performance. Be concise and actionable. Format as JSON: {"performance": "above|below", "factors": [{"title": "...", "explanation": "..."}], "recommendation": "..."}`;

		try {
			const model = aiConfig.model || "gemini-2.5-flash";
			// Cost savings: cache autopsy results by prompt hash (TTL 24h)
			const cacheKey = buildAICacheKey(
				prompt,
				model,
				0.6,
				user.id,
			);
			const cached = await getCachedAIResponse(cacheKey);
			if (cached) {
				try {
					const analysis = JSON.parse(cached);
					return apiSuccess(res, { analysis, structured: true, cached: true });
				} catch (err) {
					logger.debug("fall through", { error: String(err) });
				}
			}

			const response = await generateWithProvider(prompt, {
				provider: aiConfig.provider,
				apiKey: aiConfig.apiKey,
				baseUrl: aiConfig.baseUrl,
				model,
				keySource: aiConfig.source,
				ideaCount: 1,
				useStructuredOutput: true,
				structuredOutputSchema: {
					type: "OBJECT",
					properties: {
						performance: { type: "STRING" },
						factors: {
							type: "ARRAY",
							items: {
								type: "OBJECT",
								properties: {
									title: { type: "STRING" },
									explanation: { type: "STRING" },
								},
								required: ["title", "explanation"],
							},
						},
						recommendation: { type: "STRING" },
					},
					required: ["performance", "factors", "recommendation"],
				},
				actionLog: {
					userId: user.id,
					accountId: post.account_id ?? null,
					surface: "analytics",
					actionType: "post_autopsy",
					inputText: prompt.slice(0, 8000),
					metadata: { postId, provider: aiConfig.provider },
				},
			});

			const text = (response || "").trim();
			const jsonMatch = text.match(/\{[\s\S]*\}/);
			if (!jsonMatch) {
				return apiSuccess(res, { analysis: text, structured: false });
			}

			const rawAnalysis = JSON.parse(jsonMatch[0]);
			const analysis = {
				...rawAnalysis,
				recommendation: rawAnalysis.recommendation
					? sanitizeAIOutput(rawAnalysis.recommendation)
					: "",
				factors: Array.isArray(rawAnalysis.factors)
					? rawAnalysis.factors.map(
							(f: { title?: string | undefined; explanation?: string | undefined }) => ({
								...f,
								explanation: f.explanation
									? sanitizeAIOutput(f.explanation)
									: "",
							}),
						)
					: [],
			};

			// Cache for 24 hours
			await setCachedAIResponse(
				cacheKey,
				JSON.stringify(analysis),
				AI_CACHE_TTL.ANALYTICS_INSIGHTS,
			);

			return apiSuccess(res, { analysis, structured: true });
		} catch (err: unknown) {
			logger.error("[posts/autopsy] Analysis failed", {
				error: err instanceof Error ? err.message : String(err),
			});
			return apiError(res, 502, "AI analysis failed");
		}
	},
);
