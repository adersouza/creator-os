// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
/**
 * Handler: POST /api/analytics?action=bulk-sync
 *
 * Bulk sync accounts by group or by explicit account IDs.
 * Delegates to QStash fan-out (same pattern as queue-sync) but adds:
 * - groupId resolution → accounts in that group
 * - Cap at 200 accounts per request
 * - Per-account success/failure tracking via existing syncProgress system
 *
 * Body option A (specific accounts):
 * { accountIds?: string[], igAccountIds?: string[], platform?: "threads"|"instagram" }
 *
 * Body option B (entire group):
 * { groupId: string, platform?: "threads"|"instagram" }
 *
 * Both options return a jobId for async progress tracking.
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";
import { apiError, apiSuccess } from "../../apiResponse.js";
import { logger } from "../../logger.js";
import { getQStashClient } from "../../qstash.js";
import { getRedis, getUserCurrentJob } from "../../redis.js";
import { getSupabase } from "../../supabase.js";
import { createSyncJob } from "../../syncProgress.js";
import { neqOrNull } from "../../supabaseSafe.js";
import { parseBodyOrError } from "../../validation.js";
import { z, zEnum } from "../../zodCompat.js";

const MAX_ACCOUNTS = 200;

// biome-ignore lint/suspicious/noExplicitAny: new columns not in generated types
const db = (): any => getSupabase();

const BulkSyncSchema = z.object({
	accountIds: z.array(z.string()).optional(),
	igAccountIds: z.array(z.string()).optional(),
	groupId: z.string().optional(),
	platform: zEnum(["threads", "instagram"]).optional(),
});

export async function handleBulkSync(
	req: VercelRequest,
	res: VercelResponse,
	userId: string,
) {
	if (
		!process.env.UPSTASH_REDIS_REST_URL ||
		!process.env.UPSTASH_REDIS_REST_TOKEN
	) {
		return apiError(res, 503, "Queue service not configured");
	}

	const parsed = parseBodyOrError(res, BulkSyncSchema, req.body);
	if (!parsed) return;

	const { groupId, platform } = parsed;
	let { accountIds, igAccountIds } = parsed;

	// ── Resolve accounts ───────────────────────────────────────────────
	if (groupId) {
		// Verify group ownership
		const { data: group } = await db()
			.from("account_groups")
			.select("id")
			.eq("id", groupId)
			.eq("user_id", userId)
			.maybeSingle();

		if (!group) return apiError(res, 404, "Group not found");

		// Get Threads accounts in group (unless platform is "instagram")
		if (!platform || platform === "threads") {
			const base = db()
				.from("accounts")
				.select("id")
				.eq("user_id", userId)
				.eq("group_id", groupId)
				.eq("is_active", true);
			const { data: threads } = await neqOrNull(base, "status", "suspended");
			accountIds = ((threads ?? []) as { id: string }[]).map((a) => a.id);
		} else {
			accountIds = [];
		}

		// Get Instagram accounts in group (unless platform is "threads")
		if (!platform || platform === "instagram") {
			const base = db()
				.from("instagram_accounts")
				.select("id")
				.eq("user_id", userId)
				.eq("group_id", groupId)
				.eq("is_active", true);
			const { data: ig } = await neqOrNull(base, "status", "suspended");
			igAccountIds = ((ig ?? []) as { id: string }[]).map((a) => a.id);
		} else {
			igAccountIds = [];
		}
	} else {
		// Validate provided accountIds belong to the user (IDOR prevention)
		if (accountIds && accountIds.length > 0) {
			const { data: owned } = await db()
				.from("accounts")
				.select("id")
				.eq("user_id", userId)
				.in("id", accountIds);
			accountIds = ((owned ?? []) as { id: string }[]).map((a) => a.id);
		}
		if (igAccountIds && igAccountIds.length > 0) {
			const { data: ownedIg } = await db()
				.from("instagram_accounts")
				.select("id")
				.eq("user_id", userId)
				.in("id", igAccountIds);
			igAccountIds = ((ownedIg ?? []) as { id: string }[]).map((a) => a.id);
		}
	}

	const threadsIds = accountIds ?? [];
	const igIds = igAccountIds ?? [];
	const totalAccounts = threadsIds.length + igIds.length;

	if (totalAccounts === 0) {
		return apiSuccess(res, {
			queued: false,
			message: "No accounts to sync",
		});
	}

	if (totalAccounts > MAX_ACCOUNTS) {
		return apiError(
			res,
			400,
			`Max ${MAX_ACCOUNTS} accounts per request (got ${totalAccounts})`,
		);
	}

	// ── Check for existing active job ──────────────────────────────────
	const existingJob = await getUserCurrentJob(userId);
	if (
		existingJob &&
		(existingJob.status === "queued" || existingJob.status === "processing")
	) {
		const jobAgeMs = Date.now() - existingJob.createdAt;
		const STALE_THRESHOLD = 10 * 60 * 1000; // 10 minutes

		if (jobAgeMs < STALE_THRESHOLD) {
			return apiSuccess(res, {
				queued: false,
				existingJob: true,
				job: existingJob,
				message: "You already have a sync in progress",
			});
		}

		// Clear stale job
		logger.warn("Clearing stale sync job for bulk-sync", {
			jobId: existingJob.id,
			ageMinutes: Math.round(jobAgeMs / 60000),
		});
		const redis = getRedis();
		await redis.del(`sync-jobs:job:${existingJob.id}`);
		await redis.del(`sync-jobs:user:${userId}`);
	}

	// ── Bust IG no-insights cache ──────────────────────────────────────
	if (igIds.length > 0) {
		const redis = getRedis();
		await Promise.all(
			igIds.map((id) => redis.del(`ig-no-insights:${id}`).catch(() => {})),
		);
	}

	// ── Create job + fan out via QStash ─────────────────────────────────
	const jobId = await createSyncJob(userId, totalAccounts);
	const baseUrl = process.env.APP_URL || `https://${process.env.VERCEL_URL}`;
	const qstash = getQStashClient();
	const dateKey = new Date().toISOString().split("T")[0]!;

	const messages = [
		...threadsIds.map((accountId, i) => ({
			url: `${baseUrl}/api/sync/threads-account`,
			body: { accountId, userId, syncType: "metrics" as const, jobId },
			retries: 3,
			delay: Math.floor(i / 10) * 2, // 10 accounts per 2s wave
			deduplicationId: `threads-${accountId}-${dateKey}`,
		})),
		...igIds.map((accountId, i) => ({
			url: `${baseUrl}/api/sync/ig-account`,
			body: { accountId, userId, syncType: "metrics" as const, jobId },
			retries: 3,
			delay: Math.floor((threadsIds.length + i) / 10) * 2,
			deduplicationId: `ig-${accountId}-${dateKey}`,
		})),
	];

	let dispatched = 0;
	try {
		await qstash.batchJSON(messages);
		dispatched = messages.length;
	} catch (qErr) {
		logger.warn("QStash batchJSON failed, falling back to parallel dispatch", {
			error: String(qErr),
		});
		const results = await Promise.allSettled(
			messages.map((msg) =>
				qstash.publishJSON({
					url: msg.url,
					body: msg.body,
					retries: msg.retries,
					delay: msg.delay,
					deduplicationId: msg.deduplicationId,
				}),
			),
		);
		dispatched = results.filter((r) => r.status === "fulfilled").length;
	}

	logger.info("Bulk sync fan-out complete", {
		jobId,
		totalAccounts,
		dispatched,
		threadsCount: threadsIds.length,
		igCount: igIds.length,
		groupId: groupId ?? null,
	});

	return apiSuccess(res, {
		queued: true,
		job: {
			id: jobId,
			status: "processing",
			accountCount: totalAccounts,
			threadsCount: threadsIds.length,
			igCount: igIds.length,
			createdAt: Date.now(),
		},
		message: `Sync dispatched for ${totalAccounts} accounts`,
	});
}
