// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
import { createNotification } from "./createNotification.js";
import { logger } from "./logger.js";
import type { Platform } from "./platform.js";
import { getSupabase } from "./supabase.js";

const db = () => getSupabase();

export async function generateDailyInsight(
	accountId: string,
	platform: Platform,
	userId: string,
): Promise<void> {
	try {
		// Check time — only send between 9 AM - 9 PM UTC
		const hour = new Date().getUTCHours();
		if (hour < 9 || hour >= 21) return;

		// Max 1 daily insight per user per day
		const todayStart = new Date();
		todayStart.setUTCHours(0, 0, 0, 0);

		// #608: Dedup scoped to platform + account — not just user
		const { data: existing } = await db()
			.from("notifications")
			.select("id, data")
			.eq("user_id", userId)
			.eq("type", "daily_insight")
			.gte("created_at", todayStart.toISOString())
			.limit(10);

		if (existing && existing.length > 0) {
			// Check if this specific account already got an insight today
			// (notification data contains accountId)
			const alreadySent = (
				existing as unknown as Array<{ data?: unknown | undefined }>
			).some((n) => {
				try {
					const data = typeof n.data === "string" ? JSON.parse(n.data) : n.data;
					return (data as { accountId?: string | undefined })?.accountId === accountId;
				} catch {
					return false;
				}
			});
			if (alreadySent) return;
		}

		// Compare the last two complete UTC days. Avoid comparing a partial
		// current day against a complete previous day.
		const yesterday = new Date(Date.now() - 86400000)
			.toISOString()
			.split("T")[0]!;
		const priorDay = new Date(Date.now() - 2 * 86400000)
			.toISOString()
			.split("T")[0]!;

		const { data: analytics } = await db()
			.from("account_analytics")
			.select("date, engagement_rate, follower_growth")
			.eq("account_id", accountId)
			.in("date", [yesterday!, priorDay!])
			.order("date", { ascending: false });

		const yesterdayData = analytics?.find(
			(r: { date: string }) => r.date === yesterday,
		);
		const priorData = analytics?.find(
			(r: { date: string }) => r.date === priorDay,
		);

		let insight: string | null = null;

		// Check for significant engagement change
		if (yesterdayData && priorData) {
			const yestEng = yesterdayData.engagement_rate ?? 0;
			const priorEng = priorData.engagement_rate ?? 0;
			if (priorEng > 0) {
				const change = ((yestEng - priorEng) / priorEng) * 100;
				if (Math.abs(change) >= 20) {
					const dir = change > 0 ? "up" : "down";
					insight = `📊 Your engagement is ${dir} ${Math.abs(change).toFixed(0)}% compared to yesterday.`;
				}
			}
		}

		// Check for posting gap (no posts in 3+ days)
		if (!insight) {
			const threeDaysAgo = new Date(Date.now() - 3 * 86400000).toISOString();
			let postQuery = db()
				.from("posts")
				.select("id", { count: "exact", head: true })
				.eq("status", "published")
				.gte("published_at", threeDaysAgo);
			postQuery =
				platform === "instagram"
					? postQuery.eq("instagram_account_id", accountId)
					: postQuery.eq("account_id", accountId);
			const { count } = await postQuery;

			if (count === 0) {
				insight =
					"📝 You haven't posted in 3+ days. Staying consistent helps keep your audience engaged!";
			}
		}

		// Follower growth
		if (!insight && yesterdayData?.follower_growth) {
			const growth = yesterdayData.follower_growth;
			if (growth > 0) {
				insight = `🚀 You gained ${growth} new follower${growth !== 1 ? "s" : ""} today!`;
			}
		}

		if (!insight) return;

		await createNotification({
			userId,
			type: "daily_insight",
			title: "Daily Insight",
			message: insight,
			data: { accountId, platform },
		});

		logger.info("Daily insight sent", { userId, accountId, platform });
	} catch (err: unknown) {
		logger.warn("generateDailyInsight failed (non-fatal)", {
			userId,
			accountId,
			error: err instanceof Error ? err.message : String(err),
		});
	}
}
