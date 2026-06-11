/**
 * GET /api/health/jobs — Job health check endpoint
 *
 * Requires `Bearer ${CRON_SECRET}` or a platform-admin Supabase user token.
 * The response includes cron run history and operational intel.
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";
import { apiError, apiSuccess } from "../../apiResponse.js";
import { logger } from "../../logger.js";
import { getSupabase } from "../../supabase.js";

const DEFAULT_STALE_THRESHOLD_MS = 12 * 60 * 60 * 1000; // 12 hours

const JOB_STALE_THRESHOLD_MS: Record<string, number> = {
	"webhook-processor": 30 * 60 * 1000,
	"publish-worker": 30 * 60 * 1000,
	"scheduled-posts": 30 * 60 * 1000,
	"auto-reply-worker": 30 * 60 * 1000,
	"inbox-suggestions": 30 * 60 * 1000,
	"cta-reply-worker": 30 * 60 * 1000,
	"reply-farming-worker": 30 * 60 * 1000,
	"ig-container-publisher": 30 * 60 * 1000,
	"autoposter-watchdog": 2 * 60 * 60 * 1000,
	"sync-orchestrator": 3 * 60 * 60 * 1000,
	"periodic-sync": 8 * 60 * 60 * 1000,
	"six-hour-pipeline": 8 * 60 * 60 * 1000,
	"analytics-pipeline": 36 * 60 * 60 * 1000,
	"daily-orchestrator": 36 * 60 * 60 * 1000,
	"daily-orchestrator-late": 36 * 60 * 60 * 1000,
	"daily-intelligence": 36 * 60 * 60 * 1000,
	"health-monitor": 36 * 60 * 60 * 1000,
	"account-state-evaluator": 36 * 60 * 60 * 1000,
	"dawn-planner": 36 * 60 * 60 * 1000,
	"cost-digest": 36 * 60 * 60 * 1000,
	"auto-learning": 36 * 60 * 60 * 1000,
	"reconcile-daily": 36 * 60 * 60 * 1000,
	"overnight-brief": 36 * 60 * 60 * 1000,
	"originality-capture": 36 * 60 * 60 * 1000,
	scheduler: 36 * 60 * 60 * 1000,
	"trend-scanner": 36 * 60 * 60 * 1000,
	"weekly-reports": 8 * 24 * 60 * 60 * 1000,
	"monthly-kpi": 40 * 24 * 60 * 60 * 1000,
};
const EXPECTED_JOB_NAMES = Object.keys(JOB_STALE_THRESHOLD_MS);
const APP_ORIGIN =
	process.env.APP_URL ||
	(process.env.VERCEL_URL
		? `https://${process.env.VERCEL_URL}`
		: "https://juno33.com");

interface CronRun {
	job_name: string;
	status: string;
	started_at: string | null;
	finished_at: string | null;
}

function timeAgo(date: Date): string {
	const diffMs = Date.now() - date.getTime();
	const mins = Math.floor(diffMs / 60000);
	if (mins < 1) return "just now";
	if (mins < 60) return `${mins}m ago`;
	const hours = Math.floor(mins / 60);
	if (hours < 24) return `${hours}h ago`;
	const days = Math.floor(hours / 24);
	return `${days}d ago`;
}

function staleThresholdForJob(jobName: string): number {
	return JOB_STALE_THRESHOLD_MS[jobName] ?? DEFAULT_STALE_THRESHOLD_MS;
}

function formatThreshold(ms: number): string {
	const hours = ms / (60 * 60 * 1000);
	if (hours < 1) return `${Math.round(ms / 60000)}m`;
	if (hours < 24) return `${Math.round(hours)}h`;
	const days = hours / 24;
	return `${Math.round(days)}d`;
}

export default async function handler(req: VercelRequest, res: VercelResponse) {
	if (req.method !== "GET") {
		return apiError(res, 405, "Method not allowed");
	}

	res.setHeader("Access-Control-Allow-Origin", APP_ORIGIN);
	res.setHeader("Cache-Control", "no-store");

	// Require authentication — either CRON_SECRET or platform-admin Bearer token.
	const authHeader = req.headers.authorization;
	const cronSecret = process.env.CRON_SECRET;
	const isCronAuth = cronSecret && authHeader === `Bearer ${cronSecret}`;

	if (!isCronAuth) {
		if (!authHeader?.startsWith("Bearer ")) {
			return apiError(res, 401, "Unauthorized");
		}
		const adminIds = (process.env.PLATFORM_ADMIN_IDS || "")
			.split(",")
			.map((id) => id.trim())
			.filter(Boolean);
		if (adminIds.length === 0) {
			logger.warn("[health/jobs] PLATFORM_ADMIN_IDS not configured");
			return apiError(res, 403, "Admin access required");
		}
		const token = authHeader.slice(7);
		const {
			data: { user },
			error: authError,
		} = await getSupabase().auth.getUser(token);
		if (authError || !user) {
			return apiError(res, 401, "Unauthorized");
		}
		if (!adminIds.includes(user.id)) {
			return apiError(res, 403, "Admin access required");
		}
	}

	try {
		const db = getSupabase();

		// Query far enough back to cover low-frequency jobs like monthly KPI.
		const maxStaleThreshold = Math.max(...Object.values(JOB_STALE_THRESHOLD_MS));
		const cutoff = new Date(Date.now() - maxStaleThreshold).toISOString();
		const todayStart = new Date();
		todayStart.setHours(0, 0, 0, 0);

		const { data: runs, error } = await db
			.from("cron_runs")
			.select("job_name, status, started_at, finished_at")
			.gte("started_at", cutoff)
			.order("started_at", { ascending: false });

		if (error) {
			logger.error("[health/jobs] Failed to query cron_runs", {
				error: error.message,
			});
			return apiError(res, 500, "Failed to query job history");
		}

		// Group by job name
		const jobMap = new Map<
			string,
			{
				lastSuccessAt: Date | null;
				lastFailureAt: Date | null;
				runsToday: number;
			}
		>();

		for (const name of EXPECTED_JOB_NAMES) {
			if (!jobMap.has(name)) {
				jobMap.set(name, {
					lastSuccessAt: null,
					lastFailureAt: null,
					runsToday: 0,
				});
			}
		}

		for (const run of (runs || []) as CronRun[]) {
			const name = run.job_name;
			if (!jobMap.has(name)) {
				jobMap.set(name, {
					lastSuccessAt: null,
					lastFailureAt: null,
					runsToday: 0,
				});
			}
			const entry = jobMap.get(name) ?? {
				lastSuccessAt: null,
				lastFailureAt: null,
				runsToday: 0,
			};

			const finishedAt = run.finished_at ? new Date(run.finished_at) : null;
			const startedAt = run.started_at ? new Date(run.started_at) : null;
			const ts = finishedAt || startedAt;

			if (run.status === "success" && ts && !entry.lastSuccessAt) {
				entry.lastSuccessAt = ts;
			}
			if (run.status === "failed" && ts && !entry.lastFailureAt) {
				entry.lastFailureAt = ts;
			}

			if (startedAt && startedAt >= todayStart) {
				entry.runsToday++;
			}
		}

		let healthy = true;
		const jobs = Array.from(jobMap.entries()).map(([name, info]) => {
			const staleThresholdMs = staleThresholdForJob(name);
			const stale =
				!info.lastSuccessAt ||
				Date.now() - info.lastSuccessAt.getTime() > staleThresholdMs;
			if (stale) healthy = false;

			return {
				name,
				lastRun: info.lastSuccessAt ? timeAgo(info.lastSuccessAt) : "never",
				lastFailure: info.lastFailureAt ? timeAgo(info.lastFailureAt) : null,
				runsToday: info.runsToday,
				status: stale ? "warning" : "ok",
				staleAfter: formatThreshold(staleThresholdMs),
			};
		});

		return apiSuccess(res, { healthy, jobs });
	} catch (err: unknown) {
		logger.error("[health/jobs] Error", {
			error: err instanceof Error ? err.message : String(err),
		});
		return apiError(res, 500, "Internal error");
	}
}
