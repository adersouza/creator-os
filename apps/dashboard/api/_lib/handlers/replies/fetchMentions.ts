/**
 * Handlers for fetching mentions (queued and legacy).
 * Action: "fetch-mentions"
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";
import {
	apiSuccess,
	badRequest,
	notFound,
	serverError,
} from "../../apiResponse.js";
import { decrypt } from "../../encryption.js";
import { logger } from "../../logger.js";
import { getRedis } from "../../redis.js";
import { withRetry } from "../../retryUtils.js";
import { getSupabase } from "../../supabase.js";
import { neqOrNull } from "../../supabaseSafe.js";
import {
	type AccountRecord,
	getUserCurrentEngagementJob,
	queueEngagementSyncJob,
} from "./shared.js";

export async function handleFetchMentions(
	req: VercelRequest,
	res: VercelResponse,
	userId: string,
) {
	const { accountId, accountIds } = req.body;

	// Check if Redis is available for queue-based sync
	const redis = getRedis();
	if (redis) {
		return handleQueuedFetchMentions(req, res, userId, accountId, accountIds);
	}

	// Fallback to synchronous sync (single account)
	return handleFetchMentionsLegacy(req, res, userId, accountId);
}

// Queue-based mentions fetch
async function handleQueuedFetchMentions(
	_req: VercelRequest,
	res: VercelResponse,
	userId: string,
	accountId?: string,
	accountIds?: string[],
) {
	try {
		// Check for existing job
		const existingJob = await getUserCurrentEngagementJob(userId, "mentions");
		if (
			existingJob &&
			(existingJob.status === "queued" || existingJob.status === "processing")
		) {
			return apiSuccess(res, {
				queued: false,
				existingJob: true,
				job: existingJob,
				message: "You already have a mentions sync in progress",
			});
		}

		// Get account IDs to sync
		let idsToSync: string[] = accountIds || [];
		if (accountId && !idsToSync.includes(accountId)) {
			idsToSync.push(accountId);
		}

		if (idsToSync.length > 0) {
			const uniqueIds = [...new Set(idsToSync)].filter(Boolean);
			const base = getSupabase()
				.from("accounts")
				.select("id")
				.eq("user_id", userId)
				.in("id", uniqueIds)
				.not("threads_access_token_encrypted", "is", null);
			const { data: accounts } = await neqOrNull(base, "status", "suspended");

			idsToSync = (accounts || []).map((a: { id: string }) => a.id);
		} else {
			// If no account IDs provided, get all active accounts for user
			const base = getSupabase()
				.from("accounts")
				.select("id")
				.eq("user_id", userId)
				.not("threads_access_token_encrypted", "is", null);
			const { data: accounts } = await neqOrNull(base, "status", "suspended");

			idsToSync = (accounts || []).map((a: { id: string }) => a.id);
		}

		if (idsToSync.length === 0) {
			return apiSuccess(res, {
				queued: false,
				message: "No accounts to sync mentions for",
			});
		}

		// Queue the job
		const job = await queueEngagementSyncJob(userId, "mentions", {
			accountIds: idsToSync,
		});

		// Write to sync_jobs table for Realtime
		try {
			await getSupabase()
				.from("sync_jobs")
				.upsert(
					{
						id: job.id,
						user_id: userId,
						job_type: "mentions",
						status: "queued",
						account_count: idsToSync.length,
						current_progress: 0,
						created_at: new Date(job.createdAt).toISOString(),
					},
					{ onConflict: "id" },
				);
		} catch (dbError) {
			logger.warn("Failed to write to sync_jobs", { error: String(dbError) });
		}

		logger.info("Queued mentions sync job", {
			jobId: job.id,
			accountCount: idsToSync.length,
		});

		return apiSuccess(res, {
			queued: true,
			job: {
				id: job.id,
				status: job.status,
				accountCount: idsToSync.length,
				createdAt: job.createdAt,
			},
			message: `Mentions sync queued for ${idsToSync.length} accounts`,
		});
	} catch (error: unknown) {
		logger.error("Queue fetch-mentions error", {
			error: error instanceof Error ? error.message : String(error),
		});
		return serverError(res, "Internal server error");
	}
}

// Legacy synchronous mentions fetch (single account)
async function handleFetchMentionsLegacy(
	_req: VercelRequest,
	res: VercelResponse,
	userId: string,
	accountId?: string,
) {
	if (!accountId) return badRequest(res, "accountId is required");

	const { data: account, error: accountError } = await getSupabase()
		.from("accounts")
		.select("*")
		.eq("id", accountId)
		.eq("user_id", userId)
		.maybeSingle();

	if (accountError || !account) {
		return notFound(res, "Account not found");
	}

	const accountData = account as AccountRecord;
	if (
		!accountData.threads_access_token_encrypted ||
		!accountData.threads_user_id
	) {
		return badRequest(res, "Account not properly configured");
	}

	const token = decrypt(accountData.threads_access_token_encrypted);

	const mentionsUrl = `https://graph.threads.net/v1.0/${accountData.threads_user_id}/mentions?fields=id,text,username,timestamp,media_type,media_url,permalink,is_reply`;
	const response = await withRetry(
		() =>
			fetch(mentionsUrl, {
				headers: { Authorization: `Bearer ${token}` },
				signal: AbortSignal.timeout(10000),
			}),
		{ label: `fetchMentions:${accountData.threads_user_id}` },
	);
	const result = await response.json();

	if (result.error) {
		return serverError(res, result.error.message || "Failed to fetch mentions");
	}

	const mentions = result.data || [];
	let storedCount = 0;

	for (const mention of mentions) {
		const { data: existingMention } = await getSupabase()
			.from("mentions")
			.select("id")
			.eq("user_id", userId)
			.eq("account_id", accountId)
			.eq("threads_post_id", mention.id)
			.maybeSingle();

		if (!existingMention) {
			const { error: insertError } = await getSupabase()
				.from("mentions")
				.insert({
					user_id: userId,
					account_id: accountId,
					threads_post_id: mention.id,
					mentioned_by_username: mention.username || "unknown",
					mentioned_by_avatar: null,
					content: mention.text || "",
					media_urls: mention.media_url ? [mention.media_url] : null,
					permalink: mention.permalink || null,
					mentioned_at: mention.timestamp || new Date().toISOString(),
					is_read: false,
					// biome-ignore lint/suspicious/noExplicitAny: Supabase insert type workaround
				} as any);

			if (!insertError) storedCount++;
		}
	}

	return apiSuccess(res, {
		mentionsFound: mentions.length,
		mentionsStored: storedCount,
	});
}
