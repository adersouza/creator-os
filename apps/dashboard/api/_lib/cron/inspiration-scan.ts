// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
/**
 * Inspiration Engine Daily Scan Cron Job
 * Runs daily at 4 AM UTC to generate AI-adapted content ideas from competitor posts
 *
 * Schedule: 0 4 * * * (configured in vercel.json)
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";
import { alertCronFailure } from "../alerting.js";
import { trackGeminiResponseCost } from "../aiUsageTracking.js";
import { trackCronRun, withCronLock } from "../cronUtils.js";
import { logger, serializeError } from "../logger.js";
import { escapeForPrompt } from "../promptUtils.js";
import { getSupabase, getSupabaseAny } from "../supabase.js";

// ============================================================================
// Configuration
// ============================================================================

export const config = {
	maxDuration: 300, // 5 minutes max
};

// Tier limits for idea generation
const TIER_LIMITS = {
	free: 10,
	pro: 50,
	agency: Infinity,
	empire: Infinity,
};

// ============================================================================
// Supabase Client
// ============================================================================

// ============================================================================
// AI Generation (inline to avoid module bundling issues)
// ============================================================================

interface GeneratedIdea {
	content: string;
	insight: string;
	tags: string[];
	viralScore: number;
	formula?: string | undefined;
}

import { getUserAIConfig, type UserAIConfig } from "../aiConfig.js";

// Extracted Style DNA (simplified for cron job)
interface ExtractedStyle {
	hooks?: { patterns?: string[] | undefined } | undefined;
	vocabulary?: { signature_words?: string[] | undefined } | undefined;
	emoji_usage?: {
        		frequency?: string | undefined;
        		placement?: string | undefined;
        		favorites?: string[] | undefined;
        	} | undefined;
	length?: { typical_chars?: string | undefined; preference?: string | undefined } | undefined;
	tone?: { vibe?: string | undefined; energy?: string | undefined } | undefined;
	punctuation?: { quirks?: string[] | undefined } | undefined;
}

// Adaptation angles for variety
type AdaptationAngle =
	| "direct"
	| "counter"
	| "story"
	| "list"
	| "meme"
	| "question";

const ADAPTATION_ANGLES: Record<AdaptationAngle, string> = {
	direct: "Keep the winning concept and restyle it in your voice",
	counter:
		"Take the OPPOSITE stance or contrarian angle. Challenge the original premise",
	story:
		"Transform into a personal story. Start with 'I used to...' or 'Last week I...'",
	list: "Expand into a mini-list or actionable steps (1. 2. 3. format)",
	meme: "Make it funny/memey with internet culture vibes. Add humor or absurdity",
	question:
		"Reframe as an engaging question ('What if...', 'Why do...', 'Have you ever...')",
};

const ANGLE_KEYS: AdaptationAngle[] = [
	"direct",
	"counter",
	"story",
	"list",
	"meme",
	"question",
];

// getUserAIConfig imported from ../aiConfig.js above

async function getUserExtractedStyle(
	userId: string,
): Promise<ExtractedStyle | null> {
	try {
		// Get first account for user that has extracted_style in ai_config
		const { data: accounts } = await getSupabase()
			.from("accounts")
			.select("ai_config")
			.eq("user_id", userId)
			.not("ai_config", "is", null);

		if (!accounts || accounts.length === 0) {
			return null;
		}

		// Find the first account with extracted_style
		for (const account of accounts as AccountAiConfigRow[]) {
			const aiConfig = account.ai_config;
			if (aiConfig?.extracted_style) {
				return aiConfig.extracted_style as ExtractedStyle;
			}
		}

		return null;
	} catch (err) {
		logger.warn("Failed to fetch user extracted style", {
			error: serializeError(err),
		});
		return null;
	}
}

async function callGeminiAPI(
	prompt: string,
	apiKey: string,
	model?: string,
	userId: string = "platform",
	keySource?: "user" | "env_fallback" | undefined,
): Promise<string | null> {
	if (!apiKey) {
		return null;
	}

	const modelId = model || "gemini-2.0-flash";

	try {
		const response = await fetch(
			`https://generativelanguage.googleapis.com/v1beta/models/${modelId}:generateContent?key=${apiKey}`,
			{
				method: "POST",
				headers: { "Content-Type": "application/json" },
				body: JSON.stringify({
					contents: [{ parts: [{ text: prompt }] }],
					generationConfig: {
						temperature: 0.8,
						maxOutputTokens: 1024,
					},
				}),
				signal: AbortSignal.timeout(15000),
			},
		);

		if (!response.ok) {
			logger.error("Gemini API error", { status: response.status });
			return null;
		}

		const data = await response.json();
		trackGeminiResponseCost(
			userId,
			data,
			modelId,
			"inspiration_scan",
			keySource,
		);
		return data.candidates?.[0]?.content?.parts?.[0]?.text || null;
	} catch (error) {
		logger.error("Gemini API call failed", {
			error: serializeError(error),
		});
		return null;
	}
}

async function generateInspirationIdea(
	originalContent: string,
	_competitorUsername: string,
	style: string = "casual",
	aiConfig: UserAIConfig,
	extractedStyle?: ExtractedStyle | null,
	angle: AdaptationAngle = "direct",
	userId: string = "platform",
): Promise<(GeneratedIdea & { angle: AdaptationAngle }) | null> {
	const styleDescriptions: Record<string, string> = {
		casual: "casual, conversational, and relatable",
		professional: "professional, authoritative, and polished",
		witty: "witty, clever, and playful with humor",
		inspirational: "inspirational, motivational, and uplifting",
		edgy: "bold, provocative, and slightly controversial",
	};

	// Get angle-specific prompt instruction
	const angleInstruction = ADAPTATION_ANGLES[angle] || ADAPTATION_ANGLES.direct;

	// Calculate target length based on original
	const originalLength = originalContent.length;
	const maxLength = Math.max(80, Math.min(originalLength * 2, 150));

	// Build Style DNA context if available (prioritized voice matching)
	const styleDNAContext = extractedStyle
		? `
YOUR VOICE (Style DNA):
- Hook patterns: ${extractedStyle.hooks?.patterns?.slice(0, 3).join(" | ") || "N/A"}
- Signature phrases: ${extractedStyle.vocabulary?.signature_words?.slice(0, 5).join(", ") || "N/A"}
- Emoji style: ${extractedStyle.emoji_usage?.frequency || "moderate"} usage
- Vibe: ${extractedStyle.tone?.vibe || "conversational"}
`
		: "";

	const prompt = `Rewrite this viral post keeping the SAME THEME and VIBE but making it your own.

ORIGINAL: "${escapeForPrompt(originalContent)}"
${styleDNAContext}
ADAPTATION ANGLE: ${angleInstruction}

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
		// Parse JSON from response
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
			angle, // Track which angle was used
		};
	} catch (err) {
		logger.error("Failed to parse AI response for inspiration", {
			error: serializeError(err),
		});
		return null;
	}
}

// ============================================================================
// Row / API Types
// ============================================================================

interface AccountAiConfigRow {
	ai_config: { extracted_style?: ExtractedStyle | undefined } | null;
}

interface ProfileRow {
	subscription_tier: string | null;
}

interface ProfileTimezoneRow {
	timezone: string | null;
}

interface InspirationConfigItem {
	user_id: string;
	workspace_id: string;
	ideas_per_competitor: number | null;
	adaptation_style: string | null;
}

interface CompetitorItem {
	id: string;
	username: string;
	avatar_url: string | null;
	threads_user_id: string | null;
}

interface CompetitorPostItem {
	threads_post_id: string;
	content: string | null;
	media_urls: string[] | null;
	media_type: string | null;
	permalink: string | null;
	likes: number | null;
	replies: number | null;
	reposts: number | null;
}

// ============================================================================
// Main Cron Handler
// ============================================================================

export default async function handler(req: VercelRequest, res: VercelResponse) {
	// Verify cron secret (Vercel injects this automatically for cron jobs)
	// Strict cron secret check — no x-vercel-cron fallback (spoofable header)
	const { verifyCronAuth } = await import("../apiResponse.js");
	if (!verifyCronAuth(req, res)) return;

	const supabase = getSupabase();

	const lockResult = await withCronLock(
		supabase,
		"inspiration-scan",
		async () => {
			return trackCronRun(supabase, "inspiration-scan", async () => {
				const count = await processInspirationScan();
				return { itemsProcessed: count };
			});
		},
	);

	if (lockResult.skipped) {
		return res.status(200).json({ skipped: true });
	}

	return res.status(200).json({ success: true });
}

export async function processInspirationScan(): Promise<number> {
	const startTime = Date.now();

	logger.info("Starting inspiration scan");

	const stats = {
		usersProcessed: 0,
		competitorsScanned: 0,
		ideasGenerated: 0,
		errors: 0,
	};

	try {
		// Get all users with inspiration enabled
		const { data: configs, error: configError } = await getSupabase()
			.from("inspiration_config")
			.select("user_id, workspace_id, ideas_per_competitor, adaptation_style")
			.eq("enabled", true);

		if (configError) {
			logger.error("Error fetching inspiration configs", {
				error: serializeError(configError),
			});
			throw configError;
		}

		if (!configs || configs.length === 0) {
			logger.info("No users with inspiration enabled");
			return 0;
		}

		logger.info("Processing inspiration scan users", { count: configs.length });

		for (const configItem of configs as InspirationConfigItem[]) {
			const config = configItem;
			try {
				// #549: Respect user timezone — only generate inspirations when 4 AM UTC
				// falls within the user's "morning" window (4-10 AM local time).
				// If no timezone is set, proceed normally (default to UTC).
				try {
					const { data: profileTz } = await getSupabase()
						.from("profiles")
						.select("timezone")
						.eq("id", config.user_id)
						.maybeSingle();

					const tz = (profileTz as ProfileTimezoneRow | null)?.timezone;
					if (tz) {
						// Calculate local hour at 4 AM UTC in the user's timezone
						const nowUtc = new Date();
						let localHour: number;
						try {
							const formatter = new Intl.DateTimeFormat("en-US", {
								timeZone: tz,
								hour: "numeric",
								hour12: false,
							});
							localHour = parseInt(formatter.format(nowUtc), 10);
						} catch (formatError) {
							// Invalid timezone string — skip check, proceed normally
							logger.debug("Timezone formatting failed, proceeding", {
								userId: config.user_id,
								error: serializeError(formatError),
							});
							localHour = 4; // Treat as UTC (will pass the check)
						}

						// Only process if local time is in the "morning" window (4-10 AM)
						if (localHour < 4 || localHour > 10) {
							logger.info("Skipping user — not morning in their timezone", {
								userId: config.user_id,
								timezone: tz,
								localHour,
							});
							continue;
						}
					}
				} catch (tzErr) {
					// Timezone check is non-fatal — proceed if it fails
					logger.debug("Timezone check failed, proceeding", {
						userId: config.user_id,
						error: serializeError(tzErr),
					});
				}

				// Get user's AI config (API key) - skip if not configured
				const userAIConfig = await getUserAIConfig(config.user_id);
				if (!userAIConfig) {
					logger.info("User has no AI API key, skipping inspiration scan", {
						userId: config.user_id,
					});
					continue;
				}

				// Get user's extracted style DNA for better voice matching
				const extractedStyle = await getUserExtractedStyle(config.user_id);
				if (extractedStyle) {
					logger.info("User has Style DNA, using for adaptation", {
						userId: config.user_id,
					});
				}

				// Get user's subscription tier
				const { data: profile } = await getSupabase()
					.from("profiles")
					.select("subscription_tier")
					.eq("id", config.user_id)
					.maybeSingle();

				const profileData = profile as ProfileRow | null;
				const tier = (profileData?.subscription_tier ||
					"free") as keyof typeof TIER_LIMITS;
				const dailyLimit = TIER_LIMITS[tier] || TIER_LIMITS.free;

				// Check how many ideas generated today
				const today = new Date().toISOString().split("T")[0]!;
				const { count: todayCount } = await getSupabase()
					.from("inspiration_ideas")
					.select("*", { count: "exact", head: true })
					.eq("user_id", config.user_id)
					.gte("generated_at", `${today}T00:00:00Z`);

				const remainingQuota = dailyLimit - (todayCount || 0);
				if (remainingQuota <= 0) {
					logger.info("User at daily inspiration limit, skipping", {
						userId: config.user_id,
					});
					continue;
				}

				// Get user's competitors
				const { data: competitors } = await getSupabase()
					.from("competitors")
					.select("id, username, avatar_url, threads_user_id")
					.eq("user_id", config.user_id);

				if (!competitors || competitors.length === 0) {
					logger.info("User has no competitors for inspiration scan", {
						userId: config.user_id,
					});
					continue;
				}

				let userIdeasGenerated = 0;
				const maxIdeasPerCompetitor = config.ideas_per_competitor || 10;

				for (const competitor of competitors as CompetitorItem[]) {
					if (userIdeasGenerated >= remainingQuota) break;

					stats.competitorsScanned++;

					// Get competitor corpus posts from last 7 days. Threads competitor
					// post metrics are usually unavailable, so use recency/patterns
					// instead of fake top-performing ranking.
					const sevenDaysAgo = new Date();
					sevenDaysAgo.setDate(sevenDaysAgo.getDate() - 7);

					const { data: posts } = await getSupabase()
						.from("competitor_top_posts")
						.select("*")
						.eq("competitor_id", competitor.id)
						.gte("published_at", sevenDaysAgo.toISOString())
						.order("scraped_at", { ascending: false, nullsFirst: false })
						.limit(10);

					if (!posts || posts.length === 0) {
						logger.info("No recent posts for competitor", {
							username: competitor.username,
						});
						continue;
					}

					let competitorIdeasGenerated = 0;

					for (const post of posts as unknown as CompetitorPostItem[]) {
						if (competitorIdeasGenerated >= maxIdeasPerCompetitor) break;
						if (userIdeasGenerated >= remainingQuota) break;

						// Skip if already processed this post
						const { count: existingCount } = await getSupabaseAny()
							.from("inspiration_ideas")
							.select("*", { count: "exact", head: true })
							.eq("user_id", config.user_id)
							.eq("original_post->id", post.threads_post_id);

						if (existingCount && existingCount > 0) {
							continue;
						}

						// Rotate through angles for variety
						const angleIndex = competitorIdeasGenerated % ANGLE_KEYS.length;
						const angle = ANGLE_KEYS[angleIndex];

						// Generate AI adaptation using user's own API key (+ Style DNA if available)
						const idea = await generateInspirationIdea(
							post.content || "",
							competitor.username,
							config.adaptation_style || "casual",
							userAIConfig,
							extractedStyle,
							angle,
							config.user_id,
						);

						if (!idea) {
							stats.errors++;
							continue;
						}

						// Store in database
						const { error: insertError } = await getSupabase()
							.from("inspiration_ideas")
							.insert({
								user_id: config.user_id,
								workspace_id: config.workspace_id,
								original_post: {
									id: post.threads_post_id,
									content: post.content,
									mediaUrl: post.media_urls?.[0],
									mediaType: post.media_type,
									permalink: post.permalink,
									engagementScore:
										(post.likes || 0) +
										(post.replies || 0) * 3 +
										(post.reposts || 0) * 2,
								},
								competitor_id: competitor.id,
								competitor_username: competitor.username,
								competitor_avatar_url: competitor.avatar_url,
								adapted_content: idea.content,
								viral_score: idea.viralScore,
								ai_insight: idea.insight,
								topic_tags: idea.tags,
								adaptation_style: config.adaptation_style || "casual",
								adaptation_angle: idea.angle, // Store the angle used
								viral_formula: idea.formula || null, // Store the extracted viral formula
								status: "pending",
								generated_at: new Date().toISOString(),
								expires_at: new Date(
									Date.now() + 7 * 24 * 60 * 60 * 1000,
								).toISOString(),
							});

						if (insertError) {
							logger.error("Inspiration idea insert error", {
								error: serializeError(insertError),
							});
							stats.errors++;
							continue;
						}

						stats.ideasGenerated++;
						userIdeasGenerated++;
						competitorIdeasGenerated++;
					}
				}

				// Update last scan time
				await getSupabase()
					.from("inspiration_config")
					.update({ last_scan_at: new Date().toISOString() })
					.eq("user_id", config.user_id);

				stats.usersProcessed++;
			} catch (userError) {
				logger.error("Error processing user for inspiration scan", {
					userId: config.user_id,
					error: serializeError(userError),
				});
				stats.errors++;
			}
		}

		// Archive expired ideas instead of hard-deleting (#505)
		// Pending ideas past their expires_at get moved to 'archived' status.
		// The daily-maintenance cron handles permanent deletion of archived
		// entries older than 90 days.
		const { count: archivedCount } = await getSupabase()
			.from("inspiration_ideas")
			.update({ status: "archived" }, { count: "exact" })
			.lt("expires_at", new Date().toISOString())
			.eq("status", "pending");

		const duration = (Date.now() - startTime) / 1000;

		logger.info("Inspiration scan complete", {
			...stats,
			expiredArchived: archivedCount || 0,
			durationSeconds: duration,
		});

		// Create notification for users with new ideas
		if (stats.ideasGenerated > 0) {
			// Batch notification creation would go here
			logger.info("New inspiration ideas ready", {
				count: stats.ideasGenerated,
			});
		}

		return stats.ideasGenerated;
	} catch (error) {
		logger.error("Inspiration scan failed", {
			error: serializeError(error),
		});
		// Report to Sentry
		try {
			const { captureServerException } = await import("../sentryServer.js");
			await captureServerException(error, { cronJob: "inspiration-scan" });
		} catch (sentryErr) {
			logger.warn("[inspiration-scan] Sentry capture failed", {
				originalError: serializeError(error),
				sentryError:
					sentryErr instanceof Error ? sentryErr.message : String(sentryErr),
			});
		}
		alertCronFailure("inspiration-scan", serializeError(error));
		throw error;
	}
}
