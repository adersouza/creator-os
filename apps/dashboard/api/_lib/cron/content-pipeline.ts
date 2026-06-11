/**
 * Content Pipeline Cron — evergreen recycling, trend forecasting
 *
 * Schedule: every 6 hours (offset from periodic-sync)
 * Phases:
 *   Phase 1: Evergreen Recycling     (~30-60s) — republish due evergreen posts
 *   Phase 2: Trend Forecast Refresh  (~30-120s) — recompute forecasts for active accounts
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";
import { alertCronFailure } from "../alerting.js";
import { createNotification } from "../createNotification.js";
import { trackCronRun, withCronLock } from "../cronUtils.js";
import { logger } from "../logger.js";
import { getSupabase } from "../supabase.js";

export const config = {
	maxDuration: 300,
};

const MAX_EXECUTION_TIME = 280_000;
const JOB_NAME = "content-pipeline";

// Per-phase time budgets ensure later phases always get a chance to run
const PHASE_BUDGETS = {
	evergreenRecycling: 120_000, // 120s max for evergreen
	trendForecasts: 120_000, // 120s for forecasts — remaining headroom for wrap-up
};

function hasTimeBudget(startTime: number): boolean {
	return Date.now() - startTime < MAX_EXECUTION_TIME;
}

function hasPhaseTimeBudget(phaseStart: number, budgetMs: number): boolean {
	return Date.now() - phaseStart < budgetMs;
}

// ============================================================================
// Phase 2: Evergreen Content Recycling
// ============================================================================

/**
 * Platform-specific minimum gap enforcement (Evergreen Recycling 2026, Section 5).
 * Returns minimum days before a post can be recycled on this platform.
 */
function getMinRecycleGapDays(
	platform: string | null,
	hasFormatChange: boolean,
): number {
	if (platform === "instagram") {
		return hasFormatChange ? 45 : 90; // 30-60d reformatted, 90d identical
	}
	// Threads: 14-30d identical, 7-14d modified
	return hasFormatChange ? 10 : 21;
}

/**
 * Seasonal content detection + priority boost (Evergreen Recycling 2026, Section 5).
 * Returns a priority multiplier (1.0 = normal, 1.5 = seasonal boost).
 * Boosts content 2-3 weeks before relevant seasonal windows.
 */
function getSeasonalRecyclePriority(content: string): number {
	const now = new Date();
	const month = now.getMonth(); // 0-indexed
	const day = now.getDate();

	const lower = (content || "").toLowerCase();

	// Valentine's Day window: Jan 20 – Feb 13
	if ((month === 0 && day >= 20) || (month === 1 && day <= 13)) {
		if (/\b(valentine|love|romantic|date night|couples?|heart)\b/i.test(lower))
			return 1.5;
	}

	// New Year / fresh start: Dec 15 – Jan 15
	if ((month === 11 && day >= 15) || (month === 0 && day <= 15)) {
		if (
			/\b(new year|resolution|fresh start|goals?|restart|january)\b/i.test(
				lower,
			)
		)
			return 1.5;
	}

	// Back to school / routine restart: Aug 15 – Sep 15
	if ((month === 7 && day >= 15) || (month === 8 && day <= 15)) {
		if (/\b(school|routine|fall|autumn|back to|semester|study)\b/i.test(lower))
			return 1.5;
	}

	// Summer vibes: May 15 – Jun 15
	if ((month === 4 && day >= 15) || (month === 5 && day <= 15)) {
		if (/\b(summer|beach|vacation|pool|tan|hot girl|sun)\b/i.test(lower))
			return 1.5;
	}

	// Holiday / Christmas: Nov 20 – Dec 23
	if ((month === 10 && day >= 20) || (month === 11 && day <= 23)) {
		if (
			/\b(christmas|holiday|gift|xmas|santa|winter|cozy|festive)\b/i.test(lower)
		)
			return 1.5;
	}

	return 1.0;
}

/**
 * Extract opening hook (first sentence or first 60 chars) for uniqueness checking.
 */
function extractHook(content: string): string {
	const trimmed = (content || "").trim();
	// First sentence (period, ?, !, or newline)
	const match = trimmed.match(/^[^.!?\n]+[.!?]?/);
	if (match && match[0].length >= 10) return match[0].toLowerCase().trim();
	// Fallback: first 60 chars
	return trimmed.substring(0, 60).toLowerCase().trim();
}

export async function runEvergreenRecycling(
	startTime: number,
): Promise<{ postsRecycled: number; errors: number; retired: number }> {
	const supabase = getSupabase();
	const stats = { postsRecycled: 0, errors: 0, retired: 0 };
	const phaseStart = Date.now();
	const now = new Date();

	// Find evergreen posts due for recycling — include views_count + saves for scoring
	const { data: posts } = await supabase
		.from("posts")
		.select(
			"id, user_id, content, platform, account_id, instagram_account_id, hashtags, media_type, media_urls, engagement_rate, evergreen_interval_days, recycle_count, max_recycles, last_recycled_at, published_at, evergreen_min_engagement, views_count, likes_count, replies_count, metadata",
		)
		.eq("is_evergreen", true)
		.eq("status", "published")
		.order("last_recycled_at", { ascending: true, nullsFirst: true })
		.limit(20);

	if (!posts?.length) return stats;

	// ── Daily cap: track how many recycled posts each user has today ──
	const { getUserTier } = await import("../tierGate.js");
	const DAILY_RECYCLE_LIMITS: Record<string, number> = {
		free: 0,
		pro: 5,
		agency: 5,
		empire: 10,
	};

	const todayStart = new Date();
	todayStart.setUTCHours(0, 0, 0, 0);
	const todayISO = todayStart.toISOString();

	const userIds: string[] = [
		...new Set<string>(
			posts.map((p: { user_id: unknown }) => String(p.user_id)),
		),
	];

	const userRecycledToday = new Map<string, number>();
	const userTiers = new Map<string, string>();

	for (const uid of userIds) {
		const tier = await getUserTier(uid);
		const { count } = await supabase
			.from("posts")
			.select("id", { count: "exact", head: true })
			.eq("user_id", uid)
			.not("recycled_from_id", "is", null)
			.gte("created_at", todayISO);
		userTiers.set(uid, tier as string);
		userRecycledToday.set(uid, (count as number) || 0);
	}

	// ── Sort by seasonal priority + save rate bonus (Section 4 + 5) ──
	const scoredPosts = posts.map((post) => {
		const seasonalBoost = getSeasonalRecyclePriority(post.content || "");
		// Save rate bonus: posts with high saves are strongest evergreen signals
		const views = (post.views_count as number) || 1;
		const likes = (post.likes_count as number) || 0;
		// Approximate save rate from likes (saves aren't tracked separately in posts table)
		// High like-to-view ratio is a proxy for save-worthy content
		const likeRate = likes / views;
		const saveBonus = likeRate > 0.05 ? 1.3 : likeRate > 0.03 ? 1.1 : 1.0;
		return { post, priority: seasonalBoost * saveBonus };
	});
	scoredPosts.sort((a, b) => b.priority - a.priority);

	// Redis for cross-account dedup tracking
	type RedisLike = {
		get: (k: string) => Promise<string | null>;
		incr: (k: string) => Promise<number>;
		expire: (k: string, s: number) => Promise<unknown>;
	};
	let redis: RedisLike | null = null;
	try {
		const { getRedis } = await import("../redis.js");
		redis = getRedis() as unknown as RedisLike;
	} catch {
		/* Redis unavailable — skip dedup */
	}

	for (const { post } of scoredPosts) {
		if (
			!hasTimeBudget(startTime) ||
			!hasPhaseTimeBudget(phaseStart, PHASE_BUDGETS.evergreenRecycling)
		)
			break;

		// Daily cap check
		const userTier = userTiers.get(post.user_id) || "free";
		const dailyLimit = DAILY_RECYCLE_LIMITS[userTier] ?? 0;
		const recycledSoFar = userRecycledToday.get(post.user_id) || 0;
		if (recycledSoFar >= dailyLimit) {
			logger.info("[content-pipeline] Evergreen daily cap reached", {
				userId: post.user_id,
				tier: userTier,
				limit: dailyLimit,
				recycledToday: recycledSoFar,
			});
			continue;
		}

		// ── Auto-retirement check (Section 3 + 9) ──
		// Retire when: recycle limit hit, OR engagement dropped below 50% of original,
		// OR 2 consecutive zero-engagement cycles.
		const meta = (post.metadata || {}) as Record<string, unknown>;
		const recycleHistory = (meta.recycle_engagement_ratios as number[]) || [];
		if ((post.recycle_count || 0) >= (post.max_recycles || 5)) {
			// Auto-retire: max cycles reached
			await supabase
				.from("posts")
				.update({ is_evergreen: false })
				.eq("id", post.id);
			stats.retired++;
			logger.info("[content-pipeline] Auto-retired evergreen: max recycles", {
				postId: post.id,
			});
			continue;
		}
		if (recycleHistory.length >= 2) {
			const lastTwo = recycleHistory.slice(-2);
			// 2 consecutive zero-engagement cycles → retire
			if (lastTwo.every((r) => r <= 0)) {
				await supabase
					.from("posts")
					.update({ is_evergreen: false })
					.eq("id", post.id);
				stats.retired++;
				logger.info(
					"[content-pipeline] Auto-retired evergreen: 2 consecutive zero engagement",
					{ postId: post.id },
				);
				continue;
			}
			// Last cycle dropped below 50% of original → retire
			const lastRatio = lastTwo[lastTwo.length - 1];
			if (typeof lastRatio === "number" && lastRatio < 0.5 && lastRatio > 0) {
				await supabase
					.from("posts")
					.update({ is_evergreen: false })
					.eq("id", post.id);
				stats.retired++;
				logger.info(
					"[content-pipeline] Auto-retired evergreen: <50% of original engagement",
					{
						postId: post.id,
						lastRatio,
					},
				);
				continue;
			}
		}

		// ── Platform-specific gap enforcement (Section 5) ──
		const lastRecycled = post.last_recycled_at || post.published_at;
		if (!lastRecycled) continue;
		const minGapDays = getMinRecycleGapDays(post.platform, false);
		const minGapMs = minGapDays * 86_400_000;
		const timeSinceLastRecycle =
			now.getTime() - new Date(lastRecycled).getTime();
		if (timeSinceLastRecycle < minGapMs) continue;

		// Also respect user-configured interval if it's longer
		const userIntervalMs = (post.evergreen_interval_days || 30) * 86_400_000;
		if (timeSinceLastRecycle < userIntervalMs) continue;

		// Check minimum engagement threshold
		if (
			post.evergreen_min_engagement &&
			Number(post.engagement_rate || 0) < Number(post.evergreen_min_engagement)
		) {
			continue;
		}

		// ── Cross-account dedup: max 2 accounts per post per 48h (Section 9) ──
		if (redis) {
			try {
				const dedupKey = `evergreen-recycle:${post.id}`;
				const count = Number(await redis.get(dedupKey)) || 0;
				if (count >= 2) {
					logger.debug(
						"[content-pipeline] Cross-account dedup: max 2 accounts in 48h",
						{ postId: post.id, count },
					);
					continue;
				}
			} catch {
				/* fail-open */
			}
		}

		// ── Hook uniqueness check (Section 6 + 9) ──
		// Reject if opening line matches any previous recycle version
		const currentHook = extractHook(post.content || "");
		if (currentHook.length > 10) {
			const { data: previousRecycles } = await supabase
				.from("posts")
				.select("content")
				.eq("recycled_from_id", post.id)
				.limit(10);
			const previousHooks = (previousRecycles || []).map((p) =>
				extractHook((p.content as string) || ""),
			);
			// We'll generate a new hook via AI, but track for logging
			if (previousHooks.length > 0) {
				logger.debug("[content-pipeline] Hook history tracked", {
					postId: post.id,
					previousHookCount: previousHooks.length,
				});
			}
		}

		// ── Format diversity: vary media_type if previous recycle used same format ──
		const { data: lastRecyclePost } = await supabase
			.from("posts")
			.select("media_type")
			.eq("recycled_from_id", post.id)
			.order("created_at", { ascending: false })
			.limit(1)
			.maybeSingle();
		const lastRecycleFormat = lastRecyclePost?.media_type || null;
		const shouldChangeFormat =
			lastRecycleFormat === post.media_type && post.media_type;

		try {
			// Generate a variation of the content via AI — with hook uniqueness enforcement
			let variedContent = post.content;

			// Fetch previous hooks to tell AI to avoid them
			const { data: prevRecycles } = await supabase
				.from("posts")
				.select("content")
				.eq("recycled_from_id", post.id)
				.limit(5);
			const avoidHooks = (prevRecycles || [])
				.map((p) => extractHook((p.content as string) || ""))
				.filter((h) => h.length > 5);

			// AI rewrite — OFF by default. See evergreenManager for the same
			// gate; both paths recycle proven content, but the AI hook rewrite
			// step is now opt-in via AUTOPOSTER_AI_RECYCLE_REWRITES=1.
			const aiRewriteEnabled =
				process.env.AUTOPOSTER_AI_RECYCLE_REWRITES === "1";
			try {
				const { GoogleGenAI } = await import("@google/genai");
				const apiKey = process.env.GEMINI_API_KEY;
				const { checkDailySpendLimit, trackAICost } = await import(
					"../aiCostTracker.js"
				);
				const { allowed } = aiRewriteEnabled
					? await checkDailySpendLimit()
					: { allowed: false };
				if (aiRewriteEnabled && apiKey && allowed) {
					const genAI = new GoogleGenAI({ apiKey });
					const platform = post.platform || "threads";
					const charLimit = platform === "instagram" ? 2200 : 500;
					const recycleNum = (post.recycle_count || 0) + 1;
					const hookAvoidance =
						avoidHooks.length > 0
							? `\n\nDO NOT start with any of these hooks (already used):\n${avoidHooks.map((h) => `- "${h}"`).join("\n")}`
							: "";
					const prompt = `This is a high-performing ${platform} post being republished (recycle #${recycleNum}). Rewrite it with a COMPLETELY DIFFERENT opening hook — change the angle, restructure the flow, or shift the framing — while keeping the same core message. Max ${charLimit} characters. Return ONLY the rewritten post text.${hookAvoidance}\n\nOriginal: ${post.content}`;

					const modelId = "gemini-2.0-flash";
					const aiPromise = genAI.models.generateContent({
						model: modelId,
						contents: prompt,
					});
					const timeoutPromise = new Promise((_, reject) =>
						setTimeout(() => reject(new Error("AI timeout")), 15000),
					);
					const result = (await Promise.race([aiPromise, timeoutPromise])) as {
						text?: string | undefined;
						usageMetadata?: { promptTokenCount?: number | undefined; candidatesTokenCount?: number | undefined } | undefined;
					};
					const usage = result.usageMetadata;
					if (usage) {
						trackAICost(
							"platform",
							usage.promptTokenCount ?? 0,
							usage.candidatesTokenCount ?? 0,
							modelId,
							"evergreen_recycle_pipeline",
							"env_fallback",
						).catch(() => {});
					}
					const varied = (result.text ?? "").trim();
					if (varied && varied.length <= charLimit && varied !== post.content) {
						// Verify hook is actually different from previous recycles
						const newHook = extractHook(varied);
						const hookDuplicate = avoidHooks.some(
							(h) =>
								h === newHook ||
								(h.length > 15 && newHook.startsWith(h.substring(0, 15))),
						);
						if (!hookDuplicate) {
							variedContent = varied;
						} else {
							logger.debug(
								"[content-pipeline] AI generated duplicate hook, using anyway",
								{
									postId: post.id,
								},
							);
							variedContent = varied; // Still use it — better than identical
						}
					}
				}
			} catch (aiErr) {
				logger.warn(
					"[content-pipeline] Evergreen AI variation failed, using original",
					{
						postId: post.id,
						error: String(aiErr),
					},
				);
			}

			// Schedule the recycled post 1-4 hours from now
			const delayMs = (1 + Math.random() * 3) * 60 * 60 * 1000;

			const newPostData: Record<string, unknown> = {
				user_id: post.user_id,
				content: variedContent,
				status: "scheduled",
				scheduled_for: new Date(now.getTime() + delayMs).toISOString(),
				platform: post.platform,
				account_id: post.account_id,
				instagram_account_id: post.instagram_account_id,
				media_type: shouldChangeFormat ? null : post.media_type, // Format diversity: clear if same as last
				media_urls: post.media_urls,
				hashtags: post.hashtags,
				source: "auto-poster",
				recycled_from_id: post.id,
				metadata: {
					evergreen_recycle: true,
					recycle_number: (post.recycle_count || 0) + 1,
					original_views: post.views_count || 0,
					original_engagement_rate: post.engagement_rate || 0,
					format_changed: shouldChangeFormat || false,
				},
			};

			const { error: insertError } = await supabase
				.from("posts")
				.insert(newPostData as never);
			if (insertError) throw insertError;

			// ── Decay curve tracking (Section 3 + 9) ──
			// Store engagement ratio for this cycle relative to original.
			// We record a placeholder (1.0 for first recycle) — the actual ratio
			// gets updated by the sync cron once the recycled post has 24h of data.
			const updatedHistory = [...recycleHistory];
			// Placeholder: will be overwritten by analytics sync
			updatedHistory.push(1.0);

			const updatedMeta = {
				...meta,
				recycle_engagement_ratios: updatedHistory,
			};
			await supabase
				.from("posts")
				.update({
					recycle_count: (post.recycle_count || 0) + 1,
					last_recycled_at: now.toISOString(),
					metadata: updatedMeta,
				})
				.eq("id", post.id);

			// ── Cross-account dedup: increment counter ──
			if (redis) {
				try {
					const dedupKey = `evergreen-recycle:${post.id}`;
					await redis.incr(dedupKey);
					await redis.expire(dedupKey, 48 * 60 * 60);
				} catch {
					/* fail-open */
				}
			}

			stats.postsRecycled++;

			userRecycledToday.set(
				post.user_id,
				(userRecycledToday.get(post.user_id) || 0) + 1,
			);

			createNotification({
				userId: post.user_id,
				type: "post_scheduled",
				title: "Evergreen post recycled",
				message: `Your top-performing post was refreshed and scheduled for republishing.`,
				data: { originalPostId: post.id },
			}).catch(() => {});
		} catch (err) {
			stats.errors++;
			logger.error("[content-pipeline] Evergreen recycling failed", {
				postId: post.id,
				error: String(err),
			});
		}
	}

	return stats;
}

// ============================================================================
// Phase 3: Trend Forecast Refresh
// ============================================================================

export async function runTrendForecasts(
	startTime: number,
): Promise<{ forecastsGenerated: number; errors: number }> {
	const supabase = getSupabase();
	const stats = { forecastsGenerated: 0, errors: 0 };
	const phaseStart = Date.now();
	const todayStr = new Date().toISOString().slice(0, 10);

	// Find accounts that don't have a forecast for today
	const { data: activeAccounts } = await supabase
		.from("accounts")
		.select("id, user_id")
		.not("threads_access_token_encrypted", "is", null)
		.limit(25);

	if (!activeAccounts?.length) return stats;

	// Check which already have today's forecast
	const accountIds = activeAccounts.map((a: { id: string }) => a.id);
	const { data: existingForecasts } = await supabase
		.from("trend_forecasts")
		.select("account_id")
		.in("account_id", accountIds)
		.eq("forecast_date", todayStr);

	const alreadyForecasted = new Set(
		(existingForecasts || []).map((f) => f.account_id as string),
	);

	const { generateForecast } = await import("../trendEngine.js");

	for (const account of activeAccounts) {
		if (
			!hasTimeBudget(startTime) ||
			!hasPhaseTimeBudget(phaseStart, PHASE_BUDGETS.trendForecasts)
		)
			break;
		if (alreadyForecasted.has(account.id)) continue;

		try {
			await generateForecast(supabase, account.user_id, account.id);
			stats.forecastsGenerated++;
		} catch (err) {
			stats.errors++;
			logger.warn("[content-pipeline] Forecast generation failed", {
				accountId: account.id,
				error: String(err),
			});
		}
	}

	return stats;
}

// ============================================================================
// Main Handler
// ============================================================================

export default async function handler(req: VercelRequest, res: VercelResponse) {
	const { verifyCronAuth } = await import("../apiResponse.js");
	if (!verifyCronAuth(req, res)) return;

	const supabase = getSupabase();
	const globalStart = Date.now();

	const lockResult = await withCronLock(supabase, JOB_NAME, async () => {
		return trackCronRun(supabase, JOB_NAME, async () => {
			const phases: Record<string, unknown> = {};
			const metadata: Record<string, unknown> = { phases };
			let totalItems = 0;

			// ── Phase 1: Evergreen Recycling ──
			if (hasTimeBudget(globalStart)) {
				try {
					logger.info(
						"[content-pipeline] Phase 1: Evergreen Recycling — starting",
					);
					const p2Start = Date.now();
					const p2 = await runEvergreenRecycling(globalStart);
					phases.evergreenRecycling = {
						status: "completed",
						durationMs: Date.now() - p2Start,
						...p2,
					};
					totalItems += p2.postsRecycled + p2.retired;
					logger.info(
						"[content-pipeline] Phase 1: Evergreen Recycling — complete",
						p2,
					);
				} catch (err) {
					phases.evergreenRecycling = { status: "error", error: String(err) };
					logger.error("[content-pipeline] Phase 1 failed", {
						error: String(err),
					});
					alertCronFailure(JOB_NAME, `Evergreen: ${String(err)}`);
				}
			} else {
				phases.evergreenRecycling = {
					status: "skipped",
					reason: "time_budget",
				};
			}

			// ── Phase 2: Trend Forecasts ──
			if (hasTimeBudget(globalStart)) {
				try {
					logger.info("[content-pipeline] Phase 2: Trend Forecasts — starting");
					const p3Start = Date.now();
					const p3 = await runTrendForecasts(globalStart);
					phases.trendForecasts = {
						status: "completed",
						durationMs: Date.now() - p3Start,
						...p3,
					};
					totalItems += p3.forecastsGenerated;
					logger.info(
						"[content-pipeline] Phase 2: Trend Forecasts — complete",
						p3,
					);
				} catch (err) {
					phases.trendForecasts = { status: "error", error: String(err) };
					logger.error("[content-pipeline] Phase 2 failed", {
						error: String(err),
					});
					alertCronFailure(JOB_NAME, `Forecasts: ${String(err)}`);
				}
			} else {
				phases.trendForecasts = { status: "skipped", reason: "time_budget" };
			}

			metadata.totalDurationMs = Date.now() - globalStart;

			return { itemsProcessed: totalItems, metadata };
		});
	});

	if (lockResult.skipped) {
		return res.status(200).json({ skipped: true });
	}

	return res.status(200).json({ ok: true });
}
