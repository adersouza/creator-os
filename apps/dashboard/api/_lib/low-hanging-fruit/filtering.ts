/**
 * Recommendation filtering — deprioritization, dismissal, and snooze logic.
 * Handles Redis-based category deprioritization, snoozing, and DB-based
 * "will_try_later" dismissals with resurface scheduling.
 */

import { logger } from "../logger.js";
import { getRedis } from "../redis.js";
import type { Recommendation } from "./shared.js";
import { db } from "./shared.js";

/**
 * Filters out recs from deprioritized categories (Redis) and
 * recs dismissed with "will_try_later" that haven't resurfaced yet.
 */
export async function filterDeprioritizedAndDismissed(
	userId: string,
	accountId: string,
	recs: Recommendation[],
): Promise<Recommendation[]> {
	try {
		const redis = getRedis();

		// Check which categories are deprioritized or snoozed (30-day snooze)
		const categories = [...new Set(recs.map((r) => r.category))];
		const deprioritized = new Set<string>();

		if (categories.length > 0) {
			const depKeys = categories.map((c) => `rec:deprioritize:${userId}:${c}`);
			const snoozeKeys = categories.map((c) => `rec:snooze:${userId}:${c}`);
			const allKeys = [...depKeys, ...snoozeKeys];
			const values = await redis.mget<(string | null)[]>(...allKeys);
			categories.forEach((cat, i) => {
				// deprioritize check (first half of values)
				if (values[i]) deprioritized.add(cat);
				// snooze check (second half of values)
				if (values[i + categories.length]) deprioritized.add(cat);
			});
		}

		// Check "will_try_later" dismissals that haven't resurfaced yet
		const { data: activeDismissals } = await db()
			.from("recommendation_dismissals")
			.select("rec_id, resurface_at")
			.eq("user_id", userId)
			.eq("account_id", accountId)
			.eq("reason", "will_try_later")
			.not("resurface_at", "is", null);

		const hiddenRecIds = new Set<string>();
		const now = new Date();
		for (const d of activeDismissals ?? []) {
			if (d.resurface_at && new Date(d.resurface_at) > now) {
				hiddenRecIds.add(d.rec_id);
			}
		}

		return recs.filter((r) => {
			if (deprioritized.has(r.category)) return false;
			if (hiddenRecIds.has(r.id)) return false;
			return true;
		});
	} catch (err) {
		logger.warn("[lowHangingFruit] Filter check failed, returning unfiltered", {
			error: String(err),
		});
		return recs;
	}
}
