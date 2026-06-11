/**
 * Cron Job Utilities — Distributed locking and health tracking
 *
 * Provides two wrappers for cron jobs:
 * - withCronLock(): Prevents concurrent executions via DB-level locking
 * - trackCronRun(): Records execution history to cron_runs table
 *
 * Usage:
 *   const lockResult = await withCronLock(supabase, "job-name", async () => {
 *     return trackCronRun(supabase, "job-name", async () => {
 *       // existing logic
 *       return { itemsProcessed: count };
 *     });
 *   });
 *   if (lockResult.skipped) return res.status(200).json({ skipped: true });
 */

import * as crypto from "node:crypto";
import { logger, serializeError } from "./logger.js";
import type { TypedSupabaseClient } from "./supabase.js";

const instanceId = crypto.randomUUID();

/**
 * Lock TTL per cron job — must exceed maxDuration to prevent premature expiry.
 * Keep this in sync with vercel.json crons; tests fail if a scheduled cron is
 * not listed here.
 */
export const LOCK_TTL_MAP: Record<string, number> = {
	"webhook-processor": 130, // maxDuration: 120
	"sync-orchestrator": 190, // maxDuration: 180
	"analytics-pipeline": 310, // maxDuration: 300
	"daily-orchestrator": 310, // maxDuration: 300
	"daily-orchestrator-late": 310, // maxDuration: 300
	"health-monitor": 310, // maxDuration: 300
	"six-hour-pipeline": 310, // maxDuration: 300
	"weekly-reports": 310, // maxDuration: 300
	"cost-digest": 130, // maxDuration: 120
	"monthly-kpi": 310, // maxDuration: 300
	"auto-learning": 310, // maxDuration: 300
	"autoposter-doctor": 190, // maxDuration: 180
	"autoposter-watchdog": 310, // maxDuration: 300
	"dawn-planner": 310, // maxDuration: 300
	"publish-worker": 190, // maxDuration: 180
	"campaign-schedule-recovery": 130, // maxDuration: 120
	"trend-scanner": 310, // maxDuration: 300
	"overnight-brief": 310, // maxDuration: 300
	"originality-capture": 310, // maxDuration: 300
	"reconcile-daily": 310, // maxDuration: 300 (bumped from 120 — 28% timeout rate)
	"account-state-evaluator": 130, // maxDuration: 120
	"auto-reply-worker": 130, // maxDuration: 120
	"inbox-suggestions": 130, // maxDuration: 120
	"reply-farming-worker": 130, // maxDuration: 120
	"cta-reply-worker": 130, // maxDuration: 120
	scheduler: 190, // maxDuration: 180
};

type SupabaseClient = TypedSupabaseClient;

export async function withCronLock<T>(
	supabase: SupabaseClient,
	jobName: string,
	fn: () => Promise<T>,
	ttlSeconds?: number,
): Promise<{ skipped: true } | { skipped: false; result: T }> {
	const effectiveTtl = ttlSeconds ?? LOCK_TTL_MAP[jobName] ?? 55;

	// Try to acquire lock — fail safe if DB is under load
	let acquired: boolean;
	try {
		const { data } = await supabase.rpc("acquire_cron_lock", {
			p_job_name: jobName,
			p_locked_by: instanceId,
			p_ttl_seconds: effectiveTtl,
		});
		acquired = !!data;
	} catch {
		logger.warn("Cron lock acquisition threw — skipping run to avoid overlap", { jobName });
		return { skipped: true };
	}

	if (!acquired) {
		logger.info("Cron lock skipped — another instance holds the lock", {
			jobName,
			instanceId,
		});
		return { skipped: true };
	}

	try {
		const result = await fn();
		return { skipped: false, result };
	} finally {
		try {
			await supabase.rpc("release_cron_lock", {
				p_job_name: jobName,
				p_locked_by: instanceId,
			});
		} catch {
			// Non-fatal — lock will expire naturally after TTL
		}
	}
}

// Crons that should skip DB logging when they process 0 items.
// High-frequency pollers + orchestrators whose sub-phases track their own counts.
const SKIP_NOOP_CRONS = new Set([
	"webhook-processor",
	"publish-worker",
	"daily-orchestrator",
	"daily-orchestrator-late",
	"six-hour-pipeline",
	"health-monitor",
]);

export async function trackCronRun(
	supabase: SupabaseClient,
	jobName: string,
	fn: () => Promise<{
		itemsProcessed: number;
		metadata?: Record<string, unknown> | undefined;
	}>,
): Promise<{ itemsProcessed: number; metadata?: Record<string, unknown> | undefined }> {
	const skipNoOp = SKIP_NOOP_CRONS.has(jobName);

	// For high-frequency crons, run the function first and log a lightweight row
	if (skipNoOp) {
		const startedAt = new Date().toISOString();
		try {
			const result = await fn();
			const runId = crypto.randomUUID();
			try {
				await supabase.from("cron_runs").insert({
					id: runId,
					job_name: jobName,
					status: "success",
					started_at: startedAt,
					finished_at: new Date().toISOString(),
					items_processed: result.itemsProcessed,
					metadata: (result.itemsProcessed === 0
						? null
						: (result.metadata ??
							null)) as import("../../types/supabase.js").Json,
				});
			} catch (insertErr) {
				logger.error("Failed to record cron run (non-fatal)", {
					jobName,
					error: String(insertErr),
				});
			}
			return result;
		} catch (error) {
			const runId = crypto.randomUUID();
			try {
				await supabase.from("cron_runs").insert({
					id: runId,
					job_name: jobName,
					status: "failed",
					started_at: startedAt,
					finished_at: new Date().toISOString(),
					error: serializeError(error),
				});
			} catch (insertErr) {
				logger.error("Failed to record cron run (non-fatal)", {
					jobName,
					error: String(insertErr),
				});
			}
			throw error;
		}
	}

	// Standard path: insert "running" row first, then update
	const runId = crypto.randomUUID();

	await supabase.from("cron_runs").insert({
		id: runId,
		job_name: jobName,
		status: "running",
	});

	try {
		const result = await fn();

		await supabase
			.from("cron_runs")
			.update({
				finished_at: new Date().toISOString(),
				status: "success",
				items_processed: result.itemsProcessed,
				metadata: (result.metadata ??
					null) as import("../../types/supabase.js").Json,
			})
			.eq("id", runId);

		return result;
	} catch (error) {
		await supabase
			.from("cron_runs")
			.update({
				finished_at: new Date().toISOString(),
				status: "failed",
				error: serializeError(error),
			})
			.eq("id", runId);
		throw error;
	}
}
