// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
/**
 * Auto-Learning Cron Sub-Handler
 *
 * Closes the feedback loop between post performance and AI content generation.
 * For each active account group:
 *   1. Pulls posts from the last 7 days
 *   2. Segments into top 10% and bottom 10% by engagement rate
 *   3. Calls AI to extract winning/losing patterns
 *   4. Appends learned patterns to content_strategy.tone_notes
 *   5. Computes and stores data_driven_insights on content_strategy
 *   6. Logs ai_feedback ratings on top/bottom posts
 *   7. Saves summary to agent_notes for audit trail
 *
 * Called by: auto-learning cron (daily at 6 AM UTC — upgraded from weekly)
 */

import { logger, serializeError } from "../logger.js";
import { escapeForPrompt, sanitizeAIOutput } from "../promptUtils.js";
import { getSupabaseAny } from "../supabase.js";

// ============================================================================
// Types
// ============================================================================

import { getUserAIConfig, type UserAIConfig } from "../aiConfig.js";

interface PostPerformance {
	id: string;
	content: string;
	groupId: string;
	engagementRate: number;
	viewsCount: number;
	likesCount: number;
	repliesCount: number;
	repostsCount: number;
	contentType: string | null;
	publishedAt: string;
	hoursSincePublish: number;
	viewVelocity: number; // views per hour
	engagementVelocity: number; // (likes+replies) per hour
}

interface AIAnalysis {
	winning_patterns: string[];
	losing_patterns: string[];
	recommended_additions_to_tone_notes: string;
	recommended_removals: string;
	confidence: number;
}

type JsonObject = Record<string, unknown>;

interface GroupResult {
	groupId: string;
	groupName: string;
	totalPosts: number;
	medianER: number;
	topPostContent: string | null;
	topPostER: number | null;
	patternsFound: number;
	confidenceScore: number;
	toneNotesUpdated: boolean;
	feedbackRatings: number;
	error?: string | undefined;
}

// ============================================================================
// Constants
// ============================================================================

const MIN_POSTS_THRESHOLD = 10;
const CONFIDENCE_THRESHOLD = 0.3;
const MAX_TONE_NOTES_LENGTH = 2000;
const MAX_FEEDBACK_RATINGS = 50;
const MAX_GROUPS = 20;

function extractLikelyJsonObject(raw: string): string {
	const sanitized = sanitizeAIOutput(
		raw
			.replace(/```json\s*/gi, "")
			.replace(/```\s*/g, "")
			.trim(),
	);
	const start = sanitized.indexOf("{");
	if (start === -1) return sanitized;

	let depth = 0;
	let inString = false;
	let escaped = false;
	for (let i = start; i < sanitized.length; i++) {
		const char = sanitized[i];
		if (inString) {
			if (escaped) {
				escaped = false;
				continue;
			}
			if (char === "\\") {
				escaped = true;
				continue;
			}
			if (char === '"') {
				inString = false;
			}
			continue;
		}

		if (char === '"') {
			inString = true;
			continue;
		}
		if (char === "{") {
			depth++;
			continue;
		}
		if (char === "}") {
			depth--;
			if (depth === 0) {
				return sanitized.slice(start, i + 1);
			}
		}
	}

	return sanitized.slice(start);
}

function normalizeAIAnalysisJson(raw: string): string {
	return extractLikelyJsonObject(raw)
		.replace(/\r/g, "")
		.replace(/[\u201C\u201D]/g, '"')
		.replace(/[\u2018\u2019]/g, "'");
}

function toStringArray(value: unknown): string[] {
	if (Array.isArray(value)) {
		return value
			.map((entry) =>
				typeof entry === "string" ? sanitizeAIOutput(entry).trim() : "",
			)
			.filter(Boolean);
	}

	if (typeof value === "string") {
		return value
			.split(/\n+|(?:^|\s)[-*•]\s+/)
			.map((entry) => sanitizeAIOutput(entry).trim())
			.filter((entry) => entry.length > 0);
	}

	return [];
}

function firstNonEmptyString(...values: unknown[]): string {
	for (const value of values) {
		if (typeof value === "string") {
			const cleaned = sanitizeAIOutput(value).trim();
			if (cleaned) return cleaned;
		}
	}
	return "";
}

function deriveConfidence(
	candidate: JsonObject,
	winningPatterns: string[],
	losingPatterns: string[],
): number {
	const confidenceRaw = candidate.confidence;
	const parsed =
		typeof confidenceRaw === "number"
			? confidenceRaw
			: typeof confidenceRaw === "string"
				? Number.parseFloat(confidenceRaw)
				: Number.NaN;

	if (Number.isFinite(parsed)) {
		return Math.min(1, Math.max(0, parsed));
	}

	// Fallback: if the model produced both pattern sets, accept it at a
	// conservative confidence so the cron can still use the analysis.
	if (winningPatterns.length >= 2 && losingPatterns.length >= 2) {
		return 0.45;
	}

	if (winningPatterns.length > 0 || losingPatterns.length > 0) {
		return 0.3;
	}

	return 0;
}

function coerceAIAnalysis(value: unknown): AIAnalysis | null {
	if (!value || typeof value !== "object") return null;
	const candidate = value as JsonObject;
	const winningPatterns = toStringArray(
		candidate.winning_patterns ?? candidate.winningPatterns,
	);
	const losingPatterns = toStringArray(
		candidate.losing_patterns ?? candidate.losingPatterns,
	);
	const recommendedAdditions = firstNonEmptyString(
		candidate.recommended_additions_to_tone_notes,
		candidate.recommendedAdditionsToToneNotes,
		candidate.recommended_tone_note_additions,
		candidate.recommendedToneNoteAdditions,
		candidate.recommended_additions,
	);
	const recommendedRemovals = firstNonEmptyString(
		candidate.recommended_removals,
		candidate.recommendedRemovals,
		candidate.removals,
		"none",
	);
	const confidence = deriveConfidence(
		candidate,
		winningPatterns,
		losingPatterns,
	);

	if (
		winningPatterns.length === 0 &&
		losingPatterns.length === 0 &&
		!recommendedAdditions
	) {
		return null;
	}

	return {
		winning_patterns: winningPatterns,
		losing_patterns: losingPatterns,
		recommended_additions_to_tone_notes: recommendedAdditions,
		recommended_removals: recommendedRemovals,
		confidence,
	};
}

function tryParseAIAnalysis(raw: string): AIAnalysis | null {
	const normalized = normalizeAIAnalysisJson(raw);
	try {
		const direct = coerceAIAnalysis(JSON.parse(normalized));
		if (direct) return direct;
	} catch {
		// Fall through to best-effort object extraction below.
	}

	const jsonMatch = normalized.match(/\{[\s\S]*\}/);
	if (jsonMatch) {
		try {
			return coerceAIAnalysis(JSON.parse(jsonMatch[0]));
		} catch {
			return null;
		}
	}

	return null;
}

// ============================================================================
// Main handler
// ============================================================================

export async function processAutoLearning(): Promise<{
	groupsProcessed: number;
	toneNotesUpdated: number;
	feedbackRatings: number;
	groupResults: GroupResult[];
}> {
	const supabase = getSupabaseAny();

	// Fetch all account groups with populated accounts.
	// Note: account_groups does NOT have a workspace_id column — workspace_id
	// is resolved per-group from auto_post_group_config inside processGroup().
	const { data: groups, error: groupsErr } = await supabase
		.from("account_groups")
		.select("id, name, user_id, account_ids, voice_profile, content_strategy")
		.not("account_ids", "is", null)
		.order("name", { ascending: true })
		.limit(MAX_GROUPS);

	if (groupsErr || !groups || groups.length === 0) {
		logger.info("[auto-learning] No account groups found", {
			error: groupsErr?.message,
		});
		return {
			groupsProcessed: 0,
			toneNotesUpdated: 0,
			feedbackRatings: 0,
			groupResults: [],
		};
	}

	// Deduplicate users for AI config fetch
	const userIds = [
		...new Set(groups.map((g: { user_id: string }) => g.user_id)),
	];
	const aiConfigMap = new Map<string, UserAIConfig>();

	for (const userId of userIds) {
		const config = await getUserAIConfig(userId as string);
		if (config) aiConfigMap.set(userId as string, config);
	}

	const groupResults: GroupResult[] = [];
	let totalToneNotesUpdated = 0;
	let totalFeedbackRatings = 0;

	for (const group of groups) {
		const gTyped = {
			...group,
			content_strategy: group.content_strategy as {
				tone_notes?: string | undefined;
			} | null,
			voice_profile: group.voice_profile as string | null,
		};

		try {
			const result = await processGroup(
				gTyped,
				aiConfigMap.get(gTyped.user_id) ?? null,
			);
			groupResults.push(result);
			if (result.toneNotesUpdated) totalToneNotesUpdated++;
			totalFeedbackRatings += result.feedbackRatings;
		} catch (err) {
			const message = err instanceof Error ? err.message : String(err);
			logger.error("[auto-learning] Group processing failed", {
				groupId: gTyped.id,
				error: message,
			});
			groupResults.push({
				groupId: gTyped.id,
				groupName: gTyped.name,
				totalPosts: 0,
				medianER: 0,
				topPostContent: null,
				topPostER: null,
				patternsFound: 0,
				confidenceScore: 0,
				toneNotesUpdated: false,
				feedbackRatings: 0,
				error: message,
			});
		}
	}

	// Save summary to agent_notes (use first user_id — this is a system-level note)
	const firstUserId = (groups[0] as { user_id: string }).user_id;
	await saveAutoLearningSummary(
		firstUserId,
		groupResults,
		totalFeedbackRatings,
	);

	return {
		groupsProcessed: groupResults.filter((r) => !r.error).length,
		toneNotesUpdated: totalToneNotesUpdated,
		feedbackRatings: totalFeedbackRatings,
		groupResults,
	};
}

// ============================================================================
// Per-group processing
// ============================================================================

async function processGroup(
	group: {
		id: string;
		name: string;
		user_id: string;
		account_ids: string[] | null;
		voice_profile: string | null;
		content_strategy: { tone_notes?: string | undefined } | null;
	},
	aiConfig: UserAIConfig | null,
): Promise<GroupResult> {
	const supabase = getSupabaseAny();
	const accountIds = group.account_ids ?? [];

	if (accountIds.length === 0) {
		return makeSkippedResult(group, "No accounts in group");
	}

	// Fetch group config (timezone + workspace_id).
	// account_groups does NOT have workspace_id — resolve it from auto_post_group_config.
	const { data: groupConfigRow } = await supabase
		.from("auto_post_group_config")
		.select("timezone, workspace_id")
		.eq("group_id", group.id)
		.maybeSingle();
	const groupTimezone =
		(groupConfigRow as { timezone?: string | undefined } | null)?.timezone || "UTC";
	const workspaceId =
		(groupConfigRow as { workspace_id?: string | undefined } | null)?.workspace_id || "";

	// Step 1: Gather posts from last 7 days
	const weekAgo = new Date(Date.now() - 7 * 24 * 60 * 60 * 1000).toISOString();

	const { data: rawPosts, error: postsErr } = await supabase
		.from("posts")
		.select(
			"id, content, account_id, views_count, likes_count, replies_count, reposts_count, engagement_rate, media_type, published_at",
		)
		.in("account_id", accountIds)
		.eq("status", "published")
		.gte("published_at", weekAgo)
		.gt("views_count", 0)
		.order("engagement_rate", { ascending: false });

	if (postsErr) {
		return makeSkippedResult(group, `DB error: ${postsErr.message}`);
	}

	const posts: PostPerformance[] = (rawPosts ?? []).map(
		(p: {
			id: string;
			content: string | null;
			account_id: string | null;
			views_count: number | null;
			likes_count: number | null;
			replies_count: number | null;
			reposts_count: number | null;
			engagement_rate: number | null;
			media_type: string | null;
			published_at: string | null;
		}) => {
			const viewsCount = p.views_count || 0;
			const likesCount = p.likes_count || 0;
			const repliesCount = p.replies_count || 0;
			const hoursSincePublish = (() => {
				if (!p.published_at) return 168; // default to 7 days
				const hours =
					(Date.now() - new Date(p.published_at).getTime()) / 3600000;
				return Math.max(hours, 1); // minimum 1 hour to avoid division by zero
			})();

			return {
				id: p.id,
				content: p.content || "",
				groupId: group.id,
				engagementRate: p.engagement_rate || 0,
				viewsCount,
				likesCount,
				repliesCount,
				repostsCount: p.reposts_count || 0,
				contentType: p.media_type,
				publishedAt: p.published_at || "",
				hoursSincePublish,
				viewVelocity: viewsCount / hoursSincePublish,
				engagementVelocity: (likesCount + repliesCount) / hoursSincePublish,
			};
		},
	);

	// Step 2: Check minimum threshold
	if (posts.length < MIN_POSTS_THRESHOLD) {
		logger.info(
			`[auto-learning] Skipping ${group.name}: only ${posts.length} posts (need ${MIN_POSTS_THRESHOLD}+)`,
		);
		return makeSkippedResult(
			group,
			`Only ${posts.length} posts (need ${MIN_POSTS_THRESHOLD}+)`,
		);
	}

	// Step 3: Segment into tiers (already sorted desc by engagement_rate)
	const topCount = Math.max(1, Math.ceil(posts.length * 0.1));
	const topPerformers = posts.slice(0, topCount);
	const bottomPerformers = posts.slice(-topCount);
	const medianER = posts[Math.floor(posts.length / 2)]?.engagementRate ?? 0;

	// Step 3b: Fetch competitor benchmarks for comparative analysis
	let competitorBenchmark = "";
	try {
		const { data: competitors } = await supabase
			.from("competitors")
			.select("id")
			.eq("user_id", group.user_id);

		if (competitors && competitors.length > 0) {
			const compIds = competitors.map((c: { id: string }) => c.id);
			// Sort by recency — Threads API does not provide reliable competitor
			// post performance. This is a pattern corpus, not a top-post benchmark.
			// Filter empty content at DB level — IMAGE/VIDEO posts often have content=""
			const { data: compPosts } = await supabase
				.from("competitor_top_posts")
				.select(
					"content, engagement_score, metric_quality, competitor_username, scraped_at, hook_type, topic_label, format_type, emotional_frame, cta_style, content_length_bucket, media_style, posting_hour",
				)
				.in("competitor_id", compIds)
				.not("content", "is", null)
				.neq("content", "")
				.order("scraped_at", { ascending: false })
				.limit(20);

			if (compPosts && compPosts.length >= 3) {
				const compList = compPosts
					.map(
						(p: {
							content: string | null;
							engagement_score: number | null;
							metric_quality?: string | null;
							competitor_username: string | null;
							hook_type?: string | null;
							topic_label?: string | null;
							format_type?: string | null;
							emotional_frame?: string | null;
							cta_style?: string | null;
							content_length_bucket?: string | null;
							media_style?: string | null;
							posting_hour?: number | null;
						}) =>
							`- "${(p.content || "").slice(0, 150)}" (@${p.competitor_username || "unknown"}; hook=${p.hook_type || "unknown"}; topic=${p.topic_label || "uncategorized"}; format=${p.format_type || "unknown"}; media=${p.media_style || "unknown"}; hour=${typeof p.posting_hour === "number" ? p.posting_hour : "unknown"}; frame=${p.emotional_frame || "unknown"}; cta=${p.cta_style || "none"}; metric_quality=${p.metric_quality || "stats_unavailable"})`,
					)
					.join("\n");
				const avgCompLen = Math.round(
					compPosts.reduce(
						(s: number, p: { content: string | null }) =>
							s + (p.content || "").length,
						0,
					) / compPosts.length,
				);
				competitorBenchmark = `\n## Competitor Pattern Corpus (recent tracked competitor posts; use for language and structure, not performance ranking unless metric_quality=valid_engagement or scraper_estimated):\n${compList}\nAvg competitor post length: ${avgCompLen} chars\n`;
			}
		}
	} catch (compErr) {
		logger.debug(
			"[auto-learning] Competitor benchmark fetch failed (non-blocking)",
			{
				error: serializeError(compErr),
			},
		);
	}

	// Step 4: Call AI for pattern analysis
	if (!aiConfig) {
		logger.info(
			`[auto-learning] Skipping AI analysis for ${group.name}: no AI config`,
		);
		// Still log feedback ratings even without AI analysis
		const ratings = await logFeedbackRatings(
			group.user_id,
			topPerformers,
			bottomPerformers,
		);
		return {
			groupId: group.id,
			groupName: group.name,
			totalPosts: posts.length,
			medianER,
			topPostContent: topPerformers[0]?.content.slice(0, 80) ?? null,
			topPostER: topPerformers[0]?.engagementRate ?? null,
			patternsFound: 0,
			confidenceScore: 0,
			toneNotesUpdated: false,
			feedbackRatings: ratings,
		};
	}

	const analysis = await analyzePatterns(
		aiConfig,
		group.voice_profile,
		group.content_strategy?.tone_notes,
		topPerformers,
		bottomPerformers,
		medianER,
		competitorBenchmark,
	);

	// Step 5: Compute content type mix from auto_post_queue
	let contentTypeMixSection = "";
	try {
		const mix = await computeContentTypeMix(workspaceId, group.id);
		if (mix.length > 0) {
			const weekDate = new Date().toISOString().split("T")[0]!;
			contentTypeMixSection = formatContentTypeMixSection(mix, weekDate!);
		}
	} catch (err) {
		logger.warn("[auto-learning] Content type mix failed (non-blocking)", {
			groupId: group.id,
			error: serializeError(err),
		});
	}

	// Step 6: Update tone_notes if confidence is high enough
	let toneNotesUpdated = false;
	if (analysis && analysis.confidence >= CONFIDENCE_THRESHOLD) {
		toneNotesUpdated = await updateToneNotes(
			group,
			analysis,
			contentTypeMixSection,
		);
	} else if (analysis) {
		logger.info(
			`[auto-learning] Low confidence for ${group.name}: ${analysis.confidence} (need ${CONFIDENCE_THRESHOLD})`,
		);
	}

	// Step 7: Compute and store data-driven insights
	if (analysis && analysis.confidence >= CONFIDENCE_THRESHOLD) {
		await storeDataDrivenInsights(
			group.id,
			group.user_id,
			analysis,
			topPerformers,
			bottomPerformers,
			posts.length,
			posts,
			groupTimezone,
		);
	}

	// Step 8: Log feedback ratings
	const ratings = await logFeedbackRatings(
		group.user_id,
		topPerformers,
		bottomPerformers,
	);

	return {
		groupId: group.id,
		groupName: group.name,
		totalPosts: posts.length,
		medianER,
		topPostContent: topPerformers[0]?.content.slice(0, 80) ?? null,
		topPostER: topPerformers[0]?.engagementRate ?? null,
		patternsFound: analysis?.winning_patterns.length ?? 0,
		confidenceScore: analysis?.confidence ?? 0,
		toneNotesUpdated,
		feedbackRatings: ratings,
	};
}

function makeSkippedResult(
	group: { id: string; name: string },
	error: string,
): GroupResult {
	return {
		groupId: group.id,
		groupName: group.name,
		totalPosts: 0,
		medianER: 0,
		topPostContent: null,
		topPostER: null,
		patternsFound: 0,
		confidenceScore: 0,
		toneNotesUpdated: false,
		feedbackRatings: 0,
		error,
	};
}

// ============================================================================
// AI Pattern Analysis
// ============================================================================

async function analyzePatterns(
	aiConfig: UserAIConfig,
	voiceProfile: string | null,
	currentToneNotes: string | undefined,
	topPerformers: PostPerformance[],
	bottomPerformers: PostPerformance[],
	medianER: number,
	competitorBenchmark?: string,
): Promise<AIAnalysis | null> {
	const topList = topPerformers
		.map(
			(p) =>
				`- "${escapeForPrompt(p.content.slice(0, 200))}" (ER: ${p.engagementRate.toFixed(2)}%, views: ${p.viewsCount}, replies: ${p.repliesCount})`,
		)
		.join("\n");

	const bottomList = bottomPerformers
		.map(
			(p) =>
				`- "${escapeForPrompt(p.content.slice(0, 200))}" (ER: ${p.engagementRate.toFixed(2)}%, views: ${p.viewsCount}, replies: ${p.repliesCount})`,
		)
		.join("\n");

	const prompt = `You are analyzing social media post performance for a Threads account.

## Account Voice Profile
${escapeForPrompt(voiceProfile || "Not set")}

## Current Tone Notes
${escapeForPrompt(currentToneNotes || "None")}

## Top Performing Posts (highest engagement rate):
${topList}

## Bottom Performing Posts (lowest engagement rate):
${bottomList}

## Median Engagement Rate: ${medianER.toFixed(2)}%
${competitorBenchmark || ""}
Analyze the patterns${competitorBenchmark ? " and compare against competitor benchmarks" : ""} and respond with ONLY a JSON object:
{
  "winning_patterns": [
    "pattern 1 - be specific about what makes these work (length, structure, topic, tone, punctuation)",
    "pattern 2",
    "pattern 3"
  ],
  "losing_patterns": [
    "pattern 1 - be specific about what makes these flop",
    "pattern 2",
    "pattern 3"
  ],
  "recommended_additions_to_tone_notes": "2-3 sentences to APPEND to the existing tone notes. Only add rules that are clearly supported by the data. Reference specific examples. Format as direct instructions.",
  "recommended_removals": "Any current tone note rules that the data contradicts (or 'none')",
  "confidence": 0.7
}

Return ONLY valid JSON. No markdown fences, no explanation.`;

	try {
		const { generateWithProvider } = await import(
			"../handlers/auto-post/contentSelection.js"
		);

		const raw = await generateWithProvider(prompt, {
			provider: aiConfig.provider,
			apiKey: aiConfig.apiKey,
			baseUrl: aiConfig.baseUrl,
			model: aiConfig.model,
			ideaCount: 1,
			useStructuredOutput: true,
			structuredOutputSchema: {
				type: "OBJECT",
				properties: {
					winning_patterns: {
						type: "ARRAY",
						items: { type: "STRING" },
					},
					losing_patterns: {
						type: "ARRAY",
						items: { type: "STRING" },
					},
					recommended_additions_to_tone_notes: { type: "STRING" },
					recommended_removals: { type: "STRING" },
					confidence: { type: "NUMBER" },
				},
				required: [
					"winning_patterns",
					"losing_patterns",
					"recommended_additions_to_tone_notes",
					"recommended_removals",
					"confidence",
				],
			},
		});

		if (!raw) {
			logger.warn("[auto-learning] AI returned empty response");
			return null;
		}

		const parsed = tryParseAIAnalysis(raw);

		// Validate required fields
		if (
			!parsed ||
			!Array.isArray(parsed.winning_patterns) ||
			!Array.isArray(parsed.losing_patterns) ||
			typeof parsed.confidence !== "number"
		) {
			logger.warn("[auto-learning] AI response missing required fields", {
				rawPreview: raw.slice(0, 300),
			});
			return null;
		}

		return parsed;
	} catch (err) {
		logger.error("[auto-learning] AI analysis failed", {
			error: serializeError(err),
		});
		return null;
	}
}

// ============================================================================
// Update Content Strategy tone_notes
// ============================================================================

async function updateToneNotes(
	group: {
		id: string;
		user_id: string;
		content_strategy: { tone_notes?: string | undefined } | null;
	},
	analysis: AIAnalysis,
	contentTypeMixSection?: string,
): Promise<boolean> {
	const supabase = getSupabaseAny();
	let currentToneNotes = group.content_strategy?.tone_notes || "";

	// Remove previous DATA-DRIVEN MIX section (replace, don't stack)
	currentToneNotes = currentToneNotes
		.replace(/\n--- DATA-DRIVEN MIX[\s\S]*?(?=\n---|$)/g, "")
		.trim();

	// Build new insights from this week's analysis
	const newInsights = [
		analysis.winning_patterns.length > 0
			? `WINNING: ${analysis.winning_patterns.join(". ")}`
			: "",
		analysis.losing_patterns.length > 0
			? `AVOID: ${analysis.losing_patterns.join(". ")}`
			: "",
		analysis.recommended_additions_to_tone_notes || "",
	]
		.filter(Boolean)
		.join("\n");

	// Synthesize auto-learned section via LLM — merges old + new insights coherently
	// instead of append+truncate which loses valid older patterns
	const autoMarker = "--- AUTO-LEARNED ---";
	const autoIdx = currentToneNotes.indexOf("--- AUTO-LEARNED");
	const coreStrategy =
		autoIdx >= 0
			? currentToneNotes.substring(0, autoIdx).trim()
			: currentToneNotes.trim();
	const existingLearned =
		autoIdx >= 0
			? currentToneNotes
					.substring(autoIdx)
					.replace(/--- AUTO-LEARNED[^-]*---/, "")
					.trim()
			: "";

	let synthesizedLearned = "";
	try {
		const { generateWithProvider } = await import(
			"../handlers/auto-post/contentSelection.js"
		);
		const aiConfig = await getUserAIConfig(group.user_id);
		if (aiConfig?.apiKey && (existingLearned || newInsights)) {
			const maxLearnedChars = MAX_TONE_NOTES_LENGTH - coreStrategy.length - 100;
			const raw = await generateWithProvider(
				`EXISTING LEARNED PATTERNS:\n${existingLearned || "(none yet)"}\n\nNEW INSIGHTS THIS WEEK:\n${newInsights}`,
				{
					provider: aiConfig.provider,
					apiKey: aiConfig.apiKey,
					model: aiConfig.model,
					baseUrl: aiConfig.baseUrl,
					ideaCount: 1,
					systemInstruction: `You are a content strategy editor. Synthesize performance insights into concise, actionable bullet points.
- Merge new insights with existing ones
- Remove contradictions (new data wins)
- Remove redundancies
- Keep only ACTIONABLE patterns with specific examples
- Output under ${maxLearnedChars} characters
- Format as bullet points
- Start each bullet with - (dash)`,
				},
			);
			if (raw) synthesizedLearned = raw.trim();
		}
	} catch (err) {
		logger.warn("[auto-learning] LLM synthesis failed, using append fallback", {
			error: err instanceof Error ? err.message : String(err),
		});
	}

	// Fallback if synthesis failed: use simple append+cap
	if (!synthesizedLearned) {
		synthesizedLearned = [existingLearned, newInsights]
			.filter(Boolean)
			.join("\n")
			.substring(0, MAX_TONE_NOTES_LENGTH - coreStrategy.length - 100);
	}

	let updatedToneNotes = `${coreStrategy}\n\n${autoMarker}\n${synthesizedLearned}`;

	// Append content type mix section
	if (contentTypeMixSection) {
		updatedToneNotes += contentTypeMixSection;
	}

	// Hard safety cap
	if (updatedToneNotes.length > MAX_TONE_NOTES_LENGTH) {
		updatedToneNotes = updatedToneNotes.substring(0, MAX_TONE_NOTES_LENGTH);
	}

	// Merge into existing content_strategy JSONB
	const updatedStrategy = {
		...(group.content_strategy || {}),
		tone_notes: updatedToneNotes.trim(),
	};

	const { error } = await supabase
		.from("account_groups")
		.update({
			// biome-ignore lint/suspicious/noExplicitAny: Supabase Json type mismatch
			content_strategy: updatedStrategy as any,
			updated_at: new Date().toISOString(),
		})
		.eq("id", group.id)
		.eq("user_id", group.user_id);

	if (error) {
		logger.error("[auto-learning] Failed to update tone_notes", {
			groupId: group.id,
			error: error.message,
		});
		return false;
	}

	logger.info("[auto-learning] Updated tone_notes", {
		groupId: group.id,
		newLength: updatedToneNotes.length,
	});
	return true;
}

// ============================================================================
// Store Data-Driven Insights on Content Strategy
// ============================================================================

async function storeDataDrivenInsights(
	groupId: string,
	userId: string,
	analysis: AIAnalysis,
	topPerformers: PostPerformance[],
	bottomPerformers: PostPerformance[],
	totalPostCount: number,
	allPosts: PostPerformance[],
	groupTimezone?: string,
): Promise<void> {
	const supabase = getSupabaseAny();

	// Compute best posting hours from top performers' publish times
	const hourCounts = new Map<number, number>();
	for (const post of topPerformers) {
		if (!post.publishedAt) continue;
		const hour = new Date(post.publishedAt).getUTCHours();
		hourCounts.set(hour, (hourCounts.get(hour) || 0) + 1);
	}
	const bestHours = [...hourCounts.entries()]
		.sort((a, b) => b[1] - a[1])
		.slice(0, 3)
		.map(([hour]) => hour);

	// Compute average velocities
	const avgTopVelocity =
		topPerformers.length > 0
			? topPerformers.reduce((sum, p) => sum + p.engagementVelocity, 0) /
				topPerformers.length
			: 0;
	const avgBottomVelocity =
		bottomPerformers.length > 0
			? bottomPerformers.reduce((sum, p) => sum + p.engagementVelocity, 0) /
				bottomPerformers.length
			: 0;

	const mediaPerf = analyzeMediaPerformance(allPosts);
	const lengthPerf = analyzeContentLength(allPosts);

	// Convert best hours to local timezone if available
	let bestPostingHoursLocal: number[] | undefined;
	if (groupTimezone) {
		try {
			bestPostingHoursLocal = bestHours.map((h) => {
				const d = new Date();
				d.setUTCHours(h, 0, 0, 0);
				const localHour = parseInt(
					new Intl.DateTimeFormat("en-US", {
						hour: "numeric",
						hour12: false,
						timeZone: groupTimezone,
					}).format(d),
					10,
				);
				return localHour;
			});
		} catch {
			/* fall through — invalid timezone */
		}
	}

	const dataDrivenInsights: Record<string, unknown> = {
		updated_at: new Date().toISOString(),
		top_patterns: analysis.winning_patterns?.slice(0, 5) || [],
		avoid_patterns: analysis.losing_patterns?.slice(0, 5) || [],
		best_posting_hours: bestHours,
		avg_top_velocity: Math.round(avgTopVelocity * 100) / 100,
		avg_bottom_velocity: Math.round(avgBottomVelocity * 100) / 100,
		recommended_mix: analysis.recommended_additions_to_tone_notes || "",
		sample_size: totalPostCount,
		analysis_period_days: 7,
		media_performance: mediaPerf,
		length_performance: lengthPerf,
	};

	if (bestPostingHoursLocal) {
		dataDrivenInsights.best_posting_hours_local = bestPostingHoursLocal;
		dataDrivenInsights.timezone = groupTimezone;
	}

	try {
		// Fetch current strategy
		const { data: currentGroup } = await supabase
			.from("account_groups")
			.select("content_strategy")
			.eq("id", groupId)
			.eq("user_id", userId)
			.maybeSingle();

		const currentStrategy =
			(currentGroup?.content_strategy as Record<string, unknown>) || {};
		const updatedStrategy = {
			...currentStrategy,
			data_driven_insights: dataDrivenInsights,
		};

		const { error } = await supabase
			.from("account_groups")
			.update({
				// biome-ignore lint/suspicious/noExplicitAny: Supabase Json type mismatch
				content_strategy: updatedStrategy as any,
				updated_at: new Date().toISOString(),
			})
			.eq("id", groupId)
			.eq("user_id", userId);

		if (error) {
			logger.error("[auto-learning] Failed to store data_driven_insights", {
				groupId,
				error: error.message,
			});
			return;
		}

		logger.info("[auto-learning] Stored data_driven_insights", {
			groupId,
			bestHours,
			avgTopVelocity: dataDrivenInsights.avg_top_velocity,
			sampleSize: totalPostCount,
		});
	} catch (err) {
		logger.error("[auto-learning] Error storing data_driven_insights", {
			groupId,
			error: serializeError(err),
		});
	}
}

// ============================================================================
// Media & Length Performance Analysis
// ============================================================================

function analyzeMediaPerformance(posts: PostPerformance[]): {
	text_avg_er: number;
	media_avg_er: number;
	recommended_media_ratio: number;
} {
	const textOnly = posts.filter((p) => !p.contentType);
	const withMedia = posts.filter((p) => p.contentType);

	const textAvg =
		textOnly.length > 0
			? textOnly.reduce((sum, p) => sum + p.engagementRate, 0) / textOnly.length
			: 0;
	const mediaAvg =
		withMedia.length > 0
			? withMedia.reduce((sum, p) => sum + p.engagementRate, 0) /
				withMedia.length
			: 0;

	// Recommended ratio: proportional to relative performance, clamped 20-80%
	const total = textAvg + mediaAvg;
	const ratio = total > 0 ? Math.round((mediaAvg / total) * 100) : 50;
	return {
		text_avg_er: Math.round(textAvg * 100) / 100,
		media_avg_er: Math.round(mediaAvg * 100) / 100,
		recommended_media_ratio: Math.max(20, Math.min(80, ratio)),
	};
}

function analyzeContentLength(posts: PostPerformance[]): {
	ultra_short_er: number; // 0-25 chars
	short_er: number; // 26-60 chars
	medium_er: number; // 61-120 chars
	long_er: number; // 121+ chars
	recommended_weights: [number, number, number, number];
} {
	const buckets = {
		ultra: [] as number[],
		short: [] as number[],
		medium: [] as number[],
		long: [] as number[],
	};

	for (const p of posts) {
		const len = p.content.length;
		if (len <= 25) buckets.ultra.push(p.engagementRate);
		else if (len <= 60) buckets.short.push(p.engagementRate);
		else if (len <= 120) buckets.medium.push(p.engagementRate);
		else buckets.long.push(p.engagementRate);
	}

	const avg = (arr: number[]) =>
		arr.length > 0 ? arr.reduce((a, b) => a + b, 0) / arr.length : 0;
	const avgs = [
		avg(buckets.ultra),
		avg(buckets.short),
		avg(buckets.medium),
		avg(buckets.long),
	];

	// Normalize weights proportional to performance, 5% minimum per bucket, sum to 100
	const total = avgs.reduce((a, b) => a + b, 0);
	let weights: [number, number, number, number];
	if (total > 0) {
		const raw = avgs.map((a) => Math.max(5, Math.round((a / total) * 100)));
		const rawSum = raw.reduce((a, b) => a + b, 0);
		// Normalize to 100
		weights = raw.map((w) => Math.round((w / rawSum) * 100)) as [
			number,
			number,
			number,
			number,
		];
		// Fix rounding to exactly 100
		const diff = 100 - weights.reduce((a, b) => a + b, 0);
		weights[0] += diff;
	} else {
		weights = [30, 40, 20, 10]; // default
	}

	return {
		ultra_short_er: Math.round(avg(buckets.ultra) * 100) / 100,
		short_er: Math.round(avg(buckets.short) * 100) / 100,
		medium_er: Math.round(avg(buckets.medium) * 100) / 100,
		long_er: Math.round(avg(buckets.long) * 100) / 100,
		recommended_weights: weights,
	};
}

// ============================================================================
// Content Type Mix Analysis
// ============================================================================

interface ContentTypeMix {
	type: string;
	count: number;
	avgER: number;
	pctOfTotal: number;
}

async function computeContentTypeMix(
	workspaceId: string,
	groupId: string,
): Promise<ContentTypeMix[]> {
	const supabase = getSupabaseAny();
	const weekAgo = new Date(Date.now() - 7 * 24 * 60 * 60 * 1000).toISOString();

	try {
		const { data: queueItems } = await (
			supabase as ReturnType<typeof getSupabaseAny>
		)
			.from("auto_post_queue")
			.select("content_type, engagement_rate")
			.eq("workspace_id", workspaceId)
			.eq("group_id", groupId)
			.eq("status", "published")
			.not("content_type", "is", null)
			.gte("posted_at", weekAgo);

		if (!queueItems || queueItems.length < 5) return [];

		const typeStats = new Map<string, { total: number; count: number }>();
		for (const item of queueItems) {
			const ct = item.content_type as string;
			if (!ct) continue;
			const existing = typeStats.get(ct) || { total: 0, count: 0 };
			existing.total += Number(item.engagement_rate) || 0;
			existing.count++;
			typeStats.set(ct, existing);
		}

		const totalPosts = queueItems.length;
		const mix: ContentTypeMix[] = [];

		for (const [type, stats] of typeStats.entries()) {
			mix.push({
				type,
				count: stats.count,
				avgER:
					stats.count > 0
						? Math.round((stats.total / stats.count) * 1000) / 1000
						: 0,
				pctOfTotal: Math.round((stats.count / totalPosts) * 100),
			});
		}

		// Sort by average engagement rate descending
		mix.sort((a, b) => b.avgER - a.avgER);
		return mix;
	} catch (err) {
		logger.warn("[auto-learning] Failed to compute content type mix", {
			groupId,
			error: serializeError(err),
		});
		return [];
	}
}

function formatContentTypeMixSection(
	mix: ContentTypeMix[],
	weekDate: string,
): string {
	if (mix.length === 0) return "";

	const lines = mix.map(
		(m) =>
			`- ${Math.round(m.pctOfTotal)}% ${m.type} (avg ER: ${(m.avgER * 100).toFixed(1)}%, ${m.count} posts)`,
	);

	const best = mix[0];
	const worst = mix[mix.length - 1];

	return `\n--- DATA-DRIVEN MIX (week of ${weekDate}) ---
Recommended ratio based on performance:
${lines.join("\n")}
Top performing content_type: ${best!.type} (${(best!.avgER * 100).toFixed(1)}% avg ER)
Worst performing content_type: ${worst!.type} (${(worst!.avgER * 100).toFixed(1)}% avg ER)`;
}

// ============================================================================
// Log AI Feedback Ratings
// ============================================================================

async function logFeedbackRatings(
	userId: string,
	topPerformers: PostPerformance[],
	bottomPerformers: PostPerformance[],
): Promise<number> {
	const supabase = getSupabaseAny();
	const weekDate = new Date().toISOString().split("T")[0]!;
	let ratings = 0;

	// Rate top performers
	for (const post of topPerformers) {
		if (ratings >= MAX_FEEDBACK_RATINGS) break;
		try {
			await supabase.from("ai_feedback").insert({
				user_id: userId,
				feature: "generate",
				suggestion_content: post.content.slice(0, 500),
				was_used: true,
				context: JSON.stringify({
					source: "auto-learning",
					rating: 1,
					engagementRate: post.engagementRate,
					viewsCount: post.viewsCount,
					repliesCount: post.repliesCount,
					weekOf: weekDate,
				}),
			});
			ratings++;
		} catch (err) {
			logger.debug("[auto-learning] Failed to log positive feedback", {
				postId: post.id,
				error: String(err),
			});
		}
	}

	// Rate bottom performers
	for (const post of bottomPerformers) {
		if (ratings >= MAX_FEEDBACK_RATINGS) break;
		try {
			await supabase.from("ai_feedback").insert({
				user_id: userId,
				feature: "generate",
				suggestion_content: post.content.slice(0, 500),
				was_used: false,
				context: JSON.stringify({
					source: "auto-learning",
					rating: -1,
					engagementRate: post.engagementRate,
					viewsCount: post.viewsCount,
					repliesCount: post.repliesCount,
					weekOf: weekDate,
				}),
			});
			ratings++;
		} catch (err) {
			logger.debug("[auto-learning] Failed to log negative feedback", {
				postId: post.id,
				error: String(err),
			});
		}
	}

	return ratings;
}

// ============================================================================
// Save Summary to Agent Notes
// ============================================================================

async function saveAutoLearningSummary(
	userId: string,
	groupResults: GroupResult[],
	totalRatings: number,
): Promise<void> {
	const weekDate = new Date().toISOString().split("T")[0]!;
	const key = `auto-learning-${weekDate}`;

	const value = JSON.stringify({
		weekOf: weekDate,
		groupResults: groupResults.map((g) => ({
			groupId: g.groupId,
			groupName: g.groupName,
			totalPosts: g.totalPosts,
			medianER: g.medianER,
			topPostContent: g.topPostContent,
			topPostER: g.topPostER,
			patternsFound: g.patternsFound,
			confidenceScore: g.confidenceScore,
			toneNotesUpdated: g.toneNotesUpdated,
			error: g.error,
		})),
		totalFeedbackRatings: totalRatings,
	});

	// Truncate to agent_notes value limit (5000 chars)
	const truncatedValue = value.slice(0, 5000);

	const db = getSupabaseAny();

	// Check for existing note with this key
	const { data: existing } = await db
		.from("agent_notes")
		.select("id")
		.eq("user_id", userId)
		.eq("key", key)
		.is("account_group_id", null)
		.maybeSingle();

	if (existing) {
		const { error: updateErr } = await db
			.from("agent_notes")
			.update({ value: truncatedValue, updated_at: new Date().toISOString() })
			.eq("id", existing.id);
		if (updateErr) {
			logger.warn("[auto-learning] Failed to update agent_notes", {
				key,
				error: updateErr.message,
			});
		}
	} else {
		const { error: insertErr } = await db.from("agent_notes").insert({
			user_id: userId,
			key,
			value: truncatedValue,
			account_group_id: null,
		});
		if (insertErr) {
			logger.warn("[auto-learning] Failed to insert agent_notes", {
				key,
				error: insertErr.message,
			});
		}
	}

	logger.info("[auto-learning] Saved summary to agent_notes", {
		key,
		groupCount: groupResults.length,
	});
}

// getUserAIConfig imported from ../aiConfig.js above
