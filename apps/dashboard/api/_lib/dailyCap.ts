/**
 * Daily Publish Cap
 *
 * Limits agent/user to 250 published + scheduled posts per account per UTC day.
 * Fail-closed: if the DB check errors, we block the publish as safety measure.
 */

import { logger } from "./logger.js";
import { getSupabase } from "./supabase.js";

export const DAILY_CAP = 250;

export interface DailyCapResult {
	allowed: boolean;
	used: number;
	limit: number;
}

/**
 * Returns whether an account is under its daily publish cap.
 *
 * @param accountId  - The Threads account_id or Instagram instagram_account_id
 * @param platform   - "threads" | "instagram" (determines which column to query)
 * @param targetDate - Optional: count posts scheduled for this UTC day instead of today
 */
export async function checkDailyCap(
	accountId: string,
	platform: "threads" | "instagram",
	targetDate?: Date,
): Promise<DailyCapResult> {
	const dayStart = new Date(targetDate ?? new Date());
	dayStart.setUTCHours(0, 0, 0, 0);
	const dayEnd = new Date(dayStart);
	dayEnd.setUTCDate(dayEnd.getUTCDate() + 1);

	const accountCol =
		platform === "instagram" ? "instagram_account_id" : "account_id";

	// Scheduling path: count posts scheduled for the target day
	// Publish path: count posts already published today (by published_at, not created_at)
	// Using created_at would over-count bulk-created posts scheduled for future days
	const dateCol = targetDate ? "scheduled_for" : "published_at";
	const statuses = targetDate ? ["published", "scheduled"] : ["published"];

	const { count, error } = await getSupabase()
		.from("posts")
		.select("*", { count: "exact", head: true })
		.eq(accountCol, accountId)
		.in("status", statuses)
		.gte(dateCol, dayStart.toISOString())
		.lt(dateCol, dayEnd.toISOString());

	if (error) {
		// Fail-closed: block publishing if we can't verify the cap
		logger.warn("Daily cap check failed — blocking publish as safety measure", {
			accountId,
			platform,
			error: error.message,
		});
		return { allowed: false, used: DAILY_CAP, limit: DAILY_CAP };
	}

	const used = count ?? 0;
	return { allowed: used < DAILY_CAP, used, limit: DAILY_CAP };
}
