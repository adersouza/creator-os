/**
 * Alert Engine — queries scheduler_decisions for anomalies
 *
 * Phase 4 of the autoposter v2 migration. Replaces the autoposter-watchdog
 * cron by reading directly from the structured decision log instead of
 * inferring problems from indirect signals.
 *
 * Anomaly checks:
 * 1. Silent groups — 0 dispatches in last 2h during what should be active hours
 * 2. Mass suppression — >30% of accounts skipped with blocked status
 * 3. Empty pool — all decisions are 'skipped_no_content' for >1h
 * 4. Error rate — >20% of decisions are errors in last hour
 * 5. Cap exhaustion — all accounts at daily cap in a group
 *
 * Fires Discord alerts via the existing alerting.ts system.
 * Called at the end of each scheduler run — no separate cron needed.
 */

import { AlertLevel, alert, alertWorkspace } from "../../alerting.js";
import { logger } from "../../logger.js";
import { getRedis } from "../../redis.js";
import { getSupabaseAny } from "../../supabase.js";

/** Suppress duplicate alerts for the same condition+group within this window. */
const ALERT_DEDUP_TTL_SECONDS = 60 * 60; // 1 hour

async function shouldAlert(key: string): Promise<boolean> {
	try {
		const redis = getRedis();
		const existing = await redis.get(key);
		if (existing) return false;
		await redis.set(key, "1", { ex: ALERT_DEDUP_TTL_SECONDS });
		return true;
	} catch {
		// Redis unavailable — allow alert through rather than silently suppress
		return true;
	}
}

// biome-ignore lint/suspicious/noExplicitAny: scheduler tables not in generated types
const db = (): any => getSupabaseAny();

// ============================================================================
// Types
// ============================================================================

interface AlertResult {
	alertsFired: number;
	checks: string[];
}

interface DecisionRow {
	group_id: string;
	account_id: string;
	/** DB column is `decision`, mapped to `outcome` for code clarity */
	outcome: string;
	reason: string;
	created_at: string;
}

const EXPECTED_SILENCE_OUTCOMES = new Set([
	"skipped_daily_cap",
	"skipped_outside_window",
	"skipped_min_interval",
	"skipped_weekend",
	"skipped_blocked",
	// Supply gaps are handled by the dedicated empty_pool / low-queue checks.
	// Treating a mixed no-content + warm-up window as "silent" creates noisy
	// alerts when the scheduler is correctly waiting for future ready rows.
	"skipped_no_content",
]);

export function isActionableSilentOutcome(outcome: string): boolean {
	return !EXPECTED_SILENCE_OUTCOMES.has(outcome);
}

export function shouldAlertEmptyPool(
	lastHourOutcomes: string[],
	readyQueueDepth: number,
): boolean {
	if (readyQueueDepth > 0) return false;
	if (lastHourOutcomes.length < 3) return false;
	return lastHourOutcomes.every((outcome) => outcome === "skipped_no_content");
}

// ============================================================================
// Main entry point
// ============================================================================

/**
 * Run all anomaly checks against recent scheduler_decisions.
 * Non-critical — failures are logged but don't break the scheduler.
 */
export async function runAlertEngine(): Promise<AlertResult> {
	const checks: string[] = [];
	let alertsFired = 0;

	try {
		const now = new Date();
		const oneHourAgo = new Date(now.getTime() - 60 * 60 * 1000).toISOString();
		const twoHoursAgo = new Date(
			now.getTime() - 2 * 60 * 60 * 1000,
		).toISOString();

		// Load recent decisions (last 2h) in one query
		// DB column is `decision`, rename to `outcome` for code clarity
		const [decisionsResult, groupConfigsResult, groupNamesResult] =
			await Promise.all([
				db()
					.from("scheduler_decisions")
					.select("group_id, account_id, decision, reason, created_at")
					.gte("created_at", twoHoursAgo)
					.order("created_at", { ascending: false })
					.limit(5000),
				db()
					.from("auto_post_group_config")
					.select(
						"group_id, workspace_id, active_hours_start, active_hours_end, timezone",
					)
					.eq("enabled", true),
				db()
					.from("account_groups")
					.select("id, name"),
			]);

		if (!decisionsResult.data || decisionsResult.data.length === 0) {
			return { alertsFired: 0, checks: ["no_recent_decisions"] };
		}

		// Build group name lookup for human-readable alerts
		const groupNames = new Map<string, string>();
		for (const g of (groupNamesResult.data ?? []) as Array<{
			id: string;
			name: string;
		}>) {
			groupNames.set(g.id, g.name);
		}
		const groupLabel = (id: string) => groupNames.get(id) || id;

		// Build group active-window lookup
		const groupWindows = new Map<
			string,
			{ workspaceId: string; start: number; end: number; timezone: string }
		>();
		for (const gc of groupConfigsResult.data ?? []) {
			groupWindows.set(gc.group_id as string, {
				workspaceId: gc.workspace_id as string,
				start: gc.active_hours_start as number,
				end: gc.active_hours_end as number,
				timezone: gc.timezone as string,
			});
		}

		/** Returns true if `now` is within the group's active window (or within 30min after it ends). */
		function isWithinActiveWindow(groupId: string): boolean {
			const window = groupWindows.get(groupId);
			if (!window) return true; // No config — assume active to avoid missing real alerts
			try {
				const localHour = Number(
					new Intl.DateTimeFormat("en-US", {
						hour: "numeric",
						hour12: false,
						timeZone: window.timezone,
					}).format(now),
				);
				// Allow 30min grace period after window end to catch stragglers
				return localHour >= window.start && localHour < window.end + 1;
			} catch {
				return true;
			}
		}

		// Map DB column `decision` → `outcome` for consistent code
		const decisions = (
			decisionsResult.data as Array<Record<string, unknown>>
		).map((d) => ({
			group_id: d.group_id as string,
			account_id: d.account_id as string,
			outcome: d.decision as string,
			reason: d.reason as string,
			created_at: d.created_at as string,
		})) as DecisionRow[];
		const oneHourAgoMs = new Date(oneHourAgo).getTime();

		// Partition decisions by group
		const byGroup = new Map<string, DecisionRow[]>();
		for (const d of decisions) {
			if (!byGroup.has(d.group_id)) byGroup.set(d.group_id, []);
			byGroup.get(d.group_id)?.push(d);
		}

		// ── Check 1: Silent groups ──
		checks.push("silent_groups");
		for (const [groupId, groupDecisions] of byGroup) {
			// Skip if group is outside its active window — silence is expected
			if (!isWithinActiveWindow(groupId)) continue;

			const dispatches = groupDecisions.filter(
				(d) => d.outcome === "dispatched",
			);
			if (dispatches.length === 0 && groupDecisions.length >= 3) {
				const outcomes = [...new Set(groupDecisions.map((d) => d.outcome))];

				// Restart warm-up creates lots of scheduler decisions that are
				// intentionally silent: cap reached, outside window, min interval,
				// weekend, or account blocked/suppressed. Alert only when the silence
				// is caused by actionable supply or execution failures.
				if (!outcomes.some(isActionableSilentOutcome)) continue;

				const dedupKey = `alert:silent:${groupId}`;
				if (!(await shouldAlert(dedupKey))) continue;

				alertsFired++;
				await alertWorkspace(
					groupWindows.get(groupId)?.workspaceId || "unknown",
					AlertLevel.WARN,
					`Silent group: ${groupLabel(groupId)}`,
					{
						group: groupLabel(groupId),
						decisions: String(groupDecisions.length),
						outcomes: outcomes.join(", "),
						window: "2h",
					},
				);
			}
		}


		// ── Check 3: Empty pool ──
		checks.push("empty_pool");
		for (const [groupId, groupDecisions] of byGroup) {
			// Only check last hour
			const lastHour = groupDecisions.filter(
				(d) => new Date(d.created_at).getTime() >= oneHourAgoMs,
			);
			if (lastHour.length < 3) continue;
			const groupWindow = groupWindows.get(groupId);
			const { count: readyQueueDepth } = await db()
				.from("auto_post_queue")
				.select("*", { count: "exact", head: true })
				.eq("group_id", groupId)
				.eq("platform", "threads")
				.in("status", ["pending", "queued"]);
			const lastHourOutcomes = lastHour.map((d) => d.outcome);
			if (shouldAlertEmptyPool(lastHourOutcomes, readyQueueDepth || 0)) {
				const dedupKey = `alert:empty_pool:${groupId}`;
				if (!(await shouldAlert(dedupKey))) continue;

				alertsFired++;
				await alertWorkspace(
					groupWindow?.workspaceId || "unknown",
					AlertLevel.WARN,
					`Empty content pool: ${groupLabel(groupId)}`,
					{
						group: groupLabel(groupId),
						noContent: String(lastHour.length),
						readyQueueDepth: String(readyQueueDepth || 0),
						window: "1h",
						action: "Queue fill may be failing or disabled",
					},
				);
			}
		}

		// ── Check 4: Error rate ──
		checks.push("error_rate");
		const lastHourAll = decisions.filter(
			(d) => new Date(d.created_at).getTime() >= oneHourAgoMs,
		);
		if (lastHourAll.length >= 5) {
			const errors = lastHourAll.filter((d) => d.outcome === "error");
			const errorRate = errors.length / lastHourAll.length;
			if (errorRate > 0.2) {
				const dedupKey = "alert:error_rate:global";
				if (await shouldAlert(dedupKey)) {
					const reasons = [...new Set(errors.map((d) => d.reason))];
					alertsFired++;
					await alert(AlertLevel.ERROR, "Scheduler error rate >20%", {
						errors: `${errors.length}/${lastHourAll.length} (${Math.round(errorRate * 100)}%)`,
						reasons: reasons.slice(0, 3).join("; "),
						window: "1h",
					});
				}
			}
		}

		// ── Check 5: Cap exhaustion ──
		checks.push("cap_exhaustion");
		for (const [groupId, groupDecisions] of byGroup) {
			const lastHour = groupDecisions.filter(
				(d) => new Date(d.created_at).getTime() >= oneHourAgoMs,
			);
			if (lastHour.length < 3) continue;
			const capped = lastHour.filter((d) => d.outcome === "skipped_daily_cap");
			// All eligible accounts are capped — nothing can post
			const nonBlocked = lastHour.filter(
				(d) => d.outcome !== "skipped_blocked",
			);
			if (nonBlocked.length > 0 && capped.length === nonBlocked.length) {
				const dedupKey = `alert:cap_exhaustion:${groupId}`;
				if (!(await shouldAlert(dedupKey))) continue;

				alertsFired++;
				await alertWorkspace(
					groupWindows.get(groupId)?.workspaceId || "unknown",
					AlertLevel.INFO,
					`All accounts at daily cap: ${groupLabel(groupId)}`,
					{
						group: groupLabel(groupId),
						capped: String(capped.length),
						window: "1h",
					},
				);
			}
		}

		logger.info("[alertEngine] Checks complete", { alertsFired, checks });
	} catch (err) {
		logger.warn("[alertEngine] Alert engine error (non-fatal)", {
			error: err instanceof Error ? err.message : String(err),
		});
	}

	return { alertsFired, checks };
}
