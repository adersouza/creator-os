// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
/**
 * Best Times to Post — data-driven analysis
 *
 * Queries the posts table, groups by day-of-week + hour,
 * calculates average engagement rate per slot, returns top slots.
 * Also supports audience-based timing from IG online_followers data.
 */

import type { Platform } from "@/types/platform";
import { supabase } from "@/services/supabase";

export interface BestTimeSlot {
	day: string;
	hour: string;
	score: number; // 0-1 normalized
}

export interface AudienceHourlyData {
	hours: Record<string, number>;
	timezone: string;
	period: string;
}

export interface AudienceBestTimeSlot extends BestTimeSlot {
	followersOnline: number;
	source: "audience";
}

const DAYS = [
	"Sunday",
	"Monday",
	"Tuesday",
	"Wednesday",
	"Thursday",
	"Friday",
	"Saturday",
];

function formatHour(h: number): string {
	if (h === 0) return "12:00 AM";
	if (h === 12) return "12:00 PM";
	return h < 12 ? `${h}:00 AM` : `${h - 12}:00 PM`;
}

/**
 * Compute best posting times from actual post data.
 * Returns null if fewer than 10 published posts exist (insufficient data).
 */
export async function computeBestTimes(
	accountId: string,
	platform?: Platform,
): Promise<BestTimeSlot[] | null> {
	if (!accountId || accountId === "ALL") return null;
	let query = supabase
		.from("posts")
		.select(
			"published_at, engagement_rate, views_count, likes_count, replies_count",
		)
		.eq("account_id", accountId)
		.eq("status", "published")
		.not("published_at", "is", null);

	if (platform) {
		query = query.eq("platform", platform);
	}

	const { data: posts, error } = await query;

	if (error || !posts || posts.length < 10) {
		return null;
	}

	// Group by (dayOfWeek, hour) → engagement scores
	const buckets = new Map<string, number[]>();

	for (const post of posts) {
		const dt = new Date(post.published_at ?? "");
		const day = dt.getDay(); // 0-6
		const hour = dt.getHours(); // 0-23
		const key = `${day}-${hour}`;
		// Use engagement_rate if available, otherwise compute proxy from views/likes
		const score =
			post.engagement_rate ??
			((post.views_count ?? 0) +
				(post.likes_count ?? 0) * 10 +
				(post.replies_count ?? 0) * 20 ||
				1);
		const arr = buckets.get(key);
		if (arr) {
			arr.push(score);
		} else {
			buckets.set(key, [score]);
		}
	}

	// Compute averages
	const slots: { day: number; hour: number; avg: number }[] = [];
	for (const [key, rates] of buckets) {
		const [d, h] = key.split("-").map(Number);
		const avg = rates.reduce((a, b) => a + b, 0) / rates.length;
		slots.push({ day: d!, hour: h!, avg });
	}

	if (slots.length === 0) return null;

	// Sort descending by avg engagement
	slots.sort((a, b) => b.avg - a.avg);

	// Normalize scores to 0-1 range
	const maxAvg = slots[0]!.avg;
	const minAvg = slots[slots.length - 1]!.avg;
	const range = maxAvg - minAvg || 1;

	return slots.slice(0, 7).map((s) => ({
			day: DAYS[s.day] ?? "Unknown",
		hour: formatHour(s.hour),
		score: range > 0 ? (s.avg - minAvg) / range : 1,
	}));
}

/**
 * Compute best posting times from already-loaded posts (client-side, no DB query).
 * Used for multi-account "ALL" view where per-account DB query can't run.
 * Uses engagement proxy (views + likes + replies) instead of engagement_rate column.
 * Returns null if fewer than 10 published posts with timestamps exist.
 */
export function computeBestTimesFromPosts(
	posts: {
		publishedAt?: string | Date | { toDate?: () => Date | undefined } | null | undefined;
		performance?: {
            			views?: number | undefined;
            			likes?: number | undefined;
            			replies?: number | undefined;
            			reposts?: number | undefined;
            			quotes?: number | undefined;
            		} | null | undefined;
	}[],
): BestTimeSlot[] | null {
	// Extract posts with valid dates and any engagement signal
	const valid: { day: number; hour: number; engagement: number }[] = [];
	for (const p of posts) {
		if (!p.publishedAt) continue;
		const raw = p.publishedAt;
			const d =
				typeof raw === "object" &&
				raw !== null &&
				"toDate" in raw &&
				typeof raw.toDate === "function"
					? (raw.toDate() ?? new Date(Number.NaN))
					: new Date(raw as string | number);
		if (Number.isNaN(d.getTime())) continue;
		const perf = p.performance;
		const engagement =
			(perf?.views ?? 0) +
			(perf?.likes ?? 0) * 10 +
			(perf?.replies ?? 0) * 20 +
			(perf?.reposts ?? 0) * 15 +
			(perf?.quotes ?? 0) * 15;
		valid.push({ day: d.getDay(), hour: d.getHours(), engagement });
	}

	if (valid.length < 10) return null;

	// Group by (dayOfWeek, hour) → engagement values
	const buckets = new Map<string, number[]>();
	for (const v of valid) {
		const key = `${v.day}-${v.hour}`;
		const arr = buckets.get(key);
		if (arr) {
			arr.push(v.engagement);
		} else {
			buckets.set(key, [v.engagement]);
		}
	}

	// Compute averages
	const slots: { day: number; hour: number; avg: number }[] = [];
	for (const [key, rates] of buckets) {
		const [d, h] = key.split("-").map(Number);
		const avg = rates.reduce((a, b) => a + b, 0) / rates.length;
		slots.push({ day: d!, hour: h!, avg });
	}

	if (slots.length === 0) return null;

	// Sort descending by avg engagement
	slots.sort((a, b) => b.avg - a.avg);

	// Normalize scores to 0-1 range
	const maxAvg = slots[0]!.avg;
	const minAvg = slots[slots.length - 1]!.avg;
	const range = maxAvg - minAvg || 1;

	return slots.slice(0, 7).map((s) => ({
			day: DAYS[s.day] ?? "Unknown",
		hour: formatHour(s.hour),
		score: range > 0 ? (s.avg - minAvg) / range : 1,
	}));
}

/**
 * Compute best posting times from real audience online_followers data.
 * Fetches from the online-followers API endpoint.
 * Returns top 5 hours sorted by follower count + full 24-hour array.
 */
export async function computeBestTimesFromAudience(
	accountId: string,
): Promise<{ topSlots: AudienceBestTimeSlot[]; hourlyData: number[] } | null> {
	if (!accountId || accountId === "ALL") return null;
	try {
		// Fetch from account_analytics (ig_online_followers JSONB)
		const { data, error } = await supabase
			.from("account_analytics")
			.select("ig_online_followers")
			.eq("account_id", accountId)
			.not("ig_online_followers", "is", null)
			.order("date", { ascending: false })
			.limit(7);

		if (error || !data || data.length === 0) return null;

		// Average across available days
		const hourlyTotals = new Array(24).fill(0);
		let dayCount = 0;
		for (const row of data as {
			ig_online_followers?: Record<string, number> | undefined;
		}[]) {
			if (!row.ig_online_followers) continue;
			const hours = row.ig_online_followers as Record<string, number>;
			for (let h = 0; h < 24; h++) {
				hourlyTotals[h] += hours[String(h)] || 0;
			}
			dayCount++;
		}

		if (dayCount === 0) return null;

		const hourlyAvg = hourlyTotals.map((t) => Math.round(t / dayCount));
		const maxVal = Math.max(...hourlyAvg, 1);
		const minVal = Math.min(...hourlyAvg);
		const range = maxVal - minVal || 1;

		// Build sorted slots
		const sortedHours = hourlyAvg
			.map((val, h) => ({ hour: h, val }))
			.sort((a, b) => b.val - a.val);

		// Get current day name for display (audience data is daily average, show "Every day")
		const topSlots: AudienceBestTimeSlot[] = sortedHours
			.slice(0, 7)
			.map((s) => ({
				day: "Every day",
				hour: formatHour(s.hour),
				score: (s.val - minVal) / range,
				followersOnline: s.val,
				source: "audience",
			}));

		return { topSlots, hourlyData: hourlyAvg };
	} catch {
		return null;
	}
}
