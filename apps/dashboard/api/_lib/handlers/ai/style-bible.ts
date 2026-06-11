// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
/**
 * POST /api/ai/style-bible — Extract writing style profile from sample captions
 * GET  /api/ai/style-bible — Retrieve existing style bible
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";
import type { UserAIConfig } from "../../aiConfig.js";
import { getUserAIConfig } from "../../aiConfig.js";
import { checkAIRateLimit } from "../../aiRateLimit.js";
import { apiError, apiSuccess } from "../../apiResponse.js";
import { logger } from "../../logger.js";
import { withAuth } from "../../middleware.js";
import { escapeForPrompt } from "../../promptUtils.js";
import { getSupabase } from "../../supabase.js";
import { requireMinTier } from "../../tierGate.js";
import { generateWithProvider } from "../auto-post/aiProviders.js";
import { verifyAccountOwnership } from "../helpers/verifyOwnership.js";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface ExtractedProfile {
	avgLength: number;
	toneWords: string[];
	emojiUsage: "heavy" | "moderate" | "minimal" | "none";
	hashtagStyle: "inline" | "block" | "none";
	ctaPatterns: string[];
	sentenceStyle: "short" | "mixed" | "long";
	personality: string;
}

// ---------------------------------------------------------------------------
// Rule-based extraction
// ---------------------------------------------------------------------------

function extractRuleBased(captions: string[]): Partial<ExtractedProfile> {
	const avgLength = Math.round(
		captions.reduce((sum, c) => sum + c.length, 0) / captions.length,
	);

	// Emoji count
	const emojiRegex = /[\p{Emoji_Presentation}\p{Extended_Pictographic}]/gu;
	const totalEmojis = captions.reduce(
		(sum, c) => sum + (c.match(emojiRegex)?.length ?? 0),
		0,
	);
	const avgEmojis = totalEmojis / captions.length;
	const emojiUsage: ExtractedProfile["emojiUsage"] =
		avgEmojis >= 5
			? "heavy"
			: avgEmojis >= 2
				? "moderate"
				: avgEmojis >= 0.5
					? "minimal"
					: "none";

	// Hashtag style
	const hashtagCaptions = captions.filter((c) => c.includes("#"));
	let hashtagStyle: ExtractedProfile["hashtagStyle"] = "none";
	if (hashtagCaptions.length > captions.length * 0.3) {
		// Check if hashtags are at end (block) vs inline
		const blockCount = hashtagCaptions.filter((c) => {
			const lines = c.trim().split("\n");
			const lastLine = lines[lines.length - 1];
			return (lastLine!.match(/#\w+/g)?.length ?? 0) >= 2;
		}).length;
		hashtagStyle =
			blockCount > hashtagCaptions.length * 0.5 ? "block" : "inline";
	}

	// Sentence style
	const avgSentenceLen =
		captions.reduce((sum, c) => {
			const sentences = c.split(/[.!?]+/).filter((s) => s.trim().length > 0);
			const avgWords =
				sentences.reduce((ws, s) => ws + s.trim().split(/\s+/).length, 0) /
				Math.max(sentences.length, 1);
			return sum + avgWords;
		}, 0) / captions.length;
	const sentenceStyle: ExtractedProfile["sentenceStyle"] =
		avgSentenceLen <= 8 ? "short" : avgSentenceLen <= 15 ? "mixed" : "long";

	return { avgLength, emojiUsage, hashtagStyle, sentenceStyle };
}

// ---------------------------------------------------------------------------
// AI extraction via Gemini
// ---------------------------------------------------------------------------

interface AIExtractResult {
	profile: Partial<ExtractedProfile>;
}

async function extractWithAI(
	captions: string[],
	aiConfig: UserAIConfig,
	userId: string,
	accountId: string | null,
): Promise<AIExtractResult> {
	const prompt = `Analyze these social media captions and extract the writer's style profile. Return ONLY valid JSON with these fields:
- toneWords: array of 3-5 adjectives describing the tone (e.g. ["witty", "vulnerable", "motivational"])
- ctaPatterns: array of call-to-action patterns used (e.g. ["link in bio", "drop a comment", "save this"])
- personality: one sentence describing the writer's personality/brand voice

Captions:
${captions.map((c, i) => `${i + 1}. ${escapeForPrompt(c)}`).join("\n\n")}

JSON only, no markdown:`;

	const text = await generateWithProvider(prompt, {
		provider: aiConfig.provider,
		apiKey: aiConfig.apiKey,
		baseUrl: aiConfig.baseUrl,
		model: aiConfig.model || "gemini-2.5-flash",
		keySource: aiConfig.source,
		ideaCount: 1,
		useStructuredOutput: true,
		structuredOutputSchema: {
			type: "OBJECT",
			properties: {
				toneWords: { type: "ARRAY", items: { type: "STRING" } },
				ctaPatterns: { type: "ARRAY", items: { type: "STRING" } },
				personality: { type: "STRING" },
			},
			required: ["toneWords", "ctaPatterns", "personality"],
		},
		actionLog: {
			userId,
			accountId,
			surface: "composer",
			actionType: "style_bible_extract",
			inputText: captions.join("\n\n").slice(0, 8000),
			metadata: { sampleCount: captions.length, provider: aiConfig.provider },
		},
	});

	// Strip possible markdown fences
	const cleaned = (text ?? "{}")
		.trim()
		.replace(/^```(?:json)?\n?/g, "")
		.replace(/\n?```$/g, "");

	try {
		const parsed = JSON.parse(cleaned);
		return {
			profile: {
				toneWords: Array.isArray(parsed.toneWords) ? parsed.toneWords : [],
				ctaPatterns: Array.isArray(parsed.ctaPatterns)
					? parsed.ctaPatterns
					: [],
				personality:
					typeof parsed.personality === "string" ? parsed.personality : "",
			},
		};
		} catch (_err) {
			logger.error("[style-bible] Failed to parse AI response", {
				responseChars: text?.length ?? 0,
			});
		return {
			profile: { toneWords: [], ctaPatterns: [], personality: "" },
		};
	}
}

// ---------------------------------------------------------------------------
// Handler
// ---------------------------------------------------------------------------

export default withAuth(
	async (req: VercelRequest, res: VercelResponse, user) => {
		const supabase = getSupabase();
		const accountId = (req.query.accountId as string) || null;

		// ---- GET: retrieve existing style bible ----
		if (req.method === "GET") {
			let query = supabase
				.from("style_bibles")
				.select("*")
				.eq("user_id", user.id);

			if (accountId) {
				query = query.eq("account_id", accountId);
			} else {
				query = query.is("account_id", null);
			}

			const { data, error } = await query.maybeSingle();
			if (error) {
				logger.error("[style-bible] GET error", { error });
				return apiError(res, 500, "Failed to retrieve style bible");
			}
			return apiSuccess(res, { styleBible: data });
		}

		// ---- POST: create/update style bible ----
		if (req.method !== "POST") {
			return apiError(res, 405, "Method not allowed");
		}

		// Tier gate — Style Bible creation requires Pro or higher
		if (!(await requireMinTier(user.id, "pro", res))) return;

		// Tier-aware rate limit (Free 20/h, Pro 100/h, Empire 500/h)
		const rl = await checkAIRateLimit(user.id, "style-bible");
		res.setHeader("X-RateLimit-Limit", String(rl.limit));
		res.setHeader("X-RateLimit-Remaining", String(rl.remaining));
		if (!rl.allowed) {
			return apiError(res, 429, "Rate limit exceeded. Please wait a moment.", {
				code: "RATE_LIMITED",
			});
		}

		const { captions, accountId: bodyAccountId } = req.body || {};
		const effectiveAccountId = bodyAccountId || accountId || null;

		// Verify the caller owns the account they're attributing this style bible to
		if (effectiveAccountId) {
			const ownedAccount = await verifyAccountOwnership(
				res,
				effectiveAccountId,
				user.id,
			);
			if (!ownedAccount) return;
		}

		if (
			!Array.isArray(captions) ||
			captions.length < 3 ||
			captions.length > 20
		) {
			return apiError(res, 400, "Provide between 3 and 20 captions");
		}

		const cleanCaptions = captions
			.map((c: unknown) => (typeof c === "string" ? c.trim() : ""))
			.filter((c: string) => c.length > 0);

		if (cleanCaptions.length < 3) {
			return apiError(res, 400, "Need at least 3 non-empty captions");
		}

		// Get AI config (user's own key or platform fallback)
		const aiConfig = await getUserAIConfig(user.id);
		if (!aiConfig) {
			return apiError(
				res,
				503,
				"AI features temporarily unavailable. Add your own API key in Settings for immediate access.",
				{ code: "NO_API_KEY" },
			);
		}
		try {
			// Run both extractions
			const [ruleBased, aiExtracted] = await Promise.all([
				extractRuleBased(cleanCaptions),
				extractWithAI(cleanCaptions, aiConfig, user.id, effectiveAccountId),
			]);

			// Merge: rule-based for quantitative, AI for qualitative
			const profile: ExtractedProfile = {
				avgLength: ruleBased.avgLength ?? 0,
				toneWords: aiExtracted.profile.toneWords ?? [],
				emojiUsage: ruleBased.emojiUsage ?? "none",
				hashtagStyle: ruleBased.hashtagStyle ?? "none",
				ctaPatterns: aiExtracted.profile.ctaPatterns ?? [],
				sentenceStyle: ruleBased.sentenceStyle ?? "mixed",
				personality: aiExtracted.profile.personality ?? "",
			};

			// Upsert
			const { data, error } = await supabase
				.from("style_bibles")
				.upsert(
					{
						user_id: user.id,
						account_id: effectiveAccountId,
						// biome-ignore lint/suspicious/noExplicitAny: Supabase upsert requires cast for JSON columns
						sample_captions: cleanCaptions as any,
						// biome-ignore lint/suspicious/noExplicitAny: Supabase upsert requires cast for JSON columns
						extracted_profile: profile as any,
						updated_at: new Date().toISOString(),
					},
					{
						onConflict: "user_id,account_id",
						ignoreDuplicates: false,
					},
				)
				.select()
				.maybeSingle();

			if (error) {
				logger.error("[style-bible] Upsert error", { error });
				return apiError(res, 500, "Failed to save style bible");
			}

			return apiSuccess(res, { styleBible: data, profile }, 201);
		} catch (err) {
			logger.error("[style-bible] Extraction failed", { error: String(err) });
			return apiError(res, 500, "Style extraction failed");
		}
	},
);
