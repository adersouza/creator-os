/**
 * Dispatch QStash messages for queue items missing them.
 *
 * POST /api/dispatch-manual-queue
 * Auth: cron auth (CRON_SECRET)
 *
 * Finds all pending items in auto_post_queue that don't have a
 * qstash_message_id yet and dispatches QStash delayed publish
 * for each one at their exact scheduled_for time.
 *
 * Works for ANY source_type — not just manual inserts.
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";
import { apiError, apiSuccess, verifyCronAuth } from "./_lib/apiResponse.js";
import { logger } from "./_lib/logger.js";
import { getSupabase } from "./_lib/supabase.js";

// biome-ignore lint/suspicious/noExplicitAny: auto_post_queue columns not in generated Supabase types
const db = (): any => getSupabase();

export default async function handler(req: VercelRequest, res: VercelResponse) {
	// POST-only: this handler enqueues QStash dispatches (mutating). Allowing
	// GET made replays via referrer/log leak possible — anyone re-firing the
	// URL would re-create dispatches. Cron auth still required.
	if (req.method !== "POST") {
		return apiError(res, 405, "Method not allowed");
	}

	if (!verifyCronAuth(req, res)) return;

	try {
		const { getQStashClient } = await import("./_lib/qstash.js");
		const { RETRIES, getFailureCallbackUrl, getRequiredAppBaseUrl } =
			await import("./_lib/qstashDefaults.js");
		const { recordInfraEvent } = await import("./_lib/infraTelemetry.js");
		const qstash = getQStashClient();
		const baseUrl = getRequiredAppBaseUrl();
		const failureCb = getFailureCallbackUrl();

		// Get all pending items without QStash dispatch
		const { data: items, error } = await db()
			.from("auto_post_queue")
			.select("id, workspace_id, group_id, scheduled_for, schedule_nonce")
			.eq("status", "pending")
			.is("qstash_message_id", null)
			.order("scheduled_for", { ascending: true })
			.limit(100);

		if (error) {
			logger.error("Failed to fetch queue items for dispatch", {
				error: String(error),
			});
			return apiError(res, 500, "DB error");
		}

		if (!items || items.length === 0) {
			return apiSuccess(res, {
				dispatched: 0,
				message: "No items to dispatch",
			});
		}

		// Pre-fetch all group names + owners in one query so each item is dispatched
		// with the correct owner context for its own group.
		const groupIds = [
			...new Set(items.map((i: { group_id: string }) => i.group_id)),
		];
		const { data: groups } = await db()
			.from("account_groups")
			.select("id, name, user_id")
			.in("id", groupIds);

		const groupInfoMap = new Map<
			string,
			{ name: string; userId: string | null }
		>();
		if (groups) {
			for (const g of groups) {
				groupInfoMap.set(g.id, { name: g.name, userId: g.user_id ?? null });
			}
		}

		let dispatched = 0;
		let failed = 0;

		for (const item of items) {
			try {
				const scheduledUnix = Math.floor(
					new Date(item.scheduled_for).getTime() / 1000,
				);
				const groupInfo = groupInfoMap.get(item.group_id);
				const groupName = groupInfo?.name || "unknown";
				const ownerId = groupInfo?.userId;
				if (!ownerId) {
					throw new Error(`No owner found for group ${item.group_id}`);
				}
				const scheduleNonce =
					(item.schedule_nonce as string | null) ||
					`manual-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;

				const result = await qstash.publishJSON({
					url: `${baseUrl}/api/auto-post-publish`,
					body: {
						queueItemId: item.id,
						workspaceId: item.workspace_id,
						groupId: item.group_id,
						ownerId,
						groupName,
						scheduleNonce,
					},
					notBefore: scheduledUnix,
					retries: RETRIES.CRITICAL,
					deduplicationId: scheduleNonce,
					failureCallback: failureCb,
				});

				await db()
					.from("auto_post_queue")
					.update({
						qstash_message_id: result.messageId,
						schedule_nonce: scheduleNonce,
					})
					.eq("id", item.id);
				await recordInfraEvent("autopost-manual-dispatch", {
					queueItemId: item.id,
					scheduleNonce,
					qstashMessageId: result.messageId,
					groupId: item.group_id,
					workspaceId: item.workspace_id,
				});

				dispatched++;
			} catch (err) {
				await recordInfraEvent("autopost-manual-dispatch-failed", {
					queueItemId: item.id,
					scheduleNonce: item.schedule_nonce,
					groupId: item.group_id,
					workspaceId: item.workspace_id,
					error: String(err),
				});
				logger.warn("QStash dispatch failed", {
					queueItemId: item.id,
					error: String(err),
				});
				failed++;
			}
		}

		logger.info("Queue dispatch complete", {
			dispatched,
			failed,
			total: items.length,
		});
		return apiSuccess(res, { dispatched, failed, total: items.length });
	} catch (err) {
		logger.error("dispatch-manual-queue error", { error: String(err) });
		return apiError(res, 500, "Failed to dispatch queue", {
			details: err instanceof Error ? err.message : String(err),
		});
	}
}
