// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
/**
 * Handlers: POST /api/competitors?action=sync | queue-sync-all
 *
 * Sync a single Threads competitor or queue a bulk sync for all.
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";
import { apiError, apiSuccess } from "../../../apiResponse.js";
import { logger } from "../../../logger.js";
import { checkRateLimit } from "../../../rateLimiter.js";
import { getRedis } from "../../../redis.js";
import { withRetry } from "../../../retryUtils.js";
import { CompetitorSyncSchema } from "../../../validation.js";
import { withAuthAndBody } from "../../helpers/withAuthAndBody.js";
import {
	db,
	fetchAndStorePosts,
	getAllAccessTokens,
	getUserCurrentCompetitorJob,
	queueCompetitorSyncJob,
	tryWithFallbackTokens,
	verifyCompetitorOwnership,
} from "../shared.js";

export const handleSync = withAuthAndBody(
	CompetitorSyncSchema,
	async (user, parsed, _req, res) => {
		const { competitorId } = parsed;
		const rl = await checkRateLimit({
			key: `competitor-sync:${user.id}`,
			limit: 120,
			windowSeconds: 60 * 60,
			failMode: "closed",
		});
		if (!rl.allowed) return apiError(res, 429, "Rate limit exceeded");

		const competitor = (await verifyCompetitorOwnership(
			res,
			competitorId,
			user.id,
			"*",
		)) as (Record<string, unknown> & { username: string }) | null;
		if (!competitor) return;

		const tokens = await getAllAccessTokens(user.id);
		if (!tokens.length) return apiError(res, 400, "No connected account");

		logger.info("Syncing competitor", {
			username: competitor.username,
			tokensAvailable: tokens.length,
		});

		// Try each token until one works
		const result = await tryWithFallbackTokens(tokens, async (accessToken) => {
			const response = await withRetry(
				() =>
					fetch(
						`https://graph.threads.net/v1.0/profile_lookup?username=${encodeURIComponent(competitor.username)}`,
						{
							headers: { Authorization: `Bearer ${accessToken}` },
							signal: AbortSignal.timeout(10000),
						},
					),
				{ label: `competitorSyncProfile:${competitor.username}` },
			);
			const data = await response.json();

			if (data.error) {
				logger.info("Sync attempt failed", { error: data.error.message });
				return { data: null, error: data.error.message };
			}

			return { data };
		});

		if (!result.data) {
			logger.error("All tokens failed for sync", {
				username: competitor.username,
			});
			return apiError(res, 500, result.error || "Failed to sync competitor");
		}

		const data = result.data;
		logger.info("Sync succeeded", { attemptNumber: result.tokenIndex + 1 });

		await db()
			.from("competitors")
			.update({
				username: data.username,
				display_name: data.name || data.username,
				avatar_url: data.profile_picture_url || "",
				bio: data.biography || "",
				follower_count: data.follower_count || 0,
				is_verified: data.is_verified || false,
				likes_count_7d: data.likes_count || 0,
				quotes_count_7d: data.quotes_count || 0,
				replies_count_7d: data.replies_count || 0,
				reposts_count_7d: data.reposts_count || 0,
				views_count_7d: data.views_count || 0,
				last_synced_at: new Date().toISOString(),
				sync_status: "active",
				consecutive_failures: 0,
			})
			.eq("id", competitorId);

		// Create snapshot
		const today = new Date().toISOString().split("T")[0]!;
		await db().from("competitor_snapshots").upsert!(
			{
				competitor_id: competitorId,
				user_id: user.id,
				snapshot_date: today,
				follower_count: data.follower_count || 0,
				likes_count_7d: data.likes_count || 0,
				quotes_count_7d: data.quotes_count || 0,
				replies_count_7d: data.replies_count || 0,
				reposts_count_7d: data.reposts_count || 0,
				views_count_7d: data.views_count || 0,
			},
			{ onConflict: "competitor_id,snapshot_date" },
		);

		// Throttle between profile lookup and post fetch to avoid Meta rate limiting
		await new Promise((r) => setTimeout(r, 300));

		// Also fetch and store posts using the working token
		const workingToken = tokens[result.tokenIndex];
		const postsResult = await fetchAndStorePosts(
			competitorId,
			competitor.username,
			workingToken!,
			user.id,
		);

		return apiSuccess(res, { postsCount: postsResult.postsCount });
	},
);

export async function handleQueueSyncAll(
	req: VercelRequest,
	res: VercelResponse,
) {
	const { getAuthUserOrError } = await import("../../../apiResponse.js");
	const user = await getAuthUserOrError(req, res);
	if (!user) return;

	const redis = getRedis();
	if (!redis) {
		return apiError(res, 503, "Queue service not configured", {
			details: "Set UPSTASH_REDIS_REST_URL and UPSTASH_REDIS_REST_TOKEN",
		});
	}

	try {
		// Check for existing job
		const existingJob = await getUserCurrentCompetitorJob(user.id);
		if (
			existingJob &&
			(existingJob.status === "queued" || existingJob.status === "processing")
		) {
			return apiSuccess(res, {
				queued: false,
				existingJob: true,
				job: existingJob,
				message: "You already have a competitor sync in progress",
			});
		}

		// Get all competitor IDs for this user, sorted by follower count (high-value first)
		const { data: competitors } = await db()
			.from("competitors")
			.select("id, follower_count")
			.eq("user_id", user.id)
			.or("sync_status.eq.active,sync_status.is.null")
			.order("follower_count", { ascending: false, nullsFirst: false });

		const competitorIds = (competitors || []).map((c: { id: string }) => c.id);

		if (competitorIds.length === 0) {
			return apiSuccess(res, {
				queued: false,
				message: "No competitors to sync",
			});
		}

		// Queue the job
		const job = await queueCompetitorSyncJob(user.id, competitorIds);

		// Write to sync_jobs table for Realtime
		try {
			await db()
				.from("sync_jobs")
				.upsert(
					{
						id: job.id,
						user_id: user.id,
						job_type: "competitors",
						status: "queued",
						account_count: competitorIds.length,
						current_progress: 0,
						created_at: new Date(job.createdAt).toISOString(),
					},
					{ onConflict: "id" },
				);
		} catch (dbError) {
			logger.warn("Failed to write to sync_jobs", {
				error: String(dbError),
			});
		}

		logger.info("Queued competitor sync job", {
			jobId: job.id,
			competitorCount: competitorIds.length,
		});

		return apiSuccess(res, {
			queued: true,
			job: {
				id: job.id,
				status: job.status,
				competitorCount: competitorIds.length,
				createdAt: job.createdAt,
			},
			message: `Competitor sync queued for ${competitorIds.length} competitors`,
		});
	} catch (error: unknown) {
		logger.error("Queue sync error", { error: String(error) });
		return apiError(res, 500, "Internal server error");
	}
}
