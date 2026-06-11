/**
 * Publish Worker — publishing cron (every 5 min)
 *
 * Phase 1: scheduled-posts        — publish posts where scheduled_for <= NOW()
 * Phase 2: ig-container-publisher  — check & publish pending IG containers
 * Phase 3: queue-reconciliation    — re-dispatch stranded auto_post_queue items via QStash
 * Phase 4: queue-fill-check        — safety-net AI fill for groups below queue threshold
 *
 * Auto-reply and reply-farming moved to dedicated crons (2026-04-04):
 * - auto-reply-worker.ts (every 15 min)
 * - reply-farming-worker.ts (every 30 min)
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";

export const config = {
	maxDuration: 180,
};

const JOB_NAME = "publish-worker";
const MAX_EXECUTION_TIME = 170_000; // 170s of 180s budget

function hasTimeBudget(startTime: number): boolean {
	return Date.now() - startTime < MAX_EXECUTION_TIME;
}

export default async function handler(req: VercelRequest, res: VercelResponse) {
	const { verifyCronAuth } = await import("../_lib/apiResponse.js");
	if (!verifyCronAuth(req, res)) return;

	const { withCronLock, trackCronRun } = await import("../_lib/cronUtils.js");
	const { isAutoposterHardDisabled } = await import(
		"../_lib/handlers/auto-post/killSwitch.js"
	);
	const {
		ensureQueueItemScheduleNonce,
		markQueueItemDispatched,
		recordPublishAttempt,
	} =
		await import("../_lib/handlers/auto-post/queueState.js");
	const { getPrivilegedSupabaseAny, PRIVILEGED_DB_REASONS } = await import(
		"../_lib/privilegedDb.js"
	);
	const { logger, serializeError } = await import("../_lib/logger.js");
	const { alertCronFailure } = await import("../_lib/alerting.js");

	const supabase = getPrivilegedSupabaseAny(
		PRIVILEGED_DB_REASONS.publishExecution,
	);
	const internalCronSecret = process.env.CRON_SECRET;
	const globalStart = Date.now();

	const lockResult = await withCronLock(
		supabase,
		JOB_NAME,
		async () => {
			return trackCronRun(supabase, JOB_NAME, async () => {
				const metadataPhases: Record<string, unknown> = {};
				const metadata: Record<string, unknown> = { phases: metadataPhases };
				let totalItems = 0;

				// ── Phase 1: Scheduled Posts ──
				try {
					logger.info(`[${JOB_NAME}] Phase 1/4: Scheduled Posts — starting`);
					const p1Start = Date.now();

					const { processScheduledPosts } = await import(
						"../_lib/cron/scheduled-posts.js"
					);
					const count = await processScheduledPosts();

					metadataPhases.scheduledPosts = {
						status: "completed",
						items_processed: count,
						phase_duration_ms: Date.now() - p1Start,
					};
					totalItems += count;
					logger.info(`[${JOB_NAME}] Phase 1/4: Scheduled Posts — complete`, {
						items: count,
						durationMs: Date.now() - p1Start,
					});
				} catch (err) {
					const errMsg = serializeError(err);
					metadataPhases.scheduledPosts = {
						status: "error",
						error: errMsg,
						phase_duration_ms: Date.now() - globalStart,
					};
					logger.error(`[${JOB_NAME}] Phase 1/4: Scheduled Posts — failed`, {
						error: errMsg,
					});
					try {
						const { captureServerException } = await import(
							"../_lib/sentryServer.js"
						);
						await captureServerException(err, {
							cronJob: JOB_NAME,
							phase: "scheduled-posts",
						});
					} catch {
						/* sentry best-effort */
					}
					alertCronFailure(JOB_NAME, `scheduled-posts: ${errMsg}`);
				}

				// ── Phase 2: IG Container Publisher ──
				if (!hasTimeBudget(globalStart)) {
					logger.warn(
						`[${JOB_NAME}] Skipping phases 2-5 — time budget exhausted`,
					);
					metadataPhases.skippedAfterPhase = 1;
					metadata.totalDurationMs = Date.now() - globalStart;
					return { itemsProcessed: totalItems, metadata };
				}
				try {
					logger.info(
						`[${JOB_NAME}] Phase 2/4: IG Container Publisher — starting`,
					);
					const p2Start = Date.now();

					const { processPendingContainers } = await import(
						"../_lib/cron/ig-container-publisher.js"
					);
					const count = await processPendingContainers(supabase);

					metadataPhases.igContainerPublisher = {
						status: "completed",
						items_processed: count,
						phase_duration_ms: Date.now() - p2Start,
					};
					totalItems += count;
					logger.info(
						`[${JOB_NAME}] Phase 2/4: IG Container Publisher — complete`,
						{
							items: count,
							durationMs: Date.now() - p2Start,
						},
					);
				} catch (err) {
					const errMsg = serializeError(err);
					metadataPhases.igContainerPublisher = {
						status: "error",
						error: errMsg,
						phase_duration_ms: Date.now() - globalStart,
					};
					logger.error(
						`[${JOB_NAME}] Phase 2/4: IG Container Publisher — failed`,
						{ error: errMsg },
					);
					try {
						const { captureServerException } = await import(
							"../_lib/sentryServer.js"
						);
						await captureServerException(err, {
							cronJob: JOB_NAME,
							phase: "ig-container-publisher",
						});
					} catch {
						/* sentry best-effort */
					}
					alertCronFailure(JOB_NAME, `ig-container-publisher: ${errMsg}`);
				}

				const autoposterHardDisabled = isAutoposterHardDisabled();

				// ── Phases 3-4: Run for all enabled workspaces ──
				let enabledWorkspaceIds: string[] = [];
				let enabledWorkspaceConfigs: Array<{
					workspace_id: string;
					scheduler_version?: number | null | undefined;
					group_mode_enabled: boolean;
					enable_ai_queue_fill: boolean;
				}> = [];
				if (autoposterHardDisabled) {
					metadataPhases.queueReconciliation = {
						status: "skipped",
						reason: "autoposter_hard_disabled",
					};
					metadataPhases.queueFill = {
						status: "skipped",
						reason: "autoposter_hard_disabled",
					};
					metadata.totalDurationMs = Date.now() - globalStart;
					logger.warn(
						`[${JOB_NAME}] Skipping autoposter phases — global hard disable`,
					);
					return { itemsProcessed: totalItems, metadata };
				}

				try {
					const { data: schedCfg } = await supabase
						.from("auto_post_config")
						.select(
							"workspace_id, scheduler_version, group_mode_enabled, enable_ai_queue_fill",
						)
						.eq("is_enabled", true);
					enabledWorkspaceConfigs = (schedCfg ?? []) as Array<{
						workspace_id: string;
						scheduler_version?: number | null | undefined;
						group_mode_enabled: boolean;
						enable_ai_queue_fill: boolean;
					}>;
					enabledWorkspaceIds = enabledWorkspaceConfigs.map(
						(cfg) => cfg.workspace_id,
					);
				} catch {
					/* default to v1 */
				}

				// ── Phase 3: Auto-Post Queue Reconciliation ──
				// First repair rows where Meta publish succeeded but local finalization
				// failed. Then catch rows where QStash dispatch failed or a dispatched
				// queue item never fired. auto-post-publish claims atomically, so safe
				// re-dispatch is idempotent even if an old QStash message eventually arrives.
				if (enabledWorkspaceIds.length === 0) {
					metadataPhases.queueReconciliation = {
						status: "skipped",
						reason: "no_enabled_workspaces",
					};
					metadataPhases.queueFill = {
						status: "skipped",
						reason: "no_enabled_workspaces",
					};
					metadata.totalDurationMs = Date.now() - globalStart;
					return { itemsProcessed: totalItems, metadata };
				}
				if (!hasTimeBudget(globalStart)) {
					logger.warn(
						`[${JOB_NAME}] Skipping phases 3-5 — time budget exhausted`,
					);
					metadataPhases.skippedAfterPhase = 2;
					metadata.totalDurationMs = Date.now() - globalStart;
					return { itemsProcessed: totalItems, metadata };
				}
				try {
					logger.info(
						`[${JOB_NAME}] Phase 3/4: Queue Reconciliation — starting`,
					);
					const p3Start = Date.now();

					const { dispatchEngagementFetch } = await import(
						"../_lib/qstashSchedule.js"
					);
					const { recordInfraEvent } = await import(
						"../_lib/infraTelemetry.js"
					);

					const { data: localFinalizeRows } = await supabase
						.from("auto_post_queue")
						.select(
							"id, workspace_id, group_id, account_id, status, threads_post_id, external_published_at, finalize_error",
						)
						.in("workspace_id", enabledWorkspaceIds)
						.in("status", [
							"needs_reconciliation",
							"external_published_local_finalize_failed",
						])
						.not("threads_post_id", "is", null)
						.order("external_published_at", {
							ascending: true,
							nullsFirst: false,
						})
						.limit(25);

					let localFinalizeReconciled = 0;
					let localFinalizeFailed = 0;
					for (const item of (localFinalizeRows ?? []) as Array<{
						id: string;
						workspace_id: string;
						group_id: string;
						account_id: string | null;
						status: string;
						threads_post_id: string | null;
						external_published_at: string | null;
						finalize_error: string | null;
					}>) {
						if (!item.threads_post_id) continue;
						try {
							const { data, error } = await supabase.rpc(
								"reconcile_autoposter_publish",
								{ p_queue_item_id: item.id },
							);
							if (error) throw error;
							const reconciledRow = Array.isArray(data) ? data[0] : data;
							const postId = reconciledRow?.post_id as string | undefined;
							if (postId && item.threads_post_id) {
								await Promise.all([
									dispatchEngagementFetch(postId, item.threads_post_id, 3600),
									dispatchEngagementFetch(postId, item.threads_post_id, 86400),
								]);
							}
							await recordInfraEvent("autopost-local-finalize-reconciled", {
								queueItemId: item.id,
								postId: postId ?? null,
								threadsPostId: item.threads_post_id,
								groupId: item.group_id,
								accountId: item.account_id,
								workspaceId: item.workspace_id,
								previousStatus: item.status,
							});
							await recordPublishAttempt({
								queueItemId: item.id,
								workspaceId: item.workspace_id,
								groupId: item.group_id,
								accountId: item.account_id,
								threadsPostId: item.threads_post_id,
								result: "reconciled",
								metadata: {
									postId: postId ?? null,
									previousStatus: item.status,
									externalPublishedAt: item.external_published_at,
								},
							});
							localFinalizeReconciled++;
						} catch (reconcileErr) {
							localFinalizeFailed++;
							await recordPublishAttempt({
								queueItemId: item.id,
								workspaceId: item.workspace_id,
								groupId: item.group_id,
								accountId: item.account_id,
								threadsPostId: item.threads_post_id,
								result: "reconcile_failed",
								errorCode: "reconcile_autoposter_publish_failed",
								errorMessage: String(reconcileErr),
								metadata: {
									previousStatus: item.status,
									externalPublishedAt: item.external_published_at,
									finalizeError: item.finalize_error,
								},
							});
							await recordInfraEvent("autopost-local-finalize-reconcile-failed", {
								queueItemId: item.id,
								threadsPostId: item.threads_post_id,
								groupId: item.group_id,
								accountId: item.account_id,
								workspaceId: item.workspace_id,
								error: String(reconcileErr),
							});
							logger.warn("Local finalize reconciliation failed", {
								queueItemId: item.id,
								status: item.status,
								error: String(reconcileErr),
							});
						}
					}

					const fiveMinAgo = new Date(Date.now() - 5 * 60 * 1000).toISOString();
					const { data: stranded } = await supabase
						.from("auto_post_queue")
						.select(
							"id, workspace_id, group_id, account_id, status, pool_status, schedule_nonce",
						)
						.in("workspace_id", enabledWorkspaceIds)
						.in("status", ["pending", "queued"])
						.lte("scheduled_for", fiveMinAgo)
						.or(
							`next_retry_at.is.null,next_retry_at.lte.${new Date().toISOString()}`,
						)
						.order("scheduled_for", { ascending: true })
						.limit(25);

					let reconciled = 0;
					if (stranded && stranded.length > 0) {
						const groupIds = [
							...new Set(stranded.map((s: { group_id: string }) => s.group_id)),
						] as string[];
						const { data: groups } = await supabase
							.from("account_groups")
							.select("id, name, user_id")
							.in("id", groupIds);
						const groupMap = new Map(
							(groups ?? []).map(
								(g: { id: string; name: string; user_id: string }) => [
									g.id,
									{ name: g.name, userId: g.user_id },
								],
							),
						);

						const { getRequiredAppBaseUrl } = await import(
							"../_lib/qstashDefaults.js"
						);
						const baseUrl = getRequiredAppBaseUrl();

						for (const item of stranded as Array<{
							id: string;
							workspace_id: string;
							group_id: string;
							account_id: string | null;
							status: string;
							pool_status: string | null;
							schedule_nonce: string | null;
						}>) {
							const group = groupMap.get(item.group_id);
							if (!group) continue;

							// Stranded rows must get a fresh dedupe key. Reusing the original
							// schedule_nonce can turn reconciliation into a no-op if QStash still
							// considers that nonce spent or deduplicated.
							const scheduleNonce = await ensureQueueItemScheduleNonce(
								item.id,
								`recon-${item.id}-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`,
							);
							if (item.schedule_nonce) {
								await supabase
									.from("auto_post_queue")
									.update({
										schedule_nonce: scheduleNonce,
										qstash_message_id: null,
										last_error:
											"Manual recovery: overdue queued/pending item reset for fresh reconciliation dispatch",
									} as Record<string, unknown>)
									.eq("id", item.id)
									.in("status", ["pending", "queued"]);
							}

							try {
								if (!internalCronSecret) {
									throw new Error(
										"CRON_SECRET not configured for reconciliation invoke",
									);
								}
								const controller = new AbortController();
								const fetchTimeoutId = setTimeout(
									() => controller.abort(),
									55_000,
								);
								let response: Response;
								try {
									response = await fetch(`${baseUrl}/api/auto-post-publish`, {
										method: "POST",
										headers: {
											"content-type": "application/json",
											authorization: `Bearer ${internalCronSecret}`,
										},
										body: JSON.stringify({
											queueItemId: item.id,
											workspaceId: item.workspace_id,
											groupId: item.group_id,
											ownerId: group.userId,
											groupName: group.name,
											...(item.account_id
												? { accountId: item.account_id }
												: {}),
											scheduleNonce,
											traceId: `recon-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
										}),
										signal: controller.signal,
									});
								} finally {
									clearTimeout(fetchTimeoutId);
								}
								if (!response.ok) {
									const responseText = await response.text();
									throw new Error(
										`Recovery invoke failed with ${response.status}: ${responseText}`,
									);
								}
								await markQueueItemDispatched(item.id, {
									qstashMessageId: null,
									scheduleNonce,
								});
								await recordInfraEvent("autopost-reconciliation-dispatch", {
									queueItemId: item.id,
									scheduleNonce,
									invokeMode: "internal_cron",
									groupId: item.group_id,
									workspaceId: item.workspace_id,
								});
								reconciled++;
							} catch (qErr) {
								await recordInfraEvent(
									"autopost-reconciliation-dispatch-failed",
									{
										queueItemId: item.id,
										scheduleNonce,
										groupId: item.group_id,
										error: String(qErr),
									},
								);
								logger.warn("Reconciliation QStash dispatch failed", {
									queueItemId: item.id,
									status: item.status,
									error: String(qErr),
								});
							}
						}
					}

					metadataPhases.queueReconciliation = {
						status: "completed",
						local_finalize_repair_candidates: localFinalizeRows?.length ?? 0,
						local_finalize_reconciled: localFinalizeReconciled,
						local_finalize_failed: localFinalizeFailed,
						stranded: stranded?.length ?? 0,
						stranded_redispatched: reconciled,
						phase_duration_ms: Date.now() - p3Start,
					};
					totalItems += reconciled + localFinalizeReconciled;
					logger.info(
						`[${JOB_NAME}] Phase 3/4: Queue Reconciliation — complete`,
						{
							localFinalizeCandidates: localFinalizeRows?.length ?? 0,
							localFinalizeReconciled,
							localFinalizeFailed,
							stranded: stranded?.length ?? 0,
							strandedRedispatched: reconciled,
							durationMs: Date.now() - p3Start,
						},
					);
				} catch (err) {
					const errMsg = serializeError(err);
					metadataPhases.queueReconciliation = {
						status: "error",
						error: errMsg,
						phase_duration_ms: Date.now() - globalStart,
					};
					logger.error(
						`[${JOB_NAME}] Phase 3/4: Queue Reconciliation — failed`,
						{ error: errMsg },
					);
					alertCronFailure(JOB_NAME, `queue-reconciliation: ${errMsg}`);
				}

				// ── Phase 4: Queue Fill Safety Net ──
				// Dawn planner (every 4h) is the primary fill trigger.
				// This only fires for groups with ZERO pending items — catches
				// new groups, planner failures, and manual queue clears.
				if (!hasTimeBudget(globalStart)) {
					logger.warn(`[${JOB_NAME}] Skipping phase 4 — time budget exhausted`);
					metadataPhases.skippedAfterPhase = 3;
					metadata.totalDurationMs = Date.now() - globalStart;
					return { itemsProcessed: totalItems, metadata };
				}
				try {
					logger.info(
						`[${JOB_NAME}] Phase 4/4: Queue Fill Safety Net — starting`,
					);
					const p4Start = Date.now();

					let fillsDispatched = 0;
					for (const wsConfig of enabledWorkspaceConfigs.filter(
						(cfg) => cfg.group_mode_enabled && cfg.enable_ai_queue_fill,
					)) {
						const { data: enabledGroups } = await supabase
							.from("auto_post_group_config")
							.select("group_id, workspace_id")
							.eq("workspace_id", wsConfig.workspace_id)
							.eq("enabled", true);

						if (enabledGroups?.length) {
							const { data: groupInfo } = await supabase
								.from("account_groups")
								.select("id, name, user_id")
								.in(
									"id",
									enabledGroups.map((g: { group_id: string }) => g.group_id),
								);
							const infoMap = new Map(
								(groupInfo ?? []).map(
									(g: { id: string; name: string; user_id: string }) => [
										g.id,
										g,
									],
								),
							);

							for (const gc of enabledGroups as Array<{
								group_id: string;
								workspace_id: string;
							}>) {
								// Safety net: only fire when queue is EMPTY (0 items)
								const { count } = await supabase
									.from("auto_post_queue")
									.select("id", { count: "exact" })
									.eq("workspace_id", gc.workspace_id)
									.eq("group_id", gc.group_id)
									.in("status", ["pending", "queued"])
									.limit(1);

								if ((count ?? 0) > 0) continue; // Dawn planner handles non-empty queues

								const info = infoMap.get(gc.group_id);
								if (!info) continue;

								try {
									const { dispatchQueueFill } = await import(
										"../_lib/handlers/auto-post/queue.js"
									);
									const fillDispatch = await dispatchQueueFill(
										gc.workspace_id,
										info.user_id,
										gc.group_id,
										info.name,
									);
									if (fillDispatch.dispatched) {
										fillsDispatched++;
									} else {
										logger.info("Safety-net fill not dispatched", {
											groupId: gc.group_id,
											reason: fillDispatch.reason,
										});
									}
								} catch (qErr) {
									logger.warn("Safety-net fill dispatch failed", {
										groupId: gc.group_id,
										error: String(qErr),
									});
								}
							}
						}
					}

					metadataPhases.queueFill = {
						status: "completed",
						fills_dispatched: fillsDispatched,
						safety_net: true,
						phase_duration_ms: Date.now() - p4Start,
					};
					logger.info(
						`[${JOB_NAME}] Phase 4/4: Queue Fill Safety Net — complete`,
						{
							fillsDispatched,
							durationMs: Date.now() - p4Start,
						},
					);
				} catch (err) {
					const errMsg = serializeError(err);
					metadataPhases.queueFill = {
						status: "error",
						error: errMsg,
						phase_duration_ms: Date.now() - globalStart,
					};
					logger.error(
						`[${JOB_NAME}] Phase 4/4: Queue Fill Safety Net — failed`,
						{ error: errMsg },
					);
					alertCronFailure(JOB_NAME, `queue-fill: ${errMsg}`);
				}

				// Phases 5 (auto-reply) and 6 (reply farming) moved to dedicated crons:
				// - auto-reply-worker.ts (*/15 min)
				// - reply-farming-worker.ts (*/30 min)
				// This gives each its own time budget and prevents starvation.

				metadata.totalDurationMs = Date.now() - globalStart;

				return { itemsProcessed: totalItems, metadata };
			});
		},
		185,
	);

	if (lockResult.skipped) {
		return res.status(200).json({ skipped: true });
	}

	return res.status(200).json({ ok: true });
}
