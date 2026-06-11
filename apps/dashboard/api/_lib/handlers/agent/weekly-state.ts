/**
 * Agent Weekly Cycle State
 *
 * GET /api/agent/weekly-state
 *
 * Returns a rich state snapshot for intelligent session resumption:
 * - Posts published/scheduled this week
 * - Pending approvals
 * - Agent log summary (last 24h)
 * - Daily cap status for each account active this week
 *
 * Called from agent.ts router (already wrapped with withAuth via sub-handler pattern).
 * Uses getAuthUserOrError directly to avoid double-wrapping.
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";
import { apiError, apiSuccess, getAuthUserOrError } from "../../apiResponse.js";
import { createDbContext } from "../../dbContext.js";
import { logger } from "../../logger.js";

/** ISO timestamp for the start of the current UTC week (Monday 00:00:00) */
function weekStart(): string {
	const now = new Date();
	const day = now.getUTCDay(); // 0=Sun, 1=Mon...
	const daysFromMonday = day === 0 ? 6 : day - 1;
	const monday = new Date(now);
	monday.setUTCDate(now.getUTCDate() - daysFromMonday);
	monday.setUTCHours(0, 0, 0, 0);
	return monday.toISOString();
}

/** ISO timestamp for 24 hours ago */
function oneDayAgo(): string {
	return new Date(Date.now() - 24 * 60 * 60 * 1000).toISOString();
}

export default async function handleWeeklyState(
	req: VercelRequest,
	res: VercelResponse,
) {
	if (req.method !== "GET") return apiError(res, 405, "Method not allowed");

	const user = await getAuthUserOrError(req, res);
	if (!user) return;

	const weekStartIso = weekStart();
	const dayAgoIso = oneDayAgo();
	const userId = user.id;
	const { userDb } = createDbContext(req, user);

	// Run all queries in parallel
	const [
		publishedResult,
		publishedCountResult,
		totalPublishedResult,
		scheduledResult,
		approvalsResult,
		agentLogResult,
		agentSettingsResult,
	] = await Promise.all([
		// Recent published posts this week (preview only — capped for payload size)
		// Use OR to include posts where published_at is NULL but created_at is in range
		userDb
			.from("posts")
			.select(
				"id, content, account_id, instagram_account_id, platform, published_at, created_at",
			)
			.eq("user_id", userId)
			.eq("status", "published")
			.or(`published_at.gte.${weekStartIso},published_at.is.null`)
			.order("published_at", { ascending: false })
			.limit(5),

		// Exact count of all posts published this week
		userDb
			.from("posts")
			.select("id", { count: "exact", head: true })
			.eq("user_id", userId)
			.eq("status", "published")
			.or(`published_at.gte.${weekStartIso},published_at.is.null`),

		// Total published posts (all time) for context
		userDb
			.from("posts")
			.select("id", { count: "exact", head: true })
			.eq("user_id", userId)
			.eq("status", "published"),

		// Posts scheduled (future)
		userDb
			.from("posts")
			.select(
				"id, content, account_id, instagram_account_id, platform, scheduled_for",
			)
			.eq("user_id", userId)
			.eq("status", "scheduled")
			.gte("scheduled_for", new Date().toISOString())
			.order("scheduled_for", { ascending: true })
			.limit(10),

		// Approvals this week
		userDb
			.from("agent_approvals")
			.select("id, status, urgency, context, created_at, decided_at")
			.eq("user_id", userId)
			.gte("created_at", weekStartIso)
			.order("created_at", { ascending: false })
			.limit(20),

		// Agent log: last 24h
		userDb
			.from("agent_actions")
			.select("tool_name, success, duration_ms, created_at")
			.eq("user_id", userId)
			.gte("created_at", dayAgoIso)
			.order("created_at", { ascending: false })
			.limit(200),

		// Agent settings (paused flag)
		userDb.from("profiles").select("agent_paused").eq("id", userId).maybeSingle(),
	]);

	// Log errors for debugging but don't fail the whole response
	if (publishedCountResult.error) {
		logger.warn("[weekly-state] Published count query failed", {
			error: publishedCountResult.error.message,
		});
	}

	const totalPublished: number =
		typeof totalPublishedResult.count === "number"
			? totalPublishedResult.count
			: 0;

	// --- Summarise published posts ---
	const published: {
		id: string;
		content: string;
		account_id: string | null;
		instagram_account_id: string | null;
		platform: string | null;
		published_at: string | null;
	}[] = publishedResult.data ?? [];

	// Extract count correctly: Supabase returns { count, data, error }
	// count is a top-level property on the result, not nested
	const publishedCount: number =
		typeof publishedCountResult.count === "number"
			? publishedCountResult.count
			: published.length;

	const publishedPreview = published.slice(0, 3).map((p) => ({
		id: p.id,
		preview: p.content?.slice(0, 80),
		platform: p.platform,
		publishedAt: p.published_at,
	}));

	// --- Summarise scheduled posts ---
	const scheduled: {
		id: string;
		content: string;
		account_id: string | null;
		instagram_account_id: string | null;
		platform: string | null;
		scheduled_for: string | null;
	}[] = scheduledResult.data ?? [];
	const scheduledCount = scheduled.length;
	const nextScheduled = scheduled[0]
		? {
				id: scheduled[0].id,
				preview: scheduled[0].content?.slice(0, 80),
				platform: scheduled[0].platform,
				scheduledFor: scheduled[0].scheduled_for,
			}
		: null;

	// --- Summarise approvals ---
	const approvals: {
		id: string;
		status: string;
		urgency: string;
		context: string;
		created_at: string;
		decided_at?: string | null | undefined;
	}[] = approvalsResult.data ?? [];
	const pendingApprovals = approvals.filter((a) => a.status === "pending");
	const approvedThisWeek = approvals.filter(
		(a) => a.status === "approved",
	).length;
	const rejectedThisWeek = approvals.filter(
		(a) => a.status === "rejected",
	).length;

	// --- Summarise agent log ---
	const logEntries: {
		tool_name: string;
		success: boolean;
		duration_ms: number | null;
	}[] = agentLogResult.data ?? [];
	const totalCalls = logEntries.length;
	const successCount = logEntries.filter((e) => e.success).length;
	const toolCounts: Record<string, number> = {};
	for (const entry of logEntries) {
		toolCounts[entry.tool_name] = (toolCounts[entry.tool_name] ?? 0) + 1;
	}
	const topTools = Object.entries(toolCounts)
		.sort(([, a], [, b]) => b - a)
		.slice(0, 5)
		.map(([tool, count]) => ({ tool, count }));
	const avgDurationMs =
		totalCalls > 0
			? Math.round(
					logEntries.reduce((sum, e) => sum + (e.duration_ms ?? 0), 0) /
						totalCalls,
				)
			: 0;

	return apiSuccess(res, {
		generatedAt: new Date().toISOString(),
		weekStart: weekStartIso,
		agentPaused: agentSettingsResult.data?.agent_paused ?? false,

		postsThisWeek: {
			published: publishedCount,
			scheduled: scheduledCount,
			totalPublished,
			preview: publishedPreview,
			nextScheduled,
		},

		approvals: {
			pending: pendingApprovals.length,
			pendingItems: pendingApprovals.slice(0, 5).map((a) => ({
				id: a.id,
				urgency: a.urgency,
				context: a.context?.slice(0, 120),
				createdAt: a.created_at,
			})),
			approvedThisWeek,
			rejectedThisWeek,
		},

		agentActivity: {
			callsLast24h: totalCalls,
			successRate:
				totalCalls > 0 ? Math.round((successCount / totalCalls) * 100) : 100,
			topTools,
			avgDurationMs,
		},
	});
}
