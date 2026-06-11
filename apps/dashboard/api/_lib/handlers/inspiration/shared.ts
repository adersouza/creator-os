// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
/**
 * Shared types, constants, and helpers for inspiration handlers.
 */

import { recordDirectAIEvalSnapshot } from "../../aiEvalSnapshots.js";
import { trackGeminiResponseCost } from "../../aiUsageTracking.js";
import { decrypt } from "../../encryption.js";
import { logger } from "../../logger.js";
import { escapeForPrompt } from "../../promptUtils.js";
import { withRetry } from "../../retryUtils.js";
import { getSupabase, getSupabaseAny } from "../../supabase.js";
import { z } from "../../zodCompat.js";

// ============================================================================
// Zod Schemas
// ============================================================================

export const IdSchema = z.object({
	id: z.string().min(1, "Missing id"),
});

export const SaveSchema = z.object({
	id: z.string().min(1, "Missing id"),
	unsave: z.boolean().optional(),
});

export const BulkQueueSchema = z.object({
	count: z.number().int().min(1).max(100).optional().default(20),
});

// ============================================================================
// Supabase Client
// ============================================================================

export const db = () => getSupabase();
export { getSupabaseAny };

// ============================================================================
// Tier Limits
// ============================================================================

export const TIER_LIMITS = {
	free: { dailyIdeas: 10, manualRefreshCooldown: 24 * 60 },
	pro: { dailyIdeas: 50, manualRefreshCooldown: 60 },
	agency: { dailyIdeas: Infinity, manualRefreshCooldown: 30 },
	empire: { dailyIdeas: Infinity, manualRefreshCooldown: 0 },
};

// ============================================================================
// Type Aliases
// ============================================================================

// Re-export from canonical module (was a buggy local copy with no decryption)
import type { UserAIConfig } from "../../aiConfig.js";

export type { UserAIConfig };

export interface IGMediaPost {
	id: string;
	caption?: string | undefined;
	like_count?: number | undefined;
	comments_count?: number | undefined;
}

export interface CompetitorTopPostRow {
	threads_post_id: string;
	content?: string | undefined;
	like_count?: number | undefined;
	reply_count?: number | undefined;
	repost_count?: number | undefined;
}

export interface InspirationIdeaRow {
	id: string;
	user_id: string;
	workspace_id?: string | undefined;
	original_post?: Record<string, unknown> | undefined;
	competitor_id?: string | undefined;
	competitor_username?: string | undefined;
	competitor_avatar_url?: string | undefined;
	adapted_content?: string | undefined;
	[key: string]: unknown;
}

export interface InspirationIdeaContentRow {
	id: string;
	adapted_content?: string | undefined;
}

export interface InspirationIdeaStatusRow {
	status: string;
}

export interface InspirationIdeaCompetitorRow {
	competitor_username: string;
	competitor_avatar_url?: string | undefined;
}

export interface WorkspaceRow {
	id: string;
}

export interface InspirationConfigRow {
	enabled?: boolean | undefined;
	ideas_per_competitor?: number | undefined;
	adaptation_style?: string | undefined;
	topic_filters?: string[] | undefined;
	notify_new_ideas?: boolean | undefined;
	daily_digest_enabled?: boolean | undefined;
	last_scan_at?: string | undefined;
}

export interface AccountTokenRow {
	id: string;
	threads_access_token_encrypted: string;
}

export interface CompetitorRow {
	id: string;
	username: string;
	avatar_url?: string | undefined;
	threads_user_id?: string | undefined;
}

export interface IgAccountRow {
	id: string;
	instagram_user_id?: string | null | undefined;
	instagram_access_token_encrypted?: string | null | undefined;
	login_type?: string | null | undefined;
}

export interface GeneratedIdea {
	content: string;
	insight: string;
	tags: string[];
	viralScore: number;
}

// ============================================================================
// AI Generation Helpers
// ============================================================================

// Canonical implementation — re-export for backward compat
export { getUserAIConfig } from "../../aiConfig.js";

export async function callGeminiAPI(
	prompt: string,
	apiKey: string,
	model?: string,
	userId: string = "platform",
	keySource?: "user" | "env_fallback" | undefined,
): Promise<string | null> {
	const modelId = model || "gemini-2.0-flash";
	try {
		const response = await withRetry(
			() =>
				fetch(
					`https://generativelanguage.googleapis.com/v1beta/models/${modelId}:generateContent?key=${apiKey}`,
					{
						method: "POST",
						headers: { "Content-Type": "application/json" },
						body: JSON.stringify({
							contents: [{ parts: [{ text: prompt }] }],
							generationConfig: { temperature: 0.8, maxOutputTokens: 1024 },
						}),
						signal: AbortSignal.timeout(15000),
					},
				),
			{ label: `inspirationGemini:${modelId}` },
		);
		if (!response.ok) return null;
		const data = await response.json();
		trackGeminiResponseCost(
			userId,
			data,
			modelId,
			"inspiration_idea",
			keySource,
		);
		const output = data.candidates?.[0]?.content?.parts?.[0]?.text || null;
		recordDirectAIEvalSnapshot({
			userId,
			surface: "inspiration_idea",
			actionType: "generate_inspiration_idea",
			category: "content_generation",
			prompt,
			output: output ?? undefined,
			provider: "gemini",
			model: modelId,
			parameters: {
				temperature: 0.8,
				maxOutputTokens: 1024,
				keySource: keySource ?? null,
			},
			passed: output !== null,
			failures: output ? [] : ["provider_returned_null"],
			metadata: {
				route: "api/_lib/handlers/inspiration/shared.callGeminiAPI",
			},
		}).catch((error) => {
			logger.warn("Inspiration eval snapshot failed", { error: String(error) });
		});
		return output;
	} catch (err) {
		logger.debug("Gemini API call failed", { error: String(err) });
		return null;
	}
}

export async function generateInspirationIdea(
	originalContent: string,
	_competitorUsername: string,
	style: string,
	aiConfig: UserAIConfig,
	userId?: string | undefined,
): Promise<GeneratedIdea | null> {
	const styleDescriptions: Record<string, string> = {
		casual: "casual, conversational, and relatable",
		professional: "professional, authoritative, and polished",
		witty: "witty, clever, and playful with humor",
		inspirational: "inspirational, motivational, and uplifting",
		edgy: "bold, provocative, and slightly controversial",
	};

	// Calculate target length based on original (keep similar length)
	const originalLength = originalContent.length;
	const maxLength = Math.max(80, Math.min(originalLength * 2, 150));

	const prompt = `Rewrite this viral post keeping the SAME THEME and VIBE but making it your own.

ORIGINAL: "${escapeForPrompt(originalContent)}"

CRITICAL RULES:
1. KEEP THE SAME TOPIC CATEGORY:
   - Travel post → Travel post (different destination/moment)
   - Relationship/dating post → Relationship/dating post
   - Achievement post → Achievement post
   - Beach/vacation → Beach/vacation vibes
   - Asking for connection → Asking for connection

2. Keep similar length (~${maxLength} chars max)
3. Keep the same emotional tone (flirty stays flirty, excited stays excited)
4. Use ${styleDescriptions[style] || styleDescriptions.casual} voice
5. 1-2 emojis max

GOOD EXAMPLES:
- "cuddle buddy? please 🥺" → "binge-watching partner? please 🥺" (SAME lonely/wanting vibe)
- "the video that made my first million" → "the moment that changed my life" (SAME milestone energy)
- "you catch me at the beach! wyd?" → "caught me at the gym! what's good?" (SAME casual encounter vibe)
- "bahamas with my best friends" → "road trip with the crew" (SAME friend adventure vibe)

BAD EXAMPLES (don't do these):
- "beach vibes" → "making ramen" (random topic change - NO)
- "cuddle buddy?" → "takeout order?" (lost the emotional vibe - NO)

Return ONLY JSON: {"content": "your version", "insight": "why it works", "tags": ["tag1", "tag2"], "viralScore": 75}`;

	const response = await callGeminiAPI(
		prompt,
		aiConfig.apiKey,
		aiConfig.model,
		userId,
		aiConfig.source,
	);
	if (!response) return null;

	try {
		let jsonStr = response;
		if (response.includes("```json")) {
			jsonStr = response.split("```json")[1]!.split("```")[0]!.trim();
		} else if (response.includes("```")) {
			jsonStr = response.split("```")[1]!.split("```")[0]!.trim();
		}
		const result = JSON.parse(jsonStr);
		// Cap content to maxLength to keep it short like original
		return {
			content: (result.content || "").substring(0, maxLength + 50),
			insight: result.insight || "Strong hook with clear value",
			tags: Array.isArray(result.tags)
				? result.tags.slice(0, 3).map((t: string) => t.toLowerCase())
				: [],
			viralScore: Math.min(
				100,
				Math.max(0, parseInt(result.viralScore, 10) || 70),
			),
		};
	} catch (err) {
		logger.debug("Failed to parse AI-generated inspiration idea", {
			error: String(err),
		});
		return null;
	}
}

// Fetch top-performing IG posts from a competitor via Business Discovery
export async function fetchIGCompetitorPosts(
	encryptedToken: string,
	igUserId: string,
	targetUsername: string,
	limit: number = 10,
	loginType?: string,
): Promise<
	Array<{
		id: string;
		content: string;
		likeCount: number;
		replyCount: number;
		repostCount: number;
	}>
> {
	try {
		const { getBusinessDiscovery } = await import("../../instagramApi.js");
		const resultRaw = await getBusinessDiscovery(
			encryptedToken,
			igUserId,
			targetUsername,
			limit,
			loginType,
		);
		const result = resultRaw as unknown as {
			success: boolean;
			profile?: { media?: { data?: IGMediaPost[] | undefined } | undefined } | undefined;
		};
		if (!result.success || !result.profile?.media?.data) return [];

		return (result.profile.media.data || []).map((post: IGMediaPost) => ({
			id: post.id,
			content: post.caption || "",
			likeCount: post.like_count || 0,
			replyCount: post.comments_count || 0,
			repostCount: 0, // IG doesn't expose shares via business discovery
		}));
	} catch (e) {
		logger.warn("[inspiration:ig] Business discovery failed", {
			targetUsername,
			error: String(e),
		});
		return [];
	}
}

// Fetch competitor posts from database (synced via competitors API)
export async function fetchCompetitorPostsFromDB(
	competitorId: string,
	limit = 10,
): Promise<
	Array<{
		id: string;
		content: string;
		likeCount: number;
		replyCount: number;
		repostCount: number;
	}>
> {
	try {
		// Get posts from competitor_top_posts table (already synced by competitors API)
		const { data, error } = await db()
			.from("competitor_top_posts")
			.select(
				"threads_post_id, content, like_count, reply_count, repost_count, engagement_score",
			)
			.eq("competitor_id", competitorId)
			.order("engagement_score", { ascending: false })
			.limit(limit);

		if (error) {
			logger.error("Error fetching competitor posts from DB", {
				error: String(error),
			});
			return [];
		}

		logger.info("Found posts for competitor", {
			count: data?.length || 0,
			competitorId,
		});

		return ((data || []) as unknown as CompetitorTopPostRow[]).map((post) => ({
			id: post.threads_post_id,
			content: post.content || "",
			likeCount: post.like_count || 0,
			replyCount: post.reply_count || 0,
			repostCount: post.repost_count || 0,
		}));
	} catch (err) {
		logger.debug("Failed to fetch competitor posts from DB", {
			competitorId,
			error: String(err),
		});
		return [];
	}
}

// Re-export decrypt so refresh handler can use it
export { decrypt };
