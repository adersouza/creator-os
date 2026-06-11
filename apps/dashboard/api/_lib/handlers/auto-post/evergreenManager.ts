// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
/**
 * Evergreen Manager — topic tags, humanizer, proven templates, evergreen recycling
 *
 * Extracted from queueFill.ts. Handles:
 * - Topic tag detection for Threads topic feeds
 * - Post humanization (micro-human tics)
 * - Proven question template insertion
 * - Evergreen post recycling with AI rewrite + format transformation
 */

import { logger } from "../../logger.js";
import { getSupabaseAny } from "../../supabase.js";
import { buildPublishFingerprint } from "./publishFingerprint.js";
import { calculateNaturalPostTimes } from "./timingEngine.js";
import type { AutoPostConfig, TimingInsights } from "./types.js";

const db = () => getSupabaseAny();

type EvergreenSchedulingContext = {
	config: AutoPostConfig;
	accountCount?: number | undefined;
	insights?: TimingInsights | undefined;
	platform?: "threads" | "instagram" | undefined;
};

function scheduleEvergreenItem(
	groupId: string | undefined,
	fallbackDelayMs: number,
	scheduling?: EvergreenSchedulingContext | undefined,
): string {
	if (scheduling) {
		const [scheduledFor] = calculateNaturalPostTimes(
			1,
			scheduling.config,
			groupId,
			scheduling.accountCount,
			scheduling.insights,
			scheduling.platform,
		);
		if (scheduledFor) return scheduledFor;
	}

	return new Date(Date.now() + fallbackDelayMs).toISOString();
}

// ============================================================================
// Topic Tag Detection — matches content to Threads topic categories
// ============================================================================

/**
 * Topic tag rules ordered by specificity (most specific first).
 * Each rule: [regex, tag string]. First match wins.
 * Tags must match Threads' actual topic categories for best distribution.
 */
const TOPIC_TAG_RULES: Array<[RegExp, string]> = [
	// Gaming — broad coverage of games, platforms, gaming culture
	[
		/\b(valorant|fortnite|apex legends?|overwatch|league of legends|lol|cod|warzone|minecraft|roblox|elden ring|gta|zelda|mario kart|stardew valley|marvel rivals|smash bros?)\b/i,
		"Gaming",
	],
	[
		/\b(game[rs]?|gaming|xbox|ps[45]|playstation|nintendo|switch|steam|pc gaming|console|controller|kbm|ranked|lobby|raid|squad|respawn|esports?|twitch|streamer|derank|comp)\b/i,
		"Gaming",
	],

	// Anime & Manga
	[
		/\b(naruto|one piece|jujutsu|attack on titan|demon slayer|dragon ball|my hero|hunter x|bleach|chainsaw man|spy x family|cowboy bebop|studio ghibli|death note)\b/i,
		"Anime & Manga",
	],
	[
		/\b(anime|manga|weeb|sub vs dub|subbed|dubbed|waifu|cosplay|isekai|shonen|shoujo|otaku)\b/i,
		"Anime & Manga",
	],

	// Astrology — zodiac signs and related terms
	[
		/\b(scorpio|aries|gemini|leo|pisces|sagittarius|capricorn|libra|aquarius|virgo|taurus|cancer)\b/i,
		"Astrology",
	],
	[
		/\b(zodiac|astrology|horoscope|birth chart|mercury retrograde|rising sign|moon sign|star sign)\b/i,
		"Astrology",
	],

	// Fitness & Gym
	[
		/\b(deadlift|squat|bench press|pull.?ups?|push.?ups?|burpees|hiit|crossfit|yoga|pilates|calisthenics)\b/i,
		"Fitness",
	],
	[
		/\b(gym|workout|exercise|leg day|arm day|chest day|pre.?workout|protein|gains|lifting|cardio|treadmill|weights|reps|sets|pr\b|personal record|fit check)\b/i,
		"Fitness",
	],

	// Dating & Relationships — core niche for our accounts
	[
		/\b(situationship|talking stage|friends with benefits|fwb|ghosted|ghosting|breadcrumb|love bomb|toxic ex)\b/i,
		"Dating & Relationships",
	],
	[
		/\b(date|dating|boyfriend|girlfriend|crush|single|relationship|married|engaged|breakup|broke up|heartbreak|love language|red flag|green flag|first date|second date|type|dm me|dms)\b/i,
		"Dating & Relationships",
	],
	[/\b(would you date|be honest|prove me wrong)\b/i, "Dating & Relationships"],

	// Late Night — catches our "who's up" style content
	[
		/\b(2\s?am|3\s?am|4\s?am|1\s?am|midnight|can'?t sleep|insomnia|up late|night owl|still (up|awake)|sleepless|late night|all.?night(er)?)\b/i,
		"Late Night",
	],

	// Food & Cooking
	[
		/\b(recipe|cooking|baking|chef|kitchen|meal prep|grilling|sushi|ramen|pasta|pizza|tacos|burgers?|brunch|breakfast)\b/i,
		"Food & Cooking",
	],
	[
		/\b(snack|munchies|comfort food|takeout|delivery|hungry|starving|craving|ice cream|chocolate|cookies|fridge)\b/i,
		"Food & Cooking",
	],

	// Music
	[
		/\b(spotify|apple music|soundcloud|vinyl|album|ep\b|mixtape|concert|festival|coachella|band|dj\b|rapper|singer)\b/i,
		"Music",
	],
	[
		/\b(song|playlist|album|music|listening|artist|lyrics|melody|beat|tune|headphones|earbuds|aux)\b/i,
		"Music",
	],

	// Movies & TV
	[
		/\b(netflix|hulu|disney\+?|hbo|prime video|peacock|paramount|crunchyroll|cinema|theater|marvel|dc\b|star wars|horror movie)\b/i,
		"Movies & TV",
	],
	[
		/\b(movie|film|series|tv show|streaming|binge|rewatch|season \d|episode|documentary|thriller|rom.?com|sitcom)\b/i,
		"Movies & TV",
	],

	// Mental Health & Self-Care (relevant for vulnerable/lonely content)
	[
		/\b(therapy|therapist|mental health|anxiety|depression|burnout|boundaries|self.?care|healing|overwhelmed|exhausted|drained)\b/i,
		"Mental Health",
	],

	// Pets & Animals
	[
		/\b(dog|puppy|cat|kitten|pet|rescue|adopt|vet|corgi|golden retriever|pitbull|husky|hamster|fish tank)\b/i,
		"Pets",
	],

	// Fashion & Style
	[
		/\b(outfit|ootd|fashion|drip|fit check|sneaker|jordans?|nike|adidas|thrift|vintage|streetwear|y2k|aesthetic)\b/i,
		"Fashion & Style",
	],

	// College & Student Life
	[
		/\b(college|university|campus|dorm|semester|finals|midterm|homework|assignment|professor|lecture|tuition|grad school|student loan)\b/i,
		"Student Life",
	],
	[
		/\b(essay|studying|procrastinat|class|school|gpa|dean'?s list|roommate|cafeteria)\b/i,
		"Student Life",
	],

	// Technology
	[
		/\b(iphone|android|samsung|macbook|laptop|coding|programming|ai\b|chatgpt|app|startup|tech|software|hardware|crypto|bitcoin|nft)\b/i,
		"Technology",
	],

	// Sports (non-gaming)
	[
		/\b(nfl|nba|mlb|nhl|football|basketball|soccer|baseball|hockey|tennis|golf|mma|ufc|boxing|f1|formula)\b/i,
		"Sports",
	],
	[
		/\b(playoffs?|championship|super bowl|world cup|draft|mvp|trade|free agent|coach)\b/i,
		"Sports",
	],

	// Beauty & Skincare
	[
		/\b(skincare|makeup|foundation|concealer|mascara|lipstick|blush|contour|highlighter|cleanser|moisturizer|spf|sunscreen|retinol|serum|glow.?up|beauty)\b/i,
		"Beauty",
	],

	// Books & Reading
	[
		/\b(book|novel|reading|audiobook|kindle|library|bookstore|author|fiction|non.?fiction|thriller|romance novel|fantasy|sci.?fi|poetry)\b/i,
		"Books",
	],

	// Travel
	[
		/\b(travel|vacation|trip|flight|airport|hotel|airbnb|beach|road trip|backpack|passport|tourist|explore|adventure)\b/i,
		"Travel",
	],

	// Memes & Internet Culture
	[
		/\b(meme|viral|tiktok|reels?|trending|cringe|based|slay|no cap|bussin|sus|ratio|rent free|main character|core\b)\b/i,
		"Internet Culture",
	],
];

/**
 * Detect the best topic tag for a post based on content.
 * Returns null if no confident match — untagged is better than mismatched.
 */
export function detectTopicTag(content: string): string | null {
	const lower = content.toLowerCase();
	for (const [regex, tag] of TOPIC_TAG_RULES) {
		if (regex.test(lower)) return tag;
	}
	return null;
}

// ============================================================================
// Humanizer — adds micro-human tics to AI-generated text before insertion
// ============================================================================

export function humanizePost(content: string): string {
	// 20% chance: return unchanged (most posts should get at least some human touch)
	if (Math.random() < 0.2) return content;

	let result = content;
	const tics: Array<(s: string) => string> = [
		// Contraction swaps (drop apostrophe — how real people text)
		(s) => s.replace(/don't/g, "dont"),
		(s) => s.replace(/I'm/g, "im"),
		(s) => s.replace(/it's/g, "its"),
		(s) => s.replace(/can't/g, "cant"),
		(s) => s.replace(/won't/g, "wont"),
		(s) => s.replace(/didn't/g, "didnt"),
		(s) => s.replace(/you're/g, "ur"),
		(s) => s.replace(/you/g, "u"),
		(s) => s.replace(/\bwith\b/g, "w"),
		(s) => s.replace(/\bright now\b/g, "rn"),
		(s) => s.replace(/\bplease\b/gi, "pls"),
		(s) => s.replace(/\bbecause\b/gi, "bc"),
		// Reverse contractions (expand — variety)
		(s) => s.replace(/\bdont\b/, "don't"),
		(s) => s.replace(/\bim\b/, "I'm"),
		// Double letters
		(s) => s.replace(/\bso\b /, "sooo "),
		(s) => s.replace(/\breally\b/, "reallly"),
		(s) => s.replace(/\byeah\b/, "yeahh"),
		(s) => s.replace(/\bplease\b/i, "plsss"),
		// Punctuation swaps
		(s) => s.replace(/\.\s*$/, ".."),
		(s) => s.replace(/\.\s*$/, ""),
		(s) => s.replace(/\?$/, "??"),
		(s) => s.replace(/\?$/, "? 🥺"),
		// Lowercase first char (most common in real texting)
		(s) => s.charAt(0).toLowerCase() + s.slice(1),
		(s) => s.toLowerCase(),
		// Remove a comma
		(s) => {
			const i = s.indexOf(",");
			return i > -1 ? s.slice(0, i) + s.slice(i + 1) : s;
		},
	];

	// Pick 2-3 random tics (more aggressive than before)
	const count = Math.random() < 0.4 ? 2 : 3;
	const shuffled = tics.sort(() => Math.random() - 0.5);
	for (let i = 0; i < Math.min(count, shuffled.length); i++) {
		result = shuffled[i]!(result);
	}

	// 25% chance: add one filler word (up from 15%)
	if (Math.random() < 0.25 && result.length < 70) {
		const fillers = [
			"lol",
			"tbh",
			"ngl",
			"fr",
			"rn",
			"lowkey",
			"honestly",
			"idk",
			"haha",
			"omg",
		];
		const filler = fillers[Math.floor(Math.random() * fillers.length)];
		result = result.replace(/\.?\s*$/, ` ${filler}`);
	}

	// Grammar fix: "a [vowel]" → "an [vowel]" (always runs — grammar errors look worse than AI)
	result = result.replace(/\ba ([aeiou])/gi, (match, vowel) => {
		const prefix = match[0] === "A" ? "An" : "an";
		return `${prefix} ${vowel}`;
	});

	return result;
}

// ============================================================================
// Proven Identity-Led Templates
// ============================================================================

const PROVEN_TEMPLATES = [
	"i'm single. i don't need your money. i can cook",
	"i'm a 9 but my anime taste is unhinged",
	"i love gym playlists but mine are mostly villain music",
	"people think i'm quiet but my notes app is chaos",
	"my music taste is basically a personality test",
	"drop your top 3 songs for a gym playlist",
	"what's the animated movie that still makes you cry?",
	"i miss having someone to send dumb memes to at 2am",
	"i can tell your type from your top 3 anime",
	"my comfort movie says way too much about me",
];

/**
 * Insert a proven question template into the queue.
 * Returns the number of templates inserted (0 or 1).
 */
export async function insertProvenTemplate(
	workspaceId: string,
	groupId: string | undefined,
	canGenerate: number,
	scheduling?: EvergreenSchedulingContext | undefined,
): Promise<number> {
	const templateSlots = Math.random() < 0.2 ? 1 : 0; // 20% chance per fill cycle
	if (templateSlots <= 0 || canGenerate <= 1) return 0;

	const templateIndex = Math.floor(Math.random() * PROVEN_TEMPLATES.length);
	const template = PROVEN_TEMPLATES[templateIndex];
	// Humanize slightly — random lowercase/punctuation variation
	let finalTemplate = template;
	if (Math.random() < 0.3) finalTemplate = finalTemplate!.replace(/\?$/, "??");
	if (Math.random() < 0.2 && finalTemplate!.length < 30) {
		const fillers = ["lol", "tbh", "ngl", "fr"];
		finalTemplate = finalTemplate!.replace(
			/\?+$/,
			` ${fillers[Math.floor(Math.random() * fillers.length)]}?`,
		);
	}

	try {
		const templateTime = scheduleEvergreenItem(
			groupId,
			Math.random() * 3600000,
			scheduling,
		);
		const fingerprint = buildPublishFingerprint({
			workspaceId,
			accountId: null,
			platform: scheduling?.platform ?? "threads",
			content: finalTemplate!,
			mediaUrls: null,
		});
		const sourceId = `proven_template:${templateIndex}`;
		const templateData: Record<string, unknown> = {
			workspace_id: workspaceId,
			content: finalTemplate,
			status: "pending",
			scheduled_for: templateTime,
			predicted_viral_score: 85,
			source_type: "template",
			source_id: sourceId,
			content_fingerprint: fingerprint.normalizedTextHash,
			publish_fingerprint: fingerprint.publishFingerprint,
			normalized_text_hash: fingerprint.normalizedTextHash,
			media_fingerprint: fingerprint.mediaFingerprint,
			duplicate_window_hours: fingerprint.duplicateWindowHours,
			provenance_status: "pass",
			provenance_error: null,
			content_type: "identity_statement",
			metadata: {
				content_archetype: {
					value: "identity_statement",
					confidence: 0.7,
					reason: "identity_led_proven_template",
					is_generic_question: false,
				},
				pattern_type: "identity_statement",
				content_fingerprint: fingerprint.normalizedTextHash,
				publish_fingerprint: fingerprint.publishFingerprint,
				source_id: sourceId,
				provenance: {
					source_type: "template",
					source_id: sourceId,
					content_fingerprint: fingerprint.normalizedTextHash,
					publish_fingerprint: fingerprint.publishFingerprint,
					quality_gate_result: "system_template_pass",
					quality_gate: {
						decision: "pass",
						reason: "identity_led_proven_template",
					},
				},
				quality_gate: {
					decision: "pass",
					reason: "identity_led_proven_template",
					lane: "system_template",
					score: 85,
				},
			},
		};
		if (groupId) templateData.group_id = groupId;
		await db().from("auto_post_queue").insert(templateData);
		logger.info("Inserted proven question template", {
			template: finalTemplate,
			workspaceId,
			groupId,
		});
		return 1;
	} catch {
		// Non-blocking — template insertion is best-effort
		return 0;
	}
}

// ============================================================================
// Evergreen Recycling
// ============================================================================

export interface EvergreenResult {
	insertCount: number;
	failedCount: number;
	errors: Array<{ postId: string; error: string }>;
}

/**
 * Recycle top-performing evergreen posts with AI rewrite + format transformation.
 * ~12% of slots come from top-performing evergreen posts (3x+ avg views).
 */
export async function recycleEvergreenPosts(
	workspaceId: string,
	groupId: string,
	canGenerate: number,
	platform: "threads" | "instagram",
	scheduling?: EvergreenSchedulingContext | undefined,
): Promise<EvergreenResult> {
	const evergreenSlots = Math.max(0, Math.floor(canGenerate * 0.12)); // ~12% of slots
	if (evergreenSlots <= 0)
		return { insertCount: 0, failedCount: 0, errors: [] };

	let evergreenInsertCount = 0;
	let evergreenFailedCount = 0;
	const evergreenErrors: Array<{ postId: string; error: string }> = [];

	try {
		// Find evergreen posts for accounts in this group
		let groupAccountIds: string[] = [];
		const { data: grpEv } = await db()
			.from("account_groups")
			.select("account_ids")
			.eq("id", groupId)
			.maybeSingle();
		groupAccountIds = (grpEv?.account_ids || []) as string[];

		if (groupAccountIds.length === 0)
			return { insertCount: 0, failedCount: 0, errors: [] };

		// Get group average views (last 14 days) for 3x threshold
		const fourteenDaysAgo = new Date(
			Date.now() - 14 * 86_400_000,
		).toISOString();
		const { data: recentPosts } = await db()
			.from("posts")
			.select("views_count")
			.in("account_id", groupAccountIds)
			.eq("status", "published")
			.not("views_count", "is", null)
			.gte("published_at", fourteenDaysAgo)
			.limit(100);

		const avgViews =
			recentPosts && recentPosts.length >= 5
				? recentPosts.reduce(
						(s: number, p: { views_count: number }) =>
							s + ((p.views_count as number) || 0),
						0,
					) / recentPosts.length
				: 0;

		if (avgViews <= 0) return { insertCount: 0, failedCount: 0, errors: [] };

		// Top-5% evergreen posts (3x+ average views OR high save rate) due for recycling
		const minGapDays = platform === "instagram" ? 90 : 21;
		const minGapDate = new Date(
			Date.now() - minGapDays * 86_400_000,
		).toISOString();

		// Primary path: high-view posts (3x avg) — auto-detect based on performance
		// Removed is_evergreen filter: the flag was never auto-set, so 0 posts qualified.
		// Performance criteria (3x avg views) are sufficient for candidate selection.
		const { data: evergreenPosts } = await db()
			.from("posts")
			.select(
				"id, content, views_count, saves_count, recycle_count, max_recycles, last_recycled_at, published_at, media_urls, media_type",
			)
			.in("account_id", groupAccountIds)
			.eq("status", "published")
			.gte("views_count", Math.round(avgViews * 3))
			.or(`last_recycled_at.is.null,last_recycled_at.lte.${minGapDate}`)
			.order("views_count", { ascending: false })
			.limit(evergreenSlots * 2); // 2x headroom for filter rejects

		// Secondary path: high save-rate posts (>2% of views)
		const { data: highSavePosts } = await db()
			.from("posts")
			.select(
				"id, content, views_count, saves_count, recycle_count, max_recycles, last_recycled_at, published_at, media_urls, media_type",
			)
			.in("account_id", groupAccountIds)
			.eq("status", "published")
			.not("saves_count", "is", null)
			.gte("saves_count", 1)
			.or(`last_recycled_at.is.null,last_recycled_at.lte.${minGapDate}`)
			.order("saves_count", { ascending: false })
			.limit(evergreenSlots);

		// Merge and deduplicate
		const evergreenIds = new Set(
			(evergreenPosts || []).map((p: { id: string }) => p.id),
		);
		const mergedEvergreen = [...(evergreenPosts || [])];
		for (const sp of highSavePosts || []) {
			if (evergreenIds.has(sp.id)) continue;
			const views = (sp.views_count as number) || 1;
			const saves = (sp.saves_count as number) || 0;
			const saveRate = saves / views;
			if (saveRate >= 0.02) {
				// 2% save rate threshold
				mergedEvergreen.push(sp);
				evergreenIds.add(sp.id);
			}
		}

		if (mergedEvergreen.length === 0)
			return { insertCount: 0, failedCount: 0, errors: [] };

		for (const ep of mergedEvergreen) {
			if (evergreenInsertCount >= evergreenSlots) break;
			// Skip maxed-out posts
			if ((ep.recycle_count || 0) >= (ep.max_recycles || 5)) continue;
			// Skip if content is empty
			if (!ep.content || (ep.content as string).trim().length < 5) continue;

			// AI rewrite with fresh hook — OFF by default (set
			// AUTOPOSTER_AI_RECYCLE_REWRITES=1 to opt in). When disabled, the
			// post still recycles but with the original copy verbatim. Toggled
			// off after the April 6 c8efb002 unblock removed the is_evergreen
			// filter and made this path the highest unattributed Gemini spender.
			let recycledContent = ep.content as string;
			const aiRewriteEnabled =
				process.env.AUTOPOSTER_AI_RECYCLE_REWRITES === "1";
			try {
				const { GoogleGenAI } = await import("@google/genai");
				const geminiKey = process.env.GEMINI_API_KEY;
				const { checkDailySpendLimit, trackAICost } = await import(
					"../../aiCostTracker.js"
				);
				const { allowed } = aiRewriteEnabled
					? await checkDailySpendLimit()
					: { allowed: false };
				if (aiRewriteEnabled && geminiKey && allowed) {
					const genAI = new GoogleGenAI({ apiKey: geminiKey });
					const charLimit = platform === "instagram" ? 2200 : 500;
					const rewritePrompt = `Rewrite this proven viral post with a FRESH opening hook and angle. Keep the same core emotion and message but make it feel like a new thought. Max ${charLimit} chars. Return ONLY the rewritten text.\n\nOriginal: ${ep.content}`;
					const modelId = "gemini-2.0-flash";
					const aiResult = (await Promise.race([
						genAI.models.generateContent({
							model: modelId,
							contents: rewritePrompt,
						}),
						new Promise((_, reject) =>
							setTimeout(() => reject(new Error("timeout")), 10000),
						),
					])) as {
						text?: string | undefined;
						usageMetadata?:
							| {
									promptTokenCount?: number | undefined;
									candidatesTokenCount?: number | undefined;
							  }
							| undefined;
					};
					const usage = aiResult.usageMetadata;
					if (usage) {
						trackAICost(
							"platform",
							usage.promptTokenCount ?? 0,
							usage.candidatesTokenCount ?? 0,
							modelId,
							"evergreen_recycle_queuefill",
							"env_fallback",
						).catch(() => {});
					}
					const rewritten = (aiResult.text ?? "").trim();
					if (
						rewritten &&
						rewritten.length >= 5 &&
						rewritten.length <= charLimit
					) {
						recycledContent = rewritten;
					}
				}
			} catch {
				// Use original content if AI fails
			}

			const scheduledTime = scheduleEvergreenItem(
				groupId,
				(1 + Math.random() * 6) * 3600000,
				scheduling ? { ...scheduling, platform } : undefined,
			);

			// Format transformation on recycle
			let recycledMediaUrls = ep.media_urls || null;
			let recycledMediaType = (ep.media_type as string) || null;
			if (
				platform === "instagram" &&
				recycledMediaUrls &&
				Array.isArray(recycledMediaUrls)
			) {
				if (
					recycledMediaType === "CAROUSEL_ALBUM" &&
					recycledMediaUrls.length > 1
				) {
					recycledMediaUrls = [recycledMediaUrls[0]];
					recycledMediaType = "IMAGE";
				}
			} else if (
				platform === "threads" &&
				recycledMediaUrls &&
				Math.random() < 0.3
			) {
				recycledMediaUrls = null;
				recycledMediaType = null;
			}

			const insertData: Record<string, unknown> = {
				workspace_id: workspaceId,
				content: recycledContent,
				status: "pending",
				scheduled_for: scheduledTime,
				predicted_viral_score: Math.min(
					90,
					Math.round(((ep.views_count as number) || 0) / 10),
				),
				source_type: "recycled",
				source_content: ep.content,
				media_urls: recycledMediaUrls,
				...(recycledMediaType ? { media_type: recycledMediaType } : {}),
				group_id: groupId,
			};

			try {
				const { error: evInsertErr } = await db()
					.from("auto_post_queue")
					.insert(insertData);
				if (!evInsertErr) {
					evergreenInsertCount++;
					// Update original's recycle tracking
					try {
						await db()
							.from("posts")
							.update({
								recycle_count: ((ep.recycle_count as number) || 0) + 1,
								last_recycled_at: new Date().toISOString(),
							})
							.eq("id", ep.id);
					} catch (trackErr) {
						logger.warn("Failed to update recycle tracking", {
							postId: ep.id,
							error:
								trackErr instanceof Error ? trackErr.message : String(trackErr),
						});
					}
					logger.info("Inserted evergreen recycled post into queue", {
						originalId: ep.id,
						views: ep.views_count,
						workspaceId,
						groupId,
					});
				} else {
					evergreenFailedCount++;
					evergreenErrors.push({
						postId: ep.id,
						error: String(evInsertErr),
					});
				}
			} catch (insertErr) {
				evergreenFailedCount++;
				evergreenErrors.push({
					postId: ep.id,
					error:
						insertErr instanceof Error ? insertErr.message : String(insertErr),
				});
			}
		}
	} catch (evErr) {
		// Non-blocking — evergreen integration is best-effort
		logger.warn("Evergreen queue integration failed", {
			error: evErr instanceof Error ? evErr.message : String(evErr),
		});
	}

	if (evergreenFailedCount > 0) {
		logger.warn("Evergreen recycling had failures", {
			inserted: evergreenInsertCount,
			failed: evergreenFailedCount,
			errors: evergreenErrors,
			workspaceId,
			groupId,
		});
	}

	return {
		insertCount: evergreenInsertCount,
		failedCount: evergreenFailedCount,
		errors: evergreenErrors,
	};
}
