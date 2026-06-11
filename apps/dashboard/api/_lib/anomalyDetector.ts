// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
// Meta Platform Terms: Do not send exact API metrics to third-party AI services
/**
 * Anomaly Detection Engine
 *
 * Analyzes account analytics to detect shadowbans, engagement drops,
 * and follower anomalies. Generates AI-powered analysis via Gemini.
 */

import { createNotification } from "./createNotification.js";
import { logger } from "./logger.js";
import type { MetricDataPoint } from "./metricDeviationEngine.js";
import { DEVIATION_PRESETS, detectDeviation } from "./metricDeviationEngine.js";
import type { Platform } from "./platform.js";
import { describeEngagementRate, sanitizeMetrics } from "./sanitizeForAI.js";
import { getSupabase } from "./supabase.js";

const db = () => getSupabase();

// ============================================================================
// Types
// ============================================================================

interface AnomalyAlert {
	user_id: string;
	account_id?: string | undefined;
	instagram_account_id?: string | undefined;
	platform: Platform;
	alert_type:
		| "shadowban_suspected"
		| "engagement_drop"
		| "reach_anomaly"
		| "follower_drop";
	severity: "low" | "medium" | "high" | "critical";
	title: string;
	description: string;
	data: Record<string, unknown>;
}

interface AnalyticsRow {
	date: string;
	followers_count: number | null;
	total_views: number | null;
	total_likes: number | null;
	total_replies: number | null;
	total_reposts: number | null;
	total_shares: number | null;
	total_reach: number | null;
	engagement_rate: number | null;
	follower_growth: number | null;
	ig_reach: number | null;
}

// ============================================================================
// Main Detection
// ============================================================================

export async function detectAnomalies(
	accountId: string,
	platform: Platform,
	userId: string,
): Promise<void> {
	try {
		// account_analytics uses account_id for all platforms (Threads + IG)

		// Query last 14 days of analytics
		const fourteenDaysAgo = new Date();
		fourteenDaysAgo.setDate(fourteenDaysAgo.getDate() - 14);
		const cutoff = fourteenDaysAgo.toISOString().split("T")[0]!;

		const { data: rows, error } = (await db()
			.from("account_analytics")
			.select(
				"date, followers_count, total_views, total_likes, total_replies, total_reposts, total_shares, total_reach, engagement_rate, follower_growth, ig_reach",
			)
			.eq("account_id", accountId)
			.gte("date", cutoff)
			.order("date", { ascending: true })) as {
			data: AnalyticsRow[] | null;
			error: { message?: string | undefined } | null;
		};

		if (error || !rows) {
			logger.warn("Anomaly detection: failed to fetch analytics", {
				accountId,
				error: error?.message,
			});
			return;
		}

		// Edge case: not enough baseline data
		if (rows.length < 14) {
			logger.info("Anomaly detection: skipping, insufficient data", {
				accountId,
				days: rows.length,
			});
			return;
		}

		// Edge case: skip empty / brand-new accounts that have no signal yet.
		// The 100-follower gate was a copy from a personal-creator dashboard
		// and made the whole feature silently dead for creator-growth fleets
		// (every account in this product is in the 0–50 follower range while
		// it ramps). Use a much lower floor that still rejects accounts where
		// any reach drop is just noise.
		const latestFollowers = rows[rows.length - 1]?.followers_count ?? 0;
		const MIN_FOLLOWERS_FOR_ANOMALY_DETECTION = 5;
		if (latestFollowers < MIN_FOLLOWERS_FOR_ANOMALY_DETECTION) {
			logger.info("Anomaly detection: skipping, no signal yet", {
				accountId,
				followers: latestFollowers,
			});
			return;
		}

		const alerts: AnomalyAlert[] = [];

		// ── Build metric data points for the deviation engine ──
		const baselineRows = rows.slice(0, -3);
		const recentRows = rows.slice(-3);

		// Reach/followers ratio — detect shadowban via the deviation engine
		const reachRatioPoints: MetricDataPoint[] = baselineRows
			.map((r) => {
				const reach =
					platform === "instagram"
						? (r.ig_reach ?? r.total_reach ?? r.total_views ?? 0)
						: (r.total_views ?? 0);
				const followers = r.followers_count ?? 1;
				return { date: r.date, value: followers > 0 ? reach / followers : 0 };
			})
			.filter((dp) => dp.value > 0);

		if (reachRatioPoints.length >= 7) {
			// Use the average of recent 3 days as the "current" value
			const recentRatios = recentRows.map((r) => {
				const reach =
					platform === "instagram"
						? (r.ig_reach ?? r.total_reach ?? r.total_views ?? 0)
						: (r.total_views ?? 0);
				const followers = r.followers_count ?? 1;
				return followers > 0 ? reach / followers : 0;
			});
			const recentAvgRatio =
				recentRatios.length > 0
					? recentRatios.reduce((a, b) => a + b, 0) / recentRatios.length
					: 0;

			const shadowbanResult = detectDeviation(
				reachRatioPoints,
				recentAvgRatio,
				{ ...DEVIATION_PRESETS.shadowban, minDataPoints: 7 },
			);

			// #631: Require statistical detection — legacy heuristic alone caused false positives
			if (shadowbanResult.severity !== "none") {
				const dropPct = Math.round(Math.abs(shadowbanResult.percentChange));
				alerts.push({
					user_id: userId,
					...(platform === "instagram"
						? { instagram_account_id: accountId }
						: { account_id: accountId }),
					platform,
					alert_type: "shadowban_suspected",
					severity: "high",
					title: "⚠️ Possible Shadowban Detected",
					description: `Your reach-to-followers ratio has dropped ${dropPct}% over the last 3 days compared to your 14-day baseline. This pattern is consistent with reduced content distribution.`,
					data: {
						avgReachRatio: shadowbanResult.baselineAvg,
						recentRatios,
						dropPct,
						baselineDays: baselineRows.length,
						deviationScore: shadowbanResult.deviationScore,
					},
				});
			}
		}

		// Engagement rate — detect drops via the deviation engine
		const engRatePoints: MetricDataPoint[] = baselineRows
			.map((r) => ({ date: r.date, value: r.engagement_rate ?? 0 }))
			.filter((dp) => dp.value > 0);

		if (engRatePoints.length >= 7) {
			const recentAvgEng =
				recentRows.reduce((s, r) => s + (r.engagement_rate ?? 0), 0) /
				recentRows.length;

			const engResult = detectDeviation(engRatePoints, recentAvgEng, {
				...DEVIATION_PRESETS.engagementDrop,
				minDataPoints: 7,
			});

			if (engResult.severity !== "none") {
				const dropPct = Math.round(Math.abs(engResult.percentChange));
				alerts.push({
					user_id: userId,
					...(platform === "instagram"
						? { instagram_account_id: accountId }
						: { account_id: accountId }),
					platform,
					alert_type: "engagement_drop",
					severity: "medium",
					title: "📉 Engagement Rate Drop",
					description: `Your engagement rate has dropped ${dropPct}% from your 14-day average (${engResult.baselineAvg.toFixed(2)}% → ${recentAvgEng.toFixed(2)}%).`,
					data: {
						avgEngRate: engResult.baselineAvg,
						recentAvgEng,
						dropPct,
						deviationScore: engResult.deviationScore,
					},
				});
			}
		}

		// Follower drop — detect via the deviation engine (day-over-day)
		const followerPoints: MetricDataPoint[] = rows
			.filter((r) => r.followers_count != null && r.followers_count > 0)
			.map((r) => ({ date: r.date, value: r.followers_count ?? 0 }));

		if (followerPoints.length >= 2) {
			// Check each day-over-day transition for significant drops
			for (let i = 1; i < followerPoints.length; i++) {
				const prev = followerPoints[i - 1]!.value;
				const curr = followerPoints[i]!.value;
				const dayDropPct = ((prev - curr) / prev) * 100;

				if (dayDropPct > 5) {
					// Also validate via the engine for richer metadata
					const followerResult = detectDeviation(
						followerPoints.slice(0, i),
						curr,
						{ ...DEVIATION_PRESETS.followerDrop, minDataPoints: 2 },
					);

					alerts.push({
						user_id: userId,
						...(platform === "instagram"
							? { instagram_account_id: accountId }
							: { account_id: accountId }),
						platform,
						alert_type: "follower_drop",
						severity: "medium",
						title: "📉 Significant Follower Drop",
						description: `You lost ${prev - curr} followers (${dayDropPct.toFixed(1)}%) on ${followerPoints[i]!.date}.`,
						data: {
							date: followerPoints[i]!.date,
							previousCount: prev,
							currentCount: curr,
							dropPct: dayDropPct,
							deviationScore: followerResult.deviationScore,
						},
					});
					break; // Only flag the most recent drop
				}
			}
		}

		// ── Composite Health Score (Analytics Intelligence 2026, Section 1) ──
		// Health = 0.30×reach_trend + 0.25×save_trend + 0.25×share_trend + 0.15×comment_trend + 0.05×like_trend
		// When composite drops >20% below 30-day baseline → predict decline with 14-21 day lead time
		if (rows.length >= 7) {
			const reachTrend = (() => {
				const baseline =
					baselineRows.reduce(
						(s, r) =>
							s +
							((platform === "instagram"
								? (r.ig_reach ?? r.total_reach ?? 0)
								: (r.total_views ?? 0)) as number),
						0,
					) / (baselineRows.length || 1);
				const recent =
					recentRows.reduce(
						(s, r) =>
							s +
							((platform === "instagram"
								? (r.ig_reach ?? r.total_reach ?? 0)
								: (r.total_views ?? 0)) as number),
						0,
					) / (recentRows.length || 1);
				return baseline > 0 ? recent / baseline : 1;
			})();
			const shareTrend = (() => {
				const baseline =
					baselineRows.reduce(
						(s, r) => s + ((r.total_shares ?? r.total_reposts ?? 0) as number),
						0,
					) / (baselineRows.length || 1);
				const recent =
					recentRows.reduce(
						(s, r) => s + ((r.total_shares ?? r.total_reposts ?? 0) as number),
						0,
					) / (recentRows.length || 1);
				return baseline > 0 ? recent / baseline : 1;
			})();
			const commentTrend = (() => {
				const baseline =
					baselineRows.reduce(
						(s, r) => s + ((r.total_replies ?? 0) as number),
						0,
					) / (baselineRows.length || 1);
				const recent =
					recentRows.reduce(
						(s, r) => s + ((r.total_replies ?? 0) as number),
						0,
					) / (recentRows.length || 1);
				return baseline > 0 ? recent / baseline : 1;
			})();
			const likeTrend = (() => {
				const baseline =
					baselineRows.reduce(
						(s, r) => s + ((r.total_likes ?? 0) as number),
						0,
					) / (baselineRows.length || 1);
				const recent =
					recentRows.reduce((s, r) => s + ((r.total_likes ?? 0) as number), 0) /
					(recentRows.length || 1);
				return baseline > 0 ? recent / baseline : 1;
			})();

			// Save trend approximated from likes (saves not separately tracked in account_analytics)
			const saveTrend = likeTrend; // Proxy — save rate correlates with like rate

			const healthScore =
				0.3 * reachTrend +
				0.25 * saveTrend +
				0.25 * shareTrend +
				0.15 * commentTrend +
				0.05 * likeTrend;

			// Alert when health drops >20% below baseline (healthScore < 0.80)
			if (healthScore < 0.8) {
				const dropPct = Math.round((1 - healthScore) * 100);
				alerts.push({
					user_id: userId,
					...(platform === "instagram"
						? { instagram_account_id: accountId }
						: { account_id: accountId }),
					platform,
					alert_type: "reach_anomaly",
					severity: healthScore < 0.5 ? "critical" : "high",
					title: "📊 Account Health Declining",
					description: `Composite health score dropped ${dropPct}% below baseline. Reach (${Math.round(reachTrend * 100)}%), shares (${Math.round(shareTrend * 100)}%), comments (${Math.round(commentTrend * 100)}%) all trending down. This predicts continued decline in 14-21 days without intervention.`,
					data: {
						healthScore: Math.round(healthScore * 100) / 100,
						reachTrend: Math.round(reachTrend * 100),
						shareTrend: Math.round(shareTrend * 100),
						commentTrend: Math.round(commentTrend * 100),
						likeTrend: Math.round(likeTrend * 100),
					},
				});

				// Auto-pause autoposter for this account if severe (>50% drop for 3+ days)
				// Analytics Intelligence 2026 Section 7: auto-pause prevents further damage
				if (healthScore < 0.5) {
					try {
						const accountField =
							platform === "instagram" ? "instagram_account_id" : "account_id";
						await db()
							.from(
								platform === "instagram" ? "instagram_accounts" : "accounts",
							)
							.update({ is_active: false })
							.eq("id", accountId);
						logger.warn(
							"[anomalyDetector] Auto-paused account due to severe health decline",
							{
								accountId,
								healthScore,
								accountField,
							},
						);
					} catch {
						// Non-critical — alert still fires
					}
				}
			}
		}

		// ── Insert alerts (deduplicate) ──
		for (const alert of alerts) {
			await insertAlertIfNew(alert, accountId, platform);
		}
	} catch (err) {
		logger.warn("Anomaly detection failed", {
			accountId,
			platform,
			error: String(err),
		});
	}
}

// ============================================================================
// Dedup + Insert
// ============================================================================

async function insertAlertIfNew(
	alert: AnomalyAlert,
	accountId: string,
	platform: Platform,
): Promise<void> {
	// #636: Increased dedup window from 7 to 14 days so persistent issues
	// aren't re-flagged too quickly
	const fourteenDaysAgo = new Date();
	fourteenDaysAgo.setDate(fourteenDaysAgo.getDate() - 14);

	// Check for existing undismissed alert of same type for this account
	let query = db()
		.from("anomaly_alerts")
		.select("id")
		.eq("alert_type", alert.alert_type)
		.is("dismissed_at", null)
		.gte("created_at", fourteenDaysAgo.toISOString());

	if (platform === "instagram") {
		query = query.eq("instagram_account_id", accountId);
	} else {
		query = query.eq("account_id", accountId);
	}

	const { data: existing } = await query.limit(1);
	if (existing && existing.length > 0) {
		logger.info("Anomaly alert already exists, skipping", {
			alertType: alert.alert_type,
			accountId,
		});
		return;
	}

	// Insert the alert
	const { error } = await db()
		.from("anomaly_alerts")
		// biome-ignore lint/suspicious/noExplicitAny: AnomalyAlert has dynamic account_id fields
		.insert(alert as any);
	if (error) {
		logger.warn("Failed to insert anomaly alert", {
			error: error.message,
			alertType: alert.alert_type,
		});
		return;
	}

	logger.info("Anomaly alert created", {
		alertType: alert.alert_type,
		severity: alert.severity,
		accountId,
	});

	// Create in-app notification
	await createNotification({
		userId: alert.user_id,
		type: `anomaly_${alert.alert_type}`,
		title: alert.title,
		message: alert.description,
		data: { alertType: alert.alert_type, platform, accountId },
	});

	// Generate AI analysis asynchronously (non-blocking)
	generateAIAnalysis(alert, accountId, platform).catch((err) => {
		logger.warn("AI analysis generation failed", { error: String(err) });
	});
}

// ============================================================================
// AI Analysis via Gemini
// ============================================================================

export async function generateAIAnalysis(
	alert: AnomalyAlert,
	accountId: string,
	platform: Platform,
): Promise<void> {
	try {
		// Fetch recent posts for context
		const postQuery =
			platform === "instagram"
				? db()
						.from("posts")
						.select(
							"content, published_at, engagement_rate, ig_reach, likes_count",
						)
						.eq("instagram_account_id", accountId)
						.eq("platform", "instagram")
						.order("published_at", { ascending: false })
						.limit(10)
				: db()
						.from("posts")
						.select(
							"content, published_at, engagement_rate, views_count, likes_count",
						)
						.eq("account_id", accountId)
						.order("published_at", { ascending: false })
						.limit(10);

		const { data: recentPosts } = await postQuery;

		// Sanitize metrics: use relative descriptions instead of exact Meta API numbers
		const sanitizedMetrics =
			alert.data && typeof alert.data === "object"
				? sanitizeMetrics(alert.data as Record<string, number>)
				: "No metrics available";

		const prompt = `You are a social media analytics expert. Analyze this anomaly detected on a ${platform} account and provide actionable insights.

ALERT TYPE: ${alert.alert_type}
SEVERITY: ${alert.severity}
DESCRIPTION: ${alert.description}

METRICS SUMMARY:
${sanitizedMetrics}

RECENT POSTS (last 10):
${recentPosts?.map((p: { content?: string | null | undefined; engagement_rate?: number | null | undefined; published_at?: string | null | undefined }) => `- "${(p.content || "").substring(0, 100)}..." | Engagement: ${describeEngagementRate(p.engagement_rate ?? 0)} | ${p.published_at}`).join("\n") || "No recent posts found"}

Analyze the situation and provide exactly 3 ranked hypotheses for what's causing this issue. For each hypothesis, include:
1. The likely cause
2. Evidence from the data
3. A specific, actionable fix

Format as a concise numbered list. Be specific and reference the actual numbers. Keep total response under 500 words.`;

		// Use the server-side Gemini call pattern
		const { GoogleGenAI } = await import("@google/genai");
		const apiKey = process.env.GEMINI_API_KEY || process.env.GOOGLE_AI_API_KEY;
		if (!apiKey) {
			logger.warn("No Gemini API key configured, skipping AI analysis");
			return;
		}

		// Daily platform spend cap — bail before any token cost.
		const { checkDailySpendLimit, trackAICost } = await import(
			"./aiCostTracker.js"
		);
		const { allowed } = await checkDailySpendLimit();
		if (!allowed) {
			logger.warn(
				"[anomalyDetector] AI analysis skipped — daily spend limit reached",
			);
			return;
		}

		const modelId = "gemini-2.0-flash";
		const genai = new GoogleGenAI({ apiKey });
		const response = await genai.models.generateContent({
			model: modelId,
			contents: prompt,
		});

		const analysisText = response.text ?? "";
		if (!analysisText) return;

		// Attribute platform-key spend so the daily cap can enforce it next call.
		const usage = (
			response as { usageMetadata?: { promptTokenCount?: number | undefined; candidatesTokenCount?: number | undefined } | undefined }
		).usageMetadata;
		if (usage) {
			trackAICost(
				"platform",
				usage.promptTokenCount ?? 0,
				usage.candidatesTokenCount ?? 0,
				modelId,
				"anomaly_analysis",
				"env_fallback",
			).catch(() => {});
		}

		// Update the alert with AI analysis
		// Find the most recent alert of this type for this account
		let findQuery = db()
			.from("anomaly_alerts")
			.select("id")
			.eq("alert_type", alert.alert_type)
			.is("dismissed_at", null)
			.order("created_at", { ascending: false })
			.limit(1);

		if (platform === "instagram") {
			findQuery = findQuery.eq("instagram_account_id", accountId);
		} else {
			findQuery = findQuery.eq("account_id", accountId);
		}

		const { data: alertRow } = await findQuery;
		if (alertRow && alertRow.length > 0) {
			await db()
				.from("anomaly_alerts")
				.update({ ai_analysis: analysisText })
				.eq("id", alertRow[0]!.id);

			logger.info("AI analysis stored for anomaly alert", {
				alertId: alertRow[0]!.id,
			});
		}
	} catch (err) {
		logger.warn("generateAIAnalysis error", { error: String(err) });
	}
}
