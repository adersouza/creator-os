/**
 * Auto-Post Service — timing + scheduling logic.
 */

import { createServiceLogger, supabase } from "../api/shared";
import { getAutoPostConfig } from "./config";
import {
	getCurrentDayInTimezone,
	getCurrentHourInTimezone,
	getDateForHourInTimezone,
	getSupabaseUserId,
	getWorkspaceId,
} from "./internal";
import { getAutoPostState } from "./state";
import type { AutoPostConfig, AutoPostState } from "./types";

const log = createServiceLogger("autoPostService.scheduler");

// Re-export timezone helpers so the public API shape is preserved.
export { getCurrentDayInTimezone, getCurrentHourInTimezone };

/**
 * Check if auto-posting should be allowed right now
 * (based on active hours, weekend settings, rate limits)
 *
 * NOTE: This function is used for UI display only. It does NOT check subscription
 * tier (Empire) or account suspension status. Tier enforcement happens at the API
 * level in api/auto-post.ts (requireEmpireTier). Account suspension is checked by
 * the cron worker (auto-post-worker.ts) before each post attempt.
 */
export const canAutoPostNow = async (
	config: AutoPostConfig,
	state: AutoPostState,
	accountId: string,
): Promise<{ allowed: boolean; reason?: string | undefined }> => {
	const now = new Date();
	const timezone = config.timezone || "UTC";

	// Get current hour and day in user's timezone
	const currentHour = getCurrentHourInTimezone(timezone);
	const currentDay = getCurrentDayInTimezone(timezone);
	const isWeekend = currentDay === 0 || currentDay === 6;

	// Check weekend setting
	if (isWeekend && !config.enableWeekends) {
		return { allowed: false, reason: "Weekend posting disabled" };
	}

	// Check if 24/7 mode (end=24 or start=0 with end=0)
	const is24_7 =
		config.activeHoursEnd === 24 ||
		(config.activeHoursStart === 0 && config.activeHoursEnd === 0);

	// Check active hours (skip check in 24/7 mode)
	if (!is24_7) {
		const effectiveEnd =
			config.activeHoursEnd === 0 ? 24 : config.activeHoursEnd;
		if (currentHour < config.activeHoursStart || currentHour >= effectiveEnd) {
			return {
				allowed: false,
				reason: `Outside active hours (${config.activeHoursStart}:00-${effectiveEnd === 24 ? "00" : effectiveEnd}:00 ${timezone})`,
			};
		}
	}

	// Check per-account daily limit (max 15 per account for safety)
	const accountPostCount = state.accountPostCounts[accountId] || 0;
	if (accountPostCount >= 15) {
		return { allowed: false, reason: "Account daily limit reached (15 posts)" };
	}

	// Check minimum interval since last post
	if (state.lastPostTime) {
		const minutesSinceLastPost =
			(now.getTime() - state.lastPostTime.getTime()) / 60000;
		if (minutesSinceLastPost < config.minIntervalMinutes) {
			return {
				allowed: false,
				reason: `Minimum interval not met (${Math.ceil(config.minIntervalMinutes - minutesSinceLastPost)} min remaining)`,
			};
		}
	}

	return { allowed: true };
};

/**
 * Recalculate nextPostTime based on current config active hours
 * Called when config changes while auto-poster is enabled
 */
export const recalculateNextPostTime = async (
	workspaceId?: string,
): Promise<Date | null> => {
	const userId = await getSupabaseUserId();
	if (!userId) return null;

	try {
		const wsId = workspaceId || (await getWorkspaceId());
		if (!wsId) return null;

		const config = await getAutoPostConfig(wsId);
		if (!config.enabled) return null;

		const timezone = config.timezone || "UTC";
		const state = await getAutoPostState(wsId);

		// Calculate base next post time
		const range = config.maxIntervalMinutes - config.minIntervalMinutes;
		const randomMinutes = config.minIntervalMinutes + Math.random() * range;
		const baseTime = state.lastPostTime
			? new Date(state.lastPostTime.getTime() + randomMinutes * 60 * 1000)
			: new Date(Date.now() + randomMinutes * 60 * 1000);

		let nextPostTime = baseTime > new Date() ? baseTime : new Date();

		// Ensure nextPostTime is within active hours (using user's timezone)
		const is24_7 =
			config.activeHoursEnd === 24 ||
			(config.activeHoursStart === 0 && config.activeHoursEnd === 0);

		if (!is24_7) {
			const effectiveEnd =
				config.activeHoursEnd === 0 ? 24 : config.activeHoursEnd;
			// Get current hour in user's timezone
			const hourInUserTz = getCurrentHourInTimezone(timezone);

			if (hourInUserTz >= effectiveEnd) {
				// Jump to next day's start hour in user's timezone
				nextPostTime = getDateForHourInTimezone(
					config.activeHoursStart,
					timezone,
					1,
				);
				nextPostTime = new Date(
					nextPostTime.getTime() + Math.random() * 30 * 60 * 1000,
				);
			} else if (hourInUserTz < config.activeHoursStart) {
				// Jump to today's start hour in user's timezone
				nextPostTime = getDateForHourInTimezone(
					config.activeHoursStart,
					timezone,
					0,
				);
				nextPostTime = new Date(
					nextPostTime.getTime() + Math.random() * 30 * 60 * 1000,
				);
			}
		}

		// Save to database
		await supabase.from("auto_post_state").upsert(
			{
				workspace_id: wsId,
				next_post_time: nextPostTime.toISOString(),
				updated_at: new Date().toISOString(),
			},
			{ onConflict: "workspace_id" },
		);

		log.debug(`Recalculated nextPostTime: ${nextPostTime.toISOString()}`);
		return nextPostTime;
	} catch (error) {
		log.error("Failed to recalculate nextPostTime:", error);
		return null;
	}
};

/**
 * Calculate next random interval for human-like posting
 * Interval is always WITHIN the configured min/max bounds
 */
export const getRandomInterval = (config: AutoPostConfig): number => {
	const range = config.maxIntervalMinutes - config.minIntervalMinutes;
	const randomMinutes = config.minIntervalMinutes + Math.random() * range;
	// Clamp to max to ensure we never exceed user's configured interval
	const clampedMinutes = Math.min(randomMinutes, config.maxIntervalMinutes);
	return Math.round(clampedMinutes * 60 * 1000); // Return milliseconds
};

/**
 * Get media for a post based on config settings and group
 * Uses the mediaSource setting to determine where to pull media from
 * Returns { media, warning } - warning set if fallback used or no media available
 */
export const getMediaForPost = async (
	config: AutoPostConfig,
	groupId?: string,
): Promise<{ mediaUrl: string | null; warning?: string | undefined }> => {
	// Import media service dynamically to avoid circular deps
	const { getRandomMediaForGroup, getRandomMedia } = await import(
		"../mediaService"
	);

	// Check if we should even try to attach media
	const shouldAttachMedia = Math.random() * 100 < config.mediaAttachmentChance;
	if (!shouldAttachMedia) {
		return { mediaUrl: null };
	}

	const mediaSource = config.mediaSource || "global";

	try {
		// Global mode: pull from entire library
		if (mediaSource === "global") {
			const media = await getRandomMedia(true);
			return { mediaUrl: media?.url || null };
		}

		// Group-specific mode: only pull from group folder
		if (mediaSource === "group-specific") {
			if (!groupId) {
				return {
					mediaUrl: null,
					warning: "No group specified for group-specific media",
				};
			}

			const media = await getRandomMediaForGroup(groupId, true);
			if (!media) {
				return {
					mediaUrl: null,
					warning: `No media in group folder — posting text only`,
				};
			}
			return { mediaUrl: media.url };
		}

		// Mixed mode: prefer group, fallback to global
		if (mediaSource === "mixed") {
			if (groupId) {
				const groupMedia = await getRandomMediaForGroup(groupId, true);
				if (groupMedia) {
					return { mediaUrl: groupMedia.url };
				}
				// Fallback to global
				const globalMedia = await getRandomMedia(true);
				if (globalMedia) {
					return {
						mediaUrl: globalMedia.url,
						warning: "Using global media (no group media available)",
					};
				}
			} else {
				// No group, use global
				const media = await getRandomMedia(true);
				return { mediaUrl: media?.url || null };
			}
		}

		return { mediaUrl: null };
	} catch (error) {
		log.error("Failed to get media for post:", error);
		return { mediaUrl: null, warning: "Failed to fetch media" };
	}
};
