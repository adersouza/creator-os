/**
 * Scheduler Eligibility Checks — determines if an account can post right now.
 *
 * Pure function: no DB or Redis calls. Takes pre-loaded data and returns
 * a verdict with a human-readable reason.
 *
 * Checks (in order):
 * 1. Active window (account override > group config, supports wrap-around)
 * 2. Weekend check
 * 3. Daily cap
 * 4. Min interval
 */

import { getLocalTime } from "../../handlers/auto-post/contentSelection.js";

// ============================================================================
// Types
// ============================================================================

export interface EligibilityInput {
	/** Group config active_hours_start (0-23) */
	activeHoursStart: number;
	/** Group config active_hours_end (0-23) */
	activeHoursEnd: number;
	/** Group config timezone */
	timezone: string;
	/** Group config posts_per_account_per_day */
	dailyCap: number;
	/** Group config min_interval_minutes */
	minIntervalMinutes: number;
	/** Group config post_on_weekends */
	postOnWeekends: boolean;
	/** Per-account override (merged over group config) — may override any field above */
	override?: {
        		active_hours_start?: number | undefined;
        		active_hours_end?: number | undefined;
        		timezone?: string | undefined;
        		posts_per_account_per_day?: number | undefined;
        		min_interval_minutes?: number | undefined;
        		post_on_weekends?: boolean | undefined;
        	} | null | undefined;
	/** Last post time for this account (epoch ms), null if never posted */
	lastPostTime: number | null;
	/** Number of posts published today for this account */
	postsToday: number;
	/** Current time */
	now: Date;
}

export interface EligibilityResult {
	eligible: boolean;
	reason: string;
	/** Local hour in the effective timezone */
	localHour: number;
}

// ============================================================================
// Main check
// ============================================================================

export function checkEligibility(input: EligibilityInput): EligibilityResult {
	const { override, lastPostTime, postsToday, now } = input;

	// Merge override onto group config
	const activeStart = override?.active_hours_start ?? input.activeHoursStart;
	const activeEnd = override?.active_hours_end ?? input.activeHoursEnd;
	const tz = override?.timezone ?? input.timezone;
	const cap = override?.posts_per_account_per_day ?? input.dailyCap;
	const minInterval =
		override?.min_interval_minutes ?? input.minIntervalMinutes;
	const weekends = override?.post_on_weekends ?? input.postOnWeekends;

	const { hour: localHour, dayOfWeek } = getLocalTime(now, tz);

	// 1. Active window (supports wrap-around e.g. 22:00-04:00)
	const isInActiveHours =
		activeStart < activeEnd
			? localHour >= activeStart && localHour < activeEnd
			: localHour >= activeStart || localHour < activeEnd;
	if (!isInActiveHours) {
		return {
			eligible: false,
			reason: `outside_active_window(${localHour}h, window=${activeStart}-${activeEnd})`,
			localHour,
		};
	}

	// 2. Weekend check
	const isWeekend = dayOfWeek === 0 || dayOfWeek === 6;
	if (isWeekend && !weekends) {
		return {
			eligible: false,
			reason: "weekend_paused",
			localHour,
		};
	}

	// 3. Daily cap
	if (postsToday >= cap) {
		return {
			eligible: false,
			reason: `daily_cap_reached(${postsToday}/${cap})`,
			localHour,
		};
	}

	// 4. Min interval
	if (lastPostTime != null) {
		const minutesSince = (now.getTime() - lastPostTime) / 60000;
		if (minutesSince < minInterval) {
			return {
				eligible: false,
				reason: `min_interval(${Math.round(minutesSince)}min < ${minInterval}min)`,
				localHour,
			};
		}
	}

	return {
		eligible: true,
		reason: "eligible",
		localHour,
	};
}
