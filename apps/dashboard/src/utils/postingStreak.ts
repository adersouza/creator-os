// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
/**
 * Posting streak utilities — compute consecutive days with posts
 * and small "which days posted" bitmaps for dashboard streak widgets.
 */

import { parseDate } from "./parseDate";

interface PostLike {
	publishedAt?: string | Date | { toDate?: () => Date | undefined } | null | undefined;
	status?: string | undefined;
}

/**
 * Compute the current posting streak (consecutive days with >=1 published post,
 * counting backwards from today).
 */
export function computePostingStreak(posts: PostLike[]): number {
	const published = posts.filter(
		(p) => p.publishedAt && (p.status === "published" || !p.status),
	);
	if (published.length === 0) return 0;

	// Build a set of date strings (YYYY-MM-DD) that have posts
	const datesWithPosts = new Set<string>();
	for (const p of published) {
		if (!p.publishedAt) continue;
		const d = parseDate(p.publishedAt);
		if (!Number.isNaN(d.getTime())) {
			datesWithPosts.add(d.toISOString().split("T")[0]!);
		}
	}

	// Walk backwards from today
	let streak = 0;
	const day = new Date();
	day.setHours(0, 0, 0, 0);

	// Allow today to not have a post yet (start from yesterday if today is empty)
	const todayStr = day.toISOString().split("T")[0]!;
	if (!datesWithPosts.has(todayStr!)) {
		day.setDate(day.getDate() - 1);
	}

	for (let i = 0; i < 365; i++) {
		const dateStr = day.toISOString().split("T")[0]!;
		if (datesWithPosts.has(dateStr!)) {
			streak++;
			day.setDate(day.getDate() - 1);
		} else {
			break;
		}
	}

	return streak;
}

/**
 * Compute which days of the current week (Mon-Sun) have posts.
 * Returns a boolean[7] array where index 0 = Monday, 6 = Sunday.
 */
export function computeWeekDaysPosted(posts: PostLike[]): boolean[] {
	const published = posts.filter(
		(p) => p.publishedAt && (p.status === "published" || !p.status),
	);

	// Find this week's Monday
	const now = new Date();
	const dayOfWeek = now.getDay(); // 0=Sun, 1=Mon, ...
	const mondayOffset = dayOfWeek === 0 ? 6 : dayOfWeek - 1;
	const monday = new Date(now);
	monday.setDate(now.getDate() - mondayOffset);
	monday.setHours(0, 0, 0, 0);

	const result: boolean[] = [false, false, false, false, false, false, false];

	for (const p of published) {
		if (!p.publishedAt) continue;
		const d = parseDate(p.publishedAt);
		if (Number.isNaN(d.getTime())) continue;

		const diffMs = d.getTime() - monday.getTime();
		const diffDays = Math.floor(diffMs / 86400000);
		if (diffDays >= 0 && diffDays < 7) {
			result[diffDays] = true;
		}
	}

	return result;
}

/**
 * Compute which of the last `days` calendar days have posts.
 * Returns oldest → newest, so the final cell is today.
 */
export function computeRecentDaysPosted(posts: PostLike[], days = 14): boolean[] {
	const published = posts.filter(
		(p) => p.publishedAt && (p.status === "published" || !p.status),
	);

	const datesWithPosts = new Set<string>();
	for (const p of published) {
		if (!p.publishedAt) continue;
		const d = parseDate(p.publishedAt);
		if (!Number.isNaN(d.getTime())) {
			datesWithPosts.add(d.toISOString().split("T")[0]!);
		}
	}

	const result: boolean[] = [];
	const cursor = new Date();
	cursor.setHours(0, 0, 0, 0);
	cursor.setDate(cursor.getDate() - Math.max(0, days - 1));

	for (let i = 0; i < days; i += 1) {
		result.push(datesWithPosts.has(cursor.toISOString().split("T")[0]!));
		cursor.setDate(cursor.getDate() + 1);
	}

	return result;
}

/**
 * Split posts into current-period and previous-period buckets.
 * periodDays > 0: current = now-periodDays..now, previous = now-2*periodDays..now-periodDays
 * periodDays === 0 (all time): current = all posts, previous = empty
 */
export function splitPeriodPosts<T extends PostLike>(
	posts: T[],
	periodDays: number,
): { currentPeriod: T[]; previousPeriod: T[] } {
	if (periodDays === 0) {
		// All time: everything is "current", no comparison period
		const current = posts.filter((p) => {
			if (!p.publishedAt) return false;
			const d = parseDate(p.publishedAt);
			return !Number.isNaN(d.getTime());
		});
		return { currentPeriod: current, previousPeriod: [] };
	}

	const now = new Date();
	const periodMs = periodDays * 86400000;
	const currentStart = new Date(now.getTime() - periodMs);
	const previousStart = new Date(now.getTime() - periodMs * 2);

	const currentPeriod: T[] = [];
	const previousPeriod: T[] = [];

	for (const p of posts) {
		if (!p.publishedAt) continue;
		const d = parseDate(p.publishedAt);
		if (Number.isNaN(d.getTime())) continue;

		if (d >= currentStart) {
			currentPeriod.push(p);
		} else if (d >= previousStart) {
			previousPeriod.push(p);
		}
	}

	return { currentPeriod, previousPeriod };
}

/**
 * Split posts into this-week and previous-week buckets.
 */
export function splitWeeklyPosts<T extends PostLike>(
	posts: T[],
): { thisWeek: T[]; lastWeek: T[] } {
	const now = new Date();
	const dayOfWeek = now.getDay();
	const mondayOffset = dayOfWeek === 0 ? 6 : dayOfWeek - 1;

	const thisMonday = new Date(now);
	thisMonday.setDate(now.getDate() - mondayOffset);
	thisMonday.setHours(0, 0, 0, 0);

	const lastMonday = new Date(thisMonday);
	lastMonday.setDate(lastMonday.getDate() - 7);

	const thisWeek: T[] = [];
	const lastWeek: T[] = [];

	for (const p of posts) {
		if (!p.publishedAt) continue;
		const d = parseDate(p.publishedAt);
		if (Number.isNaN(d.getTime())) continue;

		if (d >= thisMonday) {
			thisWeek.push(p);
		} else if (d >= lastMonday) {
			lastWeek.push(p);
		}
	}

	return { thisWeek, lastWeek };
}
