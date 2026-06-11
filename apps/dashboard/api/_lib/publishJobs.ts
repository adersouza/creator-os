import type { VercelRequest, VercelResponse } from "@vercel/node";
import { apiError, apiSuccess, sanitizeErrorDetails } from "./apiResponse.js";
import { getFailureCallbackUrl, getRequiredAppBaseUrl, RETRIES } from "./qstashDefaults.js";
import { getPrivilegedSupabaseAny, PRIVILEGED_DB_REASONS } from "./privilegedDb.js";
import { getQStashClient } from "./qstash.js";
import { getOrCreateRequestId } from "./requestId.js";
import { logger } from "./logger.js";

export type PublishJobStage =
	| "queued"
	| "preflight"
	| "publishing"
	| "processing"
	| "published"
	| "failed"
	| "retrying";

export type PublishJobStatus =
	| "queued"
	| "publishing"
	| "retrying"
	| "published"
	| "failed";

const TERMINAL_STATUSES = new Set(["published", "failed"]);

export function wantsAsyncPublish(req: VercelRequest): boolean {
	const prefer = String(req.headers.prefer || req.headers.Prefer || "");
	return prefer
		.split(",")
		.map((part) => part.trim().toLowerCase())
		.includes("respond-async");
}

export async function createPublishJob(
	req: VercelRequest,
	res: VercelResponse,
	userId: string,
) {
	const requestId = getOrCreateRequestId(req, res);
	const payload = req.body as Record<string, unknown>;
	const platform = payload.platform === "instagram" ? "instagram" : "threads";
	const accountId =
		platform === "instagram" ? payload.instagramAccountId : payload.accountId;
	const idempotencyKey =
		typeof req.headers["idempotency-key"] === "string"
			? req.headers["idempotency-key"]
			: undefined;

	const supabase = getPrivilegedSupabaseAny(PRIVILEGED_DB_REASONS.publishQueue);
	if (idempotencyKey) {
		const { data: existing } = await supabase
			.from("publish_jobs")
			.select("id, status, stage, request_id")
			.eq("user_id", userId)
			.eq("idempotency_key", idempotencyKey)
			.maybeSingle();
		if (existing) {
			return apiSuccess(
				res,
				{
					jobId: existing.id,
					status: existing.status,
					stage: existing.stage,
					requestId: existing.request_id || requestId,
				},
				202,
			);
		}
	}

	const { data: job, error } = await supabase
		.from("publish_jobs")
		.insert({
			user_id: userId,
			workspace_id:
				typeof payload.workspaceId === "string" ? payload.workspaceId : null,
			platform,
			account_id: typeof accountId === "string" ? accountId : null,
			payload,
			request_id: requestId,
			idempotency_key: idempotencyKey ?? null,
			status: "queued",
			stage: "queued",
		})
		.select("id, status, stage, request_id")
		.maybeSingle();

	if (error || !job) {
		logger.error("[publish-jobs] Failed to create publish job", {
			userId,
			error: String(error),
		});
		return apiError(res, 500, "Failed to create publish job");
	}

	try {
		const qstash = getQStashClient();
		const result = await qstash.publishJSON({
			url: `${getRequiredAppBaseUrl()}/api/jobs?action=publish-worker`,
			body: { jobId: job.id },
			retries: RETRIES.CRITICAL,
			failureCallback: getFailureCallbackUrl(),
		});
		const messageId = (result as { messageId?: string; messageID?: string }).messageId
			|| (result as { messageID?: string }).messageID
			|| null;
		if (messageId) {
			await supabase
				.from("publish_jobs")
				.update({ qstash_message_id: messageId, updated_at: new Date().toISOString() })
				.eq("id", job.id);
		}
	} catch (dispatchError) {
		logger.error("[publish-jobs] QStash dispatch failed", {
			jobId: job.id,
			error: String(dispatchError),
		});
		await markPublishJobFailed(job.id, "DISPATCH_FAILED", "Publish worker dispatch failed");
		return apiError(res, 503, "Publish queue unavailable. Please try again.");
	}

	return apiSuccess(
		res,
		{
			jobId: job.id,
			status: job.status,
			stage: job.stage,
			requestId,
		},
		202,
	);
}

export async function getPublishJobStatus(
	req: VercelRequest,
	res: VercelResponse,
	userId: string,
) {
	const id = typeof req.query.id === "string" ? req.query.id : "";
	if (!id) return apiError(res, 400, "id is required");
	const { data: job, error } = await getPrivilegedSupabaseAny(
		PRIVILEGED_DB_REASONS.publishQueue,
	)
		.from("publish_jobs")
		.select("id, status, stage, result, error_code, error_message, request_id, post_id, attempt_count, updated_at, completed_at")
		.eq("id", id)
		.eq("user_id", userId)
		.maybeSingle();
	if (error) return apiError(res, 500, "Failed to load publish job");
	if (!job) return apiError(res, 404, "Publish job not found");
	return apiSuccess(res, {
		jobId: job.id,
		status: job.status,
		stage: job.stage,
		result: job.result ?? null,
		errorCode: job.error_code ?? null,
		errorMessage: job.error_message ?? null,
		requestId: job.request_id ?? null,
		postId: job.post_id ?? null,
		attemptCount: job.attempt_count ?? 0,
		updatedAt: job.updated_at ?? null,
		completedAt: job.completed_at ?? null,
	});
}

export async function processPublishJob(jobId: string) {
	const supabase = getPrivilegedSupabaseAny(PRIVILEGED_DB_REASONS.publishQueue);
	const { data: job, error } = await supabase
		.from("publish_jobs")
		.select("id, user_id, status, stage, payload, attempt_count, request_id")
		.eq("id", jobId)
		.maybeSingle();
	if (error || !job) {
		throw new Error(`Publish job not found: ${jobId}`);
	}
	if (TERMINAL_STATUSES.has(job.status)) {
		return { skipped: true, status: job.status };
	}
	if (!["queued", "retrying"].includes(job.status)) {
		return { skipped: true, status: job.status };
	}

	const nextAttemptCount = (job.attempt_count || 0) + 1;
	const { data: claimedJob, error: claimError } = await supabase
		.from("publish_jobs")
		.update({
			status: "publishing",
			stage: "preflight",
			started_at: new Date().toISOString(),
			attempt_count: nextAttemptCount,
			updated_at: new Date().toISOString(),
		})
		.eq("id", job.id)
		.in("status", ["queued", "retrying"])
		.eq("attempt_count", job.attempt_count || 0)
		.select("id, user_id, status, stage, payload, attempt_count, request_id")
		.maybeSingle();

	if (claimError) {
		throw new Error(`Failed to claim publish job ${jobId}: ${String(claimError)}`);
	}
	if (!claimedJob) {
		return { skipped: true, status: "already_claimed" };
	}

	const claimed = claimedJob as typeof job;

	const { handlePublish } = await import("./handlers/posts/publish.js");
	const response = createCaptureResponse(String(claimed.request_id || ""));
	const request = {
		body: claimed.payload,
		query: { action: "publish" },
		headers: { "x-request-id": claimed.request_id },
		method: "POST",
		url: "/api/jobs?action=publish-worker",
	} as unknown as VercelRequest;

	await updatePublishJob(claimed.id, { stage: "publishing" });
	try {
		await handlePublish(
			request,
			response as unknown as VercelResponse,
			claimed.user_id,
		);
	} catch (error) {
		logger.error("[publish-jobs] Worker publish failed", {
			jobId: claimed.id,
			error: String(error),
		});
		await markPublishJobFailed(claimed.id, "PUBLISH_WORKER_ERROR", String(error));
		return { skipped: false, status: "failed" };
	}
	const body = response.body as Record<string, unknown>;

	if (response.statusCode >= 200 && response.statusCode < 300) {
		const stage = body.status === "processing" ? "processing" : "published";
		await updatePublishJob(claimed.id, {
			status: stage === "processing" ? "publishing" : "published",
			stage,
			post_id: typeof body.postId === "string" ? body.postId : null,
			result: body,
			...(stage === "processing"
				? {}
				: { completed_at: new Date().toISOString() }),
		});
		return { skipped: false, status: stage };
	}

	const message = typeof body.error === "string" ? body.error : "Publish failed";
	await markPublishJobFailed(
		claimed.id,
		typeof body.code === "string" ? body.code : "PUBLISH_FAILED",
		message,
	);
	return { skipped: false, status: "failed" };
}

async function updatePublishJob(id: string, patch: Record<string, unknown>) {
	const { error } = await getPrivilegedSupabaseAny(
		PRIVILEGED_DB_REASONS.publishQueue,
	)
		.from("publish_jobs")
		.update({ ...patch, updated_at: new Date().toISOString() })
		.eq("id", id);
	if (error) {
		logger.warn("[publish-jobs] Failed to update publish job", {
			id,
			error: String(error),
		});
	}
}

async function markPublishJobFailed(id: string, code: string, message: string) {
	await updatePublishJob(id, {
		status: "failed",
		stage: "failed",
		error_code: code,
		error_message: sanitizeErrorDetails(message),
		completed_at: new Date().toISOString(),
	});
}

function createCaptureResponse(requestId: string) {
	const headers = new Map<string, string>();
	return {
		statusCode: 200,
		body: null as unknown,
		setHeader(name: string, value: string | number) {
			headers.set(name.toLowerCase(), String(value));
			return this;
		},
		getHeader(name: string) {
			return headers.get(name.toLowerCase());
		},
		status(code: number) {
			this.statusCode = code;
			return this;
		},
		json(body: unknown) {
			this.body = body;
			return this;
		},
		end(body?: unknown) {
			this.body = body ?? this.body;
			return this;
		},
		headers,
		requestId,
	};
}
