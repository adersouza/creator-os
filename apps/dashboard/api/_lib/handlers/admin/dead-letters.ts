/**
 * Dead Letter Queue Admin API
 *
 * GET  /api/admin/dead-letters         — List all DLQ items
 * POST /api/admin/dead-letters          — Actions: retry, purge, purge-all
 *
 * Requires admin/owner role via withAdminRole middleware.
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";
import { apiError, apiSuccess } from "../../apiResponse.js";
import { logAudit } from "../../auditLog.js";
import { withIdempotency } from "../../idempotency.js";
import { logger } from "../../logger.js";
import { withAdminRole } from "../../middleware.js";
import { getSupabase } from "../../supabase.js";
import { z, zEnum } from "../../zodCompat.js";

type SupabaseClient = ReturnType<typeof getSupabase>;

interface DlqWebhookEvent {
	id: string;
	event_type: string;
	error: string | null;
	dead_letter_at: string | null;
	dead_letter_reason: string | null;
	retry_count: number | null;
	received_at: string | null;
}

interface DlqQueueEvent {
	id: string;
	account_id: string | null;
	last_error: string | null;
	retry_count: number | null;
	created_at: string | null;
}

interface DlqContainerEvent {
	id: string;
	post_id: string | null;
	container_id: string | null;
	error: string | null;
	dead_letter_at: string | null;
	dead_letter_reason: string | null;
	check_count: number | null;
	created_at: string | null;
}

const DeadLetterActionSchema = z.object({
	action: zEnum(["retry", "purge", "purge-all"], {
		message: "action must be retry, purge, or purge-all",
	}),
	source: z.string().optional(),
	itemId: z.string().optional(),
});

export default withAdminRole(
	async (req: VercelRequest, res: VercelResponse, user) => {
		// #671: Rate limit admin endpoints
		const { checkRateLimit } = await import("../../rateLimiter.js");
		const rl = await checkRateLimit({
			key: `admin-dlq:${user.id}`,
			limit: 30,
			windowSeconds: 60,
			failMode: "open",
		});
		if (!rl.allowed) return apiError(res, 429, "Rate limit exceeded");

		const supabase = getSupabase();

		// Verify user has an active paid subscription (not free tier)
		const { data: subProfile } = await supabase
			.from("profiles")
			.select("subscription_tier")
			.eq("id", user.id)
			.maybeSingle();

		if (!subProfile || subProfile.subscription_tier === "free") {
			return apiError(
				res,
				403,
				"Active paid subscription required for DLQ management",
			);
		}

		if (req.method === "GET") {
			return listDeadLetters(res, supabase);
		}

		if (req.method === "POST") {
			const parsed = DeadLetterActionSchema.safeParse(req.body);
			if (!parsed.success) {
				return apiError(
					res,
					400,
					`Invalid input: ${parsed.error.issues[0]?.message}`,
				);
			}

			const { action, source, itemId } = parsed.data;

			return withIdempotency(
				req,
				res,
				{
					userId: user.id,
					route: "admin/dead-letters",
					action: `${action}:${source ?? "all"}`,
					enabled: true,
					requireKey: true,
					failClosed: true,
				},
				async () => {
					switch (action) {
						case "retry":
							return retryItem(res, supabase, source ?? "", itemId ?? "", user.id);
						case "purge":
							return purgeItem(res, supabase, source ?? "", itemId ?? "", user.id);
						case "purge-all":
							return purgeAll(res, supabase, source, user.id);
						default:
							return apiError(res, 400, `Unknown action: ${action}`);
					}
				},
			);
		}

		return apiError(res, 405, "Method not allowed");
	},
);

// #670: Sanitize error strings — strip stack traces and sensitive data
function sanitizeReason(reason: string | null | undefined): string | null {
	if (!reason) return null;
	return reason
		.replace(/\n\s*at .+/g, "")
		.replace(/access_token=[^\s&]+/gi, "access_token=[REDACTED]")
		.replace(/Bearer\s+[A-Za-z0-9._-]+/g, "Bearer [REDACTED]")
		.trim()
		.slice(0, 500);
}

async function listDeadLetters(res: VercelResponse, supabase: SupabaseClient) {
	// Query dead letter items from each table
	const [threadsResult, igResult, queueResult, containerResult] =
		await Promise.all([
			supabase
				.from("threads_webhook_events")
				.select(
					"id, event_type, error, dead_letter_at, dead_letter_reason, retry_count, received_at",
				)
				.eq("dead_letter", true)
				.order("dead_letter_at", { ascending: false })
				.limit(50),
			supabase
				.from("ig_webhook_events")
				.select(
					"id, event_type, error, dead_letter_at, dead_letter_reason, retry_count, received_at",
				)
				.eq("dead_letter", true)
				.order("dead_letter_at", { ascending: false })
				.limit(50),
			supabase
				.from("auto_post_queue")
				.select("id, account_id, last_error, retry_count, created_at")
				.eq("status", "dead_letter")
				.order("created_at", { ascending: false })
				.limit(50),
			supabase
				.from("ig_pending_containers")
				.select(
					"id, post_id, container_id, error, dead_letter_at, dead_letter_reason, check_count, created_at",
				)
				.eq("dead_letter", true)
				.order("dead_letter_at", { ascending: false })
				.limit(50),
		]);

	const items = [
		...((threadsResult.data || []) as DlqWebhookEvent[]).map((e) => ({
			source: "threads_webhook",
			id: e.id,
			type: e.event_type,
			reason: sanitizeReason(e.dead_letter_reason || e.error),
			deadLetterAt: e.dead_letter_at,
			retryCount: e.retry_count,
			receivedAt: e.received_at,
		})),
		...((igResult.data || []) as DlqWebhookEvent[]).map((e) => ({
			source: "ig_webhook",
			id: e.id,
			type: e.event_type,
			reason: sanitizeReason(e.dead_letter_reason || e.error),
			deadLetterAt: e.dead_letter_at,
			retryCount: e.retry_count,
			receivedAt: e.received_at,
		})),
		...((queueResult.data || []) as unknown as DlqQueueEvent[]).map((e) => ({
			source: "auto_post_queue",
			id: e.id,
			type: "auto_post",
			reason: sanitizeReason(e.last_error),
			deadLetterAt: e.created_at,
			retryCount: e.retry_count,
			receivedAt: e.created_at,
		})),
		...((containerResult.data || []) as DlqContainerEvent[]).map((e) => ({
			source: "ig_container",
			id: e.id,
			type: "container_publish",
			reason: sanitizeReason(e.dead_letter_reason || e.error),
			deadLetterAt: e.dead_letter_at,
			retryCount: e.check_count,
			receivedAt: e.created_at,
		})),
	];

	// Sort by dead letter time, newest first
	items.sort(
		(a, b) =>
			new Date(b.deadLetterAt ?? 0).getTime() -
			new Date(a.deadLetterAt ?? 0).getTime(),
	);

	return apiSuccess(res, {
		items,
		total: items.length,
		generatedAt: new Date().toISOString(),
	});
}

async function verifyItemOwnership(
	supabase: SupabaseClient,
	userId: string,
	source: string,
	itemId: string,
): Promise<boolean> {
	try {
		// For auto_post_queue, check that the account belongs to the user
		if (source === "auto_post_queue") {
			const { data: item } = await supabase
				.from("auto_post_queue")
				.select("account_id")
				.eq("id", itemId)
				.maybeSingle();
			if (!item?.account_id) return false;
			const { data: account } = await supabase
				.from("accounts")
				.select("user_id")
				.eq("id", item.account_id)
				.maybeSingle();
			return account?.user_id === userId;
		}

		// For ig_container, check that the post belongs to the user
		if (source === "ig_container") {
			const { data: item } = await supabase
				.from("ig_pending_containers")
				.select("post_id")
				.eq("id", itemId)
				.maybeSingle();
			if (!item?.post_id) return false;
			const { data: post } = await supabase
				.from("posts")
				.select("user_id")
				.eq("id", item.post_id)
				.maybeSingle();
			return post?.user_id === userId;
		}

		if (source === "threads_webhook") {
			const { data: item } = await supabase
				.from("threads_webhook_events")
				.select("threads_user_id")
				.eq("id", itemId)
				.maybeSingle();
			if (!item?.threads_user_id) return false;
			const { data: account } = await supabase
				.from("accounts")
				.select("user_id")
				.eq("threads_user_id", item.threads_user_id)
				.maybeSingle();
			return account?.user_id === userId;
		}

		if (source === "ig_webhook") {
			const { data: item } = await supabase
				.from("ig_webhook_events")
				.select("ig_user_id")
				.eq("id", itemId)
				.maybeSingle();
			if (!item?.ig_user_id) return false;
			const { data: account } = await supabase
				.from("instagram_accounts")
				.select("user_id")
				.eq("instagram_user_id", item.ig_user_id)
				.maybeSingle();
			return account?.user_id === userId;
		}

		return false;
	} catch {
		return false;
	}
}

async function retryItem(
	res: VercelResponse,
	supabase: SupabaseClient,
	source: string,
	itemId: string,
	userId: string,
) {
	if (!source || !itemId) {
		return apiError(res, 400, "source and itemId are required");
	}

	// Verify ownership for user-scoped resources
	const hasAccess = await verifyItemOwnership(supabase, userId, source, itemId);
	if (!hasAccess) {
		return apiError(res, 403, "You do not have access to this resource");
	}

	let webhookReplayPlatform: "threads" | "instagram" | null = null;
	switch (source) {
		case "threads_webhook":
			await supabase
				.from("threads_webhook_events")
				.update({
					processed: false,
					processed_at: null,
					dead_letter: false,
					dead_letter_at: null,
					dead_letter_reason: null,
					retry_count: 0,
					error: null,
					next_retry_at: null,
				})
				.eq("id", itemId);
			webhookReplayPlatform = "threads";
			break;

		case "ig_webhook":
			await supabase
				.from("ig_webhook_events")
				.update({
					processed: false,
					processed_at: null,
					dead_letter: false,
					dead_letter_at: null,
					dead_letter_reason: null,
					retry_count: 0,
					error: null,
					last_error: null,
					next_retry_at: null,
				})
				.eq("id", itemId);
			webhookReplayPlatform = "instagram";
			break;

		case "auto_post_queue":
			await supabase
				.from("auto_post_queue")
				.update({
					status: "pending",
					retry_count: 0,
					last_error: null,
					next_retry_at: null,
				})
				.eq("id", itemId);
			break;

		case "ig_container":
			await supabase
				.from("ig_pending_containers")
				.update({
					status: "pending",
					dead_letter: false,
					dead_letter_at: null,
					dead_letter_reason: null,
					error: null,
					check_count: 0,
				})
				.eq("id", itemId);
			break;

		default:
			return apiError(res, 400, `Unknown source: ${source}`);
	}

	if (webhookReplayPlatform) {
		const { scheduleWebhookReplay } = await import(
			"../../cron/webhook-processor/retry.js"
		);
		await scheduleWebhookReplay(webhookReplayPlatform, 5);
	}

	void logAudit(userId, "admin.dead-letter.retry", {
		metadata: {
			source,
			itemId,
			webhookReplayPlatform,
		},
	});

	return apiSuccess(res, {
		retried: itemId,
		...(webhookReplayPlatform
			? { replayScheduledFor: webhookReplayPlatform }
			: {}),
	});
}

async function purgeItem(
	res: VercelResponse,
	supabase: SupabaseClient,
	source: string,
	itemId: string,
	userId: string,
) {
	if (!source || !itemId) {
		return apiError(res, 400, "source and itemId are required");
	}

	// Verify ownership for user-scoped resources
	const hasAccess = await verifyItemOwnership(supabase, userId, source, itemId);
	if (!hasAccess) {
		return apiError(res, 403, "You do not have access to this resource");
	}

	const tableMap: Record<string, string> = {
		threads_webhook: "threads_webhook_events",
		ig_webhook: "ig_webhook_events",
		auto_post_queue: "auto_post_queue",
		ig_container: "ig_pending_containers",
	};

	const table = tableMap[source];
	if (!table) {
		return apiError(res, 400, `Unknown source: ${source}`);
	}

	// biome-ignore lint/suspicious/noExplicitAny: dynamic table name not in generated types
	const { error: deleteErr } = await (supabase as any)
		.from(table)
		.delete()
		.eq("id", itemId);
	if (deleteErr) {
		logger.warn("[dead-letters] Failed to purge item", {
			source,
			itemId,
			error: deleteErr.message,
		});
	} else {
		void logAudit(userId, "admin.dead-letter.purge", {
			metadata: { source, itemId },
		});
	}

	return apiSuccess(res, { purged: itemId });
}

async function purgeAll(
	res: VercelResponse,
	supabase: SupabaseClient,
	source: string | undefined,
	userId: string,
) {
	if (source) {
		// Purge all DLQ items from a specific source
		switch (source) {
			case "threads_webhook":
				await supabase
					.from("threads_webhook_events")
					.delete()
					.eq("dead_letter", true);
				break;
			case "ig_webhook":
				await supabase
					.from("ig_webhook_events")
					.delete()
					.eq("dead_letter", true);
				break;
			case "auto_post_queue":
				await supabase
					.from("auto_post_queue")
					.delete()
					.eq("status", "dead_letter");
				break;
			case "ig_container":
				await supabase
					.from("ig_pending_containers")
					.delete()
					.eq("dead_letter", true);
				break;
			default:
				return apiError(res, 400, `Unknown source: ${source}`);
		}
	} else {
		// Purge all DLQ items from all sources
		await Promise.all([
			supabase.from("threads_webhook_events").delete().eq("dead_letter", true),
			supabase.from("ig_webhook_events").delete().eq("dead_letter", true),
			supabase.from("auto_post_queue").delete().eq("status", "dead_letter"),
			supabase.from("ig_pending_containers").delete().eq("dead_letter", true),
		]);
	}

	void logAudit(userId, "admin.dead-letter.purge-all", {
		metadata: { source: source || "all" },
	});
	return apiSuccess(res, { purgedSource: source || "all" });
}
