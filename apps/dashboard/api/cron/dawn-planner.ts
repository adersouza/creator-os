/**
 * Dawn Planner — batch content planning cron (every 4h)
 *
 * Phase 3 of the autoposter rebuild (2026-04-04). Replaces the reactive
 * fill-check in publish-worker Phase 4 that dispatched fills every 5 min
 * when queue dropped below threshold (causing 240+ Gemini calls/hr).
 *
 * Now: once per day per group, generate a full day's content in one batch.
 * Runs every 4h to cover all timezone active windows — Redis dedup ensures
 * each group only plans once per calendar day.
 *
 * Safety net: publish-worker Phase 4 still catches groups with 0 pending
 * items if the dawn planner fails or hasn't run.
 */

import type { Redis } from "@upstash/redis";
import type { VercelRequest, VercelResponse } from "@vercel/node";

export const config = {
	maxDuration: 120,
};

const JOB_NAME = "dawn-planner";

export default async function handler(req: VercelRequest, res: VercelResponse) {
	const { verifyCronAuth } = await import("../_lib/apiResponse.js");
	if (!verifyCronAuth(req, res)) return;

	const { withCronLock, trackCronRun } = await import("../_lib/cronUtils.js");
	const { getSupabaseAny } = await import("../_lib/supabase.js");
	const { logger } = await import("../_lib/logger.js");

	const supabase = getSupabaseAny();

	const lockResult = await withCronLock(
		supabase,
		JOB_NAME,
		async () => {
			return trackCronRun(supabase, JOB_NAME, async () => {
				// 1. Find legacy workspaces with autoposter + AI queue fill enabled
				const { data: workspaceConfigs } = await supabase
					.from("auto_post_config")
					.select(
						"workspace_id, is_enabled, group_mode_enabled, enable_ai_queue_fill, scheduler_version",
					)
					.eq("is_enabled", true)
					.eq("enable_ai_queue_fill", true);

				const legacyWorkspaces = (
					(workspaceConfigs ?? []) as Array<{
						workspace_id: string;
						group_mode_enabled: boolean;
						enable_ai_queue_fill: boolean;
						scheduler_version?: number | null | undefined;
					}>
				).filter(
					(cfg) =>
						cfg.group_mode_enabled &&
						cfg.enable_ai_queue_fill &&
						(cfg.scheduler_version ?? 1) < 2,
				);

				if (legacyWorkspaces.length === 0) {
					return {
						itemsProcessed: 0,
						metadata: { reason: "no_enabled_workspace" },
					};
				}

				// 2. Load all enabled groups
				const { data: enabledGroups } = await supabase
					.from("auto_post_group_config")
					.select(
						"group_id, workspace_id, active_hours_start, active_hours_end, timezone, posts_per_account_per_day",
					)
					.in(
						"workspace_id",
						legacyWorkspaces.map((w) => w.workspace_id),
					)
					.eq("enabled", true);

				if (!enabledGroups?.length) {
					return {
						itemsProcessed: 0,
						metadata: { reason: "no_enabled_groups" },
					};
				}

				// 3. Load group info (name, owner, account count)
				const groupIds = enabledGroups.map(
					(g: { group_id: string }) => g.group_id,
				);
				const { data: groupInfo } = await supabase
					.from("account_groups")
					.select("id, name, user_id, account_ids")
					.in("id", groupIds);

				const infoMap = new Map(
					(groupInfo ?? []).map(
						(g: {
							id: string;
							name: string;
							user_id: string;
							account_ids: string[];
						}) => [g.id, g],
					),
				);

				let planned = 0;
				let skipped = 0;
				const groupResults: Record<string, string> = {};

				// 4. Get Redis for dedup
				let redis: Redis | undefined;
				try {
					const { getRedis } = await import("../_lib/redis.js");
					redis = getRedis();
				} catch {
					logger.warn(
						`[${JOB_NAME}] Redis unavailable, proceeding without dedup`,
					);
				}

				for (const gc of enabledGroups as Array<{
					group_id: string;
					workspace_id: string;
					active_hours_start: number;
					active_hours_end: number;
					timezone: string;
					posts_per_account_per_day: number;
				}>) {
					const info = infoMap.get(gc.group_id);
					if (!info) {
						groupResults[gc.group_id] = "no_group_info";
						skipped++;
						continue;
					}

					// 4a. Check if current time is near the group's active window start.
					// We plan within the first 4h of the active window so content is
					// ready before the first scheduled post time.
					const tz = gc.timezone || "UTC";
					let currentHour: number;
					try {
						currentHour = parseInt(
							new Intl.DateTimeFormat("en-US", {
								timeZone: tz,
								hour: "2-digit",
								hour12: false,
							}).format(new Date()),
							10,
						);
					} catch {
						currentHour = new Date().getUTCHours();
					}

					const activeStart = gc.active_hours_start ?? 8;
					const activeEnd = gc.active_hours_end ?? 23;
					const perDay = gc.posts_per_account_per_day ?? 1;
					const isHighConsumption = perDay >= 2;

					// For high-consumption groups (>= 2 posts/account/day), expand the planning
					// window to the full active window so the 4h cron can dispatch multiple fills
					// throughout the day. This prevents queue drain between dawn and dusk.
					const planWindowEnd = isHighConsumption
						? activeEnd
						: (activeStart + 4) % 24;
					let inPlanWindow: boolean;
					if (activeStart < planWindowEnd) {
						inPlanWindow =
							currentHour >= activeStart && currentHour < planWindowEnd;
					} else {
						// Wrap-around case
						inPlanWindow =
							currentHour >= activeStart || currentHour < planWindowEnd;
					}

					if (!inPlanWindow) {
						groupResults[gc.group_id] =
							`outside_plan_window(${currentHour}h, window=${activeStart}-${planWindowEnd})`;
						skipped++;
						continue;
					}

					// 4b. Redis dedup — one plan per group per calendar day (in group's timezone)
					let todayInTz: string;
					try {
						todayInTz = new Intl.DateTimeFormat("en-CA", {
							timeZone: tz,
							year: "numeric",
							month: "2-digit",
							day: "2-digit",
						}).format(new Date());
					} catch {
						todayInTz = new Date().toISOString().slice(0, 10);
					}

					// High-consumption groups use a time-slotted dedup key so the 4h cron
					// can dispatch multiple fills per day (AM/midday/PM). Standard groups
					// keep the original once-per-day dedup.
					const timeSlot = isHighConsumption
						? `-slot${Math.floor(currentHour / 4)}` // 0-5 (each 4h block)
						: "";
					const dedupKey = `dawn-planned:${gc.group_id}:${todayInTz}${timeSlot}`;
					if (redis) {
						try {
							const alreadyPlanned = await redis.get(dedupKey);
							if (alreadyPlanned) {
								groupResults[gc.group_id] = isHighConsumption
									? `already_planned_this_slot(slot${Math.floor(currentHour / 4)})`
									: "already_planned_today";
								skipped++;
								continue;
							}
						} catch {
							// Proceed without dedup check
						}
					}

					// 4c. Dispatch QStash queue fill for this group
					try {
						const { getQStashClient } = await import("../_lib/qstash.js");
						const { RETRIES, getRequiredAppBaseUrl } = await import(
							"../_lib/qstashDefaults.js"
						);
						const qstash = getQStashClient();
						const baseUrl = getRequiredAppBaseUrl();

						await qstash.publishJSON({
							url: `${baseUrl}/api/queue-fill`,
							body: {
								workspaceId: gc.workspace_id,
								ownerId: info.user_id,
								groupId: gc.group_id,
								batchMode: true,
							},
							retries: RETRIES.IMPORTANT,
							// Include time slot in QStash dedup ID so high-consumption groups
							// aren't blocked by QStash's own dedup from getting multiple fills/day
							deduplicationId: `dawn-${gc.group_id}-${todayInTz}${timeSlot}`,
						});

						// High-consumption: 3h TTL so the next 4h cron window can re-fill.
						// Standard: 4h TTL (allows same-day retry if fill produces 0 posts).
						const dedupTtlSeconds = isHighConsumption
							? 3 * 60 * 60
							: 4 * 60 * 60;
						if (redis) {
							try {
								await redis.set(dedupKey, "1", { ex: dedupTtlSeconds });
							} catch {
								// Non-critical
							}
						}

						planned++;
						groupResults[gc.group_id] = "dispatched";
						logger.info(`[${JOB_NAME}] Dispatched batch fill`, {
							groupId: gc.group_id,
							groupName: info.name,
							timezone: tz,
							currentHour,
							activeStart,
						});
					} catch (qErr) {
						groupResults[gc.group_id] = `dispatch_failed: ${String(qErr)}`;
						logger.warn(`[${JOB_NAME}] QStash dispatch failed`, {
							groupId: gc.group_id,
							error: qErr instanceof Error ? qErr.message : String(qErr),
						});
					}
				}

				logger.info(`[${JOB_NAME}] Complete`, {
					planned,
					skipped,
					groupResults,
				});

				// Zero-post alerting: only fire if a group that WAS in its plan window
				// still failed to dispatch. "outside_plan_window" and "already_planned_today"
				// are normal — don't spam Discord at off-hours.
				const hasRealFailure = Object.values(groupResults).some(
					(r) => r.startsWith("dispatch_failed") || r === "no_group_info",
				);
				if (planned === 0 && enabledGroups.length > 0 && hasRealFailure) {
					try {
						const { alert, AlertLevel } = await import("../_lib/alerting.js");
						await alert(
							AlertLevel.WARN,
							`[Dawn Planner] 0 groups dispatched out of ${enabledGroups.length} enabled`,
							{
								skipped,
								groupResults: JSON.stringify(groupResults),
								reason:
									"At least one group failed dispatch or had missing info",
							},
						);
					} catch {
						/* best-effort alerting */
					}
				}

				return {
					itemsProcessed: planned,
					metadata: { planned, skipped, groupResults },
				};
			});
		},
		115,
	);

	if (lockResult.skipped) {
		return res.status(200).json({ skipped: true });
	}

	return res.status(200).json({ ok: true });
}
