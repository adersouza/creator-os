/**
 * Auto-Post Queue Utilities
 *
 * Shared helpers for the autoposter pipeline:
 * - checkAccountEligibility: Active hours, weekends, min_interval checks
 * - dispatchQueueFill: QStash-dispatched AI queue fill with rate limiting
 *
 * flagAccountForReauth and applyHumanNoise removed (2026-04-04, Phase 4
 * cleanup) — were only used by the deleted processGroupMode path.
 * Reauth flagging is handled inline in auto-post-publish.ts.
 */

import { logger } from "../../logger.js";
import { getLocalTime } from "./contentSelection.js";
import type { GroupConfig } from "./types.js";

// ============================================================================
// Account Eligibility — merges per-account overrides with group config and
// checks active hours, weekends, and min_interval.
// ============================================================================

export interface EligibilityCheck {
	eligible: boolean;
	merged: GroupConfig;
}

export function checkAccountEligibility(
	gc: GroupConfig,
	accountId: string,
	overrideMap: Map<string, Record<string, unknown>>,
	lastPostByAccount: Map<string, number>,
	now: Date,
	/** Skip active hours check — used at fill time (planner assigns for future schedule, publish worker checks real-time) */
	skipActiveHours?: boolean,
): EligibilityCheck {
	const acctOverrides = overrideMap.get(`${gc.group_id}:${accountId}`);
	const merged = acctOverrides
		? ({ ...gc, ...acctOverrides } as GroupConfig)
		: gc;

	const { hour: currentHour, dayOfWeek } = getLocalTime(now, merged.timezone);

	// Active hours (supports wrap-around e.g. 22:00–04:00)
	// Skipped at fill time — the planner assigns accounts for future scheduled times,
	// and the publish worker re-checks eligibility at actual publish time.
	if (!skipActiveHours) {
		const isInActiveHours =
			merged.active_hours_start < merged.active_hours_end
				? currentHour >= merged.active_hours_start &&
					currentHour < merged.active_hours_end
				: currentHour >= merged.active_hours_start ||
					currentHour < merged.active_hours_end;
		if (!isInActiveHours) return { eligible: false, merged };
	}

	// Weekend check
	const isWeekend = dayOfWeek === 0 || dayOfWeek === 6;
	if (isWeekend && !merged.post_on_weekends) return { eligible: false, merged };

	// Per-account min_interval
	const lastAccountPostTime = lastPostByAccount.get(accountId);
	if (lastAccountPostTime) {
		const minutesSince = (now.getTime() - lastAccountPostTime) / 60000;
		if (minutesSince < merged.min_interval_minutes)
			return { eligible: false, merged };
	}

	return { eligible: true, merged };
}

// ============================================================================
// QStash-dispatched AI Queue Fill
// ============================================================================

/**
 * Dispatch a queue fill via QStash — rate-limited to once per group per 8 hours.
 * This prevents the old "treadmill" pattern where every 5-min cron cycle would
 * trigger Gemini calls for every group that dropped below threshold.
 * Now: one big batch fill per group per ~8h window.
 */
export type QueueFillDispatchResult = {
	dispatched: boolean;
	reason: "dispatched" | "cooldown_active" | "dispatch_failed";
};

export async function dispatchQueueFill(
	workspaceId: string,
	ownerId: string,
	groupId: string,
	groupName: string,
): Promise<QueueFillDispatchResult> {
	try {
		// 8-hour cooldown per group — prevents the every-5-min Gemini treadmill.
		// Two fills/day covers active window start + one safety refill.
		const { getRedis } = await import("../../redis.js");
		const redis = getRedis();
		const cooldownKey = `queue-fill-cooldown:${workspaceId}:${groupId}`;
		const acquired = await redis.set(cooldownKey, "1", {
			nx: true,
			ex: 8 * 60 * 60,
		});
		if (!acquired) {
			logger.info("Queue fill skipped — cooldown active (8h per group)", {
				groupId,
				groupName,
			});
			return { dispatched: false, reason: "cooldown_active" };
		}

		const { getQStashClient } = await import("../../qstash.js");
		const { RETRIES, getRequiredAppBaseUrl } = await import(
			"../../qstashDefaults.js"
		);
		const qstash = getQStashClient();
		const baseUrl = getRequiredAppBaseUrl();

		await qstash.publishJSON({
			url: `${baseUrl}/api/queue-fill`,
			body: {
				workspaceId,
				ownerId,
				groupId,
				batchMode: true,
				traceId: `fill-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
			},
			retries: RETRIES.IMPORTANT,
		});
		logger.info("Dispatched batch queue-fill job via QStash", {
			groupId,
			groupName,
		});
		return { dispatched: true, reason: "dispatched" };
	} catch (err) {
		logger.warn("QStash queue-fill dispatch failed", {
			groupId,
			error: err instanceof Error ? err.message : String(err),
		});
		return { dispatched: false, reason: "dispatch_failed" };
	}
}
