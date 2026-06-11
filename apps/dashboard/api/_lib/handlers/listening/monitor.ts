/**
 * Social Listening Monitor — POST /api/listening/monitor
 *
 * Runs keyword checks against existing data (ig_comments, ig_mentions, threads_webhook_events).
 * Stores results and triggers notifications on threshold breaches.
 *
 * Body: { alert_id?: string, workspace_id?: string }
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";

// ============================================================================
// Row / API Types
// ============================================================================

interface IgCommentRow {
	id: string;
	text: string;
	username: string;
	created_at: string;
}

interface IgMentionRow {
	id: string;
	caption: string;
	username: string;
	mentioned_at: string;
}

interface ThreadsEventRow {
	id: string;
	payload: { text?: string | undefined; message?: string | undefined; from?: { username?: string | undefined } | undefined };
	created_at: string;
}

interface ListeningResultCountRow {
	result_count: number;
	checked_at: string;
}

interface SamplePost {
	id: string;
	text: string;
	author: string;
	timestamp: string;
	source: string;
}

import { apiError, apiSuccess } from "../../apiResponse.js";
import { createNotification } from "../../createNotification.js";
import { logger } from "../../logger.js";
import { withAuth } from "../../middleware.js";
import { checkRateLimit } from "../../rateLimiter.js";
import { analyzeSentiment } from "../../sentiment.js";
import { getSupabase } from "../../supabase.js";
import { verifyWorkspaceAccess } from "../../workspaceAccess.js";
import { z } from "../../zodCompat.js";

const bodySchema = z.object({
	alert_id: z.string().uuid().optional(),
	workspace_id: z.string().uuid().optional(),
});

export default withAuth(
	async (req: VercelRequest, res: VercelResponse, user) => {
		if (req.method !== "POST") return apiError(res, 405, "Method not allowed");

		// M5: Rate limit — 60 calls per 60 seconds per user
		const rl = await checkRateLimit({
			key: `listening-monitor:${user.id}`,
			limit: 60,
			windowSeconds: 60,
			failMode: "open",
		});
		if (!rl.allowed) {
			return apiError(res, 429, "Rate limit exceeded. Please wait a moment.");
		}

		const db = getSupabase();
		const parsed = bodySchema.safeParse(req.body || {});
		if (!parsed.success) {
			return apiError(res, 400, "Invalid request body");
		}
		const { alert_id, workspace_id } = parsed.data;

		// Validate workspace membership to prevent cross-tenant IDOR
		if (workspace_id) {
			const hasAccess = await verifyWorkspaceAccess(db, user.id, workspace_id);
			if (!hasAccess) {
				return apiError(res, 403, "Not authorized for this workspace");
			}
		}

		// Fetch alerts to process
		let alertQuery = db
			.from("listening_alerts")
			.select("*")
			.eq("user_id", user.id)
			.eq("is_active", true);

		if (alert_id) {
			alertQuery = alertQuery.eq("id", alert_id);
		} else if (workspace_id) {
			alertQuery = alertQuery.eq("workspace_id", workspace_id);
		}

		const { data: alerts, error: alertsErr } = await alertQuery;
		if (alertsErr) return apiError(res, 500, "Failed to load alerts");
		if (!alerts?.length) return apiSuccess(res, { processed: 0, results: [] });

		// IDOR fix: fetch user's account IDs to scope data queries
		const { data: userAccounts } = await db
			.from("accounts")
			.select("id, threads_user_id")
			.eq("user_id", user.id);
		const { data: userIgAccounts } = await db
			.from("instagram_accounts")
			.select("id, instagram_user_id")
			.eq("user_id", user.id);
		const userThreadsUserIds = (userAccounts || [])
			.map((a: { id: string; threads_user_id?: string | undefined }) => a.threads_user_id)
			.filter(Boolean) as string[];
		const userIgUserIds = (userIgAccounts || [])
			.map(
				(a: { id: string; instagram_user_id: string }) => a.instagram_user_id,
			)
			.filter(Boolean);

		const results: unknown[] = [];

		for (const alert of alerts) {
			try {
				const keyword = alert.keyword.toLowerCase();
				const escapedKeyword = keyword.replace(/[%_\\]/g, "\\$&");
				let resultCount = 0;
				const samplePosts: SamplePost[] = [];

				// #499: Post-filter with word boundary regex to reduce false positives
				const escapedForRegex = keyword.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
				const wordBoundaryRegex = new RegExp(`\\b${escapedForRegex}\\b`, "i");

				// M17: Keyword matching uses PostgreSQL ilike (case-insensitive substring match).
				// Limitation: ilike does not support word boundaries (\b), so "art" will also
				// match "start" or "heart". PostgreSQL's ~ operator could support regex word
				// boundaries but is not available via Supabase's PostgREST query builder.
				// Phrase keywords (with spaces) reduce false positives naturally. Consider
				// adding pg_trgm or unaccent extensions for improved matching if false
				// positives become an issue.

				// Run all 3 search queries in parallel (was sequential — N+1 fix)
				const [igCommentsResult, igMentionsResult, threadEventsResult] =
					await Promise.all([
						userIgUserIds.length > 0
							? // biome-ignore lint/suspicious/noExplicitAny: TS2589 Supabase deep type — cast at source to prevent infinite type instantiation
								(db as any)
									.from("ig_comments")
									.select("id, text, username, created_at")
									.in("ig_user_id", userIgUserIds)
									.ilike("text", `%${escapedKeyword}%`)
									.order("created_at", { ascending: false })
									.limit(20)
							: Promise.resolve({ data: null }),
						userIgUserIds.length > 0
							? // biome-ignore lint/suspicious/noExplicitAny: TS2589 Supabase deep type — cast at source to prevent infinite type instantiation
								(db as any)
									.from("ig_mentions")
									.select("id, caption, username, mentioned_at")
									.in("ig_account_id", userIgUserIds)
									.ilike("caption", `%${escapedKeyword}%`)
									.order("mentioned_at", { ascending: false })
									.limit(10)
							: Promise.resolve({ data: null }),
						userThreadsUserIds.length > 0
							? // biome-ignore lint/suspicious/noExplicitAny: TS2589 Supabase deep type
								(db as any)
									.from("threads_webhook_events")
									.select("id, payload, created_at")
									.eq("processed", true)
									.in("threads_user_id", userThreadsUserIds)
									.order("created_at", { ascending: false })
									.limit(50)
							: Promise.resolve({ data: null }),
					]);

				// Process ig_comments results
				if (igCommentsResult.data?.length) {
					const filtered = (
						igCommentsResult.data as unknown as IgCommentRow[]
					).filter((c) => wordBoundaryRegex.test(c.text || ""));
					resultCount += filtered.length;
					samplePosts.push(
						...filtered.slice(0, 3).map((c) => ({
							id: c.id,
							text: c.text,
							author: c.username,
							timestamp: c.created_at,
							source: "ig_comment",
						})),
					);
				}

				// Process ig_mentions results
				if (igMentionsResult.data?.length) {
					const filteredMentions = (
						igMentionsResult.data as unknown as IgMentionRow[]
					).filter((m) => wordBoundaryRegex.test(m.caption || ""));
					resultCount += filteredMentions.length;
					samplePosts.push(
						...filteredMentions.slice(0, 2).map((m) => ({
							id: m.id,
							text: m.caption,
							author: m.username,
							timestamp: m.mentioned_at,
							source: "ig_mention",
						})),
					);
				}

				// Process threads_webhook_events results
				if (threadEventsResult.data?.length) {
					// #499: Use word boundary regex for threads events too
					const matchingThreads = (
						(threadEventsResult.data as ThreadsEventRow[]) || []
					).filter((e) => {
						const text = e.payload?.text || e.payload?.message || "";
						return wordBoundaryRegex.test(text);
					});

					if (matchingThreads.length) {
						resultCount += matchingThreads.length;
						samplePosts.push(
							...matchingThreads.slice(0, 2).map((e) => ({
								id: e.id,
								text: e.payload?.text || e.payload?.message || "",
								author: e.payload?.from?.username || "unknown",
								timestamp: e.created_at,
								source: "threads_event",
							})),
						);
					}
				}

				// sentiment breakdown
				const sentimentBreakdown = { positive: 0, neutral: 0, negative: 0 };
				for (const s of samplePosts) {
					const sentiment = analyzeSentiment(s.text);
					if (sentiment === "positive") sentimentBreakdown.positive++;
					else if (sentiment === "negative") sentimentBreakdown.negative++;
					else sentimentBreakdown.neutral++;
				}

				// M6: Deduplicate — only insert one result per alert per clock-hour
				const currentHour = new Date();
				currentHour.setMinutes(0, 0, 0);
				const { data: existingResult } = await db
					.from("listening_results")
					.select("id")
					.eq("alert_id", alert.id)
					.gte("checked_at", currentHour.toISOString())
					.limit(1);

				let result = null;
				if (!existingResult?.length) {
					// biome-ignore lint/suspicious/noExplicitAny: listening_results columns not in generated types
					const { data: inserted } = await (db as any)
						.from("listening_results")
						.insert({
							alert_id: alert.id,
							workspace_id: alert.workspace_id,
							keyword: alert.keyword,
							source: "combined",
							result_count: resultCount,
							sentiment_breakdown: sentimentBreakdown,
							sample_posts: samplePosts.slice(0, 5),
						})
						.select()
						.maybeSingle();
					result = inserted;
				} else {
					logger.debug(
						"[listening/monitor] Skipping duplicate result for current hour",
						{
							alertId: alert.id,
						},
					);
				}

				results.push(result);

				// Check threshold / spike triggers
				let shouldNotify = false;
				let spikeAvgCount = 0;

				if (
					alert.alert_type === "threshold" &&
					resultCount >= (alert.threshold_value ?? 0)
				) {
					shouldNotify = true;
				} else if (alert.alert_type === "spike") {
					// M4: Rolling 7-result average with minimum 3 previous results and 4-hour cooldown
					const { data: prevResults } = await db
						.from("listening_results")
						.select("result_count, checked_at")
						.eq("alert_id", alert.id)
						.order("checked_at", { ascending: false })
						.limit(8); // current + 7 previous

					if (prevResults && prevResults.length >= 4) {
						// Rolling average of previous results (skip the most recent which is current)
						const previous = prevResults.slice(1);
						const avgCount =
							(previous as unknown as ListeningResultCountRow[]).reduce(
								(s: number, r: ListeningResultCountRow) =>
									s + (r.result_count || 0),
								0,
							) / previous.length;
						spikeAvgCount = avgCount;

						// Only spike if 2x above average AND average is meaningful (>= 2)
						if (avgCount >= 2 && resultCount >= avgCount * 2) {
							// 4-hour cooldown: check if a notification was already sent recently for this alert
							const fourHoursAgo = new Date(
								Date.now() - 4 * 60 * 60 * 1000,
							).toISOString();
							const { data: recentNotifs } = await db
								.from("notifications")
								.select("id")
								.eq("user_id", alert.user_id ?? "")
								.eq("data->>alertId", alert.id)
								.gte("created_at", fourHoursAgo)
								.limit(1);

							if (!recentNotifs?.length) {
								shouldNotify = true;
							}
						}
					}
				}

				if (shouldNotify) {
					// Build notification message with spike context when available
					const notifMessage =
						alert.alert_type === "spike" && spikeAvgCount > 0
							? `${resultCount} mentions found for "${alert.keyword}" (${Math.round((resultCount / spikeAvgCount - 1) * 100)}% above average)`
							: `Found ${resultCount} mentions for "${alert.keyword}" (${alert.alert_type} trigger)`;

					// M12: Create in-app notification (also triggers push/email via createNotification internally)
					await createNotification({
						userId: user.id,
						type: "listening_alert",
						title: `Spike detected: "${alert.keyword}"`,
						message: notifMessage,
						data: { alertId: alert.id, keyword: alert.keyword, resultCount },
					});

					// Update last_triggered_at
					await db
						.from("listening_alerts")
						.update({ last_triggered_at: new Date().toISOString() })
						.eq("id", alert.id);
				}

				// Update last_checked_at
				await db
					.from("listening_alerts")
					.update({ last_checked_at: new Date().toISOString() })
					.eq("id", alert.id);
			} catch (err) {
				logger.error("[listening/monitor] Alert check failed", {
					alertId: alert.id,
					error: String(err),
				});
			}
		}

		return apiSuccess(res, { processed: alerts.length, results });
	},
);
