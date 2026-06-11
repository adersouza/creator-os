// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
/**
 * Timing Engine — natural post scheduling with SynchroTrap decorrelation
 *
 * Extracted from queueFill.ts. Handles:
 * - Seasonal volume multipliers
 * - Smart scheduling with learned best hours
 * - Cross-group jitter and dynamic spacing
 * - Platform-aware minimum gaps (IG 3h, Threads 30min)
 */

import { logger } from "../../logger.js";
import { getSupabaseAny } from "../../supabase.js";
import {
	THREADS_GLOBAL_PRIMARY_HOURS,
	THREADS_GLOBAL_SECONDARY_HOURS,
	type AccountTimingProfile,
	type TimingReason,
} from "./accountTimingPerformance.js";
import type { AutoPostConfig, TimingInsights } from "./types.js";

const db = () => getSupabaseAny();

type ZonedParts = {
	year: number;
	month: number;
	day: number;
	hour: number;
	minute: number;
	second: number;
};

function safeTimeZone(timezone?: string): string {
	const tz = timezone || "UTC";
	try {
		new Intl.DateTimeFormat("en-US", { timeZone: tz }).format(new Date());
		return tz;
	} catch {
		return "UTC";
	}
}

function getZonedParts(date: Date, timezone?: string): ZonedParts {
	const formatter = new Intl.DateTimeFormat("en-US", {
		timeZone: safeTimeZone(timezone),
		year: "numeric",
		month: "2-digit",
		day: "2-digit",
		hour: "2-digit",
		minute: "2-digit",
		second: "2-digit",
		hourCycle: "h23",
	});
	const parts = Object.fromEntries(
		formatter.formatToParts(date).map((part) => [part.type, part.value]),
	);
	return {
		year: Number(parts.year),
		month: Number(parts.month),
		day: Number(parts.day),
		hour: Number(parts.hour),
		minute: Number(parts.minute),
		second: Number(parts.second),
	};
}

function getTimeZoneOffsetMs(date: Date, timezone: string): number {
	const parts = getZonedParts(date, timezone);
	const asUtc = Date.UTC(
		parts.year,
		parts.month - 1,
		parts.day,
		parts.hour,
		parts.minute,
		parts.second,
	);
	return asUtc - date.getTime();
}

function zonedDateToUtc(
	dateParts: Pick<ZonedParts, "year" | "month" | "day">,
	hour: number,
	minute: number,
	second: number,
	timezone: string,
): Date {
	const wallClockUtc = Date.UTC(
		dateParts.year,
		dateParts.month - 1,
		dateParts.day,
		hour,
		minute,
		second,
	);
	let utcMs = wallClockUtc;
	for (let i = 0; i < 3; i++) {
		utcMs = wallClockUtc - getTimeZoneOffsetMs(new Date(utcMs), timezone);
	}
	return new Date(utcMs);
}

function addCalendarDays(
	dateParts: Pick<ZonedParts, "year" | "month" | "day">,
	days: number,
): Pick<ZonedParts, "year" | "month" | "day"> {
	const date = new Date(
		Date.UTC(dateParts.year, dateParts.month - 1, dateParts.day + days),
	);
	return {
		year: date.getUTCFullYear(),
		month: date.getUTCMonth() + 1,
		day: date.getUTCDate(),
	};
}

function isDateInActiveWindow(
	date: Date,
	timezone: string,
	start: number,
	end: number,
): boolean {
	return isHourInActiveWindow(getZonedParts(date, timezone).hour, start, end);
}

function moveToNextActiveWindow(
	date: Date,
	timezone: string,
	start: number,
	end: number,
): Date {
	if (isDateInActiveWindow(date, timezone, start, end)) return date;

	const activeHours = getActiveHours(start, end);
	const localToday = getZonedParts(date, timezone);
	for (let dayOffset = 0; dayOffset <= 2; dayOffset++) {
		const day = addCalendarDays(localToday, dayOffset);
		for (const hour of activeHours) {
			const candidate = zonedDateToUtc(
				day,
				hour,
				Math.floor(Math.random() * 60),
				Math.floor(Math.random() * 60),
				timezone,
			);
			if (candidate.getTime() >= date.getTime()) {
				return candidate;
			}
		}
	}

	return new Date(date.getTime() + 60 * 60 * 1000);
}

function normalizeScheduledTimes(
	times: string[],
	minGapMs: number,
	timezone: string,
	activeStart: number,
	activeEnd: number,
	now: Date,
): string[] {
	const normalized: string[] = [];
	const sorted = times.sort();
	for (let i = 0; i < sorted.length; i++) {
		let scheduled = new Date(sorted[i]!);
		if (scheduled.getTime() <= now.getTime()) {
			scheduled = new Date(now.getTime() + minGapMs);
		}

		if (normalized.length > 0) {
			const previous = new Date(normalized[normalized.length - 1]!).getTime();
			if (scheduled.getTime() - previous < minGapMs) {
				scheduled = new Date(
					previous + minGapMs + Math.random() * 10 * 60 * 1000,
				);
			}
		}

		scheduled = moveToNextActiveWindow(
			scheduled,
			timezone,
			activeStart,
			activeEnd,
		);

		if (normalized.length > 0) {
			const previous = new Date(normalized[normalized.length - 1]!).getTime();
			if (scheduled.getTime() - previous < minGapMs) {
				scheduled = moveToNextActiveWindow(
					new Date(previous + minGapMs + Math.random() * 10 * 60 * 1000),
					timezone,
					activeStart,
					activeEnd,
				);
			}
		}

		const isoMinute = scheduled.toISOString().slice(0, 16);
		const previousMinute = normalized[normalized.length - 1]?.slice(0, 16);
		if (previousMinute === isoMinute) {
			scheduled = moveToNextActiveWindow(
				new Date(scheduled.getTime() + 60_000 + Math.random() * 30_000),
				timezone,
				activeStart,
				activeEnd,
			);
		}

		normalized.push(scheduled.toISOString());
	}
	return normalized;
}

// ============================================================================
// Seasonal Volume
// ============================================================================

/**
 * Seasonal volume multiplier based on month.
 * Research-backed (Timing Intelligence 2026, Section 6):
 * - Jan-Feb: +15% (Fresh Start Effect, Valentine's Day)
 * - Mar-May: baseline
 * - Jun-Aug: -15% (summer dip)
 * - Sep-Oct: +15% (Fall Fashion Week, routine restart)
 * - Nov: baseline (BFCM ad noise offsets engagement lift)
 * - Dec 20-Jan 2: -50% (holiday trough)
 */
export function getSeasonalMultiplier(): number {
	const now = new Date();
	const month = now.getMonth(); // 0-indexed: 0=Jan, 11=Dec
	const day = now.getDate();

	// Holiday trough: Dec 20 - Jan 2
	if ((month === 11 && day >= 20) || (month === 0 && day <= 2)) {
		return 0.5;
	}

	// Monthly multipliers
	switch (month) {
		case 0: // January
		case 1: // February
			return 1.15;
		case 2: // March
		case 3: // April
		case 4: // May
			return 1.0;
		case 5: // June
		case 6: // July
		case 7: // August
			return 0.85;
		case 8: // September
		case 9: // October
			return 1.15;
		case 10: // November
			return 1.0;
		case 11: // December (before the 20th)
			return 1.0;
		default:
			return 1.0;
	}
}

// ============================================================================
// Active Window Helpers
// ============================================================================

/**
 * Check if a given hour falls within an active window (supports overnight wrap-around).
 */
export function isHourInActiveWindow(
	hour: number,
	start: number,
	end: number,
): boolean {
	if (start < end) return hour >= start && hour < end;
	return hour >= start || hour < end; // wrap-around (e.g., 22-4)
}

/**
 * Get all hours in an active window as an array (supports overnight wrap-around).
 */
export function getActiveHours(start: number, end: number): number[] {
	const hours: number[] = [];
	if (start < end) {
		for (let h = start; h < end; h++) hours.push(h);
	} else {
		for (let h = start; h < 24; h++) hours.push(h);
		for (let h = 0; h < end; h++) hours.push(h);
	}
	return hours;
}

// ============================================================================
// Natural Post Time Calculator
// ============================================================================

/**
 * Calculate natural-looking post times with inter-group jitter and dynamic spacing.
 * - Each group gets a deterministic 0-25 min offset (reduces cross-group clustering)
 * - Large groups (>15 accounts) get wider minimum spacing (60 min vs 30 min)
 * - Minimum gap enforced between consecutive posts after sorting
 * - When TimingInsights are provided, 60% of posts target learned best hours
 */
export function calculateNaturalPostTimes(
	count: number,
	_config: AutoPostConfig,
	groupId?: string,
	groupAccountCount?: number,
	insights?: TimingInsights,
	platform?: "threads" | "instagram" | "both",
): string[] {
	const now = new Date();

	// ================================================================
	// SynchroTrap Decorrelation: spread posts across 0-4 hour window
	// per group to prevent cross-account timing synchronization.
	// Uses group ID + day-of-year as seed for daily variation while
	// keeping same group in roughly the same time slot each day.
	// ================================================================
	let groupOffset = 0;
	if (groupId) {
		let hash = 0;
		for (let i = 0; i < groupId.length; i++) {
			hash = ((hash << 5) - hash + groupId.charCodeAt(i)) | 0;
		}
		// Day-of-year rotation: shift offset daily so same group varies across days
		const dayOfYear = Math.floor(
			(now.getTime() - new Date(now.getFullYear(), 0, 0).getTime()) / 86400000,
		);
		const dailySeed = Math.abs((hash + dayOfYear * 7919) | 0); // 7919 is prime
		groupOffset = (dailySeed % 240) * 60 * 1000; // 0-240 min (0-4 hours) in ms
	}

	// Account-aware spacing: more accounts means wider gaps between consecutive posts.
	// With N accounts round-robined at publish time, consecutive queue items go to
	// different accounts — the gap between them IS the inter-account gap.
	const accountCount = groupAccountCount ?? 1;
	const isLargeGroup = accountCount > 15;

	// ================================================================
	// Smart Scheduling: use learned best hours when insights are available
	// ================================================================
	const activeStart = insights?.activeHoursStart ?? 0;
	const activeEnd = insights?.activeHoursEnd ?? 24;
	const bestHours = insights?.bestPostingHours ?? [];
	const peakWindows = insights?.peakWindows ?? [];
	const tz = safeTimeZone(insights?.timezone);

	// Get today's day name in the configured timezone (or UTC)
	let todayDayName: string;
	try {
		todayDayName = now
			.toLocaleDateString("en-US", { weekday: "long", timeZone: tz })
			.toLowerCase();
	} catch {
		todayDayName = now
			.toLocaleDateString("en-US", { weekday: "long", timeZone: "UTC" })
			.toLowerCase();
	}

	// Merge bestPostingHours with today-matching peakWindows (union, dedup)
	const todayPeakHours = peakWindows
		.filter((w) => w.day.toLowerCase() === todayDayName)
		.map((w) => w.hour);
	const mergedPreferred = [...new Set([...bestHours, ...todayPeakHours])];

	// Filter preferred hours to those within the active window
	const preferredInWindow = mergedPreferred.filter((h) =>
		isHourInActiveWindow(h, activeStart, activeEnd),
	);

	// Timing Intelligence 2026: On weekends, shift preferred hours toward mornings
	// (9-12 local). Saturday is absolute lowest, Sunday only 11 AM viable.
	const isWeekend = todayDayName === "saturday" || todayDayName === "sunday";
	if (isWeekend && preferredInWindow.length > 0) {
		const morningHours = preferredInWindow.filter((h) => h >= 9 && h <= 12);
		if (morningHours.length > 0) {
			// Replace preferred with morning-only subset on weekends
			preferredInWindow.length = 0;
			preferredInWindow.push(...morningHours);
		}
	}

	// Use smart scheduling if we have valid preferred hours
	if (preferredInWindow.length > 0 && count > 0) {
		const allActiveHours = getActiveHours(activeStart, activeEnd);
		const otherActiveHours = allActiveHours.filter(
			(h) => !preferredInWindow.includes(h),
		);

		// Allocate 60% to preferred hours, rest to other active hours
		const preferredCount = Math.ceil(count * 0.6);
		const otherCount = count - preferredCount;

		const times: string[] = [];
		const today = getZonedParts(now, tz);

		// Generate times for preferred-hour posts
		for (let i = 0; i < preferredCount; i++) {
			const hour =
				preferredInWindow[Math.floor(Math.random() * preferredInWindow.length)];
			let scheduled = zonedDateToUtc(
				today,
				hour!,
				Math.floor(Math.random() * 59),
				Math.floor(Math.random() * 60),
				tz,
			);
			scheduled = new Date(scheduled.getTime() + groupOffset);

			// If the time is in the past, push to tomorrow
			if (scheduled.getTime() <= now.getTime()) {
				const tomorrow = addCalendarDays(today, 1);
				scheduled = new Date(
					zonedDateToUtc(
						tomorrow,
						hour!,
						Math.floor(Math.random() * 59),
						Math.floor(Math.random() * 60),
						tz,
					).getTime() + groupOffset,
				);
			}

			// ±5 min jitter to avoid clustering
			const jitter = (Math.random() - 0.5) * 10 * 60 * 1000;
			scheduled.setTime(scheduled.getTime() + jitter);

			times.push(scheduled.toISOString());
		}

		// Generate times for non-preferred active-hour posts
		const fallbackHours =
			otherActiveHours.length > 0 ? otherActiveHours : preferredInWindow;
		for (let i = 0; i < otherCount; i++) {
			const hour =
				fallbackHours[Math.floor(Math.random() * fallbackHours.length)];
			let scheduled = zonedDateToUtc(
				today,
				hour!,
				Math.floor(Math.random() * 59),
				Math.floor(Math.random() * 60),
				tz,
			);
			scheduled = new Date(scheduled.getTime() + groupOffset);

			if (scheduled.getTime() <= now.getTime()) {
				const tomorrow = addCalendarDays(today, 1);
				scheduled = new Date(
					zonedDateToUtc(
						tomorrow,
						hour!,
						Math.floor(Math.random() * 59),
						Math.floor(Math.random() * 60),
						tz,
					).getTime() + groupOffset,
				);
			}

			const jitter = (Math.random() - 0.5) * 10 * 60 * 1000;
			scheduled.setTime(scheduled.getTime() + jitter);

			times.push(scheduled.toISOString());
		}

		// Enforce minimum gap between consecutive posts (prevents SynchroTrap
		// detection when round-robin assigns consecutive items to different accounts).
		// Instagram needs 3-hour minimum to avoid feed reach suppression.
		// Scale jitter with account count so multi-account groups spread further.
		const baseGapMs =
			platform === "instagram"
				? 3 * 60 * 60 * 1000 // 3 hours for Instagram
				: 30 * 60 * 1000; // 30 min for Threads
		const accountJitter = Math.min(accountCount, 10) * 2 * 60 * 1000; // +2 min per account, cap at 20 min
		const minGapMs =
			baseGapMs +
			(isLargeGroup ? accountJitter : Math.floor(accountJitter / 2));
		return normalizeScheduledTimes(
			times,
			minGapMs,
			tz,
			activeStart,
			activeEnd,
			now,
		);
	}

	// ================================================================
	// Fallback: random 12-hour spread with decorrelation (no insights)
	// ================================================================
	const times: string[] = [];
	const igMinOffset = 3 * 60 * 60 * 1000; // 3 hours for Instagram
	const minOffset =
		platform === "instagram"
			? igMinOffset
			: isLargeGroup
				? 60 * 60 * 1000
				: 30 * 60 * 1000; // 60 or 30 min for Threads
	const maxOffset = 12 * 60 * 60 * 1000; // 12 hours (was 8h — wider to accommodate 4h group offset)

	for (let i = 0; i < count; i++) {
		const randomOffset = minOffset + Math.random() * (maxOffset - minOffset);
		const scheduled = new Date(now.getTime() + randomOffset + groupOffset);

		// Add ±10 min jitter to avoid round numbers (was ±5 min)
		const jitter = (Math.random() - 0.5) * 20 * 60 * 1000; // ±10 min
		scheduled.setTime(scheduled.getTime() + jitter);

		// Avoid :00 and :30
		const mins = scheduled.getMinutes();
		if (mins === 0 || mins === 30) {
			scheduled.setMinutes(mins + 2 + Math.floor(Math.random() * 8));
		}

		times.push(scheduled.toISOString());
	}

	// Enforce minimum gap (prevents SynchroTrap cross-account detection)
	// Instagram: 3-hour minimum to avoid feed reach suppression
	const fallbackBaseGapMs =
		platform === "instagram"
			? 3 * 60 * 60 * 1000 // 3 hours for Instagram
			: 30 * 60 * 1000; // 30 min for Threads
	const fallbackAccountJitter = Math.min(accountCount, 10) * 2 * 60 * 1000;
	const fallbackMinGapMs =
		fallbackBaseGapMs +
		(isLargeGroup
			? fallbackAccountJitter
			: Math.floor(fallbackAccountJitter / 2));
	return normalizeScheduledTimes(
		times,
		fallbackMinGapMs,
		tz,
		activeStart,
		activeEnd,
		now,
	);
}

export interface AccountAwareTimingSlot {
	accountId: string;
	warmupPolicy?: {
		primaryHoursOnly?: boolean | undefined;
		day?: number | null | undefined;
		status?: string | undefined;
	} | undefined;
	timezone?: string | undefined;
	activeHoursStart?: number | undefined;
	activeHoursEnd?: number | undefined;
	minIntervalMinutes?: number | undefined;
}

export interface AccountTimingSelection {
	selectedHour: number;
	timingReason: TimingReason;
	confidence: number;
	fallbackSource: string;
	sampleSize: number;
}

export interface AccountAwareScheduledTime {
	scheduledFor: string;
	timing: AccountTimingSelection;
}

function getGroupOffsetMs(groupId: string | undefined, now: Date): number {
	if (!groupId) return 0;
	let hash = 0;
	for (let i = 0; i < groupId.length; i++) {
		hash = ((hash << 5) - hash + groupId.charCodeAt(i)) | 0;
	}
	const dayOfYear = Math.floor(
		(now.getTime() - new Date(now.getFullYear(), 0, 0).getTime()) / 86400000,
	);
	const dailySeed = Math.abs((hash + dayOfYear * 7919) | 0);
	return (dailySeed % 240) * 60 * 1000;
}

function weightedPick(
	hours: Array<{ hour: number; weightedScore?: number; confidence?: number }>,
): number | null {
	if (hours.length === 0) return null;
	const weights = hours.map((hour) =>
		Math.max(1, (hour.weightedScore ?? 0) * Math.max(0.1, hour.confidence ?? 0.1)),
	);
	const total = weights.reduce((sum, weight) => sum + weight, 0);
	let cursor = Math.random() * total;
	for (let i = 0; i < hours.length; i++) {
		cursor -= weights[i]!;
		if (cursor <= 0) return hours[i]!.hour;
	}
	return hours[hours.length - 1]!.hour;
}

function pickAccountAwareHour(input: {
	slot: AccountAwareTimingSlot;
	profile?: AccountTimingProfile | undefined;
	insights?: TimingInsights | undefined;
	activeHours: number[];
}): AccountTimingSelection {
	const profile = input.profile;
	const primaryHours = THREADS_GLOBAL_PRIMARY_HOURS.filter((hour) =>
		input.activeHours.includes(hour),
	);
	const secondaryHours = THREADS_GLOBAL_SECONDARY_HOURS.filter((hour) =>
		input.activeHours.includes(hour),
	);
	const globalHours = [...primaryHours, ...secondaryHours];
	const fallbackHours =
		globalHours.length > 0 ? globalHours : input.activeHours.length > 0 ? input.activeHours : [12];

	if (input.slot.warmupPolicy?.primaryHoursOnly) {
		const warmupHours = primaryHours.length > 0 ? primaryHours : fallbackHours;
		const hour = warmupHours[Math.floor(Math.random() * warmupHours.length)]!;
		return {
			selectedHour: hour,
			timingReason: "warmup_primary_hour",
			confidence: profile?.confidence ?? 0,
			fallbackSource: "warmup_primary",
			sampleSize: profile?.sampleSize ?? 0,
		};
	}

	const accountReady =
		!!profile &&
		profile.fallbackSource === "account_learned" &&
		profile.sampleSize >= 12 &&
		profile.confidence >= 0.45;
	const warmupConservative =
		!!input.slot.warmupPolicy &&
		(!profile || profile.confidence < 0.75 || profile.sampleSize < 12);
	if (!accountReady || warmupConservative) {
		const hour = fallbackHours[Math.floor(Math.random() * fallbackHours.length)]!;
		return {
			selectedHour: hour,
			timingReason: input.slot.warmupPolicy
				? "warmup_primary_hour"
				: "global_fallback_hour",
			confidence: profile?.confidence ?? 0,
			fallbackSource: profile?.fallbackSource ?? "global_fallback",
			sampleSize: profile?.sampleSize ?? 0,
		};
	}

	const proven = profile.provenHours.filter((hour) =>
		input.activeHours.includes(hour.hour),
	);
	const provenHourSet = new Set(proven.map((hour) => hour.hour));
	const exploration = [
		...profile.explorationHours.filter((hour) =>
			input.activeHours.includes(hour.hour),
		),
		...fallbackHours
			.filter((hour) => !provenHourSet.has(hour))
			.map((hour) => ({ hour, weightedScore: 1, confidence: 0.2 })),
	];
	const randomRoll = Math.random();
	if (proven.length > 0 && randomRoll < 0.65) {
		return {
			selectedHour: weightedPick(proven) ?? proven[0]!.hour,
			timingReason: "account_proven_hour",
			confidence: profile.confidence,
			fallbackSource: profile.fallbackSource,
			sampleSize: profile.sampleSize,
		};
	}
	if (exploration.length > 0 && randomRoll < 0.87) {
		return {
			selectedHour: weightedPick(exploration) ?? exploration[0]!.hour,
			timingReason: "account_exploration_hour",
			confidence: profile.confidence,
			fallbackSource: profile.fallbackSource,
			sampleSize: profile.sampleSize,
		};
	}
	const hour =
		input.activeHours[Math.floor(Math.random() * input.activeHours.length)] ??
		fallbackHours[0]!;
	return {
		selectedHour: hour,
		timingReason: "random_human_hour",
		confidence: profile.confidence,
		fallbackSource: profile.fallbackSource,
		sampleSize: profile.sampleSize,
	};
}

/**
 * Account-aware timing for queue fill. This keeps the legacy group scheduler
 * intact, but lets pre-assigned account slots bias their intended `scheduled_for`
 * toward hours that have actually worked for that account.
 */
export function calculateAccountAwareNaturalPostTimes(input: {
	plannedSlots: AccountAwareTimingSlot[];
	config: AutoPostConfig;
	groupId?: string | undefined;
	groupAccountCount?: number | undefined;
	insights?: TimingInsights | undefined;
	platform?: "threads" | "instagram" | "both" | undefined;
	accountProfiles?: Map<string, AccountTimingProfile> | undefined;
}): AccountAwareScheduledTime[] {
	const count = input.plannedSlots.length;
	if (count === 0) return [];
	if (input.platform !== "threads") {
		return calculateNaturalPostTimes(
			count,
			input.config,
			input.groupId,
			input.groupAccountCount,
			input.insights,
			input.platform,
		).map((scheduledFor) => ({
			scheduledFor,
			timing: {
				selectedHour: getZonedParts(
					new Date(scheduledFor),
					input.insights?.timezone,
				).hour,
				timingReason: "global_fallback_hour",
				confidence: 0,
				fallbackSource: "legacy_platform_timing",
				sampleSize: 0,
			},
		}));
	}

	const now = new Date();
	const groupOffset = getGroupOffsetMs(input.groupId, now);
	const globalTz = safeTimeZone(input.insights?.timezone);
	const globalActiveStart = input.insights?.activeHoursStart ?? 0;
	const globalActiveEnd = input.insights?.activeHoursEnd ?? 24;
	const todayByTz = new Map<string, Pick<ZonedParts, "year" | "month" | "day">>();
	const lastByAccount = new Map<string, Date>();
	const usedIsoMinutes = new Set<string>();
	const selections: AccountAwareScheduledTime[] = [];

	for (let i = 0; i < input.plannedSlots.length; i++) {
		const slot = input.plannedSlots[i]!;
		const tz = safeTimeZone(slot.timezone ?? globalTz);
		const activeStart = slot.activeHoursStart ?? globalActiveStart;
		const activeEnd = slot.activeHoursEnd ?? globalActiveEnd;
		const activeHours = getActiveHours(activeStart, activeEnd);
		const today = todayByTz.get(tz) ?? getZonedParts(now, tz);
		todayByTz.set(tz, today);
		const timing = pickAccountAwareHour({
			slot,
			profile: input.accountProfiles?.get(slot.accountId),
			insights: input.insights,
			activeHours,
		});
		let scheduled = new Date(
			zonedDateToUtc(
				today,
				timing.selectedHour,
				Math.floor(Math.random() * 59),
				Math.floor(Math.random() * 60),
				tz,
			).getTime() + groupOffset,
		);
		if (scheduled.getTime() <= now.getTime()) {
			const tomorrow = addCalendarDays(today, 1);
			scheduled = new Date(
				zonedDateToUtc(
					tomorrow,
					timing.selectedHour,
					Math.floor(Math.random() * 59),
					Math.floor(Math.random() * 60),
					tz,
				).getTime() + groupOffset,
			);
		}
		scheduled = new Date(
			scheduled.getTime() + (Math.random() - 0.5) * 20 * 60 * 1000,
		);

		const minIntervalMinutes = Math.max(30, slot.minIntervalMinutes ?? 30);
		const previous = lastByAccount.get(slot.accountId);
		if (
			previous &&
			scheduled.getTime() - previous.getTime() < minIntervalMinutes * 60_000
		) {
			scheduled = new Date(
				previous.getTime() +
					minIntervalMinutes * 60_000 +
					Math.random() * 10 * 60_000,
			);
		}
		scheduled = moveToNextActiveWindow(
			scheduled,
			tz,
			activeStart,
			activeEnd,
		);
		let isoMinute = scheduled.toISOString().slice(0, 16);
		while (usedIsoMinutes.has(isoMinute)) {
			scheduled = moveToNextActiveWindow(
				new Date(scheduled.getTime() + 60_000 + Math.random() * 30_000),
				tz,
				activeStart,
				activeEnd,
			);
			isoMinute = scheduled.toISOString().slice(0, 16);
		}
		usedIsoMinutes.add(isoMinute);
		lastByAccount.set(slot.accountId, scheduled);
		const selectedHour = getZonedParts(scheduled, tz).hour;
		selections.push({
			scheduledFor: scheduled.toISOString(),
			timing: {
				...timing,
				selectedHour,
			},
		});
	}
	return selections;
}

// ============================================================================
// Queue Count Helper
// ============================================================================

export async function countPendingPosts(
	workspaceId: string,
	groupId?: string,
): Promise<number> {
	let query = db()
		.from("auto_post_queue")
		.select("*", { count: "exact", head: true })
		.eq("workspace_id", workspaceId)
		.in("status", ["pending", "queued"]);

	// Per-group count so each group fills independently
	if (groupId) {
		query = query.eq("group_id", groupId);
	}

	const { count, error } = await query;

	if (error) {
		logger.error("Error counting pending posts", {
			error: error instanceof Error ? error.message : String(error),
		});
		return 999;
	}

	return count || 0;
}
