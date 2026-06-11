/**
 * Batch event processing loops for Threads and Instagram webhook events.
 * Fetches unprocessed events from DB, dispatches to platform-specific processors,
 * handles error classification / dead-letter / retry, and broadcasts results.
 */

import type { PostgrestError, SupabaseClient } from "@supabase/supabase-js";
import { logger, serializeError } from "../../logger.js";
import { getRedis } from "../../redis.js";
import {
	calculateBackoff,
	classifyWebhookError,
	shouldRetry,
} from "../../retryUtils.js";
import { handleIgWebhookEvent } from "./ig-processors.js";
import { scheduleWebhookReplay } from "./retry.js";
import type {
	IgWebhookEvent,
	ThreadsWebhookEvent,
	WebhookEventUpdate,
} from "./shared.js";
import { MAX_EXECUTION_TIME } from "./shared.js";
import { handleThreadsWebhookEvent } from "./threads-processors.js";

export async function processThreadsWebhookEvents(
	supabase: SupabaseClient,
	startTime: number,
): Promise<number> {
	const { data: events, error: fetchError } = await supabase
		.from("threads_webhook_events")
		.select("*")
		.eq("processed", false)
		.or("dead_letter.is.null,dead_letter.eq.false")
		.or(`next_retry_at.is.null,next_retry_at.lte.${new Date().toISOString()}`)
		.order("received_at", { ascending: true })
		.limit(100);

	if (fetchError) {
		logger.warn(
			"Threads webhook events fetch error (transient, will retry next run)",
			{
				error: fetchError.message,
			},
		);
		return 0;
	}

	if (!events || events.length === 0) {
		return 0;
	}

	let processedCount = 0;
	let errorCount = 0;
	const successIds: string[] = [];
	const successEvents: ThreadsWebhookEvent[] = [];

	for (const event of events) {
		if (Date.now() - startTime > MAX_EXECUTION_TIME) {
			logger.warn(
				"[webhook-processor] Threads: time budget exhausted, deferring remaining events",
				{
					processed: processedCount,
					remaining: events.length - processedCount,
				},
			);
			break;
		}
		try {
			await handleThreadsWebhookEvent(supabase, event);

			successIds.push(event.id);
			successEvents.push(event as ThreadsWebhookEvent);
			processedCount++;
		} catch (err: unknown) {
			logger.error("Error processing Threads event", {
				eventId: event.id,
				error: serializeError(err),
			});
			try {
				const { captureServerException } = await import(
					"../../sentryServer.js"
				);
				await captureServerException(err, {
					cronJob: "webhook-processor",
					platform: "threads",
					eventId: event.id,
					eventType: event.event_type,
				});
			} catch (_sentryErr) {
				logger.warn("[webhook-processor] Sentry capture failed", {
					error: String(_sentryErr),
				});
			}

			const retryCount = event.retry_count || 0;
			const errorClass = classifyWebhookError(err);
			if (errorClass === "permanent" || !shouldRetry(retryCount)) {
				const dlqReason =
					errorClass === "permanent"
						? `Permanent error (no retry): ${serializeError(err)}`
						: `Exhausted ${retryCount} retries: ${serializeError(err)}`;
				await supabase
					.from("threads_webhook_events")
					.update({
						processed: true,
						processed_at: new Date().toISOString(),
						error: serializeError(err),
						dead_letter: true,
						dead_letter_at: new Date().toISOString(),
						dead_letter_reason: dlqReason,
					} as WebhookEventUpdate)
					.eq("id", event.id);

				logger.warn("Threads event moved to dead letter queue", {
					eventId: event.id,
					retryCount,
					errorClass,
				});
			} else {
				const nextRetryAt = calculateBackoff(retryCount);
				await supabase
					.from("threads_webhook_events")
					.update({
						error: serializeError(err),
						retry_count: retryCount + 1,
						next_retry_at: nextRetryAt.toISOString(),
					})
					.eq("id", event.id);

				const delaySeconds = Math.max(
					30,
					Math.round((nextRetryAt.getTime() - Date.now()) / 1000),
				);
				await scheduleWebhookReplay("threads", delaySeconds);
				logger.info("Threads event scheduled for retry", {
					eventId: event.id,
					retryAttempt: retryCount + 1,
				});
			}

			errorCount++;
		}
	}

	// Batch-mark all successfully processed events in one query (with retry)
	if (successIds.length > 0) {
		let markError: { message: string } | null = null;
		for (let markAttempt = 0; markAttempt < 2; markAttempt++) {
			const result = await supabase
				.from("threads_webhook_events")
				.update({ processed: true, processed_at: new Date().toISOString() })
				.in("id", successIds);
			markError = result.error;
			if (!markError) break;
			if (markAttempt === 0) await new Promise((r) => setTimeout(r, 1000));
		}
		if (markError) {
			logger.error("Batch mark failed after retry", {
				error: markError.message,
				count: successIds.length,
			});
		}
	}

	// Broadcast events so frontend can update live
	if (processedCount > 0) {
		// Look up owning user_ids for scoped broadcast channels
		const processedThreadsUserIds = [
			...new Set(successEvents.map((e) => e.threads_user_id)),
		];
		const { data: accountRows } = (await supabase
			.from("accounts")
			.select("user_id, threads_user_id")
			.in("threads_user_id", processedThreadsUserIds)) as {
			data: Array<{ user_id: string; threads_user_id: string }> | null;
			error: PostgrestError | null;
		};
		const threadsToUser = new Map(
			(accountRows || []).map((a) => [a.threads_user_id, a.user_id]),
		);

		// Broadcast per-user individual events + batch summary
		const userIds = new Set((accountRows || []).map((a) => a.user_id));
		for (const userId of userIds) {
			try {
				// Individual events for this user
				const userEvents = successEvents.filter(
					(e) => threadsToUser.get(e.threads_user_id) === userId,
				);
				for (const evt of userEvents) {
					await supabase
						.channel(`webhook-events:${userId}`)
						.httpSend("threads_event", {
							event_type: evt.event_type,
							threads_user_id: evt.threads_user_id,
							event_id: evt.id,
						});
				}
				// Batch summary
				await supabase
					.channel(`webhook-events:${userId}`)
					.httpSend("batch_processed", {
						platform: "threads",
						count: userEvents.length,
					});
			} catch (broadcastErr) {
				logger.debug(
					"[webhook-processor] Threads broadcast failed (non-blocking)",
					{
						userId,
						error:
							broadcastErr instanceof Error
								? broadcastErr.message
								: String(broadcastErr),
					},
				);
			}
		}

		// Set Redis webhook-active keys for each processed account
		try {
			const redis = getRedis();
			for (const threadsUserId of processedThreadsUserIds) {
				await redis.set(
					`webhook-active:${threadsUserId}`,
					Date.now().toString(),
					{ ex: 900 },
				);
			}
		} catch (redisErr) {
			logger.debug(
				"[webhook-processor] Redis webhook-active set failed (non-blocking)",
				{
					error:
						redisErr instanceof Error ? redisErr.message : String(redisErr),
				},
			);
		}
	}

	logger.info("Threads webhook processing complete", {
		processedCount,
		errorCount,
	});

	return processedCount;
}

export async function processIgWebhookEvents(
	supabase: SupabaseClient,
	startTime: number,
): Promise<number> {
	const { data: events, error: fetchError } = await supabase
		.from("ig_webhook_events")
		.select("*")
		.eq("processed", false)
		.or("dead_letter.is.null,dead_letter.eq.false")
		.or(`next_retry_at.is.null,next_retry_at.lte.${new Date().toISOString()}`)
		.order("received_at", { ascending: true })
		.limit(100);

	if (fetchError) {
		logger.warn(
			"IG webhook events fetch error (transient, will retry next run)",
			{
				error: fetchError.message,
			},
		);
		return 0;
	}

	if (!events || events.length === 0) {
		return 0;
	}

	let processedCount = 0;
	let errorCount = 0;
	const successIds: string[] = [];
	const successEvents: IgWebhookEvent[] = [];

	for (const event of events) {
		if (Date.now() - startTime > MAX_EXECUTION_TIME) {
			logger.warn(
				"[webhook-processor] IG: time budget exhausted, deferring remaining events",
				{
					processed: processedCount,
					remaining: events.length - processedCount,
				},
			);
			break;
		}
		try {
			await handleIgWebhookEvent(supabase, event);

			successIds.push(event.id);
			successEvents.push(event as IgWebhookEvent);
			processedCount++;
		} catch (err: unknown) {
			logger.error("Error processing IG event", {
				eventId: event.id,
				error: serializeError(err),
			});
			try {
				const { captureServerException } = await import(
					"../../sentryServer.js"
				);
				await captureServerException(err, {
					cronJob: "webhook-processor",
					platform: "instagram",
					eventId: event.id,
					eventType: event.event_type,
				});
			} catch (_sentryErr) {
				logger.warn("[webhook-processor] Sentry capture failed", {
					error: String(_sentryErr),
				});
			}

			const retryCount = event.retry_count || 0;
			const errorClass = classifyWebhookError(err);
			if (errorClass === "permanent" || !shouldRetry(retryCount)) {
				const dlqReason =
					errorClass === "permanent"
						? `Permanent error (no retry): ${serializeError(err)}`
						: `Exhausted ${retryCount} retries: ${serializeError(err)}`;
				await supabase
					.from("ig_webhook_events")
					.update({
						processed: true,
						processed_at: new Date().toISOString(),
						error: serializeError(err),
						last_error: serializeError(err),
						dead_letter: true,
						dead_letter_at: new Date().toISOString(),
						dead_letter_reason: dlqReason,
					} as WebhookEventUpdate)
					.eq("id", event.id);
				logger.warn("IG event moved to dead letter queue", {
					eventId: event.id,
					retryCount,
					errorClass,
				});
			} else {
				const nextRetryAt = calculateBackoff(retryCount);
				await supabase
					.from("ig_webhook_events")
					.update({
						error: serializeError(err),
						last_error: serializeError(err),
						retry_count: retryCount + 1,
						next_retry_at: nextRetryAt.toISOString(),
					})
					.eq("id", event.id);
				const delaySeconds = Math.max(
					30,
					Math.round((nextRetryAt.getTime() - Date.now()) / 1000),
				);
				await scheduleWebhookReplay("instagram", delaySeconds);
				logger.info("IG event scheduled for retry", {
					eventId: event.id,
					retryAttempt: retryCount + 1,
				});
			}

			errorCount++;
		}
	}

	// Batch-mark all successfully processed events in one query (with retry)
	if (successIds.length > 0) {
		let markError: { message: string } | null = null;
		for (let markAttempt = 0; markAttempt < 2; markAttempt++) {
			const result = await supabase
				.from("ig_webhook_events")
				.update({ processed: true, processed_at: new Date().toISOString() })
				.in("id", successIds);
			markError = result.error;
			if (!markError) break;
			if (markAttempt === 0) await new Promise((r) => setTimeout(r, 1000));
		}
		if (markError) {
			logger.error("Batch mark failed after retry", {
				error: markError.message,
				count: successIds.length,
			});
		}
	}

	// Broadcast events so frontend can update live
	if (processedCount > 0) {
		// Look up owning user_ids for scoped broadcast channels
		const processedIgUserIds = [
			...new Set(successEvents.map((e) => e.ig_user_id)),
		];

		// IG accounts may be in accounts (cross-posted) or instagram_accounts
		const { data: igAccountRows } = await supabase
			.from("instagram_accounts")
			.select("user_id, instagram_user_id")
			.in("instagram_user_id", processedIgUserIds);
		const igToUser = new Map(
			(igAccountRows || []).map(
				(a: { instagram_user_id: string; user_id: string }) => [
					a.instagram_user_id,
					a.user_id,
				],
			),
		);

		// Broadcast per-user individual events + batch summary
		const userIds = new Set(
			(igAccountRows || []).map((a: { user_id: string }) => a.user_id),
		);
		for (const userId of userIds) {
			try {
				const userEvents = successEvents.filter(
					(e) => igToUser.get(e.ig_user_id) === userId,
				);
				for (const evt of userEvents) {
					await supabase
						.channel(`webhook-events:${userId}`)
						.httpSend("ig_event", {
							event_type: evt.event_type,
							ig_user_id: evt.ig_user_id,
							event_id: evt.id,
						});
				}
				await supabase
					.channel(`webhook-events:${userId}`)
					.httpSend("batch_processed", {
						platform: "instagram",
						count: userEvents.length,
					});
			} catch (broadcastErr) {
				logger.debug("[webhook-processor] IG broadcast failed (non-blocking)", {
					userId,
					error:
						broadcastErr instanceof Error
							? broadcastErr.message
							: String(broadcastErr),
				});
			}
		}

		// Set Redis webhook-active keys for each processed account
		try {
			const redis = getRedis();
			for (const igUserId of processedIgUserIds) {
				await redis.set(
					`webhook-active:ig:${igUserId}`,
					Date.now().toString(),
					{ ex: 900 },
				);
			}
		} catch (redisErr) {
			logger.debug(
				"[webhook-processor] Redis webhook-active set failed (non-blocking)",
				{
					error:
						redisErr instanceof Error ? redisErr.message : String(redisErr),
				},
			);
		}
	}

	logger.info("IG webhook processing complete", { processedCount, errorCount });

	return processedCount;
}
