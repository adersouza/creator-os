/**
 * Sentiment Scan for Post Comments
 *
 * GET /api/posts/sentiment-scan?postId=...&platform=threads|instagram&limit=50
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";
import { getUserAIConfig } from "../../aiConfig.js";
import { apiError, apiSuccess } from "../../apiResponse.js";
import { logger } from "../../logger.js";
import { withAuth } from "../../middleware.js";
import { checkRateLimit } from "../../rateLimiter.js";
import { getRedis } from "../../redis.js";
import { getSupabase } from "../../supabase.js";
import { z } from "../../zodCompat.js";
import { generateWithProvider } from "../auto-post/aiProviders.js";

// biome-ignore lint/suspicious/noExplicitAny: table not yet in generated types
const db = (): any => getSupabase();

const GEMINI_MODEL = "gemini-2.5-flash";
const CACHE_TTL_SECONDS = 24 * 60 * 60;
const VALID_VERDICTS = [
	"hype",
	"drama",
	"positive",
	"neutral",
	"negative",
	"mixed",
] as const;

const LlmResultSchema = z.object({
	overall_verdict: z.string(),
	hype_score: z.number(),
	drama_score: z.number(),
	positivity: z.number(),
	negativity: z.number(),
	summary: z.string(),
	top_themes: z.array(z.string()),
	concerning_count: z.number(),
});

type LlmResult = typeof LlmResultSchema["_output"];

function clamp(n: number): number {
	return Math.min(100, Math.max(0, n));
}

function sanitizeLlmResult(raw: LlmResult): LlmResult {
	const verdict = VALID_VERDICTS.includes(
		raw.overall_verdict as (typeof VALID_VERDICTS)[number],
	)
		? raw.overall_verdict
		: "neutral";

	return {
		overall_verdict: verdict,
		hype_score: clamp(Math.round(raw.hype_score)),
		drama_score: clamp(Math.round(raw.drama_score)),
		positivity: clamp(Math.round(raw.positivity)),
		negativity: clamp(Math.round(raw.negativity)),
		summary: (raw.summary || "").substring(0, 280),
		top_themes: (raw.top_themes || []).slice(0, 5),
		concerning_count: Math.max(0, Math.round(raw.concerning_count || 0)),
	};
}

export default withAuth(
	async (req: VercelRequest, res: VercelResponse, user) => {
		if (req.method !== "GET") {
			return apiError(res, 405, "Method not allowed");
		}

		const userId = user.id;
		const postId = req.query.postId as string;
		const platform = req.query.platform as string;
		const limit = Math.min(
			Math.max(parseInt(req.query.limit as string, 10) || 50, 1),
			100,
		);

		if (!postId) return apiError(res, 400, "postId is required");
		if (!platform || !["threads", "instagram"].includes(platform)) {
			return apiError(res, 400, "platform must be 'threads' or 'instagram'");
		}

		const rl = await checkRateLimit({
			key: `sentiment-scan:${userId}`,
			limit: 30,
			windowSeconds: 60,
			failMode: "closed",
		});
		if (!rl.allowed) {
			return apiError(res, 429, "Rate limit exceeded");
		}

		// Verify post belongs to user
		const { data: post, error: postError } = await db()
			.from("posts")
			.select("id, account_id, content")
			.eq("id", postId)
			.eq("user_id", userId)
			.maybeSingle();

		if (postError)
			return apiError(res, 500, "Failed to verify post", {
				details: postError.message,
			});
		if (!post) return apiError(res, 404, "Post not found");

		// Lazy import sentiment
		const { analyzeSentiment } = await import("../../sentiment.js");

		// Fetch comments based on platform
		let comments: Array<{
			id: string;
			username: string;
			text: string;
			created_at: string;
		}> = [];

		if (platform === "threads") {
			const { data, error } = await db()
				.from("post_replies")
				.select("id, username, content, likes_count, created_at")
				.eq("post_id", postId)
				.order("created_at", { ascending: false })
				.limit(limit);

			if (error)
				return apiError(res, 500, "Failed to fetch replies", {
					details: error.message,
				});
			comments = (data ?? []).map(
				(r: {
					id: string;
					username: string;
					content: string;
					created_at: string;
				}) => ({
					id: r.id,
					username: r.username,
					text: r.content,
					created_at: r.created_at,
				}),
			);
		} else {
			const { data, error } = await db()
				.from("ig_comments")
				.select("id, comment_id, username, text, created_at")
				.eq("post_id", postId)
				.order("created_at", { ascending: false })
				.limit(limit);

			if (error)
				return apiError(res, 500, "Failed to fetch comments", {
					details: error.message,
				});
			comments = (data ?? []).map(
				(c: {
					id: string;
					username: string;
					text: string;
					created_at: string;
				}) => ({
					id: c.id,
					username: c.username,
					text: c.text,
					created_at: c.created_at,
				}),
			);
		}

		if (comments.length === 0) {
			return apiSuccess(res, {
				postId,
				platform,
				totalComments: 0,
				breakdown: { positive: 0, negative: 0, neutral: 0, question: 0 },
				sentimentScore: 0,
				verdict: "No comments to analyze",
				comments: [],
			});
		}

		// Regex per-comment breakdown (always runs — drives existing fields + fallback)
		const breakdown = { positive: 0, negative: 0, neutral: 0, question: 0 };
		const analyzed = comments.map((c) => {
			const sentiment = analyzeSentiment(c.text) as
				| "positive"
				| "negative"
				| "neutral"
				| "question";
			breakdown[sentiment] = (breakdown[sentiment] || 0) + 1;
			return { ...c, sentiment };
		});

		const total = comments.length;
		const sentimentScore =
			total > 0
				? Math.round(((breakdown.positive - breakdown.negative) / total) * 100)
				: 0;

		let verdict = "Neutral";
		if (sentimentScore > 30) verdict = "Strongly positive";
		else if (sentimentScore > 10) verdict = "Mostly positive";
		else if (sentimentScore < -30) verdict = "Strongly negative";
		else if (sentimentScore < -10) verdict = "Mostly negative";
		else if (breakdown.question > total * 0.4) verdict = "High question volume";

		// --- LLM enrichment ---
		// Skip for tiny batches — regex is accurate enough and the call isn't worth the cost.
		if (total < 5) {
			return apiSuccess(res, {
				postId,
				platform,
				totalComments: total,
				breakdown,
				sentimentScore,
				verdict,
				comments: analyzed,
				llmSkipped: true,
			});
		}

		// Check Redis cache (v2 namespace — no collision with sentiment:post:{id} hashes)
		const cacheKey = `sentiment:v2:${postId}:${limit}`;
		let cachedLlm: LlmResult | null = null;
		try {
			const redis = getRedis();
			const raw = await redis.get(cacheKey);
			if (raw) {
				cachedLlm = JSON.parse(raw as string) as LlmResult;
			}
		} catch (err) {
			logger.debug("[sentiment-scan] Redis read failed, proceeding without cache", {
				error: String(err),
			});
		}

		if (cachedLlm) {
			return apiSuccess(res, {
				postId,
				platform,
				totalComments: total,
				breakdown,
				sentimentScore,
				verdict,
				comments: analyzed,
				llm: cachedLlm,
			});
		}

		// Attempt AI call — fall back to regex-only on any failure
		const aiConfig = await getUserAIConfig(userId);
		if (!aiConfig) {
			return apiSuccess(res, {
				postId,
				platform,
				totalComments: total,
				breakdown,
				sentimentScore,
				verdict,
				comments: analyzed,
				degraded: true,
			});
		}

		try {
			const postSnippet = ((post.content as string) || "").substring(0, 300);
			const commentLines = comments
				.map((c, i) => `${i + 1}. ${c.text.substring(0, 200)}`)
				.join("\n");

			const prompt = `You are a social media sentiment analyst. Analyze the following comments on a ${platform} post and return a JSON object.

Post text (first 300 chars): "${postSnippet}"

Comments (${total} total):
${commentLines}

Return valid JSON only, no markdown fencing:
{
  "overall_verdict": "hype" | "drama" | "positive" | "neutral" | "negative" | "mixed",
  "hype_score": <0-100, scroll-stopping enthusiasm>,
  "drama_score": <0-100, conflict/call-out/controversy>,
  "positivity": <0-100>,
  "negativity": <0-100>,
  "summary": "<1-2 sentence human verdict>",
  "top_themes": ["<3-5 short labels such as callouts, compliments, questions>"],
  "concerning_count": <count of comments needing human review: threats, slurs, etc.>
}`;

			const model = aiConfig.model || GEMINI_MODEL;
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
						overall_verdict: { type: "STRING" },
						hype_score: { type: "INTEGER" },
						drama_score: { type: "INTEGER" },
						positivity: { type: "INTEGER" },
						negativity: { type: "INTEGER" },
						summary: { type: "STRING" },
						top_themes: { type: "ARRAY", items: { type: "STRING" } },
						concerning_count: { type: "INTEGER" },
					},
					required: [
						"overall_verdict",
						"hype_score",
						"drama_score",
						"positivity",
						"negativity",
						"summary",
						"top_themes",
						"concerning_count",
					],
				},
				actionLog: {
					userId,
					accountId:
						typeof (post as { account_id?: unknown }).account_id === "string"
							? ((post as { account_id: string }).account_id)
							: null,
					surface: "inbox",
					actionType: "sentiment_scan",
					inputText: prompt.slice(0, 8000),
					metadata: { postId, platform, provider: aiConfig.provider },
				},
			});

			const rawText = (response || "").trim();
			const jsonStr = rawText
				.replace(/^```json?\s*/i, "")
				.replace(/\s*```$/i, "");
			const parsed = JSON.parse(jsonStr);
			const validated = LlmResultSchema.parse(parsed);
			const llm = sanitizeLlmResult(validated);

			// Cache only successful LLM results
			try {
				const redis = getRedis();
				await redis.set(cacheKey, JSON.stringify(llm), { ex: CACHE_TTL_SECONDS });
			} catch (err) {
				logger.debug("[sentiment-scan] Redis write failed", { error: String(err) });
			}

			return apiSuccess(res, {
				postId,
				platform,
				totalComments: total,
				breakdown,
				sentimentScore,
				verdict,
				comments: analyzed,
				llm,
			});
		} catch (err) {
			logger.warn("[sentiment-scan] Gemini failed, falling back to regex", {
				userId,
				postId,
				error: err instanceof Error ? err.message : String(err),
			});

			return apiSuccess(res, {
				postId,
				platform,
				totalComments: total,
				breakdown,
				sentimentScore,
				verdict,
				comments: analyzed,
				degraded: true,
			});
		}
	},
);
