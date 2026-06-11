/**
 * Post Limits Utility
 *
 * Tracks daily publishing limits per platform:
 * - Instagram: 25 content publishes/day
 * - Threads: 250 posts/day
 */

import { dailyPublishLimit } from "@/lib/socialPlatform";
import { supabase } from "@/services/supabase";
import type { Platform } from "@/types/platform";

export interface PostLimitStatus {
	used: number;
	limit: number;
	remaining: number;
	/** "green" (>50%), "yellow" (25-50%), "red" (<25%) */
	color: "green" | "yellow" | "red";
	platform: Platform;
}

/**
 * Get today's published + scheduled post count for an account and return limit status.
 * Accepts an optional timezone to calculate "today" in the user's timezone.
 */
export async function getPostLimitStatus(
	accountId: string,
	platform: Platform,
	timezone?: string,
): Promise<PostLimitStatus> {
	if (!accountId || accountId === "ALL") {
		const limit = dailyPublishLimit(platform);
		return {
			used: 0,
			limit,
			remaining: limit,
			color: "green" as const,
			platform,
		};
	}

	// Calculate today's start in the user's timezone
	const now = new Date();
	let todayStart: Date;
	// #706: Validate timezone is a valid IANA timezone
	let validTimezone = timezone;
	if (timezone) {
		try {
			Intl.DateTimeFormat(undefined, { timeZone: timezone });
		} catch {
			validTimezone = undefined; // Fall back to local timezone
		}
	}
	if (validTimezone) {
		const parts = new Intl.DateTimeFormat("en-US", {
			timeZone: validTimezone,
			year: "numeric",
			month: "2-digit",
			day: "2-digit",
		}).formatToParts(now);
		const year = parseInt(
			parts.find((p) => p.type === "year")?.value ?? "0",
			10,
		);
		const month =
			parseInt(parts.find((p) => p.type === "month")?.value ?? "0", 10) - 1;
		const day = parseInt(parts.find((p) => p.type === "day")?.value ?? "0", 10);
		const localMidnight = new Date(year, month, day);
		const tzOffset = localMidnight.getTimezoneOffset();
		const targetDate = new Date(
			now.toLocaleString("en-US", { timeZone: validTimezone }),
		);
		const targetOffset = (now.getTime() - targetDate.getTime()) / 60000;
		todayStart = new Date(
			localMidnight.getTime() + (tzOffset + targetOffset) * 60000,
		);
	} else {
		todayStart = new Date();
		todayStart.setHours(0, 0, 0, 0);
	}

	// Count both published and scheduled posts for today
	const { count: publishedCount } = await supabase
		.from("posts")
		.select("id", { count: "exact", head: true })
		.eq("account_id", accountId)
		.eq("platform", platform)
		.eq("status", "published")
		.gte("published_at", todayStart.toISOString());

	const { count: scheduledCount } = await supabase
		.from("posts")
		.select("id", { count: "exact", head: true })
		.eq("account_id", accountId)
		.eq("platform", platform)
		.eq("status", "scheduled")
		.gte("scheduled_for", todayStart.toISOString());

	const used = (publishedCount ?? 0) + (scheduledCount ?? 0);
	const limit = dailyPublishLimit(platform);
	const remaining = Math.max(0, limit - used);
	const pct = remaining / limit;

	return {
		used,
		limit,
		remaining,
		color: pct > 0.5 ? "green" : pct > 0.25 ? "yellow" : "red",
		platform,
	};
}
